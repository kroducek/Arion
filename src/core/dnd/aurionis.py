"""
Aurionis Cog - Hlavní rozcestník pro ArionBot
Tento soubor obsahuje základní info, ping, kroniku a turnajový systém.
Zbytek mechanik (Roll, Combat, Party, Countdown) je ve vlastních souborech.
"""
import discord
import random
import json
import os
from discord.ext import commands
from discord import app_commands

from src.utils.paths import TOURNAMENT as TOURNAMENT_FILE
from src.utils.json_utils import load_json, save_json

def _load_tournament() -> list:
    """Thread-safe load tournament data."""
    data = load_json(TOURNAMENT_FILE, default=[])
    return data if isinstance(data, list) else []

def _save_tournament(data: list):
    """Thread-safe save tournament data."""
    save_json(TOURNAMENT_FILE, data)

_CLOCK_EMOJIS = ["🕛","🕐","🕑","🕒","🕓","🕔","🕕","🕖","🕗","🕘","🕙","🕚"]

def _clock_sequence(hours: int) -> str:
    start = random.randint(0, 11)
    if hours + 1 <= 10:
        return " ".join(_CLOCK_EMOJIS[(start + i) % 12] for i in range(hours + 1))
    return " ".join(_CLOCK_EMOJIS[(start + round(i * hours / 9)) % 12] for i in range(10))

def _hours_cz(n: int) -> str:
    if n == 1: return "hodina"
    if n <= 4: return "hodiny"
    return "hodin"

# ============================================================
#  KRONIKA — interaktivní rozcestník (/kronika)
# ============================================================
#  Struktura: HOME -> BOT -> KATEGORIE -> příkazy
#  Pro doplnění příkazů uprav slovník KRONIKA níže — UI se
#  vygeneruje samo (tlačítka, embedy, řádky).
# ============================================================

KRONIKA_TIMEOUT = 180  # sekund, než tlačítka zšednou

