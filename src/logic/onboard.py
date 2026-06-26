import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import os
import json
import functools
from src.logic.stats import init_stats, STAT_LABELS
from src.utils.json_utils import load_json, save_json
from src.database.characters import pkey, ensure_active
from src.core.dnd.roll_stats import record_roll

# ── Konfigurace ───────────────────────────────────────────────────────────────

ROLE_DOBRODRUH_F3_ID = 1476056192643104768
from src.utils.paths import PROFILES as DATA_FILE, ECONOMY as ECONOMY_FILE, TUTORIAL_MSG as TUTORIAL_MSG_FILE

TUTORIAL_CHANNEL_ID = 1476045697496252607
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
        "desc":  "Město začátků. Každý slavný dobrodruh napsal první řádek svého příběhu zrovna tady. Dominuje mu **katedrála světla** a kamenný most přes řeku **Auriel**, symbol naděje a řádu. Domov nejvyššího paladina **Reinharda** a jeho bratrstva paladinů a rytířů. Lumenie nyní prochází krizí.",
        "color": 0x3498db,
        "image": "https://media.discordapp.net/attachments/1484572118267068598/1484572933023334621/Copilot_20260320_145920.png?ex=69beb7c9&is=69bd6649&hm=a624e462ff950ed84f2542777c22d63ca5710c50834113b85afbc532176cc430&=&format=webp&quality=lossless&width=822&height=548",
    },
    "aquion": {
        "emoji": "🌊",
        "name":  "Aquion",
        "desc":  "Největší obchodní město Aurionisu, postavené na síti kanálů a plovoucích plošin. Říká se, že tady se dá koupit cokoliv: pravda i lež. Klášter mágů vody střeží rovnováhu sil a prakticky řídí celou ekonomickou situaci Kalexie.",
        "color": 0x1abc9c,
        "image": "https://media.discordapp.net/attachments/1484572118267068598/1484572857559285801/Copilot_20260320_150340.png?ex=69beb7b7&is=69bd6637&hm=80ace1e169079d9845326e567a5ded22e9d6bcf3dd3dc01a0b22c214864cbc40&=&format=webp&quality=lossless&width=822&height=548",
    },
    "draci_skala": {
        "emoji": "🏔️",
        "name":  "Dračí skála",
        "desc":  "Mladé město vytesané do útesů vyhaslé sopky, kde vládne **Alice Aurelion** — samozvaná královna s darem dračí řeči. Její draci krouží nad hradbami a každý nový příchozí si musí vybrat: věrně sloužit, nebo odejít. Alice nebyla viděna na veřejnosti od chvíle, kdy se ukázala v Aquionu.",
        "color": 0xe74c3c,
        "image": "https://media.discordapp.net/attachments/1484572118267068598/1484573012585087057/Copilot_20260320_150049.png?ex=69beb7dc&is=69bd665c&hm=7a0e1d64b751d2b6476e900a3f8b2f2ade7b238bfcf5b662b2487eee7d775d05&=&format=webp&quality=lossless&width=822&height=548",
    },
}

# ── Loadouty (tutorial) ────────────────────────────────────────────────────────

LOADOUTS = {
    "one_handed": {
        "emoji": "🗡️",
        "name": "Lehký meč",
        "desc": "Klasický bojovník s jednoruční zbraní",
        "items": ["mec_z_praveke_kosti", "brasna", "kozena_tunika", "lektvar_zivota"],
        "perk": "one_handed_1",
    },
    "two_handed": {
        "emoji": "⚔️",
        "name": "Obouruční meč",
        "desc": "Silný bojovník s obouruční zbraní",
        "items": ["halapartna_ohne", "brasna", "ocelovy_kyrys", "lektvar_zivota"],
        "perk": "two_handed_1",
    },
    "bow": {
        "emoji": "🏹",
        "name": "Krátký luk",
        "desc": "Lukostřelec s lukem a šípy",
        "items": ["jasanovy_luk", "sipky_10x", "brasna", "kozena_tunika", "lektvar_zivota"],
        "perk": "archery_1",
    },
    "crossbow": {
        "emoji": "🎯",
        "name": "Kuše",
        "desc": "Střelec s kuší",
        "items": ["mala_kuse", "sipky_10x", "brasna", "ocelovy_kyrys", "lektvar_zivota"],
        "perk": "archery_1",
    },
    "mage": {
        "emoji": "🔮",
        "name": "Mág",
        "desc": "Čaroděj ovládající magii",
        "items": ["magicka_hulka", "brasna", "magicka_roba", "lektvar_many"],
        "perk": "fire_magic_1",
    },
    "fire_magic": {
        "emoji": "🔥",
        "name": "Ohnivá magie",
        "desc": "Mág ovládající oheň",
        "items": ["ogniva_runa", "brasna", "magicka_roba", "lektvar_many"],
        "perk": "fire_magic_1",
    },
    "ice_magic": {
        "emoji": "❄️",
        "name": "Ledová magie",
        "desc": "Mág ovládající led",
        "items": ["ledova_runa", "brasna", "magicka_roba", "lektvar_many"],
        "perk": "ice_magic_1",
    },
    "healing_magic": {
        "emoji": "💚",
        "name": "Uzdravovací magie",
        "desc": "Lékař pomocí magie",
        "items": ["uzdravovaci_runa", "brasna", "magicka_roba", "lektvar_many"],
        "perk": "healing_magic_1",
    },
    "rogue": {
        "emoji": "🗡️",
        "name": "Tulák",
        "desc": "Rychlý tulák se dvěma dýkami",
        "items": ["nuz", "nuz", "brasna", "kozena_tunika", "lektvar_zivota"],
        "perk": "stealth_1",
    },
    "staff": {
        "emoji": "🤖",
        "name": "Bojovník s holí",
        "desc": "Mních bojující s holí",
        "items": ["bojova_hul", "brasna", "kozena_tunika", "lektvar_zivota"],
        "perk": "unarmed_1",
    },
    "acrobat": {
        "emoji": "🤸",
        "name": "Akrobata",
        "desc": "Hbitý bojovník",
        "items": ["mec_z_praveke_kosti", "brasna", "kozena_tunika", "lektvar_zivota"],
        "perk": "acrobacy_1",
    },
}

# ── Databáze ──────────────────────────────────────────────────────────────────

def update_profile(user_id, **kwargs):
    user_id = pkey(user_id)
    data    = load_json(DATA_FILE, default={})
    data.setdefault(user_id, {"rank": "F3"})
    for key, value in kwargs.items():
        data[user_id][key] = value
    save_json(DATA_FILE, data)

def add_gold(user_id: int, amount: int):
    uid  = pkey(user_id)
    data = load_json(ECONOMY_FILE, default={})
    data[uid] = data.get(uid, 0) + amount
    save_json(ECONOMY_FILE, data)

def add_registered_item_to_profile(profile: dict, item_id: str, qty: int = 1) -> None:
    inventory = profile.setdefault("inventory", [])
    for entry in inventory:
        if entry.get("type") == "registered" and entry.get("id") == item_id:
            entry["qty"] = entry.get("qty", 1) + qty
            return
    inventory.append({"type": "registered", "id": item_id, "qty": qty})



