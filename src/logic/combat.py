import discord
import asyncio
import logging
from discord.ext import commands
from discord import app_commands, ui
from src.utils.paths import COMBAT_STATE, PROFILES, ITEMS
from src.utils.json_utils import load_json, save_json
from src.database.characters import pkey


# ── Profile sync helpers ───────────────────────────────────────────────────────

def _load_profiles() -> dict:
    return load_json(PROFILES, default={})

def _save_profiles(data: dict):
    save_json(PROFILES, data)

def _pk(profiles: dict, uid) -> str:
    """Klíč profilu: pkey (uid:slot) když existuje, jinak holé uid (nemigrovaní)."""
    k = pkey(uid)
    return k if k in profiles else str(uid)

def _load_items_db() -> dict:
    return load_json(ITEMS, default={})

SOURCE_LABEL = {"zbran": "zbraň", "runa": "runa", "prostredi": "prostředí", "schopnost": "schopnost"}

def _bs():
    """Lazy import status/rune enginu (blacksmith). None když nedostupný."""
    try:
        from src.core.dnd import blacksmith
        return blacksmith
    except Exception:
        logging.getLogger(__name__).warning(
            "blacksmith modul nedostupný — statusy v boji vypnuty")
        return None

def _actor_uid(actor: str):
    """Z '<@123>' / '<@!123>' vytáhne int id, jinak None (NPC)."""
    if actor.startswith("<@"):
        digits = "".join(ch for ch in actor if ch.isdigit())
        return int(digits) if digits else None
    return None

def _writeback_player_state(uid: int, carrier: dict, bs) -> None:
    """Hráči zapíše hp_cur + statusy zpět do profilu a ubere kolo jeho nátěrům."""
    try:
        profiles = _load_profiles()
        p = profiles.get(_pk(profiles, uid))
        if not p:
            return
        p["hp_cur"]   = max(0, min(carrier.get("hp", 0), p.get("hp_max", 50)))
        p["statuses"] = carrier.get("statuses", [])
        if bs:
            bs.tick_coatings(p)
        _save_profiles(profiles)
    except Exception:
        logging.exception("[combat] writeback hp/statusů selhal")

def _compute_def_from_equipment(profile: dict, items_db: dict) -> int:
    """Spočítá celkový DEF z equipmentu hráče."""
    equipment = profile.get("equipment", {})
    seen  = set()
    total = 0
    for item_id in equipment.values():
        if item_id and item_id not in seen:
            seen.add(item_id)
            total += items_db.get(item_id, {}).get("def", 0)
    return total

def _sync_player_from_profile(mention: str, user_id: int) -> dict | None:
    """
    Načte aktuální HP/DEF/FUR hráče z profiles.json.
    Vrátí dict {hp, max_hp, def, fur} nebo None pokud profil neexistuje.
    """
    profiles = _load_profiles()
    profile  = profiles.get(_pk(profiles, user_id))
    if not profile:
        return None
    items_db = _load_items_db()
    hp_cur  = profile.get("hp_cur",  profile.get("hp_max", 50))
    hp_max  = profile.get("hp_max",  50)
    fur_cur = profile.get("fury_cur", 0)
    fur_max = profile.get("fury_max", 0)
    def_val = _compute_def_from_equipment(profile, items_db)
    return {
        "hp":     hp_cur,
        "max_hp": hp_max,
        "def":    def_val,
        "fur":    fur_cur,
        "fur_max": fur_max,   # uložíme pro referenci
    }

def _writeback_hp_to_profile(user_id: int, new_hp: int):
    """
    Zapíše nové hp_cur zpět do profiles.json pro daného hráče.
    """
    try:
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, user_id))
        if not profile:
            return
        hp_max = profile.get("hp_max", 50)
        profile["hp_cur"] = max(0, min(new_hp, hp_max))
        _save_profiles(profiles)
    except Exception:
        logging.exception("[combat] Nelze zapsat HP zpět do profilu")


# ── Bar helpers ───────────────────────────────────────────────────────────────

def _make_bar(current: int, maximum: int, length: int = 10) -> str:
    if maximum <= 0:
        return "░" * length
    filled = max(0, min(length, round((current / maximum) * length)))
    return "█" * filled + "░" * (length - filled)