KRONIKA = {
    "ariondnd": {
        "label": "ArionDND",
        "emoji": "⚔️",
        "color": 0xFFA500,
        "intro": "*Arion otevře tlustou živoucí knihu D&D mechanik a začne listovat...*",
        "footer": "ArionDND · Aurionis Act II",
        "categories": {
            "roll": {
                "label": "Roll & Check",
                "emoji": "🎲",
                "commands": (
                    "`/roll` — Hod kostkami (1d20+2d4+5...)\n"
                    "`/roll check:` — Check atributu (porovná s tvým statem)\n"
                    "`/roll check: check2:` — Kombinovaný check (průměr dvou statů)\n"
                    "`/show_rolls` — Statistiky tvých hodů"
                ),
            },
            "combat": {
                "label": "Combat",
                "emoji": "⚔️",
                "commands": (
                    "`/combat_start` — Zahájit boj\n"
                    "`/combat_join` — Zapojit se do boje\n"
                    "`/combat_add_npc` — Přidat NPC/potvoru\n"
                    "`/next` — Předat tah dalšímu\n"
                    "`/combat_end` — Ukončit boj"
                ),
            },
            "party": {
                "label": "Party",
                "emoji": "🤝",
                "commands": (
                    "`/party` — Zobraz svou partu\n"
                    "`/party set` — Nastavení party"
                ),
            },
            "postava": {
                "label": "Postava & Deník",
                "emoji": "📖",
                "commands": (
                    "`/profile` — Průkaz dobrodruha\n"
                    "`/profile-edit` — Upravit průkaz\n"
                    "`/eat` — Sněz jídlo z inventáře\n"
                    "`/diary add/show` — Deník postavy\n"
                    "`/memory show/add/remove/edit` — Vzpomínky postavy"
                ),
            },
            "quest": {
                "label": "Quest",
                "emoji": "📜",
                "commands": (
                    "`/quests` — Aktivní questy\n"
                    "`/quest add` — Přidat quest\n"
                    "`/quest status` — Změnit stav questu\n"
                    "`/quest log` — Záznam průběhu questu"
                ),
            },
            "inventar": {
                "label": "Inventář",
                "emoji": "🎒",
                "commands": (
                    "`/inv` — Zobraz inventář a equipment\n"
                    "`/equip` — Equipni item\n"
                    "`/unequip` — Sundej item ze slotu\n"
                    "`/use` — Použij consumable (lektvar, jídlo...)\n"
                    "`/inv-give` — Pošli item jinému hráči\n"
                    "`/inv-inspect` — Detail itemu z databáze"
                ),
            },
            "gold": {
                "label": "Gold & Shop",
                "emoji": "💰",
                "commands": (
                    "`/g` — Tvůj aktuální zůstatek\n"
                    "`/gsend` — Pošli zlato hráči\n"
                    "`/gleaderboard` — Žebříček bohatství\n"
                    "`/gshop open` — Otevři shop"
                ),
            },
            "reputace": {
                "label": "Reputace",
                "emoji": "🏅",
                "commands": (
                    "`/rep show` — Zobraz reputaci u frakcí\n"
                    "`/rep list` — Přehled hráčů ve frakci"
                ),
            },
            "rp": {
                "label": "RP místnosti",
                "emoji": "🎭",
                "commands": (
                    "`/rp create` — Vytvoř soukromou RP místnost\n"
                    "`/rp join` — Vstup pomocí hesla\n"
                    "`/rp spectate` — Pozvi diváka (vidí + reaguje, nepíše)\n"
                    "`/rp unspectate` — Odeber diváka\n"
                    "`/rp kick` — Vyhoď hráče nebo diváka\n"
                    "`/rp mute` — Ztichni místnost"
                ),
            },
            "turnaj": {
                "label": "Turnaj & Vyvolení",
                "emoji": "🏆",
                "commands": (
                    "`/tournament list` — Postupující do 2. kola\n"
                    "`/vyvoleni list` — Všichni zapsaní dobrodruzi"
                ),
            },
            "duchove": {
                "label": "Strážní duchové",
                "emoji": "👻",
                "commands": (
                    "`/duch seznam` — Tvoji strážní duchové\n"
                    "`/duch info` — Detail konkrétního ducha\n"
                    "`/duch slechtit` — Šlechtění dvou duchů (silnější pohltí slabšího)"
                ),
            },
        },
    },
    "arionbot": {
        "label": "ArionBOT",
        "emoji": "🎮",
        "color": 0x5865F2,
        "intro": "*Arion zamňouká a rozhodí po stole karty a herní kostky...*",
        "footer": "ArionBOT · Minihry, karty & utility",
        "categories": {
            "minihry": {
                "label": "Minihry",
                "emoji": "🎲",
                "commands": (
                    "`/minigames` — Rozcestník všech miniher (lobby jedním klikem)\n"
                    "`/kostky` — Farkle (sázky, magické kostky, boss mode)\n"
                    "`/guess` — Hádej kdo (ano/ne otázky)\n"
                    "`/liardice` — Kostka lháře (bluffování)\n"
                    "`/liarslots` — Liar Slots (sloty + bluff)\n"
                    "`/sibenice` — Šibenice (hádej větu)\n"
                    "`/blackjack` — Blackjack (sázky)"
                ),
            },
            "karty": {
                "label": "Karty",
                "emoji": "🃏",
                "commands": (
                    "`/cards info` — Přehled systému karet\n"
                    "`/cards inventory` — Tvoje karty\n"
                    "`/cards show` — Detail konkrétní karty\n"
                    "`/cards gallery` — Alba kolekcí (sady a karty)\n"
                    "`/cards list` — Dostupné vzory karet v databázi\n"
                    "`/cards upgrade` — Nasaď rámeček na kartu\n"
                    "`/cards frames` — Tvoje rámečky\n"
                    "`/cards burn` — Spal kartu za Hvězdný prach\n"
                    "`/cards set_profile` `/cards profile` — Profilová karta"
                ),
            },
            "vypravy": {
                "label": "Výpravy karet",
                "emoji": "🗺️",
                "commands": (
                    "`/cards work` — Přehled výprav (stav i dostupné expedice)\n"
                    "`/cards work_send` — Vyšli až 3 karty na výpravu za zlatem\n"
                    "`/cards work_status` — Stav tvé výpravy\n"
                    "`/cards work_claim` — Vyzvedni odměnu z dokončené výpravy"
                ),
            },
            "tarot": {
                "label": "Tarot",
                "emoji": "🔮",
                "commands": (
                    "`/tarot den` — Karta dne (zdarma)\n"
                    "`/tarot solo` — Soukromý výklad (50 🪙)\n"
                    "`/tarot session` — Veřejná session"
                ),
            },
            "gold": {
                "label": "Gold & Shop",
                "emoji": "💰",
                "commands": (
                    "`/g` — Tvůj aktuální zůstatek\n"
                    "`/gsend` — Pošli zlato hráči\n"
                    "`/gleaderboard` — Žebříček bohatství\n"
                    "`/gshop open` — Otevři shop"
                ),
            },
            "news": {
                "label": "News & Story",
                "emoji": "📰",
                "commands": (
                    "`/news show` — Nástěnka zpráv\n"
                    "`/story create` — Začni komunitní příběh\n"
                    "`/story add` — Přidej větu do příběhu\n"
                    "`/story show` — Zobraz aktuální příběh"
                ),
            },
            "utility": {
                "label": "Utility",
                "emoji": "🛠️",
                "commands": (
                    "`/poll` — Vytvoř hlasování\n"
                    "`/countdown` — Odpočet\n"
                    "`/voice lock/unlock` — Zamkni/odemkni hlasový kanál\n"
                    "`/voice hide/show` — Skryj/zobraz hlasový kanál"
                ),
            },
        },
    },
    "labyrinth": {
        "label": "Labyrinth",
        "emoji": "🌀",
        "color": 0x2ECC71,
        "intro": "*Arion zmizí ve stínech a otevírá bránu do Labyrintu...*",
        "footer": "Labyrinth · sociální dedukce",
        "categories": {
            "main": {
                "label": "Příkazy",
                "emoji": "🚪",
                "commands": (
                    "`/lobby` — Otevři lobby Door Labyrinthu (sociální dedukce, 4–10 hráčů)"
                ),
            },
        },
    },
}

