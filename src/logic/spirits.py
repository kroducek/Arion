import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import random
import datetime

from src.utils.paths import PROFILES as DATA_FILE
from src.utils.json_utils import load_json, save_json
from src.database.characters import pkey

# ══════════════════════════════════════════════════════════════════════════════
# KONFIGURACE
# ══════════════════════════════════════════════════════════════════════════════

DM_ROLE_NAME = "DM"
FU_EMO       = "<:furioku:1490160933081972866>"
SPIRIT_EMO   = "👻"

ELEMENTS: dict[str, dict] = {
    "voda":      {"emoji": "💧", "color": 0x2980b9, "furioku_type": "Vodní furioka"},
    "zeme":      {"emoji": "🪨", "color": 0x8B6914, "furioku_type": "Zemní furioka"},
    "ohen":      {"emoji": "🔥", "color": 0xe74c3c, "furioku_type": "Ohnivá furioka"},
    "vzduch":    {"emoji": "🌬️", "color": 0x99d6ea, "furioku_type": "Vzdušná furioka"},
    "svetlo":    {"emoji": "✨", "color": 0xf9e547, "furioku_type": "Světelná furioka"},
    "temnota":   {"emoji": "🌑", "color": 0x2c2c3e, "furioku_type": "Temná furioka"},
    "rovnovaha": {"emoji": "⚖️", "color": 0x1d9e75, "furioku_type": "Vyvážená furioka"},
    "prazdnota": {"emoji": "🌀", "color": 0x8e44ad, "furioku_type": "Prázdná furioka"},
    "chaos":     {"emoji": "💥", "color": 0xe67e22, "furioku_type": "Chaotická furioka"},
}

def rank_xp_threshold(rank: int) -> int:
    return int(100 * (rank ** 1.6))

def rank_up_chance(rank: int) -> float:
    return max(0.10, 0.75 - (rank - 1) * 0.07)

FURY_TO_SPIRIT_XP   = 1
RANKUP_FURY_BONUS   = 0.25   # +25% fury při rank-upu

BREED_CHANCE: dict[int, float] = {0: 0.80, 1: 0.55, 2: 0.30, 3: 0.10}
BREED_ELEMENT_BONUS   = 0.15
BREED_ELEMENT_PENALTY = 0.10

def rank_label(rank: int) -> str:
    labels = {
        1: "Běžný",
        2: "Neobvyklý", 3: "Neobvyklý",
        4: "Vzácný",    5: "Vzácný",
        6: "Epický",    7: "Epický",
        8: "Legendární",9: "Legendární",
        10: "Mytický",
    }
    if rank >= 11:
        return f"Mimo chápání (R{rank})"
    return f"{labels.get(rank, 'Neznámý')} (R{rank})"

def rank_color(rank: int) -> int:
    if rank <= 3:  return 0x888780
    if rank <= 5:  return 0x1d9e75
    if rank <= 7:  return 0x534ab7
    if rank <= 9:  return 0xf1c40f
    return 0xe74c3c

# ══════════════════════════════════════════════════════════════════════════════
# DATOVÁ VRSTVA
# ══════════════════════════════════════════════════════════════════════════════

def _load() -> dict:
    return load_json(DATA_FILE)

def _save(data: dict) -> None:
    save_json(DATA_FILE, data)

