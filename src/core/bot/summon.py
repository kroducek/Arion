"""Summonovací systém — otevírání beden s kartami."""

import asyncio
import os
import random
from functools import partial

import discord
from discord import app_commands
from discord.ext import commands

from src.core.bot.cards import (
    build_showcase_image,
    get_card_image_path,
    grant_random_card,
)
from src.utils.json_utils import load_json, save_json
from src.utils.paths import CARDS_CRATES, CARDS_DATA, CARDS_DIR, CRATES_DIR, data as _data

# ---------------------------------------------------------------------------
# Konstanty
# ---------------------------------------------------------------------------

CRATES = {
    "basic": {
        "name": "Základní bedna",
        "emoji": "📦",
        "color": 0xC27C0E,
        "description": "Obyčejná bedna z Aurionisu — uvnitř čeká jedna karta.",
        "gifs": [
            "crate_open.gif",
            "crate_open2.gif",
        ],
    },
}

STARTER_CRATES = {"basic": 1}

TICKET_EMOJI = "🎟️"
MAX_TICKETS = 10
MAX_CLOVERS = 5
LUCK_DATA = _data("summon_luck.json")

# Prodlevy jednotlivých fází animace (sekundy)
GIF_DURATION = 3.0
TICKET_STEP = 0.5
ROLL_DELAYS = [0.35, 0.35, 0.45, 0.55, 0.7, 0.9, 1.1]


# ---------------------------------------------------------------------------
# Pomocné funkce
# ---------------------------------------------------------------------------

def load_crates() -> dict:
    """Načte bedny všech hráčů."""
    return load_json(CARDS_CRATES, default={})


def get_crates(uid: str) -> dict:
    """
    Vrátí bedny hráče. Hráč, který summon ještě nikdy nepoužil, dostane
    startovní balíček.
    """
    crates = load_crates()
    if uid not in crates:
        crates[uid] = dict(STARTER_CRATES)
        save_json(CARDS_CRATES, crates)
    return crates[uid]


def change_crates(uid: str, crate_id: str, amount: int) -> int:
    """Přičte (nebo odečte) bedny hráči a vrátí nový počet."""
    crates = load_crates()
    owned = crates.setdefault(uid, dict(STARTER_CRATES))
    owned[crate_id] = max(0, owned.get(crate_id, 0) + amount)
    save_json(CARDS_CRATES, crates)
    return owned[crate_id]


def get_crate_gif_path(crate_id: str):
    """Vrátí cestu k náhodné animaci bedny, nebo None pokud soubor chybí."""
    crate_data = CRATES.get(crate_id, {})
    
    # Zkus nejdřív "gifs" (pole)
    gifs = crate_data.get("gifs", [])
    if gifs:
        selected_gif = random.choice(gifs)
    else:
        # Fallback na starý formát "gif" (single string)
        selected_gif = crate_data.get("gif")
    
    if not selected_gif:
        return None
    
    path = os.path.join(CRATES_DIR, selected_gif)
    return path if os.path.exists(path) else None


def get_roll_images(count: int) -> list:
    """Vybere obrázky karet pro rolovací animaci — nikdy dva stejné za sebou."""
    paths = [
        p for p in (
            get_card_image_path(card.get("image"))
            for card in load_json(CARDS_DATA, default=[])
        ) if p
    ]
    if not paths and os.path.isdir(CARDS_DIR):
        paths = [
            os.path.join(CARDS_DIR, f)
            for f in sorted(os.listdir(CARDS_DIR))
            if f.lower().endswith((".png", ".jpg", ".jpeg"))
        ]
    if not paths:
        return []

    frames = []
    for _ in range(count):
        choices = [p for p in paths if p != (frames[-1] if frames else None)] or paths
        frames.append(random.choice(choices))
    return frames


def ticket_bar(current: int, total: int) -> str:
    """Řádek lístků štěstí — naskákané a zbývající prázdná místa."""
    return f"{TICKET_EMOJI * current}{'▫️' * (total - current)}"


def clover_bar(current: int, total: int) -> str:
    """Řádek čtyřlístků — dlouhodobé štěstí hráče."""
    return f"{'🍀' * current}{'▫️' * (total - current)}"


def load_luck() -> dict:
    """Načte dlouhodobé štěstí hráčů."""
    return load_json(LUCK_DATA, default={})


def get_luck(uid: str) -> dict:
    """Vrátí stav štěstí hráče a doplní bezpečné výchozí hodnoty."""
    luck = load_luck()
    state = luck.setdefault(uid, {"clovers": 0})
    state["clovers"] = max(0, min(MAX_CLOVERS, int(state.get("clovers", 0))))
    save_json(LUCK_DATA, luck)
    return state


