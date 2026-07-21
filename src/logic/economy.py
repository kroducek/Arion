import discord
from discord import app_commands
from discord.ext import commands
import json
import logging
import os
import random

from src.utils.paths import (
    ECONOMY as ECONOMY_FILE,
    SILVER as SILVER_FILE,
    STARDUST as STARDUST_FILE,
    MINIGAME_CURRENCY as MINIGAME_CFG_FILE,
    SHOPS as SHOPS_FILE,
    PROFILES as PROFILES_FILE,
)
from src.utils.json_utils import load_json, save_json
from src.database.characters import pkey

# Destinace pro lokaci obchodů — čteno LÍNĚ (až za běhu), aby nezáleželo na
# pořadí načítání cogů. Statické choices se vyhodnotí při importu, kdy onboard
# ještě nemusí být načtený → nabízela se jen "Žádná". Autocomplete čte za běhu.
LOKACE_NONE = "zadna"

def _get_dests() -> dict:
    try:
        from src.logic.onboard import DESTINATIONS
        return DESTINATIONS or {}
    except Exception:
        return {}

def _lokace_label(key: str | None) -> str:
    if not key or key == LOKACE_NONE:
        return "🗺️ bez lokace"
    d = _get_dests().get(key)
    return f"{d.get('emoji','')} {d.get('name',key)}" if d else key

async def _lokace_autocomplete(interaction, current: str):
    cur = (current or "").lower()
    opts = [app_commands.Choice(name="🗺️ Žádná / všude", value=LOKACE_NONE)]
    for k, d in _get_dests().items():
        label = f"{d.get('emoji','')} {d.get('name',k)}"
        if cur in label.lower() or cur in k.lower():
            opts.append(app_commands.Choice(name=label, value=k))
    return opts[:25]

COIN         = "<:goldcoin:1490171741237018795>"

# ── Datová vrstva ──────────────────────────────────────────────────────────────

def _load_economy() -> dict:
    """Load economy data with fallback."""
    return load_json(ECONOMY_FILE, default={})

def _save_economy(data: dict) -> None:
    save_json(ECONOMY_FILE, data)


# ── Multi-currency API ────────────────────────────────────────────────────────
# Gold zůstává v economy.json beze změny ({uid: int}); silver a stardust mají
# vlastní soubory stejného tvaru. API níže směruje podle měny, takže staré
# gold čtení (economy[uid]) nikde nespadne a minihry lze přepínat postupně.
#
# Použití:
#   from src.logic.economy import get_balance, add_balance, spend, coin
#   add_balance(uid, 50, "silver")          # výhra v minihře
#   if spend(uid, bet, "silver"): ...        # sázka
#   add_balance(uid, dust, "stardust")       # spálení karty

COIN_GOLD     = COIN                      # 🟡 <:goldcoin:1490171741237018795>
COIN_SILVER   = "<:silvercoin:1518485401239683143>"   # ⚪ stříbrňáky
COIN_STARDUST = "<:stardust:1518485425407266888>"     # ✨ hvězdný prach

_CURRENCY_FILES = {
    "gold":     ECONOMY_FILE,
    "silver":   SILVER_FILE,
    "stardust": STARDUST_FILE,
}
_CURRENCY_ICONS = {
    "gold":     COIN_GOLD,
    "silver":   COIN_SILVER,
    "stardust": COIN_STARDUST,
}
CURRENCIES = tuple(_CURRENCY_FILES.keys())

# Volby měny do slash příkazů (unicode ikony — custom emoji se v nabídce nezobrazí)
MENA_CHOICES = [
    app_commands.Choice(name="🟡 Zlaťáky", value="gold"),
    app_commands.Choice(name="⚪ Stříbrňáky", value="silver"),
    app_commands.Choice(name="✨ Hvězdný prach", value="stardust"),
]
_CURRENCY_NAMES = {
    "gold": "zlaťáků",
    "silver": "stříbrňáků",
    "stardust": "hvězdného prachu",
}


def currency_name(currency: str = "gold") -> str:
    """Skloňovaný název měny pro hlášky (např. 'stříbrňáků')."""
    return _CURRENCY_NAMES.get(currency, currency)


def _currency_file(currency: str) -> str:
    if currency not in _CURRENCY_FILES:
        raise ValueError(f"Neznámá měna: {currency!r}")
    return _CURRENCY_FILES[currency]


def coin(currency: str = "gold") -> str:
    """Ikona měny pro embedy (🟡 / ⚪ / ✨)."""
    return _CURRENCY_ICONS.get(currency, "")


def _wallet_key(uid, currency: str) -> str:
    """Klíč peněženky: gold = per-postava (pkey), silver/stardust = per-účet (raw uid)."""
    return pkey(uid) if currency == "gold" else str(uid)


def get_balance(uid, currency: str = "gold") -> int:
    """Zůstatek hráče v dané měně."""
    data = load_json(_currency_file(currency), default={})
    try:
        return int(data.get(_wallet_key(uid, currency), 0))
    except (TypeError, ValueError):
        return 0


def set_balance(uid, amount: int, currency: str = "gold") -> int:
    """Nastaví zůstatek na přesnou hodnotu."""
    f = _currency_file(currency)
    data = load_json(f, default={})
    data[_wallet_key(uid, currency)] = int(amount)
    save_json(f, data)
    return int(amount)


def add_balance(uid, amount: int, currency: str = "gold") -> int:
    """Přičte částku (smí být záporná) a vrátí nový zůstatek."""
    f = _currency_file(currency)
    data = load_json(f, default={})
    key = _wallet_key(uid, currency)
    try:
        current = int(data.get(key, 0))
    except (TypeError, ValueError):
        current = 0
    data[key] = current + int(amount)
    save_json(f, data)
    return data[key]


