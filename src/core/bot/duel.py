"""
/duel @hráč <sázka> — Textová tahová 1v1 aréna. Minigame pro ArionBOT.
"""
import asyncio
import random
import discord
from discord.ext import commands
from discord import app_commands

from src.utils.paths import ECONOMY as ECONOMY_FILE
from src.utils.json_utils import load_json, save_json

COIN = "<:goldcoin:1490171741237018795>"

# ── Bojové třídy ──────────────────────────────────────────────────────────────

CLASSES: dict[str, dict] = {
    "Monk": {
        "emoji": "🥷", "hp": 85, "stamina": 120, "posture": 120, "recover": 40,
        "dmg_mod": 1.00, "color": 0xE67E22,
        "guard_absorb": 0.38, "recover_hp": 10,
        "passive": "Meditativní tok — Odpočinek léčí +10 HP navíc",
        "lore": "Disciplinovaný bojovník těla i ducha. Nikdy neutíká od boje.",
        "basic_name": "Meditace",           "basic_desc": "Obnov 30 HP a 10 sta",     "basic_cd": 3,
        "ult_name":   "Duch bouře",         "ult_desc":   "~70 dmg + 40 posture dmg",  "ult_charge_max": 5,
    },
    "Knight": {
        "emoji": "🛡️", "hp": 120, "stamina": 80, "posture": 160, "recover": 25,
        "dmg_mod": 1.15, "color": 0x95A5A6,
        "guard_absorb": 0.58, "recover_hp": 8,
        "passive": "Železná pevnost — nejsilnější štít v aréně",
        "lore": "Obrněný válečník. Pomalý. Neúprosný.",
        "basic_name": "Požehnání",          "basic_desc": "Obnov 45 sta a 40 posture", "basic_cd": 3,
        "ult_name":   "Úder spravedlnosti", "ult_desc":   "~80 dmg, ignoruje štít",    "ult_charge_max": 5,
    },
    "Rogue": {
        "emoji": "🗡️", "hp": 75, "stamina": 105, "posture": 90, "recover": 35,
        "dmg_mod": 0.95, "color": 0x2C3E50,
        "guard_absorb": 0.20, "recover_hp": 6,
        "passive": "Stínový krok — úskok vyhýbá VŠEM útokům + free counter",
        "lore": "Rychlý a zákeřný. Kdo ho uvidí, je mrtvý.",
        "basic_name": "Jedová čepel",       "basic_desc": "+20 jed / 2 kola",          "basic_cd": 3,
        "ult_name":   "Zákeřný úder",       "ult_desc":   "~90 dmg, nelze blokovat",   "ult_charge_max": 4,
    },
    "Berserker": {
        "emoji": "🪓", "hp": 100, "stamina": 90, "posture": 100, "recover": 30,
        "dmg_mod": 1.35, "color": 0xE74C3C,
        "guard_absorb": 0.25, "recover_hp": 5,
        "passive": "Krvavý hněv — pod 30 HP: dmg +50 %",
        "lore": "Šílený válečník. Čím méně HP, tím nebezpečnější.",
        "basic_name": "Bojový řev",         "basic_desc": "Příští útok +80 % (viditelné!)", "basic_cd": 4,
        "ult_name":   "Zběsilost",          "ult_desc":   "3 kola: 2× útok, nelze štítit, -8 HP/kolo", "ult_charge_max": 4,
    },
    "Guardian": {
        "emoji": "⚜️", "hp": 110, "stamina": 85, "posture": 150, "recover": 30,
        "dmg_mod": 1.00, "color": 0x27AE60,
        "guard_absorb": 0.55, "recover_hp": 8,
        "passive": "Trny — štít vrací 10 dmg útočníkovi",
        "lore": "Neproniknutelný. Protiúder je smrtící.",
        "basic_name": "Provokace",          "basic_desc": "Příší zásah -60 % + obnov posture", "basic_cd": 3,
        "ult_name":   "Odvetný úder",       "ult_desc":   "Odraz příštího útoku zpět",  "ult_charge_max": 5,
    },
    "Duelist": {
        "emoji": "🤺", "hp": 80, "stamina": 100, "posture": 100, "recover": 35,
        "dmg_mod": 1.05, "color": 0x9B59B6,
        "guard_absorb": 0.35, "recover_hp": 7,
        "passive": "Přesné oko — klam ignoruje štít úplně, plný dmg",
        "lore": "Elegantní. Každá akce je kalkulovaná.",
        "basic_name": "Přesný výpad",       "basic_desc": "~40 dmg + posture dmg, nelze blokovat", "basic_cd": 2,
        "ult_name":   "Dokonalý souboj",    "ult_desc":   "Riposte stance: příší útok → 150 % counter", "ult_charge_max": 4,
    },
}

CLASS_NAMES = list(CLASSES.keys())

# ── Akce ─────────────────────────────────────────────────────────────────────

STAM_COSTS = {
    "attack": 15, "heavy": 25, "guard": 10,
    "feint": 12,  "dodge": 15, "recover": 0,
    "basic": 0,   "ultimate": 0,
}

BASE_ATK   = 20
BASE_HEAVY = 35
PARRY_CTR  = 15

# ── Fighter ───────────────────────────────────────────────────────────────────

class Fighter:
    def __init__(self, member: discord.Member, cls_name: str):
        self.member      = member
        self.cls_name    = cls_name
        cls              = CLASSES[cls_name]
        self.hp          = cls["hp"]
        self.max_hp      = cls["hp"]
        self.stamina     = cls["stamina"]
        self.max_sta     = cls["stamina"]
        self.posture     = cls["posture"]
        self.max_posture = cls["posture"]
        self.ult_charge  = 0
        # State
        self.guard_broken: bool = False  # next hit bypasses defense + 1.5×
        self.berserk:      int  = 0      # Berserker ult: rounds remaining
        self.riposte:      bool = False  # Duelist ult: riposte stance
        self.buff_heavy:   bool = False  # Berserker basic: next attack +80 %
        self.buff_poison:  int  = 0      # Rogue: poison rounds left
        self.buff_absorb:  bool = False  # Guardian basic
        self.buff_reflect: bool = False  # Guardian ult
        self.cooldowns: dict[str, int] = {"basic": 0}
        self.action: str | None = None

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def exhausted(self) -> bool:
        return self.stamina < 5


# ── DuelState ─────────────────────────────────────────────────────────────────

