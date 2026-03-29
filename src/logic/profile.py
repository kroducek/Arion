import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

from src.utils.paths import PROFILES as DATA_FILE, ECONOMY as ECONOMY_FILE, ITEMS as ITEMS_FILE
from src.utils.json_utils import load_json, save_json
from src.logic.stats import get_xp_cap, level_label, add_xp

# ══════════════════════════════════════════════════════════════════════════════
# DATOVÁ VRSTVA
# ══════════════════════════════════════════════════════════════════════════════

def load_data():
    return load_json(DATA_FILE)

def load_economy():
    return load_json(ECONOMY_FILE)

def save_data(data):
    save_json(DATA_FILE, data)

def load_economy_data():
    return load_json(ECONOMY_FILE)

def save_economy(data):
    save_json(ECONOMY_FILE, data)

def _load_items() -> dict:
    return load_json(ITEMS_FILE, default={})

# ══════════════════════════════════════════════════════════════════════════════
# HERNÍ LOGIKA
# ══════════════════════════════════════════════════════════════════════════════

DM_ROLE_NAME = "DM"

def _is_dm(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    return any(r.name == DM_ROLE_NAME for r in interaction.user.roles)

def _ensure_player_fields(profile: dict) -> None:
    """Nastaví výchozí hodnoty HP, hlad, mana, furioka, XP a level pokud chybí."""
    profile.setdefault("hp_max",     50)
    profile.setdefault("hp_cur",     profile.get("hp_max", 50))
    profile.setdefault("hunger_max", 10)
    profile.setdefault("hunger_cur", profile.get("hunger_max", 10))
    profile.setdefault("mana_max",   5)
    profile.setdefault("mana_cur",   0)
    profile.setdefault("fury_max",   0)
    profile.setdefault("fury_cur",   0)
    profile.setdefault("vliv_svetlo",    0)
    profile.setdefault("vliv_temnota",   0)
    profile.setdefault("vliv_rovnovaha", 0)
    profile.setdefault("xp",         0)
    profile.setdefault("level",      1)
    profile.setdefault("inventory",  [])
    profile.setdefault("equipment",  {})

def _bar(current: int, maximum: int, width: int = 10) -> str:
    if maximum <= 0:
        return "░" * width
    filled = round(max(0, min(current, maximum)) / maximum * width)
    return "█" * filled + "░" * (width - filled)

def _compute_total_def(profile: dict, items_db: dict) -> int:
    equipment = profile.get("equipment", {})
    seen = set()
    total = 0
    for item_id in equipment.values():
        if item_id and item_id not in seen:
            seen.add(item_id)
            total += items_db.get(item_id, {}).get("def", 0)
    return total

# ── Mini-kopie inventory helperů (aby nedošlo k cyklickému importu) ───────────

def _find_inv_entry(inventory: list, item_key: str) -> dict | None:
    key = item_key.lower()
    for entry in inventory:
        if entry["type"] == "registered" and entry["id"].lower() == key:
            return entry
        if entry["type"] == "free" and entry.get("name", "").lower() == key:
            return entry
    return None

def _remove_from_inventory(inventory: list, item_key: str, qty: int) -> bool:
    entry = _find_inv_entry(inventory, item_key)
    if not entry or entry.get("qty", 1) < qty:
        return False
    entry["qty"] -= qty
    if entry["qty"] <= 0:
        inventory.remove(entry)
    return True

# ══════════════════════════════════════════════════════════════════════════════
# AUTOCOMPLETE
# ══════════════════════════════════════════════════════════════════════════════

async def _ac_food_item(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    items_db  = _load_items()
    data      = load_data()
    profile   = data.get(str(interaction.user.id), {})
    inventory = profile.get("inventory", [])
    cur = current.lower()
    choices = []
    for entry in inventory:
        if entry.get("type") != "registered":
            continue
        db_item = items_db.get(entry["id"], {})
        hunger  = db_item.get("hunger_restore", 0)
        if not hunger:
            continue
        name = db_item.get("name", entry["id"])
        if cur in name.lower() or cur in entry["id"].lower():
            choices.append(app_commands.Choice(
                name=f"{name}  (+{hunger} hlad)", value=entry["id"]
            ))
    return choices[:25]

# ══════════════════════════════════════════════════════════════════════════════
# MODALY PRO /profile edit
# ══════════════════════════════════════════════════════════════════════════════

class EditNameModal(discord.ui.Modal, title="Upravit jméno postavy"):
    char_name = discord.ui.TextInput(
        label="Nové jméno postavy",
        placeholder="Jak se jmenuje tvá postava?",
        required=True,
        max_length=32,
    )

    async def on_submit(self, interaction: discord.Interaction):
        data = load_data()
        uid  = str(interaction.user.id)
        data.setdefault(uid, {})["name"] = self.char_name.value
        save_data(data)
        try:
            await interaction.user.edit(nick=self.char_name.value)
        except Exception:
            pass
        await interaction.response.send_message(
            f"✅ Jméno změněno na **{self.char_name.value}**.", ephemeral=True
        )


class EditMotivationModal(discord.ui.Modal, title="Upravit motivaci"):
    motivation = discord.ui.TextInput(
        label="Motivace postavy",
        style=discord.TextStyle.paragraph,
        placeholder="Proč chceš být dobrodruhem?",
        required=True,
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        data = load_data()
        uid  = str(interaction.user.id)
        data.setdefault(uid, {})["motivation"] = self.motivation.value[:200]
        save_data(data)
        await interaction.response.send_message(
            "✅ Motivace byla aktualizována.", ephemeral=True
        )


class EditPortraitModal(discord.ui.Modal, title="Upravit portrét"):
    url = discord.ui.TextInput(
        label="URL obrázku postavy",
        placeholder="https://...",
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        data = load_data()
        uid  = str(interaction.user.id)
        data.setdefault(uid, {})["portrait_url"] = self.url.value
        save_data(data)
        await interaction.response.send_message(
            "✅ Portrét byl aktualizován.", ephemeral=True
        )


class EditProfileView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Jméno", style=discord.ButtonStyle.primary, emoji="✍️")
    async def edit_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditNameModal())

    @discord.ui.button(label="Motivace", style=discord.ButtonStyle.secondary, emoji="✨")
    async def edit_motivation(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditMotivationModal())

    @discord.ui.button(label="Portrét (URL)", style=discord.ButtonStyle.secondary, emoji="🖼️")
    async def edit_portrait(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditPortraitModal())

# ══════════════════════════════════════════════════════════════════════════════
# COG
def _apply_vliv_fury(profile: dict) -> None:
    """Přepočítá fury_max a fury_cur na základě celkového Vlivu (1 Vliv = 5 max furioku)."""
    total_vliv = (
        profile.get("vliv_svetlo",    0) +
        profile.get("vliv_temnota",   0) +
        profile.get("vliv_rovnovaha", 0)
    )
    new_max = total_vliv * 5
    old_max = profile.get("fury_max", 0)
    delta   = new_max - old_max
    profile["fury_max"] = new_max
    profile["fury_cur"] = max(0, min(new_max, profile.get("fury_cur", 0) + delta))

# ══════════════════════════════════════════════════════════════════════════════

class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /profile ───────────────────────────────────────────────────────────────

    @app_commands.command(name="profile", description="Zobrazí tvůj dobrodružný průkaz.")
    @app_commands.describe(member="Hráč (výchozí: ty).")
    async def profile(self, interaction: discord.Interaction,
                      member: Optional[discord.Member] = None):
        target   = member or interaction.user
        data     = load_data()
        user_id  = str(target.id)

        if user_id not in data:
            await interaction.response.send_message(
                f"**{target.display_name}** zatím nemá průkaz dobrodruha. Musí projít tutoriálem!",
                ephemeral=True,
            )
            return

        profile  = data[user_id]
        _ensure_player_fields(profile)
        economy  = load_economy()
        balance  = economy.get(user_id, 0)
        items_db = _load_items()

        # ── Embed ──────────────────────────────────────────────────────────────
        embed = discord.Embed(
            title=f"📜  Průkaz dobrodruha: {profile.get('name', target.display_name)}",
            color=0x3498db,
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        # Základní info
        embed.add_field(name="🎖️ Rank",   value=profile.get("rank", "F3"), inline=True)
        embed.add_field(name="👤 Jméno",   value=profile.get("name", "—"),  inline=True)
        embed.add_field(
            name="<:goldcoin:1477303464781680772> Zlaťáky",
            value=str(balance),
            inline=True,
        )

        # ── Stav (HP / Hlad / Mana / Furioka / XP) ───────────────────────────
        hp_cur     = profile.get("hp_cur", 50)
        hp_max     = profile.get("hp_max", 50)
        hunger_cur = profile.get("hunger_cur", 10)
        hunger_max = profile.get("hunger_max", 10)
        mana_cur   = profile.get("mana_cur", 0)
        mana_max   = profile.get("mana_max", 5)
        fury_cur   = profile.get("fury_cur", 0)
        fury_max   = profile.get("fury_max", 0)
        v_svetlo   = profile.get("vliv_svetlo",    0)
        v_temnota  = profile.get("vliv_temnota",   0)
        v_rovno    = profile.get("vliv_rovnovaha", 0)
        level      = profile.get("level", 0)
        xp         = profile.get("xp", 0)
        sp         = profile.get("sp", 0)
        cap        = get_xp_cap(level)
        total_def  = _compute_total_def(profile, items_db)

        hp_bar     = _bar(hp_cur, hp_max)
        hunger_bar = _bar(hunger_cur, hunger_max)
        mana_bar   = _bar(mana_cur, mana_max)
        fury_bar   = _bar(fury_cur, fury_max)
        xp_bar     = _bar(xp, cap if cap else 1)

        def_str   = f"  ·  🛡️ DEF **{total_def}**" if total_def else ""
        xp_str    = f"{xp}/{cap}" if cap else f"{xp} (MAX)"
        sp_str    = f"  ·  ⚡ **{sp}** SP" if sp > 0 else ""

        status_lines = [
            f"❤️  {hp_bar}  {hp_cur}/{hp_max} HP{def_str}",
            f"🍖  {hunger_bar}  {hunger_cur}/{hunger_max} hlad",
            f"🔷  {mana_bar}  {mana_cur}/{mana_max} mana",
            f"🔥  {fury_bar}  {fury_cur}/{fury_max} furioka",
            f"⭐  {xp_bar}  {xp_str} XP  ·  **{level_label(level)}**{sp_str}",
        ]
        embed.add_field(name="Stav", value="\n".join(status_lines), inline=False)

        # ── Vliv ──────────────────────────────────────────────────────────────
        embed.add_field(
            name="🌗 Vliv",
            value=(
                f"⚪ Světlo **{v_svetlo}**  ·  ⚫ Temnota **{v_temnota}**  ·  ⚖️ Rovnováha **{v_rovno}**"
                f"\n-# 1 Vliv = 5 furiok"
            ),
            inline=False,
        )

        # ── Statistiky ────────────────────────────────────────────────────────
        stats = profile.get("stats")
        if stats:
            stats_line = "  ·  ".join(f"**{k}** {v}" for k, v in stats.items())
            embed.add_field(name="📊 Statistiky", value=f"-# {stats_line}", inline=False)

        # ── Motivace ──────────────────────────────────────────────────────────
        if profile.get("motivation"):
            embed.add_field(name="✨ Motivace", value=profile["motivation"], inline=False)

        if profile.get("portrait_url"):
            embed.set_image(url=profile["portrait_url"])

        embed.set_footer(text=f"ID: {user_id}  ·  Aurionis: Act II")
        await interaction.response.send_message(embed=embed)

    # ── /profile-edit ──────────────────────────────────────────────────────────

    @app_commands.command(name="profile-edit", description="Uprav svůj dobrodružný průkaz.")
    async def profile_edit(self, interaction: discord.Interaction):
        data    = load_data()
        user_id = str(interaction.user.id)

        if user_id not in data or not data[user_id].get("gold_received"):
            await interaction.response.send_message(
                "Průkaz můžeš upravit až po dokončení tutoriálu.",
                ephemeral=True,
            )
            return

        profile = data[user_id]
        embed = discord.Embed(
            title="✏️  Úprava průkazu",
            description=(
                f"**Jméno:** {profile.get('name', '—')}\n"
                f"**Motivace:** {profile.get('motivation', '—')[:80]}"
                f"{'...' if len(profile.get('motivation','')) > 80 else ''}\n"
                f"**Portrét:** {'✅ nastaven' if profile.get('portrait_url') else '—'}"
            ),
            color=0x3498db,
        )
        embed.set_footer(text="Vyber co chceš upravit.")
        await interaction.response.send_message(embed=embed, view=EditProfileView(), ephemeral=True)

    # ── /eat ───────────────────────────────────────────────────────────────────

    @app_commands.command(name="eat", description="Sní jídlo z inventáře a doplní hlad.")
    @app_commands.describe(item="Jídlo z inventáře.")
    @app_commands.autocomplete(item=_ac_food_item)
    async def eat(self, interaction: discord.Interaction, item: str):
        await interaction.response.defer(ephemeral=True)
        data    = load_data()
        user_id = str(interaction.user.id)
        profile = data.get(user_id)

        if not profile:
            await interaction.followup.send("❌ Nemáš profil. Nejdřív `/start`.")
            return

        _ensure_player_fields(profile)
        items_db = _load_items()
        db_item  = items_db.get(item)

        if not db_item:
            await interaction.followup.send("❌ Tento item není v databázi.")
            return

        hunger_restore = db_item.get("hunger_restore", 0)
        if not hunger_restore:
            await interaction.followup.send(
                f"❌ **{db_item['name']}** není jídlo — nedoplní hlad.")
            return

        if not _find_inv_entry(profile["inventory"], item):
            await interaction.followup.send(
                f"❌ **{db_item['name']}** nemáš v inventáři.")
            return

        _remove_from_inventory(profile["inventory"], item, 1)

        old_hunger = profile["hunger_cur"]
        profile["hunger_cur"] = min(
            profile["hunger_max"],
            profile["hunger_cur"] + hunger_restore,
        )
        gained = profile["hunger_cur"] - old_hunger

        save_data(data)

        bar = _bar(profile["hunger_cur"], profile["hunger_max"])
        await interaction.followup.send(
            f"🍖 Snědl jsi **{db_item['name']}**.\n"
            f"Hlad: {bar}  {profile['hunger_cur']}/{profile['hunger_max']}  "
            f"*(+{gained})*"
        )

    # ══════════════════════════════════════════════════════════════════════════
    # DM / ADMIN COMMANDY
    # ══════════════════════════════════════════════════════════════════════════

    # ── /hunger-balance ───────────────────────────────────────────────────────

    @app_commands.command(
        name="hunger-balance",
        description="[DM] Odečte hunger všem hráčům (simulace hladu v čase).",
    )
    @app_commands.describe(amount="Kolik hladu odečíst (výchozí: 5).")
    async def hunger_balance(self, interaction: discord.Interaction, amount: int = 5):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM může spouštět hunger balance.")
            return

        if amount < 1:
            await interaction.followup.send("❌ Množství musí být alespoň 1.")
            return

        data     = load_data()
        affected = 0
        starving = []

        for uid, profile in data.items():
            _ensure_player_fields(profile)
            profile["hunger_cur"] = max(0, profile["hunger_cur"] - amount)
            affected += 1
            if profile["hunger_cur"] == 0:
                starving.append(profile.get("name", uid))

        save_data(data)

        lines = [f"✅ Odečteno **{amount}** hladu od **{affected}** hráčů."]
        if starving:
            lines.append(f"\n🚨 Hladoví (hunger = 0): "
                         + ", ".join(f"**{n}**" for n in starving))
        await interaction.followup.send("\n".join(lines))

    # ── /profile-admin-hp ─────────────────────────────────────────────────────

    @app_commands.command(
        name="profile-admin-hp",
        description="[DM] Nastaví nebo upraví HP hráče.",
    )
    @app_commands.describe(
        member="Hráč.",
        hp_cur="Aktuální HP (vynech = beze změny).",
        hp_max="Maximální HP (vynech = beze změny).",
        damage="Odečti toto množství HP (použij buď damage nebo heal, ne oboje).",
        heal="Přičti toto množství HP.",
    )
    async def profile_admin_hp(
        self, interaction: discord.Interaction,
        member: discord.Member,
        hp_cur: Optional[int] = None,
        hp_max: Optional[int] = None,
        damage: Optional[int] = None,
        heal:   Optional[int] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return

        data    = load_data()
        uid     = str(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return

        _ensure_player_fields(profile)

        if hp_max is not None:
            profile["hp_max"] = max(1, hp_max)
        if hp_cur is not None:
            profile["hp_cur"] = max(0, min(profile["hp_max"], hp_cur))
        if damage is not None:
            profile["hp_cur"] = max(0, profile["hp_cur"] - damage)
        if heal is not None:
            profile["hp_cur"] = min(profile["hp_max"], profile["hp_cur"] + heal)

        save_data(data)

        bar = _bar(profile["hp_cur"], profile["hp_max"])
        await interaction.followup.send(
            f"✅ **{member.display_name}** — HP aktualizováno.\n"
            f"❤️  {bar}  {profile['hp_cur']}/{profile['hp_max']}"
        )

    # ── /profile-admin-mana ───────────────────────────────────────────────────

    @app_commands.command(
        name="profile-admin-mana",
        description="[DM] Nastaví nebo upraví manu hráče.",
    )
    @app_commands.describe(
        member="Hráč.",
        mana_cur="Aktuální mana (vynech = beze změny).",
        mana_max="Maximální mana (vynech = beze změny).",
        add="Přičti toto množství many.",
        remove="Odečti toto množství many.",
    )
    async def profile_admin_mana(
        self, interaction: discord.Interaction,
        member: discord.Member,
        mana_cur: Optional[int] = None,
        mana_max: Optional[int] = None,
        add:      Optional[int] = None,
        remove:   Optional[int] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        data    = load_data()
        uid     = str(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_player_fields(profile)
        if mana_max is not None:
            profile["mana_max"] = max(1, mana_max)
        if mana_cur is not None:
            profile["mana_cur"] = max(0, min(profile["mana_max"], mana_cur))
        if add is not None:
            profile["mana_cur"] = min(profile["mana_max"], profile["mana_cur"] + add)
        if remove is not None:
            profile["mana_cur"] = max(0, profile["mana_cur"] - remove)
        save_data(data)
        bar = _bar(profile["mana_cur"], profile["mana_max"])
        await interaction.followup.send(
            f"✅ **{member.display_name}** — mana aktualizována.\n"
            f"🔷  {bar}  {profile['mana_cur']}/{profile['mana_max']}"
        )

    # ── /profile-admin-fury ───────────────────────────────────────────────────

    @app_commands.command(
        name="profile-admin-fury",
        description="[DM] Nastaví nebo upraví furioku hráče.",
    )
    @app_commands.describe(
        member="Hráč.",
        fury_cur="Aktuální furioka (vynech = beze změny).",
        fury_max="Maximální furioka (vynech = beze změny).",
        add="Přičti toto množství furiok.",
        remove="Odečti toto množství furiok.",
    )
    async def profile_admin_fury(
        self, interaction: discord.Interaction,
        member: discord.Member,
        fury_cur: Optional[int] = None,
        fury_max: Optional[int] = None,
        add:      Optional[int] = None,
        remove:   Optional[int] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        data    = load_data()
        uid     = str(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_player_fields(profile)
        if fury_max is not None:
            profile["fury_max"] = max(1, fury_max)
        if fury_cur is not None:
            profile["fury_cur"] = max(0, min(profile["fury_max"], fury_cur))
        if add is not None:
            profile["fury_cur"] = min(profile["fury_max"], profile["fury_cur"] + add)
        if remove is not None:
            profile["fury_cur"] = max(0, profile["fury_cur"] - remove)
        save_data(data)
        bar = _bar(profile["fury_cur"], profile["fury_max"])
        await interaction.followup.send(
            f"✅ **{member.display_name}** — furioka aktualizována.\n"
            f"🔥  {bar}  {profile['fury_cur']}/{profile['fury_max']}"
        )

    # ── /profile-admin-vliv ───────────────────────────────────────────────────

    @app_commands.command(
        name="profile-admin-vliv",
        description="[DM] Nastav nebo uprav Vliv hráče (Světlo / Temnota / Rovnováha).",
    )
    @app_commands.describe(
        member="Hráč.",
        typ="Který Vliv upravuješ.",
        operace="set = přesná hodnota, add = přidat, remove = odebrat.",
        hodnota="Číslo.",
    )
    @app_commands.choices(
        typ=[
            app_commands.Choice(name="Světlo",    value="vliv_svetlo"),
            app_commands.Choice(name="Temnota",   value="vliv_temnota"),
            app_commands.Choice(name="Rovnováha", value="vliv_rovnovaha"),
        ],
        operace=[
            app_commands.Choice(name="set",    value="set"),
            app_commands.Choice(name="add",    value="add"),
            app_commands.Choice(name="remove", value="remove"),
        ],
    )
    async def profile_admin_vliv(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        typ: app_commands.Choice[str],
        operace: app_commands.Choice[str],
        hodnota: int,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        data    = load_data()
        uid     = str(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_player_fields(profile)
        key     = typ.value
        old_val = profile.get(key, 0)

        if operace.value == "set":
            profile[key] = max(0, hodnota)
        elif operace.value == "add":
            profile[key] = old_val + hodnota
        else:
            profile[key] = max(0, old_val - hodnota)

        # 1 Vliv = 5 max furioku — přepočítej fury_max a fury_cur
        _apply_vliv_fury(profile)

        save_data(data)
        icons = {"vliv_svetlo": "⚪", "vliv_temnota": "⚫", "vliv_rovnovaha": "⚖️"}
        await interaction.followup.send(
            f"✅ **{member.display_name}** — {icons[key]} {typ.name} nastaven na **{profile[key]}**.\n"
            f"🔥 Furioka: {profile['fury_cur']}/{profile['fury_max']}"
        )

    # ── /vliv ─────────────────────────────────────────────────────────────────

    @app_commands.command(
        name="vliv",
        description="[DM] Přidej hráči 1 bod Vlivu a pošli požehnání.",
    )
    @app_commands.describe(
        member="Hráč.",
        typ="Typ vlivu.",
        barva="Barva embedu v hex (např. ff0000). Výchozí dle typu.",
    )
    @app_commands.choices(typ=[
        app_commands.Choice(name="Světlo",    value="vliv_svetlo"),
        app_commands.Choice(name="Temnota",   value="vliv_temnota"),
        app_commands.Choice(name="Rovnováha", value="vliv_rovnovaha"),
    ])
    async def vliv_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        typ: app_commands.Choice[str],
        barva: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        data    = load_data()
        uid     = str(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_player_fields(profile)

        key = typ.value
        profile[key] = profile.get(key, 0) + 1
        _apply_vliv_fury(profile)
        save_data(data)

        # Výchozí barvy a texty dle typu
        defaults = {
            "vliv_svetlo":    (0xffffff, "⚪", "světlem",    "Světlo"),
            "vliv_temnota":   (0x111111, "⚫", "temnotou",   "Temnota"),
            "vliv_rovnovaha": (0x1a237e, "⚖️", "rovnováhou", "Rovnováha"),
        }
        def_color, icon, pozehnan_text, typ_name = defaults[key]

        try:
            color = int(barva.lstrip("#"), 16) if barva else def_color
        except ValueError:
            color = def_color

        embed = discord.Embed(
            description=(
                f"{member.mention} byl/a požehnán/a **{pozehnan_text}**.\n\n"
                f"-# {icon} {typ_name} {profile[key]}  ·  🔥 {profile['fury_cur']}/{profile['fury_max']} furioka"
            ),
            color=color,
        )
        await interaction.channel.send(embed=embed)
        await interaction.followup.send("✅ Vliv udělen.", ephemeral=True)

    # ── /admin-tutorial-reset ──────────────────────────────────────────────────

    @app_commands.command(
        name="admin-tutorial-reset",
        description="[ADMIN] Resetuje tutorial pro hráče — může ho znovu projít.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        hrac1="Hráč ke resetu",
        hrac2="(volitelný) další hráč",
        hrac3="(volitelný) další hráč",
        hrac4="(volitelný) další hráč",
        hrac5="(volitelný) další hráč",
    )
    async def admin_tutorial_reset(
        self,
        interaction: discord.Interaction,
        hrac1: discord.Member,
        hrac2: Optional[discord.Member] = None,
        hrac3: Optional[discord.Member] = None,
        hrac4: Optional[discord.Member] = None,
        hrac5: Optional[discord.Member] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        members = [m for m in [hrac1, hrac2, hrac3, hrac4, hrac5] if m is not None]

        DEST_ROLE_IDS = {
            1479574022130892890,  # lumenie
            1479573952832733314,  # aquion
            1479574079160979588,  # draci_skala
        }
        ROLE_DOBRODRUH_F3_ID = 1476056192643104768

        data    = load_data()
        economy = load_economy_data()

        results = []
        for member in members:
            uid     = str(member.id)
            changes = []

            if uid in data:
                del data[uid]
                changes.append("profil smazán")

            if uid in economy:
                del economy[uid]
                changes.append("zlaté resetovány")

            roles_to_remove = []
            for role in member.roles:
                if role.id in DEST_ROLE_IDS or role.id == ROLE_DOBRODRUH_F3_ID:
                    roles_to_remove.append(role)
            if roles_to_remove:
                try:
                    await member.remove_roles(*roles_to_remove, reason="Tutorial reset")
                    changes.append(f"{len(roles_to_remove)} role odebrány")
                except Exception as e:
                    changes.append(f"role — chyba: {e}")

            status = " · ".join(changes) if changes else "nic ke smazání"
            results.append(f"**{member.display_name}** — {status}")

        save_data(data)
        save_economy(economy)

        embed = discord.Embed(
            title="🔄  Tutorial Reset",
            description="\n".join(results),
            color=0xe74c3c,
        )
        embed.set_footer(text=f"Provedl: {interaction.user.display_name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @admin_tutorial_reset.error
    async def reset_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Nemáš oprávnění.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Profile(bot))