def spend(uid, amount: int, currency: str = "gold") -> bool:
    """Strhne částku, jen pokud má hráč dost. Nikdy nejde do mínusu. Vrátí True/False."""
    amount = int(amount)
    if amount <= 0:
        return True
    f = _currency_file(currency)
    data = load_json(f, default={})
    key = _wallet_key(uid, currency)
    try:
        bal = int(data.get(key, 0))
    except (TypeError, ValueError):
        bal = 0
    if bal < amount:
        return False
    data[key] = bal - amount
    save_json(f, data)
    return True


def transfer(uid_from, uid_to, amount: int, currency: str = "gold") -> bool:
    """Převod mezi hráči. Vrátí False při nedostatku prostředků."""
    if int(amount) <= 0:
        return False
    if not spend(uid_from, amount, currency):
        return False
    add_balance(uid_to, amount, currency)
    return True


def get_wallet(uid) -> dict:
    """Vrátí všechny zůstatky hráče: {'gold': x, 'silver': y, 'stardust': z}."""
    return {c: get_balance(uid, c) for c in CURRENCIES}


# ── Přepínač měny miniher (globální) ──────────────────────────────────────────
# Minihry standardně běží na stříbrňáky. DM/admin může přes /minihry_mena
# přepnout na zlaťáky (např. pro vlastní testování). Default: silver.

def get_minigame_currency() -> str:
    """Měna, kterou teď používají minihry ('silver' nebo 'gold')."""
    cfg = load_json(MINIGAME_CFG_FILE, default={})
    cur = cfg.get("currency", "silver")
    return cur if cur in ("silver", "gold") else "silver"


def set_minigame_currency(currency: str) -> bool:
    """Přepne měnu miniher. Vrátí False pro neplatnou hodnotu."""
    if currency not in ("silver", "gold"):
        return False
    save_json(MINIGAME_CFG_FILE, {"currency": currency})
    return True


def minigame_file() -> str:
    """Cesta k JSON souboru měny, kterou teď používají minihry.
    Hry s vlastním _load_eco/_save_eco jen přesměrují cestu sem."""
    return _currency_file(get_minigame_currency())


def minigame_coin() -> str:
    """Ikona aktuální měny miniher."""
    return coin(get_minigame_currency())


# ── Shops datová vrstva ───────────────────────────────────────────────────────

def _load_shops() -> dict:
    return load_json(SHOPS_FILE, default={})

def _save_shops(data: dict) -> None:
    save_json(SHOPS_FILE, data)


# ══════════════════════════════════════════════════════════════════════════════
# SHOP POOLY  —  zboží podle TYPU obchodu (kovar, pekarna…), sdílené všemi shopy
# ══════════════════════════════════════════════════════════════════════════════

SHOP_POOLS_FILE = os.path.join(os.path.dirname(SHOPS_FILE), "shop_pools.json")

OFFER_SIZE = 4        # kolik položek reload náhodně vylosuje z poolů shopu


def _load_pools() -> dict:
    """{typ: [item, item, …]}  — typy jsou volné, vznikají přidáním prvního itemu."""
    return load_json(SHOP_POOLS_FILE, default={})

def _save_pools(data: dict) -> None:
    save_json(SHOP_POOLS_FILE, data)


def _parse_one_item(raw: str) -> tuple[dict | None, str | None]:
    """Jeden item ve formátu emoji;název;cena;item_id? → (item, chyba)."""
    parsed, err = _parse_items([raw])
    if err:
        return None, err
    if not parsed:
        return None, "Prázdný item."
    return parsed[0], None


def roll_offer(shop: dict) -> list[dict]:
    """Sestaví aktuální nabídku obchodu:
       náhodných OFFER_SIZE z poolů jeho typů  +  všechny speciály  +  unikát.

    Pooly se míchají dohromady (shop může mít víc typů). Unikát visí, dokud
    ho někdo nekoupí (shop['unique'] != None). Speciály jsou vždy.
    """
    pools = _load_pools()
    bag = []
    for t in shop.get("pool_types", []):
        bag.extend(pools.get(t, []))

    # náhodný výběr bez opakování (kolik je, tolik max)
    picked = random.sample(bag, min(OFFER_SIZE, len(bag))) if bag else []

    offer = list(picked)
    offer.extend(shop.get("specials", []))       # lokální speciály vždy
    unique = shop.get("unique")
    if unique:                                    # vzácný kus, dokud není koupen
        u = dict(unique)
        u["_unique"] = True                       # značka pro nákup (po koupi zmizí)
        offer.append(u)
    return offer


def shop_display_items(shop: dict) -> list[dict]:
    """Co se má reálně zobrazit/koupit. Nové shopy = 'offer' (vylosováno),
    staré shopy bez poolů = původní 'items' (zpětná kompatibilita)."""
    if shop.get("pool_types") or shop.get("specials") or shop.get("unique"):
        # nabídka se drží uložená (aby reload = vědomá akce, ne každý render jiný)
        return shop.get("offer", [])
    return shop.get("items", [])


def shops_in_location(location: str) -> list[dict]:
    """Obchody dané lokace — pro městský panel (board.py). Čte jen, nemění nic.
    Vrací [{'nazev','open','lokace'}]. 'bez lokace' obchody se do měst nepočítají.
    """
    out = []
    for preset, shop in _load_shops().items():
        if shop.get("lokace") == location:
            out.append({
                "preset": preset,
                "nazev":  shop.get("nazev", preset),
                "open":   bool(shop.get("open")),
                "channel": shop.get("channel"),
                "message": shop.get("message"),
            })
    return out

