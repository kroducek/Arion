"""Sběratelský systém karet pro ArionBot."""

import discord
import os
import random
import string
from datetime import datetime
from discord.ext import commands
from discord import app_commands
import asyncio

from src.utils.paths import CARDS_DIR, CARDS_DATA, CARDS_INVENTORY, CARDS_FRAMES, FRAMES_INVENTORY, FRAMES_DIR, data as _data
from src.utils.card_image import apply_frame_to_card
from src.utils.json_utils import load_json, save_json
from src.utils.embeds import create_error_embed

CARDS_WORK = _data("cards_work.json")

# Rarities
RARITIES = {
    "unworthy": {"color": 0x808080, "emoji": "⚪"},
    "common": {"color": 0xFFFFFF, "emoji": "🟢"},
    "rare": {"color": 0x0000FF, "emoji": "🔵"},
    "epic": {"color": 0x800080, "emoji": "🟣"},
    "legendary": {"color": 0xFFD700, "emoji": "🟡"}
}

# Qualities (Kvalita karet)
QUALITIES = {
    "shiny": {"name": "Shiny", "emoji": "✨", "color": 0xFFD700},
    "gold": {"name": "Gold", "emoji": "🥇", "color": 0xFFB142},
    "normal": {"name": "Normal", "emoji": "⚪", "color": 0x95A5A6},
    "damaged": {"name": "Damaged", "emoji": "💔", "color": 0x8B0000}
}

# Expedice
EXPEDITIONS = {
    "hlidka": {"name": "Hlídka ve městě", "reward": 2, "hours": 8, "emoji": "🛡️"},
    "lov": {"name": "Lov monster", "reward": 5, "hours": 24, "emoji": "🐺"},
    "gilda": {"name": "Úkol pro gildu", "reward": 10, "hours": 48, "emoji": "📜"}
}

# Collections / Sady
COLLECTIONS = {
    "unworthy": {"color": 0x2C2F33, "emoji": "💀", "description": "Nevolaní — padlí a zapomenutí"},
    "worthy":   {"color": 0x99AAB5, "emoji": "⚔️",  "description": "Hrdinové Aurionisu"},
    "queen":    {"color": 0xFF69B4, "emoji": "👑",  "description": "Královna a její dvůr"},
    "chosen":   {"color": 0xE74C3C, "emoji": "🔥",  "description": "Vyvolení — ti, jenž nesou osud"}
}

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
    },
    {
        "id": 3,
        "name": "Kaiser Vexx",
        "description": "Kdo ví co za tajemství v sobě skrývá.",
        "image": "unworthy_kaiser_vexx.png",
        "collection": "unworthy"
    },
    {
        "id": 4,
        "name": "Nyx",
        "description": "Vyvolená postava, která promlouvá skrze stíny.",
        "image": "chosen_one_nyx.png",
        "collection": "chosen"
    },
    {
        "id": 5,
        "name": "Darrin",
        "description": "Hrdina nesoucí břímě vyvoleného.",
        "image": "chosen_one_darrin.png",
        "collection": "chosen"
    }
]

def ensure_cards_data():
    """Při startu doplní chybějící seed karty (upsert podle ID)."""
    cards = load_json(CARDS_DATA, default=[])
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
    frames = load_json(CARDS_FRAMES, default=[])
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

def generate_unique_id():
    """Generuje unikátní ID (8 znaků)."""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=8))

