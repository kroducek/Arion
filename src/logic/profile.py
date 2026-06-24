import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

from src.utils.paths import PROFILES as DATA_FILE, ECONOMY as ECONOMY_FILE, ITEMS as ITEMS_FILE, PLAYER_PERKS, ACHIEVEMENTS, REPUTATION
from src.utils.json_utils import load_json, save_json
from src.logic.stats import get_xp_cap, level_label, add_xp
from src.logic.economy import get_balance, set_balance, COIN_SILVER, COIN_STARDUST
from src.database.characters import pkey

# ══════════════════════════════════════════════════════════════════════════════
# DATOVÁ VRSTVA
# ══════════════════════════════════════════════════════════════════════════════

def load_data():
    return load_json(DATA_FILE)

def load_economy():
    """Load economy data (single source of truth)."""
    return load_json(ECONOMY_FILE)

def save_data(data):
    save_json(DATA_FILE, data)

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
    profile.setdefault("statuses",   [])   # aktivní statusy (jed/krvácení/…)
    profile.setdefault("vliv_svetlo",    0)
    profile.setdefault("vliv_temnota",   0)
    profile.setdefault("vliv_rovnovaha", 0)
    profile.setdefault("xp",         0)
    profile.setdefault("level",      1)
    profile.setdefault("inventory",  [])
    profile.setdefault("equipment",  {})
    profile.setdefault("bio",          "")
    profile.setdefault("title",        "")
    profile.setdefault("accent_color", None)

def _bar(current: int, maximum: int, width: int = 10) -> str:
    if maximum <= 0:
        return "░" * width
    filled = round(max(0, min(current, maximum)) / maximum * width)
    return "█" * filled + "░" * (width - filled)

HP_ON  = "<:hp:1490146344290222111>"
HP_OFF = "🤍"
MN_ON  = "<:mana:1490148547427831981>"
MN_OFF = "⚪"
HN_ON  = "<:hunger:1490169001890807928>"
HN_OFF = "🦴"
FU_EMO = "<:furioku:1490160933081972866>"
MEM_EMO = "<:memory:1490167924768510083>"
XP_EMO  = "<:xp:1490159053425348748>"
VLIV_EMO    = "<:vliv:1490162671969112085>"
SVETLO_EMO  = "<:svetlo:1490166284741120120>"
TEMNOTA_EMO = "<:temnota:1490166345516581034>"
ROVNO_EMO   = "<:rovnovaha:1490166409458749671>"
COIN        = "<:goldcoin:1490171741237018795>"
SPIRIT_EMO  = "👻"

def _heart_bar(current: int, maximum: int, slots: int = 10) -> str:
    if maximum <= 0:
        return "▫️" * slots
    filled = round(max(0, min(current, maximum)) / maximum * slots)
    return "♥️" * filled + "▫️" * (slots - filled)

def _hunger_bar(current: int, maximum: int, slots: int = 10) -> str:
    if maximum <= 0:
        return "▫️" * slots
    filled = round(max(0, min(current, maximum)) / maximum * slots)
    return "🔸" * filled + "▫️" * (slots - filled)

def _mana_bar(current: int, maximum: int, slots: int = 10) -> str:
    if maximum <= 0:
        return "▫️" * slots
    filled = round(max(0, min(current, maximum)) / maximum * slots)
    return "🔹" * filled + "▫️" * (slots - filled)

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
    profile   = data.get(pkey(interaction.user.id), {})
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
        uid  = pkey(interaction.user.id)
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
        uid  = pkey(interaction.user.id)
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
        uid  = pkey(interaction.user.id)
        data.setdefault(uid, {})["portrait_url"] = self.url.value
        save_data(data)
        await interaction.response.send_message(
            "✅ Portrét byl aktualizován.", ephemeral=True
        )