def _is_dm(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    return any(r.name == DM_ROLE_NAME for r in interaction.user.roles)

def _default_spirit(name: str, rank: int, fury: int,
                    element: str, description: str = "") -> dict:
    return {
        "name":         name,
        "rank":         rank,
        "fury":         fury,
        "element":      element,
        "description":  description,
        "xp":           0,
        "xp_threshold": rank_xp_threshold(rank),
        "total_xp":     0,
        "created_at":   datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }

# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def get_equipped_spirit(profile: dict) -> dict | None:
    spirits      = profile.get("spirits", [])
    equipped_idx = profile.get("equipped_spirit_idx")
    if equipped_idx is None or not (0 <= equipped_idx < len(spirits)):
        return None
    return spirits[equipped_idx]

def spirit_fury_bonus(profile: dict) -> int:
    spirit = get_equipped_spirit(profile)
    return spirit["fury"] if spirit else 0

def fury_display(profile: dict) -> tuple[int, int, int]:
    fury_cur = profile.get("fury_cur", 0)
    fury_max = profile.get("fury_max", 0)
    bonus    = spirit_fury_bonus(profile)
    return fury_cur, fury_max, bonus

def grant_spirit_xp(profile: dict, fury_used: int) -> dict | None:
    """
    Přidá XP equipnutému duchovi.
    Vrátí result dict nebo None pokud XP nestačí na threshold.
    result: {ranked_up, old_rank, new_rank, spirit_name, fury_gained}
    fury_gained je vyplněno jen při ranked_up=True (+25% fury bonus).
    """
    spirit = get_equipped_spirit(profile)
    if not spirit or fury_used <= 0:
        return None

    gained = fury_used * FURY_TO_SPIRIT_XP
    spirit["xp"]       = spirit.get("xp", 0) + gained
    spirit["total_xp"] = spirit.get("total_xp", 0) + gained

    threshold = spirit.get("xp_threshold", rank_xp_threshold(spirit["rank"]))
    if spirit["xp"] < threshold:
        return None

    old_rank = spirit["rank"]
    chance   = rank_up_chance(old_rank)
    spirit["xp"] -= threshold

    if random.random() < chance:
        spirit["rank"]        += 1
        spirit["xp_threshold"] = rank_xp_threshold(spirit["rank"])
        # +25% fury bonus při rank-upu
        fury_bonus = max(1, int(spirit["fury"] * RANKUP_FURY_BONUS))
        spirit["fury"] += fury_bonus
        return {
            "ranked_up":   True,
            "old_rank":    old_rank,
            "new_rank":    spirit["rank"],
            "spirit_name": spirit["name"],
            "fury_gained": fury_bonus,
        }
    else:
        spirit["xp_threshold"] = int(threshold * 1.2)
        return {
            "ranked_up":   False,
            "old_rank":    old_rank,
            "new_rank":    old_rank,
            "spirit_name": spirit["name"],
            "fury_gained": 0,
        }

def breed_spirits(profile: dict, idx_a: int, idx_b: int) -> dict:
    spirits = profile.get("spirits", [])
    if not (0 <= idx_a < len(spirits) and 0 <= idx_b < len(spirits)):
        raise ValueError("Neplatné indexy duchů.")
    if idx_a == idx_b:
        raise ValueError("Nelze kombinovat ducha se sebou samým.")

    a, b       = spirits[idx_a], spirits[idx_b]
    rank_a, rank_b = a["rank"], b["rank"]
    diff       = abs(rank_a - rank_b)
    chance     = BREED_CHANCE.get(diff, 0.0) if diff <= 3 else 0.0

    elem_a, elem_b = a.get("element", ""), b.get("element", "")
    if elem_a == elem_b:
        chance = min(1.0, chance + BREED_ELEMENT_BONUS)
    else:
        chance = max(0.0, chance - BREED_ELEMENT_PENALTY)

    stronger_idx = idx_a if rank_a >= rank_b else idx_b
    weaker_idx   = idx_b if rank_a >= rank_b else idx_a
    stronger, weaker = spirits[stronger_idx], spirits[weaker_idx]

    success = random.random() < chance

    for idx in sorted([idx_a, idx_b], reverse=True):
        spirits.pop(idx)

    equipped_idx = profile.get("equipped_spirit_idx")
    if equipped_idx is not None:
        removed_lower  = min(idx_a, idx_b)
        removed_higher = max(idx_a, idx_b)
        if equipped_idx in (idx_a, idx_b):
            profile["equipped_spirit_idx"] = None
        elif equipped_idx > removed_higher:
            profile["equipped_spirit_idx"] -= 2
        elif equipped_idx > removed_lower:
            profile["equipped_spirit_idx"] -= 1

    if success:
        new_rank   = max(rank_a, rank_b) + 1
        new_fury   = a["fury"] + b["fury"]
        new_elem   = elem_a if elem_a == elem_b else f"{elem_a}/{elem_b}"
        new_spirit = _default_spirit(
            name=stronger["name"],
            rank=new_rank,
            fury=new_fury,
            element=new_elem,
            description=stronger.get("description", ""),
        )
        spirits.append(new_spirit)
        profile["equipped_spirit_idx"] = len(spirits) - 1
        return {
            "success":       True,
            "chance":        chance,
            "new_spirit":    new_spirit,
            "survivor":      None,
            "consumed_name": weaker["name"],
        }
    else:
        stronger["fury"] = int(stronger["fury"] * 1.05)
        spirits.append(stronger)
        profile["equipped_spirit_idx"] = len(spirits) - 1
        return {
            "success":       False,
            "chance":        chance,
            "new_spirit":    None,
            "survivor":      stronger,
            "consumed_name": weaker["name"],
        }

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _elem_emoji(element: str) -> str:
    return ELEMENTS.get(element.split("/")[0], {}).get("emoji", "❓")

def _spirit_line(s: dict, equipped: bool = False) -> str:
    emoji  = _elem_emoji(s.get("element", ""))
    eq     = "  ◀ *equipnutý*" if equipped else ""
    thresh = s.get("xp_threshold", rank_xp_threshold(s["rank"]))
    return (
        f"{SPIRIT_EMO} **{s['name']}** {emoji}  ·  {rank_label(s['rank'])}  ·  "
        f"{s['fury']} {FU_EMO}  ·  XP: {s.get('xp', 0)}/{thresh}{eq}"
    )

def _spirit_embed(s: dict, title: str = None) -> discord.Embed:
    elem   = s.get("element", "?")
    emoji  = _elem_emoji(elem)
    color  = ELEMENTS.get(elem.split("/")[0], {}).get("color", rank_color(s["rank"]))
    embed  = discord.Embed(title=title or f"{SPIRIT_EMO} {s['name']}", color=color)
    embed.add_field(name="Rank",    value=rank_label(s["rank"]),       inline=True)
    embed.add_field(name="Element", value=f"{emoji} {elem}",           inline=True)
    embed.add_field(name="Furioka", value=f"{s['fury']} {FU_EMO}",     inline=True)
    thresh = s.get("xp_threshold", rank_xp_threshold(s["rank"]))
    embed.add_field(
        name="Progres",
        value=f"XP: **{s.get('xp', 0)}** / {thresh}  ·  Celkem: {s.get('total_xp', 0)}",
        inline=False,
    )
    if s.get("description"):
        embed.add_field(name="Popis", value=f"*{s['description']}*", inline=False)
    embed.set_footer(text=f"Získán: {s.get('created_at', '?')[:10]}")
    return embed

# ══════════════════════════════════════════════════════════════════════════════
# CONFIRM VIEW
# ══════════════════════════════════════════════════════════════════════════════

class BreedConfirmView(discord.ui.View):
    def __init__(self, uid: str, idx_a: int, idx_b: int,
                 a_name: str, b_name: str, chance: float):
        super().__init__(timeout=30)
        self.uid     = uid
        self.idx_a   = idx_a
        self.idx_b   = idx_b
        self.a_name  = a_name
        self.b_name  = b_name
        self.chance  = chance
        self.done    = False

    async def on_timeout(self):
        if not self.done:
            for item in self.children:
                item.disabled = True

    @discord.ui.button(label="Potvrdit šlechtění", style=discord.ButtonStyle.danger, emoji="⚗️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ověř vlastnictví
        if pkey(interaction.user.id) != self.uid:
            await interaction.response.send_message("❌ Toto není tvoje šlechtění.", ephemeral=True)
            return

        self.done = True
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        # Znovu načti čerstvá data (mohla se změnit)
        data    = _load()
        profile = data.get(self.uid)
        if not profile:
            await interaction.followup.send("❌ Profil nenalezen.", ephemeral=True)
            return

        spirits = profile.get("spirits", [])
        # Přeověř indexy — jména musí souhlasit
        if (self.idx_a >= len(spirits) or self.idx_b >= len(spirits)
                or spirits[self.idx_a]["name"].lower() != self.a_name.lower()
                or spirits[self.idx_b]["name"].lower() != self.b_name.lower()):
            await interaction.followup.send(
                "❌ Duchové se změnili od potvrzení. Zkus znovu.", ephemeral=True
            )
            return

        try:
            result = breed_spirits(profile, self.idx_a, self.idx_b)
        except ValueError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
            return

        _save(data)
        chance_pct = int(result["chance"] * 100)

        if result["success"]:
            ns    = result["new_spirit"]
            emoji = _elem_emoji(ns["element"])
            embed = discord.Embed(
                title="✨ Šlechtění úspěšné!",
                description=(
                    f"**{self.a_name}** a **{self.b_name}** se sloučili!\n"
                    f"Nový duch **{ns['name']}** je equipnutý a připraven."
                ),
                color=rank_color(ns["rank"]),
            )
            embed.add_field(name="Rank",    value=rank_label(ns["rank"]),    inline=True)
            embed.add_field(name="Element", value=f"{emoji} {ns['element']}", inline=True)
            embed.add_field(name="Furioka", value=f"{ns['fury']} {FU_EMO}",  inline=True)
            embed.set_footer(text=f"Šance byla {chance_pct}%")
        else:
            sv    = result["survivor"]
            embed = discord.Embed(
                title="💀 Šlechtění selhalo",
                description=(
                    f"**{result['consumed_name']}** byl pohlcen!\n"
                    f"**{sv['name']}** přežil a mírně zesílil ({sv['fury']} {FU_EMO})."
                ),
                color=0x888780,
            )
            embed.set_footer(text=f"Šance byla {chance_pct}%")

        await interaction.followup.send(embed=embed)

    @discord.ui.button(label="Zrušit", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if pkey(interaction.user.id) != self.uid:
            await interaction.response.send_message("❌ Toto není tvoje šlechtění.", ephemeral=True)
            return
        self.done = True
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="*Šlechtění zrušeno. Oba duchové přežili.*", embed=None, view=self
        )

# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# FURIOKU: ÚTOK / OBRANA  (správa přes /staty → tlačítko Furioku)
# ══════════════════════════════════════════════════════════════════════════════
#
# Uloženo v profilu:
#   profile["furioka"] = {
#       "def_amount": int,   # kolik VLASTNÍ furioku je nasazeno do obrany
#       "atk_amount": int,   # kolik VLASTNÍ furioku je nasazeno do útoku
#       "def_spirit": bool,  # je do obrany nasazen equipnutý duch? (vyžaduje Jednotu)
#       "atk_spirit": bool,  # je do útoku nasazen equipnutý duch?
#   }
# Duch smí být nasazen jen do JEDNÉ role naráz (nedá se rozdvojit).

PERK_JEDNOTA = "furioku_jednota"
PERK_OBRANA  = "furioku_obrana"
PERK_UTOK    = "furioku_utok"


def _furioka(profile: dict) -> dict:
    f = profile.setdefault("furioka", {})
    f.setdefault("def_amount", 0)
    f.setdefault("atk_amount", 0)
    f.setdefault("def_spirit", False)
    f.setdefault("atk_spirit", False)
    return f


def _owned_perks(user_id: int) -> list[str]:
    """Perky aktivní postavy — načteno z perks cogu, s bezpečným fallbackem."""
    try:
        from src.core.dnd.perks import owned_perks
        return owned_perks(user_id)
    except Exception:
        return []


def furioka_bonuses(profile: dict, user_id: int) -> tuple[int, int]:
    """(ATK bonus, DEF bonus) z nasazené furioku + ducha. Pro combat.py.

    Vlastní furioku se počítá jen když má hráč příslušný perk. Duch přidá svou
    fury do dané role jen s perkem Jednota. Nikdy nevrací víc, než hráč reálně má.
    """
    f       = _furioka(profile)
    perks   = _owned_perks(user_id)
    spirit  = get_equipped_spirit(profile)
    fury_av = profile.get("fury_cur", 0)

    atk = f["atk_amount"] if PERK_UTOK  in perks else 0
    dfn = f["def_amount"] if PERK_OBRANA in perks else 0
    # vlastní furioku nesmí přesáhnout aktuální zásobu
    if atk + dfn > fury_av:
        # ořízni férově – útok má přednost jen kdyby došlo, jinak nech být
        overflow = atk + dfn - fury_av
        dfn = max(0, dfn - overflow)

    if PERK_JEDNOTA in perks and spirit:
        if f["atk_spirit"]:
            atk += spirit.get("fury", 0)
        elif f["def_spirit"]:
            dfn += spirit.get("fury", 0)
    return atk, dfn


def _furioka_embed(profile: dict, user_id: int) -> discord.Embed:
    f      = _furioka(profile)
    perks  = _owned_perks(user_id)
    spirit = get_equipped_spirit(profile)
    fury_cur = profile.get("fury_cur", 0)
    fury_max = profile.get("fury_max", 0)

    has_jednota = PERK_JEDNOTA in perks
    has_obrana  = PERK_OBRANA  in perks
    has_utok    = PERK_UTOK    in perks

    atk, dfn = furioka_bonuses(profile, user_id)

    def role_line(amount, spirit_on, has_perk, label):
        if not has_perk:
            return f"🔒 *chybí perk {label}*"
        parts = [f"{FU_EMO} **{amount}**"]
        if spirit_on and spirit and has_jednota:
            parts.append(f"+ 👻 {spirit['name']} (**{spirit.get('fury',0)}**)")
        return "  ".join(parts)

    embed = discord.Embed(
        title=f"{FU_EMO}  Správa furioku",
        description=(f"Zásoba furioku: **{fury_cur}/{fury_max}**\n"
                     f"-# Nasazuješ vlastní furioku do útoku/obrany. "
                     f"S perkem **Jednota** můžeš do jedné role vložit i ducha."),
        color=0x8e44ad,
    )
    embed.add_field(
        name="⚔️ Furioku: Útok",
        value=f"{role_line(f['atk_amount'], f['atk_spirit'], has_utok, 'Furioku: Útok')}\n"
              f"→ celkem **+{atk} ATK**",
        inline=True,
    )
    embed.add_field(
        name="🛡️ Furioku: Obrana",
        value=f"{role_line(f['def_amount'], f['def_spirit'], has_obrana, 'Furioku: Obrana')}\n"
              f"→ celkem **+{dfn} DEF**",
        inline=True,
    )

    if spirit:
        where = ("v útoku" if f["atk_spirit"] else "v obraně" if f["def_spirit"] else "nenasazen")
        embed.add_field(
            name="👻 Duch",
            value=(f"**{spirit['name']}** · {rank_label(spirit['rank'])} · "
                   f"{FU_EMO} {spirit.get('fury',0)}\n-# Aktuálně: {where}"),
            inline=False,
        )
    else:
        embed.add_field(name="👻 Duch",
                        value="*Nemáš equipnutého ducha (`/duch equip`).*", inline=False)

    # výpis vlastněných furioku perků
    fu_perks = [p for p in perks if p.startswith("furioku_")]
    if fu_perks:
        try:
            from src.core.dnd.perks import load_perks
            all_p = load_perks()
            names = [all_p.get(pid, {}).get("name", pid) for pid in fu_perks]
        except Exception:
            names = fu_perks
        embed.add_field(name="🌀 Tvé furioku perky",
                        value=", ".join(f"`{n}`" for n in names), inline=False)

    embed.set_footer(text="⭐ Aurionis")
    return embed


class FurioukaView(discord.ui.View):
    """Správa nasazení furioku: +/- do útoku a obrany, nasazení ducha."""

    STEP = 5

    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    # ── načti/ulož profil aktivní postavy ──
    def _get(self):
        data = _load()
        prof = data.get(pkey(self.user_id))
        return data, prof

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Toto není tvůj panel.", ephemeral=True)
            return False
        return True

    async def _refresh(self, interaction: discord.Interaction, data, profile):
        _save(data)
        await interaction.response.edit_message(
            embed=_furioka_embed(profile, self.user_id), view=self)

    def _adjust(self, profile: dict, role: str, delta: int) -> str | None:
        """Změní nasazenou vlastní furioku. Vrací chybu, nebo None."""
        perks = _owned_perks(self.user_id)
        need  = PERK_UTOK if role == "atk" else PERK_OBRANA
        if need not in perks:
            return f"Chybí ti perk **{'Furioku: Útok' if role=='atk' else 'Furioku: Obrana'}**."
        f   = _furioka(profile)
        key = f"{role}_amount"
        new = f[key] + delta
        if new < 0:
            return None                        # neklesej pod nulu, tiše
        # součet nasazené vlastní furioku nesmí přesáhnout zásobu
        other = f["def_amount"] if role == "atk" else f["atk_amount"]
        if new + other > profile.get("fury_cur", 0):
            return "Nemáš tolik furioku v zásobě."
        f[key] = new
        return None

    def _toggle_spirit(self, profile: dict, role: str) -> str | None:
        perks = _owned_perks(self.user_id)
        if PERK_JEDNOTA not in perks:
            return "Nasadit ducha vyžaduje perk **Furioku: Jednota**."
        if not get_equipped_spirit(profile):
            return "Nemáš equipnutého ducha."
        f     = _furioka(profile)
        key   = f"{role}_spirit"
        other = "def_spirit" if role == "atk" else "atk_spirit"
        f[key] = not f[key]
        if f[key]:
            f[other] = False                   # duch může být jen v jedné roli
        return None

    # ── útok ──
    @discord.ui.button(label="＋5", emoji="⚔️", style=discord.ButtonStyle.danger, row=0)
    async def atk_plus(self, interaction, _b):
        if not await self._guard(interaction): return
        data, profile = self._get()
        err = self._adjust(profile, "atk", self.STEP)
        if err: return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        await self._refresh(interaction, data, profile)

    @discord.ui.button(label="－5", emoji="⚔️", style=discord.ButtonStyle.secondary, row=0)
    async def atk_minus(self, interaction, _b):
        if not await self._guard(interaction): return
        data, profile = self._get()
        self._adjust(profile, "atk", -self.STEP)
        await self._refresh(interaction, data, profile)

    @discord.ui.button(label="Duch → útok", emoji="👻", style=discord.ButtonStyle.primary, row=0)
    async def atk_spirit(self, interaction, _b):
        if not await self._guard(interaction): return
        data, profile = self._get()
        err = self._toggle_spirit(profile, "atk")
        if err: return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        await self._refresh(interaction, data, profile)

    # ── obrana ──
    @discord.ui.button(label="＋5", emoji="🛡️", style=discord.ButtonStyle.success, row=1)
    async def def_plus(self, interaction, _b):
        if not await self._guard(interaction): return
        data, profile = self._get()
        err = self._adjust(profile, "def", self.STEP)
        if err: return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        await self._refresh(interaction, data, profile)

    @discord.ui.button(label="－5", emoji="🛡️", style=discord.ButtonStyle.secondary, row=1)
    async def def_minus(self, interaction, _b):
        if not await self._guard(interaction): return
        data, profile = self._get()
        self._adjust(profile, "def", -self.STEP)
        await self._refresh(interaction, data, profile)

    @discord.ui.button(label="Duch → obrana", emoji="👻", style=discord.ButtonStyle.primary, row=1)
    async def def_spirit(self, interaction, _b):
        if not await self._guard(interaction): return
        data, profile = self._get()
        err = self._toggle_spirit(profile, "def")
        if err: return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        await self._refresh(interaction, data, profile)

    # ── reset ──
    @discord.ui.button(label="Sundat vše", emoji="🔄", style=discord.ButtonStyle.secondary, row=2)
    async def clear(self, interaction, _b):
        if not await self._guard(interaction): return
        data, profile = self._get()
        f = _furioka(profile)
        f.update(def_amount=0, atk_amount=0, def_spirit=False, atk_spirit=False)
        await self._refresh(interaction, data, profile)


async def open_furioka(interaction: discord.Interaction, user_id: int):
    """Vstupní bod pro /staty tlačítko Furioku."""
    data = _load()
    profile = data.get(pkey(user_id))
    if not profile:
        await interaction.response.send_message(
            "Nemáš profil — projdi nejdřív tutoriálem.", ephemeral=True)
        return
    await interaction.response.send_message(
        embed=_furioka_embed(profile, user_id),
        view=FurioukaView(user_id), ephemeral=True)


class Spirits(commands.Cog):
    # Jedna skupina /duch se v limitu 100 globálních příkazů počítá jako 1 slot,
    # ne jako 9. Subpříkazy (až 25) se do limitu nezapočítávají.
    duch = app_commands.Group(name="duch", description="Strážní duchové — správa, šlechtění a info.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /duch pridat ──────────────────────────────────────────────────────────

    @duch.command(name="pridat", description="[DM] Přidá hráči nového strážného ducha.")
    @app_commands.describe(
        member="Hráč", name="Jméno ducha",
        rank="Počáteční rank (1 = slabý, 10+ = mytický)",
        fury="Kolik furioku duch přináší",
        element="Element ducha",
        description="Krátký popis (volitelné)",
    )
    @app_commands.choices(element=[
        app_commands.Choice(name=f"{v['emoji']} {k.capitalize()}", value=k)
        for k, v in ELEMENTS.items()
    ])
    async def duch_pridat(
        self, interaction: discord.Interaction,
        member: discord.Member, name: str, rank: int, fury: int,
        element: app_commands.Choice[str], description: str = "",
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        if fury < 0 or rank < 1:
            await interaction.followup.send("❌ Neplatné hodnoty.")
            return

        data    = _load()
        uid     = pkey(member.id)
        profile = data.setdefault(uid, {})
        spirits = profile.setdefault("spirits", [])

        if any(s["name"].lower() == name.lower() for s in spirits):
            await interaction.followup.send(f"❌ **{member.display_name}** už má ducha **{name}**.")
            return

        spirit = _default_spirit(name, rank, fury, element.value, description)
        spirits.append(spirit)
        _save(data)

        embed = _spirit_embed(spirit, title=f"✅ Duch přidán — {name}")
        embed.description = f"Přidán hráči **{member.display_name}**. Použij `/duch equip` k equipnutí."
        await interaction.followup.send(embed=embed)

    # ── /duch xp ──────────────────────────────────────────────────────────────

    @duch.command(name="xp", description="[DM] Přidej duchovi XP.")
    @app_commands.describe(member="Hráč", amount="Množství XP")
    async def duch_xp(
        self, interaction: discord.Interaction,
        member: discord.Member, amount: int,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        if amount <= 0:
            await interaction.followup.send("❌ Množství musí být kladné.")
            return

        data    = _load()
        uid     = pkey(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return

        spirit = get_equipped_spirit(profile)
        if spirit is None:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá equipnutého ducha.")
            return

        spirit_name = spirit["name"]
        result = grant_spirit_xp(profile, amount)
        _save(data)

        # Znovu načti ducha po uložení
        spirit = get_equipped_spirit(profile)

        if result and result["ranked_up"]:
            # Veřejný embed do kanálu
            embed = discord.Embed(
                title=f"⬆️ {member.display_name}'s duch postoupil na vyšší rank!",
                description=(
                    f"{SPIRIT_EMO} **{spirit['name']}** "
                    f"{rank_label(result['old_rank'])} → **{rank_label(result['new_rank'])}**\n\n"
                    f"Furioka: **{spirit['fury']}** {FU_EMO} "
                    f"*(+{result['fury_gained']} za rank-up)*"
                ),
                color=rank_color(spirit["rank"]),
            )
            embed.set_footer(text=f"+{amount} XP")
            # Ephemeral potvrzení DM
            await interaction.followup.send("✅ XP přidáno — duch postoupil!", ephemeral=True)
            # Veřejný announce do kanálu
            await interaction.channel.send(content=member.mention, embed=embed)

        elif result and not result["ranked_up"]:
            thresh = spirit.get("xp_threshold", rank_xp_threshold(spirit["rank"]))
            # Ephemeral info pro DM
            await interaction.followup.send(
                f"✅ +**{amount} XP** pro ducha **{spirit_name}**.\n"
                f"XP: **{spirit['xp']}** / {thresh}",
                ephemeral=True,
            )
            # Veřejný embed — pokus o rank-up selhal
            embed = discord.Embed(
                title=f"💨 {member.display_name}'s duch se pokusil postoupit...",
                description=(
                    f"{SPIRIT_EMO} **{spirit['name']}** se pokusil o rank-up, ale tentokrát to nevyšlo.\n"
                    f"Threshold se zvýšil — příště bude potřeba více síly.\n\n"
                    f"XP: **{spirit['xp']}** / {thresh}"
                ),
                color=0x888780,
            )
            await interaction.channel.send(content=member.mention, embed=embed)

        else:
            # XP přidáno ale threshold ještě nedosažen — jen ephemeral
            thresh = spirit.get("xp_threshold", rank_xp_threshold(spirit["rank"]))
            await interaction.followup.send(
                f"✅ +**{amount} XP** pro ducha **{spirit_name}**.\n"
                f"XP: **{spirit['xp']}** / {thresh}",
                ephemeral=True,
            )

    # ── /duch slechtit ────────────────────────────────────────────────────────

    @duch.command(name="slechtit", description="Pokus o šlechtění dvou duchů — silnější může pohltit slabšího!")
    @app_commands.describe(jmeno_a="Jméno prvního ducha", jmeno_b="Jméno druhého ducha")
    async def duch_slechtit(
        self, interaction: discord.Interaction,
        jmeno_a: str, jmeno_b: str,
    ):
        await interaction.response.defer(ephemeral=False)
        data    = _load()
        uid     = pkey(interaction.user.id)
        profile = data.get(uid)

        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return

        spirits = profile.get("spirits", [])
        if len(spirits) < 2:
            await interaction.followup.send("❌ Potřebuješ alespoň 2 duchy pro šlechtění.")
            return

        idx_a = next((i for i, s in enumerate(spirits) if s["name"].lower() == jmeno_a.lower()), None)
        idx_b = next((i for i, s in enumerate(spirits) if s["name"].lower() == jmeno_b.lower()), None)

        if idx_a is None:
            await interaction.followup.send(f"❌ Nemáš ducha jménem **{jmeno_a}**.")
            return
        if idx_b is None:
            await interaction.followup.send(f"❌ Nemáš ducha jménem **{jmeno_b}**.")
            return
        if idx_a == idx_b:
            await interaction.followup.send("❌ Nelze kombinovat ducha se sebou samým.")
            return

        a, b      = spirits[idx_a], spirits[idx_b]
        rank_diff = abs(a["rank"] - b["rank"])

        elem_a = a.get("element", "")
        elem_b = b.get("element", "")
        base_chance = BREED_CHANCE.get(rank_diff, 0.0) if rank_diff <= 3 else 0.0
        if elem_a == elem_b:
            warn_chance = min(1.0, base_chance + BREED_ELEMENT_BONUS)
        else:
            warn_chance = max(0.0, base_chance - BREED_ELEMENT_PENALTY)

        if rank_diff >= 4:
            warn_embed = discord.Embed(
                title="⚠️ Nebezpečné šlechtění",
                description=(
                    f"Rozdíl ranku je **{rank_diff}** — šance na úspěch je jen **{int(warn_chance * 100)}%**.\n"
                    f"Při neúspěchu silnější duch pohltí slabšího.\n\n"
                    f"**{a['name']}** (R{a['rank']}) × **{b['name']}** (R{b['rank']})"
                ),
                color=0xe74c3c,
            )
            await interaction.followup.send(embed=warn_embed)

        elem_emoji_a = _elem_emoji(elem_a)
        elem_emoji_b = _elem_emoji(elem_b)
        confirm_embed = discord.Embed(
            title="⚗️ Potvrdit šlechtění?",
            description=(
                f"{elem_emoji_a} **{a['name']}** {rank_label(a['rank'])}  ×  "
                f"{elem_emoji_b} **{b['name']}** {rank_label(b['rank'])}\n\n"
                f"Šance úspěchu: **{int(warn_chance * 100)}%**\n"
                f"Při neúspěchu slabší duch zanikne — tato akce je nevratná!"
            ),
            color=0xf39c12,
        )
        # BreedConfirmView dostane jen uid + indexy + jména (ne live objekty)
        view = BreedConfirmView(uid, idx_a, idx_b, a["name"], b["name"], warn_chance)
        await interaction.followup.send(embed=confirm_embed, view=view)

    # ── /duch equip ───────────────────────────────────────────────────────────

    @duch.command(name="equip", description="[DM] Equipni hráči strážného ducha.")
    @app_commands.describe(member="Hráč", name="Jméno ducha")
    async def duch_equip(
        self, interaction: discord.Interaction,
        member: discord.Member, name: str,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return

        data    = _load()
        uid     = pkey(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return

        spirits = profile.get("spirits", [])
        idx     = next((i for i, s in enumerate(spirits) if s["name"].lower() == name.lower()), None)
        if idx is None:
            names = ", ".join(s["name"] for s in spirits) or "žádní"
            await interaction.followup.send(f"❌ Hráč nemá ducha **{name}**.\nDostupní: {names}")
            return

        old_idx = profile.get("equipped_spirit_idx")
        profile["equipped_spirit_idx"] = idx
        _save(data)

        spirit  = spirits[idx]
        old_str = (
            f" *(předtím: {spirits[old_idx]['name']})*"
            if old_idx is not None and old_idx != idx and 0 <= old_idx < len(spirits)
            else ""
        )
        await interaction.followup.send(
            f"✅ **{member.display_name}** equipnut **{spirit['name']}** "
            f"({rank_label(spirit['rank'])}, {spirit['fury']} {FU_EMO}).{old_str}"
        )

    # ── /duch unequip ─────────────────────────────────────────────────────────

    @duch.command(name="unequip", description="[DM] Odequipni strážného ducha hráče.")
    @app_commands.describe(member="Hráč")
    async def duch_unequip(
        self, interaction: discord.Interaction,
        member: discord.Member,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return

        data    = _load()
        uid     = pkey(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return

        spirit = get_equipped_spirit(profile)
        if spirit is None:
            await interaction.followup.send(f"ℹ️ **{member.display_name}** nemá equipnutého ducha.")
            return

        profile["equipped_spirit_idx"] = None
        _save(data)
        await interaction.followup.send(f"✅ Duch **{spirit['name']}** odequipnut. Zůstává v kolekci.")

    # ── /duch upravit ─────────────────────────────────────────────────────────

    @duch.command(name="upravit", description="[DM] Uprav hodnoty existujícího ducha.")
    @app_commands.describe(
        member="Hráč", name="Jméno ducha",
        nove_fury="Nová hodnota furioku",
        novy_rank="Nový rank (resetuje XP)",
        novy_popis="Nový popis",
        nove_jmeno="Přejmenovat ducha",
    )
    async def duch_upravit(
        self, interaction: discord.Interaction,
        member: discord.Member, name: str,
        nove_fury: Optional[int] = None,
        novy_rank: Optional[int] = None,
        novy_popis: Optional[str] = None,
        nove_jmeno: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return

        data    = _load()
        uid     = pkey(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return

        spirits = profile.get("spirits", [])
        spirit  = next((s for s in spirits if s["name"].lower() == name.lower()), None)
        if spirit is None:
            names = ", ".join(s["name"] for s in spirits) or "žádní"
            await interaction.followup.send(f"❌ Hráč nemá ducha **{name}**.\nDostupní: {names}")
            return

        changes = []
        if nove_fury is not None and nove_fury >= 0:
            spirit["fury"] = nove_fury
            changes.append(f"furioka → **{nove_fury}**")
        if novy_rank is not None and novy_rank >= 1:
            spirit["rank"]          = novy_rank
            spirit["xp_threshold"]  = rank_xp_threshold(novy_rank)
            spirit["xp"]            = 0
            changes.append(f"rank → **{rank_label(novy_rank)}**")
        if novy_popis is not None:
            spirit["description"] = novy_popis
            changes.append("popis aktualizován")
        if nove_jmeno is not None:
            if any(s["name"].lower() == nove_jmeno.lower() for s in spirits if s is not spirit):
                await interaction.followup.send(f"❌ Hráč už má ducha jménem **{nove_jmeno}**.")
                return
            old_name = spirit["name"]
            spirit["name"] = nove_jmeno
            changes.append(f"přejmenován: **{old_name}** → **{nove_jmeno}**")

        if not changes:
            await interaction.followup.send("ℹ️ Nezadal/a jsi žádnou změnu.")
            return

        _save(data)
        await interaction.followup.send(
            f"✅ Duch **{spirit['name']}** hráče **{member.display_name}** upraven:\n"
            + "\n".join(f"• {c}" for c in changes)
        )

    # ── /duch odebrat ─────────────────────────────────────────────────────────

    @duch.command(name="odebrat", description="[DM] Trvale odebere ducha z kolekce hráče.")
    @app_commands.describe(member="Hráč", name="Jméno ducha")
    async def duch_odebrat(
        self, interaction: discord.Interaction,
        member: discord.Member, name: str,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return

        data    = _load()
        uid     = pkey(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return

        spirits = profile.get("spirits", [])
        idx     = next((i for i, s in enumerate(spirits) if s["name"].lower() == name.lower()), None)
        if idx is None:
            names = ", ".join(s["name"] for s in spirits) or "žádní"
            await interaction.followup.send(f"❌ Hráč nemá ducha **{name}**.\nDostupní: {names}")
            return

        equipped_idx = profile.get("equipped_spirit_idx")
        if equipped_idx == idx:
            profile["equipped_spirit_idx"] = None
        elif equipped_idx is not None and equipped_idx > idx:
            profile["equipped_spirit_idx"] -= 1

        spirits.pop(idx)
        _save(data)
        await interaction.followup.send(f"✅ Duch **{name}** trvale odebrán hráči **{member.display_name}**.")

    # ── /duch seznam ──────────────────────────────────────────────────────────

    @duch.command(name="seznam", description="Zobraz seznam strážných duchů hráče.")
    @app_commands.describe(member="Hráč (výchozí: ty)")
    async def duch_seznam(
        self, interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target  = member or interaction.user
        data    = _load()
        uid     = pkey(target.id)
        profile = data.get(uid)

        if not profile:
            await interaction.followup.send(f"❌ **{target.display_name}** nemá profil.", ephemeral=True)
            return

        spirits      = profile.get("spirits", [])
        equipped_idx = profile.get("equipped_spirit_idx")

        if not spirits:
            await interaction.followup.send(f"*{target.display_name} nemá žádného strážného ducha.*", ephemeral=True)
            return

        lines = []
        for i, s in enumerate(spirits):
            line = _spirit_line(s, equipped=(i == equipped_idx))
            if s.get("description"):
                line += f"\n-# *{s['description']}*"
            lines.append(line)

        embed = discord.Embed(
            title=f"{SPIRIT_EMO} Strážní duchové — {target.display_name}",
            description="\n\n".join(lines),
            color=0x9b59b6,
        )
        embed.set_footer(text=f"Celkem duchů: {len(spirits)}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /duch info ────────────────────────────────────────────────────────────

    @duch.command(name="info", description="Zobraz detailní info o konkrétním duchovi.")
    @app_commands.describe(name="Jméno ducha", member="Hráč (výchozí: ty)")
    async def duch_info(
        self, interaction: discord.Interaction,
        name: str, member: Optional[discord.Member] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target  = member or interaction.user
        data    = _load()
        uid     = pkey(target.id)
        profile = data.get(uid)

        if not profile:
            await interaction.followup.send(f"❌ **{target.display_name}** nemá profil.")
            return

        spirits      = profile.get("spirits", [])
        equipped_idx = profile.get("equipped_spirit_idx")
        idx          = next((i for i, s in enumerate(spirits) if s["name"].lower() == name.lower()), None)
        if idx is None:
            await interaction.followup.send(f"❌ Duch **{name}** nenalezen.")
            return

        spirit   = spirits[idx]
        equipped = (idx == equipped_idx)
        title    = f"{SPIRIT_EMO} {spirit['name']}" + (" ◀ equipnutý" if equipped else "")
        embed    = _spirit_embed(spirit, title=title)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Spirits(bot))