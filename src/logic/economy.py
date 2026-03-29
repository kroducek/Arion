import discord
from discord import app_commands
from discord.ext import commands
import json
import logging
import os

from src.utils.paths import ECONOMY as ECONOMY_FILE, SHOP as SHOP_FILE
from src.utils.json_utils import load_json, save_json

COIN         = "<:goldcoin:1477303464781680772>"

# ── Datová vrstva ──────────────────────────────────────────────────────────────

def _load(path: str, default=None):
    result = load_json(path)
    if result is None or (not result and default is not None):
        return default() if callable(default) else (default if default is not None else {})
    return result

def _save(path: str, data):
    save_json(path, data)


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
        item_lines = []
        for i, item in enumerate(items, 1):
            item_lines.append(
                f"**{i}.** {item['emoji']} **{item['name']}**\n"
                f"-# {item['price']} {COIN}"
            )
        embed.add_field(name="⚔️  Předměty", value="\n\n".join(item_lines), inline=False)

    if shop.get("ostatni"):
        embed.add_field(name="🧪  Ostatní", value=shop["ostatni"], inline=False)

    footer = "⭐ Aurionis  ·  Klikni na tlačítko pro nákup" if is_open else "⭐ Aurionis"
    embed.set_footer(text=footer)
    return embed


# ── Shop View (tlačítka) ──────────────────────────────────────────────────────

