"""Sdílený parser kostek a damage zbraní.

`/roll`, `/attack` i testy používají stejná pravidla, ať se hody nerozjedou.
"""

import random
import re

MAX_DICE = 100
MAX_SIDES = 1000

_TOKEN_RE = re.compile(r"([+-]?(?:\d+d\d+|\d+))")


class DiceError(ValueError):
    """Neplatný zápis hodu."""


class RollResult:
    def __init__(self, total: int, parts: list[str], nat20: bool, nat1: bool,
                 is_d20: bool, dice_max: int):
        self.total = total
        self.parts = parts
        self.detail = " ".join(parts)
        self.nat20 = nat20
        self.nat1 = nat1
        self.is_d20 = is_d20
        self.dice_max = dice_max


def roll_expr(expr: str, rng: random.Random | None = None) -> RollResult:
    """Hodí výraz typu `1d8+2d6-1`. Vyhodí DiceError při nesmyslu."""
    rnd = rng or random
    raw = (expr or "").lower().replace(" ", "")
    if not raw:
        raise DiceError("prázdný zápis")

    tokens = _TOKEN_RE.findall(raw)
    if not tokens or "".join(tokens).lstrip("+") != raw.lstrip("+"):
        raise DiceError(f"nerozumím zápisu: {expr}")

    total = 0
    parts: list[str] = []
    nat20 = nat1 = is_d20 = False
    dice_max = 0

    for token in tokens:
        sign = -1 if token.startswith("-") else 1
        clean = token.lstrip("+-")
        if "d" in clean:
            num, sides = (int(x) for x in clean.split("d"))
            if num > MAX_DICE or sides > MAX_SIDES or num <= 0 or sides <= 0:
                raise DiceError("příliš mnoho moci")
            if sign == 1:
                dice_max = max(dice_max, sides)
            rolls = [rnd.randint(1, sides) for _ in range(num)]
            if sides == 20 and num == 1:
                is_d20 = True
                nat20 = nat20 or rolls[0] == 20
                nat1 = nat1 or rolls[0] == 1
            total += sum(rolls) * sign
            parts.append(f"{'+' if sign == 1 else '-'}{num}d{sides}"
                         f"({', '.join(map(str, rolls))})")
        else:
            val = int(clean)
            total += val * sign
            parts.append(f"{'+' if sign == 1 else '-'}{val}")

    return RollResult(total, parts, nat20, nat1, is_d20, dice_max)


# ── Damage zbraní ─────────────────────────────────────────────────────────────

_DMG_LINE_RE = re.compile(r"^\s*dmg\s*:\s*(.+)$", re.IGNORECASE)
_DMG_EXPR_RE = re.compile(r"\d+d\d+(?:\s*[+-]\s*\d+(?:d\d+)?)*")


def item_damage_expr(db_item: dict) -> str | None:
    """Damage výraz itemu.

    Priorita: pole `dmg` → první `1dX` výraz na řádku `DMG:` v popisu →
    `atk` jako plochý bonus. None když zbraň damage nemá.
    """
    if not isinstance(db_item, dict):
        return None

    explicit = str(db_item.get("dmg") or "").strip()
    if explicit:
        return explicit

    for line in str(db_item.get("desc") or "").split("\n"):
        m = _DMG_LINE_RE.match(line)
        if not m:
            continue
        expr = _DMG_EXPR_RE.search(m.group(1).replace(" ", ""))
        if expr:
            return expr.group(0)

    atk = db_item.get("atk") or 0
    try:
        atk = int(atk)
    except (TypeError, ValueError):
        atk = 0
    return str(atk) if atk else None