class EditTitleModal(discord.ui.Modal, title="Upravit titul / epiteton"):
    titul = discord.ui.TextInput(
        label="Titul postavy (krátký taglinek)",
        placeholder="např. Popel z Lumenie",
        required=False,
        max_length=64,
    )

    async def on_submit(self, interaction: discord.Interaction):
        data = load_data()
        uid  = pkey(interaction.user.id)
        data.setdefault(uid, {})["title"] = self.titul.value.strip()
        save_data(data)
        await interaction.response.send_message("\u2705 Titul aktualizován.", ephemeral=True)


class EditBioModal(discord.ui.Modal, title="Upravit bio / lore"):
    bio = discord.ui.TextInput(
        label="Bio postavy",
        style=discord.TextStyle.paragraph,
        placeholder="Kdo je tvá postava? Odkud přišla, co ji žene\u2026",
        required=False,
        max_length=600,
    )

    async def on_submit(self, interaction: discord.Interaction):
        data = load_data()
        uid  = pkey(interaction.user.id)
        data.setdefault(uid, {})["bio"] = self.bio.value.strip()
        save_data(data)
        await interaction.response.send_message("\u2705 Bio aktualizováno.", ephemeral=True)


class EditAccentModal(discord.ui.Modal, title="Barva karty"):
    barva = discord.ui.TextInput(
        label="Hex barva (např. 3498db nebo #e74c3c)",
        placeholder="prázdné = výchozí",
        required=False,
        max_length=7,
    )

    async def on_submit(self, interaction: discord.Interaction):
        raw  = self.barva.value.strip().lstrip("#")
        data = load_data()
        uid  = pkey(interaction.user.id)
        if not raw:
            data.setdefault(uid, {})["accent_color"] = None
            save_data(data)
            await interaction.response.send_message("\u2705 Barva nastavena na výchozí.", ephemeral=True)
            return
        try:
            val = int(raw, 16)
            if not (0 <= val <= 0xFFFFFF):
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "\u274c Neplatná hex barva. Zadej třeba `3498db`.", ephemeral=True)
            return
        data.setdefault(uid, {})["accent_color"] = val
        save_data(data)
        await interaction.response.send_message(f"\u2705 Barva karty nastavena na `#{raw.lower()}`.", ephemeral=True)


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

    @discord.ui.button(label="Titul", style=discord.ButtonStyle.secondary, emoji="🏷️")
    async def edit_title(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditTitleModal())

    @discord.ui.button(label="Bio", style=discord.ButtonStyle.secondary, emoji="📖")
    async def edit_bio(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditBioModal())

    @discord.ui.button(label="Barva", style=discord.ButtonStyle.secondary, emoji="🎨")
    async def edit_accent(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditAccentModal())

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
# STRÁŽNÝ DUCH — importováno z spirits.py
# ══════════════════════════════════════════════════════════════════════════════
from src.logic.spirits import get_equipped_spirit, fury_display

# ══════════════════════════════════════════════════════════════════════════════