class ShopView(discord.ui.View):
    def __init__(self, shop: dict):
        super().__init__(timeout=None)
        for i, item in enumerate(shop.get("items", [])):
            btn = discord.ui.Button(
                label=f"{item['emoji']}  {item['name']}  ·  {item['price']} zl.",
                style=discord.ButtonStyle.secondary,
                custom_id=f"shop_buy_{i}",
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def _make_callback(self, item_index: int):
        async def callback(interaction: discord.Interaction):
            shop = _load(SHOP_FILE, dict)

            # Zkontroluj že shop je otevřený
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
            uid     = str(interaction.user.id)
            economy = _load(ECONOMY_FILE, dict)
            balance = economy.get(uid, 0)

            if balance < price:
                return await interaction.response.send_message(
                    f"Nemáš dost zlaťáků! (Chybí ti **{price - balance}** {COIN})",
                    ephemeral=True,
                )

            economy[uid] = balance - price
            _save(ECONOMY_FILE, economy)

            await interaction.response.send_message(
                f"✅ Koupil/a jsi **{item['emoji']} {item['name']}** za **{price}** {COIN}.\n"
                f"-# Zbývá ti **{economy[uid]}** {COIN}.",
                ephemeral=True,
            )
        return callback


# ── Pomocná funkce pro parsování itemů ───────────────────────────────────────

def _parse_items(raws: list[str | None]) -> tuple[list, str | None]:
    """
    Parsuje seznam raw stringů ve formátu 'emoji;název;cena'.
    Vrátí (parsed_items, error_message).
    """
    items = []
    for raw in raws:
        if not raw:
            continue
        parts = [p.strip() for p in raw.split(";")]
        if len(parts) != 3:
            return [], f"Špatný formát: `{raw}`\nPoužij: `emoji;název;cena`  (např. `⚔️;Železný meč;50`)"
        emoji_part, name_part, price_part = parts
        if not price_part.isdigit() or int(price_part) <= 0:
            return [], f"Cena musí být kladné číslo: `{price_part}`"
        items.append({"emoji": emoji_part, "name": name_part, "price": int(price_part)})
    return items, None


# ── Economy Cog ───────────────────────────────────────────────────────────────

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /g ────────────────────────────────────────────────────────────────────

    @app_commands.command(name="g", description="Zobrazí tvůj počet zlaťáků")
    async def g(self, interaction: discord.Interaction):
        economy = _load(ECONOMY_FILE, dict)
        balance = economy.get(str(interaction.user.id), 0)
        await interaction.response.send_message(
            f"{interaction.user.mention}, tvůj stav konta: **{balance}** {COIN}"
        )

    # ── /gsend ────────────────────────────────────────────────────────────────

    @app_commands.command(name="gsend", description="Pošle zlaťáky jinému hráči")
    async def gsend(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount <= 0:
            return await interaction.response.send_message("Musíš poslat víc než 0!", ephemeral=True)
        if member.id == interaction.user.id:
            return await interaction.response.send_message("Nemůžeš poslat peníze sám sobě!", ephemeral=True)
        if member.bot:
            return await interaction.response.send_message("Botům zlaťáky posílat nelze.", ephemeral=True)

        economy     = _load(ECONOMY_FILE, dict)
        sender_id   = str(interaction.user.id)
        receiver_id = str(member.id)
        sender_bal  = economy.get(sender_id, 0)

        if sender_bal < amount:
            return await interaction.response.send_message(
                f"Nemáš dost zlaťáků! (Chybí ti {amount - sender_bal} {COIN})", ephemeral=True
            )

        economy[sender_id]   = sender_bal - amount
        economy[receiver_id] = economy.get(receiver_id, 0) + amount
        _save(ECONOMY_FILE, economy)

        await interaction.response.send_message(
            f"Úspěšně jsi poslal **{amount}** {COIN} hráči {member.mention}."
        )

    # ── /gadd ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="gadd", description="Admin: Přidá zlaťáky hráči")
    @app_commands.checks.has_permissions(administrator=True)
    async def gadd(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount <= 0:
            return await interaction.response.send_message("Částka musí být větší než 0!", ephemeral=True)
        if member.bot:
            return await interaction.response.send_message("Botům zlaťáky přidávat nelze.", ephemeral=True)

        economy = _load(ECONOMY_FILE, dict)
        uid     = str(member.id)
        economy[uid] = economy.get(uid, 0) + amount
        _save(ECONOMY_FILE, economy)

        await interaction.response.send_message(
            f"✅ Přidáno **{amount}** {COIN} hráči {member.mention}. (Celkem: {economy[uid]})"
        )

    @app_commands.command(name="gremove", description="Admin: Odebere zlaťáky hráči (může jít do mínusu)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        member = "Hráč, kterému chceš odebrat zlaťáky",
        amount = "Počet zlaťáků (nebo 0 pro reset na nulu)",
        minus  = "Povolit záporný zůstatek? (výchozí: Ne)",
    )
    @app_commands.choices(minus=[
        app_commands.Choice(name="Ano — může jít do mínusu", value=1),
        app_commands.Choice(name="Ne — odebere max co má",   value=0),
    ])
    async def gremove(self, interaction: discord.Interaction, member: discord.Member, amount: int, minus: int = 0):
        if amount < 0:
            return await interaction.response.send_message(
                "Zadej kladné číslo (nebo 0 pro reset na nulu)!", ephemeral=True
            )

        economy = _load(ECONOMY_FILE, dict)
        uid     = str(member.id)
        current = economy.get(uid, 0)

        if amount == 0:
            economy[uid] = 0
            _save(ECONOMY_FILE, economy)
            return await interaction.response.send_message(
                f"🗑️ Hráči {member.mention} bylo odebráno všech **{current}** {COIN}. Konto je prázdné."
            )

        if minus:
            # Povolíme záporný zůstatek
            economy[uid] = current - amount
            _save(ECONOMY_FILE, economy)
            new_bal = economy[uid]
            bal_str = f"**{new_bal}** {COIN}" if new_bal >= 0 else f"**{new_bal}** {COIN}  *(dluh)*"
            await interaction.response.send_message(
                f"🗑️ Odebráno **{amount}** {COIN} hráči {member.mention}. (Zbývá: {bal_str})"
            )
        else:
            # Klasické chování — nejde pod nulu
            if current == 0:
                return await interaction.response.send_message(
                    f"Hráč {member.mention} nemá žádné zlaťáky.", ephemeral=True
                )
            actual       = min(amount, current)
            economy[uid] = current - actual
            _save(ECONOMY_FILE, economy)
            msg = f"🗑️ Odebráno **{actual}** {COIN} hráči {member.mention}. (Zbývá: {economy[uid]})"
            if actual < amount:
                msg += f"\n-# *(Hráč měl jen {current}, odebráno maximum. Použij `minus: Ano` pro dluh.)*"
            await interaction.response.send_message(msg)

    # ── /gleaderboard ─────────────────────────────────────────────────────────

    @app_commands.command(name="gleaderboard", description="Top 10 nejbohatších hráčů serveru")
    async def gleaderboard(self, interaction: discord.Interaction):
        economy = _load(ECONOMY_FILE, dict)
        if not economy:
            return await interaction.response.send_message(
                "Zatím tu nikdo žádné zlaťáky nemá.", ephemeral=True
            )

        sorted_all = sorted(economy.items(), key=lambda x: x[1], reverse=True)
        medals     = ["🥇", "🥈", "🥉"]
        lines      = []
        for i, (uid, balance) in enumerate(sorted_all[:10]):
            prefix = medals[i] if i < 3 else f"**{i+1}.**"
            member = interaction.guild.get_member(int(uid))
            name   = member.display_name if member else f"Neznámý ({uid})"
            lines.append(f"{prefix} {name} — **{balance}** {COIN}")

        embed = discord.Embed(
            title="🏆 Žebříček nejbohatších",
            description="\n".join(lines),
            color=0xFFD700,
        )
        caller_id   = str(interaction.user.id)
        caller_rank = next((i + 1 for i, (uid, _) in enumerate(sorted_all) if uid == caller_id), None)
        caller_bal  = economy.get(caller_id, 0)
        if caller_rank and caller_rank > 10:
            embed.set_footer(text=f"Tvoje pozice: #{caller_rank} ({caller_bal} zlaťáků)")
        elif caller_rank:
            embed.set_footer(text=f"Tvoje pozice: #{caller_rank}")

        await interaction.response.send_message(embed=embed)

    # ── /gshop ────────────────────────────────────────────────────────────────

    shop_group = app_commands.Group(name="gshop", description="Admin: Správa shopu")

    @shop_group.command(name="create", description="Admin: Vytvoř nový shop (uloží, ale nezveřejní)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        nazev   = "Název shopu",
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
        parsed, err = _parse_items([item1, item2, item3, item4, item5])
        if err:
            return await interaction.followup.send(f"❌ {err}", ephemeral=True)
        if not parsed and not ostatni:
            return await interaction.followup.send(
                "❌ Shop musí mít alespoň jeden item nebo sekci Ostatní.", ephemeral=True
            )

        shop = {
            "nazev":   nazev,
            "popis":   popis or "",
            "items":   parsed,
            "ostatni": ostatni or "",
            "open":    False,           # výchozí stav — zavřeno
            "message": None,            # ID zprávy s embedem (pro pozdější edit)
            "channel": None,
        }
        _save(SHOP_FILE, shop)
        await interaction.followup.send(
            f"✅ Shop **{nazev}** byl vytvořen.\n"
            f"-# Použij `/gshop open` pro zveřejnění do kanálu.",
            ephemeral=True,
        )

    @shop_group.command(name="edit", description="Admin: Uprav existující shop")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        nazev   = "Nový název (ponech prázdné pro beze změny)",
        popis   = "Nový popis",
        item1   = "Item 1  —  přepíše celý seznam itemů pokud zadáš alespoň jeden",
        item2   = "Item 2",
        item3   = "Item 3",
        item4   = "Item 4",
        item5   = "Item 5",
        ostatni = "Nová sekce Ostatní",
    )
    async def gshop_edit(
        self,
        interaction: discord.Interaction,
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
        shop = _load(SHOP_FILE, dict)
        if not shop:
            return await interaction.followup.send(
                "❌ Žádný shop neexistuje. Nejdřív ho vytvoř přes `/gshop create`.", ephemeral=True
            )

        # Aktualizuj jen zadané hodnoty
        if nazev:
            shop["nazev"] = nazev
        if popis is not None:
            shop["popis"] = popis

        raw_items = [item1, item2, item3, item4, item5]
        if any(raw_items):
            parsed, err = _parse_items(raw_items)
            if err:
                return await interaction.followup.send(f"❌ {err}", ephemeral=True)
            shop["items"] = parsed

        if ostatni is not None:
            shop["ostatni"] = ostatni

        _save(SHOP_FILE, shop)

        # Pokud je shop otevřený a má živou zprávu — uprav ji rovnou
        if shop.get("open") and shop.get("message") and shop.get("channel"):
            try:
                channel = interaction.guild.get_channel(shop["channel"])
                if channel:
                    msg = await channel.fetch_message(shop["message"])
                    await msg.edit(
                        embed=_build_shop_embed(shop, is_open=True),
                        view=ShopView(shop),
                    )
                    return await interaction.followup.send(
                        "✅ Shop upraven a živá zpráva aktualizována.", ephemeral=True
                    )
            except discord.NotFound:
                # Zpráva byla smazána — vyčisti stale reference
                shop["message"] = None
                shop["channel"] = None
                _save(SHOP_FILE, shop)
            except Exception:
                logging.exception("[gshop_edit] Nelze aktualizovat živou zprávu")

        await interaction.followup.send("✅ Shop upraven.", ephemeral=True)

    @shop_group.command(name="open", description="Admin: Zveřejni shop do kanálu a otevři nakupování")
    @app_commands.checks.has_permissions(administrator=True)
    async def gshop_open(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        shop = _load(SHOP_FILE, dict)
        if not shop:
            return await interaction.followup.send(
                "❌ Žádný shop neexistuje. Nejdřív ho vytvoř přes `/gshop create`.", ephemeral=True
            )
        if shop.get("open"):
            return await interaction.followup.send("Shop je už otevřený.", ephemeral=True)

        shop["open"] = True
        embed = _build_shop_embed(shop, is_open=True)
        view  = ShopView(shop)
        msg   = await interaction.channel.send(embed=embed, view=view)

        # Ulož referenci na zprávu pro pozdější edit/close
        shop["message"] = msg.id
        shop["channel"] = interaction.channel.id
        _save(SHOP_FILE, shop)

        await interaction.followup.send("🏪 Shop otevřen.", ephemeral=True)

    @shop_group.command(name="close", description="Admin: Zavři shop a deaktivuj tlačítka")
    @app_commands.checks.has_permissions(administrator=True)
    async def gshop_close(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        shop = _load(SHOP_FILE, dict)
        if not shop:
            return await interaction.followup.send("❌ Žádný shop neexistuje.", ephemeral=True)
        if not shop.get("open"):
            return await interaction.followup.send("Shop je už zavřený.", ephemeral=True)

        shop["open"] = False
        _save(SHOP_FILE, shop)

        # Uprav původní zprávu — odstraň tlačítka, zešedni embed
        if shop.get("message") and shop.get("channel"):
            try:
                channel = interaction.guild.get_channel(shop["channel"])
                if channel:
                    msg = await channel.fetch_message(shop["message"])
                    await msg.edit(
                        embed=_build_shop_embed(shop, is_open=False),
                        view=None,
                    )
            except discord.NotFound:
                shop["message"] = None
                shop["channel"] = None
                _save(SHOP_FILE, shop)
            except Exception:
                logging.exception("[gshop_close] Nelze aktualizovat živou zprávu")

        await interaction.followup.send("🔒 Shop zavřen.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Economy(bot))