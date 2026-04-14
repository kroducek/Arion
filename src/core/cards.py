"""Sběratelský systém karet pro ArionBot."""

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
    """Čte JSON soubor."""
    if not os.path.exists(filepath):
        return {} if filepath.endswith("inventory.json") else []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Pokud soubor existuje ale je prázdný, vrátí defaultní hodnotu
            if not data:
                return {} if filepath.endswith("inventory.json") else []
            return data
    except Exception:
        return {} if filepath.endswith("inventory.json") else []

def ensure_cards_data():
    """Zajistí, aby soubor cards_data.json existoval a obsahoval alespoň Alice."""
    cards = load_json(CARDS_DATA)
    if not cards:
        # Vytvoř defaultní kartu
        default_cards = [
            {
                "id": 1,
                "name": "Alice Aurelion",
                "description": "Mystická postava z Aurionisu s aurou tajemství.",
                "image": "unworthy_alice_aurelion.png"
            }
        ]
        save_json(CARDS_DATA, default_cards)

def save_json(filepath, data):
    """Uloží JSON soubor."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def generate_unique_id():
    """Generuje unikátní ID (8 znaků)."""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=8))

def get_card_by_id(card_id):
    """Vrátí data karty podle card_id."""
    cards = load_json(CARDS_DATA)
    for card in cards:
        if card.get("id") == card_id:
            return card
    return None

def get_card_image_path(image_filename: str):
    """Vrátí cestu k obrázku karty podle jména souboru."""
    if not image_filename:
        return None
    path = os.path.join(CARDS_DIR, image_filename)
    if os.path.exists(path):
        return path
    return None

def get_frame_by_id(frame_id):
    """Vrátí data rámečku podle ID."""
    frames = load_json(CARDS_FRAMES)
    for frame in frames:
        if frame.get("id") == frame_id:
            return frame
    return None

class Cards(commands.Cog):
    """Karta se skupinou příkazů."""
    def __init__(self, bot):
        self.bot = bot

    cards_group = app_commands.Group(name="cards", description="Sběratelský systém karet")

    @app_commands.command(name="print", description="[ADMIN] Vytisknout novou kartu")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        card_id="ID karty z databáze",
        rarity="Rarita: unworthy/common/rare/epic/legendary",
        owner="Discord hráč (volitelné)",
        count="Kolik kopií (default: 1)"
    )
    async def print_card(
        self, 
        interaction: discord.Interaction, 
        card_id: int, 
        rarity: str, 
        owner: discord.Member = None, 
        count: int = 1
    ):
        """Admin příkaz pro tisk nové karty."""
        if rarity not in RARITIES:
            await interaction.response.send_message(
                f"Neplatná rarita. Dostupné: {', '.join(RARITIES.keys())}", 
                ephemeral=True
            )
            return

        card_template = get_card_by_id(card_id)
        if not card_template:
            await interaction.response.send_message(
                f"Karta s ID {card_id} neexistuje.", 
                ephemeral=True
            )
            return

        owner_id = str(owner.id) if owner else None
        inventory = load_json(CARDS_INVENTORY)
        created = []

        for _ in range(count):
            unique_id = generate_unique_id()
            while unique_id in inventory:
                unique_id = generate_unique_id()

            card = {
                "card_id": card_id,
                "name": card_template.get("name"),
                "description": card_template.get("description"),
                "image": card_template.get("image"),
                "rarity": rarity,
                "owner_id": owner_id,
                "frame": None,
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
        
        ids_text = ", ".join([f"{uid}" for uid in created])
        embed.add_field(name="Unikátní IDs", value=ids_text, inline=False)
        
        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="inventory", description="Zobrazit své karty")
    async def inventory(self, interaction: discord.Interaction, user: discord.Member = None):
        """Zobrazí inventář hráče."""
        target_user = user or interaction.user
        uid = str(target_user.id)
        
        inventory = load_json(CARDS_INVENTORY)
        user_cards = {cid: card for cid, card in inventory.items() if card.get("owner_id") == uid}

        if not user_cards:
            await interaction.response.send_message(
                f"{target_user.mention} nemá žádné karty.", 
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🎴 Karty — {target_user.display_name}",
            description=f"Celkem: {len(user_cards)} karet",
            color=0xFFA500
        )

        for i, (unique_id, card) in enumerate(list(user_cards.items())[:15]):
            rarity_emoji = RARITIES.get(card.get("rarity", "unworthy"), {}).get("emoji", "⚪")
            frame_text = f"\nRámeček: {card.get('frame')}" if card.get("frame") else ""
            embed.add_field(
                name=f"{i+1}. {card.get('name')}",
                value=f"ID: {unique_id}\nRarita: {card.get('rarity')} {rarity_emoji}{frame_text}",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="show", description="Zobrazit konkrétní kartu")
    @app_commands.describe(unique_id="Unikátní ID karty", frame="Rámeček (volitelný)")
    async def show_card(self, interaction: discord.Interaction, unique_id: str, frame: str = None):
        """Zobrazí konkrétní kartu s obrázkem."""
        inventory = load_json(CARDS_INVENTORY)
        
        if unique_id not in inventory:
            await interaction.response.send_message(
                f"Karta s ID {unique_id} neexistuje.", 
                ephemeral=True
            )
            return

        card = inventory[unique_id]
        owner_id = card.get("owner_id")
        
        if owner_id and owner_id != str(interaction.user.id) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Nemáš přístup k této kartě.", ephemeral=True)
            return

        selected_frame = frame if frame else card.get("frame")
        await interaction.response.defer()

        try:
            image_path = get_card_image_path(card.get("image"))
            if image_path:
                loop = asyncio.get_event_loop()
                image_bytes = await loop.run_in_executor(None, apply_frame_to_card, image_path, selected_frame)
                file = discord.File(image_bytes, filename="card.png")
                
                rarity = card.get("rarity", "unworthy")
                embed = discord.Embed(
                    title=f"🎴 {card.get('name')}",
                    description=f"Rarita: {rarity} {RARITIES.get(rarity, {}).get('emoji', '⚪')}\nID: {unique_id}\n{card.get('description', '')}",
                    color=RARITIES.get(rarity, {}).get("color", 0x808080)
                )
                if selected_frame:
                    embed.add_field(name="Rámeček", value=f"{selected_frame}", inline=True)
                embed.set_image(url="attachment://card.png")
                await interaction.followup.send(embed=embed, file=file)
            else:
                await interaction.followup.send("Obrázek karty nenalezen.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Chyba: {str(e)}", ephemeral=True)

    @cards_group.command(name="upgrade", description="Nasadit rámeček na kartu")
    @app_commands.describe(unique_id="ID karty", frame="ID rámečku")
    async def upgrade_frame(self, interaction: discord.Interaction, unique_id: str, frame: str):
        """Aplikuje rámeček na kartu."""
        uid = str(interaction.user.id)
        inventory = load_json(CARDS_INVENTORY)
        frames_inv = load_json(FRAMES_INVENTORY)

        if unique_id not in inventory:
            await interaction.response.send_message(f"Karta {unique_id} neexistuje.", ephemeral=True)
            return

        card = inventory[unique_id]
        if card.get("owner_id") != uid:
            await interaction.response.send_message("Není to tvá karta.", ephemeral=True)
            return

        if frame not in [f.get("id") for f in frames_inv.get(uid, [])]:
            await interaction.response.send_message(f"Rámeček {frame} nemáš.", ephemeral=True)
            return

        card["frame"] = frame
        inventory[unique_id] = card
        save_json(CARDS_INVENTORY, inventory)

        frame_data = get_frame_by_id(frame)
        frame_name = frame_data.get("name") if frame_data else frame
        await interaction.response.send_message(
            f"✅ Rámeček {frame_name} nasazen na {unique_id}", 
            ephemeral=True
        )

    @cards_group.command(name="frames", description="Dostupné rámečky")
    async def show_frames(self, interaction: discord.Interaction):
        """Zobrazí seznam dostupných rámečků."""
        frames = load_json(CARDS_FRAMES)
        
        if not frames:
            await interaction.response.send_message(
                "Žádné rámečky nejsou v databázi.", 
                ephemeral=True
            )
            return

        embed = discord.Embed(title="📦 Dostupné rámečky", color=0xFF6B9D)

        for frame in frames:
            rarity_text = f" (Vyžaduje: {frame['rarity_exclusive']})" if frame.get('rarity_exclusive') else ""
            embed.add_field(
                name=f"{frame.get('name')}",
                value=f"ID: {frame.get('id')}{rarity_text}",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="list", description="Dostupné karty v databázi")
    async def list_cards(self, interaction: discord.Interaction):
        """Zobrazí seznam všech dostupných karet."""
        cards = load_json(CARDS_DATA)
        
        if not cards:
            await interaction.response.send_message(
                "Žádné karty nejsou v databázi.", 
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🎴 Dostupné karty",
            description="Použij /print <card_id> <rarity> pro vytisknutí",
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
    """Registruje cog do bota."""
    ensure_cards_data()  # Zajistí, že databáze karet existuje
    await bot.add_cog(Cards(bot))
