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
        "emoji": "🥷", "hp": 85, "stamina": 120, "recover": 40,
        "dmg_mod": 1.00, "color": 0xE67E22,
        "passive": "Meditativní tok — Odpočinek obnovuje 40 staminy",
        "lore": "Disciplinovaný bojovník těla i ducha. Nikdy neutíká od boje.",
        "basic_name": "Meditace",        "basic_desc": "Obnov 25 HP",      "basic_mana": 40,
        "ult_name":   "Duch bouře",      "ult_desc":   "~65 dmg",           "ult_charge_max": 5,
    },
    "Knight": {
        "emoji": "🛡️", "hp": 120, "stamina": 80, "recover": 25,
        "dmg_mod": 1.15, "color": 0x95A5A6,
        "passive": "Železná pevnost — štít absorbuje o 20 % více",
        "lore": "Obrněný válečník. Pomalý. Neúprosný.",
        "basic_name": "Požehnání",       "basic_desc": "Obnov 35 staminy",  "basic_mana": 35,
        "ult_name":   "Úder spravedlnosti", "ult_desc": "~75 dmg, ignoruje štít", "ult_charge_max": 5,
    },
    "Rogue": {
        "emoji": "🗡️", "hp": 75, "stamina": 105, "recover": 35,
        "dmg_mod": 0.95, "color": 0x2C3E50,
        "passive": "Stínový krok — úskok vyhýbá i lehkým útokům",
        "lore": "Rychlý a zákeřný. Kdo ho uvidí, je mrtvý.",
        "basic_name": "Jedová čepel",    "basic_desc": "Příště +15 jed",    "basic_mana": 35,
        "ult_name":   "Zákeřný úder",   "ult_desc":   "~85 dmg, nelze blokovat", "ult_charge_max": 4,
    },
    "Berserker": {
        "emoji": "🪓", "hp": 100, "stamina": 90, "recover": 30,
        "dmg_mod": 1.35, "color": 0xE74C3C,
        "passive": "Krvavý hněv — pod 30 HP: poškození +50 %",
        "lore": "Šílený válečník. Čím méně HP, tím nebezpečnější.",
        "basic_name": "Bojový řev",      "basic_desc": "Příští útok +50 %", "basic_mana": 30,
        "ult_name":   "Zběsilost",       "ult_desc":   "Dva údery za kolo", "ult_charge_max": 4,
    },
    "Guardian": {
        "emoji": "⚜️", "hp": 110, "stamina": 85, "recover": 30,
        "dmg_mod": 1.00, "color": 0x27AE60,
        "passive": "Trny — štít vrací 10 dmg útočníkovi",
        "lore": "Neproniknutelný. Protiúder je smrtící.",
        "basic_name": "Provokace",       "basic_desc": "Příští zásah -50 %","basic_mana": 35,
        "ult_name":   "Odvetný úder",    "ult_desc":   "Odraz útoku zpět",  "ult_charge_max": 5,
    },
    "Duelist": {
        "emoji": "🤺", "hp": 80, "stamina": 100, "recover": 35,
        "dmg_mod": 1.05, "color": 0x9B59B6,
        "passive": "Dokonalé parírování — výpad counter +50 % dmg",
        "lore": "Elegantní. Každá akce je kalkulovaná.",
        "basic_name": "Přesný výpad",    "basic_desc": "~35 dmg, nelze blokovat", "basic_mana": 40,
        "ult_name":   "Dokonalý souboj", "ult_desc":   "Counter 200 % dmg", "ult_charge_max": 4,
    },
}

CLASS_NAMES = list(CLASSES.keys())

# ── Akce ─────────────────────────────────────────────────────────────────────

STAM_COSTS = {
    "attack": 15, "heavy": 25, "guard": 10,
    "parry": 20,  "feint": 12, "dodge": 15, "recover": 0,
    "basic": 0,   "ultimate": 0,
}

BASE_ATK   = 20
BASE_HEAVY = 35
PARRY_CTR  = 15

# ── Fighter & DuelState ───────────────────────────────────────────────────────