# --- Admin sekce (zamčená) -------------------------------------------------
KRONIKA_ADMIN = [
    ("🌍 Postavy & svět", (
        "`/vliv` — Uděl hráči Vliv (Světlo/Temnota/Rovnováha)\n"
        "`/takedown` — Arion provede Takedown\n"
        "`/timeskip` — Přeskok v čase (narativní utilita)\n"
        "`/erase all` — Smaže všechny zprávy v místnosti\n"
        "`/hunger-balance` — Simulace hladu v čase\n"
        "`/profile-admin-hp/mana/fury/vliv` — Nastav staty hráče"
    )),
    ("🎒 Reputace & inventář", (
        "`/rep create/add/set/delete` — Správa reputace frakcí\n"
        "`/inv-db-add/edit/find/list` — Databáze itemů\n"
        "`/inv-admin-add/remove/slots` — Inventář hráčů"
    )),
    ("📜 Questy, RP & combat", (
        "`/quest add/status/remove` — Správa questů\n"
        "`/rp info/remove` — Přehled RP místností\n"
        "`/combat_sethp/setdef/remove/setorder` — Combat admin"
    )),
    ("💰 Ekonomika & turnaj", (
        "`/gshop create/edit/close` — Správa shopu\n"
        "`/gadd` `/gremove` — Zlato hráčům\n"
        "`/tournament add/remove` — Správa turnaje\n"
        "`/admin-tutorial-reset` — Reset tutoriálu hráče\n"
        "`/memory admin` — Správa vzpomínek hráčů"
    )),
    ("👻 Strážní duchové", (
        "`/duch pridat` — Přidá hráči nového ducha\n"
        "`/duch xp` — Přidej duchovi XP\n"
        "`/duch equip` `/duch unequip` — Equip/odequip ducha hráči\n"
        "`/duch upravit` — Uprav hodnoty ducha\n"
        "`/duch odebrat` — Trvale odebere ducha z kolekce hráče"
    )),
    ("🎮 ArionBOT — news & karty", (
        "`/news add/delete` — Správa nástěnky zpráv\n"
        "`/cards print` — Vytiskni novou kartu\n"
        "`/cards db_add` — Přidej vzor karty do databáze\n"
        "`/cards give_frame` — Dej rámeček hráči\n"
        "`/cards remove_card` — Smaž kartu z inventáře\n"
        "`/cards pool` — Dej hráči náhodnou kartu z poolu"
    )),
]


