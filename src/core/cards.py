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

# Collections / Sady
COLLECTIONS = {
    "unworthy": {"color": 0x2C2F33, "emoji": "💀", "description": "Nevolaní — padlí a zapomenutí"},
    "worthy":   {"color": 0x99AAB5, "emoji": "⚔️",  "description": "Hrdinové Aurionisu"},
    "queen":    {"color": 0xFF69B4, "emoji": "👑",  "description": "Královna a její dvůr"},
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

SEED_CARDS = [
    {
        "id": 1,
        "name": "Alice Aurelion",
        "description": "Mystická postava z Aurionisu s aurou tajemství.",
        "image": "unworthy_alice_aurelion.png",
        "collection": "unworthy"
    },
    {
        "id": 2,
        "name": "Enel",
        "description": "Kdo ví co za tajemství v sobě skrývá.",
        "image": "unworthy_enel.png",
        "collection": "unworthy"
    }
]

def ensure_cards_data():
    """Při startu doplní chybějící seed karty (upsert podle ID)."""
    cards = load_json(CARDS_DATA)
    existing_ids = {c.get("id") for c in cards}
    added = False
    for seed in SEED_CARDS:
        if seed["id"] not in existing_ids:
            cards.append(seed)
            added = True
    if added:
        save_json(CARDS_DATA, cards)

def ensure_frames_data():
    """Zajistí, aby soubor cards_frames.json existoval a obsahoval alespoň Riddler."""
    frames = load_json(CARDS_FRAMES)
    if not frames:
        # Vytvoř defaultní rámeček
        default_frames = [
            {
                "id": "riddler_frame",
                "name": "Riddler Rámeček",
                "image": "riddler_frame.png",
                "color": "#FF6B9D",
                "rarity_exclusive": None
            }
        ]
        save_json(CARDS_FRAMES, default_frames)

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
                "collection": card_template.get("collection"),
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
            if not image_path:
                await interaction.followup.send("Obrázek karty nenalezen.", ephemeral=True)
                return

            loop = asyncio.get_event_loop()
            image_bytes = await loop.run_in_executor(None, apply_frame_to_card, image_path, selected_frame)
            file = discord.File(image_bytes, filename="card.png")

            rarity = card.get("rarity", "unworthy")
            rarity_data = RARITIES.get(rarity, {})
            collection = card.get("collection")
            coll_data = COLLECTIONS.get(collection, {}) if collection else {}

            owner_id = card.get("owner_id")
            owner_text = f"<@{owner_id}>" if owner_id else "—"

            created_at = card.get("created_at", "")
            try:
                date_text = datetime.fromisoformat(created_at).strftime("%d. %m. %Y") if created_at else "—"
            except Exception:
                date_text = "—"

            embed = discord.Embed(
                title=f"{rarity_data.get('emoji', '⚪')}  {card.get('name')}",
                description=f"*{card.get('description', '')}*",
                color=rarity_data.get("color", 0x808080)
            )

            if collection and coll_data:
                embed.add_field(
                    name="📚 Kolekce",
                    value=f"{coll_data.get('emoji', '')} {collection.capitalize()}",
                    inline=True
                )
            embed.add_field(
                name="✨ Rarita",
                value=f"{rarity_data.get('emoji', '⚪')} {rarity.capitalize()}",
                inline=True
            )
            embed.add_field(name="\u200b", value="\u200b", inline=True)

            embed.add_field(name="👤 Vlastník", value=owner_text, inline=True)
            embed.add_field(name="🖼️ Rámeček", value=selected_frame or "Žádný", inline=True)
            embed.add_field(name="📅 Vytisknuto", value=date_text, inline=True)

            embed.add_field(name="🆔 Unikátní ID", value=f"`{unique_id}`", inline=False)

            footer = "⚜️ Aurionis"
            if coll_data.get("description"):
                footer += f"  •  {coll_data['description']}"
            embed.set_footer(text=footer)
            embed.set_image(url="attachment://card.png")

            await interaction.followup.send(embed=embed, file=file)
        except Exception as e:
            await interaction.followup.send(f"❌ Chyba: {str(e)}", ephemeral=True)

    @cards_group.command(name="upgrade", description="Nasadit rámeček na kartu")
    @app_commands.describe(unique_id="ID karty", frame="ID rámečku")
    async def upgrade_frame(self, interaction: discord.Interaction, unique_id: str, frame: str):
        """Aplikuje rámeček na kartu a odstraní ho z inventáře."""
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

        # Nasaď rámeček na kartu
        card["frame"] = frame
        inventory[unique_id] = card
        save_json(CARDS_INVENTORY, inventory)

        # Odstraň rámeček z inventáře (byl "spotřebován")
        frames_inv[uid] = [f for f in frames_inv[uid] if f.get("id") != frame]
        save_json(FRAMES_INVENTORY, frames_inv)

        frame_data = get_frame_by_id(frame)
        frame_name = frame_data.get("name") if frame_data else frame
        await interaction.response.send_message(
            f"✅ Rámeček {frame_name} nasazen na {unique_id} (spotřebován)", 
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

    @cards_group.command(name="info", description="Vítej v Aurionisu — statistiky karet")
    async def cards_info(self, interaction: discord.Interaction):
        """Uvítací embed se statistikami kartového systému."""
        cards = load_json(CARDS_DATA)
        inventory = load_json(CARDS_INVENTORY)

        total_printed = len(inventory)
        unique_designs = len(cards)

        rarity_counts = {}
        collection_counts = {}
        for c in inventory.values():
            r = c.get("rarity", "unworthy")
            rarity_counts[r] = rarity_counts.get(r, 0) + 1
            col = c.get("collection", "—")
            collection_counts[col] = collection_counts.get(col, 0) + 1

        embed = discord.Embed(
            title="⚜️  Vítej v Aurionisu!",
            description=(
                "*Sbírej, vyměňuj a obdivuj karty z říše Aurionisu.*\n"
                "*Každá karta je unikátní a nese příběh svého světa.*"
            ),
            color=0xFFD700
        )

        embed.add_field(name="🖨️ Celkem vytisknuto", value=f"**{total_printed}** karet", inline=True)
        embed.add_field(name="🎴 Unikátních vzorů", value=f"**{unique_designs}** karet", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        coll_lines = []
        for cid, cdata in COLLECTIONS.items():
            count = collection_counts.get(cid, 0)
            coll_lines.append(f"{cdata['emoji']} **{cid.capitalize()}** — {count} ks")
        if coll_lines:
            embed.add_field(name="📚 Sady", value="\n".join(coll_lines), inline=True)

        rarity_lines = []
        for rid, rdata in RARITIES.items():
            count = rarity_counts.get(rid, 0)
            rarity_lines.append(f"{rdata['emoji']} **{rid.capitalize()}** — {count} ks")
        embed.add_field(name="✨ Rarity", value="\n".join(rarity_lines), inline=True)

        embed.set_footer(text="⚜️ Aurionis Sběratelský Systém")
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

    @cards_group.command(name="gallery", description="Alba kolekcí — přehled sad a karet")
    @app_commands.describe(collection="Název sady (volitelné) — zobrazí detail kolekce")
    async def gallery(self, interaction: discord.Interaction, collection: str = None):
        """Přehled kolekcí nebo detail jedné sady."""
        cards_db = load_json(CARDS_DATA)
        inventory = load_json(CARDS_INVENTORY)

        if collection:
            collection = collection.lower()
            coll_data = COLLECTIONS.get(collection)
            if not coll_data:
                known = ", ".join(COLLECTIONS.keys())
                await interaction.response.send_message(
                    f"Neznámá kolekce `{collection}`. Dostupné: {known}", ephemeral=True
                )
                return

            # Karty v této kolekci z databáze vzorů
            coll_templates = [c for c in cards_db if c.get("collection") == collection]
            # Vytisknuti instancei v inventory
            coll_instances = [c for c in inventory.values() if c.get("collection") == collection]

            rarity_counts = {}
            for inst in coll_instances:
                r = inst.get("rarity", "unworthy")
                rarity_counts[r] = rarity_counts.get(r, 0) + 1

            embed = discord.Embed(
                title=f"{coll_data['emoji']}  Kolekce: {collection.capitalize()}",
                description=f"*{coll_data['description']}*",
                color=coll_data["color"]
            )

            embed.add_field(name="🎴 Vzorů v sadě", value=f"**{len(coll_templates)}**", inline=True)
            embed.add_field(name="🖨️ Celkem vytisknuto", value=f"**{len(coll_instances)}**", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)

            if rarity_counts:
                rarity_lines = []
                for rid, rdata in RARITIES.items():
                    count = rarity_counts.get(rid, 0)
                    if count:
                        rarity_lines.append(f"{rdata['emoji']} {rid.capitalize()} — {count} ks")
                embed.add_field(name="✨ Rarity v oběhu", value="\n".join(rarity_lines), inline=False)

            if coll_templates:
                for tmpl in coll_templates:
                    tid = tmpl.get("id")
                    copies = sum(1 for inst in coll_instances if inst.get("card_id") == tid)
                    embed.add_field(
                        name=f"#{tid} — {tmpl.get('name')}",
                        value=f"{tmpl.get('description', '—')}\n*{copies} ks v oběhu*",
                        inline=False
                    )
            else:
                embed.add_field(name="Karty", value="Žádné vzory v této kolekci.", inline=False)

            embed.set_footer(text=f"⚜️ Aurionis  •  /cards gallery pro přehled všech sad")
            await interaction.response.send_message(embed=embed)

        else:
            # Přehled všech kolekcí
            embed = discord.Embed(
                title="📚  Galerie Aurionisu",
                description="*Přehled všech kolekcí — jejich obsah a stav v oběhu.*",
                color=0xFFD700
            )

            for cid, cdata in COLLECTIONS.items():
                templates_count = sum(1 for c in cards_db if c.get("collection") == cid)
                printed_count = sum(1 for c in inventory.values() if c.get("collection") == cid)
                embed.add_field(
                    name=f"{cdata['emoji']}  {cid.capitalize()}",
                    value=(
                        f"*{cdata['description']}*\n"
                        f"🎴 Vzorů: **{templates_count}**  ·  🖨️ Vytisknuto: **{printed_count}**\n"
                        f"`/cards gallery {cid}`"
                    ),
                    inline=False
                )

            embed.set_footer(text="⚜️ Aurionis Sběratelský Systém")
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="give_frame", description="[ADMIN] Dát rámeček hráči")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(user="Hráč, kterému chceš dát rámeček", frame_id="ID rámečku")
    async def give_frame(self, interaction: discord.Interaction, user: discord.Member, frame_id: str):
        """Admin příkaz pro přidání rámečku do inventáře hráče."""
        # Zkontroluj jestli rámmeček existuje
        frame = get_frame_by_id(frame_id)
        if not frame:
            await interaction.response.send_message(
                f"Rámeček `{frame_id}` neexistuje.", 
                ephemeral=True
            )
            return

        uid = str(user.id)
        frames_inv = load_json(FRAMES_INVENTORY)
        
        # Vytvoř pole pro uživatele, pokud neexistuje
        if uid not in frames_inv:
            frames_inv[uid] = []
        
        # Zkontroluj, jestli už rámeček nemá
        if any(f.get("id") == frame_id for f in frames_inv[uid]):
            await interaction.response.send_message(
                f"{user.mention} již má rámeček `{frame.get('name')}`.", 
                ephemeral=True
            )
            return
        
        # Přidej rámeček
        frames_inv[uid].append({
            "id": frame_id,
            "name": frame.get("name")
        })
        
        save_json(FRAMES_INVENTORY, frames_inv)
        
        embed = discord.Embed(
            title="✅ Rámeček přidán",
            description=f"{user.mention} nyní vlastní **{frame.get('name')}**",
            color=0x00FF00
        )
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="remove_card", description="[ADMIN] Smazat kartu úplně")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(unique_id="Unikátní ID karty k odstranění")
    async def remove_card(self, interaction: discord.Interaction, unique_id: str):
        """Admin příkaz pro úplné smazání karty z inventáře."""
        inventory = load_json(CARDS_INVENTORY)
        
        if unique_id not in inventory:
            await interaction.response.send_message(
                f"Karta `{unique_id}` neexistuje.", 
                ephemeral=True
            )
            return
        
        card = inventory[unique_id]
        card_name = card.get("name")
        
        # Smaž kartu z inventáře
        del inventory[unique_id]
        save_json(CARDS_INVENTORY, inventory)
        
        embed = discord.Embed(
            title="🗑️ Karta smazána",
            description=f"**{card_name}** (ID: `{unique_id}`) byla úplně odstraněna.",
            color=0xFF0000
        )
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    """Registruje cog do bota."""
    ensure_cards_data()   # Zajistí, že databáze karet existuje
    ensure_frames_data()  # Zajistí, že databáze rámečků existuje
    await bot.add_cog(Cards(bot))