class DuelState:
    def __init__(self, f1: Fighter, f2: Fighter, bet: int, channel: discord.TextChannel):
        self.f1        = f1
        self.f2        = f2
        self.bet       = bet
        self.channel   = channel
        self.round     = 0
        self.done      = False
        self._lock     = asyncio.Lock()
        self.arena_msg: discord.Message | None = None
        self.last_a1: str | None = None  # for telegraph display
        self.last_a2: str | None = None

    def both_chose(self) -> bool:
        return self.f1.action is not None and self.f2.action is not None


# ── Registry ──────────────────────────────────────────────────────────────────

_active: dict[int, DuelState] = {}

def _register(state: DuelState):
    _active[state.f1.member.id] = state
    _active[state.f2.member.id] = state

def _cleanup(state: DuelState):
    _active.pop(state.f1.member.id, None)
    _active.pop(state.f2.member.id, None)
    state.done = True

# ── Vizuální helpers ──────────────────────────────────────────────────────────

def _bar(cur: int, max_: int, n: int = 10) -> str:
    filled = max(0, round(n * max(0, cur) / max_)) if max_ > 0 else 0
    return "█" * filled + "░" * (n - filled)

def _ult_bar(charge: int, max_: int) -> str:
    return "▰" * charge + "▱" * (max_ - charge)

def _hp_icon(hp: int, max_hp: int) -> str:
    r = hp / max_hp if max_hp > 0 else 0
    return "🟢" if r > 0.55 else ("🟡" if r > 0.25 else "🔴")

def _pos_icon(pos: int, max_pos: int) -> str:
    r = pos / max_pos if max_pos > 0 else 0
    return "🔵" if r > 0.50 else ("🟠" if r > 0.25 else "🔴")

def _fighter_bar(f: Fighter) -> str:
    cls   = CLASSES[f.cls_name]
    hi    = _hp_icon(max(0, f.hp), f.max_hp)
    pi    = _pos_icon(max(0, f.posture), f.max_posture)
    max_c = cls["ult_charge_max"]
    ub    = _ult_bar(f.ult_charge, max_c)
    ready = " ✨ READY!" if f.ult_charge >= max_c else f" {f.ult_charge}/{max_c}"

    tags = []
    if f.guard_broken:           tags.append("💔 GUARD BREAK")
    if f.berserk > 0:            tags.append(f"🔥 BERSERK {f.berserk}")
    if f.riposte:                tags.append("⚡ RIPOSTE")
    if f.buff_heavy:             tags.append("💢 NABITO")
    if f.buff_poison > 0:        tags.append(f"☠️ JED {f.buff_poison}")
    tag_line = ("  " + "  ".join(tags)) if tags else ""

    return (
        f"{cls['emoji']} **{f.member.display_name}** — {f.cls_name}{tag_line}\n"
        f"`HP  [{_bar(f.hp, f.max_hp)}]` {hi} {max(0, f.hp)}/{f.max_hp}\n"
        f"`STA [{_bar(f.stamina, f.max_sta)}]` ⚡ {max(0, f.stamina)}/{f.max_sta}\n"
        f"`POS [{_bar(f.posture, f.max_posture)}]` {pi} {max(0, f.posture)}/{f.max_posture}\n"
        f"`ULT [{ub}]`{ready}"
    )

def _hp_warning(f: Fighter) -> str | None:
    pct = f.hp / f.max_hp if f.max_hp > 0 else 0
    if pct <= 0.15: return f"☠️ **{f.member.display_name}** se sotva drží na nohou..."
    if pct <= 0.28: return f"⚠️ **{f.member.display_name}** je těžce raněn!"
    return None

# ── Damage resolution ─────────────────────────────────────────────────────────

def _rdm(base: int, var: int = 4) -> int:
    return base + random.randint(-var, var)

def _eff(f: Fighter, base: int) -> int:
    stam_mod  = max(0.5, f.stamina / f.max_sta) if f.max_sta > 0 else 0.5
    class_mod = CLASSES[f.cls_name]["dmg_mod"]
    rage_mod  = 1.5 if f.cls_name == "Berserker" and f.hp <= 30 else 1.0
    boost_mod = 1.8 if f.buff_heavy else 1.0
    f.buff_heavy = False
    return max(1, round(base * class_mod * stam_mod * rage_mod * boost_mod))

def _atk(f: Fighter) -> int: return _eff(f, _rdm(BASE_ATK))
def _hvy(f: Fighter) -> int: return _eff(f, _rdm(BASE_HEAVY, 5))

def _ctr(f: Fighter) -> int:
    mult = 1.5 if f.cls_name == "Duelist" else 1.0
    return max(1, round(PARRY_CTR * mult * CLASSES[f.cls_name]["dmg_mod"]))

def _guard_absorb(f: Fighter, raw: int) -> tuple[int, int]:
    """Returns (damage_taken, posture_damage)."""
    absorb = CLASSES[f.cls_name]["guard_absorb"]
    if f.buff_absorb:
        absorb = min(0.88, absorb + 0.5)
        f.buff_absorb = False
    return round(raw * (1 - absorb)), 15

def _posture_break(f: Fighter, log: list[str]):
    """Apply guard break effect."""
    f.guard_broken = True
    f.posture = f.max_posture  # reset
    log.append(f"💔 **GUARD BREAK** — obrана {f.member.display_name} se hroutí!")

def _apply_posture_dmg(f: Fighter, pdmg: int, log: list[str]):
    f.posture = max(0, f.posture - pdmg)
    if f.posture == 0:
        _posture_break(f, log)

def _apply_broken_bonus(raw: int) -> int:
    return round(raw * 1.5)

# ── Ability handlers ──────────────────────────────────────────────────────────

