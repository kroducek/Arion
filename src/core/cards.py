"""
Sběratelský systém karet pro ArionBot
Hráči sbírají karty postav s různými raritami a mohou je modifikovat rámečky a pozadími.

Příkazy:
  /cards collect       — Získat náhodnou kartu (poplatek 10 zlatých)
  /cards inventory     — Zobrazit své karty
  /cards show <id>     — Zobrazit konkrétní kartu
  /cards customize <id> frame:<frame> bg:<bg> — Modifikovat kartu
"""

import discord
import os
import random
import json
from discord.ext import commands
from discord import app_commands

from src.utils.paths import ECONOMY as ECONOMY_PATH, CARDS_DIR, CARDS_DATA, CARDS_INVENTORY

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

    @cards_group.command(name="show", description="Zobrazit konkrétní kartu")
    @app_commands.describe(card_id="ID karty z inventory (číslo)")
    async def show(self, interaction: discord.Interaction, card_id: int):
        uid = str(interaction.user.id)
        inventory = load_inventory()
        user_cards = inventory.get(uid, [])

        try:
            card = user_cards[card_id - 1]
        except IndexError:
            await interaction.response.send_message("Neplatné ID karty.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🎴 {card['name']}",
            description=f"Rarita: {card.get('rarity', 'unworthy')} {RARITIES.get(card.get('rarity', 'unworthy'), {}).get('emoji', '⚪')}\n{card.get('description', '')}",
            color=RARITIES.get(card.get("rarity", "unworthy"), {}).get("color", 0x808080)
        )
        if "image" in card:
            embed.set_image(url=card["image"])

        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="customize", description="Modifikovat kartu rámečkem a pozadím")
    @app_commands.describe(card_id="ID karty z inventory", frame="Rámeček (zatím placeholder)", bg="Pozadí (zatím placeholder)")
    async def customize(self, interaction: discord.Interaction, card_id: int, frame: str, bg: str):
        uid = str(interaction.user.id)
        inventory = load_inventory()
        user_cards = inventory.get(uid, [])

        try:
            card = user_cards[card_id - 1]
        except IndexError:
            await interaction.response.send_message("Neplatné ID karty.", ephemeral=True)
            return

        # Placeholder - implement image generation
        await interaction.response.send_message(f"Customization karty '{card['name']}' s frame '{frame}' a bg '{bg}' - zatím neimplementováno.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Cards(bot))