async def _ac_preset(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    shops = _load_shops()
    cur   = current.lower()
    return [
        app_commands.Choice(
            name=f"{'🟢' if s.get('open') else '🔴'}  {sid}  —  {s.get('nazev', sid)}",
            value=sid,
        )
        for sid, s in shops.items()
        if not cur or cur in sid.lower() or cur in s.get("nazev", "").lower()
    ][:25]


async def _ac_pooltype(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Nabídne existující typy poolů (kovar, pekarna…). Nový typ jde napsat ručně."""
    cur = (current or "").lower()
    pools = _load_pools()
    return [
        app_commands.Choice(name=f"{typ}  ({len(items)})", value=typ)
        for typ, items in pools.items()
        if not cur or cur in typ.lower()
    ][:25]


# ── Shop embed ────────────────────────────────────────────────────────────────

def _build_shop_embed(shop: dict, is_open: bool) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏪  {shop['nazev']}",
        color=0xC9A84C if is_open else 0x5D6D7E,
    )
    status_line = "" if is_open else "\n*— Obchod je momentálně zavřený —*"
    if shop.get("popis") or status_line:
        embed.description = (f"*{shop['popis']}*" if shop.get("popis") else "") + status_line

    items = shop_display_items(shop)
    if items:
        item_lines = []
        for i, item in enumerate(items, 1):
            star = "  ✨" if item.get("_unique") else ""
            item_lines.append(
                f"**{i}.** {item['emoji']} **{item['name']}**{star}\n-# {item['price']} {COIN}")
        embed.add_field(name="⚔️  Předměty", value="\n\n".join(item_lines), inline=False)

    if shop.get("ostatni"):
        embed.add_field(name="🧪  Ostatní", value=shop["ostatni"], inline=False)

    embed.set_footer(text="⭐ Aurionis  ·  Klikni na tlačítko pro nákup" if is_open else "⭐ Aurionis")
    return embed


# ── Shop View (tlačítka) ──────────────────────────────────────────────────────

class ShopView(discord.ui.View):
    MAX_BUTTONS = 25          # tvrdý limit Discordu (5 řad × 5)

    def __init__(self, preset_id: str, shop: dict):
        super().__init__(timeout=None)
        self.preset_id = preset_id
        for i, item in enumerate(shop_display_items(shop)):
            if i >= self.MAX_BUTTONS:
                break         # radši uříznout než spadnout při otevírání shopu
            tag = "  ✨" if item.get("_unique") else ""
            btn = discord.ui.Button(
                label=f"{item['emoji']}  {item['name']}  ·  {item['price']} zl.{tag}",
                style=(discord.ButtonStyle.success if item.get("_unique")
                       else discord.ButtonStyle.secondary),
                custom_id=f"gshop_{preset_id}_{i}",
            )
            btn.callback = self._make_callback(i, item["name"])
            self.add_item(btn)

    def _make_callback(self, item_index: int, expected_name: str):
        preset_id = self.preset_id
        async def callback(interaction: discord.Interaction):
            shops = _load_shops()
            shop  = shops.get(preset_id)
            if not shop:
                return await interaction.response.send_message(
                    "Tento shop už neexistuje.", ephemeral=True
                )
            if not shop.get("open", False):
                return await interaction.response.send_message(
                    "Obchod je momentálně zavřený.", ephemeral=True
                )
            items = shop_display_items(shop)
            if item_index >= len(items):
                return await interaction.response.send_message(
                    "Tento item už neexistuje.", ephemeral=True
                )
            item    = items[item_index]
            # Nabídka se mohla mezitím přemíchat (/gshop reload). Kdyby hráč měl
            # na obrazovce starou verzi, koupil by něco jiného, než vidí.
            if item.get("name") != expected_name:
                return await interaction.response.send_message(
                    "🔄 Nabídka obchodu se mezitím změnila — načti zprávu znovu.",
                    ephemeral=True
                )
            price   = item["price"]
            uid     = pkey(interaction.user.id)
            economy = _load_economy()
            balance = economy.get(uid, 0)
            if balance < price:
                return await interaction.response.send_message(
                    f"Nemáš dost zlaťáků! (Chybí ti **{price - balance}** {COIN})",
                    ephemeral=True,
                )
            economy[uid] = balance - price
            _save_economy(economy)

            # Přidej item do inventáře hráče
            profiles  = load_json(PROFILES_FILE, default={})
            profile   = profiles.setdefault(uid, {})
            inventory = profile.setdefault("inventory", [])
            item_id   = item.get("item_id")
            if item_id:
                entry = next(
                    (e for e in inventory if e.get("type") == "registered" and e.get("id") == item_id),
                    None,
                )
                if entry:
                    entry["qty"] = entry.get("qty", 1) + 1
                else:
                    inventory.append({"type": "registered", "id": item_id, "qty": 1})
            else:
                entry = next(
                    (e for e in inventory if e.get("type") == "free" and e.get("name") == item["name"]),
                    None,
                )
                if entry:
                    entry["qty"] = entry.get("qty", 1) + 1
                else:
                    inventory.append({"type": "free", "name": item["name"], "qty": 1})
            save_json(PROFILES_FILE, profiles)

            # Unikát po koupi zmizí — sundej ho ze shopu i z nabídky a překresli
            if item.get("_unique"):
                shop["unique"] = None
                shop["offer"] = [it for it in shop.get("offer", []) if not it.get("_unique")]
                _save_shops(shops)
                try:
                    # překresli embed I tlačítka — jinak by unikát zůstal vypsaný
                    # v textu, ale nešel koupit (rozbitý dojem)
                    await interaction.message.edit(
                        embed=_build_shop_embed(shop, is_open=True),
                        view=ShopView(preset_id, shop),
                    )
                except Exception:
                    logging.exception("[gshop] překreslení po koupi unikátu selhalo")

            await interaction.response.send_message(
                f"✅ Koupil/a jsi **{item['emoji']} {item['name']}** za **{price}** {COIN}."
                + ("  ✨ *(unikát!)*" if item.get("_unique") else "")
                + f"\n-# Zbývá ti **{economy[uid]}** {COIN}.",
                ephemeral=True,
            )
        return callback


# ── Pomocná funkce pro parsování itemů ───────────────────────────────────────

def _parse_items(raws: list[str | None]) -> tuple[list, str | None]:
    """
    Parsuje seznam raw stringů.
    Formáty:
      emoji;název;cena              → free item (podle jména)
      emoji;název;cena;item_id      → registered item (propojeno s items DB)
    Vrátí (parsed_items, error_message).
    """
    items = []
    for raw in raws:
        if not raw:
            continue
        parts = [p.strip() for p in raw.split(";")]
        if len(parts) not in (3, 4):
            return [], (
                f"Špatný formát: `{raw}`\n"
                f"Použij: `emoji;název;cena` nebo `emoji;název;cena;item_id`"
            )
        emoji_part, name_part, price_part = parts[0], parts[1], parts[2]
        item_id = parts[3] if len(parts) == 4 else None
        if not price_part.isdigit() or int(price_part) <= 0:
            return [], f"Cena musí být kladné číslo: `{price_part}`"
        entry: dict = {"emoji": emoji_part, "name": name_part, "price": int(price_part)}
        if item_id:
            entry["item_id"] = item_id
        items.append(entry)
    return items, None


# ── Žebříček s přepínači měny ──────────────────────────────────────────────────

_LB_NAMES = {"gold": "Zlaťáky", "silver": "Stříbrňáky", "stardust": "Hvězdný prach"}


def build_leaderboard_embed(guild, currency: str = "gold") -> discord.Embed:
    """Sestaví embed žebříčku pro danou měnu (top 10)."""
    data = load_json(_currency_file(currency), default={})
    icon = coin(currency)
    title = f"🏆 Žebříček — {_LB_NAMES.get(currency, currency)}"

    if not data:
        return discord.Embed(title=title, description="*Zatím tu nikdo nic nemá.*", color=0xFFD700)

    ranked = sorted(data.items(), key=lambda x: x[1], reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, bal) in enumerate(ranked):
        prefix = medals[i] if i < 3 else f"**{i+1}.**"
        member = guild.get_member(int(uid.split(":")[0])) if guild else None
        name   = member.display_name if member else f"Neznámý ({uid})"
        lines.append(f"{prefix} {name} — **{bal}** {icon}")

    return discord.Embed(title=title, description="\n".join(lines), color=0xFFD700)


class LeaderboardView(discord.ui.View):
    """Přepínač měny pod žebříčkem — kdokoli může přepnout zobrazení."""

    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Zlaťáky", emoji="🟡", style=discord.ButtonStyle.secondary)
    async def gold_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_leaderboard_embed(interaction.guild, "gold"), view=self
        )

    @discord.ui.button(label="Stříbrňáky", emoji="⚪", style=discord.ButtonStyle.secondary)
    async def silver_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_leaderboard_embed(interaction.guild, "silver"), view=self
        )


# ── Economy Cog ───────────────────────────────────────────────────────────────

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /g ────────────────────────────────────────────────────────────────────

    @app_commands.command(name="g", description="Zobrazí tvé měny (zlaťáky, stříbrňáky, hvězdný prach)")
    async def g(self, interaction: discord.Interaction):
        w = get_wallet(interaction.user.id)
        await interaction.response.send_message(
            f"{interaction.user.mention}, tvé konto:\n"
            f"{COIN_GOLD} **{w['gold']}** zlaťáků\n"
            f"{COIN_SILVER} **{w['silver']}** stříbrňáků\n"
            f"{COIN_STARDUST} **{w['stardust']}** hvězdného prachu"
        )

    # ── /gsend ────────────────────────────────────────────────────────────────

    @app_commands.command(name="gsend", description="Pošle měnu jinému hráči")
    @app_commands.describe(
        member="Komu chceš poslat",
        amount="Kolik",
        mena="Která měna (výchozí: zlaťáky)",
    )
    @app_commands.choices(mena=MENA_CHOICES)
    async def gsend(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: int,
        mena: app_commands.Choice[str] | None = None,
    ):
        currency = mena.value if mena else "gold"
        icon = coin(currency)

        if amount <= 0:
            return await interaction.response.send_message("Musíš poslat víc než 0!", ephemeral=True)
        if member.id == interaction.user.id:
            return await interaction.response.send_message("Nemůžeš poslat měnu sám sobě!", ephemeral=True)
        if member.bot:
            return await interaction.response.send_message("Botům měnu posílat nelze.", ephemeral=True)

        if not spend(interaction.user.id, amount, currency):
            have = get_balance(interaction.user.id, currency)
            return await interaction.response.send_message(
                f"Nemáš dost! (Chybí ti {amount - have} {icon})", ephemeral=True
            )
        add_balance(member.id, amount, currency)

        await interaction.response.send_message(
            f"Úspěšně jsi poslal **{amount}** {icon} hráči {member.mention}."
        )

    # ── /gadd ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="gadd", description="Admin: Přidá měnu hráči")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        member="Hráč",
        amount="Kolik přidat",
        mena="Která měna (výchozí: zlaťáky)",
    )
    @app_commands.choices(mena=MENA_CHOICES)
    async def gadd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: int,
        mena: app_commands.Choice[str] | None = None,
    ):
        currency = mena.value if mena else "gold"
        icon = coin(currency)

        if amount <= 0:
            return await interaction.response.send_message("Částka musí být větší než 0!", ephemeral=True)
        if member.bot:
            return await interaction.response.send_message("Botům měnu přidávat nelze.", ephemeral=True)

        new_bal = add_balance(member.id, amount, currency)
        await interaction.response.send_message(
            f"✅ Přidáno **{amount}** {icon} hráči {member.mention}. (Celkem: {new_bal})"
        )

    @app_commands.command(name="gremove", description="Admin: Odebere měnu hráči (může jít do mínusu)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        member = "Hráč, kterému chceš odebrat měnu",
        amount = "Kolik odebrat (nebo 0 pro reset na nulu)",
        mena   = "Která měna (výchozí: zlaťáky)",
        minus  = "Povolit záporný zůstatek? (výchozí: Ne)",
    )
    @app_commands.choices(
        mena=MENA_CHOICES,
        minus=[
            app_commands.Choice(name="Ano — může jít do mínusu", value=1),
            app_commands.Choice(name="Ne — odebere max co má",   value=0),
        ],
    )
    async def gremove(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: int,
        mena: app_commands.Choice[str] | None = None,
        minus: int = 0,
    ):
        currency = mena.value if mena else "gold"
        icon = coin(currency)

        if amount < 0:
            return await interaction.response.send_message(
                "Zadej kladné číslo (nebo 0 pro reset na nulu)!", ephemeral=True
            )

        current = get_balance(member.id, currency)

        if amount == 0:
            set_balance(member.id, 0, currency)
            return await interaction.response.send_message(
                f"🗑️ Hráči {member.mention} bylo odebráno všech **{current}** {icon}. Konto je prázdné."
            )

        if minus:
            # Povolíme záporný zůstatek
            new_bal = add_balance(member.id, -amount, currency)
            bal_str = f"**{new_bal}** {icon}" if new_bal >= 0 else f"**{new_bal}** {icon}  *(dluh)*"
            await interaction.response.send_message(
                f"🗑️ Odebráno **{amount}** {icon} hráči {member.mention}. (Zbývá: {bal_str})"
            )
        else:
            # Klasické chování — nejde pod nulu
            if current == 0:
                return await interaction.response.send_message(
                    f"Hráč {member.mention} nemá žádné {currency_name(currency)}.", ephemeral=True
                )
            actual = min(amount, current)
            set_balance(member.id, current - actual, currency)
            msg = f"🗑️ Odebráno **{actual}** {icon} hráči {member.mention}. (Zbývá: {current - actual})"
            if actual < amount:
                msg += f"\n-# *(Hráč měl jen {current}, odebráno maximum. Použij `minus: Ano` pro dluh.)*"
            await interaction.response.send_message(msg)

    # ── /minihry_mena ─────────────────────────────────────────────────────────

    @app_commands.command(name="minihry_mena", description="Admin: Přepni měnu miniher (silver/gold)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(mena="Na co přepnout minihry (výchozí stav: stříbrňáky)")
    @app_commands.choices(mena=[
        app_commands.Choice(name="⚪ Stříbrňáky (normální)", value="silver"),
        app_commands.Choice(name="🟡 Zlaťáky (testovací režim)", value="gold"),
    ])
    async def minihry_mena(self, interaction: discord.Interaction, mena: app_commands.Choice[str]):
        if not set_minigame_currency(mena.value):
            return await interaction.response.send_message("❌ Neplatná měna.", ephemeral=True)
        icon = coin(mena.value)
        mena_nom = "stříbrňáky" if mena.value == "silver" else "zlaťáky"
        await interaction.response.send_message(
            f"🎮 Minihry teď běží na **{mena_nom}** {icon}.\n"
            f"-# Platí pro nově začaté hry (sázky i výhry).",
            ephemeral=True,
        )

    # ── /gshop ────────────────────────────────────────────────────────────────

    shop_group = app_commands.Group(name="gshop", description="Admin: Správa shopů")

    @shop_group.command(name="create", description="Admin: Vytvoř nový preset shopu")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        preset  = "Unikátní ID presetu (např. kovarna_lumenie)",
        nazev   = "Zobrazovaný název shopu",
        popis   = "Krátký popis / uvítací text (volitelné)",
        typy    = "Pooly zboží — čárkou (kovar,alchymie). Zboží se pak losuje z poolu.",
        unikat  = "Vzácný kus: emoji;název;cena;item_id?  (visí dokud ho někdo nekoupí)",
        item1   = "Item 1  —  formát: emoji;název;cena  (pevný item, když nechceš pool)",
        item2   = "Item 2",
        item3   = "Item 3",
        item4   = "Item 4",
        item5   = "Item 5",
        ostatni = "Volný text pro ostatní zboží (lektvary, jídlo…)",
        lokace  = "Ve kterém městě obchod stojí (pro panel města).",
    )
    @app_commands.autocomplete(lokace=_lokace_autocomplete, typy=_ac_pooltype)
    async def gshop_create(
        self,
        interaction: discord.Interaction,
        preset:  str,
        nazev:   str,
        popis:   str | None = None,
        typy:    str | None = None,
        unikat:  str | None = None,
        item1:   str | None = None,
        item2:   str | None = None,
        item3:   str | None = None,
        item4:   str | None = None,
        item5:   str | None = None,
        ostatni: str | None = None,
        lokace:  str = LOKACE_NONE,
    ):
        await interaction.response.defer(ephemeral=True)
        preset = preset.strip().lower().replace(" ", "_")
        shops  = _load_shops()
        if preset in shops:
            return await interaction.followup.send(
                f"❌ Preset `{preset}` už existuje. Použij `/gshop edit`.", ephemeral=True
            )
        parsed, err = _parse_items([item1, item2, item3, item4, item5])
        if err:
            return await interaction.followup.send(f"❌ {err}", ephemeral=True)

        # typy poolů (čárkou) + volitelný unikát
        pool_types = [t.strip().lower().replace(" ", "_")
                      for t in (typy or "").split(",") if t.strip()]
        unique = None
        if unikat:
            unique, uerr = _parse_one_item(unikat)
            if uerr:
                return await interaction.followup.send(f"❌ Unikát: {uerr}", ephemeral=True)

        if not parsed and not ostatni and not pool_types and not unique:
            return await interaction.followup.send(
                "❌ Shop musí mít alespoň jeden item, pool (`typy`), unikát nebo sekci Ostatní.",
                ephemeral=True
            )

        shops[preset] = {
            "nazev":   nazev,
            "popis":   popis or "",
            "items":   parsed,
            "ostatni": ostatni or "",
            "lokace":  lokace,
            "pool_types": pool_types,
            "specials":   [],
            "unique":     unique,
            "offer":      [],
            "open":    False,
            "message": None,
            "channel": None,
        }
        # rovnou namíchej první nabídku, ať shop není prázdný
        if pool_types or unique:
            shops[preset]["offer"] = roll_offer(shops[preset])
        _save_shops(shops)
        info = []
        if pool_types:
            info.append(f"📦 pooly: {', '.join(pool_types)} "
                        f"({len(shops[preset]['offer'])} v nabídce)")
        if unique:
            info.append(f"✨ unikát: {unique['emoji']} {unique['name']}")
        if parsed:
            info.append(f"{len(parsed)} pevných itemů")
        await interaction.followup.send(
            f"✅ Preset **`{preset}`** — **{nazev}** vytvořen.\n"
            + (f"-# {'  ·  '.join(info)}\n" if info else "")
            + f"-# Použij `/gshop open preset:{preset}` pro zveřejnění.",
            ephemeral=True,
        )

    @shop_group.command(name="edit", description="Admin: Uprav existující preset shopu")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        preset  = "Preset k úpravě",
        nazev   = "Nový název (ponech prázdné pro beze změny)",
        popis   = "Nový popis",
        item1   = "Item 1  —  přepíše celý seznam itemů pokud zadáš alespoň jeden",
        item2   = "Item 2",
        item3   = "Item 3",
        item4   = "Item 4",
        item5   = "Item 5",
        ostatni = "Nová sekce Ostatní",
        lokace  = "Změň město obchodu (pro panel města).",
    )
    @app_commands.autocomplete(lokace=_lokace_autocomplete, preset=_ac_preset)
    async def gshop_edit(
        self,
        interaction: discord.Interaction,
        preset:  str,
        nazev:   str | None = None,
        popis:   str | None = None,
        item1:   str | None = None,
        item2:   str | None = None,
        item3:   str | None = None,
        item4:   str | None = None,
        item5:   str | None = None,
        ostatni: str | None = None,
        lokace:  str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        shops = _load_shops()
        shop  = shops.get(preset)
        if not shop:
            return await interaction.followup.send(
                f"❌ Preset `{preset}` neexistuje.", ephemeral=True
            )

        if nazev:
            shop["nazev"] = nazev
        if popis is not None:
            shop["popis"] = popis
        if any([item1, item2, item3, item4, item5]):
            parsed, err = _parse_items([item1, item2, item3, item4, item5])
            if err:
                return await interaction.followup.send(f"❌ {err}", ephemeral=True)
            shop["items"] = parsed
        if ostatni is not None:
            shop["ostatni"] = ostatni
        if lokace is not None:
            shop["lokace"] = lokace

        _save_shops(shops)

        # Pokud je shop otevřený — aktualizuj živou zprávu
        if shop.get("open") and shop.get("message") and shop.get("channel"):
            try:
                channel = interaction.guild.get_channel(shop["channel"])
                if channel:
                    msg = await channel.fetch_message(shop["message"])
                    await msg.edit(
                        embed=_build_shop_embed(shop, is_open=True),
                        view=ShopView(preset, shop),
                    )
                    return await interaction.followup.send(
                        "✅ Preset upraven a živá zpráva aktualizována.", ephemeral=True
                    )
            except discord.NotFound:
                shop["message"] = None
                shop["channel"] = None
                _save_shops(shops)
            except Exception:
                logging.exception("[gshop_edit] Nelze aktualizovat živou zprávu")

        await interaction.followup.send(f"✅ Preset `{preset}` upraven.", ephemeral=True)

    @shop_group.command(name="open", description="Admin: Zveřejni preset shopu do kanálu")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(preset="Preset k otevření")
    @app_commands.autocomplete(preset=_ac_preset)
    async def gshop_open(self, interaction: discord.Interaction, preset: str):
        await interaction.response.defer(ephemeral=True)
        shops = _load_shops()
        shop  = shops.get(preset)
        if not shop:
            return await interaction.followup.send(
                f"❌ Preset `{preset}` neexistuje.", ephemeral=True
            )
        if shop.get("open"):
            ch = interaction.guild.get_channel(shop.get("channel", 0))
            where = ch.mention if ch else "neznámý kanál"
            return await interaction.followup.send(
                f"Shop je už otevřený v {where}.", ephemeral=True
            )

        shop["open"] = True
        # poolový shop bez namíchané nabídky → vylosuj při otevření
        if (shop.get("pool_types") or shop.get("specials") or shop.get("unique")) \
                and not shop.get("offer"):
            shop["offer"] = roll_offer(shop)
        msg = await interaction.channel.send(
            embed=_build_shop_embed(shop, is_open=True),
            view=ShopView(preset, shop),
        )
        shop["message"] = msg.id
        shop["channel"] = interaction.channel.id
        _save_shops(shops)
        await interaction.followup.send(f"🏪 **{shop['nazev']}** otevřen.", ephemeral=True)

    @shop_group.command(name="close", description="Admin: Zavři preset shopu")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(preset="Preset k zavření")
    @app_commands.autocomplete(preset=_ac_preset)
    async def gshop_close(self, interaction: discord.Interaction, preset: str):
        await interaction.response.defer(ephemeral=True)
        shops = _load_shops()
        shop  = shops.get(preset)
        if not shop:
            return await interaction.followup.send(
                f"❌ Preset `{preset}` neexistuje.", ephemeral=True
            )
        if not shop.get("open"):
            return await interaction.followup.send("Shop je už zavřený.", ephemeral=True)

        shop["open"] = False
        if shop.get("message") and shop.get("channel"):
            try:
                channel = interaction.guild.get_channel(shop["channel"])
                if channel:
                    msg = await channel.fetch_message(shop["message"])
                    await msg.edit(embed=_build_shop_embed(shop, is_open=False), view=None)
            except discord.NotFound:
                pass
            except Exception:
                logging.exception("[gshop_close] Nelze aktualizovat živou zprávu")
        shop["message"] = None
        shop["channel"] = None
        _save_shops(shops)
        await interaction.followup.send(f"🔒 **{shop['nazev']}** zavřen.", ephemeral=True)

    @shop_group.command(name="presets", description="Admin: Seznam všech shopů a jejich stav")
    @app_commands.checks.has_permissions(administrator=True)
    async def gshop_presets(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        shops = _load_shops()
        if not shops:
            return await interaction.followup.send(
                "Žádné presety. Vytvoř první přes `/gshop create`.", ephemeral=True
            )
        lines = []
        for sid, s in shops.items():
            status = "🟢 otevřeno" if s.get("open") else "🔴 zavřeno"
            ch = interaction.guild.get_channel(s.get("channel") or 0)
            ch_txt = f"  ·  {ch.mention}" if ch and s.get("open") else ""

            types = s.get("pool_types") or []
            if types:
                detail = (f"📦 pooly: {', '.join(types)}  ·  "
                          f"{len(s.get('offer', []))} v nabídce")
                extra = []
                if s.get("specials"):
                    extra.append(f"{len(s['specials'])}× speciál")
                if s.get("unique"):
                    extra.append("✨ unikát")
                if extra:
                    detail += "  ·  " + ", ".join(extra)
            else:
                detail = (f"⚠️ starý režim — {len(s.get('items', []))} pevných itemů  ·  "
                          f"přepni přes `/gshop settype`")

            lines.append(
                f"**`{sid}`** — {s.get('nazev', '?')}  ·  {status}{ch_txt}\n"
                f"-# {detail}"
            )
        embed = discord.Embed(
            title="🏪  Přehled shopů",
            description="\n\n".join(lines),
            color=0xC9A84C,
        )
        embed.set_footer(text="⭐ Aurionis")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @shop_group.command(name="delete", description="Admin: Smaž preset shopu")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(preset="Preset ke smazání")
    @app_commands.autocomplete(preset=_ac_preset)
    async def gshop_delete(self, interaction: discord.Interaction, preset: str):
        await interaction.response.defer(ephemeral=True)
        shops = _load_shops()
        shop  = shops.get(preset)
        if not shop:
            return await interaction.followup.send(
                f"❌ Preset `{preset}` neexistuje.", ephemeral=True
            )
        # Zavři živou zprávu pokud je otevřená
        if shop.get("open") and shop.get("message") and shop.get("channel"):
            try:
                channel = interaction.guild.get_channel(shop["channel"])
                if channel:
                    msg = await channel.fetch_message(shop["message"])
                    await msg.edit(embed=_build_shop_embed(shop, is_open=False), view=None)
            except Exception:
                pass
        del shops[preset]
        _save_shops(shops)
        await interaction.followup.send(
            f"🗑️ Preset **`{preset}`** — **{shop.get('nazev', '')}** smazán.", ephemeral=True
        )

    # ══════════════════════════════════════════════════════════════════════════
    # SHOP POOLY  —  /gpool add/list/remove  +  /gshop reload/special/unique
    # ══════════════════════════════════════════════════════════════════════════

    pool_group = app_commands.Group(name="gpool", description="Admin: Zásobníky zboží podle typu")

    @pool_group.command(name="add", description="Admin: Přidá item do poolu typu (kovar, pekarna…)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        typ="Typ obchodu (volný — kovar, pekarna, alchymie…). Nový se založí sám.",
        item="Item: `emoji;název;cena` nebo `emoji;název;cena;item_id`",
    )
    @app_commands.autocomplete(typ=_ac_pooltype)
    async def gpool_add(self, interaction: discord.Interaction, typ: str, item: str):
        await interaction.response.defer(ephemeral=True)
        typ = typ.strip().lower().replace(" ", "_")
        parsed, err = _parse_one_item(item)
        if err:
            return await interaction.followup.send(f"❌ {err}", ephemeral=True)
        pools = _load_pools()
        pools.setdefault(typ, []).append(parsed)
        _save_pools(pools)
        await interaction.followup.send(
            f"✅ Přidáno do poolu **{typ}**: {parsed['emoji']} {parsed['name']} "
            f"· {parsed['price']} zl.  (celkem **{len(pools[typ])}**)", ephemeral=True)

    @pool_group.command(name="list", description="Admin: Vypíše pool typu")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(typ="Typ obchodu")
    @app_commands.autocomplete(typ=_ac_pooltype)
    async def gpool_list(self, interaction: discord.Interaction, typ: str):
        await interaction.response.defer(ephemeral=True)
        typ = typ.strip().lower().replace(" ", "_")
        items = _load_pools().get(typ, [])
        if not items:
            return await interaction.followup.send(
                f"Pool **{typ}** je prázdný nebo neexistuje.", ephemeral=True)
        lines = [f"{i+1}. {it['emoji']} **{it['name']}** · {it['price']} zl."
                 + (f"  `{it['item_id']}`" if it.get("item_id") else "")
                 for i, it in enumerate(items)]
        desc = "\n".join(lines)
        if len(desc) > 3900:
            desc = desc[:3900] + "\n-# …"
        embed = discord.Embed(title=f"📦 Pool — {typ} ({len(items)})",
                              description=desc, color=0xC9A84C)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @pool_group.command(name="remove", description="Admin: Odebere item z poolu podle čísla z /gpool list")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(typ="Typ obchodu", cislo="Pořadí z /gpool list")
    @app_commands.autocomplete(typ=_ac_pooltype)
    async def gpool_remove(self, interaction: discord.Interaction, typ: str, cislo: int):
        await interaction.response.defer(ephemeral=True)
        typ = typ.strip().lower().replace(" ", "_")
        pools = _load_pools()
        items = pools.get(typ, [])
        if not (1 <= cislo <= len(items)):
            return await interaction.followup.send(
                f"❌ Neplatné číslo (1–{len(items)}).", ephemeral=True)
        removed = items.pop(cislo - 1)
        _save_pools(pools)
        await interaction.followup.send(
            f"🗑️ Odebráno z **{typ}**: {removed['emoji']} {removed['name']}", ephemeral=True)

    @shop_group.command(name="reload", description="Admin: Přemíchá nabídku shopu z poolů")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(preset="Shop k přemíchání")
    @app_commands.autocomplete(preset=_ac_preset)
    async def gshop_reload(self, interaction: discord.Interaction, preset: str):
        await interaction.response.defer(ephemeral=True)
        shops = _load_shops()
        shop  = shops.get(preset)
        if not shop:
            return await interaction.followup.send(f"❌ Preset `{preset}` neexistuje.", ephemeral=True)
        shop["offer"] = roll_offer(shop)
        _save_shops(shops)
        # překresli živou zprávu, pokud je otevřená
        if shop.get("open") and shop.get("message") and shop.get("channel"):
            try:
                channel = interaction.guild.get_channel(shop["channel"])
                msg = await channel.fetch_message(shop["message"])
                await msg.edit(embed=_build_shop_embed(shop, is_open=True),
                               view=ShopView(preset, shop))
            except Exception:
                logging.exception("[gshop_reload] živá zpráva")
        await interaction.followup.send(
            f"♻️ **{shop.get('nazev','')}** přemíchán — **{len(shop['offer'])}** položek "
            f"({', '.join(shop.get('pool_types', [])) or 'bez poolu'}).", ephemeral=True)

    @shop_group.command(name="special", description="Admin: Přidá lokální speciál do shopu (vždy v nabídce)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(preset="Shop", item="`emoji;název;cena;item_id?` (prázdné = vypíše speciály)")
    @app_commands.autocomplete(preset=_ac_preset)
    async def gshop_special(self, interaction: discord.Interaction, preset: str, item: str | None = None):
        await interaction.response.defer(ephemeral=True)
        shops = _load_shops()
        shop  = shops.get(preset)
        if not shop:
            return await interaction.followup.send(f"❌ Preset `{preset}` neexistuje.", ephemeral=True)
        specials = shop.setdefault("specials", [])
        if not item:
            if not specials:
                return await interaction.followup.send("Žádné speciály.", ephemeral=True)
            lines = [f"{i+1}. {s['emoji']} {s['name']} · {s['price']} zl." for i, s in enumerate(specials)]
            return await interaction.followup.send("**Speciály:**\n" + "\n".join(lines), ephemeral=True)
        parsed, err = _parse_one_item(item)
        if err:
            return await interaction.followup.send(f"❌ {err}", ephemeral=True)
        specials.append(parsed)
        _save_shops(shops)
        await interaction.followup.send(
            f"✅ Speciál přidán do **{shop.get('nazev','')}**: {parsed['emoji']} {parsed['name']}.\n"
            f"-# Projeví se po `/gshop reload`.", ephemeral=True)

    @shop_group.command(name="unique", description="Admin: Nastaví/sundá unikátní vzácný item (visí do koupě)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(preset="Shop", item="`emoji;název;cena;item_id?` — prázdné = sundá unikát")
    @app_commands.autocomplete(preset=_ac_preset)
    async def gshop_unique(self, interaction: discord.Interaction, preset: str, item: str | None = None):
        await interaction.response.defer(ephemeral=True)
        shops = _load_shops()
        shop  = shops.get(preset)
        if not shop:
            return await interaction.followup.send(f"❌ Preset `{preset}` neexistuje.", ephemeral=True)
        if not item:
            shop["unique"] = None
            _save_shops(shops)
            return await interaction.followup.send("🚫 Unikát sundán.\n-# Projeví se po `/gshop reload`.", ephemeral=True)
        parsed, err = _parse_one_item(item)
        if err:
            return await interaction.followup.send(f"❌ {err}", ephemeral=True)
        shop["unique"] = parsed
        _save_shops(shops)
        await interaction.followup.send(
            f"✨ Unikát nastaven pro **{shop.get('nazev','')}**: {parsed['emoji']} {parsed['name']} "
            f"· {parsed['price']} zl.\n-# Visí dokud ho někdo nekoupí. Projeví se po `/gshop reload`.",
            ephemeral=True)

    @shop_group.command(name="settype", description="Admin: Nastaví typy poolů shopu (čárkou)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(preset="Shop", typy="Typy oddělené čárkou (kovar,alchymie). Prázdné = zruší.")
    @app_commands.autocomplete(preset=_ac_preset, typy=_ac_pooltype)
    async def gshop_settype(self, interaction: discord.Interaction, preset: str, typy: str | None = None):
        await interaction.response.defer(ephemeral=True)
        shops = _load_shops()
        shop  = shops.get(preset)
        if not shop:
            return await interaction.followup.send(f"❌ Preset `{preset}` neexistuje.", ephemeral=True)
        types = [t.strip().lower().replace(" ", "_") for t in (typy or "").split(",") if t.strip()]
        shop["pool_types"] = types
        shop["offer"] = roll_offer(shop)
        _save_shops(shops)
        await interaction.followup.send(
            f"✅ **{shop.get('nazev','')}** má typy: {', '.join(types) or '—'}.\n"
            f"-# Nabídka přemíchána ({len(shop['offer'])} položek).", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Economy(bot))