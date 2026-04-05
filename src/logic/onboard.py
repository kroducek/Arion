import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import os
import json
from src.logic.stats import init_stats, STAT_LABELS
from src.utils.json_utils import load_json, save_json
from src.core.roll_stats import record_roll

# ── Konfigurace ───────────────────────────────────────────────────────────────

ROLE_DOBRODRUH_F3_ID = 1476056192643104768
from src.utils.paths import PROFILES as DATA_FILE, ECONOMY as ECONOMY_FILE
COIN                 = "<:goldcoin:1490171741237018795>"

# Obrázky
URL_PLAKAT_HVEZDA   = "https://media.discordapp.net/attachments/1484572118267068598/1484572264123994215/Copilot-20260316-144814.png?ex=69beb729&is=69bd65a9&hm=76e19b81f3b4a6e9effa21f03950a4eab18828ca8e1e81a93b42ff3cb8ddc63b&=&format=webp&quality=lossless&width=432&height=648"
URL_RECAP_ALICE     = "https://media.discordapp.net/attachments/1478419662101287013/1479883190075134155/image.png?ex=69be22df&is=69bcd15f&hm=f261fb2aa148fe41ed07dfbee52506f633f62513ea436fc4a08ddd269b00bd47&=&format=webp&quality=lossless&width=432&height=648"
URL_RECAP_VLADCE    = "https://media.discordapp.net/attachments/1483970683485818961/1483970683817037944/BCO.1f1170a1-b53c-4f30-8a02-ebd298842c77.png?ex=69be8125&is=69bd2fa5&hm=ce5d6884329783b959b4aa618c0fcda2d885cbb7a7677f80921647ed19baa4ce&=&format=webp&quality=lossless&width=432&height=648"
URL_RECAP_REINHARD  = "https://media.discordapp.net/attachments/1479869197784711168/1479895462273089707/image.png?ex=69be2e4d&is=69bcdccd&hm=d6ad1dfaa4a1a5086a9972b7f74fd0f69f1850f72a3c0ed948aa7e601c5a27c6&=&format=webp&quality=lossless&width=432&height=648"
URL_ARION_ENCOUNTER = "https://media.discordapp.net/attachments/1484572118267068598/1484573144831230105/Copilot_20260320_151711.png?ex=69beb7fb&is=69bd667b&hm=6a22f9c9bacc138a38a75675ba56fb33f2435943869d7063982049a108f6acb9&=&format=webp&quality=lossless&width=432&height=648"
URL_TUTORIAL_END    = "https://media.discordapp.net/attachments/1484572118267068598/1484572790521860238/Copilot_20260320_152810.png?ex=69beb7a7&is=69bd6627&hm=acda23f306ba646170ea9ae589fa7315be735841124f2c2bcd3ca8efae6f4dec&=&format=webp&quality=lossless&width=822&height=548"

# ── Destinace ─────────────────────────────────────────────────────────────────

DESTINATIONS = {
    "lumenie": {
        "emoji": "🏰",
        "name":  "Lumenie",
        "desc":  "Město začátků. Každý slavný dobrodruh napsal první řádek svého příběhu zrovna tady. Dominuje mu **katedrála světla** a kamenný most přes řeku **Auriel**, symbol naděje a řádu. Domov nejvyššího paladina **Reinharda** a jeho bratrstva paladinů a rytířů. Lumenie nyní prochází krizí..",
        "color": 0x3498db,
        "image": "https://media.discordapp.net/attachments/1484572118267068598/1484572933023334621/Copilot_20260320_145920.png?ex=69beb7c9&is=69bd6649&hm=a624e462ff950ed84f2542777c22d63ca5710c50834113b85afbc532176cc430&=&format=webp&quality=lossless&width=822&height=548",
    },
    "aquion": {
        "emoji": "🌊",
        "name":  "Aquion",
        "desc":  "Největší obchodní město Aurionisu, postavené na síti kanálů a plovoucích plošin. Říká se, že tady se dá koupit cokoliv.. i pravda, i lež. Klášter mágů vody střeží rovnováhu sil a prakticky řídí celou ekonomickou situaci Kalexie.",
        "color": 0x1abc9c,
        "image": "https://media.discordapp.net/attachments/1484572118267068598/1484572857559285801/Copilot_20260320_150340.png?ex=69beb7b7&is=69bd6637&hm=80ace1e169079d9845326e567a5ded22e9d6bcf3dd3dc01a0b22c214864cbc40&=&format=webp&quality=lossless&width=822&height=548",
    },
    "draci_skala": {
        "emoji": "🏔️",
        "name":  "Dračí skála",
        "desc":  "Mladé město vytesané do útesů vyhaslé sopky kde vládne **Alice Aurelion** — samozvaná královna s darem dračí řeči. Její draci krouží nad hradbami a každý nový příchozí si musí vybrat: věrně sloužit a nebo odejít. Alice nebyla viděna na veřejnosti od té doby co se ukázala v Aquionu.",
        "color": 0xe74c3c,
        "image": "https://media.discordapp.net/attachments/1484572118267068598/1484573012585087057/Copilot_20260320_150049.png?ex=69beb7dc&is=69bd665c&hm=7a0e1d64b751d2b6476e900a3f8b2f2ade7b238bfcf5b662b2487eee7d775d05&=&format=webp&quality=lossless&width=822&height=548",
    },
}

# ── Databáze ──────────────────────────────────────────────────────────────────

def update_profile(user_id, **kwargs):
    user_id = str(user_id)
    data    = load_json(DATA_FILE, default={})
    data.setdefault(user_id, {"rank": "F3"})
    for key, value in kwargs.items():
        data[user_id][key] = value
    save_json(DATA_FILE, data)

def add_gold(user_id: int, amount: int):
    uid  = str(user_id)
    data = load_json(ECONOMY_FILE, default={})
    data[uid] = data.get(uid, 0) + amount
    save_json(ECONOMY_FILE, data)



# ══════════════════════════════════════════════════════════════════════════════
# KROK 1 — Volání Hvězdy
# ══════════════════════════════════════════════════════════════════════════════

