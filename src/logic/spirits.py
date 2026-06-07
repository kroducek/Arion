import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import random
import datetime

from src.utils.paths import PROFILES as DATA_FILE
from src.utils.json_utils import load_json, save_json

# ══════════════════════════════════════════════════════════════════════════════
# KONFIGURACE
# ══════════════════════════════════════════════════════════════════════════════

DM_ROLE_NAME = "DM"
FU_EMO       = "<:furioku:1490160933081972866>"
SPIRIT_EMO   = "👻"

# Elementy — jméno, emoji, vliv na furioku (flavor), afinity k vliv statům
ELEMENTS: dict[str, dict] = {
    "stín":     {"emoji": "🌑", "vliv": "temnota",   "color": 0x2c2c3e},
    "voda":     {"emoji": "💧", "vliv": "rovnovaha",  "color": 0x2980b9},
    "světlo":   {"emoji": "✨", "vliv": "svetlo",     "color": 0xf9e547},
    "příroda":  {"emoji": "🌿", "vliv": None,         "color": 0x27ae60},
    "oheň":     {"emoji": "🔥", "vliv": None,         "color": 0xe74c3c},
    "prázdnota":{"emoji": "🌀", "vliv": None,         "color": 0x8e44ad},
}

# XP potřebné pro rank-up attempt (index = rank, hodnota = xp threshold)
# rank 1→2 = 100 xp, rank 9→10 = 2500 xp atd.
def rank_xp_threshold(rank: int) -> int:
    """XP threshold pro pokus o rank-up z daného ranku."""
    return int(100 * (rank ** 1.6))

# Šance rank-upu při organickém růstu (bez šlechtění)
def rank_up_chance(rank: int) -> float:
    """Základní šance (0-1) při dosažení XP thresholdu."""
    return max(0.10, 0.75 - (rank - 1) * 0.07)

# XP za použití furioku (1 bod furioku = 1 spirit xp)
FURY_TO_SPIRIT_XP = 1

# Šlechtění — šance dle rozdílu ranku (abs(rank_a - rank_b))
BREED_CHANCE: dict[int, float] = {0: 0.80, 1: 0.55, 2: 0.30, 3: 0.10}
BREED_ELEMENT_BONUS    = 0.15   # stejný element
BREED_ELEMENT_PENALTY  = 0.10   # různý element

# Rank labely (pro zobrazení)
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
    if rank <= 3:   return 0x888780
    if rank <= 5:   return 0x1d9e75
    if rank <= 7:   return 0x534ab7
    if rank <= 9:   return 0xf1c40f
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
        "name":        name,
        "rank":        rank,
        "fury":        fury,
        "element":     element,
        "description": description,
        "xp":          0,
        "xp_threshold": rank_xp_threshold(rank),
        "total_xp":    0,
        "created_at":  datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }

# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API — volané z profile.py
# ══════════════════════════════════════════════════════════════════════════════

def get_equipped_spirit(profile: dict) -> dict | None:
    """Vrátí dict equipnutého ducha nebo None."""
    spirits      = profile.get("spirits", [])
    equipped_idx = profile.get("equipped_spirit_idx")
    if equipped_idx is None or not (0 <= equipped_idx < len(spirits)):
        return None
    return spirits[equipped_idx]


def spirit_fury_bonus(profile: dict) -> int:
    """Vrátí bonus furioku od equipnutého ducha (0 pokud žádný)."""
    spirit = get_equipped_spirit(profile)
    return spirit["fury"] if spirit else 0


def fury_display(profile: dict) -> tuple[int, int, int]:
    """
    Vrátí (fury_cur, fury_max, spirit_bonus) pro zobrazení v profilu.
    fury_cur a fury_max jsou čisté hodnoty hráče BEZ ducha.
    spirit_bonus se přičítá jen vizuálně.
    """
    fury_cur = profile.get("fury_cur", 0)
    fury_max = profile.get("fury_max", 0)
    bonus    = spirit_fury_bonus(profile)
    return fury_cur, fury_max, bonus