def _count_cmds(commands_text: str) -> int:
    """Počet příkazů v textu kategorie (počítá výskyty `/…). Placeholder = 0."""
    if "Doplň" in commands_text:
        return 0
    return commands_text.count("`/")


def _world_counts(bot_key: str) -> tuple[int, int]:
    """(počet příkazů, počet kapitol) daného světa."""
    cats = KRONIKA[bot_key]["categories"]
    cmds = sum(_count_cmds(c["commands"]) for c in cats.values())
    return cmds, len(cats)


def _build_home_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📖 Kronika Aurionis",
        description=(
            "🐾 *Arion nastraží uši a otevře živoucí knihu.*\n\n"
            "**„Ahoj, vítej v kronice! S čím, že ti to mám pomoct?“**\n\n"
            "Vyber si svět níže 👇"
        ),
        color=0xFFD700,
    )
    dnd_c, dnd_k = _world_counts("ariondnd")
    bot_c, bot_k = _world_counts("arionbot")
    lab_c, lab_k = _world_counts("labyrinth")
    embed.add_field(
        name="⚔️ ArionDND",
        value=f"D&D mechaniky, boj, postavy, questy\n-# {dnd_c} příkazů · {dnd_k} kapitol",
        inline=True)
    embed.add_field(
        name="🎮 ArionBOT",
        value=f"Minihry & karty\n-# {bot_c} příkazů · {bot_k} kapitol",
        inline=True)
    embed.add_field(
        name="🌀 Labyrinth",
        value=f"Labyrint a jeho tajemství\n-# {lab_c} příkazů · {lab_k} kapitol",
        inline=True)
    embed.set_footer(text="Aurionis · Act II · klikni na tlačítko · 🔒 Admin sekce dole")
    return embed


def _build_bot_embed(bot_key: str, cat_key=None) -> discord.Embed:
    bot = KRONIKA[bot_key]
    if cat_key is None:
        cmds, kap = _world_counts(bot_key)
        embed = discord.Embed(
            title=f"{bot['emoji']} {bot['label']} — Kronika",
            description=bot["intro"],
            color=bot["color"],
        )
        lines = []
        for c in bot["categories"].values():
            n = _count_cmds(c["commands"])
            badge = f" · {n}" if n else ""
            lines.append(f"{c['emoji']} **{c['label']}**{badge}")
        embed.add_field(name="Vyber kapitolu níže 👇", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"{bot['footer']}  ·  {cmds} příkazů v {kap} kapitolách")
        return embed

    cat = bot["categories"][cat_key]
    embed = discord.Embed(
        title=f"{cat['emoji']} {cat['label']}",
        description=f"*{bot['label']} — kronika*",
        color=bot["color"],
    )
    embed.add_field(name="Příkazy", value=cat["commands"], inline=False)
    embed.set_footer(text=f"{bot['footer']} · ⬅️ Zpět pro výběr světa")
    return embed


def _build_admin_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🔒 Admin — Kronika správců",
        description="*Arion ti pokývla — máš klíč ke správcovské části knihy.*",
        color=0xE74C3C,
    )
    for name, value in KRONIKA_ADMIN:
        embed.add_field(name=name, value=value, inline=False)
    embed.set_footer(text="Aurionis · jen pro správce · ⬅️ Zpět")
    return embed