class TutorialPartOneView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    @discord.ui.button(label="Naslouchat hlasu❓", style=discord.ButtonStyle.primary, emoji="✨")
    async def listen(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ochrana — hráč s dokončeným profilem nemůže spustit tutorial znovu
        uid = str(interaction.user.id)
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get(uid, {}).get("gold_received"):
                    return await interaction.response.send_message(
                        "Už jsi tutorial dokončil/a! "
                        "Pokud potřebuješ pomoc, napiš DM",
                        ephemeral=True,
                    )
            except Exception:
                pass

        embed = discord.Embed(
            title="🌌 Aurionis: Act II",
            description=(
                "Svět se mění pod tíhou nových zkoušek.\n\n"
                "**Turnaj Hvězdy** byl vyhlášen a jeho vítěz si může přát úplně cokoliv.\n\n"
                "Mocní se pohybují ve stínech, zatímco slabí mizí beze stopy.\n\n"
                "Ti, jenž jsou zváni **Vyvolenými**, stojí na rozhraní mezi oběma světy.\n\n"
                "*Pravda byla odhalena, ale jaká ta pravda vlastně je?*"
            ),
            color=0x2f3136,
        )
        embed.add_field(
            name="❓ Než vstoupíš dál...",
            value="Byl jsi s námi od začátku, nebo přicházíš jako nová tvář?",
        )
        await interaction.response.send_message(embed=embed, view=ActSelectionView(), ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# KROK 2 — Rozcestník
# ══════════════════════════════════════════════════════════════════════════════

class ActSelectionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    @discord.ui.button(label="Já už příběh znám", style=discord.ButtonStyle.success, emoji="⚔️")
    async def old_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _show_destination_choice(interaction)

    @discord.ui.button(label="Chci recap Actu I.", style=discord.ButtonStyle.secondary, emoji="📖")
    async def new_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RecapView(page=1)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


# ══════════════════════════════════════════════════════════════════════════════
# KROK 3 — Rekapitulace (volitelné)
# ══════════════════════════════════════════════════════════════════════════════

class RecapView(discord.ui.View):
    def __init__(self, page=1):
        super().__init__(timeout=600)
        self.page = page
        self._update_buttons()

    def _update_buttons(self):
        self.prev_page.disabled = (self.page == 1)
        self.next_page.disabled = (self.page == 3)

    def get_embed(self) -> discord.Embed:
        pages = {
            1: discord.Embed(
                title="Kapitola I 👑 Rozdělená koruna",
                description=(
                    "**Alice Aurelion** přišla s nárokem, který nikdo nečekal.. krev starého rodu,"
                    "dar dračí řeči a legitimní právo na trůn Kalexie a vlastně i všech ostatních říší\n\n"
                    "**Král Talias** ji odmítl uznat, označil ji za lhářku a podvodnici. Nyní shromažďuje vazaly a zbraně."
                    "Aurionis se ocitl na hraně občanské války a nad vším visí stín **Turnaje Hvězdy** kde si vítěz může přát cokoliv"
                ),
                color=0xe74c3c,
            ),
            2: discord.Embed(
                title="Kapitola II 🛡️ Zrazená přísaha",
                description=(
                    "**Reinhard**, nejvyšší paladin, symbol cti a řádu odložil insignii.."
                    "Ochránce Kalexie a vstoupil do Turnaje Hvězdy sám za sebe\n\n"
                    "*'Stanu se králem hvězdy pro vás všechny'*\n\n"
                    "Za ním zůstala prázdnota, obrana Kalexie se zhroutila a ti, kdo mu "
                    "věřili zůstali bez odpovědí. Talias zuří, je pro něj stejným samozvancem jako Alice"
                ),
                color=0x3498db,
            ),
            3: discord.Embed(
                title="Kapitola III 🎭 Vládce stínů",
                description=(
                    "Muž beze jména, kterému všichni říkají **Vládce stínů**, ovládá sílu zvanou "
                    "esenciální očistění, ta dokáže vzít schopnosti, identitu i smysl existence\n\n"
                    "Během jediné noci v Lumenii přišli tisíce upírů o svou podstatu a"
                    "město je nyní plné uprchlíků, kteří ani nevědí kým jsou vlastně jsou"
                    "a nikdo neví kde Vládce udeří příště.. První byla Lumenie, pak Aquion.."
                ),
                color=0x2c3e50,
            ),
        }
        embed = pages[self.page]
        imgs  = {1: URL_RECAP_ALICE, 2: URL_RECAP_REINHARD, 3: URL_RECAP_VLADCE}
        embed.set_image(url=imgs[self.page])
        return embed

    @discord.ui.button(label="Zpět", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Dále", style=discord.ButtonStyle.secondary, emoji="➡️")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Chápu, chci pokračovat", style=discord.ButtonStyle.success, emoji="✅")
    async def finish_recap(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await _show_destination_choice_followup(interaction)


# ══════════════════════════════════════════════════════════════════════════════
# KROK 4 — Volba destinace
# ══════════════════════════════════════════════════════════════════════════════

def _destination_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🌍  Kde se probudíš?",
        description=(
            "Světlo tě táhne třemi různými směry najednou, z každého směru cítíš úplně jinou energii "
            "Každé místo tě čeká.. ale ty si můžeš vybrat jen jednu cestu\n\n"
            "Vyber svoji destinaci:"
        ),
        color=0xFFD700,
    )
    for d in DESTINATIONS.values():
        embed.add_field(name=f"{d['emoji']} {d['name']}", value=f"-# {d['desc']}", inline=False)
    return embed

async def _show_destination_choice(interaction: discord.Interaction):
    await interaction.response.edit_message(embed=_destination_embed(), view=DestinationView())

async def _show_destination_choice_followup(interaction: discord.Interaction):
    await interaction.edit_original_response(embed=_destination_embed(), view=DestinationView())


class DestinationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    @discord.ui.button(label="Lumenie", style=discord.ButtonStyle.primary, emoji="🏰")
    async def choose_lumenie(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _start_encounter(interaction, dest_key="lumenie")

    @discord.ui.button(label="Dračí skála", style=discord.ButtonStyle.danger, emoji="🏔️")
    async def choose_draci_skala(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _start_encounter(interaction, dest_key="draci_skala")

    @discord.ui.button(label="Aquion", style=discord.ButtonStyle.secondary, emoji="🌊")
    async def choose_aquion(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _start_encounter(interaction, dest_key="aquion")


# ══════════════════════════════════════════════════════════════════════════════
# KROK 5 — Random Encounter: První lekce s Arion
# ══════════════════════════════════════════════════════════════════════════════

async def _start_encounter(interaction: discord.Interaction, dest_key: str):
    update_profile(interaction.user.id, destination=dest_key)

    arion_roll = random.randint(1, 12)

    embed = discord.Embed(
        title="🐱",
        description=(
            "> *Pomalu otevřeš oči a všechno se ti zdá zmatené, ale až děsivě známé.\n"
            "Hlavou ti prochází myšlenka — jestli jsi tu už někdy nebyl.\n"
            "Modré lampy osvětlují ulici, zatímco ty se nacházíš před cechem dobrodruhů.*\n\n"
            "Z rohu uličky vyběhne bronzová kočička v magickém klobouku a šťastně zamňouká\n\n"
            "**'No ne, další! Heeej, ahoooj, nechceš být dobrodruh?'**\n\n"
            "Dřív než stačíš odpovědět, tak kočička zamrská tlapkou a vyčaruje "
            "třpytivou kouli vody, kterou hodí rovnou po tobě"
        ),
        color=0x3498db,
    )
    embed.add_field(
        name=f"🎲 Arion Attack Roll  `/roll 1d12`",
        value=f"Výsledek: **{arion_roll}**",
        inline=False,
    )
    embed.add_field(
        name="🛡️ Tvůj tah!",
        value=(
            "Musíš hodit na **Obratnost** — zvládneš se vyhnout?\n"
            "Hoď `/roll 1d20`  ·  hranice úspěchu: **10+**\n\n"
            "-# *(Simulace: klikni na tlačítko níže)*"
        ),
        inline=False,
    )
    embed.set_footer(text="⭐ Aurionis  ·  Arion tě pozoruje s pobaveným výrazem.")

    await interaction.response.edit_message(
        embed=embed,
        view=EncounterView(dest_key=dest_key, arion_roll=arion_roll),
    )


class EncounterView(discord.ui.View):
    def __init__(self, dest_key: str, arion_roll: int):
        super().__init__(timeout=600)
        self.dest_key   = dest_key
        self.arion_roll = arion_roll
        self._rolled    = False

    @discord.ui.button(label="Hodit na Obratnost  /roll 1d20", style=discord.ButtonStyle.primary, emoji="🎲")
    async def roll_defense(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._rolled:
            await interaction.response.defer()
            return
        self._rolled    = True
        button.disabled = True
        player_roll = random.randint(1, 20)
        success     = player_roll >= 10

        if success:
            embed = discord.Embed(
                title="💨  ",
                description=(
                    f"Hodíš se stranou a koule vody projde těsně kolem tvého ucha, roztříští se o zeď za tebou.\n\n"
                    f"Arion na tebe upřeně zírá a pak se rozesměje.\n\n"
                    f"**'Máš dobré reflexy! To se mi líbí!'**\n\n"
                    f"S úšklebkem ukáže na dveře cechu\n"
                    f"**'Můžu tě navést na cestu, pojď dovnitř!'"
                    f"**"
                ),
                color=0x2ecc71,
            )
        else:
            embed = discord.Embed(
                title="💦  ",
                description=(
                    f"Koule vody ti trefí přímo do obličeje a jsi kompletně promočený.\n\n"
                    f"Arion se skoro sesype smíchy.\n\n"
                    f"**'AHA-HAHA-HAHA! Ach jo, ach jo..'**  *máchne tlapkou*\n\n"
                    f"*Na kůži ti začínají růst malé toxické houby.* Arion je sfoukne jedním dechem "
                    f"a ty se rozplynou. Stále se chichotající kočka ukáže na dveře.\n"
                    f"**'Ahaha, pojď dovnitř!'**"
                ),
                color=0xe67e22,
            )

        embed.add_field(
            name="🎲 Tvůj hod  `/roll 1d20`",
            value=(
                f"Výsledek: **{player_roll}**  "
                f"{'✅ Úspěch' if success else '❌ Neúspěch'}  ·  hranice: 10+"
            ),
            inline=False,
        )
        embed.set_footer(text="⭐ Aurionis  ·  Arion přistává.")

        await interaction.response.edit_message(
            embed=embed,
            view=ArionIntroView(dest_key=self.dest_key, dodged=success),
        )


# ══════════════════════════════════════════════════════════════════════════════
# KROK 6 — Arion: Představení
# ══════════════════════════════════════════════════════════════════════════════

class ArionIntroView(discord.ui.View):
    def __init__(self, dest_key: str, dodged: bool = True):
        super().__init__(timeout=600)
        self.dest_key = dest_key
        self.dodged   = dodged

    @discord.ui.button(label="Počkat..", style=discord.ButtonStyle.secondary, emoji="👁️")
    async def wait(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.dodged:
            landing = (
                "Kočička přistane přímo před tebou a ztlumí pád pomocí jakési aury "
                "a rovnou tě změří pohledem od hlavy k patě"
            )
        else:
            landing = (
                "Kočička přistane *na tobě* — ...doslova. "
                "Použije tě jako odrazový můstek, odskočí a přistane o krok dál. "
                "Otočí se a změří tě pohledem od hlavy k patě jako by se nic nestalo."
            )

        embed = discord.Embed(
            title="🐱  Já jsem Arion!",
            description=(
                f"{landing}\n\n"
                "***'Já jsem Arion!'***  řekne pyšně jako by to bylo to "
                "nejdůležitější sdělení světa.\n\n"
                "Líně si olízne srst a zvedne pohled k tobě\n\n"
                "***'A ty jsi?'***"
            ),
            color=0x3498db,
        )
        embed.set_footer(text="⭐ Aurionis  ·  Arion čeká na odpověď.")
        await interaction.response.edit_message(
            embed=embed,
            view=GuildEntranceView(dest_key=self.dest_key),
        )


class GuildEntranceView(discord.ui.View):
    def __init__(self, dest_key: str):
        super().__init__(timeout=600)
        self.dest_key = dest_key

    @discord.ui.button(label="Představit se", style=discord.ButtonStyle.primary, emoji="✍️")
    async def reply_arion(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NameRegistrationModal(dest_key=self.dest_key))


# ══════════════════════════════════════════════════════════════════════════════
# KROK 7a — Jméno
# ══════════════════════════════════════════════════════════════════════════════

class NameRegistrationModal(discord.ui.Modal, title="Jak se jmenuješ?"):
    char_name = discord.ui.TextInput(
        label="Jméno postavy",
        placeholder="Jak se jmenuje tvá postava?",
        required=True,
        max_length=32,
    )

    def __init__(self, dest_key: str):
        super().__init__()
        self.dest_key = dest_key

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.char_name.value
        update_profile(interaction.user.id, name=new_name)
        try:
            await interaction.user.edit(nick=new_name)
        except Exception:
            pass

        embed = discord.Embed(
            title="🐱  Hm..",
            description=(
                f"***'{new_name}.'***\n\n"
                "Arion to zopakuje nahlas a pomalu jako by zkoušela jak tvé jméno zní ve vzduchu. "
                "Arion se zamračí a prohlží si tě vemi důkladně\n\n"
                "Ale pak se něco změní\n\n"
                "Rozběhne se přímo proti tobě"
            ),
            color=0x3498db,
        )
        embed.add_field(
            name="⭐  Perk: Nejobratnější",
            value="-# Arion na tebe skočí dřív než stačíš zareagovat",
            inline=False,
        )
        embed.set_footer(text="⭐ Aurionis  ·  Co teď?")
        await interaction.response.edit_message(
            embed=embed,
            view=ArionLeapView(dest_key=self.dest_key, char_name=new_name),
        )


# ══════════════════════════════════════════════════════════════════════════════
# KROK 7b — Arion prozkoumává / check roll
# ══════════════════════════════════════════════════════════════════════════════

class ArionLeapView(discord.ui.View):
    def __init__(self, dest_key: str, char_name: str):
        super().__init__(timeout=600)
        self.dest_key  = dest_key
        self.char_name = char_name

    @discord.ui.button(label="Zahodit Arion  /check", style=discord.ButtonStyle.danger, emoji="💪")
    async def throw_arion(self, interaction: discord.Interaction, button: discord.ui.Button):
        roll = random.randint(1, 20)

        if roll >= 11:
            desc = (
                f"-# 🎲 STR check — **{roll}**/20\n\n"
                "Chytíš ji za límec klobouku a prudce zahodíš.\n\n"
                "Arion přistane na čtyřech tlapách pár metrů od tebe, "
                "narovná si klobouk a kouká na tebe s novým respektem.\n\n"
                "***'Oooh... Takže ty jsi tenhle typ.'***\n\n"
                "Chvíli vypadá jako by nad něčím přemýšlela.\n\n"
                "***'Vzpomínáš si na něco?'***"
            )
        else:
            desc = (
                f"-# 🎲 STR check — **{roll}**/20\n\n"
                "Zkusíš ji shodit, ale Arion se drží jako klíště. "
                "Přeleze přes tvé rameno, pak po zádech, pak zase zpátky..\n\n"
                "***'Nedaří se ti mě shodit, že?'*** poznamená spokojeně.\n\n"
                "***'Vzpomínáš si na něco?'***"
            )

        embed = discord.Embed(title="🎲", description=desc, color=0xf0a500)
        embed.set_footer(text="⭐ Aurionis")
        await interaction.response.edit_message(
            embed=embed,
            view=ArionMemoryView(dest_key=self.dest_key),
        )

    @discord.ui.button(label="Nechat ji tě prozkoumat", style=discord.ButtonStyle.secondary, emoji="🐾")
    async def let_arion(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🐾  ..Co to dělá?",
            description=(
                "Necháš ji a Arion začne šplhat po tobě se soustředěným výrazem. "
                "Přičichne ke tvému ramenu, pak ke krku, pak strčí nos přímo do tvých vlasů.\n\n"
                "***'Hm..'***\n\n"
                "Sleze dolů a postaví se před tebe.\n\n"
                "***'Vzpomínáš si na něco?'***"
            ),
            color=0x9b59b6,
        )
        embed.set_footer(text="⭐ Aurionis")
        await interaction.response.edit_message(
            embed=embed,
            view=ArionMemoryView(dest_key=self.dest_key),
        )


# ══════════════════════════════════════════════════════════════════════════════
# KROK 7c — Arion: Paměť?
# ══════════════════════════════════════════════════════════════════════════════

class ArionMemoryView(discord.ui.View):
    def __init__(self, dest_key: str):
        super().__init__(timeout=600)
        self.dest_key = dest_key

    async def _go_hm(self, interaction: discord.Interaction, title: str, description: str):
        embed = discord.Embed(title=title, description=description, color=0x2c3e50)
        embed.set_footer(text="⭐ Aurionis")
        await interaction.response.edit_message(embed=embed, view=ArionHmView(dest_key=self.dest_key))

    @discord.ui.button(label="Nevzpomínám si na nic..", style=discord.ButtonStyle.secondary, emoji="🤔")
    async def just_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go_hm(
            interaction,
            title="🐱  Hm..",
            description=(
                "Arion tě chvíli pozoruje a pak tiše sklopí pohled\n\n"
                "***'Hm..'***\n\n"
                "*Trapné ticho přerušuje jen rušná ulice a zvednutý vítr*"
            ),
        )

    @discord.ui.button(label="Já myslel, že kočky nemluví..", style=discord.ButtonStyle.secondary, emoji="🐱")
    async def cats_dont_talk(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go_hm(
            interaction,
            title="🐱  ..",
            description=(
                "Arion na tebe zírá s výrazem absolutní pohrdavé nadřazenosti\n\n"
                "***'Většina lidí taky nemluví..'***\n\n"
                "*Otočí se s pocitem povýšení. Diskuse zřejmě skončila*"
            ),
        )

    @discord.ui.button(label="Mám divný pocit..", style=discord.ButtonStyle.secondary, emoji="💭")
    async def weird_feeling(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go_hm(
            interaction,
            title="🐱  ..",
            description=(
                "Arion se na tebe podívá trochu jinak než předtím\n\n"
                "***'Hm..'***\n\n"
                "*Nic neřekne. Ale chvíli trvá než odvrátí pohled*"
            ),
        )


class ArionHmView(discord.ui.View):
    def __init__(self, dest_key: str):
        super().__init__(timeout=600)
        self.dest_key = dest_key

    @discord.ui.button(label="Hm?", style=discord.ButtonStyle.secondary, emoji="❓")
    async def hm(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🐱  ..Ale nic.",
            description=(
                "Arion zvedne hlavu a její výraz se vrátí do normálu "
                "nebo aspoň do toho co u ní normál je.\n\n"
                "***'...Ale nic, vyvolený'***\n\n"
                "Otočí se a zamíří ke dveřím cechu. "
                "Klobouk se na hlavě narovná sám od sebe.\n\n"
                "***'Pojď dovnitř'***"
            ),
            color=0x2c3e50,
        )
        embed.set_footer(text="⭐ Aurionis  ·  Uvnitř je tepleji.")
        await interaction.response.edit_message(
            embed=embed,
            view=EnterGuildInsideView(dest_key=self.dest_key),
        )


class EnterGuildInsideView(discord.ui.View):
    def __init__(self, dest_key: str):
        super().__init__(timeout=600)
        self.dest_key = dest_key

    @discord.ui.button(label="Jít dovnitř", style=discord.ButtonStyle.success, emoji="🚪")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🏛️  Cech dobrodruhů",
            description=(
                "Dveře se za tebou zavřou a hluk ulice utichne\n\n"
                "Uvnitř panuje svérázný pořádek, u stolu v rohu se hádají dva trpaslíci "
                "o tom kdo zabil draka jako poslední. Častokrát slyšíš jméno Aurelion. "
                "Někdo jiný spí na lavici s helmou přes obličej.\n\n"
                "Arion přeskočí pult jedním plynulým pohybem a "
                "přistane na druhé straně kde otevře tlustou, živoucí knihu\n\n"
                "***'..Standardní procedura, přijmu tě mezi dobrodruhy'***\n\n"
                "Přejede tlapkou přes zvláštní destičku vedle knihy a ta se "
                "rozsvítí modrou aurou jako by reagovala na dotyk\n\n"
                "***'Tak se podíváme z jakého jsi těsta'***"
            ),
            color=0x2c3e50,
        )
        embed.set_image(url=URL_ARION_ENCOUNTER)
        embed.set_footer(text="⭐ Aurionis  ·  Rozděl své body.")

        labels     = ['STR', 'DEX', 'INS', 'INT', 'CHA', 'WIS']
        base_stats = {s: 0 for s in labels}
        init_stats(interaction.user.id, base_stats=base_stats, sp=5)

        await interaction.response.edit_message(
            embed=embed,
            view=TutorialSPView(
                dest_key=self.dest_key,
                portrait_url=None,
                sp_remaining=5,
                stats={s: 0 for s in labels},
            ),
        )


# ══════════════════════════════════════════════════════════════════════════════
# KROK 8c — Motivace (po portrétu — Arion zapíše poslední pole průkazu)
# ══════════════════════════════════════════════════════════════════════════════

class MotivationView(discord.ui.View):
    def __init__(self, dest_key: str, stats: dict | None = None, portrait_url: str | None = None):
        super().__init__(timeout=600)
        self.dest_key    = dest_key
        self.stats       = stats
        self.portrait_url = portrait_url

    @discord.ui.button(label="Odpovědět Arion", style=discord.ButtonStyle.primary, emoji="✍️")
    async def reply_motivation(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            MotivationModal(dest_key=self.dest_key, stats=self.stats, portrait_url=self.portrait_url)
        )


class MotivationModal(discord.ui.Modal, title="Tvá motivace"):
    motivation = discord.ui.TextInput(
        label="Proč chceš být dobrodruhem?",
        style=discord.TextStyle.paragraph,
        placeholder="Sláva, bohatství, nebo něco hlubšího?",
        required=True,
        max_length=1000,
    )

    def __init__(self, dest_key: str, stats: dict | None = None, portrait_url: str | None = None):
        super().__init__()
        self.dest_key    = dest_key
        self.stats       = stats
        self.portrait_url = portrait_url

    async def on_submit(self, interaction: discord.Interaction):
        update_profile(interaction.user.id, motivation=self.motivation.value[:200])
        await _show_guild_card(
            interaction,
            dest_key=self.dest_key,
            portrait_url=self.portrait_url,
            stats=self.stats,
        )


# ══════════════════════════════════════════════════════════════════════════════
# SP rozdělování v tutorialu
# ══════════════════════════════════════════════════════════════════════════════

STAT_FULL_NAMES = {
    "STR": "Síla",
    "DEX": "Obratnost",
    "INS": "Instinkty",
    "INT": "Inteligence",
    "CHA": "Charisma",
    "WIS": "Moudrost",
}

class TutorialSPView(discord.ui.View):
    """Hráč rozděluje 5 SP přímo v tutorialu — každý klik = 1 SP do statu."""

    def __init__(
        self,
        dest_key: str,
        stats: dict | None,
        portrait_url: str | None,
        sp_remaining: int,
    ):
        super().__init__(timeout=600)
        self.dest_key     = dest_key
        self.stats        = stats or {}
        self.portrait_url = portrait_url
        self.sp_remaining = sp_remaining
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        labels = ['STR', 'DEX', 'INS', 'INT', 'CHA', 'WIS']
        for stat in labels:
            btn = discord.ui.Button(
                label=f"{stat} {self.stats.get(stat, 0)}  ({STAT_FULL_NAMES[stat]})",
                style=discord.ButtonStyle.secondary,
                disabled=(self.sp_remaining <= 0),
            )
            btn.callback = self._make_callback(stat)
            self.add_item(btn)
        if self.sp_remaining <= 0:
            done_btn = discord.ui.Button(
                label="Hotovo, pokračovat →",
                style=discord.ButtonStyle.success,
                emoji="✅",
                row=4,
            )
            done_btn.callback = self._done_callback
            self.add_item(done_btn)

            reset_btn = discord.ui.Button(
                label="Chci to změnit",
                style=discord.ButtonStyle.danger,
                emoji="🔄",
                row=4,
            )
            reset_btn.callback = self._reset_callback
            self.add_item(reset_btn)

    def _make_callback(self, stat: str):
        async def callback(interaction: discord.Interaction):
            from src.logic.stats import spend_sp
            success = spend_sp(interaction.user.id, stat, 1)
            if not success:
                await interaction.response.defer()
                return

            self.stats[stat] = self.stats.get(stat, 1) + 1
            self.sp_remaining -= 1
            self._build_buttons()

            stats_lines = "  ·  ".join(
                f"**{s}** {self.stats.get(s, 1)}" for s in ['STR', 'DEX', 'INS', 'INT', 'CHA', 'WIS']
            )

            if self.sp_remaining > 0:
                desc = (
                    f"**+1 {stat}** — {STAT_FULL_NAMES[stat]} zvýšena.\n\n"
                    f"{stats_lines}\n\n"
                    f"*Zbývá: **{self.sp_remaining} SP***"
                )
                footer = f"⭐ Aurionis  ·  {self.sp_remaining} SP zbývá"
            else:
                desc = (
                    f"**+1 {stat}** — {STAT_FULL_NAMES[stat]} zvýšena.\n\n"
                    f"{stats_lines}\n\n"
                    "***'Dobrá volba.'***\n\n"
                    "*Světelné koule zhasnou. Sken je kompletní.*"
                )
                footer = "⭐ Aurionis  ·  Všechny SP rozděleny"

            embed = discord.Embed(
                title="⚡  Skill Pointy",
                description=desc,
                color=0x9b59b6,
            )
            embed.set_footer(text=footer)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def _reset_callback(self, interaction: discord.Interaction):
        labels = ['STR', 'DEX', 'INS', 'INT', 'CHA', 'WIS']
        from src.logic.stats import init_stats
        init_stats(interaction.user.id, base_stats={s: 0 for s in labels}, sp=5)
        self.stats = {s: 0 for s in labels}
        self.sp_remaining = 5
        self._build_buttons()

        embed = discord.Embed(
            title="⚡  Skill Pointy",
            description=(
                "SP resetovány. Rozhodni znovu.\n\n"
                "*Zbývá: **5 SP***"
            ),
            color=0x9b59b6,
        )
        embed.set_footer(text="⭐ Aurionis  ·  5 SP zbývá")
        await interaction.response.edit_message(embed=embed, view=self)

    async def _done_callback(self, interaction: discord.Interaction):
        labels      = ['STR', 'DEX', 'INS', 'INT', 'CHA', 'WIS']
        stats_lines = "  ·  ".join(f"**{s}** {self.stats.get(s, 0)}" for s in labels)

        embed = discord.Embed(
            title="🖼️  Ještě jedna věc...",
            description=(
                f"-# {stats_lines}\n\n"
                "Arion nakloní hlavu na stranu.\n\n"
                "***'Můžu si tě nakreslit do záznamu? Miluji umění.'***\n\n"
                "*Kouká na tebe s výrazem, který dává jasně najevo, "
                "že odmítnutí by ji osobně urazilo.*"
            ),
            color=0x9b59b6,
        )
        embed.set_footer(text="⭐ Aurionis  ·  Skoro hotovo.")
        await interaction.response.edit_message(
            embed=embed,
            view=PortraitView(dest_key=self.dest_key, stats=self.stats),
        )


# ══════════════════════════════════════════════════════════════════════════════
# KROK 8b — Portrét
# ══════════════════════════════════════════════════════════════════════════════

class PortraitView(discord.ui.View):
    def __init__(self, dest_key: str, stats: dict | None = None):
        super().__init__(timeout=600)
        self.dest_key = dest_key
        self.stats    = stats

    @discord.ui.button(label="Uhm.. tak jo? (nahrát URL)", style=discord.ButtonStyle.primary, emoji="🖼️")
    async def upload_portrait(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PortraitModal(dest_key=self.dest_key, stats=self.stats))

    @discord.ui.button(label="Radši ne (přeskočit)", style=discord.ButtonStyle.secondary, emoji="🙅")
    async def skip_portrait(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _show_motivation_prompt(interaction, dest_key=self.dest_key, portrait_url=None, stats=self.stats)


class PortraitModal(discord.ui.Modal, title="Portrét postavy"):
    url = discord.ui.TextInput(
        label="Odkaz na obrázek (URL)",
        placeholder="Vlož URL obrázku postavy...",
        required=True,
    )

    def __init__(self, dest_key: str, stats: dict | None = None):
        super().__init__()
        self.dest_key = dest_key
        self.stats    = stats

    async def on_submit(self, interaction: discord.Interaction):
        portrait_url = self.url.value
        update_profile(interaction.user.id, portrait_url=portrait_url)
        await _show_motivation_prompt(interaction, dest_key=self.dest_key, portrait_url=portrait_url, stats=self.stats)


# ══════════════════════════════════════════════════════════════════════════════
# KROK 8b — Motivace prompt (po portrétu, před průkazem)
# ══════════════════════════════════════════════════════════════════════════════

async def _show_motivation_prompt(
    interaction: discord.Interaction,
    dest_key: str,
    portrait_url: str | None,
    stats: dict | None,
):
    embed = discord.Embed(
        title="📜",
        description=(
            "Arion otočí průkaz dobrodruha k tobě\n\n"
            "Všechna pole jsou vyplněna... jméno, sken i tvůj portrét. "
            "Zbývá jen jedno prázdné místo ve spodní části\n\n"
            "*Pero se samo zdvihne nad stránku a začne zapisovat tvou odpověď*\n\n"
            "***'Proč vlastně chceš být dobrodruhem?'***\n\n"
            "-# *Tohle pole uvidí každý kdo si průkaz prohlédne*"
        ),
        color=0x9b59b6,
    )
    if portrait_url:
        embed.set_thumbnail(url=portrait_url)
    embed.set_footer(text="⭐ Aurionis  ·  Arion poslouchá.")
    await interaction.response.edit_message(
        embed=embed,
        view=MotivationView(dest_key=dest_key, stats=stats, portrait_url=portrait_url),
    )


# ══════════════════════════════════════════════════════════════════════════════
# KROK 8c — Průkaz dobrodruha
# ══════════════════════════════════════════════════════════════════════════════

async def _show_guild_card(
    interaction: discord.Interaction,
    dest_key: str,
    portrait_url: str | None,
    stats: dict | None = None,
):
    # Přidej rank roli
    role = interaction.guild.get_role(ROLE_DOBRODRUH_F3_ID)
    if role:
        try:
            await interaction.user.add_roles(role)
        except Exception:
            pass

    if portrait_url:
        portrait_text = (
            "Arion vytvoří magické plátno a chvíli tě soustředěně pozoruje"
            "A pak začne kreslit. Za pár vteřin je hotovo, spokojeně přikývne sama pro sebe.\n\n"
            "***'Moc hezké...'***\n\n"
        )
    else:
        portrait_text = (
            "Arion zavře knihu a jen mávne rukou\n\n"
            "***'Jak chceš, tak se přiště zastav'***\n\n"
        )

    # Stats text — vryje se do průkazu
    if stats:
        stats_line = "  ·  ".join(f"**{k}** {v}" for k, v in stats.items())
        stats_scene = (
            f"\n\nVidíš jak se magicky na průkaz vyrývají čísla\n"
            f"-# {stats_line}\n\n"
            f"*Co to znamená?*"
        )
    else:
        stats_scene = ""

    embed = discord.Embed(
        title="📜  Průkaz dobrodruha",
        description=(
            portrait_text +
            "Sáhne pod pult a vytáhne starý kožený váček s cechovní pečetí\n\n"
            "***'Mňau.. Vstupní poplatek je sto zlatých...'***\n\n"
            "Arion si hluboce povzdychne, ale následně výraz změní v euforii\n\n"
            "***'...ale jsou temné časy a každý dobrodruh se počítá "
            "...Takže tentokrát platíme my vám'***\n\n"
            "Načmárá tvé jméno na nějaký formulář a pak ti podá váček přes pult"
            + stats_scene
        ),
        color=0xFFD700,
    )
    if portrait_url:
        embed.set_thumbnail(url=portrait_url)
    embed.set_footer(text="⭐ Aurionis  ·  Průkaz je tvůj.")

    view = StatsDialogView(dest_key=dest_key, portrait_url=portrait_url) if stats else GoldView(dest_key=dest_key, portrait_url=portrait_url)
    await interaction.response.edit_message(embed=embed, view=view)


# ── Stats dialog — "Co to znamená?" ───────────────────────────────────────────

class StatsDialogView(discord.ui.View):
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=600)
        self.dest_key    = dest_key
        self.portrait_url = portrait_url

    @discord.ui.button(label='"Co to znamená?"', style=discord.ButtonStyle.secondary, emoji="❓")
    async def ask_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🐱  Magický sken",
            description=(
                "Arion se přehoupne přes pult a kouká na čísla na tvým průkazu\n\n"
                "***'Magický sken dokáže z části odhadnout tvou přirozenou sílu "
                "a převést ji na konkrétní čísla..'***\n\n"
                "***'Přirozená síla?..'***\n\n"
                "***'Můžeš se od toho odrazit a vědět v čem se chceš zlepšit'***"
            ),
            color=0x9b59b6,
        )
        if self.portrait_url:
            embed.set_thumbnail(url=self.portrait_url)
        embed.set_footer(text="⭐ Aurionis  ·  Skoro hotovo.")
        await interaction.response.edit_message(
            embed=embed,
            view=GoldView(dest_key=self.dest_key, portrait_url=self.portrait_url),
        )


# ══════════════════════════════════════════════════════════════════════════════
# KROK 9 — Zlaté a rozloučení s Arion
# ══════════════════════════════════════════════════════════════════════════════

class GoldView(discord.ui.View):
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=600)
        self.dest_key     = dest_key
        self.portrait_url = portrait_url

    @discord.ui.button(label="Převzít zlaté", style=discord.ButtonStyle.success, emoji="🪙")
    async def receive_gold(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ochrana před double-klikem — deaktivuj tlačítko okamžitě
        button.disabled = True
        await interaction.response.defer()

        uid = str(interaction.user.id)
        profile = {}
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    profile = json.load(f)
            except Exception:
                pass
        if profile.get(uid, {}).get("gold_received"):
            await interaction.followup.send(
                "Zlaté jsi už jednou převzal/a! *(Pokud myslíš, že jde o chybu, piš adminovi.)*",
                ephemeral=True,
            )
            return
        add_gold(interaction.user.id, 100)
        update_profile(interaction.user.id, gold_received=True)

        dest = DESTINATIONS[self.dest_key]
        embed = discord.Embed(
            title="🪙  Měšec se zlatými",
            description=(
                "Zlaté uvnitř cinkají velmi přesvědčivě\n\n"
                f"**+100** {COIN} připsáno na tvé konto\n\n"
                "Ještě než tě nechá odejít tak prohodí\n\n"
                f"***'Svět tam venku není moc přívětivý.."
                f"..obzvlášť teď, za Turnaje. Dávej na sebe pozor..'***\n\n"
                f"***'{dest['emoji']} {dest['name']} tě čeká'***\n\n"
                "*Arion ti přestane věnovat pozornost. To je zřejmě rozloučení*"
            ),
            color=0xFFD700,
        )
        if self.portrait_url:
            embed.set_thumbnail(url=self.portrait_url)
        embed.set_footer(text="⭐ Aurionis  ·  Poslední krok.")

        await interaction.edit_original_response(
            embed=embed,
            view=BulletinBoardView(dest_key=self.dest_key, portrait_url=self.portrait_url),
        )


# ══════════════════════════════════════════════════════════════════════════════
# KROK 10 — Nástěnka, vize, charisma hod
# ══════════════════════════════════════════════════════════════════════════════

class BulletinBoardView(discord.ui.View):
    """Hráč si všimne nástěnky a turnajového seznamu."""
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=600)
        self.dest_key     = dest_key
        self.portrait_url = portrait_url

    @discord.ui.button(label="Podívat se na nástěnku", style=discord.ButtonStyle.secondary, emoji="📋")
    async def look_bulletin(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📋  Nástěnka cechu",
            description=(
                "Zastavíš se u vývěsky u dveří.\n\n"
                "Visí tu různé zakázky.. vybírání odměn, eskorty, průzkum "
                "a každý má vedle sebe cechovní pečeť s označením minimálního ranku."
                "**Žádný není pro F3...**\n\n"
                "*Jasně. Musíš si nejdřív dobudovat jméno..*\n\n"
                "Pod úkoly visí ručně psaný list, "
                "jiný papír, jiný rukopis. Nadpis říká:\n\n"
                "**✨ Turnaj Hvězdy — postupující do 2. kola**\n\n"
                "*Hao · Darryn · Gabriel*\n\n"
                "-# *Nikdo koho bys měl znát. A přesto proč ti ta jména "
                "přijdou tak povědomá?*"
            ),
            color=0x2c3e50,
        )
        if self.portrait_url:
            embed.set_thumbnail(url=self.portrait_url)
        embed.set_footer(text="⭐ Aurionis")

        await interaction.response.edit_message(
            embed=embed,
            view=VisionView(dest_key=self.dest_key, portrait_url=self.portrait_url),
        )


class VisionView(discord.ui.View):
    """Hráč se zamotá — krátká vize. Může se pokusit si vzpomenout přes /check."""
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=600)
        self.dest_key     = dest_key
        self.portrait_url = portrait_url

    @discord.ui.button(label="Zamyslet se", style=discord.ButtonStyle.secondary, emoji="💭")
    async def think(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="💭  ..",
            description=(
                "Vzpomínky.. vracejí se ti útržky, "
                "ale nedokážeš z nich pořádně číst.\n\n"
                "Svět se na vteřinu roztočí\n\n"
                "*Ležíš na zemi a na rukou máš krev, scéna je rozmazaná.*\n"
                "*Od tebe pomalu odchází muž v masce.. vypadá jako šašek?*\n\n"
                "**\"Dávej pozor...\"**\n\n"
                "Vzpamatuješ se. Jsi stále v cechu dobrodruhů..\n\n"
                "*Tvoje duše se chvěje*\n\n"
                "Zkusíš se soustředit.. vytáhnout z té vize aspoň něco. "
            ),
            color=0x1a1a2e,
        )
        if self.portrait_url:
            embed.set_thumbnail(url=self.portrait_url)
        embed.set_footer(text="⭐ Aurionis  ·  /check — Wisdom · Intelligence · Insight")

        await interaction.response.edit_message(
            embed=embed,
            view=MemoryCheckView(dest_key=self.dest_key, portrait_url=self.portrait_url),
        )


class MemoryCheckView(discord.ui.View):
    """/check — hráč hází vlastní roll, Arion sleduje WIS/INT/INS."""
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=600)
        self.dest_key     = dest_key
        self.portrait_url = portrait_url
        self._checked     = False

    @discord.ui.button(label="🎲 Zkusit si vzpomenout  /check", style=discord.ButtonStyle.primary)
    async def memory_check(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._checked:
            await interaction.response.defer()
            return
        self._checked   = True
        button.disabled = True
        await interaction.response.defer()

        # Vždy nat20 WIS — hráč si v tutorialu vždy vzpomene
        if interaction.guild:
            record_roll(
                interaction.guild.id, interaction.user.id,
                nat20=True, nat1=False, hit24=False, is_check=True,
            )

        arion_line = (
            "*Arion zvedne oči od knihy a chvíli tě ostražitě sleduje bez pohnutí.*\n"
            "***'..Paměť se ti vrací. Pomalu... ale vrací.'***"
        )
        outcome_desc = (
            "Soustředíš se a z hluboka se nadechneš.\n\n"
            "Na vteřinu se obraz zostří.\n\n"
            "*Muž v masce.. Šašek.. stojí blíž než v první vizi, vidíš ho zřetelněji.*\n\n"
            "*Maska nedává najevo žádné emoce. Ani úsměv, ani hněv. Jen prázdnota.*\n\n"
            "*Za ním..? nebo pod ním? — voda. Všude voda a písek.*\n"
            "*Ostrov. Malý a izolovaný. Cítíš sůl a vítr..*\n\n"
            "*A pak ten hlas, klidný jako rozsudek:*\n\n"
            "**\"Dávej pozor\"**\n\n"
            "*Jméno se ti nevybaví, ani místo se ti nevybaví.*\n"
            "*Ale víš, že to není poprvé co jsi ho viděl/a.*\n\n"
            f"{arion_line}"
        )

        embed = discord.Embed(
            title="🌟  Přirozená 20!",
            description=f"-# *Moudrost check — /roll 1d20*\n\n{outcome_desc}",
            color=0x27ae60,
        )
        if self.portrait_url:
            embed.set_thumbnail(url=self.portrait_url)
        embed.set_footer(text="⭐ Aurionis")

        await interaction.edit_original_response(
            embed=embed,
            view=CollisionTransitionView(
                dest_key=self.dest_key,
                portrait_url=self.portrait_url,
            ),
        )

        # Zapiš první vzpomínku
        uid = str(interaction.user.id)
        try:
            profiles = load_json(DATA_FILE, default={})
            profiles.setdefault(uid, {}).setdefault("memories", [])
            if not profiles[uid]["memories"]:
                profiles[uid]["memories"].append(
                    "Muž v masce šaška. Ostrov, voda a písek. Krev na rukou. "
                    "\"Dávej pozor.\" — Jméno ani místo si nevybavím, ale vím, že to nebylo poprvé."
                )
                save_json(DATA_FILE, profiles)
                if interaction.channel:
                    await interaction.channel.send(
                        f"📜 **{interaction.user.display_name}** si úspěšně vzpomněl/a."
                    )
        except Exception as e:
            print(f"[onboard] Nepodařilo se zapsat vzpomínku: {e}")


class CollisionTransitionView(discord.ui.View):
    """Přechod — vzpamatuješ se a narazíš do muže s rohy."""
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=600)
        self.dest_key     = dest_key
        self.portrait_url = portrait_url

    @discord.ui.button(label="Vzpamatovat se", style=discord.ButtonStyle.secondary, emoji="👁️")
    async def snap_back(self, interaction: discord.Interaction, button: discord.ui.Button):
        desc = (
            "Jsi stále v cechu a\n\n"
            "*nikdo si toho nevšiml.*\n\n"
            "Nebo.. skoro nikdo...\n\n"
            "Ramenem narazíš do mohutného muže, "
            "který právě míjí dveře. Ohlédne se. "
            "Na hlavě má démonní rohy a na tebe se "
            "valí pivo z právě vyleveného džbánu."
        )
        embed = discord.Embed(
            title="💥  ..",
            description=desc,
            color=0x2c3e50,
        )
        if self.portrait_url:
            embed.set_thumbnail(url=self.portrait_url)
        embed.set_footer(text="⭐ Aurionis  ·  Charisma check.")

        await interaction.response.edit_message(
            embed=embed,
            view=CharismaRollView(dest_key=self.dest_key, portrait_url=self.portrait_url),
        )


class CharismaRollView(discord.ui.View):
    """Hráč hází na Charisma — skutečný náhodný roll."""
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=600)
        self.dest_key     = dest_key
        self.portrait_url = portrait_url
        self._rolled      = False

    @discord.ui.button(label="🎲 Hodit na Charisma  /roll 1d20", style=discord.ButtonStyle.primary)
    async def roll_charisma(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._rolled:
            await interaction.response.defer()
            return
        self._rolled    = True
        button.disabled = True
        await interaction.response.defer()

        roll  = random.randint(1, 20)
        nat20 = roll == 20
        nat1  = roll == 1

        if interaction.guild:
            record_roll(
                interaction.guild.id, interaction.user.id,
                nat20=nat20, nat1=nat1, hit24=(roll == 24), is_check=True,
            )

        if nat20:
            arion_note = (
                "*Arion zvedne oči od knihy. Jen se podívá. Pak se vrátí ke čtení.*\n"
                "***'..Hmm.'***"
            )
            outcome_title = "🌟  Přirozená 20!"
            outcome_desc  = (
                f"Hodil/a jsi **{roll}** — přirozená dvacítka.\n\n"
                "Zvládneš situaci s překvapivou elegancí. "
                "Muž s rohy se zastaví, přeměří tě — pak se krátce zasměje.\n\n"
                "***\"První den v práci co? "
                "Hao je moc silný.. nevím jestli má cenu se do toho turnaje vůbec hlásit.\"***\n\n"
                "*Odejde. Ani se neohlédne.*\n\n"
                f"{arion_note}"
            )
        elif nat1:
            arion_note = (
                "*Arion se podívá přes okraj knihy. Zavře ji.*\n"
                "***'..Hmm.'***"
            )
            outcome_title = "💀  Přirozená 1."
            outcome_desc  = (
                f"Hodil/a jsi **{roll}** — přirozená jednička.\n\n"
                "Snažíš se omluvit — a při tom omylem strčíš do korbelu. "
                "Zbytek piva se vylije přímo na muže s rohy.\n\n"
                "*Vedlejší stůl, který už sledoval celou situaci, umírá smíchy.*\n\n"
                "Muž se na tebe dlouze podívá. Nic neřekne. Odejde.\n\n"
                f"{arion_note}"
            )
        elif roll >= 10:
            arion_note = (
                "*Arion si tě přeměří pohledem a vrátí se ke knize.*\n"
                "***'Ujde to.'***"
            )
            outcome_title = "✅  Úspěch."
            outcome_desc  = (
                f"Hodil/a jsi **{roll}** — úspěch.\n\n"
                "Rychle se zorientuješ a omluvíš se dřív než situace stihne eskalovat.\n\n"
                "***\"V pohodě, sakra.. dávej větší pozor.\"***\n\n"
                "*Muž s rohy si prorazí cestu ke dveřím. Situace zažehnána.*\n\n"
                f"{arion_note}"
            )
        else:
            arion_note = "*Arion se ani nepodívá.*"
            outcome_title = "❌  Neúspěch."
            outcome_desc  = (
                f"Hodil/a jsi **{roll}** — neúspěch.\n\n"
                "Něco zakoktáš. Ani sám nevíš co.\n\n"
                "*Muž s rohy zakroutí očima a odejde naštvaně pryč.*\n\n"
                f"{arion_note}"
            )

        emoji = "🌟" if nat20 else ("💀" if nat1 else "🎲")
        embed = discord.Embed(
            title=f"{emoji}  {outcome_title}",
            description=f"-# *Charisma check — /roll 1d20*\n\n{outcome_desc}",
            color=0x27ae60 if roll >= 10 else 0xe74c3c,
        )
        if self.portrait_url:
            embed.set_thumbnail(url=self.portrait_url)
        embed.set_footer(text="⭐ Aurionis")

        await interaction.edit_original_response(
            embed=embed,
            view=FinalEnterView(dest_key=self.dest_key, portrait_url=self.portrait_url),
        )


# ══════════════════════════════════════════════════════════════════════════════
# KROK 11 — Vstup do světa + přidělení role destinace
# ══════════════════════════════════════════════════════════════════════════════

# ID rolí pro destinace
DEST_ROLE_IDS = {
    "lumenie":     1479574022130892890,
    "aquion":      1479573952832733314,
    "draci_skala": 1479574079160979588,
}

# ID hub kanálů
DEST_HUB_CHANNEL_IDS = {
    "lumenie":     1479577214562467932,   # #hub-lumenie
    "aquion":      1479577365410480260,   # #hub-aquion
    "draci_skala": 1479577639537610872,   # #hub-draci-skala
}

# ID chat kanálů hned pod huby — hráč se sem přesune po tutoriálu
DEST_CHAT_CHANNEL_IDS = {
    "lumenie":     1485643091426676816,
    "aquion":      1485643326358290542,
    "draci_skala": 1485643414501462057,
}

_HUB_FOOTER = (
    "\n\n-# <:arion:1477303464781680772> Domluv se v chatu kde se napojíš na příběh — "
    "nový hráč začíná ve skupině "
    "Metagaming tu neprováděj "
    "**Dont dare a devil**"
)

DEST_HUB_WELCOME = {
    "lumenie":     f'*„Lumenie"* — řekneš si pro sebe Všechno ti připadá zvláštní{_HUB_FOOTER}',
    "aquion":      f'*„Aquion"* — řekneš si pro sebe Všechno ti připadá zvláštní{_HUB_FOOTER}',
    "draci_skala": f'*„Dračí skála"* — řekneš si pro sebe Všechno ti připadá zvláštní{_HUB_FOOTER}',
}

class FinalEnterView(discord.ui.View):
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=600)
        self.dest_key     = dest_key
        self.portrait_url = portrait_url
        dest = DESTINATIONS[dest_key]
        self.enter_btn.label = f"Vstoupit — {dest['emoji']} {dest['name']}"

    @discord.ui.button(label="Vstoupit", style=discord.ButtonStyle.primary, emoji="🚪")
    async def enter_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # ── Přiřaď roli destinace ──────────────────────────────────────────
        role_id = DEST_ROLE_IDS.get(self.dest_key)
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role:
                try:
                    await interaction.user.add_roles(role)
                except Exception as e:
                    print(f"[onboard] Nepodařilo se přidat roli destinace: {e}")

        # ── První stránka — probuzení ──────────────────────────────────────
        embed = discord.Embed(
            title="✨  ..",
            description=(
                "***'..Hm?'***\n\n"
                "Chvíli ti trvá než se vzpamatuješ.\n\n"
                "*Kde to jsem.. kdo jsem?*\n\n"
                "Podíváš se na své ruce...\n\n"
                "*'Takový.. jsem byl vždy?'*"
            ),
            color=0x2c3e50,
        )
        if self.portrait_url:
            embed.set_thumbnail(url=self.portrait_url)
        embed.set_footer(text="⭐ Aurionis")

        await interaction.response.edit_message(
            embed=embed,
            view=ArrivalStreetView(dest_key=self.dest_key, portrait_url=self.portrait_url),
        )

        # ── Pošli uvítání do hub kanálu destinace ─────────────────────────
        hub_channel_id = DEST_HUB_CHANNEL_IDS.get(self.dest_key, 0)
        if hub_channel_id:
            hub_channel = interaction.guild.get_channel(hub_channel_id)
            if hub_channel:
                try:
                    await hub_channel.send(
                        f"Nový dobrodruh F3: {interaction.user.mention}\n\n"
                        + DEST_HUB_WELCOME[self.dest_key]
                    )
                except Exception as e:
                    print(f"[onboard] Nepodařilo se poslat uvítání do hub kanálu: {e}")

        # ── Přidej hráče do chat kanálu (vidí + píší) ─────────────────────
        chat_channel_id = DEST_CHAT_CHANNEL_IDS.get(self.dest_key, 0)
        if chat_channel_id:
            chat_channel = interaction.guild.get_channel(chat_channel_id)
            if chat_channel:
                try:
                    await chat_channel.set_permissions(
                        interaction.user,
                        read_messages=True,
                        send_messages=True,
                    )
                    dest = DESTINATIONS[self.dest_key]
                    await chat_channel.send(
                        f"{interaction.user.mention} {dest['emoji']} *přichází do {dest['name']}.*"
                    )
                except Exception as e:
                    print(f"[onboard] Nepodařilo se přidat do chat kanálu: {e}")

        # ── Zápis do deníku ────────────────────────────────────────────────
        try:
            from datetime import datetime
            from src.utils.paths import DIARIES as diary_path
            uid        = str(interaction.user.id)
            date_str   = datetime.now().strftime("%d.%m.")

            diaries = {}
            if os.path.exists(diary_path):
                with open(diary_path, "r", encoding="utf-8") as f:
                    diaries = json.load(f)

            entries = diaries.get(uid, [])
            entries.append({
                "text":   f"{date_str} — Tutorial byl dokončen, vítej v Aurionisu.",
                "pinned": True,
                "tag":    "⭐",
            })
            diaries[uid] = entries

            with open(diary_path, "w", encoding="utf-8") as f:
                json.dump(diaries, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[onboard] Nepodařilo se zapsat do deníku: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# KROK 11 — Příjezd: Ulice
# ══════════════════════════════════════════════════════════════════════════════

class ArrivalStreetView(discord.ui.View):
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=600)
        self.dest_key    = dest_key
        self.portrait_url = portrait_url

    @discord.ui.button(label="Rozhlédnout se", style=discord.ButtonStyle.secondary, emoji="👁️")
    async def look_around(self, interaction: discord.Interaction, button: discord.ui.Button):
        dest = DESTINATIONS[self.dest_key]

        if self.dest_key == "lumenie":
            street_desc = (
                "Světlo se rozpustí a ty stojíš na dlážděné ulici.\n\n"
                "Modré lampy osvětlují cestu.. zatímco "
                "vzduch voní po svíčkách a starém kameni. "
                "V dálce se tyčí **katedrála světla**, její věž je majestátní"
                "Po **mostě přes řeku Auriel** proudí davy "
                "obchodníků, poutníků i bojovníků s cechovní pečetí.\n\n"
                "*Tohle je místo kde každý slavný dobrodruh napsal první řádek svého příběhu.*\n\n"
                "*A ty právě píšeš ten svůj*"
            )
        elif self.dest_key == "aquion":
            street_desc = (
                "Světlo zmizí a pod nohama zaskřípe dřevo mola.\n\n"
                "V Aquionu je klid, ale když se zaposloucháš, "
                "slyšíš rušnou tržnici z dálky. "
                "Kanály se třpytí v odrazu světýlek, zatímco opodál"
                "se tyčí **klášter mágů vody**.\n\n"
                "*Říká se, že tady se dá koupit cokoliv. I pravda. I lež.*\n\n"
                "*Záleží jen na tom, co si dovolíš hledat a kolik máš zrovna zlaťáků..*"
            )
        elif self.dest_key == "draci_skala":
            street_desc = (
                "Světlo povolí a ostrý horský vzduch tě přivítá jako facka.\n\n"
                "Furt se tady pracuje, kamenné ulice ještě nemají ani jména "
                "a prochází tu spousta ozbrojených jedinců. "
                "Vysoko nad hradbami lítá drak, střeží pevnost, zatímco "
                "dole roste město, které se teprve učí být městem.\n\n"
                "*Každý ví kdo tu vládne.*\n\n"
                "*A teď jsi tu i ty. Náhoda? Nebo ne?*"
            )
        else:
            street_desc = "*Svět se otevírá před tebou.*"

        embed = discord.Embed(
            title=f"{dest['emoji']}  {dest['name']}",
            description=street_desc,
            color=dest["color"],
        )
        if dest.get("image"):
            embed.set_image(url=dest["image"])
        if self.portrait_url:
            embed.set_thumbnail(url=self.portrait_url)
        embed.set_footer(text=f"⭐ Aurionis  ·  Vítej v {dest['name']}.")

        await interaction.response.edit_message(
            embed=embed,
            view=FirstStepView(),
        )


class FirstStepView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    @discord.ui.button(label="Vykročit", style=discord.ButtonStyle.secondary, emoji="🚶")
    async def first_step(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="✨  Aurionis čeká",
            description=(
                "Uděláš první krok\n\n"
                "Příběh se začíná psát a tentokrát jsi v něm ty"
            ),
            color=0xFFD700,
        )
        embed.set_image(url=URL_TUTORIAL_END)
        embed.set_footer(text="⭐ Aurionis")
        await interaction.response.edit_message(embed=embed, view=None)


# ══════════════════════════════════════════════════════════════════════════════
# VAROVÁNÍ — před spuštěním tutoriálu
# ══════════════════════════════════════════════════════════════════════════════

class TutorialWarningView(discord.ui.View):
    """Úvodní varování se třemi možnostmi před spuštěním tutoriálu."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Spustit tutoriál", style=discord.ButtonStyle.success, emoji="✨", row=0)
    async def start_tutorial(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="✨ Volání Hvězdy",
            description=(
                "*Ticho a prázdno.. jsi ve své mysli a nebo putuješ nekonečným vesmírem?*\n\n"
                "Přemítáš o tom co je pro tebe realita a pak tě oslepí jasné světlo.\n\n"
                "**'Zdravím tě, Vyvolený...'**"
            ),
            color=0xFFD700,
        )
        embed.set_image(url=URL_PLAKAT_HVEZDA)
        await interaction.response.edit_message(embed=embed, view=TutorialPartOneView())

    @discord.ui.button(label="Už mám postavu", style=discord.ButtonStyle.secondary, emoji="📜", row=0)
    async def has_character(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📜  Existující postava",
            description=(
                "Pokud přicházíš z jiného Aurionis projektu a máš hotovou postavu, "
                "napiš administrátorovi — ten ti postavu přesune.\n\n"
                "*Tutorial pro tebe není potřeba.*"
            ),
            color=0x95a5a6,
        )
        embed.set_footer(text="⭐ Aurionis  ·  Kontaktuj administrátora.")
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="Zavřít tutorial", style=discord.ButtonStyle.danger, emoji="✖️", row=0)
    async def close_tutorial(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await interaction.message.delete()


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class Onboarding(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup_tutorial", description="Spusť úvodní tutorial Aurionisu")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_tutorial(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚠️  Úvodní tutorial",
            description=(
                "**Pozor** — pokud budeš pokračovat, spustíš úvodní tutorial "
                "a tvorbu postavy.\n\n"
                "⏱️ *Délka: přibližně 15 minut*\n\n"
                "Pokud už máš postavu z jiného Aurionis projektu, "
                "klikni na **Už mám postavu**."
            ),
            color=0xe67e22,
        )
        embed.set_footer(text="⭐ Aurionis  ·  Vyber možnost níže.")

        await interaction.response.send_message("✅ Brána do Actu II byla vztyčena.", ephemeral=True)
        await interaction.channel.send(embed=embed, view=TutorialWarningView())


async def setup(bot):
    await bot.add_cog(Onboarding(bot))