def get_card_by_id(card_id):
    """Vrátí data karty podle card_id."""
    cards = load_json(CARDS_DATA, default=[])
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
    frames = load_json(CARDS_FRAMES, default=[])
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
        
        # Zjisti nejvyšší existující print number pro tuto kartu
        max_print = 0
        for c in inventory.values():
            if c.get("card_id") == card_id:
                p = c.get("print_number", 0)
                if p > max_print:
                    max_print = p

        for i in range(count):
            unique_id = generate_unique_id()
            while unique_id in inventory:
                unique_id = generate_unique_id()

            # Výběr kvality
            q_roll = random.random()
            if q_roll < 0.05: quality = "shiny"
            elif q_roll < 0.20: quality = "gold"
            elif q_roll < 0.70: quality = "normal"
            else: quality = "damaged"

            max_print += 1
            print_number = max_print

            card = {
                "card_id": card_id,
                "name": card_template.get("name"),
                "description": card_template.get("description"),
                "image": card_template.get("image"),
                "collection": card_template.get("collection"),
                "rarity": rarity,
                "quality": quality,
                "print_number": print_number,
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
            qual = card.get("quality", "normal")
            qual_data = QUALITIES.get(qual, QUALITIES["normal"])
            qual_text = f"{qual_data['emoji']} {qual_data['name']}"
            
            print_num = card.get("print_number", "?")
            frame_text = f"\nRámeček: {card.get('frame')}" if card.get("frame") else ""
            embed.add_field(
                name=f"{i+1}. {card.get('name')} (Print #{print_num})",
                value=f"ID: `{unique_id}`\nRarita: {card.get('rarity').capitalize()} {rarity_emoji}  ·  Kvalita: {qual_text}{frame_text}",
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
            await interaction.response.send_message(embed=create_error_embed("❌ Přístup odepřen", "Tato karta ti nepatří."), ephemeral=True)
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
            
            qual = card.get("quality", "normal")
            qual_data = QUALITIES.get(qual, QUALITIES["normal"])
            embed.add_field(
                name="💎 Kvalita",
                value=f"{qual_data['emoji']} {qual_data['name']}",
                inline=True
            )
            
            print_num = card.get("print_number", "?")
            embed.add_field(name="🖨️ Tisk", value=f"**#{print_num}**", inline=True)

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
            await interaction.response.send_message(embed=create_error_embed("❌ Karta nenalezena", f"ID `{unique_id}` neexistuje."), ephemeral=True)
            return

        card = inventory[unique_id]
        if card.get("owner_id") != uid:
            await interaction.response.send_message(embed=create_error_embed("❌ Přístup odepřen", "Tato karta ti nepatří."), ephemeral=True)
            return

        if frame not in [f.get("id") for f in frames_inv.get(uid, [])]:
            await interaction.response.send_message(embed=create_error_embed("❌ Rámeček nenalezen", f"Rámeček `{frame}` nemáš v inventáři."), ephemeral=True)
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
        frames = load_json(CARDS_FRAMES, default=[])
        
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
        cards = load_json(CARDS_DATA, default=[])
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
        cards = load_json(CARDS_DATA, default=[])
        
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
        cards_db = load_json(CARDS_DATA, default=[])
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

    @cards_group.command(name="set_profile", description="Nastaví vybranou kartu jako reprezentativní na tvém RPG profilu")
    @app_commands.describe(unique_id="Unikátní ID karty")
    async def set_profile_card(self, interaction: discord.Interaction, unique_id: str):
        """Nastaví profilovou kartu."""
        uid = str(interaction.user.id)
        inventory = load_json(CARDS_INVENTORY)
        
        if unique_id not in inventory:
            await interaction.response.send_message(f"Karta s ID `{unique_id}` neexistuje.", ephemeral=True)
            return
            
        card = inventory[unique_id]
        if card.get("owner_id") != uid:
            await interaction.response.send_message("Tato karta ti nepatří.", ephemeral=True)
            return
            
        from src.logic.profile import _load_profiles as p_load, _save_profiles as p_save
        profiles = p_load()
        if uid not in profiles:
            profiles[uid] = {}
            
        profiles[uid]["active_card_id"] = unique_id
        p_save(profiles)
        
        await interaction.response.send_message(f"✅ Karta **{card.get('name')}** (Print #{card.get('print_number', '?')}) byla nastavena jako tvá profilová karta!", ephemeral=True)

    @cards_group.command(name="burn", description="Spálit kartu a získat Hvězdný prach")
    @app_commands.describe(unique_id="Unikátní ID karty")
    async def burn_card(self, interaction: discord.Interaction, unique_id: str):
        """Spálí kartu hráče a přidá mu Hvězdný prach do inventáře."""
        uid = str(interaction.user.id)
        inventory = load_json(CARDS_INVENTORY)
        
        if unique_id not in inventory:
            await interaction.response.send_message(
                f"Karta s ID `{unique_id}` neexistuje.", 
                ephemeral=True
            )
            return
            
        card = inventory[unique_id]
        if card.get("owner_id") != uid:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Přístup odepřen", "Tato karta ti nepatří."), 
                ephemeral=True
            )
            return

        works = load_json(CARDS_WORK, default={})
        user_work = works.get(uid)
        if user_work and unique_id in user_work.get("cards", []):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nelze spálit", "Karta je momentálně na výpravě! Nejprve si vyzvedni odměnu."), 
                ephemeral=True
            )
            return

        # Odstranění z profilu, pokud je to aktivní karta
        from src.logic.profile import _load_profiles as p_load, _save_profiles as p_save
        profiles = p_load()
        if uid in profiles and profiles[uid].get("active_card_id") == unique_id:
            profiles[uid]["active_card_id"] = None
            p_save(profiles)

        rarity = card.get("rarity", "unworthy")
        dust_amounts = {
            "unworthy": 1,
            "common": 2,
            "rare": 5,
            "epic": 15,
            "legendary": 50
        }
        base_dust = dust_amounts.get(rarity, 1)
        
        qual = card.get("quality", "normal")
        qual_mults = {
            "shiny": 2.0,
            "gold": 1.5,
            "normal": 1.0,
            "damaged": 0.5
        }
        mult = qual_mults.get(qual, 1.0)
        
        total_dust = max(1, int(base_dust * mult))
        card_name = card.get("name")
        
        # Přidání Hvězdného prachu do inventáře
        from src.logic.inventory import _load_profiles, _save_profiles, _ensure_inv_fields, _find_inv_entry
        inv_profiles = _load_profiles()
        profile = inv_profiles.get(uid)
        if not profile:
            profile = {"xp": 0, "level": 1, "balance": 0, "bank": 0}
        profile = _ensure_inv_fields(profile)
        
        entry = _find_inv_entry(profile["inventory"], "Hvězdný prach")
        if entry and entry["type"] == "free":
            entry["qty"] = entry.get("qty", 1) + total_dust
        else:
            profile["inventory"].append({"type": "free", "name": "Hvězdný prach", "qty": total_dust})
            
        inv_profiles[uid] = profile
        _save_profiles(inv_profiles)
        
        # Smaž kartu
        del inventory[unique_id]
        save_json(CARDS_INVENTORY, inventory)
        
        embed = discord.Embed(
            title="🔥 Karta spálena",
            description=f"Spálil jsi **{card_name}** (ID: `{unique_id}`).\nDuše karty se rozpadla na **{total_dust}x Hvězdný prach**.",
            color=0xFF8C00
        )
        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="work_send", description="Vyšle až 3 karty na výpravu za zlatem")
    @app_commands.describe(
        vyprava="Typ výpravy",
        card1="ID první karty",
        card2="ID druhé karty (volitelné)",
        card3="ID třetí karty (volitelné)"
    )
    @app_commands.choices(vyprava=[
        app_commands.Choice(name="Hlídka ve městě (8h / +2 Zlaté)", value="hlidka"),
        app_commands.Choice(name="Lov monster (24h / +5 Zlatých)", value="lov"),
        app_commands.Choice(name="Úkol pro gildu (48h / +10 Zlatých)", value="gilda")
    ])
    async def work_send(self, interaction: discord.Interaction, vyprava: str, card1: str, card2: str = None, card3: str = None):
        uid = str(interaction.user.id)
        works = load_json(CARDS_WORK, default={})
        
        if uid in works:
            await interaction.response.send_message("Již máš aktivní výpravu! Zkontroluj ji přes `/cards work_status`.", ephemeral=True)
            return
            
        card_ids = [c for c in [card1, card2, card3] if c]
        if len(set(card_ids)) != len(card_ids):
            await interaction.response.send_message("Nemůžeš poslat stejnou kartu víckrát!", ephemeral=True)
            return
            
        inventory = load_json(CARDS_INVENTORY)
        for cid in card_ids:
            if cid not in inventory or inventory[cid].get("owner_id") != uid:
                await interaction.response.send_message(f"Karta s ID `{cid}` ti nepatří nebo neexistuje.", ephemeral=True)
                return
                
        exp = EXPEDITIONS.get(vyprava)
        if not exp:
            return
            
        from datetime import datetime, timedelta
        now = datetime.now()
        end_time = now + timedelta(hours=exp["hours"])
        
        works[uid] = {
            "type": vyprava,
            "cards": card_ids,
            "start_time": now.isoformat(),
            "end_time": end_time.isoformat()
        }
        save_json(CARDS_WORK, works)
        
        embed = discord.Embed(
            title=f"{exp['emoji']} Výprava zahájena: {exp['name']}",
            description=f"Vyslal jsi **{len(card_ids)}** karet na výpravu.\nNávrat: <t:{int(end_time.timestamp())}:R>",
            color=0x3498db
        )
        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="work_status", description="Stav tvé aktuální výpravy")
    async def work_status(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        works = load_json(CARDS_WORK, default={})
        
        if uid not in works:
            await interaction.response.send_message("Nemáš žádnou aktivní výpravu. Použij `/cards work_send`.", ephemeral=True)
            return
            
        work = works[uid]
        exp = EXPEDITIONS.get(work["type"])
        from datetime import datetime
        end_time = datetime.fromisoformat(work["end_time"])
        
        embed = discord.Embed(
            title=f"{exp['emoji']} Probíhá výprava: {exp['name']}",
            description=f"Počet karet: **{len(work['cards'])}**\nZisk na kartu: **{exp['reward']}** zlaťáků\n"
                        f"Návrat: <t:{int(end_time.timestamp())}:R>",
            color=0x3498db
        )
        if datetime.now() >= end_time:
            embed.color = 0x2ecc71
            embed.description += "\n\n✅ **Výprava skončila!** Použij `/cards work_claim` pro zisk odměny."
            
        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="work_claim", description="Vyzvednout odměnu z dokončené výpravy")
    async def work_claim(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        works = load_json(CARDS_WORK, default={})
        
        if uid not in works:
            await interaction.response.send_message("Nemáš žádnou aktivní výpravu.", ephemeral=True)
            return
            
        work = works[uid]
        from datetime import datetime
        end_time = datetime.fromisoformat(work["end_time"])
        
        if datetime.now() < end_time:
            await interaction.response.send_message(f"Výprava ještě neskončila! Návrat: <t:{int(end_time.timestamp())}:R>", ephemeral=True)
            return
            
        exp = EXPEDITIONS.get(work["type"])
        reward = exp["reward"] * len(work["cards"])
        
        # Add to economy
        from src.logic.economy import load_economy, save_economy
        eco = load_economy()
        eco[uid] = eco.get(uid, 0) + reward
        save_economy(eco)
        
        del works[uid]
        save_json(CARDS_WORK, works)
        
        embed = discord.Embed(
            title="💰 Výprava dokončena",
            description=f"Tvé karty se v pořádku vrátily z **{exp['name']}**.\n\nZískáváš **{reward} zlaťáků**!",
            color=0xFFD700
        )
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    """Registruje cog do bota."""
    ensure_cards_data()   # Zajistí, že databáze karet existuje
    ensure_frames_data()  # Zajistí, že databáze rámečků existuje
    await bot.add_cog(Cards(bot))
