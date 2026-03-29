import random
import re
import json
import os
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

# ── Konfigurace ──────────────────────────────────────────────────────────────
from src.utils.paths import STORY_LIB as LIBRARY_FILE, STORY_SAVE as SAVE_FILE

PLOT_TWISTS = [
    "gumová kachnička", "motorová pila", "záchodové prkénko", "plameňák", "ponožky v sandálech",
    "jaderný reaktor", "nemanželské dítě", "tajný agent", "bagr", "majonéza",
    "mimozemšťan", "kouzelná hůlka", "chlupatý pavouk", "neviditelný plášť", "zlomený palec",
    "párek v rohlíku", "mluvící kámen", "křeček", "falešný knír", "teleport",
    "rozzuřený dav", "létající koberec", "svatební šaty", "kyselá okurka", "toaletní papír",
    "laserové oči", "detektor lži", "upír", "klobása", "hrací skříňka",
    "mapa k pokladu", "časostroj", "jedovatá žába", "rozbité zrcadlo", "výherní los",
    "falešné zuby", "pirátská loď", "drak", "kaktus", "zmrzlina",
    "výbušnina", "kouzelný lektvar", "zombík", "rytířské brnění", "papoušek",
    "padák", "stará bota", "banánová slupka", "šampon", "tchyňský jazyk"
]

FALLBACK_NOUNS = [
    "drak", "hrdina", "tajemství", "poklad", "les", "hrad", "kniha",
    "meč", "démon", "věštkyně", "loď", "ostrov", "mapa", "dopis", "klíč"
]

# ── Pomocné funkce ────────────────────────────────────────────────────────────