def _build_prukaz_embed(target, profile) -> discord.Embed:
    """Lore strana — vizitka postavy (text, obrázek, měny)."""
    user_id      = pkey(target.id)
    char_name    = profile.get("name", target.display_name)
    title        = profile.get("title", "")
    economy      = load_economy()
    balance      = economy.get(user_id, 0)
    silver_bal   = get_balance(target.id, "silver")
    stardust_bal = get_balance(target.id, "stardust")
    equipped_spirit = get_equipped_spirit(profile)

    lines = []
    if title:
        lines.append(f"\U0001f4ac *{title}*")
    lines.append(f"\U0001f396\ufe0f Rank: **{profile.get('rank', 'F3')}**")
    lines.append(f"-# {COIN} **{balance}**  \u00b7  {COIN_SILVER} **{silver_bal}**  \u00b7  {COIN_STARDUST} **{stardust_bal}**")
    if equipped_spirit:
        sf = f"+{equipped_spirit['fury']}" if equipped_spirit["fury"] > 0 else str(equipped_spirit["fury"])
        lines.append(f"-# {SPIRIT_EMO} *Strážný duch: {equipped_spirit['name']} ({sf} {FU_EMO})*")

    bio = profile.get("bio", "")
    if bio:
        lines.append("")
        lines.append(bio)

    if profile.get("motivation"):
        lines.append("")
        lines.append(f"\u2728  {profile['motivation']}")

    memories = profile.get("memories", [])
    if memories:
        mem = memories[-1]
        if len(mem) > 1020:
            mem = mem[:1020] + "\u2026"
        lines.append("")
        lines.append(f"{MEM_EMO} **Poslední vzpomínka**")
        lines.append(f"*{mem}*")

    active_card_id = profile.get("active_card_id")
    if active_card_id:
        try:
            from src.utils.paths import CARDS_INVENTORY
            cards_inv = load_json(CARDS_INVENTORY, {})
            card = cards_inv.get(active_card_id)
            if card:
                print_num = card.get("print_number", "?")
                qual = card.get("quality", "normal")
                qual_icon = {"shiny": "\u2728", "gold": "\U0001f947", "normal": "\u26aa", "damaged": "\U0001f494"}.get(qual, "\u26aa")
                lines.append("")
                lines.append("\U0001f3b4 **Reprezentativní karta**")
                lines.append(f"*{card.get('name')}  \u00b7  Print #{print_num}  \u00b7  {qual_icon} {qual.capitalize()}  \u00b7  ID: `{active_card_id}`*")
        except Exception:
            pass

    color = profile.get("accent_color") or 0x3498db
    embed = discord.Embed(
        title=f"\U0001faaa  Průkaz dobrodruha: {char_name}",
        description="\n".join(lines),
        color=color,
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    if profile.get("portrait_url"):
        embed.set_image(url=profile["portrait_url"])
    embed.set_footer(text=f"ID: {user_id}  \u00b7  Act: Aurionis \u00b7 Act II")
    return embed


def _build_stats_embed(target, profile, guild_id=None) -> discord.Embed:
    """Progress strana — čísla (staty, XP, atributy, vliv, reputace)."""
    user_id   = pkey(target.id)
    char_name = profile.get("name", target.display_name)
    items_db  = _load_items()

    hp_cur = profile.get("hp_cur", 50); hp_max = profile.get("hp_max", 50)
    hunger_cur = profile.get("hunger_cur", 10); hunger_max = profile.get("hunger_max", 10)
    mana_cur = profile.get("mana_cur", 0); mana_max = profile.get("mana_max", 5)
    fury_cur, fury_max, spirit_bonus = fury_display(profile)
    equipped_spirit = get_equipped_spirit(profile)
    v_svetlo = profile.get("vliv_svetlo", 0)
    v_temnota = profile.get("vliv_temnota", 0)
    v_rovno = profile.get("vliv_rovnovaha", 0)
    level = profile.get("level", 0)
    xp = profile.get("xp", 0)
    sp = profile.get("sp", 0)
    cap = get_xp_cap(level)
    total_def = _compute_total_def(profile, items_db)

    hp_bar = _heart_bar(hp_cur, hp_max)
    hunger_bar = _hunger_bar(hunger_cur, hunger_max)
    mana_bar = _mana_bar(mana_cur, mana_max)
    fury_total = fury_cur + spirit_bonus
    fury_bar = _bar(fury_total, fury_max + spirit_bonus if fury_max > 0 else 1)
    xp_bar = _bar(xp, cap if cap else 1)
    def_str = f"  \u00b7  \U0001f6e1\ufe0f **{total_def}** DEF" if total_def else ""
    xp_str = f"{xp} (MAX)" if not cap else f"{xp}/{cap}"
    sp_str = f"  \u26a1 **{sp}** SP" if sp > 0 else ""

    lines = []
    lines.append(f"{HP_ON} Zdraví:  {hp_bar}  \u00b7  {hp_cur}/{hp_max}{def_str}")
    lines.append(f"{MN_ON} Mana:  {mana_bar}  \u00b7  {mana_cur}/{mana_max}")
    lines.append(f"{HN_ON} Hlad:  {hunger_bar}  \u00b7  {hunger_cur}/{hunger_max}")
    if spirit_bonus > 0 and equipped_spirit:
        fury_display_str = f"{fury_cur}/{fury_max}  *(+{spirit_bonus} od {equipped_spirit['name']})*"
    else:
        fury_display_str = f"{fury_cur}/{fury_max}"
    lines.append(f"{FU_EMO} Furioka:  {fury_bar}  \u00b7  {fury_display_str}")
    lines.append(f"\u00b7  **{level_label(level)}**  \u00b7  {XP_EMO}  {xp_bar}  \u00b7  {xp_str}{sp_str}")

    active_statuses = profile.get("statuses") or []
    if active_statuses:
        try:
            from src.core.dnd.blacksmith import load_statuses
            _sreg = load_statuses()
        except Exception:
            _sreg = {}
        icons = "".join(_sreg.get(st.get("status"), {}).get("emoji", "\u2022") for st in active_statuses)
        lines.append(f"\U0001fa78 Statusy:  {icons}  *(detail v `/quicksheet`)*")

    lines.append(f"{VLIV_EMO}  {SVETLO_EMO} **{v_svetlo}**  \u00b7  {TEMNOTA_EMO} **{v_temnota}**  \u00b7  {ROVNO_EMO} **{v_rovno}**")
    lines.append("-# 1 Vliv = 5 furiok")

    stats = profile.get("stats", {})
    if stats:
        lines.append("")
        stats_line = "  \u00b7  ".join(f"**{k}** {v}" for k, v in stats.items())
        lines.append(f"-# {stats_line}")

    if guild_id is not None:
        try:
            rep_all = load_json(REPUTATION, {})
            g = rep_all.get(str(guild_id), {})
            reps = g.get("players", {}).get(user_id, {})
            rep_line = "  \u00b7  ".join(f"{f} `{v:+d}`" for f, v in reps.items() if v)
            if rep_line:
                lines.append("")
                lines.append(f"\U0001f4dc Reputace:  {rep_line}")
        except Exception:
            pass

    try:
        pp_data  = load_json(PLAYER_PERKS, {})
        ach_data = load_json(ACHIEVEMENTS, {})
        perk_cnt = len(pp_data.get(user_id, {}).get("perks", []))
        ach_cnt  = len(ach_data.get(str(target.id), []))   # achievementy = účet (holé)
        lines.append("")
        lines.append(f"\U0001f3f7\ufe0f Perky: **{perk_cnt}**  \u00b7  \U0001f3c6 Achievementy: **{ach_cnt}**")
    except Exception:
        pass

    color = profile.get("accent_color") or 0x2ecc71
    embed = discord.Embed(
        title=f"\U0001f4ca  Staty: {char_name}",
        description="\n".join(lines),
        color=color,
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.set_footer(text=f"ID: {user_id}  \u00b7  Act: Aurionis \u00b7 Act II")
    return embed


class ProfileView(discord.ui.View):
    def __init__(self, target, guild_id, can_edit: bool):
        super().__init__(timeout=300)
        self.target   = target
        self.guild_id = guild_id
        self.owner_id = target.id
        if not can_edit:
            self.remove_item(self.edit_btn)

    def _load_profile(self):
        data = load_data()
        profile = data.get(pkey(self.target.id))
        if profile:
            _ensure_player_fields(profile)
        return profile

    @discord.ui.button(label="Průkaz", style=discord.ButtonStyle.primary, emoji="🪪")
    async def prukaz_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        profile = self._load_profile()
        if not profile:
            await interaction.response.send_message("Průkaz už neexistuje.", ephemeral=True)
            return
        await interaction.response.edit_message(embed=_build_prukaz_embed(self.target, profile), view=self)

    @discord.ui.button(label="Staty", style=discord.ButtonStyle.success, emoji="📊")
    async def stats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        profile = self._load_profile()
        if not profile:
            await interaction.response.send_message("Průkaz už neexistuje.", ephemeral=True)
            return
        await interaction.response.edit_message(embed=_build_stats_embed(self.target, profile, self.guild_id), view=self)

    @discord.ui.button(label="Upravit", style=discord.ButtonStyle.secondary, emoji="✏️", row=1)
    async def edit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Tohle není tvůj průkaz.", ephemeral=True)
            return
        data = load_data()
        uid  = pkey(interaction.user.id)
        if uid not in data or not data[uid].get("gold_received"):
            await interaction.response.send_message(
                "Průkaz můžeš upravit až po dokončení tutoriálu.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Co chceš na průkazu upravit?", view=EditProfileView(), ephemeral=True)


class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /profile ───────────────────────────────────────────────────────────────

    @app_commands.command(name="profile", description="Zobrazí tvůj dobrodružný průkaz.")
    @app_commands.describe(member="Hráč (výchozí: ty).")
    async def profile(self, interaction: discord.Interaction,
                      member: Optional[discord.Member] = None):
        target  = member or interaction.user
        data    = load_data()
        user_id = pkey(target.id)

        if user_id not in data:
            await interaction.response.send_message(
                f"**{target.display_name}** zatím nemá průkaz dobrodruha. Musí projít tutoriálem!",
                ephemeral=True,
            )
            return

        profile = data[user_id]
        _ensure_player_fields(profile)

        embed    = _build_prukaz_embed(target, profile)
        can_edit = (target.id == interaction.user.id)
        guild_id = interaction.guild.id if interaction.guild else None
        view     = ProfileView(target, guild_id, can_edit)
        await interaction.response.send_message(embed=embed, view=view)


    # ── /eat ───────────────────────────────────────────────────────────────────

    @app_commands.command(name="eat", description="Sní jídlo z inventáře a doplní hlad.")
    @app_commands.describe(item="Jídlo z inventáře.")
    @app_commands.autocomplete(item=_ac_food_item)
    async def eat(self, interaction: discord.Interaction, item: str):
        await interaction.response.defer(ephemeral=True)
        data    = load_data()
        user_id = pkey(interaction.user.id)
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
        uid     = pkey(member.id)
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

        bar = _heart_bar(profile["hp_cur"], profile["hp_max"])
        await interaction.followup.send(
            f"✅ **{member.display_name}** — HP aktualizováno.\n"
            f"{bar}  {profile['hp_cur']}/{profile['hp_max']}"
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
        uid     = pkey(member.id)
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
        uid     = pkey(member.id)
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
        uid     = pkey(member.id)
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
        uid     = pkey(member.id)
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
        economy = load_economy()
        player_perks = load_json(PLAYER_PERKS, default={})
        achievements = load_json(ACHIEVEMENTS, default={})

        results = []
        for member in members:
            uid     = pkey(member.id)
            changes = []

            if uid in data:
                del data[uid]
                changes.append("profil smazán")

            if uid in economy:
                del economy[uid]
                changes.append("zlaté resetovány")

            if get_balance(member.id, "silver") or get_balance(member.id, "stardust"):
                set_balance(member.id, 0, "silver")
                set_balance(member.id, 0, "stardust")
                changes.append("stříbro a prach resetovány")

            if uid in player_perks:
                del player_perks[uid]
                changes.append("perky resetovány")

            _acct = str(member.id)
            if _acct in achievements and "Vítej v Aurionisu" in achievements[_acct]:
                achievements[_acct].remove("Vítej v Aurionisu")
                if not achievements[_acct]:
                    del achievements[_acct]
                changes.append("tutorial achievement odebrán")

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
        save_json(PLAYER_PERKS, player_perks)
        save_json(ACHIEVEMENTS, achievements)

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