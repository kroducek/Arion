import discord
import asyncio
import logging
from discord.ext import commands
from discord import app_commands
from src.utils.paths import COMBAT_STATE
from src.utils.json_utils import load_json, save_json


# ── Boss bar helpers ──────────────────────────────────────────────────────────

def _make_bar(current: int, maximum: int, length: int = 10) -> str:
    if maximum <= 0:
        return "░" * length
    filled = max(0, min(length, round((current / maximum) * length)))
    return "█" * filled + "░" * (length - filled)


def _boss_embed(name: str, s: dict, flashing: bool = False) -> discord.Embed:
    hp      = s["hp"]
    max_hp  = s["max_hp"]
    defense = s["def"]
    hp_pct  = round((hp / max_hp) * 100) if max_hp > 0 else 0
    rage    = 100 - hp_pct

    color = 0xe74c3c if hp_pct <= 30 else (0xe67e22 if hp_pct <= 60 else 0x2ecc71)

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
    if dead:
        desc += "\n\n💀 **Boss padl.**"

    return discord.Embed(
        title=f"{'💀' if dead else '☠️'}  {name}",
        description=desc,
        color=color,
    )


class CombatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # channel_id: {"order": [], "current_index": 0, "locked": False, "stats": {}}
        # stats: {name: {"hp": int, "max_hp": int, "def": int}} -- pouze pro NPC
        self.active_combats = self._load_state()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_state(self):
        """Uloží stav všech aktivních combatů do JSON."""
        try:
            serializable = {str(k): v for k, v in self.active_combats.items()}
            save_json(COMBAT_STATE, serializable)
        except Exception:
            logging.exception("[combat] Nelze uložit stav")

    def _load_state(self) -> dict:
        """Načte stav combatů ze JSON při spuštění bota."""
        try:
            raw = load_json(COMBAT_STATE, default={})
            return {int(k): v for k, v in raw.items()}
        except Exception:
            logging.exception("[combat] Nelze načíst stav")
            return {}

    # ── Helpers ───────────────────────────────────────────────────────────────

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

    def _format_name(self, name: str, stats: dict) -> str:
        """Vrátí jméno s HP/DEF barem pokud má stats."""
        if name not in stats:
            return name
        s = stats[name]
        hp = s["hp"]
        max_hp = s["max_hp"]
        defense = s["def"]

        def_part = f"  🛡️ {defense}" if defense > 0 else ""
        return f"{name}  ❤️ {hp}/{max_hp}{def_part}"

    async def _show_order(self, interaction, title, current_actor):
        combat = self.active_combats[interaction.channel_id]
        order = combat["order"]
        idx = combat["current_index"]
        stats = combat["stats"]
        active = combat.get("active_player")

        list_str = ""
        for i, name in enumerate(order):
            formatted = self._format_name(name, stats)
            if combat["locked"] and i == idx:
                list_str += f"▶️ **{formatted}** (NA RADE)\n"
            elif not combat["locked"] and active and name == active:
                list_str += f"🔥 **{formatted}** (PRAVE HRAJE)\n"
            else:
                list_str += f"◽ {formatted}\n"

        embed = discord.Embed(
            title=title,
            description=list_str if list_str else "Seznam je prazdny.",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(content=f"Akci provadi: {active or current_actor}", embed=embed)

    # ── Příkazy ───────────────────────────────────────────────────────────────

    @app_commands.command(name="combat_start", description="Zahaji boj v teto mistnosti")
    async def combat_start(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        self.active_combats[channel_id] = {
            "order": [],
            "current_index": 0,
            "locked": False,
            "stats": {},
            "first": None,
            "active_player": None
        }
        self._save_state()
        embed = discord.Embed(
            title="⚔️ BOJ ZACINA",
            description="Combat byl zahajen! Poradi se tvori dynamicky.\nNapis `/combat_join` nebo `/combat_add_npc` pro akci.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="combat_join", description="Hrac se zapoji do boje a odehraje tah")
    async def combat_join(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message("Zde nebezi combat.", ephemeral=True)

        combat = self.active_combats[channel_id]
        user = interaction.user.mention

        if combat["locked"]:
            return await interaction.response.send_message("Order je uzavreny. Pockej na svuj tah.", ephemeral=True)

        just_joined = user not in combat["order"]
        if just_joined:
            combat["order"].append(user)
            if combat["first"] is None:
                combat["first"] = user

        if combat.get("active_player") is None:
            combat["active_player"] = user

        active = combat["active_player"]
        self._save_state()

        if just_joined and active != user:
            await interaction.response.send_message(
                f"Byl jsi pridan do poradi! Prave hraje: {active}. Pockej na svuj tah.",
                ephemeral=True
            )
        else:
            await self._show_order(interaction, "⚡ Hrac prebira iniciativu!", user)

    @app_commands.command(name="combat_add_npc", description="GM prida NPC/potvoru s HP a DEF")
    @app_commands.describe(
        name="Jmeno NPC",
        hp="Maximum zivotu (vychozi: 100)",
        current_hp="Aktualni HP pri vstupu do boje -- pokud nenastaveno, pouzije se max HP",
        defense="Obrana / DEF (vychozi: 0)"
    )
    async def combat_add_npc(
        self,
        interaction: discord.Interaction,
        name: str,
        hp: int = 100,
        current_hp: int = -1,
        defense: int = 0
    ):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message("Zde nebezi combat.", ephemeral=True)

        name = name.strip()
        if not name:
            return await interaction.response.send_message("Jméno NPC nesmí být prázdné.", ephemeral=True)

        actual_current = hp if current_hp == -1 else max(0, min(current_hp, hp))

        combat = self.active_combats[channel_id]

        # Pokud NPC se stejným jménem existuje, přidej číselnou příponu
        final_name = name
        counter = 2
        while final_name in combat["stats"]:
            final_name = f"{name} {counter}"
            counter += 1

        combat["order"].append(final_name)
        combat["stats"][final_name] = {
            "hp": actual_current,
            "max_hp": hp,
            "def": defense
        }
        self._save_state()

        await self._show_order(interaction, f"💀 {final_name} se zapojuje do boje!", final_name)

    @app_commands.command(name="combat_add_boss", description="GM přidá bosse s oddělených boss barem")
    @app_commands.describe(
        name="Jméno bosse",
        hp="Maximum životů (výchozí: 200)",
        defense="Obrana / DEF (výchozí: 0)",
    )
    async def combat_add_boss(
        self,
        interaction: discord.Interaction,
        name: str,
        hp: int = 200,
        defense: int = 0,
    ):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message("Zde neběží combat.", ephemeral=True)

        combat = self.active_combats[channel_id]
        if combat.get("boss"):
            return await interaction.response.send_message(
                "V tomto combatu už boss je. Nejdřív ho odeber přes `/combat_remove`.", ephemeral=True
            )

        name = name.strip()
        if not name:
            return await interaction.response.send_message("Jméno bosse nesmí být prázdné.", ephemeral=True)

        combat["order"].append(name)
        combat["stats"][name] = {"hp": hp, "max_hp": hp, "def": defense}

        await interaction.response.defer()

        boss_msg = await interaction.channel.send(embed=_boss_embed(name, combat["stats"][name]))

        combat["boss"] = {
            "name": name,
            "message_id": boss_msg.id,
            "channel_id": channel_id,
        }
        self._save_state()

        await interaction.followup.send(
            f"☠️ Boss **{name}** vstoupil do boje!  ❤️ {hp} HP  🛡️ {defense} DEF"
        )

    @app_commands.command(name="combat_sethp", description="Admin: Rucne nastavi HP NPC behem combatu")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        name="Jmeno NPC (presne jak bylo zadano)",
        hp="Nove HP (zadej zapornou hodnotu pro odecteni, kladnou pro nastaveni)"
    )
    async def combat_sethp(self, interaction: discord.Interaction, name: str, hp: int):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message("Zde nebezi combat.", ephemeral=True)

        combat = self.active_combats[channel_id]
        stats = combat["stats"]

        if name not in stats:
            return await interaction.response.send_message(
                f"NPC '{name}' nema zaznamenane HP. Pouze NPC pridana pres `/combat_add_npc` maji HP.",
                ephemeral=True
            )

        old_hp = stats[name]["hp"]
        max_hp = stats[name]["max_hp"]

        if hp < 0:
            new_hp = max(0, old_hp + hp)
            change_str = f"{hp} (poskozeni)"
        else:
            new_hp = min(hp, max_hp)
            change_str = f"nastaveno na {new_hp}"

        stats[name]["hp"] = new_hp
        self._save_state()

        is_boss = combat.get("boss", {}).get("name") == name

        bar_filled = round((new_hp / max_hp) * 10) if max_hp > 0 else 0
        bar_filled = max(0, min(10, bar_filled))
        bar = "🟥" * bar_filled + "⬛" * (10 - bar_filled)

        status = ""
        if new_hp == 0:
            status = "\n\n💀 **HP dosahlo nuly!** Zvaz pouziti `/combat_remove`."

        embed = discord.Embed(
            title=f"❤️ HP upraveno: {name}",
            description=(
                f"{bar}\n"
                f"**{old_hp}** → **{new_hp}** / {max_hp}  ({change_str})\n"
                f"🛡️ DEF: {stats[name]['def']}"
                f"{status}"
            ),
            color=discord.Color.red() if new_hp == 0 else discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed)

        if is_boss:
            asyncio.create_task(self._update_boss_bar(combat, flashing=(hp < 0)))

    @app_commands.command(name="combat_setdef", description="Admin: Rucne nastavi DEF NPC behem combatu")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        name="Jmeno NPC",
        defense="Nova hodnota obrany"
    )
    async def combat_setdef(self, interaction: discord.Interaction, name: str, defense: int):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message("Zde nebezi combat.", ephemeral=True)

        stats = self.active_combats[channel_id]["stats"]
        if name not in stats:
            return await interaction.response.send_message(
                f"NPC '{name}' nema zaznamenane stats.",
                ephemeral=True
            )

        old_def = stats[name]["def"]
        stats[name]["def"] = max(0, defense)
        self._save_state()

        embed = discord.Embed(
            title=f"🛡️ DEF upraveno: {name}",
            description=f"**{old_def}** → **{stats[name]['def']}**",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="combat_remove", description="Odebere nekoho z poradi")
    async def combat_remove(self, interaction: discord.Interaction, name: str):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message("Zde nebezi combat.", ephemeral=True)

        combat = self.active_combats[channel_id]
        order = combat["order"]

        to_remove = None
        for item in order:
            if name in item:
                to_remove = item
                break

        if not to_remove:
            return await interaction.response.send_message(f"'{name}' nebyl v poradi nalezen.", ephemeral=True)

        removed_idx = order.index(to_remove)
        order.remove(to_remove)
        combat["stats"].pop(to_remove, None)

        if combat.get("boss", {}).get("name") == to_remove:
            combat.pop("boss", None)

        # Pokud odstraněný byl active_player, resetuj ho
        if combat.get("active_player") == to_remove:
            combat["active_player"] = order[0] if order else None

        if combat["locked"]:
            if len(order) == 0:
                combat["locked"] = False
                combat["current_index"] = 0
            elif removed_idx <= combat["current_index"]:
                combat["current_index"] = max(0, combat["current_index"] - 1)

        self._save_state()
        await interaction.response.send_message(f"❌ **{to_remove}** byl odstranyen z boje.")

    @app_commands.command(name="combat_setorder", description="Uzavre poradi do pevne smycky")
    @app_commands.checks.has_permissions(administrator=True)
    async def combat_setorder(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats or not self.active_combats[channel_id]["order"]:
            return await interaction.response.send_message("Seznam je prazdny.", ephemeral=True)

        combat = self.active_combats[channel_id]

        first = combat.get("first")
        if first and first in combat["order"] and combat["order"][0] != first:
            combat["order"].remove(first)
            combat["order"].insert(0, first)

        combat["locked"] = True
        combat["current_index"] = 0
        self._save_state()

        await self._show_order(interaction, "🔒 PORADI UZAVRENO", combat["order"][0])

    @app_commands.command(name="next", description="Preda tah dalsimu v poradi")
    async def next_turn(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats or not self.active_combats[channel_id]["locked"]:
            return await interaction.response.send_message("Combat neni v loop rezimu. Pouzij `/combat_setorder`.", ephemeral=True)

        combat = self.active_combats[channel_id]
        current_actor = combat["order"][combat["current_index"]]

        is_npc_turn = not current_actor.startswith("<@")
        is_admin = interaction.user.guild_permissions.administrator
        is_current_player = interaction.user.mention == current_actor

        if not is_npc_turn and not is_current_player and not is_admin:
            return await interaction.response.send_message(
                f"Nejsi na rade! Nyni hraje: {current_actor}",
                ephemeral=True
            )

        if is_npc_turn and not is_admin:
            return await interaction.response.send_message(
                f"Tah NPC **{current_actor}** muze predat pouze GM (admin).",
                ephemeral=True
            )

        combat["current_index"] = (combat["current_index"] + 1) % len(combat["order"])
        current_actor = combat["order"][combat["current_index"]]
        combat["active_player"] = current_actor
        self._save_state()

        await self._show_order(interaction, "➡️ DALSI NA RADE", current_actor)

    @app_commands.command(name="combat_end", description="Ukonci combat a vymaze data")
    async def combat_end(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id in self.active_combats:
            del self.active_combats[channel_id]
            self._save_state()
            await interaction.response.send_message("🏁 Combat je u konce.")
        else:
            await interaction.response.send_message("Zadny aktivni boj.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(CombatCog(bot))