def grant_spirit_xp(profile: dict, fury_used: int) -> dict | None:
    """
    Přidá XP equipnutému duchovi za použité furioko.
    Pokud duch dosáhne thresholdu, pokusí se o rank-up.
    Vrátí dict s info o rank-upu nebo None pokud nic nenastalo.
    {ranked_up: bool, old_rank: int, new_rank: int, spirit_name: str}
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

    # Pokus o rank-up
    old_rank = spirit["rank"]
    chance   = rank_up_chance(old_rank)
    spirit["xp"] -= threshold  # spotřebuj XP

    if random.random() < chance:
        spirit["rank"]         += 1
        spirit["xp_threshold"]  = rank_xp_threshold(spirit["rank"])
        return {
            "ranked_up":  True,
            "old_rank":   old_rank,
            "new_rank":   spirit["rank"],
            "spirit_name": spirit["name"],
        }
    else:
        # Neuspěl — threshold se o 20% zvýší (vyšší bar příště)
        spirit["xp_threshold"] = int(threshold * 1.2)
        return {
            "ranked_up":  False,
            "old_rank":   old_rank,
            "new_rank":   old_rank,
            "spirit_name": spirit["name"],
        }


def breed_spirits(profile: dict, idx_a: int, idx_b: int) -> dict:
    """
    Pokus o šlechtění dvou duchů.
    Vrátí {'success': bool, 'chance': float, 'survivor': dict|None,
            'new_spirit': dict|None, 'consumed_name': str}
    Při neúspěchu silnější pohltí slabšího (slabší zaniká).
    """
    spirits = profile.get("spirits", [])
    if not (0 <= idx_a < len(spirits) and 0 <= idx_b < len(spirits)):
        raise ValueError("Neplatné indexy duchů.")
    if idx_a == idx_b:
        raise ValueError("Nelze kombinovat ducha se sebou samým.")

    a, b   = spirits[idx_a], spirits[idx_b]
    rank_a, rank_b = a["rank"], b["rank"]
    diff   = abs(rank_a - rank_b)
    chance = BREED_CHANCE.get(diff, 0.0) if diff <= 3 else 0.0

    # Element modifier
    elem_a, elem_b = a.get("element", ""), b.get("element", "")
    if elem_a == elem_b:
        chance = min(1.0, chance + BREED_ELEMENT_BONUS)
    else:
        chance = max(0.0, chance - BREED_ELEMENT_PENALTY)

    stronger_idx = idx_a if rank_a >= rank_b else idx_b
    weaker_idx   = idx_b if rank_a >= rank_b else idx_a
    stronger, weaker = spirits[stronger_idx], spirits[weaker_idx]

    success = random.random() < chance

    # Odstraň oba duchy (od vyššího indexu, aby nesklouzl)
    for idx in sorted([idx_a, idx_b], reverse=True):
        spirits.pop(idx)

    # Opravi equipped_spirit_idx pokud byl ovlivněn
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
        new_rank  = max(rank_a, rank_b) + 1
        new_fury  = a["fury"] + b["fury"]
        new_elem  = elem_a if elem_a == elem_b else f"{elem_a}/{elem_b}"
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
        # Silnější přežívá (mírně posílí fury)
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
# HELPERS — formátování
# ══════════════════════════════════════════════════════════════════════════════

def _spirit_line(s: dict, equipped: bool = False) -> str:
    elem     = s.get("element", "?")
    elem_cfg = ELEMENTS.get(elem.split("/")[0], {})
    emoji    = elem_cfg.get("emoji", "❓")
    eq       = " ◀ *equipnutý*" if equipped else ""
    return (
        f"{SPIRIT_EMO} **{s['name']}** {emoji}  ·  {rank_label(s['rank'])}  ·  "
        f"{s['fury']} {FU_EMO}  ·  XP: {s.get('xp', 0)}/{s.get('xp_threshold', rank_xp_threshold(s['rank']))}"
        f"{eq}"
    )

def _spirit_embed(s: dict, title: str = None) -> discord.Embed:
    elem     = s.get("element", "?")
    elem_cfg = ELEMENTS.get(elem.split("/")[0], {})
    emoji    = elem_cfg.get("emoji", "❓")
    color    = rank_color(s["rank"])
    embed = discord.Embed(
        title=title or f"{SPIRIT_EMO} {s['name']}",
        color=color,
    )
    embed.add_field(name="Rank",    value=rank_label(s["rank"]),       inline=True)
    embed.add_field(name="Element", value=f"{emoji} {elem}",           inline=True)
    embed.add_field(name="Furioka", value=f"{s['fury']} {FU_EMO}",     inline=True)
    xp_thresh = s.get("xp_threshold", rank_xp_threshold(s["rank"]))
    embed.add_field(
        name="Progres",
        value=f"XP: **{s.get('xp', 0)}** / {xp_thresh}  ·  Celkem: {s.get('total_xp', 0)}",
        inline=False,
    )
    if s.get("description"):
        embed.add_field(name="Popis", value=f"*{s['description']}*", inline=False)
    embed.set_footer(text=f"Získán: {s.get('created_at', '?')[:10]}")
    return embed

# ══════════════════════════════════════════════════════════════════════════════
# CONFIRM VIEW — potvrzení před destruktivní akcí
# ══════════════════════════════════════════════════════════════════════════════

class BreedConfirmView(discord.ui.View):
    """Tlačítka Potvrdit / Zrušit pro šlechtění."""

    def __init__(self, profile: dict, data: dict, idx_a: int, idx_b: int,
                 a: dict, b: dict, chance: float):
        super().__init__(timeout=30)
        self.profile = profile
        self.data    = data
        self.idx_a   = idx_a
        self.idx_b   = idx_b
        self.a       = a
        self.b       = b
        self.chance  = chance
        self.done    = False

    async def on_timeout(self):
        if not self.done:
            for item in self.children:
                item.disabled = True

    @discord.ui.button(label="Potvrdit šlechtění", style=discord.ButtonStyle.danger, emoji="⚗️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.done = True
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        try:
            result = breed_spirits(self.profile, self.idx_a, self.idx_b)
        except ValueError as e:
            await interaction.followup.send(f"❌ {e}")
            return

        _save(self.data)

        chance_pct = int(result["chance"] * 100)
        if result["success"]:
            ns = result["new_spirit"]
            embed = discord.Embed(
                title="✨ Šlechtění úspěšné!",
                description=(
                    f"**{self.a['name']}** a **{self.b['name']}** se sloučili!\nNový duch je equipnutý a připraven."

                    f"Nový duch je equipnutý a připraven."
                ),
                color=rank_color(ns["rank"]),
            )
            embed.add_field(name="Jméno",   value=ns["name"],               inline=True)
            embed.add_field(name="Rank",    value=rank_label(ns["rank"]),   inline=True)
            embed.add_field(name="Furioka", value=f"{ns['fury']} {FU_EMO}", inline=True)
            elem_emoji = ELEMENTS.get(ns["element"].split("/")[0], {}).get("emoji", "❓")
            embed.add_field(name="Element", value=f"{elem_emoji} {ns['element']}", inline=True)
            embed.set_footer(text=f"Šance byla {chance_pct}%")
        else:
            sv = result["survivor"]
            embed = discord.Embed(
                title="💀 Šlechtění selhalo",
                description=(
                    f"**{result['consumed_name']}** byl pohlcen!\n**{sv['name']}** přežil a mírně zesílil ({sv['fury']} {FU_EMO})."

                    f"**{sv['name']}** přežil a mírně zesílil ({sv['fury']} {FU_EMO})."
                ),
                color=0x888780,
            )
            embed.set_footer(text=f"Šance byla {chance_pct}%")

        await interaction.followup.send(embed=embed)

    @discord.ui.button(label="Zrušit", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.done = True
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="*Šlechtění zrušeno. Oba duchové přežili.*", view=self
        )


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class Spirits(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /duch-pridat ──────────────────────────────────────────────────────────

    @app_commands.command(
        name="duch-pridat",
        description="[DM] Přidá hráči nového strážného ducha.",
    )
    @app_commands.describe(
        member="Hráč",
        name="Jméno ducha",
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
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        name: str,
        rank: int,
        fury: int,
        element: app_commands.Choice[str],
        description: str = "",
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        if fury < 0:
            await interaction.followup.send("❌ Furioka musí být nezáporné.")
            return
        if rank < 1:
            await interaction.followup.send("❌ Rank musí být alespoň 1.")
            return

        data    = _load()
        uid     = str(member.id)
        profile = data.setdefault(uid, {})
        spirits = profile.setdefault("spirits", [])

        if any(s["name"].lower() == name.lower() for s in spirits):
            await interaction.followup.send(
                f"❌ Hráč **{member.display_name}** už má ducha jménem **{name}**."
            )
            return

        spirit = _default_spirit(name, rank, fury, element.value, description)
        spirits.append(spirit)
        _save(data)

        embed = _spirit_embed(spirit, title=f"✅ Duch přidán — {name}")
        embed.description = f"Přidán hráči **{member.display_name}**. Použij `/duch-equip` k equipnutí."
        await interaction.followup.send(embed=embed)

    # ── /duch-xp ──────────────────────────────────────────────────────────────

    @app_commands.command(
        name="duch-xp",
        description="[DM] Přidej duchovi XP (simuluje využití furioku).",
    )
    @app_commands.describe(
        member="Hráč",
        amount="Množství XP",
    )
    async def duch_xp(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: int,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        if amount <= 0:
            await interaction.followup.send("❌ Množství musí být kladné.")
            return

        data    = _load()
        uid     = str(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return

        spirit = get_equipped_spirit(profile)
        if spirit is None:
            await interaction.followup.send(
                f"❌ **{member.display_name}** nemá equipnutého ducha."
            )
            return

        result = grant_spirit_xp(profile, amount)
        _save(data)

        spirit = get_equipped_spirit(profile)
        if result and result["ranked_up"]:
            embed = discord.Embed(
                title=f"⬆️ Duch posílil! — {spirit['name']}",
                description=(
                    f"**{member.display_name}**'s duch postoupil na **{rank_label(spirit['rank'])}**!\n\n"
                    f"{rank_label(result['old_rank'])} → **{rank_label(result['new_rank'])}**\n"
                    f"Furioka: **{spirit['fury']}** {FU_EMO}"
                ),
                color=rank_color(spirit["rank"]),
            )
            await interaction.followup.send(embed=embed)
        elif result and not result["ranked_up"]:
            await interaction.followup.send(
                f"✅ +**{amount} XP** pro ducha **{spirit['name']}**.\n"
                f"Pokus o rank-up selhal — threshold se zvýšil.\n"
                f"XP: **{spirit['xp']}** / {spirit['xp_threshold']}"
            )
        else:
            await interaction.followup.send(
                f"✅ +**{amount} XP** pro ducha **{spirit['name']}**.\n"
                f"XP: **{spirit['xp']}** / {spirit['xp_threshold']}"
            )

    # ── /duch-slechtit ────────────────────────────────────────────────────────

    @app_commands.command(
        name="duch-slechtit",
        description="Pokus o šlechtění dvou duchů — silnější může pohltit slabšího!",
    )
    @app_commands.describe(
        jmeno_a="Jméno prvního ducha",
        jmeno_b="Jméno druhého ducha",
    )
    async def duch_slechtit(
        self,
        interaction: discord.Interaction,
        jmeno_a: str,
        jmeno_b: str,
    ):
        await interaction.response.defer(ephemeral=False)
        data    = _load()
        uid     = str(interaction.user.id)
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

        a, b = spirits[idx_a], spirits[idx_b]
        rank_diff = abs(a["rank"] - b["rank"])

        # Varování při velkém rozdílu — spočítej skutečnou šanci
        base_chance = BREED_CHANCE.get(rank_diff, 0.0) if rank_diff <= 3 else 0.0
        elem_a_warn = a.get("element", "")
        elem_b_warn = b.get("element", "")
        if elem_a_warn == elem_b_warn:
            warn_chance = min(1.0, base_chance + BREED_ELEMENT_BONUS)
        else:
            warn_chance = max(0.0, base_chance - BREED_ELEMENT_PENALTY)

        if rank_diff >= 4:
            warn_pct = int(warn_chance * 100)
            embed = discord.Embed(
                title="⚠️ Nebezpečné šlechtění",
                description=(
                    f"Rozdíl ranku je **{rank_diff}** — šance na úspěch je jen **{warn_pct}%**.\n"
                    f"Při neúspěchu silnější duch pohltí slabšího.\n\n"
                    f"**{a['name']}** (R{a['rank']}) × **{b['name']}** (R{b['rank']})\n"
                    "Šlechtění přesto probíhá..."
                ),
                color=0xe74c3c,
            )
            await interaction.followup.send(embed=embed)

        # Ukázat náhled + potvrzovací tlačítka
        elem_emoji_a = ELEMENTS.get(a.get("element", "").split("/")[0], {}).get("emoji", "❓")
        elem_emoji_b = ELEMENTS.get(b.get("element", "").split("/")[0], {}).get("emoji", "❓")
        confirm_embed = discord.Embed(
            title="⚗️ Potvrdit šlechtění?",
            description=(
                f"{elem_emoji_a} **{a['name']}** {rank_label(a['rank'])}  ×  "
                f"{elem_emoji_b} **{b['name']}** {rank_label(b['rank'])}\n\n"
                f"Šance úspěchu: **{int(warn_chance * 100)}%**\n"
                "Při neúspěchu slabší duch zanikne — tato akce je nevratná!"
            ),
            color=0xf39c12,
        )
        view = BreedConfirmView(profile, data, idx_a, idx_b, a, b, warn_chance)
        await interaction.followup.send(embed=confirm_embed, view=view)

    # ── /duch-equip ───────────────────────────────────────────────────────────

    @app_commands.command(
        name="duch-equip",
        description="[DM] Equipni hráči strážného ducha.",
    )
    @app_commands.describe(member="Hráč", name="Jméno ducha")
    async def duch_equip(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        name: str,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return

        data    = _load()
        uid     = str(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return

        spirits = profile.get("spirits", [])
        idx     = next((i for i, s in enumerate(spirits) if s["name"].lower() == name.lower()), None)
        if idx is None:
            names = ", ".join(s["name"] for s in spirits) or "žádní"
            await interaction.followup.send(
                f"❌ Hráč nemá ducha **{name}**.\nDostupní: {names}"
            )
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

    # ── /duch-unequip ─────────────────────────────────────────────────────────

    @app_commands.command(
        name="duch-unequip",
        description="[DM] Odequipni strážného ducha hráče.",
    )
    @app_commands.describe(member="Hráč")
    async def duch_unequip(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return

        data    = _load()
        uid     = str(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return

        spirit = get_equipped_spirit(profile)
        if spirit is None:
            await interaction.followup.send(
                f"ℹ️ **{member.display_name}** nemá equipnutého ducha."
            )
            return

        profile["equipped_spirit_idx"] = None
        _save(data)
        await interaction.followup.send(
            f"✅ Duch **{spirit['name']}** odequipnut. Zůstává v kolekci."
        )

    # ── /duch-upravit ─────────────────────────────────────────────────────────

    @app_commands.command(
        name="duch-upravit",
        description="[DM] Uprav hodnoty existujícího ducha.",
    )
    @app_commands.describe(
        member="Hráč",
        name="Jméno ducha",
        nove_fury="Nová hodnota furioku",
        novy_rank="Nový rank",
        novy_popis="Nový popis",
        nove_jmeno="Přejmenovat ducha",
    )
    async def duch_upravit(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        name: str,
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
        uid     = str(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return

        spirits = profile.get("spirits", [])
        spirit  = next((s for s in spirits if s["name"].lower() == name.lower()), None)
        if spirit is None:
            names = ", ".join(s["name"] for s in spirits) or "žádní"
            await interaction.followup.send(
                f"❌ Hráč nemá ducha **{name}**.\nDostupní: {names}"
            )
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

    # ── /duch-odebrat ─────────────────────────────────────────────────────────

    @app_commands.command(
        name="duch-odebrat",
        description="[DM] Trvale odebere ducha z kolekce hráče.",
    )
    @app_commands.describe(member="Hráč", name="Jméno ducha")
    async def duch_odebrat(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        name: str,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return

        data    = _load()
        uid     = str(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return

        spirits = profile.get("spirits", [])
        idx     = next((i for i, s in enumerate(spirits) if s["name"].lower() == name.lower()), None)
        if idx is None:
            names = ", ".join(s["name"] for s in spirits) or "žádní"
            await interaction.followup.send(
                f"❌ Hráč nemá ducha **{name}**.\nDostupní: {names}"
            )
            return

        equipped_idx = profile.get("equipped_spirit_idx")
        if equipped_idx == idx:
            profile["equipped_spirit_idx"] = None
        elif equipped_idx is not None and equipped_idx > idx:
            profile["equipped_spirit_idx"] -= 1

        spirits.pop(idx)
        _save(data)
        await interaction.followup.send(
            f"✅ Duch **{name}** trvale odebrán hráči **{member.display_name}**."
        )

    # ── /duch-seznam ──────────────────────────────────────────────────────────

    @app_commands.command(
        name="duch-seznam",
        description="Zobraz seznam strážných duchů hráče.",
    )
    @app_commands.describe(member="Hráč (výchozí: ty)")
    async def duch_seznam(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target  = member or interaction.user
        data    = _load()
        uid     = str(target.id)
        profile = data.get(uid)

        if not profile:
            await interaction.followup.send(f"❌ **{target.display_name}** nemá profil.")
            return

        spirits      = profile.get("spirits", [])
        equipped_idx = profile.get("equipped_spirit_idx")

        if not spirits:
            await interaction.followup.send(
                f"*{target.display_name} nemá žádného strážného ducha.*"
            )
            return

        lines = [
            _spirit_line(s, equipped=(i == equipped_idx))
            + (f"\n-# *{s['description']}*" if s.get("description") else "")
            for i, s in enumerate(spirits)
        ]

        embed = discord.Embed(
            title=f"{SPIRIT_EMO} Strážní duchové — {target.display_name}",
            description="\n\n".join(lines),
            color=0x9b59b6,
        )
        embed.set_footer(text=f"Celkem duchů: {len(spirits)}")
        await interaction.followup.send(embed=embed)

    # ── /duch-info ────────────────────────────────────────────────────────────

    @app_commands.command(
        name="duch-info",
        description="Zobraz detailní info o konkrétním duchovi.",
    )
    @app_commands.describe(
        name="Jméno ducha",
        member="Hráč (výchozí: ty)",
    )
    async def duch_info(
        self,
        interaction: discord.Interaction,
        name: str,
        member: Optional[discord.Member] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target  = member or interaction.user
        data    = _load()
        uid     = str(target.id)
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

        spirit = spirits[idx]
        equipped = (idx == equipped_idx)
        title = f"{SPIRIT_EMO} {spirit['name']}" + (" ◀ equipnutý" if equipped else "")
        embed = _spirit_embed(spirit, title=title)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Spirits(bot))