def load_library() -> list:
    if os.path.exists(LIBRARY_FILE):
        with open(LIBRARY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_to_library(topic: str, players: list, sentences: list):
    library = load_library()
    library.append({
        "topic": topic,
        "players": players,
        "story": " ".join(sentences),
        "date": datetime.now().strftime("%d.%m.%Y %H:%M")
    })
    with open(LIBRARY_FILE, "w", encoding="utf-8") as f:
        json.dump(library, f, ensure_ascii=False, indent=2)


def save_game_state(channel_id: int, game: dict):
    """Uloží stav hry do souboru (pojistka při pádu bota)."""
    saves = {}
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                saves = json.load(f)
        except:
            saves = {}
    # Ulozit jen serializovatelna data (bez discord objektu)
    saves[str(channel_id)] = {
        "topic": game["topic"],
        "max_rounds": game["max_rounds"],
        "rounds": game["rounds"],
        "current_turn_index": game["current_turn_index"],
        "player_ids": [p.id for p in game["players"]],
        "player_names": [p.display_name for p in game["players"]],
        "butterfly_word": game.get("butterfly_word"),
        "butterfly_triggered": game.get("butterfly_triggered", False),
        "flashback_done": game.get("flashback_done", False),
    }
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(saves, f, ensure_ascii=False, indent=2)

def delete_game_save(channel_id: int):
    if not os.path.exists(SAVE_FILE):
        return
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            saves = json.load(f)
        saves.pop(str(channel_id), None)
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(saves, f, ensure_ascii=False, indent=2)
    except:
        pass

def chunk_text(text: str, size: int = 4000) -> list[str]:
    chunks = []
    while len(text) > size:
        split_at = text.rfind(" ", 0, size)
        if split_at == -1:
            split_at = size
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    chunks.append(text)
    return chunks

def make_progress_bar(current: int, total: int, length: int = 10) -> str:
    """Vizuální progress bar. Např: [▰▰▰▱▱▱▱▱▱▱] 30%"""
    filled = round((current / total) * length)
    bar = "▰" * filled + "▱" * (length - filled)
    pct = round((current / total) * 100)
    return f"[{bar}] {pct}%"

def extract_noun(sentence: str) -> str | None:
    """Vytáhne zajímavé slovo (6+ znaků) z věty pro Butterfly Effect."""
    stopwords = {
        "které", "která", "který", "jejich", "tohoto", "tento", "tato", "toto",
        "jsem", "jste", "bylo", "byla", "není", "jsou", "jako", "nebo", "také",
        "když", "před", "přes", "proti", "mezi", "velmi", "proto", "potom",
        "najednou", "teprve", "ještě", "každý", "každá", "každé"
    }
    words = re.findall(r'\b[a-záčďéěíňóřšťúůýž]{6,}\b', sentence.lower())
    candidates = [w for w in words if w not in stopwords]
    return random.choice(candidates) if candidates else None


# ── Mystery Box View ──────────────────────────────────────────────────────────

class MysteryBoxView(discord.ui.View):
    def __init__(self, cog, channel_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.channel_id = channel_id
        self.opened = False

    async def _resolve(self, interaction: discord.Interaction, is_left: bool):
        if self.opened:
            await interaction.response.send_message("Truhla už byla otevřena!", ephemeral=True)
            return
        self.opened = True
        self.stop()

        game = self.cog.active_games.get(self.channel_id)
        if not game:
            await interaction.response.send_message("Hra skončila.", ephemeral=True)
            return

        current_player = game["players"][game["current_turn_index"]]
        # 50/50 bez ohledu na to, kdo kliknul na co – napínavost!
        blessing = random.random() < 0.5

        if blessing:
            old_twist = game["current_twist"]
            # Zrusit vsechny twisty – hrac pise volne
            game["current_twist"] = None
            game["forced_twist"] = None
            game["forced_by"] = None
            game["extra_twist"] = None
            await interaction.response.edit_message(
                content=(
                    f"✨ **POŽEHNÁNÍ!** {interaction.user.display_name} otevřel truhlu!\n"
                    f"Twist `{old_twist}` byl zrušen. {current_player.mention} píše volně!"
                ),
                view=None
            )
        else:
            curse_word = random.choice(PLOT_TWISTS)
            game["extra_twist"] = curse_word
            await interaction.response.edit_message(
                content=(
                    f"💀 **PROKLETÍ!** {interaction.user.display_name} otevřel truhlu!\n"
                    f"{current_player.mention} musí navíc použít slovo: `{curse_word}`"
                ),
                view=None
            )
            # Poslat embed s aktualizovanymi twisty aby hrac videl oba pozadavky
            channel = interaction.client.get_channel(self.channel_id)
            if channel:
                await self.cog.next_turn(self.channel_id, channel, resend_embed=True)

    @discord.ui.button(label="⬛ Levá truhla", style=discord.ButtonStyle.success, custom_id="box_left")
    async def left_box(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, is_left=True)

    @discord.ui.button(label="⬛ Pravá truhla", style=discord.ButtonStyle.danger, custom_id="box_right")
    async def right_box(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, is_left=False)


# ── Lobby View ────────────────────────────────────────────────────────────────

class StoryLobby(discord.ui.View):
    def __init__(self, cog, author, max_rounds, topic):
        super().__init__(timeout=None)
        self.cog = cog
        self.author = author
        self.max_rounds = max_rounds
        self.topic = topic
        self.players = [author]

    @discord.ui.button(label="Připojit se", style=discord.ButtonStyle.success, custom_id="join_btn")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in [p.id for p in self.players]:
            await interaction.response.send_message("Už jsi v lobby!", ephemeral=True)
            return
        self.players.append(interaction.user)
        await interaction.response.edit_message(
            content=f"**Kronika: {self.topic}**\nLobby: {len(self.players)} hráčů připraveno."
        )

    @discord.ui.button(label="Start", style=discord.ButtonStyle.primary, custom_id="start_btn")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Pouze zakladatel může odstartovat hru!", ephemeral=True)
            return
        if len(self.players) < 2:
            await interaction.response.send_message("Potřebujete alespoň 2 hráče!", ephemeral=True)
            return
        await interaction.response.edit_message(content="Hra začíná! 🚀", view=None)
        await self.cog.start_story_game(interaction.channel, self.players, self.max_rounds, self.topic)


# ── STOP! Modal ───────────────────────────────────────────────────────────────

class StopWordModal(discord.ui.Modal, title="STOP! Zadej slovo pro hráče"):
    word = discord.ui.TextInput(
        label="Slovo, které musí hráč použít",
        placeholder="napiš jedno slovo...",
        max_length=40
    )

    def __init__(self, cog, channel_id):
        super().__init__()
        self.cog = cog
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        game = self.cog.active_games.get(self.channel_id)
        if not game:
            await interaction.response.send_message("Hra už neběží.", ephemeral=True)
            return
        if game.get("forced_twist"):
            await interaction.response.send_message("Už je jedno slovo aktivní, počkej!", ephemeral=True)
            return

        forced = self.word.value.strip()
        game["forced_twist"] = forced
        game["forced_by"] = interaction.user.display_name

        channel = interaction.client.get_channel(self.channel_id)
        await channel.send(
            f"🛑 **STOP!** {interaction.user.display_name} přerušuje příběh!\n"
            f"Aktuální hráč musí do své věty zapsat slovo: `{forced}`"
        )
        await interaction.response.send_message("Slovo odesláno! 😈", ephemeral=True)


# ── Main Cog ──────────────────────────────────────────────────────────────────

class StoryCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_games: dict = {}

    # ── Spuštění hry ─────────────────────────────────────────────────────────

    async def start_story_game(self, channel, players, max_rounds, topic):
        random.shuffle(players)
        self.active_games[channel.id] = {
            "players": players,
            "current_turn_index": 0,
            "rounds": [],
            "max_rounds": max_rounds,
            "topic": topic,
            "current_twist": None,
            "extra_twist": None,
            "forced_twist": None,
            "forced_by": None,
            # Butterfly Effect
            "butterfly_word": None,
            "butterfly_triggered": False,
            # Flashback
            "flashback_pending": False,
            "flashback_player": None,
            "flashback_done": False,
        }
        await self.next_turn(channel.id, channel)

    # ── Tah ──────────────────────────────────────────────────────────────────

    async def next_turn(self, channel_id, channel, resend_embed=False):
        if channel_id not in self.active_games:
            return

        game = self.active_games[channel_id]

        if len(game["rounds"]) >= game["max_rounds"]:
            await self._end_game(channel, game)
            del self.active_games[channel_id]
            return

        count = len(game["rounds"])
        total = game["max_rounds"]
        current_player = game["players"][game["current_turn_index"]]

        # ── Butterfly: ulož slovo z 1. třetiny ───────────────────────────────
        if not game["butterfly_word"] and count >= max(1, total // 3) and game["rounds"]:
            noun = extract_noun(game["rounds"][0]) or random.choice(FALLBACK_NOUNS)
            game["butterfly_word"] = noun

        # ── Speciální události ────────────────────────────────────────────────
        special_event = None

        # Flashback: jednou za hru, od 50% dál
        if (not game["flashback_done"] and count >= total // 2 and random.random() < 0.20):
            game["flashback_pending"] = True
            game["flashback_player"] = random.choice(game["players"])
            game["flashback_done"] = True
            current_player = game["flashback_player"]
            special_event = "flashback"

        # Butterfly Effect: jednou za hru, od 66% dál
        elif (game["butterfly_word"] and not game["butterfly_triggered"]
              and count >= (total * 2 // 3) and random.random() < 0.30):
            game["butterfly_triggered"] = True
            game["current_twist"] = game["butterfly_word"]
            special_event = "butterfly"

        # ── Twist logika ──────────────────────────────────────────────────────
        has_twist = False
        twist_lines = []

        if game["forced_twist"]:
            game["current_twist"] = game["forced_twist"]
            twist_lines.append(f"🛑 **STOP od {game['forced_by']}:** `{game['forced_twist']}`")
            has_twist = True
        elif special_event == "butterfly":
            twist_lines.append(f"🦋 **Motýlí efekt:** `{game['butterfly_word']}`")
            has_twist = True
        elif special_event is None and random.random() < 0.25:
            game["current_twist"] = random.choice(PLOT_TWISTS)
            twist_lines.append(f"⚠️ **PLOT TWIST:** `{game['current_twist']}`")
            has_twist = True
        elif special_event is None:
            game["current_twist"] = None

        if game.get("extra_twist"):
            twist_lines.append(f"💀 **Prokletí navíc:** `{game['extra_twist']}`")
            has_twist = True

        twist_msg = ("\n" + "\n".join(twist_lines)) if twist_lines else ""

        # ── Kontext příběhu ───────────────────────────────────────────────────
        last_sentences = game["rounds"][-3:]
        story_so_far = " ".join(last_sentences) if game["rounds"] else "Začni příběh první větou!"
        if len(story_so_far) > 1000:
            story_so_far = "..." + story_so_far[-997:]

        progress = make_progress_bar(count, total)

        # ── Embed ─────────────────────────────────────────────────────────────
        embed = discord.Embed(title=f"Kronika: {game['topic']}", color=discord.Color.blue())
        embed.add_field(name="Předchozí události:", value=story_so_far, inline=False)

        if special_event == "flashback":
            embed.color = discord.Color.from_rgb(148, 103, 189)
            embed.add_field(
                name="⏳ FLASHBACK!",
                value=(
                    f"{current_player.mention} byl vybrán osudem!\n"
                    f"Napiš větu, která se stala **PŘED začátkem příběhu**.\n"
                    f"Tato věta bude vložena na **úplný začátek** Kroniky."
                ),
                inline=False
            )
        elif special_event == "butterfly":
            embed.color = discord.Color.from_rgb(255, 140, 0)
            embed.add_field(
                name="🦋 MOTÝLÍ EFEKT!",
                value=(
                    f"{current_player.mention}, osud se vrací!\n"
                    f"Musíš zakomponovat slovo z úvodu příběhu: `{game['butterfly_word']}`"
                ),
                inline=False
            )
        else:
            embed.add_field(
                name="Na řadě:",
                value=f"{current_player.mention}{twist_msg}",
                inline=False
            )

        embed.set_footer(text=f"Postup: {progress}  •  Kolo {count + 1}/{total}")

        # ── Mystery Box – jen pokud je twist a není speciální event ──────────
        if has_twist and special_event is None:
            view = MysteryBoxView(self, channel_id)
            await channel.send(
                content="🎁 **Mystery Box!** Kdo první klikne, rozhodne o osudu hráče:",
                embed=embed,
                view=view
            )
        else:
            await channel.send(embed=embed)

    # ── Konec hry ────────────────────────────────────────────────────────────

    async def _end_game(self, channel, game):
        final_story = " ".join(game["rounds"])
        authors = ", ".join(p.display_name for p in game["players"])

        save_to_library(
            game["topic"],
            [p.display_name for p in game["players"]],
            game["rounds"]
        )

        chunks = chunk_text(final_story, size=3800)
        total = len(chunks)

        if total == 1:
            embed = discord.Embed(
                title=f"📖 Konec Kroniky: {game['topic']}",
                description=final_story,
                color=discord.Color.gold()
            )
            embed.set_footer(text=f"Autoři: {authors}")
            await channel.send(embed=embed)
        else:
            for i, chunk in enumerate(chunks, 1):
                embed = discord.Embed(
                    title=f"📖 Kronika: {game['topic']} ({i}/{total})",
                    description=chunk,
                    color=discord.Color.gold()
                )
                if i == total:
                    embed.set_footer(text=f"Autoři: {authors} • Konec příběhu")
                await channel.send(embed=embed)

    # ── Příchozí zprávy ───────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.channel.id not in self.active_games:
            return

        game = self.active_games[message.channel.id]
        channel_id = message.channel.id

        expected_player = (
            game["flashback_player"] if game.get("flashback_pending")
            else game["players"][game["current_turn_index"]]
        )

        if message.author.id != expected_player.id:
            return

        text = message.content.strip()
        ctx = await self.bot.get_context(message)
        if ctx.valid or text.startswith("/"):
            return

        # ── Kontrola twistů ───────────────────────────────────────────────────
        twists_to_check = []
        if game["current_twist"]:
            twists_to_check.append(game["current_twist"])
        if game.get("extra_twist"):
            twists_to_check.append(game["extra_twist"])

        for tw in twists_to_check:
            if tw.lower() not in text.lower():
                try:
                    await message.delete()
                except Exception:
                    pass
                err = await message.channel.send(
                    f"❌ {message.author.mention}, chybí slovo: `{tw}`!"
                )
                await err.delete(delay=5)
                return

        # ── Přijmutí věty ─────────────────────────────────────────────────────
        if game.get("flashback_pending"):
            game["rounds"].insert(0, f"[Vzpomínka: {text}]")
            game["flashback_pending"] = False
            game["flashback_player"] = None
            # Po flashbacku pokračuje stejný hráč, který byl na tahu
        else:
            game["rounds"].append(text)
            game["current_turn_index"] = (game["current_turn_index"] + 1) % len(game["players"])

        # Reset twistů
        game["forced_twist"] = None
        game["forced_by"] = None
        game["current_twist"] = None
        game["extra_twist"] = None

        try:
            await message.delete()
        except Exception as e:
            print(f"Chyba při mazání zprávy: {e}")

        save_game_state(channel_id, game)
        await self.next_turn(channel_id, message.channel)

    # ── Slash příkazy ─────────────────────────────────────────────────────────

    @app_commands.command(name="story_create", description="Založ novou Kroniku!")
    @app_commands.describe(max_kol="Počet kol do konce hry", tema="Téma příběhu")
    async def story_create(self, interaction: discord.Interaction, max_kol: int, tema: str):
        if interaction.channel.id in self.active_games:
            await interaction.response.send_message("Tady už jedna hra běží!", ephemeral=True)
            return
        view = StoryLobby(self, interaction.user, max_kol, tema)
        await interaction.response.send_message(
            f"**Nová Kronika: {tema}**\nCíl: {max_kol} kol.\nČeká se na hráče...",
            view=view
        )

    @app_commands.command(name="story_skip", description="Přeskočí aktuálního hráče.")
    async def story_skip(self, interaction: discord.Interaction):
        if interaction.channel.id not in self.active_games:
            await interaction.response.send_message("Tady se nic nehraje.", ephemeral=True)
            return
        game = self.active_games[interaction.channel.id]
        game["current_turn_index"] = (game["current_turn_index"] + 1) % len(game["players"])
        await interaction.response.send_message("⏩ Hráč byl přeskočen.")
        await self.next_turn(interaction.channel.id, interaction.channel)

    @app_commands.command(name="story_cancel", description="Zruší hru v tomto kanálu.")
    async def story_cancel(self, interaction: discord.Interaction):
        if interaction.channel.id in self.active_games:
            del self.active_games[interaction.channel.id]
            await interaction.response.send_message("🛑 Hra byla zrušena.")
        else:
            await interaction.response.send_message("Žádná hra neběží.", ephemeral=True)

    @app_commands.command(name="story_stop", description="[DIVÁK] Zastav příběh a zadej slovo!")
    async def story_stop(self, interaction: discord.Interaction):
        if interaction.channel.id not in self.active_games:
            await interaction.response.send_message("Tady se nic nehraje.", ephemeral=True)
            return
        modal = StopWordModal(self, interaction.channel.id)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="story_library", description="Zobraz uložené příběhy z Kroniky.")
    @app_commands.describe(index="Číslo příběhu (nech prázdné pro seznam)")
    async def story_library(self, interaction: discord.Interaction, index: int = None):
        library = load_library()
        if not library:
            await interaction.response.send_message("Knihovna je zatím prázdná.", ephemeral=True)
            return

        if index is None:
            lines = [
                f"`{i}.` **{e['topic']}** – {e['date']} ({', '.join(e['players'])})"
                for i, e in enumerate(library, 1)
            ]
            text = "\n".join(lines)
            chunks = chunk_text(text, size=3800)
            await interaction.response.send_message(
                f"📚 **Kronika – Knihovna** ({len(library)} příběhů)\n\n{chunks[0]}",
                ephemeral=True
            )
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk, ephemeral=True)
        else:
            if index < 1 or index > len(library):
                await interaction.response.send_message(
                    f"Příběh č. {index} neexistuje. Máme {len(library)} příběhů.", ephemeral=True
                )
                return
            entry = library[index - 1]
            authors = ", ".join(entry["players"])
            chunks = chunk_text(entry["story"], size=3800)
            total = len(chunks)

            await interaction.response.defer(ephemeral=True)
            for i, chunk in enumerate(chunks, 1):
                embed = discord.Embed(
                    title=f"📖 {entry['topic']}" + (f" ({i}/{total})" if total > 1 else ""),
                    description=chunk,
                    color=discord.Color.purple()
                )
                if i == total:
                    embed.set_footer(text=f"Autoři: {authors} • {entry['date']}")
                await interaction.followup.send(embed=embed, ephemeral=True)



    @app_commands.command(name="story_resume", description="Obnoví rozehranou hru po pádu bota")
    @app_commands.describe(index="Číslo kola od kterého pokračovat (nech prázdné = pokračuj od posledního uloženého)")
    @app_commands.checks.has_permissions(administrator=True)
    async def story_resume(self, interaction: discord.Interaction, index: int = None):
        if interaction.channel.id in self.active_games:
            await interaction.response.send_message("Tady už hra běží!", ephemeral=True)
            return

        if not os.path.exists(SAVE_FILE):
            await interaction.response.send_message("Žádná uložená hra nenalezena.", ephemeral=True)
            return

        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                saves = json.load(f)
        except:
            await interaction.response.send_message("Chyba při čtení uložené hry.", ephemeral=True)
            return

        channel_id = str(interaction.channel.id)
        if channel_id not in saves:
            await interaction.response.send_message(
                "Pro tento kanál nebyla nalezena žádná uložená hra.\n-# Tip: save se vytváří automaticky po každém odehraném kole.",
                ephemeral=True
            )
            return

        save = saves[channel_id]

        # Obnovit hrace z guild members
        players = []
        missing = []
        for pid, pname in zip(save["player_ids"], save["player_names"]):
            member = interaction.guild.get_member(pid)
            if member:
                players.append(member)
            else:
                missing.append(pname)

        if not players:
            await interaction.response.send_message("Žádný z původních hráčů není na serveru.", ephemeral=True)
            return

        rounds = save["rounds"]

        # Pokud admin zadal konkrétní index, ořízni kola
        if index is not None:
            if index < 1 or index > len(rounds):
                await interaction.response.send_message(
                    f"Index {index} je mimo rozsah. Uloženo je {len(rounds)} kol.",
                    ephemeral=True
                )
                return
            rounds = rounds[:index]

        # Obnovit hru
        self.active_games[interaction.channel.id] = {
            "players": players,
            "current_turn_index": save.get("current_turn_index", 0) % len(players),
            "rounds": rounds,
            "max_rounds": save["max_rounds"],
            "topic": save["topic"],
            "current_twist": None,
            "extra_twist": None,
            "forced_twist": None,
            "forced_by": None,
            "butterfly_word": save.get("butterfly_word"),
            "butterfly_triggered": save.get("butterfly_triggered", False),
            "flashback_pending": False,
            "flashback_player": None,
            "flashback_done": save.get("flashback_done", False),
        }

        warn = (f"\n\u26a0\ufe0f Chyb\u011bj\u00edc\u00ed hr\u00e1\u010di (ode\u0161li ze serveru): {', '.join(missing)}") if missing else ""
        resume_from = len(rounds) + 1

        await interaction.response.send_message(
            f"\u267b\ufe0f **Hra obnovena!** T\u00e9ma: **{save['topic']}**\nPokra\u010dujeme od kola **{resume_from}/{save['max_rounds']}**{warn}"
        )
        await self.next_turn(interaction.channel.id, interaction.channel)

async def setup(bot: commands.Bot):
    await bot.add_cog(StoryCog(bot))