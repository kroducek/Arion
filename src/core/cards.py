"""
Sběratelský systém karet pro ArionBot
Každá karta má unikátní ID (např. kszehsjr)
Admin vytiskne karty, hráči je vlastní a mohou je vylepšit rámečky.

Admin příkazy:
  /print <card_id> <rarity>  — Vytisknout novou kartu do databáze
  /cards list               — Zobrazit všechny dostupné karty

Hráčské příkazy:
  /cards inventory          — Tvé karty
  /cards show <unique_id>   — Zobrazit konkrétní kartu
  /cards show <unique_id> frame:<frame> — S konkrétním rámečkem
  /cards frames            — Dostupné rámečky
  /cards upgrade <unique_id> <frame>    — Nastavit rámeček kartě (pokud ho máš)
"""

import discord
import os
import random
import string
import json
from datetime import datetime
from discord.ext import commands
from discord import app_commands
import asyncio

from src.utils.paths import CARDS_DIR, CARDS_DATA, CARDS_INVENTORY, CARDS_FRAMES, FRAMES_INVENTORY, FRAMES_DIR
from src.utils.card_image import apply_frame_to_card, get_card_image_path

# Rarities
RARITIES = {
    "unworthy": {"color": 0x808080, "emoji": "⚪"},
    "common": {"color": 0xFFFFFF, "emoji": "🟢"},
    "rare": {"color": 0x0000FF, "emoji": "🔵"},
    "epic": {"color": 0x800080, "emoji": "🟣"},
    "legendary": {"color": 0xFFD700, "emoji": "🟡"}
}

def load_json(filepath):
    if not os.path.exists(filepath):
        return {} if filepath.endswith("inventory.json") else []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {} if filepath.endswith("inventory.json") else []

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def generate_unique_id():
    """Generuje unikátní ID (8 znaků: čísla + malá písmena)"""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=8))

def get_card_by_id(card_id):
    """Vrátí data karty podle card_id (číslo)"""
    cards = load_json(CARDS_DATA)
    for card in cards:
        if card.get("id") == card_id:
            return card
    return None

def get_frame_by_id(frame_id):
    """Vrátí data rámečku podle ID"""
    frames = load_json(CARDS_FRAMES)
    for frame in frames:
        if frame.get("id") == frame_id:
            return frame
    return None