class _NavButton(discord.ui.Button):
    """Univerzální navigační tlačítko kroniky."""
    def __init__(self, *, label, emoji, style, action, target=None, row=None):
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self.action = action
        self.target = target

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle(interaction, self.action, self.target)


class KronikaView(discord.ui.View):
    """Stavová view: HOME -> BOT -> KATEGORIE / ADMIN."""
    def __init__(self, author_id: int, *, bot_key=None, cat_key=None, admin=False):
        super().__init__(timeout=KRONIKA_TIMEOUT)
        self.author_id = author_id
        self.bot_key = bot_key
        self.cat_key = cat_key
        self.admin = admin
        self.message = None  # discord.Message, nastaví se po odeslání
        self._build()

    # --- sestavení tlačítek podle aktuálního stavu ---
    def _build(self):
        self.clear_items()

        if self.admin:
            self.add_item(_NavButton(label="Zpět", emoji="⬅️",
                                     style=discord.ButtonStyle.primary,
                                     action="home", row=0))
            return

        if self.bot_key is None:
            # HOME — tři boti + admin
            self.add_item(_NavButton(label="ArionDND", emoji="⚔️",
                                     style=discord.ButtonStyle.primary,
                                     action="bot", target="ariondnd", row=0))
            self.add_item(_NavButton(label="ArionBOT", emoji="🎮",
                                     style=discord.ButtonStyle.success,
                                     action="bot", target="arionbot", row=0))
            self.add_item(_NavButton(label="Labyrinth", emoji="🌀",
                                     style=discord.ButtonStyle.secondary,
                                     action="bot", target="labyrinth", row=0))
            self.add_item(_NavButton(label="Admin", emoji="🔒",
                                     style=discord.ButtonStyle.danger,
                                     action="admin", row=1))
            return

        # BOT menu — kategorie + zpět
        bot = KRONIKA[self.bot_key]
        cats = list(bot["categories"].items())
        for idx, (ckey, cat) in enumerate(cats):
            self.add_item(_NavButton(label=cat["label"], emoji=cat["emoji"],
                                     style=discord.ButtonStyle.secondary,
                                     action="category", target=ckey,
                                     row=min(idx // 5, 3)))
        back_row = min((len(cats) - 1) // 5 + 1, 4)
        self.add_item(_NavButton(label="Zpět", emoji="⬅️",
                                 style=discord.ButtonStyle.primary,
                                 action="home", row=back_row))

    # --- jen autor smí ovládat ---
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "🐾 *Tahle kronika patří někomu jinému.* Otevři si vlastní přes `/kronika`.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    # --- routing kliknutí ---
    async def handle(self, interaction: discord.Interaction, action: str, target):
        if action == "home":
            self.bot_key = self.cat_key = None
            self.admin = False
            self._build()
            await interaction.response.edit_message(embed=_build_home_embed(), view=self)

        elif action == "bot":
            self.bot_key, self.cat_key, self.admin = target, None, False
            self._build()
            await interaction.response.edit_message(embed=_build_bot_embed(target, None), view=self)

        elif action == "category":
            self.cat_key = target
            await interaction.response.edit_message(
                embed=_build_bot_embed(self.bot_key, target), view=self
            )

        elif action == "admin":
            perms = getattr(interaction.user, "guild_permissions", None)
            if not (perms and perms.administrator):
                await interaction.response.send_message(
                    "🔒 *Arion ti tlapkou zastoupí cestu.* Tahle část kroniky je jen pro **správce**.",
                    ephemeral=True,
                )
                return
            self.admin, self.bot_key, self.cat_key = True, None, None
            self._build()
            await interaction.response.edit_message(embed=_build_admin_embed(), view=self)


class Aurionis(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"✅ Arion Kronika je připravena k zápisu!")

    # --- ZÁKLADNÍ PŘÍKAZY ---

    @app_commands.command(name="ping", description="Zjistí, jak rychle Arion přiběhne")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🐾 *Arion nastraží uši!* Přiběhla jsem za **{latency}ms**, mňau!")

    @app_commands.command(name="meow", description="Interact with Arion")
    async def meow(self, interaction: discord.Interaction):
        responses = [
            "🐱 *Arion se ti otřela o nohu a spokojeně zamňoukala*",
            "🧶 *Arion ti přinesla virtuální klubíčko. Chce si hrát!*",
            "💤 *Arion spí na tvé klávesnici. Teď nic nenapíšeš*",
            "✨ *Arion upřeně hledí do prázdna za tebou. Vidí něco, co ty ne*",
            "🐾 *Arion ti vyskočila na rameno a jemně tě kousla do ucha*",
            "🐱 *Arion se svalila na záda a ukazuje bříško. Je to past?*",
            "🌙 *Arion tiše přede a její srst slabě světluje v barvách Aurionisu*",
            "🐭 *Arion ti přinesla ulovenou mechanickou myš. Je na sebe hrdá*",
            "🥛 *Arion vylila tvou virtuální kávu. Jen se na tebe drze podívala*",
            "📦 *Arion našla krabici od tvého nového procesoru a okamžitě se do ní nasáčkovala*",
            "🐈 *Arion se protahuje. Vypadá nekonečně dlouhá*",
            "💨 *Arion dostala 'zoomies' a proběhla tvým kanálem rychlostí světla*",
            "👀 *Arion tě sleduje zpoza rohu. Má rozšířené zorničky*",
            "🦋 *Arion se snaží chytit digitálního motýla*",
            "🧼 *Arion si pečlivě olizuje tlapku a ignoruje tvou existenci*",
            "👑 *Arion si sedla na tvůj pomyslný trůn. Teď vládne ona*",
            "🌌 *Arion ti tlapkou ukazuje na vzdálenou hvězdu v systému Aurionis*",
            "🥯 *Arion ukradla tvou svačinu a utekla s ní pod postel*",
            "🛸 *Arion se snaží ulovit laserové ukazovátko z jiné dimenze*",
            "📡 *Arion zachytila signál z hlubokého vesmíru a teď zmateně mňouká na router*",
            "🌵 *Arion se pokusila očichat kaktus. Teď uraženě sedí v koutě*",
            "🍞 *Arion se složila do dokonalého tvaru bochníku chleba*",
            "🧿 *Arioniny oči na vteřinu zazářily jako supernovy*",
            "🎵 *Arion začala příst v rytmu tvé oblíbené hudby*",
            "🧛 *Arion na tebe vybafla ze stínu. Skoro ti vyskočilo srdce*",
            "🧊 *Arion tlapkou shazuje virtuální kostky ledu ze stolu. Jen tak*",
            "🧶 *Arion se zamotala do kabelů od tvého setupu. Pomoz jí!*",
            "💤 *Arion chrápe tak hlasitě, že to vibruje s celým serverem*",
            "🎀 *Arion si hraje s tvým kurzorem myši. Skoro jsi kliknul jinam!*",
            "🧠 *Arion vypadá, že právě pochopila smysl vesmíru. Pak se začala honit za ocasem*",
            "🕵️ *Arion ti prohledává kapsy. Hledá pamlsky, ne důkazy*",
            "🌈 *Arion proskočila duhou a teď chvíli zanechává barevné stopy*",
            "🛑 *Arion si lehla přímo na cestu tvému dalšímu příkazu*",
            "💎 *Arion ti přinesla zářící krystal z hlubin Aurionisu*",
            "🌋 *Arion shodila tvou klávesnici do imaginární lávy*",
            "🛸 *Arion byla na vteřinu unesena UFO, ale vrátili ji, protože moc mňoukala*",
            "🍟 *Arion ti olízla hranolku. Už ji asi nebudeš chtít*",
            "🧹 *Arion útočí na koště. Je to její úhlavní nepřítel*",
            "🌡️ *Arion je tak huňatá, že zvýšila teplotu v kanálu o 2 stupně*",
            "🖤 *Arion se ti schovala do stínu. Vidíš jen její svítící oči*"
        ]
        await interaction.response.send_message(random.choice(responses))

    @app_commands.command(name="erase", description="Smaže všechny zprávy v této místnosti")
    @app_commands.describe(confirmation="Potvrzení smazání všech zpráv (napiš 'all')")
    async def erase(self, interaction: discord.Interaction, confirmation: str):
        if confirmation.lower() != "all":
            await interaction.response.send_message("Pro smazání všech zpráv použij '/erase all'", ephemeral=True)
            return

        # Kontrola oprávnění
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Nemáš oprávnění mazat zprávy.", ephemeral=True)
            return

        channel = interaction.channel

        # Defer odpověď, protože mazání může trvat
        await interaction.response.defer(ephemeral=True)

        try:
            # Smaž všechny zprávy (loop kvůli limitu Discordu)
            deleted_count = 0
            while True:
                deleted = await channel.purge(limit=100)
                deleted_count += len(deleted)
                if len(deleted) < 100:
                    break
            await interaction.followup.send(f"✅ Smazáno {deleted_count} zpráv v této místnosti.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Nemám oprávnění mazat zprávy v této místnosti.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Chyba při mazání: {str(e)}", ephemeral=True)

    @app_commands.command(name="kronika", description="Otevři Kroniku Aurionis — rozcestník všech příkazů")
    async def help(self, interaction: discord.Interaction):
        view = KronikaView(author_id=interaction.user.id)
        await interaction.response.send_message(embed=_build_home_embed(), view=view)
        view.message = await interaction.original_response()

    # --- VYVOLENÍ (Seznam postav) ---

    vyvoleni_group = app_commands.Group(name="vyvoleni", description="Seznam vyvolených dobrodruhů")

    @vyvoleni_group.command(name="list", description="Zobrazí všechny zaregistrované postavy")
    async def vyvoleni_list(self, interaction: discord.Interaction):
        import json
        from src.utils.paths import PROFILES as DATA_FILE
        if not os.path.exists(DATA_FILE):
            await interaction.response.send_message("Zatím nikdo není zapsán v knize osudu.", ephemeral=True)
            return
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            data = {}

        if not data:
            await interaction.response.send_message("Zatím nikdo není zapsán v knize osudu.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📖 Kniha osudu — Vyvolení",
            description="*Arion listuje tlustou živoucí knihou a čte jména nahlas...*",
            color=0xFFD700
        )

        lines = []
        for uid, profile in data.items():
            name = profile.get("name", "—")
            rank = profile.get("rank", "F3")
            member = interaction.guild.get_member(int(uid))
            discord_tag = f" <@{uid}>" if member else ""
            lines.append(f"**{name}** · `{rank}`{discord_tag}")

        # Rozděl na chunky kvůli limitu pole (1024 znaků)
        chunk, chunks = [], []
        for line in lines:
            if sum(len(l) + 1 for l in chunk) + len(line) > 950:
                chunks.append(chunk)
                chunk = []
            chunk.append(line)
        if chunk:
            chunks.append(chunk)

        for i, ch in enumerate(chunks):
            embed.add_field(
                name=f"Zapsaní dobrodruzi {f'({i+1})' if len(chunks) > 1 else ''}",
                value="\n".join(ch),
                inline=False
            )

        embed.set_footer(text=f"Celkem zapsáno: {len(data)} dobrodruhů | Aurionis: Act II")
        await interaction.response.send_message(embed=embed)

    # --- TURNAJOVÝ SYSTÉM (Hvězdy) ---

    tournament_group = app_commands.Group(name="tournament", description="Správa turnaje Hvězdy")

    @tournament_group.command(name="list", description="Zobrazí vyvolené ve druhém kole")
    async def tournament_list(self, interaction: discord.Interaction):
        players = _load_tournament()
        if players:
            lines = []
            for entry in players:
                # entry může být string (jméno) nebo int (Discord user ID)
                if isinstance(entry, int) or (isinstance(entry, str) and entry.isdigit()):
                    lines.append(f"• <@{int(entry)}>")
                else:
                    lines.append(f"• {entry}")
            players_list = "\n".join(lines)
        else:
            players_list = "• Zatím nikdo..."

        embed = discord.Embed(
            title="✨ Turnaj Hvězdy — druhé kolo",
            description="**Vyvolení, kteří postoupili do druhého kola:**",
            color=0xFFD700
        )
        embed.add_field(name=f"Postupující ({len(players)})", value=players_list, inline=False)
        embed.set_footer(text="Arion bedlivě sleduje Turnaj o Krále hvězdy")
        await interaction.response.send_message(embed=embed)

    @tournament_group.command(name="add", description="[ADMIN] Přidá hráče nebo jméno do turnaje")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        jmeno="Jméno NPC nebo vlastní text",
        hrac="Discord hráč (volitelné — místo jména)"
    )
    async def tournament_add(
        self,
        interaction: discord.Interaction,
        jmeno: str = None,
        hrac: discord.Member = None,
    ):
        if not jmeno and not hrac:
            await interaction.response.send_message("Zadej jméno nebo vyber hráče.", ephemeral=True)
            return

        players = _load_tournament()
        entry   = str(hrac.id) if hrac else jmeno
        label   = hrac.display_name if hrac else jmeno

        if entry in players or (hrac and str(hrac.id) in [str(p) for p in players]):
            await interaction.response.send_message(
                f"🐾 *Mňau?* `{label}` už v kronice zapsaného mám!", ephemeral=True
            )
            return

        players.append(entry)
        _save_tournament(players)
        await interaction.response.send_message(
            f"✅ *Arion zapsala nové jméno do kroniky.* `{label}` postoupil/a do druhého kola!"
        )

    @tournament_group.command(name="remove", description="[ADMIN] Odebere hráče nebo jméno z turnaje")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        jmeno="Jméno NPC nebo vlastní text",
        hrac="Discord hráč (volitelné)"
    )
    async def tournament_remove(
        self,
        interaction: discord.Interaction,
        jmeno: str = None,
        hrac: discord.Member = None,
    ):
        if not jmeno and not hrac:
            await interaction.response.send_message("Zadej jméno nebo vyber hráče.", ephemeral=True)
            return

        players = _load_tournament()
        entry   = str(hrac.id) if hrac else jmeno
        label   = hrac.display_name if hrac else jmeno

        # Hledej v seznamu jako string nebo int
        match = None
        for p in players:
            if str(p) == str(entry):
                match = p
                break

        if match is None:
            await interaction.response.send_message(
                f"🐾 *Mňau?* `{label}` v mém seznamu není.", ephemeral=True
            )
            return

        players.remove(match)
        _save_tournament(players)
        await interaction.response.send_message(
            f"❌ *Arion přemázla jméno tlapkou.* `{label}` byl/a z turnaje vyřazen/a."
        )

    @tournament_add.error
    @tournament_remove.error
    async def tournament_admin_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Nemáš oprávnění spravovat turnaj.", ephemeral=True)

    # --- TIMESKIP ---

    @app_commands.command(name="timeskip", description="Přeskok v čase — narativní DM utilita")
    @app_commands.describe(
        hours="Počet přeskočených hodin (1–72)",
        poznamka="Co se během přeskoku dělo (volitelné)"
    )
    async def timeskip(
        self,
        interaction: discord.Interaction,
        hours: app_commands.Range[int, 1, 72],
        poznamka: str = None,
    ):
        clocks = _clock_sequence(hours)
        noun = _hours_cz(hours)

        if hours == 1:
            elapsed = f"Uběhla **1 {noun}**."
        elif hours <= 4:
            elapsed = f"Uběhly **{hours} {noun}**."
        else:
            elapsed = f"Uběhlo **{hours} {noun}**."

        embed = discord.Embed(color=0x3B1F6B)
        embed.set_author(name="⏳  Přeskok v čase")
        embed.add_field(name="​", value=clocks, inline=False)
        embed.add_field(name="​", value=elapsed, inline=False)
        if poznamka:
            embed.add_field(name="​", value=f"*{poznamka}*", inline=False)
        embed.set_footer(text="Aurionis · Přeskok v čase")
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Aurionis(bot))