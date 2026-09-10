import asyncio
import os
import random
from datetime import datetime, timedelta, timezone
from functools import partial
from zoneinfo import ZoneInfo
import discord
from discord import app_commands
from discord.ext import commands
from src.core.bot.cards import (
    KeepBurnView,
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

DAILY_DATA = _data("summon_daily.json")
DAILY_REWARD_CRATE = "basic"
# Reset o půlnoci podle českého času, ne posouvající se 24h okno od posledního
# vyzvednutí — jinak by se čas nároku každý den o kousek posouval dál.
DAILY_RESET_TZ = ZoneInfo("Europe/Prague")

# Prodlevy jednotlivých fází animace (sekundy)
GIF_DURATION = 3.0
TICKET_STEP = 0.5
ROLL_DELAYS = [0.35, 0.35, 0.45, 0.55, 0.7, 0.9, 1.1]

# Konfetové snímky pro wow efekt při 5/5 jackpotu (garantovaná Legendary + Shiny)
JACKPOT_FX_FRAMES = [
    "🎉 🎊 ✨ 🎉 🎊 ✨ 🎉",
    "🎊 ✨ 🎉 🎊 ✨ 🎉 🎊",
    "✨ 🎉 🎊 ✨ 🎉 🎊 ✨",
]


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


def ticket_bar(current: int, total: int) -> str:
    """Řádek lístků štěstí — naskákané a zbývající prázdná místa."""
    return f"{TICKET_EMOJI * current}{'▫️' * (total - current)}"


def clover_bar(current: int, total: int) -> str:
    """Řádek čtyřlístků — dlouhodobé štěstí hráče."""
    return f"{'🍀' * current}{'▫️' * (total - current)}"


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


def reset_clovers(uid: str) -> int:
    """Resetuje čtyřlístkový meter po dosažení 5/5 jackpotu."""
    luck = load_luck()
    state = luck.setdefault(uid, {"clovers": 0})
    state["clovers"] = 0
    save_json(LUCK_DATA, luck)
    return 0


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
        self._claiming_daily: set[str] = set()

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
                color=0x3498DB,
            )
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            if gif_path:
                files.append(discord.File(gif_path, filename="daily_open.gif"))
                embed.set_image(url="attachment://daily_open.gif")
            await interaction.response.send_message(embed=embed, files=files)
            message = await interaction.original_response()
            await asyncio.sleep(0.9)

            embed.description = "✨ Prach se sype ven, odměna je skoro tady…"
            await message.edit(embed=embed)
            await asyncio.sleep(0.9)

            remaining_to_next = _next_reset_at(now) - now
            final_embed = discord.Embed(
                title="🎁 Denní odměna vyzvednuta!",
                description=(
                    f"### +1× {crate_data['emoji']} {crate_data['name']}\n"
                    f"-# {crate_data['description']}"
                ),
                color=0xF5B942,
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

    @summon_group.command(name="admin-jackpot", description="[ADMIN] Otestovat 5/5 jackpot bez změny reálného luck metru")
    @app_commands.checks.has_permissions(administrator=True)
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
        change_crates(uid, crate, -1)
        try:
            await self._run_opening(interaction, crate, crate_data)
        except Exception:
            change_crates(uid, crate, 1)
            raise
        finally:
            self._opening.discard(uid)

    async def _play_jackpot_fx(self, message: discord.Message, interaction: discord.Interaction):
        """Konfetový wow efekt při dosažení 5/5 čtyřlístků — garantovaná Legendary + Shiny karta."""
        for frame in JACKPOT_FX_FRAMES * 2:
            fx_embed = discord.Embed(
                title="🌟 JACKPOT 5/5 🌟",
                description=f"{frame}\n\n**GARANTOVANÁ LEGENDARY ✨ SHINY KARTA!**\n{frame}",
                color=0xFFD700,
            )
            fx_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            await message.edit(embed=fx_embed, attachments=[])
            await asyncio.sleep(0.3)

        final_embed = discord.Embed(
            title="🎉🎊 JACKPOT!!! 🎊🎉",
            description=(
                "🍀🍀🍀🍀🍀\n\n"
                "**5/5 ČTYŘLÍSTKŮ DOSAŽENO!**\n"
                "Aurionis se otřásá v základech — čeká tě garantovaná **LEGENDARY ✨ SHINY** karta!"
            ),
            color=0xFFD700,
        )
        final_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await message.edit(embed=final_embed, attachments=[])
        await asyncio.sleep(1.5)

    async def _fail_opening(self, message: discord.Message):
        """
        Best-effort úprava zprávy do jasného chybového stavu, když se animace
        uprostřed něčeho pokazí (např. 413 od Discordu na moc velký obrázek) —
        ať zpráva nezůstane navždy viset na '🌀 Karty se točí…'.
        """
        try:
            await message.edit(
                content=None,
                embed=discord.Embed(
                    title="⚠️ Otevírání se nepovedlo",
                    description="Něco se pokazilo uprostřed animace. Zkus to prosím znovu.",
                    color=0xE74C3C,
                ),
                attachments=[],
                view=None,
            )
        except discord.HTTPException:
            pass

    async def _run_opening(
        self,
        interaction: discord.Interaction,
        crate: str,
        crate_data: dict,
        *,
        forced_tickets: int = None,
        forced_clovers: int = None,
        is_test: bool = False,
    ):
        """
        Odehraje animaci otevírání a nakonec přidělí kartu.

        forced_tickets/forced_clovers/is_test slouží jen pro /summon admin-jackpot —
        umožní vynutit a vizuálně otestovat 5/5 jackpot scénář, aniž by se sáhlo
        na reálný stav beden nebo dlouhodobého luck metru hráče.
        """
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

        try:
            await asyncio.sleep(GIF_DURATION)

            tickets = forced_tickets if forced_tickets is not None else random.randint(1, MAX_TICKETS)
            clovers_before = (
                forced_clovers
                if forced_clovers is not None
                else (0 if is_test else get_luck(str(interaction.user.id)).get("clovers", 0))
            )
            tickets = max(1, min(MAX_TICKETS, int(tickets)))
            clovers_before = max(0, min(MAX_CLOVERS, int(clovers_before)))

            for i in range(1, tickets + 1):
                embed.description = (
                    f"*Sbíráš lístky štěstí…*\n\n"
                    f"{ticket_bar(i, MAX_TICKETS)}\n**{i}/{MAX_TICKETS}**"
                )
                await message.edit(embed=embed)
                await asyncio.sleep(TICKET_STEP)

            # 10/10 lístků přidá jeden čtyřlístek do luck metru.
            # Testovací režim nesmí měnit reálný luck meter hráče.
            if tickets == MAX_TICKETS:
                clovers_after = (
                    clovers_before
                    if is_test
                    else add_clover(str(interaction.user.id))
                )
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

            guaranteed_jackpot = clovers_after >= MAX_CLOVERS

            for delay, frame in zip(ROLL_DELAYS, get_roll_images(len(ROLL_DELAYS))):
                roll_embed = discord.Embed(
                    title="🌀 Karty se točí…",
                    description=f"{ticket_bar(tickets, MAX_TICKETS)}\n🍀 {clover_bar(clovers_after, MAX_CLOVERS)}",
                    color=crate_data["color"],
                )
                roll_embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
                roll_embed.set_image(url=f"attachment://{os.path.basename(frame)}")
                try:
                    await message.edit(
                        embed=roll_embed,
                        attachments=[discord.File(frame, filename=os.path.basename(frame))],
                    )
                except discord.HTTPException:
                    # Jeden vadný/moc velký snímek nesmí spadnout celou animaci —
                    # pokračuj bez obrázku a jeď dál.
                    roll_embed.set_image(url=None)
                    await message.edit(embed=roll_embed, attachments=[])
                await asyncio.sleep(delay)

            if guaranteed_jackpot:
                await self._play_jackpot_fx(message, interaction)

            granted = grant_random_card(
                str(interaction.user.id),
                tickets=tickets,
                clovers=clovers_after,
                guaranteed_jackpot=guaranteed_jackpot,
            )
            if not granted:
                await message.edit(
                    embed=discord.Embed(
                        title="📦 Bedna je prázdná",
                        description="Databáze karet neobsahuje žádný vzor — bedna se ti vrátila.",
                        color=0xE74C3C,
                    ),
                    attachments=[],
                )
                if not is_test:
                    change_crates(str(interaction.user.id), crate, 1)
                return

            unique_id, card = granted
            if guaranteed_jackpot and not is_test:
                reset_clovers(str(interaction.user.id))
                clovers_after = 0
            elif guaranteed_jackpot and is_test:
                clovers_after = 0  # jen pro zobrazení v showcase, reálný luck meter zůstává netknutý
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
            view = KeepBurnView(uid=str(interaction.user.id), unique_id=unique_id, card=card)

            if showcase is None:
                await message.edit(
                    content=f"🎴 {interaction.user.mention} vysummonoval **{card.get('name')}** — obrázek karty chybí.",
                    embed=None,
                    attachments=[],
                    view=view,
                )
                view.message = message
                return

            await message.edit(
                content=f"🎴 {interaction.user.mention} vysummonoval **{card.get('name')}**!",
                embed=None,
                attachments=[discord.File(showcase, filename="card.png")],
                view=view,
            )
            view.message = message
        except Exception:
            await self._fail_opening(message)
            raise


async def setup(bot):
    """Registruje cog do bota."""
    await bot.add_cog(Summon(bot))