def _hp_color(hp: int, max_hp: int) -> int:
    if max_hp <= 0:
        return 0x95a5a6
    pct = hp / max_hp
    if pct <= 0.25:
        return 0xe74c3c   # červená
    if pct <= 0.60:
        return 0xe67e22   # oranžová
    return 0x2ecc71       # zelená


# ── Formát řádku v order listu ────────────────────────────────────────────────

def _format_actor_line(name: str, stats: dict, is_active: bool, idx_marker: bool,
                       status_str: str = "") -> str:
    """
    Vrátí jeden řádek pro order embed.
    - Hráči (mention) bez stats → jen mention
    - NPC / hráči se stats → HP bar + DEF + FUR (+ ikony statusů)
    """
    s = stats.get(name)

    if s:
        hp      = s["hp"]
        max_hp  = s["max_hp"]
        defense = s.get("def", 0)
        fury    = s.get("fur", 0)
        bar     = _make_bar(hp, max_hp, 8)

        hp_str  = f"❤️ `{hp:>3}/{max_hp}` {bar}"
        def_str = f"  🛡️`{defense}`" if defense > 0 else ""
        fur_str = f"  🔥`{fury}`"    if fury    > 0 else ""
        st_str  = f"  {status_str}" if status_str else ""
        stats_line = f"\n> *{hp_str}{def_str}{fur_str}{st_str}*"
    else:
        stats_line = ""

    if idx_marker:
        prefix = "▶️"
        name_fmt = f"**{name}**"
        suffix = "  *(na řadě)*"
    else:
        prefix = "◽"
        name_fmt = name
        suffix = ""

    return f"{prefix} {name_fmt}{suffix}{stats_line}"


# ── Boss bar embed ─────────────────────────────────────────────────────────────

def _boss_embed(name: str, s: dict, flashing: bool = False) -> discord.Embed:
    hp      = s["hp"]
    max_hp  = s["max_hp"]
    defense = s.get("def", 0)
    fury    = s.get("fur", 0)
    hp_pct  = round((hp / max_hp) * 100) if max_hp > 0 else 0
    rage    = 100 - hp_pct
    color   = _hp_color(hp, max_hp)

    if flashing:
        return discord.Embed(
            title=f"💥  {name}  💥",
            description="*— přijímá poškození —*",
            color=0xff0000,
        )

    hp_bar   = _make_bar(hp, max_hp)
    rage_bar = _make_bar(rage, 100)
    dead     = hp == 0

    desc = (
        f"```\n"
        f"╔══════════════════════╗\n"
        f"║  HP    {hp_bar}  {hp:>4}/{max_hp}\n"
        f"║  Rage  {rage_bar}  {rage:>3}%\n"
        f"╚══════════════════════╝\n"
        f"```"
    )
    if defense > 0:
        desc += f"\n🛡️ DEF: **{defense}**"
    if fury > 0:
        desc += f"  🔥 FUR: **{fury}**"
    if dead:
        desc += "\n\n💀 **Boss padl.**"

    return discord.Embed(
        title=f"{'💀' if dead else '☠️'}  {name}",
        description=desc,
        color=color,
    )


# ── Order embed builder ────────────────────────────────────────────────────────

def _build_order_embed(title: str, combat: dict, note: str = "") -> discord.Embed:
    """Sestaví embed s pořadím bojovníků, HP/DEF/FUR stats a aktuálním na řadě."""
    order   = combat["order"]
    idx     = combat["current_index"]
    stats   = combat["stats"]
    locked  = combat["locked"]

    lines = []
    bs  = _bs()
    reg = bs.load_statuses() if bs else {}
    for i, name in enumerate(order):
        is_active = locked and (i == idx)
        s = stats.get(name)
        st_str = bs.status_icons(s, reg) if (bs and s) else ""
        lines.append(_format_actor_line(name, stats, is_active=is_active,
                                        idx_marker=is_active, status_str=st_str))

    description = "\n".join(lines) if lines else "*Seznam je prázdný.*"
    if note:
        description = f"*{note}*\n\n" + description

    active = combat.get("active_player") or (order[idx] if locked and order else None)
    footer = f"Na řadě: {active}" if active else ""

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.gold(),
    )
    if footer:
        embed.set_footer(text=footer)
    return embed


