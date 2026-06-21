"""Sběratelský systém karet pro ArionBot."""

import discord
import os
import random
import string
from datetime import datetime, timedelta
from discord.ext import commands
from discord import app_commands
import asyncio

from src.utils.paths import CARDS_DIR, CARDS_DATA, CARDS_INVENTORY, CARDS_FRAMES, FRAMES_INVENTORY, data as _data
from src.utils.card_image import apply_frame_to_card
from src.utils.json_utils import load_json, save_json
from src.utils.embeds import create_error_embed
from src.logic.profile import load_data as profile_load, save_data as profile_save
from src.logic.inventory import _load_profiles as inv_load, _save_profiles as inv_save
from src.logic.economy import _load_economy as load_economy, _save_economy as save_economy, add_balance

CARDS_WORK = _data("cards_work.json")

# ---------------------------------------------------------------------------
# Konstanty
# ---------------------------------------------------------------------------

RARITIES = {
    "uncommon":  {"color": 0x808080, "emoji": "⚪"},
    "common":    {"color": 0xFFFFFF, "emoji": "🟢"},
    "rare":      {"color": 0x0000FF, "emoji": "🔵"},
    "epic":      {"color": 0x800080, "emoji": "🟣"},
    "legendary": {"color": 0xFFD700, "emoji": "🟡"},
}

QUALITIES = {
    "shiny":   {"name": "Shiny",   "emoji": "✨", "color": 0xFFD700},
    "gold":    {"name": "Gold",    "emoji": "🥇", "color": 0xFFB142},
    "normal":  {"name": "Normal",  "emoji": "⚪", "color": 0x95A5A6},
    "damaged": {"name": "Damaged", "emoji": "💔", "color": 0x8B0000},
}

# Hodnoty Hvězdného prachu — sdílené mezi /burn a /info
DUST_VALUES = {
    "uncommon":  1,
    "common":    2,
    "rare":      5,
    "epic":     15,
    "legendary": 50,
}

QUALITY_MULTIPLIERS = {
    "shiny":   2.0,
    "gold":    1.5,
    "normal":  1.0,
    "damaged": 0.5,
}

EXPEDITIONS = {
    "hlidka": {"name": "Hlídka ve městě",      "reward":  5, "hours":  6, "emoji": "🛡️",  "description": "Střežení městských bran"},
    "tabor":  {"name": "Táborový kemp",       "reward":  8, "hours": 12, "emoji": "🏕️", "description": "Řídící tábor v pustině"},
    "lov":    {"name": "Lov monster",         "reward": 12, "hours": 20, "emoji": "🐺", "description": "Hon na nebezpečné bestie"},
    "gilda":  {"name": "Úkol pro gildu",      "reward": 20, "hours": 36, "emoji": "📜", "description": "Speciální úkol pro gildu"},
    "bitva":  {"name": "Velká bitva",         "reward": 35, "hours": 48, "emoji": "⚔️",  "description": "Cesta na válečné bojiště — vysoké riziko!"},
}

COLLECTIONS = {
    "unworthy": {"color": 0x2C2F33, "emoji": "💀", "description": "Nevolaní — padlí a zapomenutí"},
    "worthy":   {"color": 0x99AAB5, "emoji": "⚔️",  "description": "Hrdinové Aurionisu"},
    "queen":    {"color": 0xFF69B4, "emoji": "👑",  "description": "Královna a její dvůr"},
    "chosen":   {"color": 0xE74C3C, "emoji": "🔥",  "description": "Vyvolení — ti, jenž nesou osud"},
}

SEED_CARDS = [
    {"id": 1, "name": "Alice Aurelion", "description": "Mystická postava z Aurionisu s aurou tajemství.",    "image": "unworthy_alice_aurelion.png", "collection": "unworthy"},
    {"id": 2, "name": "Enel",           "description": "Kdo ví co za tajemství v sobě skrývá.",              "image": "unworthy_enel.png",           "collection": "unworthy"},
    {"id": 3, "name": "Kaiser Vexx",    "description": "Kdo ví co za tajemství v sobě skrývá.",              "image": "unworthy_kaiser_vexx.png",    "collection": "unworthy"},
    {"id": 4, "name": "Nyx",            "description": "Vyvolená postava, která promlouvá skrze stíny.",     "image": "chosen_one_nyx.png",          "collection": "chosen"},
    {"id": 5, "name": "Darrin",         "description": "Hrdina nesoucí břímě vyvoleného.",                   "image": "chosen_one_darrin.png",       "collection": "chosen"},
]

# ---------------------------------------------------------------------------
# Pomocné funkce
# ---------------------------------------------------------------------------

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
    """Zajistí, aby soubor cards_frames.json existoval a obsahoval alespoň výchozí rámeček."""
    frames = load_json(CARDS_FRAMES, default=[])
    if not frames:
        save_json(CARDS_FRAMES, [
            {
                "id": "riddler_frame",
                "name": "Riddler Rámeček",
                "image": "riddler_frame.png",
                "color": "#FF6B9D",
                "rarity_exclusive": None,
            }
        ])


def generate_unique_id() -> str:
    """Generuje náhodné unikátní ID (8 znaků)."""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=8))


def get_card_by_id(card_id: int):
    """Vrátí šablonu karty podle ID, nebo None."""
    for card in load_json(CARDS_DATA, default=[]):
        if card.get("id") == card_id:
            return card
    return None


def get_card_image_path(image_filename: str):
    """Vrátí absolutní cestu k obrázku karty, nebo None pokud soubor neexistuje."""
    if not image_filename:
        return None
    path = os.path.join(CARDS_DIR, image_filename)
    return path if os.path.exists(path) else None


