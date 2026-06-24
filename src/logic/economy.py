import discord
from discord import app_commands
from discord.ext import commands
import json
import logging
import os

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


# ── Shop embed ────────────────────────────────────────────────────────────────

def _build_shop_embed(shop: dict, is_open: bool) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏪  {shop['nazev']}",
        color=0xC9A84C if is_open else 0x5D6D7E,
    )
    status_line = "" if is_open else "\n*— Obchod je momentálně zavřený —*"
    if shop.get("popis") or status_line:
        embed.description = (f"*{shop['popis']}*" if shop.get("popis") else "") + status_line

    items = shop.get("items", [])
    if items:
        item_lines = [
            f"**{i}.** {item['emoji']} **{item['name']}**\n-# {item['price']} {COIN}"
            for i, item in enumerate(items, 1)
        ]
        embed.add_field(name="⚔️  Předměty", value="\n\n".join(item_lines), inline=False)

    if shop.get("ostatni"):
        embed.add_field(name="🧪  Ostatní", value=shop["ostatni"], inline=False)

    embed.set_footer(text="⭐ Aurionis  ·  Klikni na tlačítko pro nákup" if is_open else "⭐ Aurionis")
    return embed


# ── Shop View (tlačítka) ──────────────────────────────────────────────────────

class ShopView(discord.ui.View):
    def __init__(self, preset_id: str, shop: dict):
        super().__init__(timeout=None)
        self.preset_id = preset_id
        for i, item in enumerate(shop.get("items", [])):
            btn = discord.ui.Button(
                label=f"{item['emoji']}  {item['name']}  ·  {item['price']} zl.",
                style=discord.ButtonStyle.secondary,
                custom_id=f"gshop_{preset_id}_{i}",
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def _make_callback(self, item_index: int):
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
            items = shop.get("items", [])
            if item_index >= len(items):
                return await interaction.response.send_message(
                    "Tento item už neexistuje.", ephemeral=True
                )
            item    = items[item_index]
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
                # Registered item — stackuje se s ostatními stejnými
                entry = next(
                    (e for e in inventory if e.get("type") == "registered" and e.get("id") == item_id),
                    None,
                )
                if entry:
                    entry["qty"] = entry.get("qty", 1) + 1
                else:
                    inventory.append({"type": "registered", "id": item_id, "qty": 1})
            else:
                # Free item — stackuje se podle jména
                entry = next(
                    (e for e in inventory if e.get("type") == "free" and e.get("name") == item["name"]),
                    None,
                )
                if entry:
                    entry["qty"] = entry.get("qty", 1) + 1
                else:
                    inventory.append({"type": "free", "name": item["name"], "qty": 1})
            save_json(PROFILES_FILE, profiles)

            await interaction.response.send_message(
                f"✅ Koupil/a jsi **{item['emoji']} {item['name']}** za **{price}** {COIN}.\n"
                f"-# Zbývá ti **{economy[uid]}** {COIN}.",
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

    # ── /gleaderboard ─────────────────────────────────────────────────────────

    @app_commands.command(name="gleaderboard", description="Žebříček nejbohatších (přepínání 🟡/⚪)")
    async def gleaderboard(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=build_leaderboard_embed(interaction.guild, "gold"),
            view=LeaderboardView(),
        )

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
        item1   = "Item 1  —  formát: emoji;název;cena  (např. ⚔️;Železný meč;50)",
        item2   = "Item 2",
        item3   = "Item 3",
        item4   = "Item 4",
        item5   = "Item 5",
        ostatni = "Volný text pro ostatní zboží (lektvary, jídlo…)",
    )
    async def gshop_create(
        self,
        interaction: discord.Interaction,
        preset:  str,
        nazev:   str,
        popis:   str | None = None,
        item1:   str | None = None,
        item2:   str | None = None,
        item3:   str | None = None,
        item4:   str | None = None,
        item5:   str | None = None,
        ostatni: str | None = None,
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
        if not parsed and not ostatni:
            return await interaction.followup.send(
                "❌ Shop musí mít alespoň jeden item nebo sekci Ostatní.", ephemeral=True
            )
        shops[preset] = {
            "nazev":   nazev,
            "popis":   popis or "",
            "items":   parsed,
            "ostatni": ostatni or "",
            "open":    False,
            "message": None,
            "channel": None,
        }
        _save_shops(shops)
        await interaction.followup.send(
            f"✅ Preset **`{preset}`** — **{nazev}** vytvořen.\n"
            f"-# Použij `/gshop open preset:{preset}` pro zveřejnění.",
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
    )
    @app_commands.autocomplete(preset=_ac_preset)
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
            lines.append(
                f"**`{sid}`** — {s.get('nazev', '?')}  ·  {status}{ch_txt}\n"
                f"-# {len(s.get('items', []))} itemů"
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


async def setup(bot):
    await bot.add_cog(Economy(bot))