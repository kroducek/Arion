import asyncio
import io
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import discord
from discord import app_commands
from discord.ext import commands
from src.core.cards.cards import (
    BRAND_PURPLE,
    KeepBurnView,
    build_showcase_image,
    get_card_image_path,
    check_collection_achievement,
)
from src.utils.json_utils import load_json, save_json, update_json
from src.utils.paths import CARDS_CRATES, CARDS_DATA, CARDS_DIR, CRATES_DIR, data as _data
from src.utils.admin_gate import admin_only
from src.core.cards.summon_render import render_opening
from src.core.cards.summon_reward import settle_opening, NoCrates, EmptyCardPool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konstanty
# ---------------------------------------------------------------------------

CRATES = {
    "basic": {
        "name": "Základní bedna",
        "emoji": "📦",
        "color": 0xC27C0E,
        "description": "Uvnitř tě čeká jedna karta.",
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

DAILY_DATA = _data("summon_daily.json")
DAILY_REWARD_CRATE = "basic"
# Reset o půlnoci podle českého času, ne posouvající se 24h okno od posledního
# vyzvednutí — jinak by se čas nároku každý den o kousek posouval dál.
DAILY_RESET_TZ = ZoneInfo("Europe/Prague")

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
    def ensure(crates):
        crates.setdefault(uid, dict(STARTER_CRATES))
        return crates
    return update_json(CARDS_CRATES, ensure)[uid]


def change_crates(uid: str, crate_id: str, amount: int) -> int:
    """Atomic with summon settlement, including grants from the admin bot."""
    def change(crates):
        owned = crates.setdefault(uid, dict(STARTER_CRATES))
        owned[crate_id] = max(0, owned.get(crate_id, 0) + amount)
        return crates
    return update_json(CARDS_CRATES, change)[uid][crate_id]


def get_crate_gif_path(crate_id: str, previous: str = None):
    """Choose an existing crate GIF, avoiding the previous one when possible."""
    crate_data = CRATES.get(crate_id, {})
    names = crate_data.get("gifs") or [crate_data.get("gif")]
    paths = [os.path.join(CRATES_DIR, name) for name in names if name]
    paths = [path for path in paths if os.path.isfile(path)]
    choices = [path for path in paths if path != previous] or paths
    return random.choice(choices) if choices else None


# Bezpečná hranice pod Discord upload limitem i na neboostnutých serverech —
# obrázky nad touto velikostí se do rychle se měnící animace nezařadí.
MAX_ROLL_IMAGE_BYTES = 8 * 1024 * 1024


def get_roll_images(count: int) -> list:
    """Vybere obrázky karet pro rolovací animaci — nikdy dva stejné za sebou, nikdy moc velký soubor."""
    def _size_ok(p: str) -> bool:
        try:
            return os.path.getsize(p) <= MAX_ROLL_IMAGE_BYTES
        except OSError:
            return False

    paths = [
        p for p in (
            get_card_image_path(card.get("image"))
            for card in load_json(CARDS_DATA, default=[])
        ) if p and _size_ok(p)
    ]
    if not paths and os.path.isdir(CARDS_DIR):
        paths = [
            os.path.join(CARDS_DIR, f)
            for f in sorted(os.listdir(CARDS_DIR))
            if f.lower().endswith((".png", ".jpg", ".jpeg")) and _size_ok(os.path.join(CARDS_DIR, f))
        ]
    if not paths:
        return []

    frames = []
    for _ in range(count):
        choices = [p for p in paths if p != (frames[-1] if frames else None)] or paths
        frames.append(random.choice(choices))
    return frames


def luck_embed(tickets: int, clovers: int, *, jackpot=False, remaining=None):
    """Separate embed keeps emoji meters below the animation/result image."""
    embed = discord.Embed(color=BRAND_PURPLE)
    embed.add_field(name=f"Lístky štěstí · {tickets}/{MAX_TICKETS}",
                    value=TICKET_EMOJI * tickets + "▫️" * (MAX_TICKETS - tickets), inline=False)
    embed.add_field(name=f"Čtyřlístky štěstí · {clovers}/{MAX_CLOVERS}",
                    value="🍀" * clovers + "▫️" * (MAX_CLOVERS - clovers), inline=False)
    if jackpot:
        embed.description = "🌟 **JACKPOT · Legendary Shiny!**"
        if remaining is not None:
            embed.set_footer(text=f"Po jackpotu začínáš znovu · {remaining}/{MAX_CLOVERS} čtyřlístků")
    elif tickets == MAX_TICKETS:
        embed.description = "🍀 **Dokonalé štěstí · +1 čtyřlístek**"
    return embed


def streak_bar(streak: int, cap: int = 7) -> str:
    """Řádek streaku — plamínky za dosažené dny v rámci týdenního cyklu (nad cap se jen dopočítávají čísla)."""
    filled = min(streak, cap)
    return f"{'🔥' * filled}{'▫️' * (cap - filled)}"


def format_remaining(delta: timedelta) -> str:
    """Naformátuje zbývající čas jako 'Xh Ym'."""
    hours, rem = divmod(int(delta.total_seconds()), 3600)
    minutes = rem // 60
    return f"{hours}h {minutes}m"


def load_luck() -> dict:
    """Načte dlouhodobé štěstí hráčů."""
    return load_json(LUCK_DATA, default={})


def get_luck(uid: str) -> dict:
    """Vrátí stav štěstí hráče a doplní bezpečné výchozí hodnoty."""
    def ensure(luck):
        state = luck.setdefault(uid, {"clovers": 0})
        state["clovers"] = max(0, min(MAX_CLOVERS, int(state.get("clovers", 0))))
        return luck
    return update_json(LUCK_DATA, ensure)[uid]


def load_daily() -> dict:
    """Načte stav denních odměn všech hráčů."""
    return load_json(DAILY_DATA, default={})


def _parse_utc(iso_str: str) -> datetime:
    """Naparsuje ISO timestamp a doplní UTC, pokud v něm chybí timezone."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _local_date(dt: datetime):
    """Vrátí kalendářní datum daného okamžiku v DAILY_RESET_TZ — podle toho se pozná, jestli je 'ještě dnes'."""
    return dt.astimezone(DAILY_RESET_TZ).date()


def _next_reset_at(now: datetime) -> datetime:
    """Vrátí okamžik nejbližší půlnoci v DAILY_RESET_TZ od zadaného 'now' (v UTC)."""
    today_local = _local_date(now)
    midnight_local = datetime.combine(
        today_local + timedelta(days=1), datetime.min.time(), tzinfo=DAILY_RESET_TZ
    )
    return midnight_local.astimezone(timezone.utc)


def days_word(n: int) -> str:
    """Skloňuje slovo 'den' podle počtu — 1 den / 2-4 dny / 5+ dní."""
    if n == 1:
        return "den"
    if 2 <= n <= 4:
        return "dny"
    return "dní"


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Summon(commands.Cog):
    """Otevírání beden s kartami."""

    def __init__(self, bot):
        self.bot = bot
        self._opening: set[str] = set()
        self._render_slot = asyncio.Semaphore(1)
        self._last_crate_gif: dict[str, str] = {}
        self._claiming_daily: set[str] = set()

    summon_group = app_commands.Group(name="summon", description="Summonování karet z beden")

    @summon_group.command(name="crates", description="Přehled tvých beden")
    async def show_crates(self, interaction: discord.Interaction):
        """Vypíše bedny v inventáři hráče."""
        owned = get_crates(str(interaction.user.id))

        embed = discord.Embed(
            title="📦 Tvé bedny",
            description="Otevři je příkazem `/summon open`.",
            color=BRAND_PURPLE,
        )
        for crate_id, crate in CRATES.items():
            embed.add_field(
                name=f"{crate['emoji']} {crate['name']}",
                value=f"**{owned.get(crate_id, 0)}×**\n*{crate['description']}*",
                inline=True,
            )
        embed.set_footer(text="⚜️ Aurionis")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @summon_group.command(name="daily", description="Vyzvedni si denní odměnu (jednou za 24 hodin)")
    async def daily(self, interaction: discord.Interaction):
        """Denní odměna — 1× Základní bedna. Počítá se i day streak a nejdelší streak."""
        uid = str(interaction.user.id)

        if uid in self._claiming_daily:
            await interaction.response.send_message(
                "Odměnu si už vyzvedáváš — chvilku počkej.", ephemeral=True
            )
            return

        now = datetime.now(timezone.utc)
        today = _local_date(now)
        data = load_daily()
        state = data.get(uid, {"last_claim": None, "streak": 0, "max_streak": 0})

        last_claim_raw = state.get("last_claim")
        if last_claim_raw:
            last_claim = _parse_utc(last_claim_raw)
            last_date = _local_date(last_claim)

            if last_date == today:
                remaining = _next_reset_at(now) - now
                await interaction.response.send_message(
                    f"⏳ Dnešní odměnu jsi už vyzvedl. Resetuje se o půlnoci — zkus to znovu za **{format_remaining(remaining)}**.",
                    ephemeral=True,
                )
                return

            days_gap = (today - last_date).days
            new_streak = state.get("streak", 0) + 1 if days_gap == 1 else 1
        else:
            new_streak = 1

        streak_broken = bool(last_claim_raw) and new_streak == 1 and state.get("streak", 0) > 1
        new_max_streak = max(state.get("max_streak", 0), new_streak)
        is_new_record = new_streak > 1 and new_streak > state.get("max_streak", 0)

        self._claiming_daily.add(uid)
        try:
            data[uid] = {
                "last_claim": now.isoformat(),
                "streak": new_streak,
                "max_streak": new_max_streak,
            }
            save_json(DAILY_DATA, data)
            change_crates(uid, DAILY_REWARD_CRATE, 1)

            crate_data = CRATES[DAILY_REWARD_CRATE]
            gif_path = get_crate_gif_path(DAILY_REWARD_CRATE)
            files = []

            embed = discord.Embed(
                title="📅 Denní odměna",
                description="*Kalendář se s vrzáním otáčí…*",
                color=BRAND_PURPLE,
            )
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            if gif_path:
                files.append(discord.File(gif_path, filename="daily_open.gif"))
                embed.set_image(url="attachment://daily_open.gif")
            await interaction.response.send_message(embed=embed, files=files)
            message = await interaction.original_response()
            await asyncio.sleep(0.9)

            embed.description = "✨ ...A prach se sype ven, odměna je skoro tady."
            await message.edit(embed=embed)
            await asyncio.sleep(0.9)

            remaining_to_next = _next_reset_at(now) - now
            final_embed = discord.Embed(
                title="🎁 Denní odměna vyzvednuta!",
                description=(
                    f"### +1× {crate_data['emoji']} {crate_data['name']}\n"
                    f"-# {crate_data['description']}"
                ),
                color=BRAND_PURPLE,
            )
            final_embed.set_author(name=f"{interaction.user.display_name} • Denní odměna", icon_url=interaction.user.display_avatar.url)
            final_embed.set_thumbnail(url=interaction.user.display_avatar.url)
            final_embed.add_field(
                name="🔥 Streak",
                value=f"{streak_bar(new_streak)}\n**{new_streak}** {days_word(new_streak)} v kuse",
                inline=False,
            )
            final_embed.add_field(
                name="🏆 Rekord",
                value=f"**{new_max_streak}** {days_word(new_max_streak)}" + (" 🆕" if is_new_record else ""),
                inline=True,
            )
            final_embed.add_field(
                name="🕛 Další odměna",
                value=f"za **{format_remaining(remaining_to_next)}**",
                inline=True,
            )
            if streak_broken:
                final_embed.set_footer(text="💔 Streak spadl, protože sis odměnu nevyzvedl včas — jedeš znovu od 1. Vrať se zítra!")
            elif is_new_record:
                final_embed.set_footer(text="🆕 Nové osobní maximum! Vrať se zítra a posuň ho ještě dál.")
            else:
                final_embed.set_footer(text="Vrať se zítra, ať streak nespadne!")
            await message.edit(embed=final_embed, attachments=[])
        finally:
            self._claiming_daily.discard(uid)

    @summon_group.command(name="give", description="[ADMIN] Přidat bedny více hráčům najednou")
    @admin_only()
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

    @summon_group.command(name="admin-jackpot", description="[ADMIN] Otestovat 5/5 jackpot bez změny reálného luck metru")
    @admin_only()
    @app_commands.describe(crate="Typ bedny, na které chceš jackpot otestovat")
    @app_commands.choices(crate=[
        app_commands.Choice(name="Základní bedna", value="basic"),
    ])
    async def admin_jackpot(self, interaction: discord.Interaction, crate: str = "basic"):
        """[ADMIN] Spustí testovací 5/5 jackpot scénář bez odečtení bedny a bez změny luck metru."""
        crate_data = CRATES.get(crate)
        if not crate_data:
            await interaction.response.send_message("Taková bedna neexistuje.", ephemeral=True)
            return

        uid = str(interaction.user.id)
        if uid in self._opening:
            await interaction.response.send_message(
                "Jednu bednu už právě otevíráš — počkej, než dopadne.", ephemeral=True
            )
            return

        self._opening.add(uid)
        try:
            await self._run_opening(
                interaction,
                crate,
                crate_data,
                forced_tickets=MAX_TICKETS,
                forced_clovers=MAX_CLOVERS,
                is_test=True,
            )
        finally:
            self._opening.discard(uid)

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
        try:
            await self._run_opening(interaction, crate, crate_data)
        finally:
            self._opening.discard(uid)

    async def _run_opening(
        self, interaction, crate, crate_data, *, forced_tickets=None,
        forced_clovers=None, is_test=False,
    ):
        """Commit once, then present. Display errors never refund a granted card."""
        await interaction.response.defer()
        intro = discord.Embed(
            title="Pečeť se probouzí",
            description=f"{crate_data['name']} · Připravuji otevření…",
            color=BRAND_PURPLE,
        )
        intro.set_author(name=interaction.user.display_name,
                         icon_url=interaction.user.display_avatar.url)
        if is_test:
            intro.set_footer(text="ADMIN NÁHLED · bez změny inventáře a štěstí")
        # If this fails, nothing has been charged yet.
        gif_path = get_crate_gif_path(crate, self._last_crate_gif.get(crate))
        files = []
        if gif_path:
            self._last_crate_gif[crate] = gif_path
            intro.set_image(url="attachment://crate_open.gif")
            files.append(discord.File(gif_path, filename="crate_open.gif"))
        message = await interaction.followup.send(embed=intro, files=files, wait=True)
        try:
            reward = settle_opening(
                str(interaction.user.id), crate,
                forced_tickets if forced_tickets is not None else random.randint(1, MAX_TICKETS),
                preview=is_test, forced_clovers=forced_clovers,
            )
        except (NoCrates, EmptyCardPool) as error:
            text = "Nemáš žádnou bednu tohoto typu." if isinstance(error, NoCrates) else "Databáze karet je prázdná. Bedna zůstává u tebe."
            await message.edit(embed=discord.Embed(title="Otevření není dostupné", description=text,
                                                  color=BRAND_PURPLE), attachments=[])
            return
        except Exception:
            logger.exception("Summon settlement failed; transaction rolled back")
            await message.edit(embed=discord.Embed(title="Otevření se nepovedlo",
                description="Bedna zůstává u tebe. Zkus to znovu.", color=BRAND_PURPLE), attachments=[])
            return

        # Everything below is presentation of an already committed reward.
        showcase = None
        try:
            # Bound peak memory/CPU. Under load reveal immediately instead of queueing GIFs.
            if not self._render_slot.locked():
                async with self._render_slot:
                    animation, duration = await asyncio.to_thread(
                        render_opening, reward.card, get_card_image_path(reward.card.get("image")),
                        get_roll_images(8),
                        jackpot=reward.jackpot,
                        max_bytes=min(MAX_ROLL_IMAGE_BYTES, getattr(interaction, "filesize_limit", MAX_ROLL_IMAGE_BYTES)),
                    )
                intro.title = "Odhalení karty"
                intro.description = "Pečeť · štěstí · výběr · odhalení"
                intro.set_image(url="attachment://summon.gif")
                await message.edit(embeds=[intro, luck_embed(reward.tickets, reward.clovers, jackpot=reward.jackpot)],
                                   attachments=[discord.File(io.BytesIO(animation), filename="summon.gif")])
                await asyncio.sleep(duration + 0.4)
        except Exception:
            logger.exception("Summon animation unavailable; revealing committed reward")

        try:
            showcase = await asyncio.to_thread(
                build_showcase_image, reward.card, reward.unique_id,
                owner_name=interaction.user.display_name,
            )
        except Exception:
            logger.exception("Summon showcase unavailable; using text result")

        card = reward.card
        prefix = "ADMIN NÁHLED · " if is_test else ""
        summary = (
            f"{prefix}**{card.get('name', 'Karta')}** · "
            f"{card.get('rarity', '').capitalize()} / {card.get('quality', '').capitalize()}\n"
            + ("Testovací karta se neukládá." if is_test else
               f"Karta je v inventáři {interaction.user.mention}. ID: `{reward.unique_id}`")
        )
        view = None if is_test else KeepBurnView(uid=str(interaction.user.id),
                                                 unique_id=reward.unique_id, card=card)
        meters = luck_embed(reward.tickets, reward.clovers, jackpot=reward.jackpot,
                            remaining=reward.remaining_clovers if not is_test else None)
        result_embeds = [meters]
        if showcase:
            card_embed = discord.Embed(color=BRAND_PURPLE)
            card_embed.set_image(url="attachment://card.png")
            result_embeds.insert(0, card_embed)
        try:
            await message.edit(content=summary, embeds=result_embeds,
                attachments=[discord.File(showcase, filename="card.png")] if showcase else [], view=view)
            if view:
                view.message = message
        except Exception:
            logger.exception("Final reveal failed; reward remains in inventory")
            try:
                # Covers rejected attachments and a deleted original message.
                result_message = await interaction.followup.send(summary, embed=meters, view=view, wait=True)
                if view:
                    view.message = result_message
            except Exception:
                logger.exception("Unable to notify player of committed summon reward")
        if not is_test:
            try:
                await check_collection_achievement(interaction.user, interaction.channel)
            except Exception:
                logger.exception("Collection announcement failed after summon")


async def setup(bot):
    """Registruje cog do bota."""
    await bot.add_cog(Summon(bot))