def get_frame_by_id(frame_id: str):
    """Vrátí data rámečku podle ID, nebo None."""
    for frame in load_json(CARDS_FRAMES, default=[]):
        if frame.get("id") == frame_id:
            return frame
    return None


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Cards(commands.Cog):
    """Sběratelský systém karet."""

    def __init__(self, bot):
        self.bot = bot

    cards_group = app_commands.Group(name="cards", description="Sběratelský systém karet")

    # -----------------------------------------------------------------------
    # Admin příkazy
    # -----------------------------------------------------------------------

    @cards_group.command(name="print", description="[ADMIN] Vytisknout novou kartu")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        card_id="ID karty z databáze",
        rarity="Rarita karty",
        owner="Discord hráč — vlastník (volitelné)",
        count="Kolik kopií vytisknout (výchozí: 1)",
    )
    @app_commands.choices(rarity=[
        app_commands.Choice(name="Uncommon",  value="uncommon"),
        app_commands.Choice(name="Common",    value="common"),
        app_commands.Choice(name="Rare",      value="rare"),
        app_commands.Choice(name="Epic",      value="epic"),
        app_commands.Choice(name="Legendary", value="legendary"),
    ])
    async def print_card(
        self,
        interaction: discord.Interaction,
        card_id: int,
        rarity: str,
        owner: discord.Member = None,
        count: int = 1,
    ):
        """Admin příkaz pro tisk nové karty do inventáře."""
        if not 1 <= count <= 50:
            await interaction.response.send_message("Počet musí být mezi 1 a 50.", ephemeral=True)
            return

        card_template = get_card_by_id(card_id)
        if not card_template:
            await interaction.response.send_message(f"Karta s ID **{card_id}** neexistuje.", ephemeral=True)
            return

        owner_id = str(owner.id) if owner else None
        inventory = load_json(CARDS_INVENTORY, default={})

        max_print = max(
            (c.get("print_number", 0) for c in inventory.values() if c.get("card_id") == card_id),
            default=0,
        )

        created = []
        for _ in range(count):
            unique_id = generate_unique_id()
            while unique_id in inventory:
                unique_id = generate_unique_id()

            q_roll = random.random()
            if q_roll < 0.05:   quality = "shiny"
            elif q_roll < 0.20: quality = "gold"
            elif q_roll < 0.70: quality = "normal"
            else:               quality = "damaged"

            max_print += 1
            inventory[unique_id] = {
                "card_id":      card_id,
                "name":         card_template.get("name"),
                "description":  card_template.get("description"),
                "image":        card_template.get("image"),
                "collection":   card_template.get("collection"),
                "rarity":       rarity,
                "quality":      quality,
                "print_number": max_print,
                "owner_id":     owner_id,
                "frame":        None,
                "created_at":   datetime.now().isoformat(),
            }
            created.append(unique_id)

        save_json(CARDS_INVENTORY, inventory)

        owner_mention = f"<@{owner_id}>" if owner_id else "—"
        embed = discord.Embed(
            title="✅ Karty vytištěny",
            description=(
                f"**{card_template.get('name')}** × {count}\n"
                f"Rarita: {rarity.capitalize()} {RARITIES[rarity]['emoji']}\n"
                f"Vlastník: {owner_mention}"
            ),
            color=RARITIES[rarity]["color"],
        )
        ids_value = ", ".join(created)
        if len(ids_value) > 1000:
            ids_value = ids_value[:1000] + f"\n… a {len(created) - ids_value[:1000].count(',') - 1} dalších"
        embed.add_field(name="🆔 Unikátní IDs", value=ids_value, inline=False)
        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="db_add", description="[ADMIN] Přidat novou kartu do databáze vzorů")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        name="Jméno karty",
        description="Popis karty",
        collection="Kolekce, do které karta patří",
        image="Název souboru obrázku (např. chosen_nyx.png)",
        attachment="Nahraj obrázek přímo z Discordu (uloží se pod zadaným názvem)",
    )
    @app_commands.choices(collection=[
        app_commands.Choice(name="Unworthy — Nevolaní",         value="unworthy"),
        app_commands.Choice(name="Worthy — Hrdinové Aurionisu", value="worthy"),
        app_commands.Choice(name="Queen — Královna a dvůr",     value="queen"),
        app_commands.Choice(name="Chosen — Vyvolení",           value="chosen"),
    ])
    async def db_add(
        self,
        interaction: discord.Interaction,
        name: str,
        description: str,
        collection: str,
        image: str,
        attachment: discord.Attachment = None,
    ):
        """[ADMIN] Přidá novou kartu do databáze vzorů karet."""
        cards = load_json(CARDS_DATA, default=[])

        # Duplicitní jméno
        if any(c.get("name", "").lower() == name.strip().lower() for c in cards):
            await interaction.response.send_message(
                f"Karta se jménem **{name}** již v databázi existuje.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Ověř bezpečnost názvu souboru — žádné cesty nebo separátory
        safe_image = image.strip()
        if any(ch in safe_image for ch in ("/", "\\", "..")):
            await interaction.followup.send("❌ Neplatný název souboru — nepoužívej lomítka ani '..'.", ephemeral=True)
            return
        image_status = ""
        if attachment:
            if not attachment.content_type or not attachment.content_type.startswith("image/"):
                await interaction.followup.send("❌ Příloha není obrázek. Použij PNG nebo JPG.", ephemeral=True)
                return
            try:
                dest = os.path.join(CARDS_DIR, safe_image)
                image_data = await attachment.read()
                with open(dest, "wb") as f:
                    f.write(image_data)
                image_status = "✅ uložen z přílohy"
            except Exception as e:
                await interaction.followup.send(f"❌ Nepodařilo se uložit obrázek: {e}", ephemeral=True)
                return
        else:
            if get_card_image_path(safe_image):
                image_status = "✅ nalezen v adresáři"
            else:
                image_status = "⚠️ soubor nenalezen — karta nebude zobrazitelná"

        # Přiděl nové ID
        next_id = max((c.get("id", 0) for c in cards), default=0) + 1

        new_card = {
            "id":          next_id,
            "name":        name.strip(),
            "description": description.strip(),
            "image":       safe_image,
            "collection":  collection,
        }
        cards.append(new_card)
        save_json(CARDS_DATA, cards)

        coll_data = COLLECTIONS[collection]
        embed = discord.Embed(
            title="✅ Karta přidána do databáze",
            description=f"{coll_data['emoji']} **{new_card['name']}**\n*{new_card['description']}*",
            color=coll_data["color"],
        )
        embed.add_field(name="🆔 Nové ID",   value=f"**#{next_id}**",                             inline=True)
        embed.add_field(name="📚 Kolekce",   value=f"{coll_data['emoji']} {collection.capitalize()}", inline=True)
        embed.add_field(name="🖼️ Obrázek",  value=f"`{new_card['image']}`\n{image_status}",       inline=True)
        embed.set_footer(text=f"Použij /cards print {next_id} <rarita> pro vytisknutí první kopie.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @cards_group.command(name="give_frame", description="[ADMIN] Dát rámeček hráči")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(user="Hráč, kterému chceš dát rámeček", frame_id="ID rámečku")
    async def give_frame(self, interaction: discord.Interaction, user: discord.Member, frame_id: str):
        """Admin příkaz pro přidání rámečku do inventáře hráče."""
        frame = get_frame_by_id(frame_id)
        if not frame:
            await interaction.response.send_message(f"Rámeček `{frame_id}` neexistuje.", ephemeral=True)
            return

        uid = str(user.id)
        frames_inv = load_json(FRAMES_INVENTORY, default={})

        if uid not in frames_inv:
            frames_inv[uid] = []

        if any(f.get("id") == frame_id for f in frames_inv[uid]):
            await interaction.response.send_message(
                f"{user.mention} již má rámeček **{frame.get('name')}**.", ephemeral=True
            )
            return

        frames_inv[uid].append({"id": frame_id, "name": frame.get("name")})
        save_json(FRAMES_INVENTORY, frames_inv)

        embed = discord.Embed(
            title="✅ Rámeček přidán",
            description=f"{user.mention} nyní vlastní **{frame.get('name')}**.",
            color=0x00FF00,
        )
        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="remove_card", description="[ADMIN] Smazat kartu úplně z inventáře")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(unique_id="Unikátní ID karty k odstranění")
    async def remove_card(self, interaction: discord.Interaction, unique_id: str):
        """Admin příkaz pro úplné smazání instance karty z inventáře."""
        inventory = load_json(CARDS_INVENTORY, default={})

        if unique_id not in inventory:
            await interaction.response.send_message(f"Karta `{unique_id}` neexistuje.", ephemeral=True)
            return

        card_name = inventory[unique_id].get("name", unique_id)
        owner_id = inventory[unique_id].get("owner_id")

        # Varování pokud je karta na výpravě
        works = load_json(CARDS_WORK, default={})
        on_work = owner_id and any(
            unique_id in w.get("cards", [])
            for w in works.values()
        )

        del inventory[unique_id]
        save_json(CARDS_INVENTORY, inventory)

        # Vyčisti profilovou referenci pokud existuje
        if owner_id:
            profiles = profile_load()
            if profiles.get(owner_id, {}).get("active_card_id") == unique_id:
                profiles[owner_id]["active_card_id"] = None
                profile_save(profiles)

        embed = discord.Embed(
            title="🗑️ Karta smazána",
            description=f"**{card_name}** (ID: `{unique_id}`) byla úplně odstraněna.",
            color=0xFF0000,
        )
        if on_work:
            embed.add_field(
                name="⚠️ Pozor",
                value="Karta byla na aktivní výpravě. Data výpravy zůstávají — hráč dostane odměnu za prázdné ID.",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    # -----------------------------------------------------------------------
    # Hráčské příkazy — inventář a karty
    # -----------------------------------------------------------------------

    @cards_group.command(name="inventory", description="Zobrazit své karty")
    @app_commands.describe(user="Hráč (volitelné — výchozí jsi ty)")
    async def show_inventory(self, interaction: discord.Interaction, user: discord.Member = None):
        """Zobrazí inventář hráče."""
        target = user or interaction.user
        uid = str(target.id)

        inv = load_json(CARDS_INVENTORY, default={})
        user_cards = {cid: card for cid, card in inv.items() if card.get("owner_id") == uid}

        if not user_cards:
            await interaction.response.send_message(f"{target.mention} nemá žádné karty.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🎴 Karty — {target.display_name}",
            description=f"Celkem: **{len(user_cards)}** karet",
            color=0xFFA500,
        )

        for i, (unique_id, card) in enumerate(list(user_cards.items())[:15]):
            rarity = card.get("rarity", "uncommon")
            rarity_emoji = RARITIES.get(rarity, RARITIES["uncommon"])["emoji"]
            qual = card.get("quality", "normal")
            qual_data = QUALITIES.get(qual, QUALITIES["normal"])
            frame_text = f"\nRámeček: {card['frame']}" if card.get("frame") else ""
            embed.add_field(
                name=f"{i + 1}. {card.get('name', '?')} (Print #{card.get('print_number', '?')})",
                value=(
                    f"ID: `{unique_id}`\n"
                    f"Rarita: {rarity.capitalize()} {rarity_emoji}  ·  "
                    f"Kvalita: {qual_data['emoji']} {qual_data['name']}"
                    f"{frame_text}"
                ),
                inline=False,
            )

        if len(user_cards) > 15:
            embed.set_footer(text=f"Zobrazeno 15 z {len(user_cards)} karet.")

        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="show", description="Zobrazit konkrétní kartu")
    @app_commands.describe(unique_id="Unikátní ID karty", frame="ID rámečku (volitelné — přepíše uložený)")
    async def show_card(self, interaction: discord.Interaction, unique_id: str, frame: str = None):
        """Zobrazí konkrétní kartu s obrázkem."""
        inv = load_json(CARDS_INVENTORY, default={})

        if unique_id not in inv:
            await interaction.response.send_message(f"Karta s ID `{unique_id}` neexistuje.", ephemeral=True)
            return

        card = inv[unique_id]
        card_owner_id = card.get("owner_id")

        if card_owner_id and card_owner_id != str(interaction.user.id) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Přístup odepřen", "Tato karta ti nepatří."), ephemeral=True
            )
            return

        selected_frame = frame or card.get("frame")
        await interaction.response.defer()

        try:
            image_path = get_card_image_path(card.get("image"))
            if not image_path:
                await interaction.followup.send("Obrázek karty nebyl nalezen.", ephemeral=True)
                return

            loop = asyncio.get_running_loop()
            image_bytes = await loop.run_in_executor(None, apply_frame_to_card, image_path, selected_frame)
            file = discord.File(image_bytes, filename="card.png")

            rarity = card.get("rarity", "uncommon")
            rarity_data = RARITIES.get(rarity, RARITIES["uncommon"])
            collection = card.get("collection")
            coll_data = COLLECTIONS.get(collection, {}) if collection else {}
            qual = card.get("quality", "normal")
            qual_data = QUALITIES.get(qual, QUALITIES["normal"])

            try:
                date_text = datetime.fromisoformat(card.get("created_at", "")).strftime("%d. %m. %Y")
            except Exception:
                date_text = "—"

            embed = discord.Embed(
                title=f"{rarity_data['emoji']}  {card.get('name', '?')}",
                description=f"*{card.get('description', '')}*",
                color=rarity_data["color"],
            )
            if collection and coll_data:
                embed.add_field(name="📚 Kolekce", value=f"{coll_data.get('emoji', '')} {collection.capitalize()}", inline=True)
            embed.add_field(name="✨ Rarita",     value=f"{rarity_data['emoji']} {rarity.capitalize()}",   inline=True)
            embed.add_field(name="💎 Kvalita",    value=f"{qual_data['emoji']} {qual_data['name']}",        inline=True)
            embed.add_field(name="🖨️ Tisk",      value=f"**#{card.get('print_number', '?')}**",            inline=True)
            embed.add_field(name="👤 Vlastník",   value=f"<@{card_owner_id}>" if card_owner_id else "—",    inline=True)
            embed.add_field(name="🖼️ Rámeček",   value=selected_frame or "Žádný",                         inline=True)
            embed.add_field(name="📅 Vytisknuto", value=date_text,                                          inline=True)
            embed.add_field(name="🆔 Unikátní ID", value=f"`{unique_id}`",                                  inline=False)

            footer = "⚜️ Aurionis"
            if coll_data.get("description"):
                footer += f"  •  {coll_data['description']}"
            embed.set_footer(text=footer)
            embed.set_image(url="attachment://card.png")

            await interaction.followup.send(embed=embed, file=file)
        except Exception as e:
            await interaction.followup.send(f"❌ Chyba při zobrazení karty: {e}", ephemeral=True)

    @cards_group.command(name="upgrade", description="Nasadit rámeček na kartu")
    @app_commands.describe(unique_id="ID karty", frame="ID rámečku z tvého inventáře")
    async def upgrade_frame(self, interaction: discord.Interaction, unique_id: str, frame: str):
        """Aplikuje rámeček na kartu (rámeček se spotřebuje)."""
        uid = str(interaction.user.id)
        inv = load_json(CARDS_INVENTORY, default={})
        frames_inv = load_json(FRAMES_INVENTORY, default={})

        if unique_id not in inv:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Karta nenalezena", f"ID `{unique_id}` neexistuje."), ephemeral=True
            )
            return

        card = inv[unique_id]
        if card.get("owner_id") != uid:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Přístup odepřen", "Tato karta ti nepatří."), ephemeral=True
            )
            return

        # Karta na výpravě?
        works = load_json(CARDS_WORK, default={})
        user_work = works.get(uid)
        if user_work and unique_id in user_work.get("cards", []):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nelze upravit", "Karta je momentálně na výpravě!"),
                ephemeral=True,
            )
            return

        user_frames = frames_inv.get(uid, [])
        if frame not in [f.get("id") for f in user_frames]:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Rámeček nenalezen", f"Rámeček `{frame}` nemáš v inventáři."), ephemeral=True
            )
            return

        card["frame"] = frame
        inv[unique_id] = card
        save_json(CARDS_INVENTORY, inv)

        frames_inv[uid] = [f for f in user_frames if f.get("id") != frame]
        save_json(FRAMES_INVENTORY, frames_inv)

        frame_data = get_frame_by_id(frame)
        frame_name = frame_data.get("name") if frame_data else frame
        await interaction.response.send_message(
            f"✅ Rámeček **{frame_name}** nasazen na kartu **{card.get('name', unique_id)}** (spotřebován z inventáře).",
            ephemeral=True,
        )

    @cards_group.command(name="frames", description="Rámečky ve tvém inventáři")
    async def show_frames(self, interaction: discord.Interaction):
        """Zobrazí rámečky v inventáři hráče."""
        uid = str(interaction.user.id)
        frames_inv = load_json(FRAMES_INVENTORY, default={})
        user_frames = frames_inv.get(uid, [])

        all_frames = load_json(CARDS_FRAMES, default=[])

        if not all_frames:
            await interaction.response.send_message("Žádné rámečky nejsou v databázi.", ephemeral=True)
            return

        embed = discord.Embed(title="📦 Rámečky", color=0xFF6B9D)

        owned_ids = {f.get("id") for f in user_frames}
        for f in all_frames:
            rarity_text = f" · Vyžaduje: {f['rarity_exclusive']}" if f.get("rarity_exclusive") else ""
            owned_mark = " ✅" if f.get("id") in owned_ids else ""
            embed.add_field(
                name=f"{f.get('name')}{owned_mark}",
                value=f"ID: `{f.get('id')}`{rarity_text}",
                inline=False,
            )

        embed.set_footer(text=f"Vlastníš: {len(user_frames)} z {len(all_frames)} rámečků.")
        await interaction.response.send_message(embed=embed)

    # -----------------------------------------------------------------------
    # Info & databáze
    # -----------------------------------------------------------------------

    @cards_group.command(name="info", description="Vítej v Aurionisu — přehled systému karet")
    async def cards_info(self, interaction: discord.Interaction):
        """Uvítací embed s kompletním přehledem kartového systému."""
        cards = load_json(CARDS_DATA, default=[])
        inv = load_json(CARDS_INVENTORY, default={})

        rarity_counts = {}
        collection_counts = {}
        for c in inv.values():
            r = c.get("rarity", "uncommon")
            rarity_counts[r] = rarity_counts.get(r, 0) + 1
            col = c.get("collection", "—")
            collection_counts[col] = collection_counts.get(col, 0) + 1

        embed = discord.Embed(
            title="⚜️  Vítej v Aurionisu!",
            description=(
                "*Sbírej, vyměňuj a obdivuj karty z říše Aurionisu.*\n"
                "*Každá karta je unikátní a nese příběh svého světa.*\n\u200b"
            ),
            color=0xFFD700,
        )

        embed.add_field(name="🖨️ Celkem vytisknuto", value=f"**{len(inv)}** karet",      inline=True)
        embed.add_field(name="🎴 Unikátních vzorů",   value=f"**{len(cards)}** karet",    inline=True)
        embed.add_field(name="\u200b",                value="\u200b",                      inline=True)

        coll_lines = [
            f"{cdata['emoji']} **{cid.capitalize()}** — {collection_counts.get(cid, 0)} ks"
            for cid, cdata in COLLECTIONS.items()
        ]
        embed.add_field(name="📚 Sady v oběhu", value="\n".join(coll_lines), inline=True)

        rarity_lines = [
            f"{rdata['emoji']} **{rid.capitalize()}** — {rarity_counts.get(rid, 0)} ks"
            for rid, rdata in RARITIES.items()
        ]
        embed.add_field(name="✨ Rarity v oběhu", value="\n".join(rarity_lines), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        quality_lines = [
            f"{qdata['emoji']} **{qdata['name']}** — ×{QUALITY_MULTIPLIERS[qid]:.1f} prachu"
            for qid, qdata in QUALITIES.items()
        ]
        embed.add_field(name="💎 Kvality karet", value="\n".join(quality_lines), inline=True)

        dust_lines = [
            f"{RARITIES[rid]['emoji']} {rid.capitalize()} — **{val}** prachu"
            for rid, val in DUST_VALUES.items()
        ]
        embed.add_field(name="🔥 Hodnota při spálení", value="\n".join(dust_lines), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        exp_lines = [
            f"{exp['emoji']} **{exp['name']}** — {exp['hours']}h · +{exp['reward']} zl./kartu"
            for exp in EXPEDITIONS.values()
        ]
        embed.add_field(name="⚔️ Výpravy", value="\n".join(exp_lines), inline=False)

        commands_text = (
            "`/cards inventory` — tvé karty\n"
            "`/cards show <id>` — detail karty\n"
            "`/cards profile` — profilová karta\n"
            "`/cards set_profile <id>` — nastav profilovou kartu\n"
            "`/cards burn <id>` — spálit kartu za prach\n"
            "`/cards work` — přehled výpravy\n"
            "`/cards work_send` — vyslat karty\n"
            "`/cards work_claim` — vyzvednout odměnu\n"
            "`/cards gallery` — přehled kolekcí\n"
            "`/cards list` — databáze karet"
        )
        embed.add_field(name="📖 Příkazy", value=commands_text, inline=False)
        embed.set_footer(text="⚜️ Aurionis Sběratelský Systém  •  /cards info")
        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="list", description="Dostupné vzory karet v databázi")
    async def list_cards(self, interaction: discord.Interaction):
        """Zobrazí seznam všech dostupných vzorů karet."""
        cards = load_json(CARDS_DATA, default=[])

        if not cards:
            await interaction.response.send_message("Žádné karty nejsou v databázi.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎴 Databáze karet",
            description="Použij `/cards print <id> <rarita>` pro vytisknutí kopie.",
            color=0xFFA500,
        )
        for card in cards:
            coll = card.get("collection", "—")
            coll_emoji = COLLECTIONS.get(coll, {}).get("emoji", "")
            embed.add_field(
                name=f"#{card.get('id')} — {card.get('name', '?')}  {coll_emoji}",
                value=card.get("description", "—"),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="gallery", description="Alba kolekcí — přehled sad a karet")
    @app_commands.describe(collection="Sada (volitelné) — zobrazí detail kolekce")
    @app_commands.choices(collection=[
        app_commands.Choice(name="Unworthy — Nevolaní",         value="unworthy"),
        app_commands.Choice(name="Worthy — Hrdinové Aurionisu", value="worthy"),
        app_commands.Choice(name="Queen — Královna a dvůr",     value="queen"),
        app_commands.Choice(name="Chosen — Vyvolení",           value="chosen"),
    ])
    async def gallery(self, interaction: discord.Interaction, collection: str = None):
        """Přehled kolekcí nebo detail jedné sady."""
        cards_db = load_json(CARDS_DATA, default=[])
        inv = load_json(CARDS_INVENTORY, default={})

        if collection:
            collection = collection.lower()
            coll_data = COLLECTIONS.get(collection)
            if not coll_data:
                await interaction.response.send_message(
                    f"Neznámá kolekce `{collection}`. Dostupné: {', '.join(COLLECTIONS.keys())}", ephemeral=True
                )
                return

            templates = [c for c in cards_db if c.get("collection") == collection]
            instances = [c for c in inv.values() if c.get("collection") == collection]

            rarity_counts = {}
            for inst in instances:
                r = inst.get("rarity", "uncommon")
                rarity_counts[r] = rarity_counts.get(r, 0) + 1

            embed = discord.Embed(
                title=f"{coll_data['emoji']}  Kolekce: {collection.capitalize()}",
                description=f"*{coll_data['description']}*",
                color=coll_data["color"],
            )
            embed.add_field(name="🎴 Vzorů v sadě",       value=f"**{len(templates)}**",   inline=True)
            embed.add_field(name="🖨️ Celkem vytisknuto",  value=f"**{len(instances)}**",   inline=True)
            embed.add_field(name="\u200b",                  value="\u200b",                  inline=True)

            if rarity_counts:
                rarity_lines = [
                    f"{RARITIES[rid]['emoji']} {rid.capitalize()} — {cnt} ks"
                    for rid, cnt in rarity_counts.items()
                    if cnt
                ]
                embed.add_field(name="✨ Rarity v oběhu", value="\n".join(rarity_lines), inline=False)

            if templates:
                for tmpl in templates:
                    tid = tmpl.get("id")
                    copies = sum(1 for inst in instances if inst.get("card_id") == tid)
                    embed.add_field(
                        name=f"#{tid} — {tmpl.get('name', '?')}",
                        value=f"{tmpl.get('description', '—')}\n*{copies} ks v oběhu*",
                        inline=False,
                    )
            else:
                embed.add_field(name="Karty", value="Žádné vzory v této kolekci.", inline=False)

            embed.set_footer(text="⚜️ Aurionis  •  /cards gallery pro přehled všech sad")
            await interaction.response.send_message(embed=embed)

        else:
            embed = discord.Embed(
                title="📚  Galerie Aurionisu",
                description="*Přehled všech kolekcí — jejich obsah a stav v oběhu.*",
                color=0xFFD700,
            )
            for cid, cdata in COLLECTIONS.items():
                templates_count = sum(1 for c in cards_db if c.get("collection") == cid)
                printed_count   = sum(1 for c in inv.values() if c.get("collection") == cid)
                embed.add_field(
                    name=f"{cdata['emoji']}  {cid.capitalize()}",
                    value=(
                        f"*{cdata['description']}*\n"
                        f"🎴 Vzorů: **{templates_count}**  ·  🖨️ Vytisknuto: **{printed_count}**\n"
                        f"`/cards gallery {cid}`"
                    ),
                    inline=False,
                )
            embed.set_footer(text="⚜️ Aurionis Sběratelský Systém")
            await interaction.response.send_message(embed=embed)

    # -----------------------------------------------------------------------
    # Profil
    # -----------------------------------------------------------------------

    @cards_group.command(name="set_profile", description="Nastaví kartu jako svou profilovou")
    @app_commands.describe(unique_id="Unikátní ID karty")
    async def set_profile_card(self, interaction: discord.Interaction, unique_id: str):
        """Nastaví profilovou kartu hráče."""
        uid = str(interaction.user.id)
        inv = load_json(CARDS_INVENTORY, default={})

        if unique_id not in inv:
            await interaction.response.send_message(f"Karta s ID `{unique_id}` neexistuje.", ephemeral=True)
            return

        card = inv[unique_id]
        if card.get("owner_id") != uid:
            await interaction.response.send_message("Tato karta ti nepatří.", ephemeral=True)
            return

        profiles = profile_load()
        if uid not in profiles:
            profiles[uid] = {}
        profiles[uid]["active_card_id"] = unique_id
        profile_save(profiles)

        await interaction.response.send_message(
            f"✅ Karta **{card.get('name')}** (Print #{card.get('print_number', '?')}) nastavena jako tvá profilová karta!",
            ephemeral=True,
        )

    @cards_group.command(name="profile", description="Zobrazit svou (nebo cizí) profilovou kartu")
    @app_commands.describe(user="Hráč (volitelné — výchozí jsi ty)")
    async def show_profile_card(self, interaction: discord.Interaction, user: discord.Member = None):
        """Zobrazí nastavenou profilovou kartu hráče."""
        target = user or interaction.user
        uid = str(target.id)

        profiles = profile_load()
        active_card_id = profiles.get(uid, {}).get("active_card_id")

        if not active_card_id:
            msg = "Nemáš nastavenou profilovou kartu." if not user else f"{target.mention} nemá nastavenou profilovou kartu."
            await interaction.response.send_message(
                f"{msg} Nastav ji pomocí `/cards set_profile <id>`.", ephemeral=True
            )
            return

        inv = load_json(CARDS_INVENTORY, default={})
        if active_card_id not in inv:
            # Karta byla spálena nebo smazána — vyčisti referenci
            profiles[uid]["active_card_id"] = None
            profile_save(profiles)
            await interaction.response.send_message(
                "Profilová karta již neexistuje (byla spálena nebo smazána). Nastav novou pomocí `/cards set_profile <id>`.",
                ephemeral=True,
            )
            return

        card = inv[active_card_id]
        await interaction.response.defer()

        try:
            image_path = get_card_image_path(card.get("image"))
            if not image_path:
                await interaction.followup.send("Obrázek karty nebyl nalezen.", ephemeral=True)
                return

            loop = asyncio.get_running_loop()
            selected_frame = card.get("frame")
            image_bytes = await loop.run_in_executor(None, apply_frame_to_card, image_path, selected_frame)
            file = discord.File(image_bytes, filename="card.png")

            rarity = card.get("rarity", "uncommon")
            rarity_data = RARITIES.get(rarity, RARITIES["uncommon"])
            collection = card.get("collection")
            coll_data = COLLECTIONS.get(collection, {}) if collection else {}
            qual = card.get("quality", "normal")
            qual_data = QUALITIES.get(qual, QUALITIES["normal"])

            embed = discord.Embed(
                title=f"🃏 Profilová karta — {target.display_name}",
                description=f"{rarity_data['emoji']} **{card.get('name', '?')}**\n*{card.get('description', '')}*",
                color=rarity_data["color"],
            )
            embed.add_field(name="✨ Rarita",  value=f"{rarity_data['emoji']} {rarity.capitalize()}",         inline=True)
            embed.add_field(name="💎 Kvalita", value=f"{qual_data['emoji']} {qual_data['name']}",              inline=True)
            embed.add_field(name="🖨️ Tisk",   value=f"**#{card.get('print_number', '?')}**",                  inline=True)
            if coll_data:
                embed.add_field(name="📚 Kolekce", value=f"{coll_data.get('emoji', '')} {collection.capitalize()}", inline=True)
            embed.add_field(name="🖼️ Rámeček", value=selected_frame or "Žádný",                               inline=True)
            embed.add_field(name="🆔 Karta ID", value=f"`{active_card_id}`",                                   inline=True)

            footer = "⚜️ Aurionis"
            if coll_data.get("description"):
                footer += f"  •  {coll_data['description']}"
            embed.set_footer(text=footer)
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.set_image(url="attachment://card.png")

            await interaction.followup.send(embed=embed, file=file)
        except Exception as e:
            await interaction.followup.send(f"❌ Chyba při zobrazení karty: {e}", ephemeral=True)

    # -----------------------------------------------------------------------
    # Spálení
    # -----------------------------------------------------------------------

    @cards_group.command(name="burn", description="Spálit kartu a získat Hvězdný prach")
    @app_commands.describe(unique_id="Unikátní ID karty ke spálení")
    async def burn_card(self, interaction: discord.Interaction, unique_id: str):
        """Spálí kartu hráče a připíše mu Hvězdný prach."""
        uid = str(interaction.user.id)
        inv = load_json(CARDS_INVENTORY, default={})

        if unique_id not in inv:
            await interaction.response.send_message(f"Karta s ID `{unique_id}` neexistuje.", ephemeral=True)
            return

        card = inv[unique_id]
        if card.get("owner_id") != uid:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Přístup odepřen", "Tato karta ti nepatří."), ephemeral=True
            )
            return

        # Karta na výpravě?
        works = load_json(CARDS_WORK, default={})
        user_work = works.get(uid)
        if user_work and unique_id in user_work.get("cards", []):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nelze spálit", "Karta je momentálně na výpravě! Nejprve si vyzvedni odměnu."),
                ephemeral=True,
            )
            return

        # Odstraň z profilu, pokud je aktivní
        profiles = profile_load()
        if uid in profiles and profiles[uid].get("active_card_id") == unique_id:
            profiles[uid]["active_card_id"] = None
            profile_save(profiles)

        # Výpočet prachu
        rarity = card.get("rarity", "uncommon")
        qual = card.get("quality", "normal")
        base_dust = DUST_VALUES.get(rarity, 1)
        mult = QUALITY_MULTIPLIERS.get(qual, 1.0)
        total_dust = max(1, int(base_dust * mult))
        card_name = card.get("name", unique_id)

        # Připiš prach do economy (nová měna stardust ✨)
        add_balance(uid, total_dust, "stardust")

        # Smaž kartu
        del inv[unique_id]
        save_json(CARDS_INVENTORY, inv)

        embed = discord.Embed(
            title="🔥 Karta spálena",
            description=(
                f"Spálil jsi **{card_name}** (ID: `{unique_id}`).\n"
                f"Duše karty se rozpadla na **{total_dust}× Hvězdný prach**."
            ),
            color=0xFF8C00,
        )
        qual_data = QUALITIES.get(qual, QUALITIES["normal"])
        embed.add_field(name="Rarita",  value=f"{RARITIES.get(rarity, {}).get('emoji', '')} {rarity.capitalize()}", inline=True)
        embed.add_field(name="Kvalita", value=f"{qual_data['emoji']} {qual_data['name']} (×{mult:.1f})",             inline=True)
        await interaction.response.send_message(embed=embed)

    # -----------------------------------------------------------------------
    # Výpravy
    # -----------------------------------------------------------------------

    @cards_group.command(name="pool", description="Dej hráči jednu náhodnou kartu z pool")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(user="Hráč, kterému chceš kartu dát")
    async def pool_card(self, interaction: discord.Interaction, user: discord.Member):
        """[ADMIN] Dá hráči jednu náhodnou kartu z dostupného pool."""
        uid = str(user.id)
        cards_db = load_json(CARDS_DATA, default=[])
        
        if not cards_db:
            await interaction.response.send_message("Databáze karet je prázdná!", ephemeral=True)
            return

        # Random rarity podle procent
        rarity_roll = random.random()
        if rarity_roll < 0.01:      rarity = "legendary"
        elif rarity_roll < 0.06:    rarity = "epic"
        elif rarity_roll < 0.16:    rarity = "rare"
        elif rarity_roll < 0.36:    rarity = "common"
        else:                       rarity = "uncommon"

        # Random kvalita
        quality_roll = random.random()
        if quality_roll < 0.05:     quality = "shiny"
        elif quality_roll < 0.20:   quality = "gold"
        elif quality_roll < 0.70:   quality = "normal"
        else:                       quality = "damaged"

        # Random karta z DB
        card_template = random.choice(cards_db)
        card_id = card_template.get("id")

        # Přidej do inventáře
        inventory = load_json(CARDS_INVENTORY, default={})
        unique_id = generate_unique_id()
        while unique_id in inventory:
            unique_id = generate_unique_id()

        max_print = max(
            (c.get("print_number", 0) for c in inventory.values() if c.get("card_id") == card_id),
            default=0,
        ) + 1

        inventory[unique_id] = {
            "card_id":      card_id,
            "name":         card_template.get("name"),
            "description":  card_template.get("description"),
            "image":        card_template.get("image"),
            "collection":   card_template.get("collection"),
            "rarity":       rarity,
            "quality":      quality,
            "print_number": max_print,
            "owner_id":     uid,
            "frame":        None,
            "created_at":   datetime.now().isoformat(),
        }
        save_json(CARDS_INVENTORY, inventory)

        # Veřejný embed
        rarity_data = RARITIES.get(rarity, RARITIES["uncommon"])
        quality_data = QUALITIES.get(quality, QUALITIES["normal"])
        coll_data = COLLECTIONS.get(card_template.get("collection"), {})

        embed = discord.Embed(
            title=f"🎴 **Získal jsi: {card_template.get('name')}!**",
            description=f"*{card_template.get('description', '')}*",
            color=rarity_data["color"],
        )
        embed.add_field(name="👤 Hráč",     value=user.mention,                                       inline=True)
        embed.add_field(name="✨ Rarita",   value=f"{rarity_data['emoji']} {rarity.capitalize()}",   inline=True)
        embed.add_field(name="💎 Kvalita", value=f"{quality_data['emoji']} {quality_data['name']}",  inline=True)
        if coll_data:
            embed.add_field(name="📚 Kolekce", value=f"{coll_data.get('emoji', '')} {card_template.get('collection', 'N/A').capitalize()}", inline=True)
        embed.add_field(name="🖨️ Tisk",    value=f"**#{max_print}**",                                inline=True)
        embed.add_field(name="🆔 ID",      value=f"`{unique_id}`",                                  inline=True)
        embed.set_footer(text="⚜️ Aurionis  •  Karta přidána do tvého inventáře")
        embed.set_thumbnail(url=user.display_avatar.url)

        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="work", description="Přehled výpravy — stav nebo dostupné expedice")
    async def work_hub(self, interaction: discord.Interaction):
        """Zobrazí stav aktivní výpravy, nebo přehled dostupných expedic."""
        uid = str(interaction.user.id)
        works = load_json(CARDS_WORK, default={})

        if uid in works:
            work = works[uid]
            exp = EXPEDITIONS.get(work.get("type"))
            if not exp:
                # Poškozená data výpravy
                await interaction.response.send_message(
                    "⚠️ Data tvé výpravy jsou poškozena. Kontaktuj admina.", ephemeral=True
                )
                return

            end_time = datetime.fromisoformat(work["end_time"])
            finished = datetime.now() >= end_time

            # Výpočet očekávané odměny
            card_count = len(work["cards"])
            base_reward = exp["reward"] * card_count
            bonus_mult = 1.25 if card_count >= 3 else (1.10 if card_count == 2 else 1.0)
            expected_reward = int(base_reward * bonus_mult)
            
            embed = discord.Embed(
                title=f"{exp['emoji']} Probíhá výprava: {exp['name']}",
                description=f"*{exp['description']}*",
                color=0x2ecc71 if finished else 0x3498db,
            )
            embed.add_field(name="🎴 Počet karet", value=f"**{card_count}**", inline=True)
            embed.add_field(name="💵 Odměna/kartu", value=f"**{exp['reward']}** zl", inline=True)
            embed.add_field(name="✨ Očekávaný zisk", value=f"**{expected_reward}** zl" + (f" (+{int((bonus_mult-1.0)*100)}%)" if bonus_mult > 1.0 else ""), inline=True)
            embed.add_field(name="⏰ Návrat", value=f"<t:{int(end_time.timestamp())}:R>", inline=False)

            inv = load_json(CARDS_INVENTORY, default={})
            cards_text = "\n".join(
                f"`{cid}` — {inv[cid].get('name', '?')}" if cid in inv else f"`{cid}`"
                for cid in work["cards"]
            )
            embed.add_field(name="🎴 Vyslané karty", value=cards_text or "—", inline=False)

            if finished:
                embed.add_field(
                    name="✅ Výprava skončila!",
                    value="Použij `/cards work_claim` pro vyzvednutí odměny.",
                    inline=False,
                )
        else:
            embed = discord.Embed(
                title="⚔️ Výpravné centrum",
                description="Nemáš žádnou aktivní výpravu. Vyšli karty pomocí `/cards work_send`.\n🎁 **Bonus: Pošli více karet = více zisku!** (+10% za 2, +25% za 3)\n\u200b",
                color=0x3498db,
            )
            for exp_id, exp in EXPEDITIONS.items():
                embed.add_field(
                    name=f"{exp['emoji']} {exp['name']}",
                    value=f"⏱️ {exp['hours']}h  •  💵 +{exp['reward']} zl/kartu\n*{exp['description']}*\n`/cards work_send {exp_id}`",
                    inline=False,
                )
            embed.set_footer(text="Delší expedice = vyšší odměny. Pošli až 3 karty pro bonus!")

        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="work_send", description="Vyšle až 3 karty na výpravu za zlatem")
    @app_commands.describe(
        vyprava="Typ výpravy",
        card1="ID první karty",
        card2="ID druhé karty (volitelné)",
        card3="ID třetí karty (volitelné)",
    )
    @app_commands.choices(vyprava=[
        app_commands.Choice(name="🛡️ Hlídka (6h / +5 Zl)",          value="hlidka"),
        app_commands.Choice(name="🏕️ Táborový kemp (12h / +8 Zl)",   value="tabor"),
        app_commands.Choice(name="🐺 Lov monster (20h / +12 Zl)",    value="lov"),
        app_commands.Choice(name="📜 Úkol pro gildu (36h / +20 Zl)", value="gilda"),
        app_commands.Choice(name="⚔️ Velká bitva (48h / +35 Zl)",    value="bitva"),
    ])
    async def work_send(
        self,
        interaction: discord.Interaction,
        vyprava: str,
        card1: str,
        card2: str = None,
        card3: str = None,
    ):
        """Vyšle karty hráče na expedici."""
        uid = str(interaction.user.id)
        works = load_json(CARDS_WORK, default={})

        if uid in works:
            await interaction.response.send_message(
                "Již máš aktivní výpravu! Zkontroluj ji přes `/cards work`.", ephemeral=True
            )
            return

        card_ids = [c for c in [card1, card2, card3] if c]
        if len(set(card_ids)) != len(card_ids):
            await interaction.response.send_message("Nemůžeš poslat stejnou kartu víckrát!", ephemeral=True)
            return

        inv = load_json(CARDS_INVENTORY, default={})
        for cid in card_ids:
            if cid not in inv or inv[cid].get("owner_id") != uid:
                await interaction.response.send_message(
                    f"Karta s ID `{cid}` ti nepatří nebo neexistuje.", ephemeral=True
                )
                return

        exp = EXPEDITIONS.get(vyprava)
        if not exp:
            await interaction.response.send_message("Neznámý typ výpravy.", ephemeral=True)
            return

        now = datetime.now()
        end_time = now + timedelta(hours=exp["hours"])
        works[uid] = {
            "type":       vyprava,
            "cards":      card_ids,
            "start_time": now.isoformat(),
            "end_time":   end_time.isoformat(),
        }
        save_json(CARDS_WORK, works)

        card_names = ", ".join(inv[cid].get("name", cid) for cid in card_ids)
        
        # Výpočet očekávané odměny s bonusem
        base_reward = exp['reward'] * len(card_ids)
        bonus_mult = 1.25 if len(card_ids) >= 3 else (1.10 if len(card_ids) == 2 else 1.0)
        expected_reward = int(base_reward * bonus_mult)
        bonus_text = ""
        if bonus_mult > 1.0:
            bonus_text = f" (+ {int((bonus_mult - 1.0) * 100)}% bonus!)"
        
        embed = discord.Embed(
            title=f"{exp['emoji']} Výprava zahájena: {exp['name']}",
            description=f"*{exp['description']}*",
            color=0x3498db,
        )
        embed.add_field(name="🎴 Vyslané karty", value=card_names, inline=False)
        embed.add_field(name="⏱️ Trvání", value=f"**{exp['hours']}h**", inline=True)
        embed.add_field(name="💵 Očekávaná odměna", value=f"**{expected_reward}** zl{bonus_text}", inline=True)
        embed.add_field(name="⏰ Návrat", value=f"<t:{int(end_time.timestamp())}:R>", inline=False)
        embed.set_footer(text="Vyzvednout odměnu si můžeš pomocí /cards work_claim")
        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="work_status", description="Stav tvé aktuální výpravy")
    async def work_status(self, interaction: discord.Interaction):
        """Zobrazí stav probíhající výpravy."""
        uid = str(interaction.user.id)
        works = load_json(CARDS_WORK, default={})

        if uid not in works:
            await interaction.response.send_message(
                "Nemáš žádnou aktivní výpravu. Použij `/cards work_send`.", ephemeral=True
            )
            return

        work = works[uid]
        exp = EXPEDITIONS.get(work.get("type"))
        if not exp:
            await interaction.response.send_message(
                "⚠️ Data tvé výpravy jsou poškozena. Kontaktuj admina.", ephemeral=True
            )
            return

        end_time = datetime.fromisoformat(work["end_time"])
        finished = datetime.now() >= end_time

        # Výpočet očekávané odměny
        card_count = len(work["cards"])
        base_reward = exp["reward"] * card_count
        bonus_mult = 1.25 if card_count >= 3 else (1.10 if card_count == 2 else 1.0)
        expected_reward = int(base_reward * bonus_mult)

        embed = discord.Embed(
            title=f"{exp['emoji']} Probíhá výprava: {exp['name']}",
            description=f"*{exp['description']}*",
            color=0x2ecc71 if finished else 0x3498db,
        )
        embed.add_field(name="🎴 Počet karet", value=f"**{card_count}**", inline=True)
        embed.add_field(name="💵 Odměna/kartu", value=f"**{exp['reward']}** zl", inline=True)
        embed.add_field(name="✨ Očekávaný zisk", value=f"**{expected_reward}** zl" + (f" (+{int((bonus_mult-1.0)*100)}%)" if bonus_mult > 1.0 else ""), inline=True)
        embed.add_field(name="⏰ Návrat", value=f"<t:{int(end_time.timestamp())}:R>", inline=False)
        
        if finished:
            embed.add_field(
                name="✅ Výprava skončila!",
                value="Použij `/cards work_claim` pro vyzvednutí odměny.",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="work_claim", description="Vyzvednout odměnu z dokončené výpravy")
    async def work_claim(self, interaction: discord.Interaction):
        """Vyzvedne odměnu za dokončenou výpravu."""
        uid = str(interaction.user.id)
        works = load_json(CARDS_WORK, default={})

        if uid not in works:
            await interaction.response.send_message("Nemáš žádnou aktivní výpravu.", ephemeral=True)
            return

        work = works[uid]
        exp = EXPEDITIONS.get(work.get("type"))
        if not exp:
            await interaction.response.send_message(
                "⚠️ Data tvé výpravy jsou poškozena. Kontaktuj admina.", ephemeral=True
            )
            return

        end_time = datetime.fromisoformat(work["end_time"])
        if datetime.now() < end_time:
            await interaction.response.send_message(
                f"Výprava ještě neskončila! Návrat: <t:{int(end_time.timestamp())}:R>", ephemeral=True
            )
            return

        # Výpočet odměny s bonusem za počet karet
        card_count = len(work["cards"])
        base_reward = exp["reward"] * card_count
        
        # Bonus: 10% za 2 karty, 25% za 3 karty
        bonus_multiplier = 1.0
        if card_count == 2:
            bonus_multiplier = 1.10
        elif card_count >= 3:
            bonus_multiplier = 1.25
        
        reward = int(base_reward * bonus_multiplier)

        eco = load_economy()
        eco[uid] = eco.get(uid, 0) + reward
        save_economy(eco)

        del works[uid]
        save_json(CARDS_WORK, works)

        # Build embed s detaily
        embed = discord.Embed(
            title="💰 Výprava dokončena",
            description=f"Tvé karty se v pořádku vrátily z **{exp['name']}**!",
            color=0xFFD700,
        )
        embed.add_field(name="🎴 Počet karet", value=f"**{card_count}**", inline=True)
        embed.add_field(name="💵 Odměna na kartu", value=f"**{exp['reward']}** zl", inline=True)
        if bonus_multiplier > 1.0:
            bonus_pct = int((bonus_multiplier - 1.0) * 100)
            embed.add_field(name="🎁 Bonus", value=f"+{bonus_pct}% (víc karet = víc zisku!)", inline=True)
        embed.add_field(name="✨ Celkem", value=f"**{reward} zlaťáků**", inline=False, )
        embed.set_footer(text=f"Základní: {int(base_reward)} zl" if bonus_multiplier > 1.0 else "")
        await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def setup(bot):
    """Registruje cog do bota."""
    ensure_cards_data()
    ensure_frames_data()
    _migrate_stardust_to_economy()
    await bot.add_cog(Cards(bot))


def _migrate_stardust_to_economy():
    """
    Jednorázový sběr: starý 'Hvězdný prach' jako free item v inventářích
    převede na novou měnu stardust v economy a item odstraní.
    Idempotentní — po převedení už žádné itemy nezůstanou, takže opakované
    spuštění (každý restart) nic neudělá.
    """
    try:
        profiles = inv_load()
    except Exception:
        return

    changed = False
    for uid, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        # Prach může být v profile["inventory"] i ve storages["inventory"]
        lists = []
        if isinstance(profile.get("inventory"), list):
            lists.append(profile["inventory"])
        storages = profile.get("storages")
        if isinstance(storages, dict) and isinstance(storages.get("inventory"), list):
            if storages["inventory"] is not profile.get("inventory"):
                lists.append(storages["inventory"])

        total = 0
        for inv in lists:
            kept = []
            for item in inv:
                if item.get("type") == "free" and item.get("name") == "Hvězdný prach":
                    total += int(item.get("qty", 0))
                else:
                    kept.append(item)
            inv[:] = kept  # uprav list in-place

        if total > 0:
            add_balance(uid, total, "stardust")
            changed = True

    if changed:
        inv_save(profiles)
        print("[cards] Migrace Hvězdného prachu do economy dokončena.")