import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import random
from datetime import date

from src.utils.paths import PERKS, PLAYER_PERKS
from src.utils.audit import log_action

ARION_NAME = "Aurionis"

# ── Skupiny a barvy ───────────────────────────────────────────────────────────

GROUP_ORDER = ["Furioku", "Magie", "Pasivky", "Temnota", "Světlo", "Unikátní"]
GROUP_EMOJI = {
    "Furioku":  "👻",
    "Magie":    "🔮",
    "Pasivky":  "🛡️",
    "Temnota":  "🌑",
    "Světlo":   "☀️",
    "Unikátní": "⭐",
}
GROUP_COLOR = {
    "Furioku":  0x7B68EE,
    "Magie":    0x9B59B6,
    "Pasivky":  0x95A5A6,
    "Temnota":  0x2C2F33,
    "Světlo":   0xFFD700,
    "Unikátní": 0xFF6B35,
}

# ── Seed databáze perků ───────────────────────────────────────────────────────
# unique=True → perk není v náhodném poolu (/give-random-perk)

_SEED_PERKS: dict[str, dict] = {
    # ── Furioku ──────────────────────────────────────────────────────────────
    "furioku_promena": {
        "name": "Furioku: Proměna",
        "group": "Furioku",
        "passive": False,
        "unique": False,
        "desc": "Proměníš se v duši, máš přesně dvě použití na den. Jedno na proměnu v duši a jedno na proměnu zpět v člověka.",
        "subdesc": None,
        "cooldown_uses": 2,
        "cooldown_type": "daily",
    },
    "furioku_odhaleni": {
        "name": "Furioku: Odhalení",
        "group": "Furioku",
        "passive": False,
        "unique": False,
        "desc": "Okolo tvé ruky se objeví malí duchové (rarita podle lokace), duchy můžeš následně pohltit či jinak využít.",
        "subdesc": None,
        "cooldown_uses": 2,
        "cooldown_type": "daily",
    },
    "furioku_kombinovany_utok": {
        "name": "Furioku: Kombinovaný útok",
        "group": "Furioku",
        "passive": True,
        "unique": False,
        "desc": "Ty a ten, se kterým útok provádíš, můžete zkombinovat své útoky do jednoho kombinovaného.",
        "subdesc": "Vyžaduje, aby oba vlastnili tento perk.",
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "furioku_zrychleni": {
        "name": "Furioku: Zrychlení",
        "group": "Furioku",
        "passive": True,
        "unique": False,
        "desc": "Ve formě duše se můžeš pohybovat velmi rychle. Ve formě humanoida vyžaduje aktivaci furioku.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "furioku_odrazeni": {
        "name": "Furioku: Odražení",
        "group": "Furioku",
        "passive": True,
        "unique": False,
        "desc": "Pokud je tvá furioku větší než soupeřova, odrazíš ho. Ve formě duše nevyžaduje aktivaci. Odražení nedává dmg, max. následky (fall).",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "furioku_jednota": {
        "name": "Furioku: Jednota",
        "group": "Furioku",
        "passive": True,
        "unique": False,
        "desc": "Ty a Duch, se kterým máš vytvořené pouto, dokážete sjednotit své duše a pracovat v Jednotě.",
        "subdesc": "Furioku se v Jednotě sloučí. Můžeš využívat speciální schopnosti a atributy ducha.",
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "furioku_trhlina": {
        "name": "Furioku: Trhlina",
        "group": "Furioku",
        "passive": False,
        "unique": False,
        "desc": "Multidimenzionální trhlina tě vezme na jedno místo, kam si hra myslí, že chceš nejvíc. Velmi nebezpečné používat.",
        "subdesc": None,
        "cooldown_uses": 1,
        "cooldown_type": "daily",
    },
    "furioku_obrana": {
        "name": "Furioku: Obrana",
        "group": "Furioku",
        "passive": True,
        "unique": False,
        "desc": "Využiješ své furioku jako auru na obranu těla. Funguje jako DEF — vynaložená furioku poskytuje ekvivalentní bonus k obraně.",
        "subdesc": "Využiješ např. 10 furioku → +10 DEF. DMG ničí využívanou furioku.",
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    # ── Magie ─────────────────────────────────────────────────────────────────
    "zprava": {
        "name": "Zpráva",
        "group": "Magie",
        "passive": False,
        "unique": False,
        "desc": "Můžeš poslat magický dopis někomu, s kým máš blízký vztah. Funguje přes celou mapu a osoba ti může odpovědět nazpět.",
        "subdesc": None,
        "cooldown_uses": 1,
        "cooldown_type": "daily",
    },
    "magicke_citeni": {
        "name": "Magické cítění",
        "group": "Magie",
        "passive": True,
        "unique": False,
        "desc": "Cítíš přítomnost magie ve svém okolí — její směr, intenzitu a neklid. Pokud se pokusíš magii aktivně zaměřit nebo rozlišit, vyžaduje to hod na Inteligenci.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    # ── Pasivky ───────────────────────────────────────────────────────────────
    "instinkt_preziti": {
        "name": "Instinkt přežití",
        "group": "Pasivky",
        "passive": True,
        "unique": False,
        "desc": "Tělo i mysl reagují dřív než rozum. Při odhalování pastí +2 k instincts.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "ohnizdorny": {
        "name": "Ohnivzdorný",
        "group": "Pasivky",
        "passive": True,
        "unique": False,
        "desc": "Oheň ti již nemůže ublížit.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "zabry": {
        "name": "Žábry",
        "group": "Pasivky",
        "passive": True,
        "unique": False,
        "desc": "Magické žábry ti narostou vždy, když budeš pod vodou. Umíš dýchat pod vodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "farmar": {
        "name": "Farmář",
        "group": "Pasivky",
        "passive": True,
        "unique": False,
        "desc": "Země ti přeje. Pokud vlastníš farmu, každá zasazená úroda dozraje během jednoho dne.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    # ── Temnota ───────────────────────────────────────────────────────────────
    "temna_pritomnost": {
        "name": "Temná přítomnost",
        "group": "Temnota",
        "passive": False,
        "unique": False,
        "desc": "Okamžitě ucítíš přítomnost živých bytostí až do kilometru daleko a temnota tě k nim dovede.",
        "subdesc": None,
        "cooldown_uses": 2,
        "cooldown_type": "daily",
    },
    # ── Světlo ────────────────────────────────────────────────────────────────
    "vyslanec_svetla": {
        "name": "Vyslanec světla",
        "group": "Světlo",
        "passive": True,
        "unique": False,
        "desc": "Jsi imunní vůči temnotě — temné útoky tě nezasáhnou, kletby na tebe nefungují.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "pozehani": {
        "name": "Požehnání",
        "group": "Světlo",
        "passive": False,
        "unique": False,
        "desc": "Pokud je den a svítí slunce, můžeš načerpat požehnání od světla. +10 heal HP, +10 heal mana. Zvyšuje jakýkoliv ohnivý DMG o 1d2, pokud jsi požehnán.",
        "subdesc": None,
        "cooldown_uses": 1,
        "cooldown_type": "daily",
    },
    "svetlo_lumeniovo": {
        "name": "Světlo Lumeniovo",
        "group": "Světlo",
        "passive": False,
        "unique": False,
        "desc": "Na pár minut (15–20) vytvoříš levitující kouli světla, která se pohybuje tam, kam ty jdeš, a osvěcuje prostor kolem tebe.",
        "subdesc": None,
        "cooldown_uses": 2,
        "cooldown_type": "daily",
    },
    # ── Unikátní (nejsou v náhodném poolu) ───────────────────────────────────
    "restart": {
        "name": "Restart",
        "group": "Unikátní",
        "passive": True,
        "unique": True,
        "desc": "Pokud zemřeš, Noxarath tě oživí a objevíš se na náhodném místě. Ztratíš část XP a sanity.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "vahy_spravedlnosti": {
        "name": "Váhy spravedlnosti",
        "group": "Unikátní",
        "passive": False,
        "unique": True,
        "desc": "Nad nepřítelem vytvoříš magické váhy, které ho soudí za jeho činy.",
        "subdesc": None,
        "cooldown_uses": 2,
        "cooldown_type": "daily",
    },
}

_SYNC_FIELDS = {"name", "group", "passive", "unique", "desc", "subdesc", "cooldown_uses", "cooldown_type"}
_LEGACY_IDS  = {"terra", "ignis", "zaklady_bendingu", "vaha_svobody"}

# ── Storage ───────────────────────────────────────────────────────────────────

def load_perks() -> dict:
    if not os.path.exists(PERKS):
        return {}
    try:
        with open(PERKS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_perks(data: dict):
    with open(PERKS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_player_perks() -> dict:
    if not os.path.exists(PLAYER_PERKS):
        return {}
    try:
        with open(PLAYER_PERKS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_player_perks(data: dict):
    with open(PLAYER_PERKS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _get_player(uid_str: str, data: dict) -> dict:
    data.setdefault(uid_str, {"perks": [], "cooldowns": {}})
    p = data[uid_str]
    p.setdefault("perks", [])
    p.setdefault("cooldowns", {})
    return p

# ── Migrace ───────────────────────────────────────────────────────────────────

def _migrate_perks():
    perks   = load_perks()
    changed = False
    for lid in _LEGACY_IDS:
        if lid in perks:
            del perks[lid]
            changed = True
    for pid, seed in _SEED_PERKS.items():
        if pid not in perks:
            perks[pid] = seed
            changed = True
        else:
            for field in _SYNC_FIELDS:
                if perks[pid].get(field) != seed.get(field):
                    perks[pid][field] = seed[field]
                    changed = True
    if changed:
        save_perks(perks)
        print("[perks] Migrace dokončena.")

# ── Cooldown helpers ──────────────────────────────────────────────────────────

def _check_and_use_cooldown(player: dict, perk_id: str, perk: dict) -> tuple[bool, str]:
    today = date.today().isoformat()
    cd    = player["cooldowns"].get(perk_id, {"used": 0, "date": today})
    if cd["date"] != today:
        cd = {"used": 0, "date": today}
    used = cd["used"]
    max_ = perk.get("cooldown_uses", 0)
    if max_ > 0 and used >= max_:
        return False, f"Dnes již použito **{used}/{max_}×**. Reset při půlnoci."
    if max_ > 0:
        cd["used"] = used + 1
        cd["date"] = today
        player["cooldowns"][perk_id] = cd
    return True, ""

def _cooldown_bar(used: int, max_: int) -> str:
    return f"`{'▰' * used}{'▱' * (max_ - used)}` · {used}/{max_}×"

def _cooldown_status(player: dict, perk_id: str, perk: dict) -> str:
    max_ = perk.get("cooldown_uses", 0)
    if max_ == 0:
        return ""
    today = date.today().isoformat()
    cd    = player.get("cooldowns", {}).get(perk_id, {"used": 0, "date": today})
    used  = cd["used"] if cd.get("date") == today else 0
    done  = " ✅" if used >= max_ else ""
    return f"⏳ {_cooldown_bar(used, max_)}{done} dnes"

# ── Announce helpers ──────────────────────────────────────────────────────────

def _perk_announce_embed(member: discord.Member, perk_id: str, perk: dict, used: int) -> discord.Embed:
    group  = perk.get("group", "")
    color  = GROUP_COLOR.get(group, 0xFFD700)
    gemoji = GROUP_EMOJI.get(group, "✨")
    max_   = perk.get("cooldown_uses", 0)

    desc = f"### {gemoji} {perk['name']}\n{perk['desc']}"
    if perk.get("subdesc"):
        desc += f"\n-# {perk['subdesc']}"
    if max_ > 0:
        desc += f"\n\n⏳ {_cooldown_bar(used, max_)} dnes"

    embed = discord.Embed(
        title=f"✨ {member.display_name} aktivoval perk!",
        description=desc,
        color=color,
    )
    embed.set_footer(text=f"⭐ {ARION_NAME}")
    return embed

async def _dm_perk(member: discord.Member, perk: dict, perk_id: str):
    group  = perk.get("group", "")
    gemoji = GROUP_EMOJI.get(group, "✨")
    color  = GROUP_COLOR.get(group, 0xFFD700)
    desc   = f"**{perk['name']}**\n{perk['desc']}"
    if perk.get("subdesc"):
        desc += f"\n-# {perk['subdesc']}"
    max_  = perk.get("cooldown_uses", 0)
    embed = discord.Embed(
        title=f"{gemoji}  Získal/a jsi perk!",
        description=desc,
        color=color,
    )
    if max_ > 0:
        embed.add_field(name="⏳ Cooldown", value=f"{max_}×/den", inline=True)
    embed.set_footer(text=f"⭐ {ARION_NAME}  ·  Použij /perk use k aktivaci")
    try:
        await member.send(embed=embed)
    except discord.Forbidden:
        pass

# ── Modaly ────────────────────────────────────────────────────────────────────

class PerkNewModal(discord.ui.Modal, title="Nový perk"):
    perk_id    = discord.ui.TextInput(label="ID perku (snake_case)", placeholder="napr_novy_perk", max_length=60)
    perk_name  = discord.ui.TextInput(label="Název", max_length=80)
    perk_group = discord.ui.TextInput(label="Skupina", placeholder="Furioku / Magie / Světlo / Unikátní / ...", max_length=40)
    perk_desc  = discord.ui.TextInput(label="Popis", style=discord.TextStyle.paragraph, max_length=500)
    perk_cd    = discord.ui.TextInput(label="Cooldown (počet/den, 0=žádný)", placeholder="0", max_length=3, default="0")

    async def on_submit(self, interaction: discord.Interaction):
        pid = self.perk_id.value.strip().lower().replace(" ", "_")
        try:
            cd_uses = int(self.perk_cd.value.strip())
        except ValueError:
            cd_uses = 0
        perks = load_perks()
        perks[pid] = {
            "name":          self.perk_name.value.strip(),
            "group":         self.perk_group.value.strip(),
            "passive":       False,
            "unique":        False,
            "desc":          self.perk_desc.value.strip(),
            "subdesc":       None,
            "cooldown_uses": cd_uses,
            "cooldown_type": "daily" if cd_uses > 0 else None,
        }
        save_perks(perks)
        await interaction.response.send_message(
            f"✅ Perk **{perks[pid]['name']}** (`{pid}`) přidán do databáze.", ephemeral=True
        )


class PerkEditModal(discord.ui.Modal, title="Upravit perk"):
    perk_name  = discord.ui.TextInput(label="Název", max_length=80)
    perk_group = discord.ui.TextInput(label="Skupina", max_length=40)
    perk_desc  = discord.ui.TextInput(label="Popis", style=discord.TextStyle.paragraph, max_length=500)
    perk_subd  = discord.ui.TextInput(label="Subdesc (prázdné = žádný)", style=discord.TextStyle.paragraph, max_length=300, required=False)
    perk_cd    = discord.ui.TextInput(label="Cooldown (počet/den, 0=žádný)", max_length=3)

    def __init__(self, perk_id: str, perk: dict):
        super().__init__()
        self._perk_id       = perk_id
        self.perk_name.default  = perk.get("name", "")
        self.perk_group.default = perk.get("group", "")
        self.perk_desc.default  = perk.get("desc", "")
        self.perk_subd.default  = perk.get("subdesc") or ""
        self.perk_cd.default    = str(perk.get("cooldown_uses", 0))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cd_uses = int(self.perk_cd.value.strip())
        except ValueError:
            cd_uses = 0
        perks = load_perks()
        if self._perk_id not in perks:
            await interaction.response.send_message("Perk mezitím zmizel z databáze.", ephemeral=True)
            return
        p = perks[self._perk_id]
        p["name"]          = self.perk_name.value.strip()
        p["group"]         = self.perk_group.value.strip()
        p["desc"]          = self.perk_desc.value.strip()
        p["subdesc"]       = self.perk_subd.value.strip() or None
        p["cooldown_uses"] = cd_uses
        p["cooldown_type"] = "daily" if cd_uses > 0 else None
        save_perks(perks)
        await interaction.response.send_message(f"✅ Perk **{p['name']}** upraven.", ephemeral=True)


# ── Cog ───────────────────────────────────────────────────────────────────────

class PerksCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _migrate_perks()

    # ── /perks skupina ───────────────────────────────────────────────────────

    perks_group = app_commands.Group(name="perks", description="Perky hráčů")

    @perks_group.command(name="show", description="Zobraz perky hráče")
    @app_commands.describe(member="Hráč (výchozí: ty)")
    async def perks_show(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target      = member or interaction.user
        all_perks   = load_perks()
        player_data = load_player_perks()
        player      = _get_player(str(target.id), player_data)
        owned       = player["perks"]

        if not owned:
            is_self = target.id == interaction.user.id
            msg = "Nemáš žádné perky." if is_self else f"**{target.display_name}** nemá žádné perky."
            await interaction.response.send_message(msg, ephemeral=True)
            return

        unique_list:  list[tuple[str, dict]] = []
        cooldown_list: list[tuple[str, dict]] = []
        passive_list:  list[tuple[str, dict]] = []

        for pid in owned:
            p = all_perks.get(pid)
            if not p:
                continue
            if p.get("unique"):
                unique_list.append((pid, p))
            elif not p.get("passive"):
                cooldown_list.append((pid, p))
            else:
                passive_list.append((pid, p))

        def fmt_entry(pid: str, p: dict) -> list[str]:
            gemoji     = GROUP_EMOJI.get(p.get("group", ""), "▸")
            passive_tag = " *(pasivní)*" if p.get("passive") else ""
            lines = [f"▸ {gemoji} **{p['name']}**{passive_tag}"]
            cd_str = _cooldown_status(player, pid, p)
            lines.append(f"-# {cd_str}  ·  `{pid}`" if cd_str else f"-# `{pid}`")
            return lines

        sections: list[str] = []
        if unique_list:
            sections.append("\n⭐ **Unikátní**")
            for pid, p in unique_list:
                sections.extend(fmt_entry(pid, p))
        if cooldown_list:
            sections.append("\n⚡ **S Cooldownem**")
            for pid, p in cooldown_list:
                sections.extend(fmt_entry(pid, p))
        if passive_list:
            sections.append("\n🛡️ **Pasivní**")
            for pid, p in passive_list:
                sections.extend(fmt_entry(pid, p))

        is_self = target.id == interaction.user.id
        title   = "Tvoje perky" if is_self else f"Perky — {target.display_name}"
        desc    = f"### 🏷️ {title}" + "\n".join(sections)
        desc   += f"\n\n-# *Celkem perků: {len(owned)}  ·  /perk use — aktivuj perk*"

        embed = discord.Embed(description=desc, color=0x7B68EE)
        embed.set_footer(text=f"⭐ {ARION_NAME}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @perks_group.command(name="give", description="Přiřaď perk hráči (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(perk_id="ID perku", member="Hráč")
    async def perks_give(self, interaction: discord.Interaction, perk_id: str, member: discord.Member):
        all_perks = load_perks()
        if perk_id not in all_perks:
            await interaction.response.send_message(f"Perk `{perk_id}` neexistuje.", ephemeral=True)
            return
        player_data = load_player_perks()
        player      = _get_player(str(member.id), player_data)
        if perk_id in player["perks"]:
            await interaction.response.send_message(
                f"{member.mention} už má **{all_perks[perk_id]['name']}**.", ephemeral=True
            )
            return
        player["perks"].append(perk_id)
        save_player_perks(player_data)
        log_action("perk_give", interaction.user.display_name, member.display_name, perk_id)

        perk   = all_perks[perk_id]
        await _dm_perk(member, perk, perk_id)

        group  = perk.get("group", "")
        gemoji = GROUP_EMOJI.get(group, "✨")
        color  = GROUP_COLOR.get(group, 0xFFD700)
        desc   = f"### {gemoji} {perk['name']}\n{perk['desc']}"
        if perk.get("subdesc"):
            desc += f"\n-# {perk['subdesc']}"
        embed = discord.Embed(title="📋  Perk přiřazen", description=desc, color=color)
        embed.add_field(name="Hráč", value=member.mention, inline=True)
        embed.set_footer(text=f"⭐ {ARION_NAME}  ·  ID: {perk_id}")
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Perk **{perk['name']}** přiřazen {member.mention}.", ephemeral=True
        )

    @perks_group.command(name="list", description="Seznam všech perků v databázi (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def perks_list(self, interaction: discord.Interaction):
        perks = load_perks()
        if not perks:
            await interaction.response.send_message("Databáze perků je prázdná.", ephemeral=True)
            return

        groups: dict[str, list[tuple[str, dict]]] = {}
        ungrouped: list[tuple[str, dict]] = []
        for pid, p in perks.items():
            g = p.get("group", "")
            if g in GROUP_ORDER:
                groups.setdefault(g, []).append((pid, p))
            else:
                ungrouped.append((pid, p))

        lines: list[str] = []
        for g in GROUP_ORDER:
            if g not in groups:
                continue
            gemoji = GROUP_EMOJI.get(g, "▸")
            lines.append(f"\n{gemoji} **{g}**")
            for pid, p in groups[g]:
                passive_tag = " *(pasivní)*" if p.get("passive") else ""
                unique_tag  = " ⭐" if p.get("unique") else ""
                max_        = p.get("cooldown_uses", 0)
                cd_tag      = f" · ⏳ {max_}×/den" if max_ > 0 else ""
                lines.append(f"▸ **{p['name']}**{passive_tag}{unique_tag}{cd_tag}")
                lines.append(f"-# `{pid}`")
        if ungrouped:
            lines.append("\n✨ **Ostatní**")
            for pid, p in ungrouped:
                lines.append(f"▸ **{p['name']}**")
                lines.append(f"-# `{pid}`")

        desc = f"### 📋 Databáze perků — {len(perks)} celkem" + "\n".join(lines)
        embed = discord.Embed(description=desc[:4000], color=0x7B68EE)
        embed.set_footer(text=f"⭐ {ARION_NAME}  ·  /perks give <id> @hráč — přiřaď perk")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /give-random-perk ─────────────────────────────────────────────────────

    @app_commands.command(name="give-random-perk", description="Dej hráči náhodný perk (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hráč který dostane perk")
    async def give_random_perk(self, interaction: discord.Interaction, member: discord.Member):
        all_perks   = load_perks()
        player_data = load_player_perks()
        player      = _get_player(str(member.id), player_data)
        owned       = set(player["perks"])
        available   = [pid for pid, p in all_perks.items() if pid not in owned and not p.get("unique")]

        if not available:
            await interaction.response.send_message(
                f"{member.mention} už vlastní všechny dostupné perky z náhodného poolu.", ephemeral=True
            )
            return

        chosen_id = random.choice(available)
        chosen    = all_perks[chosen_id]
        player["perks"].append(chosen_id)
        save_player_perks(player_data)
        log_action("perk_random", interaction.user.display_name, member.display_name, chosen_id)

        await _dm_perk(member, chosen, chosen_id)

        # Nat20 stat (read-only, jen pro flavor)
        nat20_line = ""
        try:
            from src.core.dnd.roll_stats import get_stats
            stats = get_stats(interaction.guild.id, member.id)
            nat20 = stats.get("nat20", 0)
            if nat20 > 0:
                nat20_line = f"\n-# {member.display_name} hodil již **{nat20}** nat20!"
        except Exception:
            pass

        embed = discord.Embed(
            title="🎲  Náhodný perk!",
            description=f"{member.mention} právě získal nový perk.{nat20_line}",
            color=0x7B68EE,
        )
        embed.set_footer(text=f"⭐ {ARION_NAME}  ·  Detaily v DM")
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Perk **{chosen['name']}** (`{chosen_id}`) přiřazen {member.mention}.", ephemeral=True
        )

    # ── /perk skupina ─────────────────────────────────────────────────────────

    perk_group = app_commands.Group(name="perk", description="Správa a použití perků")

    @perk_group.command(name="give", description="Přiřaď konkrétní perk hráči (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(perk_id="ID perku", member="Hráč")
    async def perk_give(self, interaction: discord.Interaction, perk_id: str, member: discord.Member):
        all_perks = load_perks()
        if perk_id not in all_perks:
            await interaction.response.send_message(f"Perk `{perk_id}` neexistuje.", ephemeral=True)
            return
        player_data = load_player_perks()
        player      = _get_player(str(member.id), player_data)
        if perk_id in player["perks"]:
            await interaction.response.send_message(
                f"{member.mention} už má **{all_perks[perk_id]['name']}**.", ephemeral=True
            )
            return
        player["perks"].append(perk_id)
        save_player_perks(player_data)
        log_action("perk_give", interaction.user.display_name, member.display_name, perk_id)

        perk   = all_perks[perk_id]
        await _dm_perk(member, perk, perk_id)

        group  = perk.get("group", "")
        gemoji = GROUP_EMOJI.get(group, "✨")
        color  = GROUP_COLOR.get(group, 0xFFD700)
        desc   = f"### {gemoji} {perk['name']}\n{perk['desc']}"
        if perk.get("subdesc"):
            desc += f"\n-# {perk['subdesc']}"
        embed = discord.Embed(title="📋  Perk přiřazen", description=desc, color=color)
        embed.add_field(name="Hráč", value=member.mention, inline=True)
        embed.set_footer(text=f"⭐ {ARION_NAME}  ·  ID: {perk_id}")
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Perk **{perk['name']}** přiřazen {member.mention}.", ephemeral=True
        )

    @perk_group.command(name="remove", description="Odeber perk hráči (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(perk_id="ID perku", member="Hráč")
    async def perk_remove(self, interaction: discord.Interaction, perk_id: str, member: discord.Member):
        player_data = load_player_perks()
        player      = _get_player(str(member.id), player_data)
        if perk_id not in player["perks"]:
            all_perks = load_perks()
            name = all_perks.get(perk_id, {}).get("name", perk_id)
            await interaction.response.send_message(f"{member.mention} nemá **{name}**.", ephemeral=True)
            return
        player["perks"].remove(perk_id)
        player["cooldowns"].pop(perk_id, None)
        save_player_perks(player_data)
        all_perks = load_perks()
        name = all_perks.get(perk_id, {}).get("name", perk_id)
        log_action("perk_remove", interaction.user.display_name, member.display_name, perk_id)
        await interaction.response.send_message(
            f"✅ Perk **{name}** odebrán {member.mention}.", ephemeral=True
        )

    @perk_group.command(name="reset", description="Resetuj cooldowny hráče nebo všech (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hráč (prázdné = reset všech)")
    async def perk_reset(self, interaction: discord.Interaction, member: discord.Member | None = None):
        player_data = load_player_perks()
        if member:
            player = _get_player(str(member.id), player_data)
            player["cooldowns"] = {}
            save_player_perks(player_data)
            await interaction.response.send_message(
                f"✅ Cooldowny {member.mention} resetovány.", ephemeral=True
            )
        else:
            for uid_str in player_data:
                player_data[uid_str]["cooldowns"] = {}
            save_player_perks(player_data)
            await interaction.response.send_message(
                "✅ Cooldowny všech hráčů resetovány.", ephemeral=True
            )

    @perk_group.command(name="new", description="Vytvoř nový perk v databázi (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def perk_new(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PerkNewModal())

    @perk_group.command(name="edit", description="Uprav existující perk v databázi (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(perk_id="ID perku k úpravě")
    async def perk_edit(self, interaction: discord.Interaction, perk_id: str):
        perks = load_perks()
        if perk_id not in perks:
            await interaction.response.send_message(f"Perk `{perk_id}` neexistuje.", ephemeral=True)
            return
        await interaction.response.send_modal(PerkEditModal(perk_id, perks[perk_id]))

    @perk_group.command(name="delete", description="Smaž perk z databáze (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(perk_id="ID perku ke smazání")
    async def perk_delete(self, interaction: discord.Interaction, perk_id: str):
        perks = load_perks()
        if perk_id not in perks:
            await interaction.response.send_message(f"Perk `{perk_id}` neexistuje.", ephemeral=True)
            return
        name = perks[perk_id].get("name", perk_id)
        del perks[perk_id]
        save_perks(perks)
        await interaction.response.send_message(f"✅ Perk **{name}** smazán z databáze.", ephemeral=True)

    @perk_group.command(name="detail", description="Zobraz detailní info o perku")
    @app_commands.describe(perk_id="Perk k zobrazení")
    async def perk_detail(self, interaction: discord.Interaction, perk_id: str):
        perks = load_perks()
        if perk_id not in perks:
            await interaction.response.send_message(f"Perk `{perk_id}` neexistuje.", ephemeral=True)
            return
        p = perks[perk_id]

        group  = p.get("group", "")
        gemoji = GROUP_EMOJI.get(group, "✨")
        color  = GROUP_COLOR.get(group, 0xFFD700)

        passive_line = "🔒 Pasivní" if p.get("passive") else "⚡ Aktivní"
        unique_line  = "⭐ Unikátní" if p.get("unique") else "🎲 V náhodném poolu"
        max_         = p.get("cooldown_uses", 0)
        cd_line      = f"{max_}×/den" if max_ > 0 else "—"

        desc = f"### {gemoji} {p['name']}\n{p['desc']}"
        if p.get("subdesc"):
            desc += f"\n-# {p['subdesc']}"

        embed = discord.Embed(description=desc, color=color)
        embed.add_field(name="Typ",       value=passive_line, inline=True)
        embed.add_field(name="⏳ Cooldown", value=cd_line,     inline=True)
        embed.add_field(name="Dostupnost", value=unique_line,  inline=True)
        embed.set_footer(text=f"⭐ {ARION_NAME}  ·  ID: {perk_id}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @perk_group.command(name="use", description="Aktivuj perk")
    @app_commands.describe(perk_id="Perk k aktivaci")
    async def perk_use(self, interaction: discord.Interaction, perk_id: str):
        all_perks   = load_perks()
        player_data = load_player_perks()
        player      = _get_player(str(interaction.user.id), player_data)

        if perk_id not in player["perks"]:
            await interaction.response.send_message("Tento perk nevlastníš.", ephemeral=True)
            return
        if perk_id not in all_perks:
            await interaction.response.send_message("Perk nenalezen v databázi.", ephemeral=True)
            return

        perk = all_perks[perk_id]
        if perk.get("passive"):
            await interaction.response.send_message(
                f"**{perk['name']}** je pasivní perk — aktivuje se automaticky, nelze ho ručně použít.",
                ephemeral=True,
            )
            return

        ok, err_msg = _check_and_use_cooldown(player, perk_id, perk)
        if not ok:
            await interaction.response.send_message(
                f"⏳ **Cooldown aktivní** — {err_msg}", ephemeral=True
            )
            return

        save_player_perks(player_data)
        today = date.today().isoformat()
        cd    = player["cooldowns"].get(perk_id, {})
        used  = cd.get("used", 0) if cd.get("date") == today else 0

        embed = _perk_announce_embed(interaction.user, perk_id, perk, used)
        await interaction.response.send_message(embed=embed)

    # ── Autocomplete ──────────────────────────────────────────────────────────

    @perk_give.autocomplete("perk_id")
    @perk_edit.autocomplete("perk_id")
    @perk_delete.autocomplete("perk_id")
    @perks_give.autocomplete("perk_id")
    async def perk_db_autocomplete(self, interaction: discord.Interaction, current: str):
        perks = load_perks()
        return [
            app_commands.Choice(name=f"{p['name']} ({pid})", value=pid)
            for pid, p in perks.items()
            if current.lower() in pid.lower() or current.lower() in p.get("name", "").lower()
        ][:25]

    @perk_remove.autocomplete("perk_id")
    @perk_use.autocomplete("perk_id")
    async def perk_owned_autocomplete(self, interaction: discord.Interaction, current: str):
        all_perks   = load_perks()
        player_data = load_player_perks()
        player      = _get_player(str(interaction.user.id), player_data)
        owned       = player["perks"]
        return [
            app_commands.Choice(
                name=f"{all_perks[pid]['name']} ({pid})" if pid in all_perks else pid,
                value=pid,
            )
            for pid in owned
            if current.lower() in pid.lower()
            or (pid in all_perks and current.lower() in all_perks[pid].get("name", "").lower())
        ][:25]


async def setup(bot):
    await bot.add_cog(PerksCog(bot))