class Cards(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    cards_group = app_commands.Group(name="cards", description="Sběratelský systém karet")

    # ====== ADMIN COMMANDS ======

    @app_commands.command(name="print", description="[ADMIN] Vytisknout novou kartu")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(card_id="ID karty z databáze (číslo)", rarity="Rarita: unworthy/common/rare/epic/legendary", owner="Discord hráč (volitelné)", count="Kolik kopií (default: 1)")
    async def print_card(self, interaction: discord.Interaction, card_id: int, rarity: str, owner: discord.Member = None, count: int = 1):
        # Zkontroluj raritu
        if rarity not in RARITIES:
            await interaction.response.send_message(f"Neplatná rarita. Dostupné: {', '.join(RARITIES.keys())}", ephemeral=True)
            return

        # Zkontroluj card_id
        card_template = get_card_by_id(card_id)
        if not card_template:
            await interaction.response.send_message(f"Karta s ID {card_id} neexistuje.", ephemeral=True)
            return

        # Xác định vlastníka
        owner_id = str(owner.id) if owner else None

        # Vytiskni karty
        inventory = load_json(CARDS_INVENTORY)
        created = []

        for _ in range(count):
            unique_id = generate_unique_id()
            
            # Kontrola duplikátu (velmi vzácné)
            while unique_id in inventory:
                unique_id = generate_unique_id()

            card = {
                "card_id": card_id,
                "name": card_template.get("name"),
                "description": card_template.get("description"),
                "image": card_template.get("image"),
                "rarity": rarity,
                "owner_id": owner_id,
                "frame": None,  # Default bez rámečku
                "created_at": datetime.now().isoformat()
            }
            
            inventory[unique_id] = card
            created.append(unique_id)

        save_json(CARDS_INVENTORY, inventory)

        owner_mention = f"<@{owner_id}>" if owner_id else "—"
        embed = discord.Embed(
            title="✅ Karty vytištěny",
            description=f"**{card_template.get('name')}** × {count}\nRarita: {rarity} {RARITIES[rarity]['emoji']}\nVlastník: {owner_mention}",
            color=RARITIES[rarity]["color"]
        )
        
        # IDs jako field
        ids_text = ", ".join([f"`{uid}`" for uid in created])
        embed.add_field(name="Unikátní IDs", value=ids_text, inline=False)
        
        await interaction.response.send_message(embed=embed)

    # ====== HRÁČSKÉ COMMANDS ======

    @cards_group.command(name="inventory", description="Zobrazit své karty")
    async def inventory(self, interaction: discord.Interaction, user: discord.Member = None):
        target_user = user or interaction.user
        uid = str(target_user.id)
        
        inventory = load_json(CARDS_INVENTORY)
        user_cards = {cid: card for cid, card in inventory.items() if card.get("owner_id") == uid}

        if not user_cards:
            await interaction.response.send_message(f"{target_user.mention} nemá žádné karty.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🎴 Karty — {target_user.display_name}",
            description=f"Celkem: {len(user_cards)} karet",
            color=0xFFA500
        )

        for i, (unique_id, card) in enumerate(list(user_cards.items())[:15]):  # Max 15 na embed
            rarity_emoji = RARITIES.get(card.get("rarity", "unworthy"), {}).get("emoji", "⚪")
            frame_text = f"\nRámeček: `{card.get('frame')}`" if card.get("frame") else ""
            embed.add_field(
                name=f"{i+1}. {card.get('name')}",
                value=f"ID: `{unique_id}`\nRarita: {card.get('rarity')} {rarity_emoji}{frame_text}",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="show", description="Zobrazit konkrétní kartu")
    @app_commands.describe(unique_id="Unikátní ID karty (např. kszehsjr)", frame="Rámeček (volitelný)")
    async def show_card(self, interaction: discord.Interaction, unique_id: str, frame: str = None):
        inventory = load_json(CARDS_INVENTORY)
        
        if unique_id not in inventory:
            await interaction.response.send_message(f"Karta s ID `{unique_id}` neexistuje.", ephemeral=True)
            return

        card = inventory[unique_id]
        owner_id = card.get("owner_id")
        
        # Pokud karta má vlastníka, jen on ji může vidět (nebo admins)
        if owner_id and owner_id != str(interaction.user.id) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Ned máš přístup k této kartě.", ephemeral=True)
            return

        # Určí rámeček
        selected_frame = frame if frame else card.get("frame")

        await interaction.response.defer()

        try:
            image_path = get_card_image_path(card.get("card_id", 1))
            if image_path:
                loop = asyncio.get_event_loop()
                image_bytes = await loop.run_in_executor(None, apply_frame_to_card, image_path, selected_frame or "default")
                file = discord.File(image_bytes, filename="card.png")
                
                rarity = card.get("rarity", "unworthy")
                embed = discord.Embed(
                    title=f"🎴 {card.get('name')}",
                    description=f"Rarita: {rarity} {RARITIES.get(rarity, {}).get('emoji', '⚪')}\nID: `{unique_id}`\n{card.get('description', '')}",
                    color=RARITIES.get(rarity, {}).get("color", 0x808080)
                )
                if selected_frame:
                    embed.add_field(name="Rámeček", value=f"`{selected_frame}`", inline=True)
                embed.set_image(url="attachment://card.png")
                await interaction.followup.send(embed=embed, file=file)
            else:
                await interaction.followup.send(f"Obrázek karty nenalezen.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Chyba: {str(e)}", ephemeral=True)

    @cards_group.command(name="upgrade", description="Nasadit rámeček na kartu")
    @app_commands.describe(unique_id="ID karty", frame="ID rámečku (musíš ho mít)")
    async def upgrade_frame(self, interaction: discord.Interaction, unique_id: str, frame: str):
        uid = str(interaction.user.id)
        inventory = load_json(CARDS_INVENTORY)
        frames_inv = load_json(FRAMES_INVENTORY)

        # Zkontroluj kartu
        if unique_id not in inventory:
            await interaction.response.send_message(f"Karta `{unique_id}` neexistuje.", ephemeral=True)
            return

        card = inventory[unique_id]
        if card.get("owner_id") != uid:
            await interaction.response.send_message("Není to tvá karta.", ephemeral=True)
            return

        # Zkontroluj rámeček
        if frame not in [f.get("id") for f in frames_inv.get(uid, [])]:
            await interaction.response.send_message(f"Rámeček `{frame}` nemáš.", ephemeral=True)
            return

        # Nastav rámeček
        card["frame"] = frame
        inventory[unique_id] = card
        save_json(CARDS_INVENTORY, inventory)

        frame_data = get_frame_by_id(frame)
        frame_name = frame_data.get("name") if frame_data else frame
        await interaction.response.send_message(f"✅ Rámeček `{frame_name}` nasazen na `{unique_id}`", ephemeral=True)

    @cards_group.command(name="frames", description="Dostupné rámečky")
    async def show_frames(self, interaction: discord.Interaction):
        frames = load_json(CARDS_FRAMES)
        
        if not frames:
            await interaction.response.send_message("Žádné rámečky nejsou v databázi.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📦 Dostupné rámečky",
            color=0xFF6B9D
        )

        for frame in frames:
            rarity_text = f" (Vyžaduje: {frame['rarity_exclusive']})" if frame.get('rarity_exclusive') else ""
            embed.add_field(
                name=f"{frame.get('name')}",
                value=f"ID: `{frame.get('id')}`{rarity_text}",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="list", description="Dostupné karty v databázi")
    async def list_cards(self, interaction: discord.Interaction):
        cards = load_json(CARDS_DATA)
        
        if not cards:
            await interaction.response.send_message("Žádné karty nejsou v databázi.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎴 Dostupné karty",
            description="Použij `/print <card_id> <rarity>` pro vytisknutí",
            color=0xFFA500
        )

        for card in cards:
            embed.add_field(
                name=f"#{card.get('id')} — {card.get('name')}",
                value=f"{card.get('description')}",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Cards(bot))"""
Sběratelský systém karet pro ArionBot
Hráči sbírají karty postav s různými raritami a mohou je modifikovat rámečky.

Příkazy:
  /cards collect       — Získat náhodnou kartu (poplatek 10 zlatých)
  /cards inventory     — Zobrazit své karty
  /cards show <id> frame:<frame>   — Zobrazit kartu s rámečkem
  /cards frames        — Zobrazit dostupné rámečky
  /cards customize <id> <frame>    — Změnit rámeček karty
"""

import discord
import os
import random
import json
from discord.ext import commands
from discord import app_commands
import asyncio

from src.utils.paths import ECONOMY as ECONOMY_PATH, CARDS_DIR, CARDS_DATA, CARDS_INVENTORY, CARDS_FRAMES, FRAMES_INVENTORY, FRAMES_DIR
from src.utils.card_image import apply_frame_to_card, get_card_image_path

COLLECT_COST = 10
GOLD_EMOJI = "<:goldcoin:1490171741237018795>"

# Rarities
RARITIES = {
    "unworthy": {"color": 0x808080, "chance": 50, "emoji": "⚪"},
    "common": {"color": 0xFFFFFF, "chance": 30, "emoji": "🟢"},
    "rare": {"color": 0x0000FF, "chance": 15, "emoji": "🔵"},
    "epic": {"color": 0x800080, "chance": 4, "emoji": "🟣"},
    "legendary": {"color": 0xFFD700, "chance": 1, "emoji": "🟡"}
}

def load_eco():
    if not os.path.exists(ECONOMY_PATH):
        return {}
    try:
        with open(ECONOMY_PATH, "r", encoding="utf-8") as f:
            c = f.read().strip()
            return json.loads(c) if c else {}
    except Exception:
        return {}

def save_eco(data):
    with open(ECONOMY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def deduct(uid, amount):
    data = load_eco()
    key = str(uid)
    if data.get(key, 0) < amount:
        return False
    data[key] -= amount
    save_eco(data)
    return True

def balance(uid):
    return load_eco().get(str(uid), 0)

def load_cards_data():
    if not os.path.exists(CARDS_DATA):
        return []
    try:
        with open(CARDS_DATA, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def load_inventory():
    if not os.path.exists(CARDS_INVENTORY):
        return {}
    try:
        with open(CARDS_INVENTORY, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_inventory(data):
    with open(CARDS_INVENTORY, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def load_frames_inventory():
    if not os.path.exists(FRAMES_INVENTORY):
        return {}
    try:
        with open(FRAMES_INVENTORY, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_frames_inventory(data):
    with open(FRAMES_INVENTORY, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

class Cards(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    cards_group = app_commands.Group(name="cards", description="Sběratelský systém karet")

    @cards_group.command(name="collect", description="Získat náhodnou kartu (10 zlatých)")
    async def collect(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        if not deduct(uid, COLLECT_COST):
            await interaction.response.send_message(f"Nemáš dostatek zlata. Potřebuješ {COLLECT_COST} {GOLD_EMOJI}.", ephemeral=True)
            return

        # Random rarity
        rand = random.randint(1, 100)
        cumulative = 0
        selected_rarity = "unworthy"
        for rarity, data in RARITIES.items():
            cumulative += data["chance"]
            if rand <= cumulative:
                selected_rarity = rarity
                break

        # Random card from data
        cards_data = load_cards_data()
        if not cards_data:
            await interaction.response.send_message("Žádné karty nejsou k dispozici.", ephemeral=True)
            return

        card = random.choice(cards_data).copy()
        card["rarity"] = selected_rarity

        # Add to inventory
        inventory = load_inventory()
        if uid not in inventory:
            inventory[uid] = []
        inventory[uid].append(card)
        save_inventory(inventory)

        embed = discord.Embed(
            title=f"🎴 Získal jsi kartu!",
            description=f"**{card['name']}**\nRarita: {selected_rarity} {RARITIES[selected_rarity]['emoji']}",
            color=RARITIES[selected_rarity]["color"]
        )
        if "image" in card:
            embed.set_image(url=card["image"])

        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="inventory", description="Zobrazit své karty")
    async def inventory(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        inventory = load_inventory()
        user_cards = inventory.get(uid, [])

        if not user_cards:
            await interaction.response.send_message("Nemáš žádné karty.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎴 Tvé karty",
            description=f"Máš {len(user_cards)} karet.",
            color=0xFFA500
        )

        for i, card in enumerate(user_cards[:10]):  # Show first 10
            rarity_emoji = RARITIES.get(card.get("rarity", "unworthy"), {}).get("emoji", "⚪")
            embed.add_field(
                name=f"{i+1}. {card['name']}",
                value=f"Rarita: {card.get('rarity', 'unworthy')} {rarity_emoji}",
                inline=True
            )

        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="show", description="Zobrazit konkrétní kartu s rámečkem")
    @app_commands.describe(card_id="ID karty z inventory (číslo)", frame="ID rámečku (volitelné—zvolí poslední použitý)")
    async def show(self, interaction: discord.Interaction, card_id: int, frame: str = None):
        uid = str(interaction.user.id)
        inventory = load_inventory()
        user_cards = inventory.get(uid, [])

        try:
            card = user_cards[card_id - 1]
        except IndexError:
            await interaction.response.send_message("Neplatné ID karty.", ephemeral=True)
            return

        # Určí který rámeček použít
        if frame:
            selected_frame = frame
        else:
            selected_frame = card.get("frame", "gold_frame")

        # Defer odpověď
        await interaction.response.defer()

        try:
            # Pokud existuje obrázek, aplikuj rámeček
            image_path = get_card_image_path(card.get('id', 1))
            if image_path:
                # Spusť generování v threadu
                loop = asyncio.get_event_loop()
                image_bytes = await loop.run_in_executor(None, apply_frame_to_card, image_path, selected_frame)
                file = discord.File(image_bytes, filename="card.png")
                
                embed = discord.Embed(
                    title=f"🎴 {card['name']}",
                    description=f"Rarita: {card.get('rarity', 'unworthy')} {RARITIES.get(card.get('rarity', 'unworthy'), {}).get('emoji', '⚪')}\nRámeček: `{selected_frame}`\n{card.get('description', '')}",
                    color=RARITIES.get(card.get("rarity", "unworthy"), {}).get("color", 0x808080)
                )
                embed.set_image(url="attachment://card.png")
                await interaction.followup.send(embed=embed, file=file)
            else:
                # Fallback bez obrázku
                embed = discord.Embed(
                    title=f"🎴 {card['name']}",
                    description=f"Rarita: {card.get('rarity', 'unworthy')} {RARITIES.get(card.get('rarity', 'unworthy'), {}).get('emoji', '⚪')}\n{card.get('description', '')}",
                    color=RARITIES.get(card.get("rarity", "unworthy"), {}).get("color", 0x808080)
                )
                await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"❌ Chyba při generování karty: {str(e)}", ephemeral=True)

    @cards_group.command(name="customize", description="Změnit rámeček tvé karty")
    @app_commands.describe(card_id="ID karty z inventory", frame="ID nového rámečku")
    async def customize(self, interaction: discord.Interaction, card_id: int, frame: str):
        uid = str(interaction.user.id)
        inventory = load_inventory()
        user_cards = inventory.get(uid, [])

        try:
            card = user_cards[card_id - 1]
        except IndexError:
            await interaction.response.send_message("Neplatné ID karty.", ephemeral=True)
            return

        # Ulož nový rámeček
        if "frame" not in card:
            card["frame"] = "gold_frame"
        card["frame"] = frame
        
        user_cards[card_id - 1] = card
        inventory[uid] = user_cards
        save_inventory(inventory)

        await interaction.response.send_message(f"✅ Rámeček karty '{card['name']}' změněn na `{frame}`", ephemeral=True)

    @cards_group.command(name="frames", description="Zobrazit dostupné rámečky")
    async def frames(self, interaction: discord.Interaction):
        from src.utils.card_image import load_json, FRAMES_FILE
        frames_list = load_json(FRAMES_FILE)
        
        if not frames_list:
            await interaction.response.send_message("Žádné rámečky nejsou k dispozici.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🎴 Dostupné rámečky",
            description="Použij: `/cards show <id> frame:<frame_id>`",
            color=0xFFD700
        )
        
        for frame in frames_list:
            rarity_text = f" (Vyžaduje: {frame['rarity_exclusive']})" if frame['rarity_exclusive'] else ""
            embed.add_field(
                name=f"{frame['name']}",
                value=f"ID: `{frame['id']}`{rarity_text}",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)

    frames_group = app_commands.Group(name="frames", description="Sbírka rámečků")

    @frames_group.command(name="collect", description="Získat náhodný rámeček (10 zlatých)")
    async def collect_frame(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        if not deduct(uid, COLLECT_COST):
            await interaction.response.send_message(f"Nemáš dostatek zlata. Potřebuješ {COLLECT_COST} {GOLD_EMOJI}.", ephemeral=True)
            return

        # Načti dostupné rámečky
        frames_data = load_json(CARDS_FRAMES)
        if not frames_data:
            await interaction.response.send_message("Žádné rámečky nejsou k dispozici.", ephemeral=True)
            return

        # Vyber náhodný rámeček
        frame = random.choice(frames_data)
        
        # Přidej do inventáře
        inventory = load_frames_inventory()
        if uid not in inventory:
            inventory[uid] = []
        
        # Zkontroluj duplikáty
        if frame["id"] not in [f["id"] if isinstance(f, dict) else f for f in inventory[uid]]:
            inventory[uid].append(frame)
            save_frames_inventory(inventory)
            
            embed = discord.Embed(
                title=f"📦 Získal jsi rámeček!",
                description=f"**{frame['name']}**",
                color=0xFF6B9D
            )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(f"Už máš rámeček `{frame['name']}`.", ephemeral=True)

    @frames_group.command(name="inventory", description="Zobrazit své rámečky")
    async def frames_inventory(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        inventory = load_frames_inventory()
        user_frames = inventory.get(uid, [])

        if not user_frames:
            await interaction.response.send_message("Nemáš žádné rámečky.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📦 Tvé rámečky",
            description=f"Máš {len(user_frames)} rámečků.",
            color=0xFF6B9D
        )

        for i, frame in enumerate(user_frames[:15]):
            frame_name = frame.get("name", "—") if isinstance(frame, dict) else "—"
            frame_id = frame.get("id", f"frame_{i}") if isinstance(frame, dict) else frame
            embed.add_field(
                name=f"{i+1}. {frame_name}",
                value=f"ID: `{frame_id}`",
                inline=True
            )

        await interaction.response.send_message(embed=embed)

def load_json(filepath):
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

async def setup(bot):
    await bot.add_cog(Cards(bot))