# ══════════════════════════════════════════════════════════════════════════════
# KROK 1 — Volání Hvězdy
# ══════════════════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════
# ZNOVUPOUŽITELNÉ STAVEBNÍ BLOKY TUTORIÁLU (beat + dialog s volbami)
# ═════════════════════════════════════════════════════════════

# Plakát Aurionis: Act II (pozn.: Discord CDN URL s ?ex=... expiruje — ideálně přehostit)
URL_PLAKAT_ACT2 = "https://cdn.discordapp.com/attachments/1477815245908082779/1519240012724699158/IMG_0441.png?ex=6a3d7ec5&is=6a3c2d45&hm=26f0ff116d82c11d495eefb60575000635d870d73184d4fa0ebfc890f3edd2b7&"

URL_PLAKAT_ALICE = "https://cdn.discordapp.com/attachments/1477815245908082779/1519240013882200194/IMG_0176.png?ex=6a3d7ec5&is=6a3c2d45&hm=cedc265b8206e076339265f104ffdebdaccb43eb58ff3b36ecfc8a6af174cf3e&"
URL_PLAKAT_AURELION = "https://cdn.discordapp.com/attachments/1477815245908082779/1520054580463796314/IMG_0479.png?ex=6a3fcca5&is=6a3e7b25&hm=e67202576084d8a35f7919a0de46ee21bb1ac3d9c1d5366465323e024f8884fb&"
ARION_COLOR = 0xb87333  # bronz — Arionina barva


def _arion_reply_embed(text: str, title: str = "🐱  Arion") -> discord.Embed:
    """Jednotný vzhled Arioniny repliky v dialogu."""
    e = discord.Embed(title=title, description=text, color=ARION_COLOR)
    e.set_footer(text="⭐ Aurionis")
    return e


class StoryBeatView(discord.ui.View):
    """Vizuální beat (obrázek/text) + jediné tlačítko → on_continue(interaction)."""
    def __init__(self, on_continue, *, label="Pokračovat", emoji="▶️"):
        super().__init__(timeout=600)
        self._on_continue = on_continue
        self.go.label = label
        self.go.emoji = emoji

    @discord.ui.button(label="Pokračovat", style=discord.ButtonStyle.primary, emoji="▶️")
    async def go(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._on_continue(interaction)


class DialogChoiceView(discord.ui.View):
    """
    Dialog s volbami. choices = [(label, Arionova_odpověď)].
    Po kliknutí ukáže Arionovu reakci na danou volbu + view z next_view_factory().
    Volby konvergují do stejného pokračování (žádné větvení stavu).
    """
    def __init__(self, choices, next_view_factory, *, reply_title="🐱  Arion"):
        super().__init__(timeout=600)
        self._next        = next_view_factory
        self._reply_title = reply_title
        for label, reply in choices:
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
            btn.callback = self._make_cb(reply)
            self.add_item(btn)

    def _make_cb(self, reply):
        async def cb(interaction: discord.Interaction):
            nxt = self._next()
            if not reply:  # tichá volba → pokračuje rovnou (bez repliky)
                cont = getattr(nxt, "_on_continue", None)
                if cont is not None:
                    await cont(interaction)
                    return
            embed = _arion_reply_embed(reply, self._reply_title)
            await interaction.response.edit_message(embed=embed, view=nxt)
        return cb


class TutorialPartOneView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    @discord.ui.button(label="Naslouchat hlasu", style=discord.ButtonStyle.primary, emoji="✨")
    async def listen(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ochrana — hráč s dokončeným profilem nemůže spustit tutorial znovu
        uid = pkey(interaction.user.id)
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
                "Ti, kdo jsou zváni **Vyvolenými**, stojí na rozhraní mezi oběma světy.\n\n"
                "*Pravda byla odhalena, ale jaká ta pravda vlastně je?*\n\n"
                "-# ⚠️ Tutorial bude delší! Před startem si přečti lore v **#lore**.\n"
                "-# Budete mít čas si klidně vybrat perky a vybavení"
            ),
            color=0x2f3136,
        )
        embed.add_field(
            name="❓ Než vstoupíš dál...",
            value="Byl jsi s námi od začátku, nebo přicházíš jako nová tvář?",
        )
        await interaction.response.edit_message(embed=embed, view=ActSelectionView())


# ══════════════════════════════════════════════════════════════════════════════
# KROK 2 — Rozcestník
# ══════════════════════════════════════════════════════════════════════════════

class ActSelectionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    @discord.ui.button(label="Já už příběh znám", style=discord.ButtonStyle.success, emoji="⏩")
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
                    "**Alice Aurelion** přišla s nárokem, který nikdo nečekal: krev starého rodu, "
                    "dar dračí řeči a legitimní právo na trůn Kalexie, vlastně i všech ostatních říší.\n\n"
                    "**Král Talias** ji odmítl uznat, označil ji za lhářku a podvodnici. Nyní shromažďuje vazaly a zbraně. "
                    "Aurionis se ocitl na hraně občanské války a nad vším visí stín **Turnaje Hvězdy**, kde si vítěz může přát cokoliv."
                ),
                color=0xe74c3c,
            ),
            2: discord.Embed(
                title="Kapitola II 🛡️ Zrazená přísaha",
                description=(
                    "**Reinhard**, nejvyšší paladin a symbol cti a řádu, odložil insignii "
                    "ochránce Kalexie a vstoupil do Turnaje Hvězdy sám za sebe.\n\n"
                    "*'Stanu se králem Hvězdy pro vás všechny.'*\n\n"
                    "Za ním zůstala prázdnota, obrana Kalexie se zhroutila a ti, kdo mu "
                    "věřili, zůstali bez odpovědí. Talias zuří, je pro něj stejným samozvancem jako Alice."
                ),
                color=0x3498db,
            ),
            3: discord.Embed(
                title="Kapitola III 🎭 Vládce stínů",
                description=(
                    "Muž beze jména, kterému všichni říkají **Vládce stínů**, ovládá sílu zvanou "
                    "esenciální očištění. Ta dokáže vzít schopnosti, identitu i smysl existence.\n\n"
                    "Během jediné noci v Lumenii přišly tisíce upírů o svou podstatu a "
                    "město je nyní plné uprchlíků, kteří ani nevědí, kým vlastně jsou. "
                    "Nikdo neví, kde Vládce udeří příště. První byla Lumenie, pak Aquion."
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
            "Světlo tě táhne třemi různými směry najednou. Z každého směru cítíš úplně jinou energii. "
            "Každé místo tě čeká, ale ty si můžeš vybrat jen jednu cestu.\n\n"
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
        await _show_act2_poster(interaction, dest_key="lumenie")

    @discord.ui.button(label="Dračí skála", style=discord.ButtonStyle.danger, emoji="🏔️")
    async def choose_draci_skala(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _show_act2_poster(interaction, dest_key="draci_skala")

    @discord.ui.button(label="Aquion", style=discord.ButtonStyle.secondary, emoji="🌊")
    async def choose_aquion(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _show_act2_poster(interaction, dest_key="aquion")


# ══════════════════════════════════════════════════════════════════════════════
# KROK 5 — Random Encounter: První lekce s Arion
# ══════════════════════════════════════════════════════════════════════════════

async def _show_act2_poster(interaction: discord.Interaction, dest_key: str):
    """Beat: plakát Aurionis Act II → první kontakt s Arion."""
    update_profile(interaction.user.id, destination=dest_key)
    embed = discord.Embed(title="Velký omnyoji Hao", color=0x1a1a2e)
    embed.set_image(url=URL_PLAKAT_ACT2)
    await interaction.response.edit_message(
        embed=embed,
        view=StoryBeatView(functools.partial(_show_first_contact, dest_key=dest_key)),
    )


async def _show_first_contact(interaction: discord.Interaction, dest_key: str):
    """Dialog: první setkání s Arion — volby → reakce → hod na obratnost."""
    embed = discord.Embed(
        title="🐱",
        description=(
            "> *Pomalu otevřeš oči a všechno se ti zdá zmatené, ale až děsivě známé. "
            "Hlavou ti prochází myšlenka — jestli jsi tu už někdy nebyl. "
            "Modré lampy osvětlují ulici, zatímco ty stojíš před cechem dobrodruhů.*\n\n"
            "Z rohu uličky vyběhne bronzová kočička v magickém klobouku a šťastně zamňouká\n\n"
            "**\'No ne, další! Heeej, ahoooj — nechceš být dobrodruh?\'**"
        ),
        color=0x3498db,
    )
    embed.set_footer(text="⭐ Aurionis  ·  Co odpovíš?")
    choices = [
        ("Jasně, proč ne?",  "„Tak jo. Někdo jako ty se hodí vždycky. V týhle době jsou dobří silní lidé potřeba.“"),
        ("Mluvící kočka!!!", "*Naježí se.*  „Mluvící člověk!!“ *řekne posměšně.*  „Pche. Vy vyvolení jste všichni stejní.“"),
        ("Co jsi zač?",      "„Vedu guildu bojovníků, dobrodruhů.. říkej si tomu jak chceš.“  *Pousměje se, očividně je na sebe pyšná.*"),
        ("(mlčet)",          "„Halooo? Ty jsi ten tichý typ, co?“"),
    ]
    next_factory = lambda: StoryBeatView(
        functools.partial(_start_encounter, dest_key=dest_key),
        label="Ukaž, co umíš!", emoji="🤸",
    )
    await interaction.response.edit_message(
        embed=embed,
        view=DialogChoiceView(choices, next_factory),
    )


async def _start_encounter(interaction: discord.Interaction, dest_key: str):
    update_profile(interaction.user.id, destination=dest_key)

    arion_roll = random.randint(1, 12)

    embed = discord.Embed(
        title="🤸  Ukaž, co umíš!",
        description=(
            "Arion zamrská tlapkou a vyčaruje třpytivou kouli vody — "
            "a než stačíš cokoliv říct, hodí ji rovnou po tobě!"
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
                    f"*Spokojeně se culí a mrskne ocasem.*"
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
                    f"a ty se rozplynou. *Pořád se chichotá.*"
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
                "*'Já jsem Arion!'*  řekne pyšně jako by to bylo to "
                "nejdůležitější sdělení světa.\n\n"
                "Líně si olízne srst a zvedne pohled k tobě\n\n"
                "*'A ty jsi?'*"
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
        ensure_active(interaction.user.id, new_name)
        update_profile(interaction.user.id, name=new_name)
        try:
            await interaction.user.edit(nick=new_name)
        except Exception:
            pass

        embed = discord.Embed(
            title="🐱  Hm..",
            description=(
                f"*'{new_name}.'*\n\n"
                "Arion to zopakuje nahlas a pomalu jako by zkoušela jak tvé jméno zní ve vzduchu. "
                "Zamračí se a prohlíží si tě velmi důkladně.\n\n"
                "Pak se něco změní.\n\n"
                "Rozběhne se přímo proti tobě."
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

    @discord.ui.button(label="Setřást Arion  /check", style=discord.ButtonStyle.danger, emoji="💪")
    async def throw_arion(self, interaction: discord.Interaction, button: discord.ui.Button):
        roll = random.randint(1, 20)

        if roll >= 11:
            desc = (
                f"-# 🎲 STR check — **{roll}**/20\n\n"
                "Chytíš ji za límec klobouku a prudce zahodíš.\n\n"
                "Arion přistane na čtyřech tlapách pár metrů od tebe, "
                "narovná si klobouk a kouká na tebe s novým respektem.\n\n"
                "*'Oooh... Takže ty jsi tenhle typ.'*\n\n"
                "Chvíli vypadá jako by nad něčím přemýšlela.\n\n"
                "*'Vzpomínáš si na něco?'*"
            )
        else:
            desc = (
                f"-# 🎲 STR check — **{roll}**/20\n\n"
                "Zkusíš ji shodit, ale Arion se drží jako klíště. "
                "Přeleze přes tvé rameno, pak po zádech, pak zase zpátky..\n\n"
                "*'Nedaří se ti mě shodit, že?'* poznamená spokojeně.\n\n"
                "*'Vzpomínáš si na něco?'*"
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
                "*'Hm..'*\n\n"
                "Sleze dolů a postaví se před tebe.\n\n"
                "*'Vzpomínáš si na něco?'*"
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
        embed.set_footer(text="⭐ Aurionis  ·  Co řekneš?")
        aura_reply = (
            "Arion zvedne hlavu a její výraz se vrátí do normálu — "
            "nebo aspoň do toho, co u ní jako normál působí.\n\n"
            "*'…Ale nic, vyvolený. Jen máš zajímavou auru.'*\n\n"
            "Otočí se a zamíří ke dveřím cechu. Klobouk se jí narovná sám od sebe.\n\n"
            "*'Pojď dovnitř.'*"
        )
        choices = [
            ("Hm?",         aura_reply),
            ("Co se děje?", aura_reply),
            ("(mlčet)",     aura_reply),
        ]
        next_factory = lambda: StoryBeatView(functools.partial(_show_alice_poster, dest_key=self.dest_key))
        await interaction.response.edit_message(
            embed=embed,
            view=DialogChoiceView(choices, next_factory, reply_title="🐱  ..Ale nic."),
        )

    @discord.ui.button(label="Nevzpomínám si na nic..", style=discord.ButtonStyle.secondary, emoji="🤔")
    async def just_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go_hm(
            interaction,
            title="🐱  Hm..",
            description=(
                "Arion tě chvíli pozoruje a pak tiše sklopí pohled\n\n"
                "*'Hm..'*\n\n"
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
                "*'Většina lidí taky nemluví..'*\n\n"
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
                "*'Hm..'*\n\n"
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
                "nebo aspoň do toho, co u ní jako normál působí.\n\n"
                "*'...Ale nic, vyvolený.'*\n\n"
                "Otočí se a zamíří ke dveřím cechu. "
                "Klobouk se na hlavě narovná sám od sebe.\n\n"
                "*'Pojď dovnitř'*"
            ),
            color=0x2c3e50,
        )
        embed.set_footer(text="⭐ Aurionis  ·  Uvnitř je tepleji.")
        await interaction.response.edit_message(
            embed=embed,
            view=EnterGuildInsideView(dest_key=self.dest_key),
        )


async def _show_alice_poster(interaction: discord.Interaction, dest_key: str):
    """Beat: plakát Matka draků Alice Aurelion → vstup do cechu."""
    embed = discord.Embed(title="Matka draků Alice Aurelion", color=0x1a1a2e)
    embed.set_image(url=URL_PLAKAT_ALICE)
    await interaction.response.edit_message(
        embed=embed,
        view=EnterGuildInsideView(dest_key=dest_key),
    )


async def _show_acceptance(interaction: discord.Interaction, dest_key: str):
    """Beat A: Arion přijme hráče mezi dobrodruhy + dialog → staty."""
    embed = discord.Embed(
        title="📖  Přijetí mezi dobrodruhy",
        description=(
            "Arion přeskočí pult jedním plynulým pohybem a přistane na druhé straně, "
            "kde otevře tlustou, živoucí knihu.\n\n"
            "*„..Standardní procedura. Přijmu tě mezi dobrodruhy.“*"
        ),
        color=0x2c3e50,
    )
    embed.set_image(url=URL_ARION_ENCOUNTER)
    embed.set_footer(text="⭐ Aurionis  ·  Co řekneš?")
    choices = [
        ("Co když nechci být dobrodruh?",          "„Hloupost! Každý chce být dobrodruh!“"),
        ("(mlčet)",                                None),
        ("Jakto, že můžeš mluvit když jsi kočka?", "„Ty s tím nedáš pokoj, co? Jsem magická! Magická kočka!“"),
    ]
    next_factory = lambda: StoryBeatView(functools.partial(_show_stats_intro, dest_key=dest_key))
    await interaction.response.edit_message(
        embed=embed,
        view=DialogChoiceView(choices, next_factory),
    )


async def _show_stats_intro(interaction: discord.Interaction, dest_key: str):
    """Beat B: destička se rozsvítí → rozdělení statů."""
    embed = discord.Embed(
        title="✨",
        description=(
            "Přejede tlapkou přes zvláštní destičku vedle knihy a ta se rozsvítí "
            "modrou aurou, jako by reagovala na dotyk.\n\n"
            "*„Tak se podíváme, z jakého jsi těsta.“*"
        ),
        color=0x2c3e50,
    )
    embed.set_footer(text="⭐ Aurionis  ·  Rozděl své body.")
    labels     = ['STR', 'DEX', 'INS', 'INT', 'CHA', 'WIS']
    base_stats = {s: 0 for s in labels}
    init_stats(interaction.user.id, base_stats=base_stats, ap=5)
    await interaction.response.edit_message(
        embed=embed,
        view=TutorialSPView(
            dest_key=dest_key,
            portrait_url=None,
            sp_remaining=5,
            stats={s: 0 for s in labels},
        ),
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
                "Dveře se za tebou zavřou a hluk ulice utichne.\n\n"
                "Uvnitř panuje svérázný pořádek — u stolu v rohu se hádají dva trpaslíci "
                "o tom, kdo zabil draka jako poslední. Častokrát slyšíš jméno Aurelion. "
                "Někdo jiný spí na lavici s helmou přes obličej."
            ),
            color=0x2c3e50,
        )
        embed.set_footer(text="⭐ Aurionis  ·  Co řekneš?")
        choices = [
            ("Je to tu hezké.",        "„Díky! A taky si tu pořádně můžeš namastit kapsu a potkat nové kamarády — super, ne?“"),
            ("Vypadají silně",         "„Tihleti? Věř mi — pokud chceš být opravdu silný, musíš jít za svoje limity.“"),
            ("Jak jsem se tady vzal?", "„Jo, to nevim.. ale nejsi první ani poslední.“"),
        ]
        next_factory = lambda: StoryBeatView(functools.partial(_show_acceptance, dest_key=self.dest_key))
        await interaction.response.edit_message(
            embed=embed,
            view=DialogChoiceView(choices, next_factory),
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
# AP rozdělování v tutorialu
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
    """Hráč rozděluje 5 AP přímo v tutorialu — každý klik = 1 AP do atributu."""

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
            from src.logic.stats import spend_ap
            success = spend_ap(interaction.user.id, stat, 1)
            if not success:
                await interaction.response.defer()
                return

            self.stats[stat] = self.stats.get(stat, 0) + 1
            self.sp_remaining -= 1
            self._build_buttons()

            stats_lines = "  ·  ".join(
                f"**{s}** {self.stats.get(s, 0)}" for s in ['STR', 'DEX', 'INS', 'INT', 'CHA', 'WIS']
            )

            if self.sp_remaining > 0:
                desc = (
                    f"**+1 {stat}** — {STAT_FULL_NAMES[stat]} zvýšena.\n\n"
                    f"{stats_lines}\n\n"
                    f"*Zbývá: **{self.sp_remaining} AP***"
                )
                footer = f"⭐ Aurionis  ·  {self.sp_remaining} AP zbývá"
            else:
                desc = (
                    f"**+1 {stat}** — {STAT_FULL_NAMES[stat]} zvýšena.\n\n"
                    f"{stats_lines}\n\n"
                    "*'Dobrá volba.'*\n\n"
                    "*Světelné koule zhasnou. Sken je kompletní.*"
                )
                footer = "⭐ Aurionis  ·  Všechny AP rozděleny"

            embed = discord.Embed(
                title="🎯  Attribute Pointy",
                description=desc,
                color=0x9b59b6,
            )
            embed.set_footer(text=footer)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def _reset_callback(self, interaction: discord.Interaction):
        labels = ['STR', 'DEX', 'INS', 'INT', 'CHA', 'WIS']
        from src.logic.stats import init_stats
        init_stats(interaction.user.id, base_stats={s: 0 for s in labels}, ap=5)
        self.stats = {s: 0 for s in labels}
        self.sp_remaining = 5
        self._build_buttons()

        embed = discord.Embed(
            title="🎯  Attribute Pointy",
            description=(
                "AP resetovány. Rozhodni znovu.\n\n"
                "*Zbývá: **5 AP***"
            ),
            color=0x9b59b6,
        )
        embed.set_footer(text="⭐ Aurionis  ·  5 AP zbývá")
        await interaction.response.edit_message(embed=embed, view=self)

    async def _done_callback(self, interaction: discord.Interaction):
        labels      = ['STR', 'DEX', 'INS', 'INT', 'CHA', 'WIS']
        stats_lines = "  ·  ".join(f"**{s}** {self.stats.get(s, 0)}" for s in labels)

        embed = discord.Embed(
            title="🖼️  Ještě jedna věc...",
            description=(
                f"-# {stats_lines}\n\n"
                "Arion nakloní hlavu na stranu.\n\n"
                "*'Můžu si tě nakreslit do záznamu? Miluji umění.'*\n\n"
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
            "*'Proč vlastně chceš být dobrodruhem?'*\n\n"
            "-# *Tohle pole uvidí každý, kdo si průkaz prohlédne.*"
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
            "Arion vytvoří magické plátno a chvíli tě soustředěně pozoruje. "
            "Pak začne kreslit. Za pár vteřin je hotovo a spokojeně přikývne sama pro sebe.\n\n"
            "*'Moc hezké...'*\n\n"
        )
    else:
        portrait_text = (
            "Arion zavře knihu a jen mávne rukou\n\n"
            "*'Jak chceš, tak se příště zastav.'*\n\n"
        )

    embed = discord.Embed(
        title="📜  Průkaz dobrodruha",
        description=(
            portrait_text +
            "Sáhne pod pult a vytáhne starý kožený váček s cechovní pečetí\n\n"
            "*'Mňau.. Vstupní poplatek je sto zlatých...'*\n\n"
            "Arion si hluboce povzdychne, ale následně výraz změní v euforii\n\n"
            "*'...ale jsou temné časy a každý dobrodruh se počítá "
            "...takže tentokrát platíme my vám!'*"
        ),
        color=0xFFD700,
    )
    if portrait_url:
        embed.set_thumbnail(url=portrait_url)
    embed.set_footer(text="⭐ Aurionis  ·  Co řekneš?")

    choices = [
        ("Neskončíte takhle švorc?",
         "„Pravděpodobně! Ale jak říkám — hodí se nám teď každý schopný dobrodruh!“"),
        ("Díky.", "„Není zač.“"),
        ("(mlčet)", None),
    ]
    next_factory = lambda: StoryBeatView(
        functools.partial(_show_card_handover, dest_key=dest_key,
                          portrait_url=portrait_url, stats=stats)
    )
    await interaction.response.edit_message(
        embed=embed,
        view=DialogChoiceView(choices, next_factory),
    )


async def _show_card_handover(
    interaction: discord.Interaction,
    dest_key: str,
    portrait_url: str | None,
    stats: dict | None = None,
):
    if stats:
        stats_line = "  ·  ".join(f"**{k}** {v}" for k, v in stats.items())
        stats_scene = (
            f"\n\nVidíš, jak se magicky na průkaz vyrývají čísla.\n"
            f"-# {stats_line}\n\n"
            f"*Co to znamená?*"
        )
    else:
        stats_scene = ""

    embed = discord.Embed(
        title="📜  Průkaz dobrodruha",
        description=(
            "Načmárá tvé jméno na nějaký formulář a pak ti podá váček přes pult."
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
                "Arion se přehoupne přes pult a kouká na čísla na tvém průkazu.\n\n"
                "*'Magický sken dokáže zčásti odhadnout tvou přirozenou sílu "
                "a převést ji na konkrétní čísla.'*\n\n"
                "*'Přirozená síla?..'*\n\n"
                "*'Můžeš se od toho odrazit a vědět, v čem se chceš zlepšit.'*"
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

        uid = pkey(interaction.user.id)
        profile = load_json(DATA_FILE, default={})
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
                f"*'Svět tam venku není moc přívětivý.. "
                f"obzvlášť teď, za Turnaje. Dávej na sebe pozor.'*\n\n"
                f"*'{dest['emoji']} {dest['name']} tě čeká'*\n\n"
                "*Arion ti přestane věnovat pozornost. Teď je čas se vyzbrojit.*"
            ),
            color=0xFFD700,
        )
        if self.portrait_url:
            embed.set_thumbnail(url=self.portrait_url)
        embed.set_footer(text="⭐ Aurionis  ·  Vyber si vybavení.")

        await interaction.edit_original_response(
            embed=embed,
            view=LoadoutSelectView(dest_key=self.dest_key, portrait_url=self.portrait_url),
        )




# ══════════════════════════════════════════════════════════════════════════════
# NOVÝ FLOW: LOADOUT → PERKY
# ══════════════════════════════════════════════════════════════════════════════

class LoadoutSelectView(discord.ui.View):
    """Hráč si vybere loadout (vybavení + prvotní perk)."""
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=600)
        self.dest_key = dest_key
        self.portrait_url = portrait_url
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        for loadout_id, loadout in LOADOUTS.items():
            btn = discord.ui.Button(
                label=f"{loadout['emoji']} {loadout['name']}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"loadout:{loadout_id}",
            )
            btn.callback = self._make_callback(loadout_id)
            self.add_item(btn)

    def _make_callback(self, loadout_id: str):
        async def callback(interaction: discord.Interaction):
            await _show_perk_selection(
                interaction,
                dest_key=self.dest_key,
                portrait_url=self.portrait_url,
                loadout_id=loadout_id,
            )
        return callback


async def _show_perk_selection(
    interaction: discord.Interaction,
    dest_key: str,
    portrait_url: str | None,
    loadout_id: str,
):
    """Zobraz výběr 4 perků."""
    loadout = LOADOUTS.get(loadout_id)
    if not loadout:
        await interaction.response.defer()
        return

    embed = discord.Embed(
        title="🎯  Zvol si 4 perky",
        description=(
            f"Vybral/a sis loadout **{loadout['name']}**.\n\n"
            f"Dostaneš prvotní perk: **{loadout['perk']}** a startovní položky.\n\n"
            "Teď si vyber 4 dodatečné perky dle svého uvážení.\n\n"
            "-# Tip: Perky se ti později hodí v boji. Zvol si moudře!"
        ),
        color=0x9b59b6,
    )
    if portrait_url:
        embed.set_thumbnail(url=portrait_url)
    embed.set_footer(text="⭐ Aurionis  ·  Vyber si perky.")

    view = PerkSelectionView(
        dest_key=dest_key,
        portrait_url=portrait_url,
        loadout_id=loadout_id,
        selected_perks=[],
        max_perks=4,
    )
    await interaction.response.edit_message(embed=embed, view=view)


class PerkSelectionView(discord.ui.View):
    """Hráč si vybere 4 perky."""
    def __init__(self, dest_key: str, portrait_url: str | None, loadout_id: str,
                 selected_perks: list[str], max_perks: int):
        super().__init__(timeout=600)
        self.dest_key = dest_key
        self.portrait_url = portrait_url
        self.loadout_id = loadout_id
        self.selected_perks = selected_perks
        self.max_perks = max_perks

        self._build_perk_picker()
        self._add_finish_button()

    def _available_perks(self) -> list[tuple[str, str]]:
        """Vrať perky dostupné pro tutorialový výběr."""
        try:
            from src.core.dnd.perks import load_perks
            perks = load_perks()
        except Exception as e:
            print(f"[onboard] Chyba při načtení perků: {e}")
            perks = {}

        perk_list = []
        blocked = set(self.selected_perks)
        loadout = LOADOUTS.get(self.loadout_id, {})
        if loadout.get("perk"):
            blocked.add(loadout["perk"])

        for perk_id, perk in perks.items():
            if perk_id in blocked:
                continue
            is_tier_one = perk_id.endswith("_1") or perk_id == "magicke_citeni"
            if is_tier_one and (perk.get("learnable") or perk_id in ["fire_magic_1", "ice_magic_1", "healing_magic_1"]):
                perk_list.append((perk_id, perk.get("name", perk_id)))

        return perk_list

    def _build_perk_picker(self):
        remaining = self.max_perks - len(self.selected_perks)
        if remaining <= 0:
            return

        perk_list = self._available_perks()
        if not perk_list:
            btn = discord.ui.Button(
                label="Perky se nepodařilo načíst",
                style=discord.ButtonStyle.danger,
                disabled=True,
            )
            self.add_item(btn)
            return

        options = [
            discord.SelectOption(label=perk_name[:100], value=perk_id)
            for perk_id, perk_name in perk_list[:25]
        ]
        picker = discord.ui.Select(
            placeholder=f"Vyber zbývající perky ({remaining})",
            min_values=1,
            max_values=min(remaining, len(options)),
            options=options,
            row=0,
        )
        picker.callback = self._select_perks
        self.add_item(picker)

    async def _select_perks(self, interaction: discord.Interaction):
        remaining = self.max_perks - len(self.selected_perks)
        for perk_id in interaction.data.get("values", [])[:remaining]:
            if perk_id not in self.selected_perks:
                self.selected_perks.append(perk_id)

        self.clear_items()
        self._build_perk_picker()
        self._add_finish_button()

        selected_str = "\n".join(f"- `{perk_id}`" for perk_id in self.selected_perks) or "*Zatím nic*"
        embed = discord.Embed(
            title="🎯  Zvol si 4 perky",
            description=(
                f"Vybrané perky:\n{selected_str}\n\n"
                f"Zbývá: **{self.max_perks - len(self.selected_perks)}**"
            ),
            color=0x9b59b6,
        )
        if self.portrait_url:
            embed.set_thumbnail(url=self.portrait_url)
        embed.set_footer(text="⭐ Aurionis")
        await interaction.response.edit_message(embed=embed, view=self)

    def _add_finish_button(self):
        if len(self.selected_perks) >= self.max_perks:
            confirm_btn = discord.ui.Button(
                label="Potvrdit výběr",
                style=discord.ButtonStyle.success,
                emoji="✅",
                row=4,
            )
            confirm_btn.callback = self._finish
            self.add_item(confirm_btn)
            
            reset_btn = discord.ui.Button(
                label="Vybrat znovu",
                style=discord.ButtonStyle.danger,
                emoji="🔄",
                row=4,
            )
            reset_btn.callback = self._reset_perks
            self.add_item(reset_btn)

    async def _finish(self, interaction: discord.Interaction):
        # Hráč je hotov, přidělíme mu perky a itemy.
        await _finalize_tutorial(
            interaction,
            dest_key=self.dest_key,
            portrait_url=self.portrait_url,
            loadout_id=self.loadout_id,
            additional_perks=self.selected_perks,
        )

    async def _reset_perks(self, interaction: discord.Interaction):
        """Reset perk selection."""
        self.selected_perks = []
        self.clear_items()
        self._build_perk_picker()
        self._add_finish_button()
        
        embed = discord.Embed(
            title="🎯  Zvol si 4 perky",
            description=(
                f"Výběr resetován. Vyber si nové perky:\n\n"
                f"Zbývá: **{self.max_perks}**"
            ),
            color=0x9b59b6,
        )
        if self.portrait_url:
            embed.set_thumbnail(url=self.portrait_url)
        embed.set_footer(text="⭐ Aurionis  ·  Vyber si perky.")
        await interaction.response.edit_message(embed=embed, view=self)


async def _show_arion_farewell(interaction, dest_key, portrait_url):
    """Beat: rozloučení s Arion → plakát Poslední Aurelion → nástěnka."""
    embed = discord.Embed(
        title="🐱  Arion",
        description=(
            "Arion zaklapne knihu a usadí se na pultě.\n\n"
            "*„Tak se měj. A nezapomeň se podívat na nástěnku — "
            "i když pochybuju, že tvý úkoly nebudou rozebraný.“*"
        ),
        color=0xb87333,
    )
    embed.set_footer(text="⭐ Aurionis  ·  Co řekneš?")
    choices = [
        ("Díky, Arion, měj se", "*Kočka na tebe spokojeně zavrní.*"),
        ("Měj se, kočko",       "*Arion od tebe naštvaně odvrátí pohled.*"),
        ("(mlčet…)",            "*Arion ti packou zamává a zazubí se.*"),
    ]
    next_factory = lambda: StoryBeatView(
        functools.partial(_show_aurelion_poster, dest_key=dest_key, portrait_url=portrait_url)
    )
    await interaction.response.edit_message(
        embed=embed, view=DialogChoiceView(choices, next_factory),
    )


async def _show_aurelion_poster(interaction, dest_key, portrait_url):
    """Beat: plakát Poslední Aurelion → nástěnka."""
    embed = discord.Embed(title="Poslední Aurelion", color=0x1a1a2e)
    embed.set_image(url=URL_PLAKAT_AURELION)
    embed.set_footer(text="⭐ Aurionis  ·  Podívej se na nástěnku.")
    await interaction.response.edit_message(
        embed=embed,
        view=StoryBeatView(
            functools.partial(_show_ready, dest_key=dest_key, portrait_url=portrait_url)
        ),
    )


async def _show_ready(interaction, dest_key, portrait_url):
    """Beat: 'Připraven/a!' tipy → nástěnka."""
    embed = discord.Embed(
        title="✨  Připraven/a!",
        description=(
            "Vybral/a sis loadout a perky.\n\n"
            "Teď už je čas vstoupit do Aurionisu.\n\n"
            "-# Tip: /equip si nasadíš vybavení, /perks show zobrazí perky, "
            "/stats ukáže statistiky a /profile je tvá vizitka!"
        ),
        color=0x27ae60,
    )
    if portrait_url:
        embed.set_thumbnail(url=portrait_url)
    embed.set_footer(text="⭐ Aurionis  ·  Vítej v Aurionisu!")
    await interaction.response.edit_message(
        embed=embed,
        view=BulletinBoardView(dest_key=dest_key, portrait_url=portrait_url),
    )


async def _finalize_tutorial(
    interaction: discord.Interaction,
    dest_key: str,
    portrait_url: str | None,
    loadout_id: str,
    additional_perks: list[str],
):
    """Přidělí hráči itemy, perky a pokračuje do závěru tutorialu."""
    try:
        from src.core.dnd.perks import load_player_perks, save_player_perks

        user_id = pkey(interaction.user.id)
        loadout = LOADOUTS.get(loadout_id)
        if not loadout:
            return

        # Přidej všechny perky (prvotní + dodatečné)
        all_perks = [loadout["perk"]] + additional_perks
        player_perks = load_player_perks()
        player = player_perks.setdefault(user_id, {"perks": [], "cooldowns": {}, "progress": {}})
        player["perks"] = all_perks
        player.setdefault("cooldowns", {})
        player.setdefault("progress", {})
        save_player_perks(player_perks)

        profiles = load_json(DATA_FILE, default={})
        profile = profiles.setdefault(user_id, {"rank": "F3"})
        for item_id in loadout.get("items", []):
            add_registered_item_to_profile(profile, item_id)
        save_json(DATA_FILE, profiles)

        # Zapiš do profilu, že je hotovo
        update_profile(interaction.user.id, loadout_selected=loadout_id, perks_selected=len(additional_perks))

    except Exception as e:
        print(f"[onboard] Chyba při finalizaci tutoriálu: {e}")

    # Rozloučení s Arion → plakát Poslední Aurelion → nástěnka
    await _show_arion_farewell(interaction, dest_key, portrait_url)


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
                "a každý má vedle sebe cechovní pečeť s označením minimálního ranku. "
                "**Žádný není pro F3...**\n\n"
                "*Jasně. Musíš si nejdřív dobudovat jméno..*\n\n"
                "Pod úkoly visí ručně psaný list, "
                "jiný papír, jiný rukopis. Nadpis říká:\n\n"
                "**✨ Turnaj Hvězdy — postupující do 2. kola**\n\n"
                "*Pergamen je zatím prázdný. Nikdo ještě nepostoupil.*"
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
            "*'..Paměť se ti vrací. Pomalu... ale vrací.'*"
        )
        outcome_desc = (
            "Soustředíš se a zhluboka se nadechneš.\n\n"
            "Na vteřinu se obraz zostří.\n\n"
            "*Muž v masce.. Šašek.. stojí blíž než v první vizi, vidíš ho zřetelněji.*\n\n"
            "*Maska nedává najevo žádné emoce. Ani úsměv, ani hněv. Jen prázdnota.*\n\n"
            "*Za ním..? nebo pod ním? — voda. Všude voda a písek.*\n"
            "*Ostrov. Malý a izolovaný. Cítíš sůl a vítr..*\n\n"
            "*A pak ten hlas, klidný jako rozsudek:*\n\n"
            "**\"Dávej pozor\"**\n\n"
            "*Jméno se ti nevybaví. Ani místo.*\n"
            "*Ale víš, že to není poprvé, co jsi ho viděl/a.*\n\n"
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
        uid = pkey(interaction.user.id)
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
            "Na hlavě má démonické rohy a na tebe se "
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
                "*'..Hmm.'*"
            )
            outcome_title = "🌟  Přirozená 20!"
            outcome_desc  = (
                f"Hodil/a jsi **{roll}** — přirozená dvacítka.\n\n"
                "Zvládneš situaci s překvapivou elegancí. "
                "Muž s rohy se zastaví, přeměří tě — pak se krátce zasměje.\n\n"
                "***\"První den v práci, co? "
                "Myslím si, že to vyhraje rank 1 Hao.\"***\n\n"
                "*Odejde. Ani se neohlédne.*\n\n"
                f"{arion_note}"
            )
        elif nat1:
            arion_note = (
                "*Arion se podívá přes okraj knihy. Zavře ji.*\n"
                "*'..Hmm.'*"
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
                "*'Ujde to.'*"
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
    "\n\n-# <:arion:1477303464781680772> Domluv se v chatu, kde se napojíš na příběh. "
    "Nový hráč začíná ve skupině. "
    "Metagaming tu neprováděj. "
    "**Don't dare a devil.**"
)

DEST_HUB_WELCOME = {
    "lumenie":     f'*„Lumenie.“* řekneš si pro sebe. Všechno ti připadá zvláštní.{_HUB_FOOTER}',
    "aquion":      f'*„Aquion.“* řekneš si pro sebe. Všechno ti připadá zvláštní.{_HUB_FOOTER}',
    "draci_skala": f'*„Dračí skála.“* řekneš si pro sebe. Všechno ti připadá zvláštní.{_HUB_FOOTER}',
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
                "*'..Hm?'*\n\n"
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

        # ── Auto-přiřazení questů (musí být před hub embedem) ─────────────
        assigned: list[tuple[str, str]] = []
        try:
            from src.core.dnd.quests import (
                load_quests, save_quests, load_diaries, save_diaries,
                make_diary_entry, _migrate_entries, Category,
            )
            CITY_QUEST = {
                "lumenie":     "Stíny v srdci",
                "aquion":      "Šampion podsvětí",
                "draci_skala": "Draci",
            }
            MAIN_QUEST = "Poslední Aurelion"
            uid_int    = interaction.user.id
            uid_str    = str(uid_int)
            quests     = load_quests()
            diaries    = load_diaries()
            entries    = _migrate_entries(diaries.get(uid_str, []))

            for qname in [MAIN_QUEST, CITY_QUEST.get(self.dest_key)]:
                if qname and qname in quests:
                    qdata = quests[qname]
                    if uid_int not in qdata.get("members", []):
                        qdata.setdefault("members", []).append(uid_int)
                        entries.append(make_diary_entry(qname, qdata.get("info", ""), qdata.get("xp")))
                        assigned.append((qname, qdata.get("xp", "")))

            diaries[uid_str] = entries
            save_diaries(diaries)
            save_quests(quests)
        except Exception as e:
            print(f"[onboard] Auto-quest chyba: {e}")

        # ── Pošli uvítání do hub kanálu destinace ─────────────────────────
        hub_channel_id = DEST_HUB_CHANNEL_IDS.get(self.dest_key, 0)
        if hub_channel_id:
            hub_channel = interaction.guild.get_channel(hub_channel_id)
            if hub_channel:
                try:
                    dest        = DESTINATIONS[self.dest_key]
                    city_name   = dest["name"]
                    preposition = "na" if self.dest_key == "draci_skala" else "v"

                    hub_embed = discord.Embed(
                        title=f"{dest['emoji']}  Vítej {preposition} {city_name}!",
                        description=(
                            f"{interaction.user.mention} právě vstoupil/a do příběhu.\n\n"
                            + DEST_HUB_WELCOME[self.dest_key]
                        ),
                        color=dest["color"],
                    )
                    if assigned:
                        quest_lines = [
                            f"📜 **{qname}**" + (f"  ✨ {qxp}" if qxp else "")
                            for qname, qxp in assigned
                        ]
                        hub_embed.add_field(
                            name="📋 Questy přidány do deníku",
                            value="\n".join(quest_lines),
                            inline=False,
                        )
                    hub_embed.set_footer(text="⭐ Aurionis  ·  /diary show — zobraz svůj deník")
                    await hub_channel.send(embed=hub_embed)
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
            uid        = pkey(interaction.user.id)
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

        # Achievement se udělí úplně nakonec, až po uvítání v hubu i městském chatu.
        # Nový system: Achievement se jmenuje podle destinace, aby hráči věděli kam přišli.
        try:
            from src.core.dnd.achievements import grant_achievement, announce_achievement
            
            # Mapování destinací na achievement ID
            dest_achievements = {
                "lumenie":     "Lumenie: Nový příchod",
                "aquion":      "Aquion: Nový příchod",
                "draci_skala": "Dračí skála: Nový příchod",
            }
            
            achievement_id = dest_achievements.get(self.dest_key, "Vítej v Aurionisu")
            if grant_achievement(interaction.user.id, achievement_id):
                await announce_achievement(interaction.user, interaction.channel, achievement_id)
        except Exception as e:
            print(f"[onboard] Nepodařilo se udělit tutorial achievement: {e}")


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
                "Modré lampy osvětlují cestu, zatímco "
                "vzduch voní po svíčkách a starém kameni. "
                "V dálce se tyčí **katedrála světla**, její věž je majestátní. "
                "Po **mostě přes řeku Auriel** proudí davy "
                "obchodníků, poutníků i bojovníků s cechovní pečetí.\n\n"
                "*Tohle je místo, kde každý slavný dobrodruh napsal první řádek svého příběhu.*\n\n"
                "*A ty právě píšeš ten svůj.*"
            )
        elif self.dest_key == "aquion":
            street_desc = (
                "Světlo zmizí a pod nohama zaskřípe dřevo mola.\n\n"
                "V Aquionu je klid, ale když se zaposloucháš, "
                "slyšíš rušnou tržnici z dálky. "
                "Kanály se třpytí v odrazu světýlek, zatímco opodál "
                "se tyčí **klášter mágů vody**.\n\n"
                "*Říká se, že tady se dá koupit cokoliv. I pravda. I lež.*\n\n"
                "*Záleží jen na tom, co si dovolíš hledat a kolik máš zrovna zlaťáků.*"
            )
        elif self.dest_key == "draci_skala":
            street_desc = (
                "Světlo povolí a ostrý horský vzduch tě přivítá jako facka.\n\n"
                "Pořád se tady pracuje, kamenné ulice ještě nemají ani jména "
                "a prochází tu spousta ozbrojených jedinců. "
                "Vysoko nad hradbami lítá drak, střeží pevnost, zatímco "
                "dole roste město, které se teprve učí být městem.\n\n"
                "*Každý ví, kdo tu vládne.*\n\n"
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
                "Uděláš první krok.\n\n"
                "Příběh se začíná psát a tentokrát jsi v něm ty."
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
    """Statický embed v tutoriálovém kanálu — flow pokračuje jako ephemeral."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Spustit tutoriál", style=discord.ButtonStyle.success, emoji="✨", row=0, custom_id="onboard:start")
    async def start_tutorial(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="✨ Volání Hvězdy",
            description=(
                "*Ticho a prázdno.. jsi ve své mysli, nebo putuješ nekonečným vesmírem?*\n\n"
                "Přemítáš o tom, co je pro tebe realita, a pak tě oslepí jasné světlo.\n\n"
                "**'Zdravím tě, Vyvolený...'**"
            ),
            color=0xFFD700,
        )
        embed.set_image(url=URL_PLAKAT_HVEZDA)
        await interaction.response.send_message(embed=embed, view=TutorialPartOneView(), ephemeral=True)

    @discord.ui.button(label="Už mám postavu", style=discord.ButtonStyle.secondary, emoji="📜", row=0, custom_id="onboard:has_char")
    async def has_character(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📜  Existující postava",
            description=(
                "Pokud přicházíš z jiného projektu Aurionis a máš hotovou postavu, "
                "napiš administrátorovi — ten ti postavu přesune.\n\n"
                "*Tutorial pro tebe není potřeba.*"
            ),
            color=0x95a5a6,
        )
        embed.set_footer(text="⭐ Aurionis  ·  Kontaktuj administrátora.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class Onboarding(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup-tutorial", description="Spusť úvodní tutorial Aurionisu")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_tutorial(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="✨  Vítej v Aurionisu",
            description=(
                "***Svět se mění. Mocní se pohybují ve stínech.\n"
                "Turnaj Hvězdy byl vyhlášen — a jeho vítěz si může přát cokoliv.***\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Stojíš na prahu příběhu, který je jen tvůj.\n"
                "Každé rozhodnutí zanechá stopu. Každá volba má cenu.\n\n"
                "**Jsi připraven/a vstoupit?**\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "-# ⏱️ Délka tutoriálu: přibližně 15 minut\n"
                "-# 📜 Pokud máš postavu z jiného Aurionis projektu, klikni na **Už mám postavu**"
            ),
            color=0xFFD700,
        )
        embed.set_image(url=URL_PLAKAT_HVEZDA)
        embed.set_footer(text="⭐ Aurionis  ·  Act II  ·  Tvůj příběh začíná zde.")

        await interaction.response.send_message("✅ Brána do Actu II byla vztyčena.", ephemeral=True)

        tutorial_channel = interaction.guild.get_channel(TUTORIAL_CHANNEL_ID)
        if tutorial_channel is None:
            tutorial_channel = await interaction.guild.fetch_channel(TUTORIAL_CHANNEL_ID)

        # Pokud existuje stará zpráva, edituj ji — jinak pošli novou
        msg_id = None
        try:
            stored = load_json(TUTORIAL_MSG_FILE, default={})
            msg_id = stored.get("message_id")
        except Exception:
            pass

        if msg_id:
            try:
                old_msg = await tutorial_channel.fetch_message(msg_id)
                await old_msg.edit(embed=embed, view=TutorialWarningView())
                return
            except Exception:
                pass

        new_msg = await tutorial_channel.send(embed=embed, view=TutorialWarningView())
        try:
            save_json(TUTORIAL_MSG_FILE, {"message_id": new_msg.id})
        except Exception:
            pass

    @app_commands.command(name="admin-class-give", description="[ADMIN] Přidělí hráči startovní vybavení třídy")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(class_="Vyber třídu/loadout", player="Cíl hráče (prázdno = ty)")
    async def admin_class_give(
        self,
        interaction: discord.Interaction,
        class_: str,
        player: discord.User = None,
    ):
        await self.admin_loadout_give(interaction, loadout=class_, player=player)

    @app_commands.command(name="admin-loadout-give", description="[ADMIN] Přidělí hráči startovní vybavení třídy")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(loadout="Vybrat třídu/loadout", player="Cíl hráče (prázdno = ty)")
    async def admin_loadout_give(
        self,
        interaction: discord.Interaction,
        loadout: str,
        player: discord.User = None,
    ):
        """Přidělí hráči startovní vybavení vybrané třídy."""
        target_user = player or interaction.user
        
        if loadout not in LOADOUTS:
            await interaction.response.send_message(
                f"❌ Neznámý loadout: `{loadout}`\n"
                f"Dostupné: {', '.join(LOADOUTS.keys())}",
                ephemeral=True,
            )
            return
        
        try:
            loadout_data = LOADOUTS[loadout]
            profiles = load_json(DATA_FILE, default={})
            ensure_active(target_user.id)
            profile = profiles.setdefault(pkey(target_user.id), {"rank": "F3"})
            
            for item_id in loadout_data.get("items", []):
                add_registered_item_to_profile(profile, item_id, qty=1)
            
            save_json(DATA_FILE, profiles)
            
            embed = discord.Embed(
                title="✅  Loadout přidělen",
                description=(
                    f"**{target_user.mention}** ({loadout}) nyní má:\n\n"
                    + "\n".join(f"• {item_id}" for item_id in loadout_data.get("items", []))
                ),
                color=0x27ae60,
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            embed = discord.Embed(
                title="❌  Chyba",
                description=f"```\n{str(e)}\n```",
                color=0xe74c3c,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Onboarding(bot))