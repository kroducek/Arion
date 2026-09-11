"""
char_target.py — sdílený parametr `postava` pro admin příkazy.

Admin tak může cílit na konkrétní postavu hráče (např. `/gadd @snajpy 200 Erith`),
aniž by hráč musel dělat `/character switch`. Bez parametru se použije jeho
aktivní postava — chování zůstává stejné jako dřív.

Použití v cogu:

    from src.database.characters import use_slot
    from src.utils.char_target import POSTAVA_DESC, postava_autocomplete, resolve_postava

    @app_commands.describe(postava=POSTAVA_DESC)
    @app_commands.autocomplete(postava=postava_autocomplete)
    async def cmd(self, interaction, member, ..., postava: str | None = None):
        slot, err = resolve_postava(member.id, postava)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        with use_slot(member.id, slot):
            ...
"""
from discord import app_commands

from src.database.characters import get_active_slot, list_chars, resolve_slot

POSTAVA_DESC = "Postava hráče — jméno nebo číslo slotu (výchozí: jeho aktivní)"


async def postava_autocomplete(interaction, current: str) -> list[app_commands.Choice[str]]:
    """Nabídne postavy hráče zvoleného v parametru `member`."""
    member = getattr(interaction.namespace, "member", None)
    uid = getattr(member, "id", None)
    if uid is None:
        return []
    chars = list_chars(uid)
    active = get_active_slot(uid)
    cur = (current or "").lower().strip()
    out = []
    for slot in sorted(chars):
        name = chars[slot].get("name", f"Postava {slot}")
        if cur and cur not in slot.lower() and cur not in name.lower():
            continue
        label = f"{slot} · {name}" + ("  ⭐ aktivní" if slot == active else "")
        out.append(app_commands.Choice(name=label[:100], value=slot))
    return out[:25]


def resolve_postava(uid, postava: str | None) -> tuple[str | None, str | None]:
    """→ (slot, chybová hláška). Bez zadání vrací aktivní slot hráče."""
    if not postava or not str(postava).strip():
        return get_active_slot(uid), None
    slot = resolve_slot(uid, postava)
    if slot is None:
        chars = list_chars(uid)
        seznam = ", ".join(
            f"`{s} · {c.get('name', f'Postava {s}')}`" for s, c in sorted(chars.items())
        ) or "*žádné postavy*"
        return None, (
            f"❌ Postavu `{postava}` u tohoto hráče neznám (nebo sedí na víc postav). "
            f"Má: {seznam}"
        )
    return slot, None


def char_label(uid, slot) -> str:
    """Jméno postavy pro hlášky."""
    ch = list_chars(uid).get(str(slot)) or {}
    return ch.get("name") or f"Postava {slot}"


def char_note(uid, slot, postava: str | None) -> str:
    """Přípona do hlášky — jen když admin cílil na konkrétní postavu."""
    return f"\n-# postava: **{char_label(uid, slot)}**" if postava else ""