# ── EOT Button View ────────────────────────────────────────────────────────────

class EOTView(ui.View):
    def __init__(self, cog: "CombatCog", channel_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.channel_id = channel_id

    @ui.button(label="⏭️  End of Turn", style=discord.ButtonStyle.danger)
    async def eot_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.channel_id not in self.cog.active_combats:
            return await interaction.response.send_message(
                "❌ *Combat byl ukončen.*", ephemeral=True
            )

        combat = self.cog.active_combats[self.channel_id]

        if not combat.get("locked"):
            return await interaction.response.send_message(
                "⚠️ *Combat ještě není uzavřen. Čekej na `/combat_setorder`.*",
                ephemeral=True,
            )

        order = combat["order"]
        if not order:
            return await interaction.response.send_message(
                "⚠️ *Pořadí je prázdné.*", ephemeral=True
            )

        current_actor = order[combat["current_index"]]
        is_npc_turn   = not current_actor.startswith("<@")
        is_admin      = interaction.user.guild_permissions.administrator
        is_current    = interaction.user.mention == current_actor

        if is_npc_turn and not is_admin:
            return await interaction.response.send_message(
                f"🎲 *Tah NPC **{current_actor}** může předat pouze GM (admin).*",
                ephemeral=True,
            )

        if not is_npc_turn and not is_current and not is_admin:
            return await interaction.response.send_message(
                f"⏳ *Nejsi na řadě! Nyní hraje: {current_actor}*",
                ephemeral=True,
            )

        # Advance
        combat["current_index"] = (combat["current_index"] + 1) % len(order)
        next_actor = order[combat["current_index"]]
        combat["active_player"] = next_actor

        # Nové kolo (pořadí se obtočilo) → auto-tick statusů (dmg z jedu/krvácení atd.)
        tick_note = ""
        if combat["current_index"] == 0 and combat.get("auto_tick", True):
            tick_note = self.cog._tick_round(combat)
        self.cog._save_state()

        note = f"Tah předán — nyní hraje {next_actor}"
        if tick_note:
            note += f"\n\n{tick_note}"
        embed = _build_order_embed("⏭️  Další na řadě!", combat, note=note)
        view = EOTView(self.cog, self.channel_id)
        await interaction.response.send_message(embed=embed, view=view)


# ── CombatCog ─────────────────────────────────────────────────────────────────

class CombatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_combats = self._load_state()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_state(self):
        try:
            serializable = {str(k): v for k, v in self.active_combats.items()}
            save_json(COMBAT_STATE, serializable)
        except Exception:
            logging.exception("[combat] Nelze uložit stav")

    def _load_state(self) -> dict:
        try:
            raw = load_json(COMBAT_STATE, default={})
            return {int(k): v for k, v in raw.items()}
        except Exception:
            logging.exception("[combat] Nelze načíst stav")
            return {}

    # ── Boss bar ──────────────────────────────────────────────────────────────

    async def _update_boss_bar(self, combat: dict, flashing: bool = False):
        boss = combat.get("boss")
        if not boss:
            return
        try:
            channel = self.bot.get_channel(boss["channel_id"])
            if not channel:
                return
            msg = await channel.fetch_message(boss["message_id"])
            s = combat["stats"].get(boss["name"])
            if not s:
                return
            if flashing:
                await msg.edit(embed=_boss_embed(boss["name"], s, flashing=True))
                await asyncio.sleep(0.7)
            await msg.edit(embed=_boss_embed(boss["name"], s))
        except Exception:
            logging.exception("[combat] Nelze aktualizovat boss bar")

    # ── Helpers pro odpovědi ──────────────────────────────────────────────────

    async def _send_order(self, interaction: discord.Interaction, title: str, note: str = ""):
        """Odešle order embed bez EOT tlačítka (použij před setorder)."""
        combat = self.active_combats[interaction.channel_id]
        embed  = _build_order_embed(title, combat, note)
        await interaction.response.send_message(embed=embed)

    async def _send_order_with_eot(self, interaction: discord.Interaction, title: str, note: str = ""):
        """Odešle order embed s EOT tlačítkem (po setorder)."""
        combat = self.active_combats[interaction.channel_id]
        embed  = _build_order_embed(title, combat, note)
        view   = EOTView(self, interaction.channel_id)
        # Pokud interaction už byl deferred, použij followup
        try:
            await interaction.followup.send(embed=embed, view=view)
        except Exception:
            await interaction.response.send_message(embed=embed, view=view)

    # ── Statusy: tick + ovládání ───────────────────────────────────────────────

    def _tick_round(self, combat: dict) -> str:
        """Konec kola: u všech aktérů udělí dmg ze statusů a sníží trvání.

        Hráčům zapíše hp + statusy zpět do profilu a uberou kolo jejich nátěrům.
        Vrací shrnutí pro embed (prázdné, když se nic nestalo).
        """
        bs = _bs()
        if not bs:
            return ""
        reg   = bs.load_statuses()
        lines = []
        for actor, s in combat["stats"].items():
            dmg, log = bs.tick_statuses(s, reg)
            if dmg:
                s["hp"] = max(0, s.get("hp", 0) - dmg)
            uid = _actor_uid(actor)
            if uid is not None:
                _writeback_player_state(uid, s, bs)
            if log:
                lines.append(f"**{actor}**: " + " · ".join(log))
        if not lines:
            return ""
        return "🩸 **Konec kola — statusy:**\n" + "\n".join(lines)

    combat_effect = app_commands.Group(
        name="combat_effect", description="Statusy v boji — jed/krvácení atd. (DM).")

    async def _ac_actor(self, interaction: discord.Interaction, current: str):
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return []
        cur = current.lower()
        return [app_commands.Choice(name=a[:100], value=a)
                for a in combat["order"] if cur in a.lower()][:25]

    async def _ac_status_id(self, interaction: discord.Interaction, current: str):
        bs = _bs()
        if not bs:
            return []
        reg = bs.load_statuses(); cur = current.lower()
        return [app_commands.Choice(name=f"{s.get('emoji','•')} {s['name']} ({sid})"[:100], value=sid)
                for sid, s in reg.items() if cur in sid.lower() or cur in s.get("name","").lower()][:25]

    @combat_effect.command(name="add", description="[DM] Přidej status aktérovi.")
    @app_commands.describe(target="Aktér (hráč/NPC).", status="Status.", source="Odkud efekt je.")
    @app_commands.choices(source=[
        app_commands.Choice(name="zbraň",     value="zbran"),
        app_commands.Choice(name="runa",      value="runa"),
        app_commands.Choice(name="prostředí", value="prostredi"),
        app_commands.Choice(name="schopnost", value="schopnost"),
    ])
    @app_commands.autocomplete(target=_ac_actor, status=_ac_status_id)
    async def combat_status_add(self, interaction: discord.Interaction,
                                target: str, status: str, source: str = "prostredi"):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Jen GM (admin).", ephemeral=True)
        combat = self.active_combats.get(interaction.channel_id)
        if not combat or target not in combat["stats"]:
            return await interaction.response.send_message("❌ Aktér není v boji.", ephemeral=True)
        bs = _bs()
        if not bs:
            return await interaction.response.send_message("❌ Status engine nedostupný.", ephemeral=True)
        reg  = bs.load_statuses()
        inst = bs.apply_status(combat["stats"][target], status, source, reg)
        if not inst:
            return await interaction.response.send_message(f"❌ Status `{status}` neexistuje.", ephemeral=True)
        uid = _actor_uid(target)
        if uid is not None:
            _writeback_player_state(uid, combat["stats"][target], bs)
        self._save_state()
        sdef = reg.get(status, {})
        await interaction.response.send_message(
            f"{sdef.get('emoji','•')} **{sdef.get('name', status)}** přidán na **{target}** "
            f"(zdroj: {SOURCE_LABEL.get(source, source)}).")

    @combat_effect.command(name="clear", description="[DM] Vyléč statusy aktéra (dle typu).")
    @app_commands.describe(target="Aktér.", cure="Typ léčení.")
    @app_commands.choices(cure=[
        app_commands.Choice(name="fyzické", value="fyzické"),
        app_commands.Choice(name="magické", value="magické"),
        app_commands.Choice(name="vše",     value="vse"),
    ])
    @app_commands.autocomplete(target=_ac_actor)
    async def combat_status_clear(self, interaction: discord.Interaction,
                                  target: str, cure: str = "vse"):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Jen GM (admin).", ephemeral=True)
        combat = self.active_combats.get(interaction.channel_id)
        if not combat or target not in combat["stats"]:
            return await interaction.response.send_message("❌ Aktér není v boji.", ephemeral=True)
        bs = _bs()
        if not bs:
            return await interaction.response.send_message("❌ Status engine nedostupný.", ephemeral=True)
        carrier = combat["stats"][target]
        if cure == "vse":
            removed = [s.get("status") for s in carrier.get("statuses", [])]
            carrier["statuses"] = []
        else:
            removed = bs.cure_statuses(carrier, cure)
        uid = _actor_uid(target)
        if uid is not None:
            _writeback_player_state(uid, carrier, bs)
        self._save_state()
        await interaction.response.send_message(
            f"🩹 **{target}** — sundáno: {', '.join(removed) if removed else 'nic'}.")

    @combat_effect.command(name="list", description="Zobraz statusy aktéra.")
    @app_commands.autocomplete(target=_ac_actor)
    async def combat_status_list(self, interaction: discord.Interaction, target: str):
        combat = self.active_combats.get(interaction.channel_id)
        if not combat or target not in combat["stats"]:
            return await interaction.response.send_message("❌ Aktér není v boji.", ephemeral=True)
        bs = _bs()
        desc = bs.describe_statuses(combat["stats"][target]) if bs else ""
        await interaction.response.send_message(
            f"**{target}** statusy:\n{desc or '*žádné*'}", ephemeral=True)

    @combat_effect.command(name="autotick", description="[DM] Zapni/vypni auto-odečet dmg ze statusů.")
    async def combat_status_autotick(self, interaction: discord.Interaction, zapnuto: bool):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Jen GM (admin).", ephemeral=True)
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return await interaction.response.send_message("❌ V téhle místnosti není boj.", ephemeral=True)
        combat["auto_tick"] = zapnuto
        self._save_state()
        await interaction.response.send_message(
            f"⚙️ Auto-tick statusů: **{'zapnut' if zapnuto else 'vypnut'}**.")

    # ── /combat_start ─────────────────────────────────────────────────────────

    @app_commands.command(name="combat_start", description="Zahájí boj v této místnosti")
    async def combat_start(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        self.active_combats[channel_id] = {
            "order":         [],
            "current_index": 0,
            "locked":        False,
            "stats":         {},
            "first":         None,
            "active_player": None,
        }
        self._save_state()
        embed = discord.Embed(
            title="⚔️  Boj začíná!",
            description=(
                "*Combat byl zahájen v tomto kanálu.*\n\n"
                "Hráči: `/combat_join`\n"
                "GM přidá NPC: `/combat_add_npc`\n"
                "GM uzavře pořadí: `/combat_setorder`"
            ),
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)

    # ── /combat_join ──────────────────────────────────────────────────────────

    @app_commands.command(name="combat_join", description="Hráč se zapojí do boje")
    async def combat_join(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        combat = self.active_combats[channel_id]
        user   = interaction.user.mention

        if combat["locked"]:
            return await interaction.response.send_message(
                "🔒 *Pořadí je uzavřeno. Počkej na svůj tah.*", ephemeral=True
            )

        just_joined = user not in combat["order"]
        if just_joined:
            combat["order"].append(user)
            if combat["first"] is None:
                combat["first"] = user

        # ── Synchronizace stats z profilu ────────────────────────────────────
        synced = _sync_player_from_profile(user, interaction.user.id)
        if synced:
            # Vždy přepiš aktuální hodnoty (resync při každém joinu)
            combat["stats"][user] = {
                "hp":     synced["hp"],
                "max_hp": synced["max_hp"],
                "def":    synced["def"],
                "fur":    synced["fur"],
            }

        if combat.get("active_player") is None:
            combat["active_player"] = user

        active = combat["active_player"]
        self._save_state()

        if just_joined and active != user:
            # Informuj ephemeral, ale přidej i stats info
            stats_info = (
                f"\n*❤️ `{synced['hp']}/{synced['max_hp']}`  🛡️ `{synced['def']}`  🔥 `{synced['fur']}`*"
                if synced else ""
            )
            await interaction.response.send_message(
                f"✅ *Byl jsi přidán do pořadí!*{stats_info}\nPrávě hraje: {active}. Počkej na svůj tah.",
                ephemeral=True,
            )
        else:
            await self._send_order(
                interaction,
                "⚡  Hráč přebírá iniciativu!",
                note=f"{user} se zapojil do boje",
            )

    # ── /combat_add_npc ───────────────────────────────────────────────────────

    @app_commands.command(name="combat_add_npc", description="GM přidá NPC/potvoru s HP, DEF a FUR")
    @app_commands.describe(
        name="Jméno NPC",
        hp="Maximum životů (výchozí: 100)",
        current_hp="Aktuální HP při vstupu — pokud nenastaveno, použije se max HP",
        defense="Obrana / DEF (výchozí: 0)",
        fury="Zuřivost / FUR (výchozí: 0)",
    )
    async def combat_add_npc(
        self,
        interaction: discord.Interaction,
        name: str,
        hp: int = 100,
        current_hp: int = -1,
        defense: int = 0,
        fury: int = 0,
    ):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        name = name.strip()
        if not name:
            return await interaction.response.send_message(
                "⚠️ *Jméno NPC nesmí být prázdné.*", ephemeral=True
            )

        actual_current = hp if current_hp == -1 else max(0, min(current_hp, hp))
        combat = self.active_combats[channel_id]

        final_name = name
        counter = 2
        while final_name in combat["stats"] or final_name in combat["order"]:
            final_name = f"{name} {counter}"
            counter += 1

        combat["order"].append(final_name)
        combat["stats"][final_name] = {
            "hp":     actual_current,
            "max_hp": hp,
            "def":    defense,
            "fur":    fury,
        }
        self._save_state()

        await self._send_order(
            interaction,
            f"💀  {final_name} vstupuje do boje!",
            note=f"NPC přidáno — HP {actual_current}/{hp}  DEF {defense}  FUR {fury}",
        )

    # ── /combat_add_player_stats ──────────────────────────────────────────────

    @app_commands.command(
        name="combat_add_player_stats",
        description="GM přidá HP/DEF/FUR hráči (např. pro tracking zranění)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        mention="Hráč (mention)",
        hp="Maximum životů",
        current_hp="Aktuální HP (výchozí = max HP)",
        defense="DEF (výchozí: 0)",
        fury="FUR / Zuřivost (výchozí: 0)",
    )
    async def combat_add_player_stats(
        self,
        interaction: discord.Interaction,
        mention: discord.Member,
        hp: int = 100,
        current_hp: int = -1,
        defense: int = 0,
        fury: int = 0,
    ):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        combat      = self.active_combats[channel_id]
        player_key  = mention.mention
        actual_hp   = hp if current_hp == -1 else max(0, min(current_hp, hp))

        combat["stats"][player_key] = {
            "hp":     actual_hp,
            "max_hp": hp,
            "def":    defense,
            "fur":    fury,
        }
        self._save_state()

        await interaction.response.send_message(
            f"✅ *Stats přidány pro {player_key}* — ❤️ `{actual_hp}/{hp}`  🛡️ `{defense}`  🔥 `{fury}`",
            ephemeral=True,
        )

    # ── /combat_add_boss ──────────────────────────────────────────────────────

    @app_commands.command(name="combat_add_boss", description="GM přidá bosse s odděleným boss barem")
    @app_commands.describe(
        name="Jméno bosse",
        hp="Maximum životů (výchozí: 200)",
        defense="DEF (výchozí: 0)",
        fury="FUR (výchozí: 0)",
    )
    async def combat_add_boss(
        self,
        interaction: discord.Interaction,
        name: str,
        hp: int = 200,
        defense: int = 0,
        fury: int = 0,
    ):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        combat = self.active_combats[channel_id]
        if combat.get("boss"):
            return await interaction.response.send_message(
                "⚠️ *V tomto combatu už boss je. Nejdřív ho odeber přes `/combat_remove`.*",
                ephemeral=True,
            )

        name = name.strip()
        if not name:
            return await interaction.response.send_message(
                "⚠️ *Jméno bosse nesmí být prázdné.*", ephemeral=True
            )

        combat["order"].append(name)
        combat["stats"][name] = {"hp": hp, "max_hp": hp, "def": defense, "fur": fury}

        await interaction.response.defer()

        boss_msg = await interaction.channel.send(embed=_boss_embed(name, combat["stats"][name]))

        combat["boss"] = {
            "name":       name,
            "message_id": boss_msg.id,
            "channel_id": channel_id,
        }
        self._save_state()

        await interaction.followup.send(
            f"☠️ *Boss **{name}** vstoupil do boje!*  ❤️ `{hp}` HP  🛡️ `{defense}` DEF  🔥 `{fury}` FUR"
        )

    # ── /combat_sethp ─────────────────────────────────────────────────────────

    @app_commands.command(name="combat_sethp", description="Admin: nastaví HP NPC/hráči během combatu")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        name="Jméno NPC nebo mention hráče (@mention nebo přesné jméno)",
        hp="Nové HP (záporná hodnota = poškození, kladná = absolutní nastavení)",
    )
    async def combat_sethp(self, interaction: discord.Interaction, name: str, hp: int):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        combat = self.active_combats[channel_id]
        stats  = combat["stats"]

        if name not in stats:
            return await interaction.response.send_message(
                f"⚠️ *`{name}` nemá zaznamenané HP.*\n"
                "NPC: `/combat_add_npc`  |  Hráč: `/combat_add_player_stats` nebo `/combat_join`",
                ephemeral=True,
            )

        old_hp = stats[name]["hp"]
        max_hp = stats[name]["max_hp"]

        if hp < 0:
            new_hp     = max(0, old_hp + hp)
            change_str = f"poškození {hp}"
        else:
            new_hp     = min(hp, max_hp)
            change_str = f"nastaveno na {new_hp}"

        stats[name]["hp"] = new_hp
        self._save_state()

        # ── Zpětný zápis do profilu pokud jde o hráče (mention) ──────────────
        is_player = name.startswith("<@")
        if is_player:
            # Parsujeme user ID z mentiony: <@123456> nebo <@!123456>
            try:
                uid = int(name.strip("<@!>"))
                _writeback_hp_to_profile(uid, new_hp)
            except ValueError:
                pass

        bar   = _make_bar(new_hp, max_hp)
        color = _hp_color(new_hp, max_hp)
        dead  = new_hp == 0

        embed = discord.Embed(
            title=f"❤️  HP upraveno — {name}",
            description=(
                f"`{bar}` **{new_hp}/{max_hp}**\n"
                f"*{old_hp} → {new_hp}  ({change_str})*\n"
                f"🛡️ DEF: `{stats[name]['def']}`  🔥 FUR: `{stats[name].get('fur', 0)}`"
                + ("\n*↩️ Zapsáno do profilu hráče.*" if is_player else "")
                + ("\n\n💀 *HP dosáhlo nuly! Zvaž `/combat_remove`.*" if dead else "")
            ),
            color=discord.Color.red() if dead else color,
        )
        await interaction.response.send_message(embed=embed)

        is_boss = combat.get("boss", {}).get("name") == name
        if is_boss:
            asyncio.create_task(self._update_boss_bar(combat, flashing=(hp < 0)))

    # ── /combat_setdef ────────────────────────────────────────────────────────

    @app_commands.command(name="combat_setdef", description="Admin: nastaví DEF NPC/hráči")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(name="Jméno NPC nebo mention hráče", defense="Nová hodnota obrany")
    async def combat_setdef(self, interaction: discord.Interaction, name: str, defense: int):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        stats = self.active_combats[channel_id]["stats"]
        if name not in stats:
            return await interaction.response.send_message(
                f"⚠️ *`{name}` nemá zaznamenané stats.*", ephemeral=True
            )

        old_def        = stats[name]["def"]
        stats[name]["def"] = max(0, defense)
        self._save_state()

        embed = discord.Embed(
            title=f"🛡️  DEF upraveno — {name}",
            description=f"*{old_def} → **{stats[name]['def']}***",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed)

    # ── /combat_setfur ────────────────────────────────────────────────────────

    @app_commands.command(name="combat_setfur", description="Admin: nastaví FUR (zuřivost) NPC/hráči")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(name="Jméno NPC nebo mention hráče", fury="Nová hodnota zuřivosti")
    async def combat_setfur(self, interaction: discord.Interaction, name: str, fury: int):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        stats = self.active_combats[channel_id]["stats"]
        if name not in stats:
            return await interaction.response.send_message(
                f"⚠️ *`{name}` nemá zaznamenané stats.*", ephemeral=True
            )

        old_fur        = stats[name].get("fur", 0)
        stats[name]["fur"] = max(0, fury)
        self._save_state()

        embed = discord.Embed(
            title=f"🔥  FUR upraveno — {name}",
            description=f"*{old_fur} → **{stats[name]['fur']}***",
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)

    # ── /combat_remove ────────────────────────────────────────────────────────

    @app_commands.command(name="combat_remove", description="Odebere někoho z pořadí")
    async def combat_remove(self, interaction: discord.Interaction, name: str):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        combat = self.active_combats[channel_id]
        order  = combat["order"]

        to_remove = next((item for item in order if name in item), None)
        if not to_remove:
            return await interaction.response.send_message(
                f"⚠️ *`{name}` nebyl v pořadí nalezen.*", ephemeral=True
            )

        removed_idx = order.index(to_remove)
        order.remove(to_remove)
        combat["stats"].pop(to_remove, None)

        if combat.get("boss", {}).get("name") == to_remove:
            combat.pop("boss", None)

        if combat.get("active_player") == to_remove:
            combat["active_player"] = order[0] if order else None

        if combat["locked"]:
            if not order:
                combat["locked"]        = False
                combat["current_index"] = 0
            elif removed_idx <= combat["current_index"]:
                combat["current_index"] = max(0, combat["current_index"] - 1)

        self._save_state()
        await interaction.response.send_message(
            f"❌ *{to_remove} byl odstraněn z boje.*"
        )

    # ── /combat_setorder ──────────────────────────────────────────────────────

    @app_commands.command(
        name="combat_setorder",
        description="Uzavře pořadí do pevné smyčky a spustí combat"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def combat_setorder(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats or not self.active_combats[channel_id]["order"]:
            return await interaction.response.send_message(
                "⚠️ *Seznam je prázdný.*", ephemeral=True
            )

        combat = self.active_combats[channel_id]

        # Hráč, který se připojil jako první, jde na začátek
        first = combat.get("first")
        if first and first in combat["order"] and combat["order"][0] != first:
            combat["order"].remove(first)
            combat["order"].insert(0, first)

        combat["locked"]        = True
        combat["current_index"] = 0
        combat["active_player"] = combat["order"][0]
        self._save_state()

        embed = _build_order_embed(
            "🔒  Pořadí uzavřeno — boj začíná!",
            combat,
            note="Admin uzavřel pořadí. Použij tlačítko ⏭️ pro předání tahu.",
        )
        view = EOTView(self, channel_id)

        await interaction.response.defer()
        await interaction.followup.send(embed=embed, view=view)

    # ── /combat_end ───────────────────────────────────────────────────────────

    @app_commands.command(name="combat_end", description="Ukončí combat a vymaže data")
    async def combat_end(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id in self.active_combats:
            del self.active_combats[channel_id]
            self._save_state()
            embed = discord.Embed(
                title="🏁  Combat ukončen",
                description="*Boj skončil. Data byla vymazána.*",
                color=discord.Color.greyple(),
            )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(
                "⚠️ *Žádný aktivní boj.*", ephemeral=True
            )

    # ── /combat_status ────────────────────────────────────────────────────────

    @app_commands.command(name="combat_status", description="Zobrazí aktuální pořadí a stats")
    async def combat_status(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        combat = self.active_combats[channel_id]
        embed  = _build_order_embed("📋  Aktuální stav combatu", combat)
        view   = EOTView(self, channel_id) if combat.get("locked") else discord.utils.MISSING

        if combat.get("locked"):
            await interaction.response.send_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(CombatCog(bot))