def _apply_basic(f: Fighter, log: list[str]) -> int:
    """Applies basic ability. Returns damage to deal to opponent."""
    cls = CLASSES[f.cls_name]
    f.cooldowns["basic"] = cls["basic_cd"]
    n = f.member.display_name
    if f.cls_name == "Monk":
        heal = 30; sta = 10
        f.hp = min(f.max_hp, f.hp + heal)
        f.stamina = min(f.max_sta, f.stamina + sta)
        log.append(f"✨ **{n}** se ponoří do klidu — **+{heal} HP**, **+{sta} staminy**.")
    elif f.cls_name == "Knight":
        sta = 45; pos = 40
        f.stamina = min(f.max_sta, f.stamina + sta)
        f.posture = min(f.max_posture, f.posture + pos)
        log.append(f"✨ **{n}** se požehná — **+{sta} sta**, posture zpevněna.")
    elif f.cls_name == "Rogue":
        f.buff_poison = 2
        log.append(f"☠️ **{n}** natírá čepel jedem... **+20 dmg** po 2 kola.")
    elif f.cls_name == "Berserker":
        f.buff_heavy = True
        log.append(f"💢 **{n}** zadusí řev — připravuje devastující úder!")
    elif f.cls_name == "Guardian":
        f.buff_absorb = True
        f.posture = min(f.max_posture, f.posture + 40)
        log.append(f"🛡️ **{n}** zpevňuje postoj — příší zásah **-60 %**, posture obnovena.")
    elif f.cls_name == "Duelist":
        dmg  = 40 + random.randint(-3, 3)
        pdmg = 20
        log.append(f"🤺 **{n}** — přesný výpad! **{dmg}** dmg, nelze blokovat.")
        return dmg
    return 0

def _apply_ultimate(f: Fighter, log: list[str]) -> int:
    """Applies ultimate. Returns damage to deal to opponent."""
    f.ult_charge = 0
    n = f.member.display_name
    if f.cls_name == "Monk":
        dmg  = 70 + random.randint(-5, 5)
        pdmg = 40
        log.append(f"💥 **{n}** — DUCH BOUŘE! Výbuch energie za **{dmg}** dmg!")
        return dmg
    elif f.cls_name == "Knight":
        dmg = 80 + random.randint(-5, 5)
        log.append(f"💥 **{n}** — ÚDER SPRAVEDLNOSTI! Meč proniká čistě — **{dmg}** dmg!")
        return dmg
    elif f.cls_name == "Rogue":
        dmg = 90 + random.randint(-5, 5)
        log.append(f"💥 **{n}** — ZÁKEŘNÝ ÚDER! Z temnoty — **{dmg}** dmg, žádná obrana!")
        return dmg
    elif f.cls_name == "Berserker":
        f.berserk = 3
        log.append(f"💥 **{n}** — ZBĚSILOST! Přichází šílenství. **3 kola berserk módu!**")
        return 0
    elif f.cls_name == "Guardian":
        f.buff_reflect = True
        log.append(f"💥 **{n}** — ODVETNÝ ÚDER! Připraven pohltit a vrátit vše zpět. ⚜️")
        return 0
    elif f.cls_name == "Duelist":
        f.riposte = True
        log.append(f"💥 **{n}** — DOKONALÝ SOUBOJ! Vstupuje do riposte stance... ⚡")
        return 0
    return 0

# ── Round resolution ──────────────────────────────────────────────────────────

