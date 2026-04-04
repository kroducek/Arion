import discord
from discord import app_commands
from discord.ext import commands
import json
import logging
import os

from src.utils.paths import ECONOMY as ECONOMY_FILE, SHOPS as SHOPS_FILE, PROFILES as PROFILES_FILE
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