class Fighter:
    def __init__(self, member: discord.Member, cls_name: str):
        self.member     = member
        self.cls_name   = cls_name
        cls             = CLASSES[cls_name]
        self.hp         = cls["hp"]
        self.max_hp     = cls["hp"]
        self.stamina    = cls["stamina"]
        self.max_sta    = cls["stamina"]
        self.mana       = 0
        self.max_mana   = 100
        self.ult_charge = 0
        # Round buffs
        self.buff_atk_boost: bool = False  # Berserker basic
        self.buff_poison:    int  = 0      # Rogue basic (next round)
        self.buff_absorb:    bool = False  # Guardian basic
        self.buff_reflect:   bool = False  # Guardian ult
        self.action: str | None = None

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def exhausted(self) -> bool:
        return self.stamina < 5


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

def _fighter_bar(f: Fighter) -> str:
    cls   = CLASSES[f.cls_name]
    hi    = _hp_icon(max(0, f.hp), f.max_hp)
    max_c = cls["ult_charge_max"]
    ub    = _ult_bar(f.ult_charge, max_c)
    ready = " ✨ READY!" if f.ult_charge >= max_c else f" {f.ult_charge}/{max_c}"
    return (
        f"{cls['emoji']} **{f.member.display_name}** — {f.cls_name}\n"
        f"`HP  [{_bar(f.hp, f.max_hp)}]` {hi} {max(0, f.hp)}/{f.max_hp}\n"
        f"`STA [{_bar(f.stamina, f.max_sta)}]` ⚡ {max(0, f.stamina)}/{f.max_sta}\n"
        f"`MAN [{_bar(f.mana, f.max_mana)}]` 🔵 {f.mana}/{f.max_mana}\n"
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
    boost_mod = 1.5 if f.buff_atk_boost else 1.0
    f.buff_atk_boost = False
    return max(1, round(base * class_mod * stam_mod * rage_mod * boost_mod))

def _atk(f: Fighter) -> int: return _eff(f, _rdm(BASE_ATK))
def _hvy(f: Fighter) -> int: return _eff(f, _rdm(BASE_HEAVY, 5))

def _ctr(f: Fighter) -> int:
    mult = 1.5 if f.cls_name == "Duelist" else 1.0
    return max(1, round(PARRY_CTR * mult * CLASSES[f.cls_name]["dmg_mod"]))

def _guard_absorb(f: Fighter, raw: int) -> int:
    base = 0.55 if f.cls_name == "Knight" else 0.35
    if f.buff_absorb:
        base = min(0.85, base + 0.5)
        f.buff_absorb = False
    return round(raw * (1 - base))

# ── Ability handlers ──────────────────────────────────────────────────────────

def _apply_basic(f: Fighter, log: list[str]) -> int:
    """Returns damage to deal to opponent."""
    cls = CLASSES[f.cls_name]
    f.mana -= cls["basic_mana"]
    n = f.member.display_name
    if f.cls_name == "Monk":
        heal = 25
        f.hp = min(f.max_hp, f.hp + heal)
        log.append(f"✨ **{n}** medituje — obnova **{heal} HP**!")
    elif f.cls_name == "Knight":
        sta = 35
        f.stamina = min(f.max_sta, f.stamina + sta)
        log.append(f"✨ **{n}** se požehná — obnova **{sta} staminy**!")
    elif f.cls_name == "Rogue":
        f.buff_poison = 15
        log.append(f"☠️ **{n}** natírá čepel jedem... příště **+15** jed!")
    elif f.cls_name == "Berserker":
        f.buff_atk_boost = True
        log.append(f"😤 **{n}** řve bojový pokřik — příští útok **+50 % dmg**!")
    elif f.cls_name == "Guardian":
        f.buff_absorb = True
        log.append(f"🛡️ **{n}** zaujímá pevný postoj — příší zásah **-50 % dmg**!")
    elif f.cls_name == "Duelist":
        dmg = 35 + random.randint(-3, 3)
        log.append(f"🤺 **{n}** přesný výpad — **{dmg}** dmg, nelze blokovat!")
        return dmg
    return 0

def _apply_ultimate(f: Fighter, log: list[str]) -> int:
    """Returns damage to deal to opponent. Sets buff_reflect for Guardian."""
    f.ult_charge = 0
    n = f.member.display_name
    if f.cls_name == "Monk":
        dmg = 65 + random.randint(-5, 5)
        log.append(f"💥 **{n}** — DUCH BOUŘE! Silný úder za **{dmg}** dmg!")
        return dmg
    elif f.cls_name == "Knight":
        dmg = 75 + random.randint(-5, 5)
        log.append(f"💥 **{n}** — ÚDER SPRAVEDLNOSTI! Žádná obrana! **{dmg}** dmg!")
        return dmg
    elif f.cls_name == "Rogue":
        dmg = 85 + random.randint(-5, 5)
        log.append(f"💥 **{n}** — ZÁKEŘNÝ ÚDER! Z ničeho nic — **{dmg}** dmg!")
        return dmg
    elif f.cls_name == "Berserker":
        d1 = _atk(f); d2 = _atk(f)
        dmg = d1 + d2
        log.append(f"💥 **{n}** — ZBĚSILOST! Dva údery: **{d1}** + **{d2}** = **{dmg}** dmg!")
        return dmg
    elif f.cls_name == "Guardian":
        f.buff_reflect = True
        log.append(f"💥 **{n}** — ODVETNÝ ÚDER! Připraven odrazit vše zpět! ⚜️")
        return 0
    elif f.cls_name == "Duelist":
        dmg = round(PARRY_CTR * 2 * CLASSES["Duelist"]["dmg_mod"])
        log.append(f"💥 **{n}** — DOKONALÝ SOUBOJ! Bleskový counter za **{dmg}** dmg!")
        return dmg
    return 0

# ── Round resolution ──────────────────────────────────────────────────────────

def resolve_round(state: DuelState) -> list[str]:
    f1, f2 = state.f1, state.f2
    a1, a2 = f1.action, f2.action
    n1, n2 = f1.member.display_name, f2.member.display_name

    log: list[str] = []
    d1 = 0  # damage to f1
    d2 = 0  # damage to f2

    # Mana regen
    f1.mana = min(f1.max_mana, f1.mana + 15)
    f2.mana = min(f2.max_mana, f2.mana + 15)

    # Stamina costs
    f1.stamina = max(0, f1.stamina - STAM_COSTS.get(a1, 0))
    f2.stamina = max(0, f2.stamina - STAM_COSTS.get(a2, 0))

    # Recover bonus
    if a1 == "recover": f1.stamina = min(f1.max_sta, f1.stamina + CLASSES[f1.cls_name]["recover"])
    if a2 == "recover": f2.stamina = min(f2.max_sta, f2.stamina + CLASSES[f2.cls_name]["recover"])

    # Poison tick
    if f1.buff_poison > 0:
        d1 += f1.buff_poison
        log.append(f"☠️ **{n1}** trpí jedem — **{f1.buff_poison}** damage!")
        f1.buff_poison = 0
    if f2.buff_poison > 0:
        d2 += f2.buff_poison
        log.append(f"☠️ **{n2}** trpí jedem — **{f2.buff_poison}** damage!")
        f2.buff_poison = 0

    # Nested helpers
    def guard_hit(atk: Fighter, grd: Fighter, raw: int) -> tuple[int, int]:
        dmg    = _guard_absorb(grd, raw)
        thorns = 10 if grd.cls_name == "Guardian" else 0
        log.append(f"🛡️ **{grd.member.display_name}** blokuje — přijímá pouze **{dmg}** damage!")
        if thorns: log.append(f"✀ Trny vrací **{thorns}** damage útočníkovi!")
        return dmg, thorns

    def parry_hit(pry: Fighter, bonus: float = 1.0) -> int:
        ctr = round(_ctr(pry) * bonus)
        log.append(f"⚡ **{pry.member.display_name}** PARUJE — counter strike za **{ctr}**!")
        return ctr

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
            log.append(f"🔄 **{n2}** ODRÁŽÍ útok zpět — **{raw}** dmg pro **{n1}**!")
        else:
            d2 += raw

    if a2 == "ultimate":
        raw = _apply_ultimate(f2, log)
        if f1.buff_reflect and raw > 0:
            d2 += raw; f1.buff_reflect = False
            log.append(f"🔄 **{n1}** ODRÁŽÍ útok zpět — **{raw}** dmg pro **{n2}**!")
        else:
            d1 += raw

    # ── Normal matrix ─────────────────────────────────────────────────────────

    if ab1 and not ab2:
        # f1 used ability (open to attack), f2 acts normally
        if a2 in ("attack", "heavy"):
            raw = _hvy(f2) if a2 == "heavy" else _atk(f2)
            d1 += raw
            log.append(f"{'🪓' if a2 == 'heavy' else '⚔️'} **{n2}** trestá otevřenou pozici — **{raw}** damage!")
        elif a2 == "feint":
            raw = _atk(f2); d1 += raw
            log.append(f"🎭 **{n2}** pronáší klam — **{raw}** damage!")

    elif not ab1 and ab2:
        # f2 used ability (open), f1 acts normally
        if a1 in ("attack", "heavy"):
            raw = _hvy(f1) if a1 == "heavy" else _atk(f1)
            d2 += raw
            log.append(f"{'🪓' if a1 == 'heavy' else '⚔️'} **{n1}** trestá otevřenou pozici — **{raw}** damage!")
        elif a1 == "feint":
            raw = _atk(f1); d2 += raw
            log.append(f"🎭 **{n1}** pronáší klam — **{raw}** damage!")

    elif not ab1 and not ab2:
        # Both normal actions
        if a1 == "recover" and a2 == "recover":
            log.append("💚 Oba si oddechnou. **Napětí stoupá.**")

        elif a1 == "recover":
            log.append(f"💚 **{n1}** nabírá dech...")
            if a2 in ("attack", "heavy", "feint"):
                raw = round((_hvy(f2) if a2 == "heavy" else _atk(f2)) * 1.3)
                d1 += raw
                log.append(f"💀 **{n2}** trestá recovery — **{raw}** damage!")
            else:
                log.append(f"*{n2} nezaútočil.*")

        elif a2 == "recover":
            log.append(f"💚 **{n2}** nabírá dech...")
            if a1 in ("attack", "heavy", "feint"):
                raw = round((_hvy(f1) if a1 == "heavy" else _atk(f1)) * 1.3)
                d2 += raw
                log.append(f"💀 **{n1}** trestá recovery — **{raw}** damage!")
            else:
                log.append(f"*{n1} nezaútočil.*")

        elif a1 == "guard" and a2 == "guard":
            log.append("🛡️ Oba zvedají štíty — **pat**.")

        elif a1 == "guard":
            if a2 == "attack":
                dmg, t = guard_hit(f2, f1, _atk(f2)); d1 += dmg; d2 += t
            elif a2 == "heavy":
                dmg, t = guard_hit(f2, f1, round(_hvy(f2) * 1.3)); d1 += dmg; d2 += t
                log.append("*Heavy útok proniká obranou!*")
            elif a2 == "feint":
                dmg = round(_atk(f2) * 0.85); d1 += dmg
                log.append(f"🎭 **{n2}** FEINTUJE kolem guárdu — **{dmg}** damage!")
            else:
                log.append("Žádný z bojovníků nezaútočil.")

        elif a2 == "guard":
            if a1 == "attack":
                dmg, t = guard_hit(f1, f2, _atk(f1)); d2 += dmg; d1 += t
            elif a1 == "heavy":
                dmg, t = guard_hit(f1, f2, round(_hvy(f1) * 1.3)); d2 += dmg; d1 += t
                log.append("*Heavy útok proniká obranou!*")
            elif a1 == "feint":
                dmg = round(_atk(f1) * 0.85); d2 += dmg
                log.append(f"🎭 **{n1}** FEINTUJE kolem guárdu — **{dmg}** damage!")
            else:
                log.append("Žádný z bojovníků nezaútočil.")

        elif a1 == "parry" and a2 == "parry":
            log.append("⚡ Oba jdou na výpad — **čepele se zamknou!** Pat.")

        elif a1 == "parry":
            if a2 in ("attack", "heavy"):
                d2 += parry_hit(f1, 1.5 if a2 == "heavy" else 1.0)
                log.append(f"*Útok {n2} je odražen!*")
            elif a2 == "feint":
                dmg = _atk(f2); d1 += dmg
                log.append(f"🎭 **{n2}** FEINTUJE — **{n1}** paruje vzduch! **{dmg}** damage!")
            elif a2 == "dodge":
                log.append("Oba čtou stejný moment — žádný kontakt.")
            else:
                log.append(f"**{n1}** čeká na útok... ale {n2} nezaútočil.")

        elif a2 == "parry":
            if a1 in ("attack", "heavy"):
                d1 += parry_hit(f2, 1.5 if a1 == "heavy" else 1.0)
                log.append(f"*Útok {n1} je odražen!*")
            elif a1 == "feint":
                dmg = _atk(f1); d2 += dmg
                log.append(f"🎭 **{n1}** FEINTUJE — **{n2}** paruje vzduch! **{dmg}** damage!")
            elif a1 == "dodge":
                log.append("Oba čtou stejný moment — žádný kontakt.")
            else:
                log.append(f"**{n2}** čeká na útok... ale {n1} nezaútočil.")

        elif a1 == "dodge" and a2 == "dodge":
            log.append("💨 Oba uhýbají — kroužení. Žádný kontakt.")

        elif a1 == "dodge":
            if a2 == "heavy":
                log.append(f"💨 **{n1}** vykročí stranou — heavy mine!")
            elif a2 == "attack":
                if f1.cls_name == "Rogue":
                    log.append(f"💨 **{n1}** *(Stínový krok)* — plný dodge i na útok!")
                else:
                    dmg = round(_atk(f2) * 0.45); d1 += dmg
                    log.append(f"💨 **{n1}** částečně uhýbá — **{dmg}** damage!")
            elif a2 == "feint":
                if f1.cls_name == "Rogue":
                    log.append(f"💨 **{n1}** čte feint — mizí!")
                else:
                    dmg = round(_atk(f2) * 0.45); d1 += dmg
                    log.append(f"🎭 **{n2}** feintuje, **{n1}** nestačí — **{dmg}** damage!")
            else:
                log.append(f"**{n1}** uhýbá — ale {n2} nezaútočil.")

        elif a2 == "dodge":
            if a1 == "heavy":
                log.append(f"💨 **{n2}** vykročí stranou — heavy mine!")
            elif a1 == "attack":
                if f2.cls_name == "Rogue":
                    log.append(f"💨 **{n2}** *(Stínový krok)* — plný dodge i na útok!")
                else:
                    dmg = round(_atk(f1) * 0.45); d2 += dmg
                    log.append(f"💨 **{n2}** částečně uhýbá — **{dmg}** damage!")
            elif a1 == "feint":
                if f2.cls_name == "Rogue":
                    log.append(f"💨 **{n2}** čte feint — mizí!")
                else:
                    dmg = round(_atk(f1) * 0.45); d2 += dmg
                    log.append(f"🎭 **{n1}** feintuje, **{n2}** nestačí — **{dmg}** damage!")
            else:
                log.append(f"**{n2}** uhýbá — ale {n1} nezaútočil.")

        elif a1 == "feint" and a2 == "feint":
            t1 = _atk(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append(f"🎭 Oba feintují — oba zaútočí! **{t2}** / **{t1}** damage.")

        elif a1 == "attack" and a2 == "attack":
            t1 = _atk(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append(f"⚔️ **{n1}** vs **{n2}** — čepele se kříží!")
            log.append(f"*Oba si vymění údery. **{t2}** / **{t1}** damage.*")

        elif a1 == "attack" and a2 == "feint":
            t1 = _atk(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append(f"⚔️ **{n1}** zaútočí — **{n2}** zároveň feintuje. Oba zasáhnou!")

        elif a1 == "feint" and a2 == "attack":
            t1 = _atk(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append(f"🎭 **{n1}** feintuje — **{n2}** zároveň zaútočí. Oba zasáhnou!")

        elif a1 == "heavy" and a2 == "heavy":
            t1 = _hvy(f2); t2 = _hvy(f1)
            d1 += t1; d2 += t2
            log.append("💥 **MASIVNÍ KOLIZE** — oba heavy útočí!")
            log.append(f"*Aréna se třese. **{t2}** / **{t1}** damage.*")

        elif a1 == "heavy" and a2 == "attack":
            t1 = _atk(f2); t2 = _hvy(f1)
            d1 += t1; d2 += t2
            log.append(f"⚔️ **{n2}** zaútočí rychle — **{n1}**'s heavy také dopadá!")

        elif a1 == "attack" and a2 == "heavy":
            t1 = _hvy(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append(f"⚔️ **{n1}** zaútočí rychle — **{n2}**'s heavy také dopadá!")

        elif a1 == "heavy" and a2 == "feint":
            t1 = _atk(f2); t2 = _hvy(f1)
            d1 += t1; d2 += t2
            log.append(f"🪓 **{n1}**'s heavy je příliš odhodlaný — **{n2}** zasáhne feintnem!")

        elif a1 == "feint" and a2 == "heavy":
            t1 = _hvy(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append(f"🪓 **{n2}**'s heavy je příliš odhodlaný — **{n1}** zasáhne feintnem!")

        else:
            log.append("Boj pokračuje...")

    # ── Apply damage ──────────────────────────────────────────────────────────

    f1.hp -= d1
    f2.hp -= d2

    if not log:
        log.append("*Žádný kontakt.*")

    # ── Ult charge: increment when landing a damaging attack ──────────────────
    atk_acts = ("attack", "heavy", "feint")
    if a1 in atk_acts and d2 > 0:
        f1.ult_charge = min(CLASSES[f1.cls_name]["ult_charge_max"], f1.ult_charge + 1)
    if a2 in atk_acts and d1 > 0:
        f2.ult_charge = min(CLASSES[f2.cls_name]["ult_charge_max"], f2.ult_charge + 1)
    if a1 == "basic" and f1.cls_name == "Duelist" and d2 > 0:
        f1.ult_charge = min(CLASSES["Duelist"]["ult_charge_max"], f1.ult_charge + 1)
    if a2 == "basic" and f2.cls_name == "Duelist" and d1 > 0:
        f2.ult_charge = min(CLASSES["Duelist"]["ult_charge_max"], f2.ult_charge + 1)

    f1.action = None
    f2.action = None
    return log

# ── Embed builders ────────────────────────────────────────────────────────────

CROWD_LINES = [
    "Dav jásá!", "Aréna zní výkřiky!", "Krev na písku.",
    "Nikdo neopouští svá místa.", "Napětí je hmatatelné.",
]

FINISHERS = [
    "padá na kolena — aréna ztichne.",
    "se zhroutí pod posledním úderem.",
    "zakolísá — a padá.",
    "je poražen. Aréna exploduje!",
    "nemůže vstát. Je po všem.",
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
    for f in [f1, f2]:
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
    f1, f2 = state.f1, state.f2
    parts  = [_fighter_bar(f1), "", _fighter_bar(f2), "", "-# *Oba hráči volí akci...*"]
    embed  = discord.Embed(
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
            f"-# ✨ {c['basic_name']} ({c['basic_mana']} mana)  ·  💥 {c['ult_name']} ({c['ult_charge_max']} úderů)\n"
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
    cls = CLASSES[fighter.cls_name]
    text = (
        f"## {cls['emoji']} Tvoje třída: **{fighter.cls_name}**\n"
        f"_{cls['lore']}_\n\n"
        f"**HP:** {cls['hp']}  ·  **Stamina:** {cls['stamina']}  ·  **Dmg:** {cls['dmg_mod']}×\n\n"
        f"**Pasivní schopnost:**\n> {cls['passive']}\n\n"
        f"**✨ {cls['basic_name']}** ({cls['basic_mana']} many)\n"
        f"> {cls['basic_desc']}\n\n"
        f"**💥 {cls['ult_name']}** (nabij {cls['ult_charge_max']} úderů)\n"
        f"> {cls['ult_desc']}\n\n"
        f"-# Mana se dobíjí +15 za kolo. Ultimate se nabíjí každým zasaženým útokem."
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

        # Row 0: attack, heavy, guard, parry, feint
        row0 = [
            ("attack", discord.ButtonStyle.red,     f"⚔️ Útok  (15 sta · ~{BASE_ATK} dmg)"),
            ("heavy",  discord.ButtonStyle.red,     f"🪓 Těžký útok  (25 sta · ~{BASE_HEAVY} dmg)"),
            ("guard",  discord.ButtonStyle.green,   "🛡️ Štít  (10 sta)"),
            ("parry",  discord.ButtonStyle.green,   "⚡ Výpad  (20 sta · counter)"),
            ("feint",  discord.ButtonStyle.blurple, "🎭 Klam  (12 sta · obejde štít)"),
        ]
        # Row 1: dodge, recover, basic, ultimate
        row1_static = [
            ("dodge",   discord.ButtonStyle.blurple, "💨 Úskok  (15 sta)"),
            ("recover", discord.ButtonStyle.grey,    f"💚 Odpočinek  (+{cls['recover']} sta)"),
        ]

        for action, style, label in row0:
            btn          = discord.ui.Button(label=label, style=style, row=0)
            btn.callback = self._make_cb(action)
            self.add_item(btn)

        for action, style, label in row1_static:
            btn          = discord.ui.Button(label=label, style=style, row=1)
            btn.callback = self._make_cb(action)
            self.add_item(btn)

        # Basic ability
        has_mana = fighter.mana >= cls["basic_mana"]
        b_btn = discord.ui.Button(
            label=f"✨ {cls['basic_name']}  ({cls['basic_mana']} mana · {cls['basic_desc']})",
            style=discord.ButtonStyle.blurple,
            disabled=not has_mana,
            row=1,
        )
        b_btn.callback = self._make_cb("basic")
        self.add_item(b_btn)

        # Ultimate
        ult_ready = fighter.ult_charge >= cls["ult_charge_max"]
        u_lbl = f"💥 {cls['ult_name']}  ({'✅ READY' if ult_ready else f\"{fighter.ult_charge}/{cls['ult_charge_max']}\"})"
        u_btn = discord.ui.Button(
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
                cls = CLASSES[self.fighter.cls_name]
                await interaction.response.edit_message(
                    content=f"⚠️ **Jsi vyčerpaný!** Musíš použít 💚 Odpočinek nebo 🛡️ Štít.\n-# Stamina: {self.fighter.stamina}/{self.fighter.max_sta}",
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
                content=f"✅ Vybral jsi **{label}**. Čekám na soupeře...",
                view=None,
            )
            await _try_resolve(self.state)
        return cb


class ArenaView(discord.ui.View):
    """Veřejná — tlačítka pro výběr akce (ephemeral ActionView)."""

    def __init__(self, state: DuelState):
        super().__init__(timeout=600)  # 10 min safety cleanup
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
                await interaction.response.send_message("✅ Tvá akce je vybrána. Čekáš na soupeře...", ephemeral=True)
                return
            cls = CLASSES[fighter.cls_name]
            await interaction.response.send_message(
                f"**Kolo {self.state.round + 1}** — Vyber akci!\n"
                f"-# STA: {fighter.stamina}/{fighter.max_sta}  ·  MAN: {fighter.mana}/{fighter.max_mana}  ·  ULT: {fighter.ult_charge}/{cls['ult_charge_max']}",
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
        arena_view      = ArenaView(state)
        state.arena_msg = await self.channel.send(embed=build_status_embed(state), view=arena_view)

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

        # Disable old ArenaView
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
            arena_view      = ArenaView(state)
            state.arena_msg = await state.channel.send(embed=build_status_embed(state), view=arena_view)

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