def resolve_round(state: DuelState) -> list[str]:
    f1, f2 = state.f1, state.f2
    a1, a2 = f1.action, f2.action
    n1, n2 = f1.member.display_name, f2.member.display_name

    log: list[str] = []
    d1 = 0  # damage to f1
    d2 = 0  # damage to f2

    # Cooldown decrement
    for f in (f1, f2):
        for k in list(f.cooldowns):
            if f.cooldowns[k] > 0:
                f.cooldowns[k] -= 1

    # Stamina costs + recover
    f1.stamina = max(0, f1.stamina - STAM_COSTS.get(a1, 0))
    f2.stamina = max(0, f2.stamina - STAM_COSTS.get(a2, 0))
    if a1 == "recover":
        cls1 = CLASSES[f1.cls_name]
        f1.stamina = min(f1.max_sta, f1.stamina + cls1["recover"])
        f1.posture = min(f1.max_posture, f1.posture + 20)
        f1.hp = min(f1.max_hp, f1.hp + cls1["recover_hp"])
    if a2 == "recover":
        cls2 = CLASSES[f2.cls_name]
        f2.stamina = min(f2.max_sta, f2.stamina + cls2["recover"])
        f2.posture = min(f2.max_posture, f2.posture + 20)
        f2.hp = min(f2.max_hp, f2.hp + cls2["recover_hp"])

    # Posture passive recovery
    f1.posture = min(f1.max_posture, f1.posture + 5)
    f2.posture = min(f2.max_posture, f2.posture + 5)

    # Poison tick
    if f1.buff_poison > 0:
        d1 += 20; f1.buff_poison -= 1
        log.append(f"☠️ Jed pálí v žilách **{n1}** — **20** damage!")
    if f2.buff_poison > 0:
        d2 += 20; f2.buff_poison -= 1
        log.append(f"☠️ Jed pálí v žilách **{n2}** — **20** damage!")

    # Berserk HP drain
    if f1.berserk > 0:
        d1 += 8
        log.append(f"🔥 **{n1}** hoří zevnitř — **8** HP za šílenství.")
    if f2.berserk > 0:
        d2 += 8
        log.append(f"🔥 **{n2}** hoří zevnitř — **8** HP za šílenství.")

    # Nested helpers
    def do_guard(atk: Fighter, grd: Fighter, raw: int, is_heavy: bool = False) -> tuple[int, int]:
        if grd.guard_broken:
            dmg = _apply_broken_bonus(raw)
            log.append(f"💔 **{grd.member.display_name}** je otevřen — plný úder **{dmg}** dmg!")
            grd.guard_broken = False
            return dmg, 0
        dmg, pdmg = _guard_absorb(grd, raw)
        thorns = 10 if grd.cls_name == "Guardian" else 0
        if is_heavy:
            pdmg = 35
            log.append(f"🛡️ **{grd.member.display_name}** drží — ale heavy tříští postoj! **{dmg}** dmg.")
        else:
            log.append(f"🛡️ **{grd.member.display_name}** blokuje — přijímá pouze **{dmg}** dmg.")
        if thorns:
            log.append(f"✀ Trny vrací **{thorns}** zpět!")
        _apply_posture_dmg(grd, pdmg, log)
        return dmg, thorns

    def berserk_attack(f: Fighter) -> int:
        """Double attack for berserk mode."""
        d1b = _atk(f); d2b = _atk(f)
        dmg = d1b + d2b
        log.append(f"🪓 **{f.member.display_name}** útočí dvakrát — **{d1b}** + **{d2b}** = **{dmg}** dmg!")
        return dmg

    # ── Basic / Ultimate pre-pass ─────────────────────────────────────────────

    ab1 = a1 in ("basic", "ultimate")
    ab2 = a2 in ("basic", "ultimate")

    if a1 == "basic":
        d2 += _apply_basic(f1, log)
    if a2 == "basic":
        d1 += _apply_basic(f2, log)

    if a1 == "ultimate":
        raw = _apply_ultimate(f1, log)
        if f2.buff_reflect and raw > 0:
            d1 += raw; f2.buff_reflect = False
            log.append(f"🔄 **{n2}** ODRÁŽÍ útok — **{raw}** dmg letí zpět na **{n1}**!")
        else:
            d2 += raw

    if a2 == "ultimate":
        raw = _apply_ultimate(f2, log)
        if f1.buff_reflect and raw > 0:
            d2 += raw; f1.buff_reflect = False
            log.append(f"🔄 **{n1}** ODRÁŽÍ útok — **{raw}** dmg letí zpět na **{n2}**!")
        else:
            d1 += raw

    # ── Ability user is OPEN to normal attacks ────────────────────────────────

    if ab1 and not ab2:
        if a2 in ("attack", "heavy"):
            raw = _hvy(f2) if a2 == "heavy" else _atk(f2)
            if f1.guard_broken: raw = _apply_broken_bonus(raw); f1.guard_broken = False
            d1 += raw
            log.append(f"{'🪓' if a2 == 'heavy' else '⚔️'} **{n2}** trestá otevřenou pozici — **{raw}** dmg!")
        elif a2 == "feint":
            raw = _atk(f2); d1 += raw
            log.append(f"🎭 **{n2}** pronáší klam na otevřeného soupeře — **{raw}** dmg!")

    elif not ab1 and ab2:
        if a1 in ("attack", "heavy"):
            raw = _hvy(f1) if a1 == "heavy" else _atk(f1)
            if f2.guard_broken: raw = _apply_broken_bonus(raw); f2.guard_broken = False
            d2 += raw
            log.append(f"{'🪓' if a1 == 'heavy' else '⚔️'} **{n1}** trestá otevřenou pozici — **{raw}** dmg!")
        elif a1 == "feint":
            raw = _atk(f1); d2 += raw
            log.append(f"🎭 **{n1}** pronáší klam na otevřeného soupeře — **{raw}** dmg!")

    elif not ab1 and not ab2:

        # ── Berserk mode override ──────────────────────────────────────────────
        if f1.berserk > 0 and a1 in ("attack", "heavy", "feint"):
            raw = berserk_attack(f1)
            if f2.guard_broken: raw = _apply_broken_bonus(raw); f2.guard_broken = False
            elif a1 == "feint": pass  # feint still bypasses guard while berserk
            d2 += raw
            f1.berserk -= 1
            # f2 can still counter
            if a2 in ("attack", "heavy"):
                c = _hvy(f2) if a2 == "heavy" else _atk(f2)
                d1 += c
                log.append(f"⚔️ **{n2}** también odpovídá — **{c}** dmg!")
        elif f2.berserk > 0 and a2 in ("attack", "heavy", "feint"):
            raw = berserk_attack(f2)
            if f1.guard_broken: raw = _apply_broken_bonus(raw); f1.guard_broken = False
            d1 += raw
            f2.berserk -= 1
            if a1 in ("attack", "heavy"):
                c = _hvy(f1) if a1 == "heavy" else _atk(f1)
                d2 += c
                log.append(f"⚔️ **{n1}** también odpovídá — **{c}** dmg!")

        # ── Duelist riposte check ─────────────────────────────────────────────
        elif f1.riposte and a2 in ("attack", "heavy"):
            ctr = round(_ctr(f1) * 1.5)
            dmg_in = _hvy(f2) if a2 == "heavy" else _atk(f2)
            d1 += round(dmg_in * 0.2)  # tanked partial
            d2 += ctr
            f1.riposte = False
            log.append(f"⚡ **{n1}** čekal přesně na tohle — RIPOSTE za **{ctr}** dmg!")
            log.append(f"*{n1} inkasuje jen zlomek — **{round(dmg_in * 0.2)}** dmg.*")
        elif f2.riposte and a1 in ("attack", "heavy"):
            ctr = round(_ctr(f2) * 1.5)
            dmg_in = _hvy(f1) if a1 == "heavy" else _atk(f1)
            d2 += round(dmg_in * 0.2)
            d1 += ctr
            f2.riposte = False
            log.append(f"⚡ **{n2}** čekal přesně na tohle — RIPOSTE za **{ctr}** dmg!")
            log.append(f"*{n2} inkasuje jen zlomek — **{round(dmg_in * 0.2)}** dmg.*")

        # ── Normal matrix ─────────────────────────────────────────────────────

        elif a1 == "recover" and a2 == "recover":
            log.append("💚 Oba si oddechnou. Napětí v aréně stoupá...")

        elif a1 == "recover":
            log.append(f"💚 **{n1}** nabírá dech, hledá střed...")
            if a2 in ("attack", "heavy", "feint"):
                raw = round((_hvy(f2) if a2 == "heavy" else _atk(f2)) * 1.3)
                if f1.guard_broken: raw = _apply_broken_bonus(raw); f1.guard_broken = False
                d1 += raw
                log.append(f"💀 **{n2}** se vrhne vpřed — **{raw}** dmg bez milosti!")
            else:
                log.append(f"*{n2} se drží zpátky.*")

        elif a2 == "recover":
            log.append(f"💚 **{n2}** nabírá dech, hledá střed...")
            if a1 in ("attack", "heavy", "feint"):
                raw = round((_hvy(f1) if a1 == "heavy" else _atk(f1)) * 1.3)
                if f2.guard_broken: raw = _apply_broken_bonus(raw); f2.guard_broken = False
                d2 += raw
                log.append(f"💀 **{n1}** se vrhne vpřed — **{raw}** dmg bez milosti!")
            else:
                log.append(f"*{n1} se drží zpátky.*")

        elif a1 == "guard" and a2 == "guard":
            log.append("🛡️ Oba zvedají štíty — pat. Ticho.")
            f1.posture = min(f1.max_posture, f1.posture + 5)
            f2.posture = min(f2.max_posture, f2.posture + 5)

        elif a1 == "guard":
            if a2 == "attack":
                dmg, t = do_guard(f2, f1, _atk(f2)); d1 += dmg; d2 += t
            elif a2 == "heavy":
                dmg, t = do_guard(f2, f1, _hvy(f2), is_heavy=True); d1 += dmg; d2 += t
            elif a2 == "feint":
                raw = _atk(f2) if f2.cls_name != "Duelist" else round(_atk(f2) / 0.85)
                suffix = " *(Přesné oko — plný dmg)*" if f2.cls_name == "Duelist" else ""
                log.append(f"🎭 **{n2}** feintuje — štít brání vzduch! **{raw}** dmg proniká!{suffix}")
                _apply_posture_dmg(f1, 25, log)
                d1 += raw
            else:
                log.append(f"*{n2} nezaútočil na štít {n1}.*")

        elif a2 == "guard":
            if a1 == "attack":
                dmg, t = do_guard(f1, f2, _atk(f1)); d2 += dmg; d1 += t
            elif a1 == "heavy":
                dmg, t = do_guard(f1, f2, _hvy(f1), is_heavy=True); d2 += dmg; d1 += t
            elif a1 == "feint":
                raw = _atk(f1) if f1.cls_name != "Duelist" else round(_atk(f1) / 0.85)
                suffix = " *(Přesné oko — plný dmg)*" if f1.cls_name == "Duelist" else ""
                log.append(f"🎭 **{n1}** feintuje — štít brání vzduch! **{raw}** dmg proniká!{suffix}")
                _apply_posture_dmg(f2, 25, log)
                d2 += raw
            else:
                log.append(f"*{n1} nezaútočil na štít {n2}.*")

        elif a1 == "dodge" and a2 == "dodge":
            log.append("💨 Oba proplují kolem — kroužení, žádný kontakt.")

        elif a1 == "dodge":
            if a2 in ("attack", "heavy"):
                if f1.cls_name == "Rogue":
                    free_dmg = round(_atk(f1) * 0.7)
                    d2 += free_dmg
                    log.append(f"💨 **{n1}** *(Stínový krok)* — mizí z dosahu a kontrahuje za **{free_dmg}** dmg!")
                elif a2 == "heavy":
                    perfect = random.random() < 0.25
                    if perfect:
                        free_dmg = round(_atk(f1) * 0.8); d2 += free_dmg
                        log.append(f"💨 **PERFECT DODGE** — {n1} mizí z trajektorie heavy a kontrahuje! **{free_dmg}** dmg!")
                    else:
                        log.append(f"💨 **{n1}** vykračuje ze sekyry — heavy mine!")
                else:
                    dmg = round(_atk(f2) * 0.45); d1 += dmg
                    log.append(f"💨 **{n1}** částečně uhýbá — **{dmg}** dmg clippí ramenem.")
            elif a2 == "feint":
                if f1.cls_name == "Rogue":
                    log.append(f"💨 **{n1}** čte feint — mizí beze stopy.")
                else:
                    dmg = round(_atk(f2) * 0.45); d1 += dmg
                    log.append(f"🎭 **{n2}** feintuje a clippí uhýbajícího {n1} — **{dmg}** dmg.")
            else:
                log.append(f"**{n1}** uhýbá — ale {n2} nezaútočil.")

        elif a2 == "dodge":
            if a1 in ("attack", "heavy"):
                if f2.cls_name == "Rogue":
                    free_dmg = round(_atk(f2) * 0.7)
                    d1 += free_dmg
                    log.append(f"💨 **{n2}** *(Stínový krok)* — mizí z dosahu a kontrahuje za **{free_dmg}** dmg!")
                elif a1 == "heavy":
                    perfect = random.random() < 0.25
                    if perfect:
                        free_dmg = round(_atk(f2) * 0.8); d1 += free_dmg
                        log.append(f"💨 **PERFECT DODGE** — {n2} mizí z trajektorie heavy a kontrahuje! **{free_dmg}** dmg!")
                    else:
                        log.append(f"💨 **{n2}** vykračuje ze sekyry — heavy mine!")
                else:
                    dmg = round(_atk(f1) * 0.45); d2 += dmg
                    log.append(f"💨 **{n2}** částečně uhýbá — **{dmg}** dmg clippí ramenem.")
            elif a1 == "feint":
                if f2.cls_name == "Rogue":
                    log.append(f"💨 **{n2}** čte feint — mizí beze stopy.")
                else:
                    dmg = round(_atk(f1) * 0.45); d2 += dmg
                    log.append(f"🎭 **{n1}** feintuje a clippí uhýbajícího {n2} — **{dmg}** dmg.")
            else:
                log.append(f"**{n2}** uhýbá — ale {n1} nezaútočil.")

        elif a1 == "feint" and a2 == "feint":
            t1 = _atk(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append("🎭 Oba feintují — oba se přeříznout! Dav vzhlíží...")
            log.append(f"*Simultánní hit: **{t2}** / **{t1}** dmg.*")

        elif a1 == "attack" and a2 == "attack":
            t1 = _atk(f2); t2 = _atk(f1)
            if f1.guard_broken: t1 = _apply_broken_bonus(t1); f1.guard_broken = False
            if f2.guard_broken: t2 = _apply_broken_bonus(t2); f2.guard_broken = False
            d1 += t1; d2 += t2
            log.append(f"⚔️ **{n1}** vs **{n2}** — čepele se kříží!")
            log.append(f"*Oba si vymění rány. **{t2}** / **{t1}** dmg.*")

        elif a1 == "attack" and a2 == "feint":
            t1 = _atk(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append(f"⚔️ **{n1}** zaútočí — **{n2}** zároveň prolézá obranou. Oba zasáhnou.")

        elif a1 == "feint" and a2 == "attack":
            t1 = _atk(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append(f"🎭 **{n1}** se vmísí — **{n2}** zároveň prolézá. Oba zasáhnou.")

        elif a1 == "heavy" and a2 == "heavy":
            t1 = _hvy(f2); t2 = _hvy(f1)
            if f1.guard_broken: t1 = _apply_broken_bonus(t1); f1.guard_broken = False
            if f2.guard_broken: t2 = _apply_broken_bonus(t2); f2.guard_broken = False
            d1 += t1; d2 += t2
            _apply_posture_dmg(f1, 20, log); _apply_posture_dmg(f2, 20, log)
            log.append("💥 **MASIVNÍ KOLIZE** — oba heavy se střetnou!")
            log.append(f"*Aréna se třese. **{t2}** / **{t1}** dmg. Postoje otřeseny.*")

        elif a1 == "heavy" and a2 == "attack":
            t1 = _atk(f2); t2 = _hvy(f1)
            d1 += t1; d2 += t2
            _apply_posture_dmg(f2, 20, log)
            log.append(f"⚔️ **{n2}** zaútočí rychle — ale **{n1}**'s heavy dopadá tíhou.")

        elif a1 == "attack" and a2 == "heavy":
            t1 = _hvy(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            _apply_posture_dmg(f1, 20, log)
            log.append(f"⚔️ **{n1}** zaútočí rychle — ale **{n2}**'s heavy dopadá tíhou.")

        elif a1 == "heavy" and a2 == "feint":
            t1 = _atk(f2); t2 = _hvy(f1)
            d1 += t1; d2 += t2
            log.append(f"🎭 **{n2}** čte heavy a propluje — **{t1}** dmg. Ale heavy stejně dopadá — **{t2}** dmg.")

        elif a1 == "feint" and a2 == "heavy":
            t1 = _hvy(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append(f"🎭 **{n1}** čte heavy a propluje — **{t2}** dmg. Ale heavy stejně dopadá — **{t1}** dmg.")

        else:
            log.append("Boj pokračuje... nikdo nespěchá.")

    # ── Apply damage ──────────────────────────────────────────────────────────

    f1.hp -= d1
    f2.hp -= d2

    if not log:
        log.append("*Ticho. Nikdo se nehýbá.*")

    # ── Ult charge ────────────────────────────────────────────────────────────
    atk_acts = ("attack", "heavy", "feint")
    if a1 in atk_acts and d2 > 0:
        f1.ult_charge = min(CLASSES[f1.cls_name]["ult_charge_max"], f1.ult_charge + 1)
    if a2 in atk_acts and d1 > 0:
        f2.ult_charge = min(CLASSES[f2.cls_name]["ult_charge_max"], f2.ult_charge + 1)
    if a1 == "basic" and f1.cls_name == "Duelist" and d2 > 0:
        f1.ult_charge = min(CLASSES["Duelist"]["ult_charge_max"], f1.ult_charge + 1)
    if a2 == "basic" and f2.cls_name == "Duelist" and d1 > 0:
        f2.ult_charge = min(CLASSES["Duelist"]["ult_charge_max"], f2.ult_charge + 1)

    # ── Telegraph ─────────────────────────────────────────────────────────────
    state.last_a1 = a1
    state.last_a2 = a2

    f1.action = None
    f2.action = None
    return log

# ── Embed builders ────────────────────────────────────────────────────────────

CROWD_LINES = [
    "Dav jásá!", "Aréna zní výkřiky!", "Krev na písku.",
    "Nikdo neopouští svá místa.", "Napětí je hmatatelné.",
    "Aréna drží dech.", "Bouře se schyluje.",
]

FINISHERS = [
    "padá na kolena — aréna ztichne.",
    "se zhroutí pod posledním úderem.",
    "zakolísá a padá. Hotovo.",
    "je poražen. Aréna exploduje výkřiky!",
    "nemůže vstát. Duel rozhodnut.",
]

def build_round_embed(state: DuelState, log: list[str]) -> discord.Embed:
    f1, f2 = state.f1, state.f2
    sep    = "━" * 22
    parts  = [
        f"**Kolo {state.round}** — {random.choice(CROWD_LINES)}",
        f"`{sep}`",
        *log,
        f"`{sep}`",
        "",
        _fighter_bar(f1),
        "",
        _fighter_bar(f2),
    ]
    for f in (f1, f2):
        w = _hp_warning(f)
        if w: parts += ["", w]

    embed = discord.Embed(
        title=f"⚔️  {f1.member.display_name}  vs  {f2.member.display_name}",
        description="\n".join(parts),
        color=0x1a1a2e,
    )
    footer = f"⭐ Aurionis  ·  Kolo {state.round}"
    if state.bet: footer += f"  ·  Sázka: {state.bet} {COIN}"
    embed.set_footer(text=footer)
    return embed

def build_status_embed(state: DuelState) -> discord.Embed:
    f1, f2  = state.f1, state.f2
    parts   = [_fighter_bar(f1), "", _fighter_bar(f2), ""]

    # Telegraph warnings
    if state.last_a1 == "heavy":
        parts.append(f"⚠️ *{f1.member.display_name} se rozmáchá...*")
    if state.last_a2 == "heavy":
        parts.append(f"⚠️ *{f2.member.display_name} se rozmáchá...*")
    if f1.buff_heavy:
        parts.append(f"💢 *{f1.member.display_name} nabil úder — POZOR!*")
    if f2.buff_heavy:
        parts.append(f"💢 *{f2.member.display_name} nabil úder — POZOR!*")

    parts.append("\n-# *Oba hráči volí akci...*")

    embed = discord.Embed(
        title=f"⚔️  {f1.member.display_name}  vs  {f2.member.display_name}",
        description="\n".join(parts),
        color=0x1a1a2e,
    )
    footer = f"⭐ Aurionis  ·  Kolo {state.round + 1}"
    if state.bet: footer += f"  ·  Sázka: {state.bet} {COIN}"
    embed.set_footer(text=footer)
    return embed

def build_intro_embed(state: DuelState) -> discord.Embed:
    f1, f2 = state.f1, state.f2

    def block(f: Fighter) -> str:
        c = CLASSES[f.cls_name]
        return (
            f"{c['emoji']} **{f.member.display_name}** — *{f.cls_name}*\n"
            f"-# 🛡️ {c['passive']}\n"
            f"-# ✨ {c['basic_name']} (CD {c['basic_cd']} kola)  ·  💥 {c['ult_name']} ({c['ult_charge_max']} úderů)\n"
            f"-# _{c['lore']}_"
        )

    desc = f"{block(f1)}\n\n{block(f2)}\n\n📨 *Detaily třídy jsem odeslal do DM!*\n**Oba hráči volí první akci!**"
    embed = discord.Embed(title="⚔️  DUEL ZAČÍNÁ!", description=desc, color=0x1a1a2e)
    if state.bet:
        embed.set_footer(text=f"💰 Sázka: {state.bet} {COIN} každý  ·  výherce bere vše")
    return embed

def build_finish_embed(winner: Fighter, loser: Fighter, bet: int) -> discord.Embed:
    wcls = CLASSES[winner.cls_name]
    desc = (
        f"{wcls['emoji']} **{winner.member.display_name}** stojí jako vítěz!\n\n"
        f"*{loser.member.display_name} {random.choice(FINISHERS)}*\n"
    )
    if bet:
        desc += f"\n💰 **{winner.member.display_name}** získává **{bet * 2}** {COIN}!"
    embed = discord.Embed(title="☠️  KONEC DUELU", description=desc, color=wcls["color"])
    embed.set_footer(text="⭐ Aurionis")
    return embed

# ── DM helper ─────────────────────────────────────────────────────────────────

async def _dm_class_info(fighter: Fighter):
    cls  = CLASSES[fighter.cls_name]
    text = (
        f"## {cls['emoji']} Tvoje třída: **{fighter.cls_name}**\n"
        f"_{cls['lore']}_\n\n"
        f"**HP:** {cls['hp']}  ·  **Stamina:** {cls['stamina']}  ·  **Posture:** {cls['posture']}  ·  **Dmg:** {cls['dmg_mod']}×\n\n"
        f"**Pasivní schopnost:**\n> {cls['passive']}\n\n"
        f"**✨ {cls['basic_name']}** (cooldown {cls['basic_cd']} kola)\n"
        f"> {cls['basic_desc']}\n\n"
        f"**💥 {cls['ult_name']}** (nabij {cls['ult_charge_max']} úderů)\n"
        f"> {cls['ult_desc']}\n\n"
        f"**Posture** — buduje se pod těžkými údery a parry. Při 0: 💔 GUARD BREAK!\n"
        f"**Feint** — trestá štít, výpad i úskok. Čti soupeře!\n"
        f"**Heavy** je telegrafováno v aréně — soupeř to vidí."
    )
    try:
        await fighter.member.send(text)
    except Exception:
        pass

# ── Views ─────────────────────────────────────────────────────────────────────

class ActionView(discord.ui.View):
    """Ephemeral — hráč vybírá akci. Bez timeoutu."""

    def __init__(self, state: DuelState, fighter: Fighter):
        super().__init__(timeout=None)
        self.state   = state
        self.fighter = fighter
        cls          = CLASSES[fighter.cls_name]
        berserk      = fighter.berserk > 0

        # Row 0: attack, heavy, guard, feint, dodge
        row0 = [
            ("attack",  discord.ButtonStyle.red,     f"⚔️ Útok  (15 sta · ~{BASE_ATK} dmg)",       False),
            ("heavy",   discord.ButtonStyle.red,     f"🪓 Těžký útok  (25 sta · ~{BASE_HEAVY} dmg)", False),
            ("guard",   discord.ButtonStyle.green,   "🛡️ Štít  (10 sta)",                            berserk),
            ("feint",   discord.ButtonStyle.blurple, "🎭 Klam  (12 sta · čte obranu)",               False),
            ("dodge",   discord.ButtonStyle.blurple, "💨 Úskok  (15 sta)",                            False),
        ]
        # Row 1: recover, basic, ultimate
        row1_static = [
            ("recover", discord.ButtonStyle.grey, f"💚 Odpočinek  (+{cls['recover']} sta, +{cls['recover_hp']} HP)"),
        ]

        for action, style, label, disabled in row0:
            btn = discord.ui.Button(label=label, style=style, row=0, disabled=disabled)
            btn.callback = self._make_cb(action)
            self.add_item(btn)

        for action, style, label in row1_static:
            btn = discord.ui.Button(label=label, style=style, row=1)
            btn.callback = self._make_cb(action)
            self.add_item(btn)

        # Basic ability
        cd     = fighter.cooldowns.get("basic", 0)
        b_rdy  = cd == 0
        b_lbl  = f"✨ {cls['basic_name']}" + (f"  · {cd} kola" if not b_rdy else "")
        b_btn  = discord.ui.Button(label=b_lbl, style=discord.ButtonStyle.blurple, disabled=not b_rdy, row=1)
        b_btn.callback = self._make_cb("basic")
        self.add_item(b_btn)

        # Ultimate
        ult_ready  = fighter.ult_charge >= cls["ult_charge_max"]
        ult_status = "✅ READY" if ult_ready else f"{fighter.ult_charge}/{cls['ult_charge_max']}"
        u_lbl      = f"💥 {cls['ult_name']}  ({ult_status})"
        u_btn      = discord.ui.Button(
            label=u_lbl,
            style=discord.ButtonStyle.red if ult_ready else discord.ButtonStyle.grey,
            disabled=not ult_ready,
            row=1,
        )
        u_btn.callback = self._make_cb("ultimate")
        self.add_item(u_btn)

    def _make_cb(self, action: str):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.fighter.member.id:
                await interaction.response.send_message("Toto není tvůj souboj!", ephemeral=True)
                return
            if self.fighter.action is not None:
                await interaction.response.send_message("Už jsi vybral!", ephemeral=True)
                return
            if self.state.done:
                await interaction.response.send_message("Duel skončil.", ephemeral=True)
                return
            if self.fighter.exhausted and action not in ("recover", "guard", "basic", "ultimate"):
                await interaction.response.edit_message(
                    content=f"⚠️ **Vyčerpán!** Použij 💚 Odpočinek nebo 🛡️ Štít.\n-# STA: {self.fighter.stamina}/{self.fighter.max_sta}",
                    view=self,
                )
                return

            self.fighter.action = action
            self.stop()

            cls = CLASSES[self.fighter.cls_name]
            if action == "basic":
                label = cls["basic_name"]
            elif action == "ultimate":
                label = cls["ult_name"]
            else:
                cz = {"attack": "Útok", "heavy": "Těžký útok", "guard": "Štít",
                      "parry": "Výpad", "feint": "Klam", "dodge": "Úskok", "recover": "Odpočinek"}
                label = cz.get(action, action)

            await interaction.response.edit_message(
                content=f"✅ **{label}** — čekám na soupeře...",
                view=None,
            )
            await _try_resolve(self.state)
        return cb


class ArenaView(discord.ui.View):
    """Veřejná — tlačítka pro výběr akce (otevírá ephemeral ActionView)."""

    def __init__(self, state: DuelState):
        super().__init__(timeout=600)
        self.state = state

        b1 = discord.ui.Button(label=f"⚔️ {state.f1.member.display_name}", style=discord.ButtonStyle.red)
        b2 = discord.ui.Button(label=f"⚔️ {state.f2.member.display_name}", style=discord.ButtonStyle.blurple)
        b1.callback = self._make_choose(state.f1)
        b2.callback = self._make_choose(state.f2)
        self.add_item(b1)
        self.add_item(b2)

    def _make_choose(self, fighter: Fighter):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != fighter.member.id:
                await interaction.response.send_message("Toto není tvůj souboj!", ephemeral=True)
                return
            if self.state.done:
                await interaction.response.send_message("Duel skončil.", ephemeral=True)
                return
            if fighter.action is not None:
                await interaction.response.send_message("✅ Akce vybrána. Čekáš na soupeře...", ephemeral=True)
                return
            cls = CLASSES[fighter.cls_name]
            await interaction.response.send_message(
                f"**Kolo {self.state.round + 1}** — Vyber akci!\n"
                f"-# STA: {fighter.stamina}/{fighter.max_sta}  ·  POS: {fighter.posture}/{fighter.max_posture}  ·  ULT: {fighter.ult_charge}/{cls['ult_charge_max']}",
                view=ActionView(self.state, fighter),
                ephemeral=True,
            )
        return cb

    async def on_timeout(self):
        if not self.state.done:
            _cleanup(self.state)


class ChallengeView(discord.ui.View):
    """Výzva k duelu — přijmout / odmítnout."""

    def __init__(self, challenger: discord.Member, target: discord.Member,
                 bet: int, channel: discord.TextChannel):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.target     = target
        self.bet        = bet
        self.channel    = channel
        self.answered   = False

    @discord.ui.button(label="⚔️ Přijmout", style=discord.ButtonStyle.red)
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("Výzva není pro tebe!", ephemeral=True)
            return
        if self.answered:
            return
        self.answered = True
        self.stop()

        if self.bet > 0:
            eco   = load_json(ECONOMY_FILE, {})
            c_bal = eco.get(str(self.challenger.id), 0)
            t_bal = eco.get(str(self.target.id), 0)
            if c_bal < self.bet:
                await interaction.response.edit_message(
                    content=f"❌ **{self.challenger.display_name}** nemá dost zlatých!", view=None
                )
                return
            if t_bal < self.bet:
                await interaction.response.edit_message(
                    content=f"❌ **{self.target.display_name}** nemá dost zlatých!", view=None
                )
                return
            eco[str(self.challenger.id)] = c_bal - self.bet
            eco[str(self.target.id)]     = t_bal - self.bet
            save_json(ECONOMY_FILE, eco)

        cls1, cls2 = random.sample(CLASS_NAMES, 2)
        f1    = Fighter(self.challenger, cls1)
        f2    = Fighter(self.target,     cls2)
        state = DuelState(f1, f2, self.bet, self.channel)
        _register(state)

        await interaction.response.edit_message(embed=build_intro_embed(state), view=None)
        state.arena_msg = await self.channel.send(embed=build_status_embed(state), view=ArenaView(state))

        await asyncio.gather(_dm_class_info(f1), _dm_class_info(f2), return_exceptions=True)

    @discord.ui.button(label="🚫 Odmítnout", style=discord.ButtonStyle.grey)
    async def decline(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("Výzva není pro tebe!", ephemeral=True)
            return
        if self.answered:
            return
        self.answered = True
        self.stop()
        await interaction.response.edit_message(
            content=f"🚫 **{self.target.display_name}** odmítl duel.", view=None
        )

    async def on_timeout(self):
        if not self.answered:
            self.answered = True
            try:
                await self.message.edit(
                    content=f"⏱️ Výzva vypršela — **{self.target.display_name}** neodpověděl.", view=None
                )
            except Exception:
                pass

# ── Resolution loop ───────────────────────────────────────────────────────────

async def _try_resolve(state: DuelState):
    if state.done or not state.both_chose():
        return
    async with state._lock:
        if state.done or not state.both_chose():
            return

        state.round += 1
        log = resolve_round(state)

        f1_dead = state.f1.hp <= 0
        f2_dead = state.f2.hp <= 0

        if state.arena_msg:
            try:
                await state.arena_msg.edit(view=None)
            except Exception:
                pass

        if f1_dead or f2_dead:
            winner = state.f2 if f1_dead else state.f1
            loser  = state.f1 if f1_dead else state.f2
            _cleanup(state)

            if state.bet > 0:
                eco = load_json(ECONOMY_FILE, {})
                wid = str(winner.member.id)
                eco[wid] = eco.get(wid, 0) + state.bet * 2
                save_json(ECONOMY_FILE, eco)

            await state.channel.send(embed=build_round_embed(state, log))
            await state.channel.send(embed=build_finish_embed(winner, loser, state.bet))
        else:
            await state.channel.send(embed=build_round_embed(state, log))
            state.arena_msg = await state.channel.send(
                embed=build_status_embed(state), view=ArenaView(state)
            )

# ── Cog ───────────────────────────────────────────────────────────────────────

class DuelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="duel", description="Vyzvi hráče na souboj s sázkou!")
    @app_commands.describe(member="Soupeř", bet="Sázka v zlatých (0 = bez sázky)")
    async def duel(self, interaction: discord.Interaction,
                   member: discord.Member, bet: int = 0):
        challenger = interaction.user
        if member.id == challenger.id:
            await interaction.response.send_message("Nemůžeš vyzvat sám sebe.", ephemeral=True); return
        if member.bot:
            await interaction.response.send_message("Nemůžeš vyzvat bota.", ephemeral=True); return
        if challenger.id in _active:
            await interaction.response.send_message("Už jsi v aktivním duelu!", ephemeral=True); return
        if member.id in _active:
            await interaction.response.send_message(f"**{member.display_name}** je už v duelu.", ephemeral=True); return
        if bet < 0:
            await interaction.response.send_message("Sázka nesmí být záporná.", ephemeral=True); return
        if bet > 0:
            eco = load_json(ECONOMY_FILE, {})
            if eco.get(str(challenger.id), 0) < bet:
                await interaction.response.send_message(
                    f"Nemáš dost zlatých! (máš {eco.get(str(challenger.id), 0)} {COIN})", ephemeral=True
                ); return

        view    = ChallengeView(challenger, member, bet, interaction.channel)
        bet_txt = f" o **{bet}** {COIN}" if bet else ""
        embed   = discord.Embed(
            title="⚔️  Výzva k duelu!",
            description=(
                f"{challenger.mention} vyzývá {member.mention} na souboj{bet_txt}!\n\n"
                f"-# Obdržíš náhodnou bojovou třídu. Souboj je tahový — mindgames rozhodují.\n"
                f"-# Sázka je stržena při přijetí."
            ),
            color=0xE74C3C,
        )
        embed.set_footer(text="⭐ Aurionis  ·  Výzva vyprší za 60 sekund")
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(DuelCog(bot))