def add_clover(uid: str) -> int:
    """Přidá čtyřlístek, maximálně do 5/5."""
    luck = load_luck()
    state = luck.setdefault(uid, {"clovers": 0})
    state["clovers"] = min(MAX_CLOVERS, int(state.get("clovers", 0)) + 1)
    save_json(LUCK_DATA, luck)
    return state["clovers"]


def total_luck(tickets: int, clovers: int) -> int:
    """
    Přepočítá viditelné štěstí na sílu rollu.
    Každý lístek = +1 luck, každý čtyřlístek = +2 luck.
    """
    return min(20, max(0, tickets + clovers * 2))


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Summon(commands.Cog):
    """Otevírání beden s kartami."""

    def __init__(self, bot):
        self.bot = bot
        self._opening: set[str] = set()

    summon_group = app_commands.Group(name="summon", description="Summonování karet z beden")

    @summon_group.command(name="crates", description="Přehled tvých beden")
    async def show_crates(self, interaction: discord.Interaction):
        """Vypíše bedny v inventáři hráče."""
        owned = get_crates(str(interaction.user.id))

        embed = discord.Embed(
            title="📦 Tvé bedny",
            description="Otevři je příkazem `/summon open`.",
            color=0xC27C0E,
        )
        for crate_id, crate in CRATES.items():
            embed.add_field(
                name=f"{crate['emoji']} {crate['name']}",
                value=f"**{owned.get(crate_id, 0)}×**\n*{crate['description']}*",
                inline=True,
            )
        embed.set_footer(text="⚜️ Aurionis")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @summon_group.command(name="give", description="[ADMIN] Přidat bedny více hráčům najednou")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        users="Hráči oddělení mezerou nebo zatagování",
        crate="Typ bedny",
        count="Počet beden na hráče (výchozí: 1)"
    )
    @app_commands.choices(crate=[
        app_commands.Choice(name="Základní bedna", value="basic"),
    ])
    async def give_crate(
        self,
        interaction: discord.Interaction,
        users: str,
        crate: str = "basic",
        count: int = 1,
    ):
        """[ADMIN] Přidá bedny více hráčům najednou."""
        if crate not in CRATES:
            await interaction.response.send_message("Taková bedna neexistuje.", ephemeral=True)
            return
        if not 1 <= count <= 100:
            await interaction.response.send_message("Počet musí být mezi 1 a 100.", ephemeral=True)
            return

        # Parsuj uživatele z textu (tagování nebo ID)
        user_ids = []
        for mention in users.split():
            # Pokud je to tag <@ID>
            if mention.startswith("<@") and mention.endswith(">"):
                uid = mention.strip("<@!>")
                user_ids.append(uid)
            # Pokud je to jen ID
            elif mention.isdigit():
                user_ids.append(mention)

        if not user_ids:
            await interaction.response.send_message(
                "❌ Žádní hráči nenalezeni. Použij `/summon give @user1 @user2 ... basic 5`",
                ephemeral=True
            )
            return

        results = []
        for uid in user_ids:
            total = change_crates(uid, crate, count)
            try:
                user = await self.bot.fetch_user(int(uid))
                user_name = user.name
            except:
                user_name = f"ID:{uid}"
            results.append(f"✅ {user_name} — **{count}×** {CRATES[crate]['name']} (celkem: **{total}**)")

        embed = discord.Embed(
            title=f"{CRATES[crate]['emoji']} Bedny rozdány",
            description="\n".join(results),
            color=CRATES[crate]["color"],
        )
        await interaction.response.send_message(embed=embed)

    @summon_group.command(name="open", description="Otevřít bednu a summonovat kartu")
    @app_commands.describe(crate="Typ bedny (výchozí: základní)")
    @app_commands.choices(crate=[
        app_commands.Choice(name="Základní bedna", value="basic"),
    ])
    async def open_crate(self, interaction: discord.Interaction, crate: str = "basic"):
        """Otevře bednu — animace a náhodná karta do inventáře."""
        uid = str(interaction.user.id)
        crate_data = CRATES.get(crate)
        if not crate_data:
            await interaction.response.send_message("Taková bedna neexistuje.", ephemeral=True)
            return

        if uid in self._opening:
            await interaction.response.send_message(
                "Jednu bednu už otevíráš — počkej, než dopadne.", ephemeral=True
            )
            return

        if get_crates(uid).get(crate, 0) < 1:
            await interaction.response.send_message(
                f"Nemáš žádnou **{crate_data['name']}**. Zeptej se adminů na `/summon give`.",
                ephemeral=True,
            )
            return

        self._opening.add(uid)
        change_crates(uid, crate, -1)
        try:
            await self._run_opening(interaction, crate, crate_data)
        except Exception:
            change_crates(uid, crate, 1)
            raise
        finally:
            self._opening.discard(uid)

    async def _run_opening(self, interaction: discord.Interaction, crate: str, crate_data: dict):
        """Odehraje animaci otevírání a nakonec přidělí kartu."""
        await interaction.response.defer()

        embed = discord.Embed(
            title=f"{crate_data['emoji']} Otevíráš: {crate_data['name']}",
            description="*Pečeť praská…*",
            color=crate_data["color"],
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)

        gif_path = get_crate_gif_path(crate)
        files = []
        if gif_path:
            files.append(discord.File(gif_path, filename="crate_open.gif"))
            embed.set_image(url="attachment://crate_open.gif")

        message = await interaction.followup.send(embed=embed, files=files, wait=True)
        await asyncio.sleep(GIF_DURATION)

        tickets = random.randint(1, MAX_TICKETS)
        clovers_before = get_luck(str(interaction.user.id)).get("clovers", 0)

        for i in range(1, tickets + 1):
            embed.description = (
                f"*Sbíráš lístky štěstí…*\n\n"
                f"{ticket_bar(i, MAX_TICKETS)}\n**{i}/{MAX_TICKETS}**"
            )
            await message.edit(embed=embed)
            await asyncio.sleep(TICKET_STEP)

        # 10/10 lístků se přelije do dlouhodobého čtyřlístkového štěstí.
        # To je přesně ten dramatický moment po naplnění 1/10.
        jackpot = tickets == MAX_TICKETS
        if jackpot:
            clovers_after = add_clover(str(interaction.user.id))
            embed.description = (
                "🍀 **JACKPOT!!!!** 🍀\n\n"
                f"{ticket_bar(MAX_TICKETS, MAX_TICKETS)}\n"
                f"Čtyřlístky štěstí: **{clovers_after}/{MAX_CLOVERS}**\n"
                f"{clover_bar(clovers_after, MAX_CLOVERS)}"
            )
            await message.edit(embed=embed)
            await asyncio.sleep(1.25)
        else:
            clovers_after = clovers_before
            embed.description = (
                f"*Máš **{tickets}** "
                f"{'lístek' if tickets == 1 else 'lístky' if tickets < 5 else 'lístků'} štěstí!*\n\n"
                f"{ticket_bar(tickets, MAX_TICKETS)}\n"
                f"🍀 Čtyřlístky: **{clovers_after}/{MAX_CLOVERS}**"
            )
            await message.edit(embed=embed)
            await asyncio.sleep(0.8)

        luck_value = total_luck(tickets, clovers_after)

        for delay, frame in zip(ROLL_DELAYS, get_roll_images(len(ROLL_DELAYS))):
            roll_embed = discord.Embed(
                title="🌀 Karty se točí…",
                description=f"{ticket_bar(tickets, MAX_TICKETS)}\n🍀 {clover_bar(clovers_after, MAX_CLOVERS)}",
                color=crate_data["color"],
            )
            roll_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            roll_embed.set_image(url=f"attachment://{os.path.basename(frame)}")
            await message.edit(
                embed=roll_embed,
                attachments=[discord.File(frame, filename=os.path.basename(frame))],
            )
            await asyncio.sleep(delay)

        granted = grant_random_card(str(interaction.user.id), luck=luck_value)
        if not granted:
            await message.edit(
                embed=discord.Embed(
                    title="📦 Bedna je prázdná",
                    description="Databáze karet neobsahuje žádný vzor — bedna se ti vrátila.",
                    color=0xE74C3C,
                ),
                attachments=[],
            )
            change_crates(str(interaction.user.id), crate, 1)
            return

        unique_id, card = granted
        showcase = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                build_showcase_image,
                card,
                unique_id,
                owner_name=interaction.user.display_name,
                tickets=f"{tickets}/{MAX_TICKETS}  ·  🍀 {clovers_after}/{MAX_CLOVERS}",
            ),
        )
        if showcase is None:
            await message.edit(
                content=f"🎴 {interaction.user.mention} vysummonoval **{card.get('name')}** — obrázek karty chybí.",
                embed=None,
                attachments=[],
            )
            return

        await message.edit(
            content=f"🎴 {interaction.user.mention} vysummonoval **{card.get('name')}**!",
            embed=None,
            attachments=[discord.File(showcase, filename="card.png")],
        )


async def setup(bot):
    """Registruje cog do bota."""
    await bot.add_cog(Summon(bot))