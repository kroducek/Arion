import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import os
import json
import functools
import logging
from src.logic.stats import init_stats, STAT_LABELS

logger = logging.getLogger("onboard")

_ONBOARD_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IMAGES_DIR = os.path.join(_ONBOARD_ROOT, "src", "assets", "onboard")

# Jednorázová diagnostika při startu — co je reálně nasazené
try:
    if os.path.isdir(IMAGES_DIR):
        logger.info("[onboard] IMAGES_DIR=%s OBSAH=%s", IMAGES_DIR, sorted(os.listdir(IMAGES_DIR)))
    else:
        _p = os.path.dirname(IMAGES_DIR)
        logger.warning("[onboard] IMAGES_DIR NEEXISTUJE: %s | %s obsahuje: %s",
                       IMAGES_DIR, _p, sorted(os.listdir(_p)) if os.path.isdir(_p) else "(neexistuje)")
except Exception:
    logger.exception("[onboard] diag obrázků")

_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")

def _resolve_image(fname):
    """Najde reálný soubor podle jména bez ohledu na velikost písmen a příponu
    (např. 'main_aurionis.png' najde i 'main_aurionis.PNG' nebo 'arion_guild.jpg').
    Vrací (cesta, attachment_jméno) nebo (None, None)."""
    if not fname:
        return None, None
    stem = os.path.splitext(fname)[0].lower()
    try:
        for real in os.listdir(IMAGES_DIR):
            rstem, rext = os.path.splitext(real)
            if rstem.lower() == stem and rext.lower() in _IMG_EXTS:
                return os.path.join(IMAGES_DIR, real), f"{stem}{rext.lower()}"
    except FileNotFoundError:
        pass
    return None, None

def _img(fname):
    """discord.File z src/assets/onboard (nebo None, když soubor chybí)."""
    path, att = _resolve_image(fname)
    if path is None:
        logger.warning("[onboard] chybí obrázek: %s (hledáno v %s)", fname, IMAGES_DIR)
        return None
    return discord.File(path, filename=att)

def _attach(embed, fname):
    """Nastaví obrázek embedu z lokálního souboru a vrátí discord.File (nebo None)."""
    path, att = _resolve_image(fname)
    if path is None:
        logger.warning("[onboard] chybí obrázek: %s", fname)
        return None
    embed.set_image(url=f"attachment://{att}")
    return discord.File(path, filename=att)
from src.utils.json_utils import load_json, save_json
from src.database.characters import pkey, ensure_active

# ── Konfigurace ───────────────────────────────────────────────────────────────

ROLE_DOBRODRUH_F3_ID = 1476056192643104768
from src.utils.paths import PROFILES as DATA_FILE, ECONOMY as ECONOMY_FILE, TUTORIAL_MSG as TUTORIAL_MSG_FILE, ITEMS
from src.logic.economy import get_balance, set_balance, COIN_SILVER

TUTORIAL_CHANNEL_ID = 1476045697496252607
COIN                 = "<:goldcoin:1490171741237018795>"

# Obrázky
URL_PLAKAT_HVEZDA = "main_aurionis.png"
URL_RECAP_ALICE = "recap_alice.png"
URL_RECAP_VLADCE = "recap_gabriel.png"
URL_RECAP_REINHARD = "recap_reinhard.png"
URL_ARION_ENCOUNTER = "arion_guild.png"
URL_TUTORIAL_END = "tutorial_end.png"

# ── Destinace ─────────────────────────────────────────────────────────────────

DESTINATIONS = {
    "lumenie": {
        "emoji": "🏰",
        "name":  "Lumenie",
        "desc":  "Město začátků. Každý slavný dobrodruh napsal první řádek svého příběhu zrovna tady. Dominuje mu **katedrála světla** a kamenný most přes řeku **Auriel**, symbol naděje a řádu. Domov nejvyššího paladina **Reinharda** a jeho bratrstva paladinů a rytířů. Lumenie nyní prochází krizí.",
        "color": 0x3498db,
        "image": "lumenie.png",
    },
    "aquion": {
        "emoji": "🌊",
        "name":  "Aquion",
        "desc":  "Největší obchodní město Aurionisu, postavené na síti kanálů a plovoucích plošin. Říká se, že tady se dá koupit cokoliv: pravda i lež. Klášter mágů vody střeží rovnováhu sil a prakticky řídí celou ekonomickou situaci Kalexie.",
        "color": 0x1abc9c,
        "image": "aquion.png",
    },
    "draci_skala": {
        "emoji": "🏔️",
        "name":  "Dračí skála",
        "desc":  "Mladé město vytesané do útesů vyhaslé sopky, kde vládne **Alice Aurelion** — samozvaná královna s darem dračí řeči. Její draci krouží nad hradbami a každý nový příchozí si musí vybrat: věrně sloužit, nebo odejít. Alice nebyla viděna na veřejnosti od chvíle, kdy se ukázala v Aquionu.",
        "color": 0xe74c3c,
        "image": "draci_skala.png",
    },
}

# ── Loadouty (tutorial) ────────────────────────────────────────────────────────

LOADOUTS = {
    "crossbow": {
        "emoji": "🎯",
        "name": "Kuše",
        "desc": "Střelec s kuší",
        "items": [("mala_kuse", 1), ("obycejna_sipka", 10), ("stredni_lektvar_zivota", 1), ("brasna", 1)],
        "perk": "aim",
    },
    "daggers": {
        "emoji": "🔪",
        "name": "Dýky",
        "desc": "Hbitý zabiják s dýkami a uměním plížení",
        "items": [("nuz", 1), ("mala_dyka", 1), ("brasna", 1), ("stredni_lektvar_zivota", 1)],
        "perk": "stealth_1",
    },
    "one_handed": {
        "emoji": "🗡️",
        "name": "Meč",
        "desc": "Klasický bojovník s jednoruční zbraní",
        "items": [("stary_mec", 1), ("brasna", 1), ("stredni_lektvar_zivota", 1)],
        "perk": "light_weapons",
    },
    "wand": {
        "emoji": "🪄",
        "name": "Magická hůlka",
        "desc": "Čaroděj ovládající runovou magii hůlkou",
        "items": [("zakladni_hulka", 1), ("brasna", 1), ("stredni_lektvar_many", 1)],
        "perk": "rune_basics_1",
    },
    "scrolls": {
        "emoji": "📜",
        "name": "Magické svitky",
        "desc": "Sesilatel kouzel ze svitků",
        "items": [("svitek_ohnivy_sip", 2), ("svitek_ledovy_blok", 2), ("svitek_slabeho_uzdraveni", 2), ("svitek_jedovy_osten", 2), ("brasna", 1), ("stredni_lektvar_many", 1)],
        "perk": "rune_basics_1",
    },
    "two_handed": {
        "emoji": "⚔️",
        "name": "Obouruční meč",
        "desc": "Silný bojovník s obouruční zbraní",
        "items": [("stary_obourucni_mec", 1), ("brasna", 1), ("stredni_lektvar_zivota", 1)],
        "perk": "heavy_weapons",
    },
    "bow": {
        "emoji": "🏹",
        "name": "Luk",
        "desc": "Lukostřelec s lukem a šípy",
        "items": [("maly_luk", 1), ("obycejny_sip", 10), ("brasna", 1), ("stredni_lektvar_zivota", 1)],
        "perk": "aim",
    },
}


def _loadout_items_db() -> dict:
    try:
        return load_json(ITEMS, default={})
    except Exception:
        return {}


def _perk_name(perk_id: str) -> str:
    try:
        from src.core.dnd.perks import load_perks
        return load_perks().get(perk_id, {}).get("name", perk_id)
    except Exception:
        return perk_id


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
URL_PLAKAT_ACT2 = "plakat_hao.png"

URL_PLAKAT_ALICE = "plakat_vladce_stinu.png"
URL_PLAKAT_AURELION = "plakat_posledni_aurelion.png"
ARION_COLOR = 0xb87333  # bronz — Arionina barva


def _arion_reply_embed(text: str, title: str = "🐱  Arion") -> discord.Embed:
    """Jednotný vzhled Arioniny repliky v dialogu."""
    e = discord.Embed(title=title, description=text, color=ARION_COLOR)
    e.set_footer(text="⭐ Aurionis")
    return e


class TutorialView(discord.ui.View):
    """Základ tutoriálových views — ošetří timeout i chyby, ať hráč neuvízne."""
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        self.message = interaction.message
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        msg = getattr(self, "message", None)
        if msg is not None:
            try:
                await msg.edit(content="⏳ *Vypršel čas nečinnosti — spusť tutorial znovu.*", view=self)
            except Exception:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        logger.exception("[onboard] chyba ve view (%s): %s", type(item).__name__, error)
        text = "⚠️ Něco se pokazilo. Zkus to prosím znovu — nebo spusť tutorial znovu."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except Exception:
            pass


class StoryBeatView(TutorialView):
    """Vizuální beat (obrázek/text) + jediné tlačítko → on_continue(interaction)."""
    def __init__(self, on_continue, *, label="Pokračovat", emoji="▶️"):
        super().__init__(timeout=1800)
        self._on_continue = on_continue
        self.go.label = label
        self.go.emoji = emoji

    @discord.ui.button(label="Pokračovat", style=discord.ButtonStyle.primary, emoji="▶️")
    async def go(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._on_continue(interaction)


class DialogChoiceView(TutorialView):
    """
    Dialog s volbami. choices = [(label, Arionova_odpověď)].
    Po kliknutí ukáže Arionovu reakci na danou volbu + view z next_view_factory().
    Volby konvergují do stejného pokračování (žádné větvení stavu).
    """
    def __init__(self, choices, next_view_factory, *, reply_title="🐱  Arion"):
        super().__init__(timeout=1800)
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


class TutorialPartOneView(TutorialView):
    def __init__(self):
        super().__init__(timeout=1800)

    @discord.ui.button(label="Naslouchat hlasu", style=discord.ButtonStyle.primary, emoji="✨")
    async def listen(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ochrana — hráč s dokončeným profilem nemůže spustit tutorial znovu
        uid = pkey(interaction.user.id)
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get(uid, {}).get("loadout_selected"):
                    return await interaction.response.send_message(
                        "Už jsi tutorial dokončil/a! "
                        "Pokud potřebuješ pomoc, napiš DM",
                        ephemeral=True,
                    )
            except Exception:
                logger.exception('[onboard] potlačená chyba')

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

class ActSelectionView(TutorialView):
    def __init__(self):
        super().__init__(timeout=1800)

    @discord.ui.button(label="Já už příběh znám", style=discord.ButtonStyle.success, emoji="⏩")
    async def old_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _show_destination_choice(interaction)

    @discord.ui.button(label="Chci recap Actu I.", style=discord.ButtonStyle.secondary, emoji="📖")
    async def new_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RecapView(page=1)
        embed = view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view, attachments=[view._pending_file] if view._pending_file else [])


# ══════════════════════════════════════════════════════════════════════════════
# KROK 3 — Rekapitulace (volitelné)
# ══════════════════════════════════════════════════════════════════════════════

class RecapView(TutorialView):
    def __init__(self, page=1):
        super().__init__(timeout=1800)
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
        self._pending_file = _attach(embed, imgs[self.page])
        return embed

    @discord.ui.button(label="Zpět", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self, attachments=[self._pending_file] if self._pending_file else [])

    @discord.ui.button(label="Dále", style=discord.ButtonStyle.secondary, emoji="➡️")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self, attachments=[self._pending_file] if self._pending_file else [])

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


class DestinationView(TutorialView):
    def __init__(self):
        super().__init__(timeout=1800)

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
    _f = _attach(embed, URL_PLAKAT_ACT2)
    await interaction.response.edit_message(
        embed=embed,
        view=StoryBeatView(functools.partial(_show_first_contact, dest_key=dest_key)),
        attachments=[_f] if _f else [],
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


class EncounterView(TutorialView):
    def __init__(self, dest_key: str, arion_roll: int):
        super().__init__(timeout=1800)
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

class ArionIntroView(TutorialView):
    def __init__(self, dest_key: str, dodged: bool = True):
        super().__init__(timeout=1800)
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


class GuildEntranceView(TutorialView):
    def __init__(self, dest_key: str):
        super().__init__(timeout=1800)
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
            logger.exception('[onboard] potlačená chyba')

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

class ArionLeapView(TutorialView):
    def __init__(self, dest_key: str, char_name: str):
        super().__init__(timeout=1800)
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

class ArionMemoryView(TutorialView):
    def __init__(self, dest_key: str):
        super().__init__(timeout=1800)
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


class ArionHmView(TutorialView):
    def __init__(self, dest_key: str):
        super().__init__(timeout=1800)
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
    """Beat: plakát Vládce stínů → vstup do cechu."""
    embed = discord.Embed(title="Vládce stínů", color=0x1a1a2e)
    _f = _attach(embed, URL_PLAKAT_ALICE)
    await interaction.response.edit_message(
        embed=embed,
        view=EnterGuildInsideView(dest_key=dest_key),
        attachments=[_f] if _f else [],
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
    _f = _attach(embed, URL_ARION_ENCOUNTER)
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
        attachments=[_f] if _f else [],
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
    labels     = STAT_LABELS
    base_stats = {s: 0 for s in labels}
    init_stats(interaction.user.id, base_stats=base_stats, ap=3, sp=3)
    await interaction.response.edit_message(
        embed=embed,
        view=TutorialSPView(
            dest_key=dest_key,
            portrait_url=None,
            sp_remaining=3,
            stats={s: 0 for s in labels},
        ),
    )


class EnterGuildInsideView(TutorialView):
    def __init__(self, dest_key: str):
        super().__init__(timeout=1800)
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
# KROK 8c — Motivace (View + Modal)
# ══════════════════════════════════════════════════════════════════════════════

class MotivationView(TutorialView):
    def __init__(self, dest_key: str, stats: dict | None = None, portrait_url: str | None = None):
        super().__init__(timeout=1800)
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
# KROK 8a — Rozdělení atributů (AP)
# ══════════════════════════════════════════════════════════════════════════════

STAT_FULL_NAMES = {
    "STR": "Síla",
    "DEX": "Obratnost",
    "INS": "Instinkty",
    "INT": "Inteligence",
    "CHA": "Charisma",
    "WIS": "Moudrost",
}

class TutorialSPView(TutorialView):
    """Hráč rozděluje 3 AP přímo v tutorialu — každý klik = 1 AP do atributu."""

    def __init__(
        self,
        dest_key: str,
        stats: dict | None,
        portrait_url: str | None,
        sp_remaining: int,
    ):
        super().__init__(timeout=1800)
        self.dest_key     = dest_key
        self.stats        = stats or {}
        self.portrait_url = portrait_url
        self.sp_remaining = sp_remaining
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        labels = STAT_LABELS
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
                f"**{s}** {self.stats.get(s, 0)}" for s in STAT_LABELS
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
        labels = STAT_LABELS
        from src.logic.stats import init_stats
        init_stats(interaction.user.id, base_stats={s: 0 for s in labels}, ap=3, sp=3)
        self.stats = {s: 0 for s in labels}
        self.sp_remaining = 3
        self._build_buttons()

        embed = discord.Embed(
            title="🎯  Attribute Pointy",
            description=(
                "AP resetovány. Rozhodni znovu.\n\n"
                "*Zbývá: **3 AP***"
            ),
            color=0x9b59b6,
        )
        embed.set_footer(text="⭐ Aurionis  ·  3 AP zbývá")
        await interaction.response.edit_message(embed=embed, view=self)

    async def _done_callback(self, interaction: discord.Interaction):
        labels      = STAT_LABELS
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

class PortraitView(TutorialView):
    def __init__(self, dest_key: str, stats: dict | None = None):
        super().__init__(timeout=1800)
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
# KROK 8c — Motivace (prompt)
# ══════════════════════════════════════════════════════════════════════════════

async def _show_motivation_prompt(
    interaction: discord.Interaction,
    dest_key: str,
    portrait_url: str | None,
    stats: dict | None,
):
    if portrait_url:
        reakce = (
            "Arion vezme tvůj portrét a chvíli ho soustředěně zkoumá. "
            "Pak spokojeně přikývne sama pro sebe.\n\n"
            "*'Moc hezké...'*\n\n"
            "Otočí průkaz dobrodruha k tobě\n\n"
            "Všechna pole jsou vyplněna... jméno, sken i tvůj portrét. "
            "Zbývá jen jedno prázdné místo ve spodní části\n\n"
        )
    else:
        reakce = (
            "Arion mávne tlapkou, že to nevadí\n\n"
            "*'Jak chceš — tak třeba příště.'*\n\n"
            "Otočí průkaz dobrodruha k tobě\n\n"
            "Hlavní pole jsou vyplněna... jméno i sken. Portrét sis nechal/a prázdný. "
            "Zbývá ještě jedno místo ve spodní části\n\n"
        )
    embed = discord.Embed(
        title="📜",
        description=(
            reakce +
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
# KROK 8d — Průkaz dobrodruha
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
            logger.exception('[onboard] potlačená chyba')

    embed = discord.Embed(
        title="📜  Průkaz dobrodruha",
        description=(
            "Arion sáhne pod pult a vytáhne starý kožený váček s cechovní pečetí\n\n"
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

class StatsDialogView(TutorialView):
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=1800)
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

class GoldView(TutorialView):
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=1800)
        self.dest_key     = dest_key
        self.portrait_url = portrait_url

    @discord.ui.button(label="Převzít zlaté", style=discord.ButtonStyle.success, emoji="🪙")
    async def receive_gold(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ochrana před double-klikem — deaktivuj tlačítko okamžitě
        button.disabled = True
        await interaction.response.defer()

        uid = pkey(interaction.user.id)
        profile = load_json(DATA_FILE, default={})
        if not profile.get(uid, {}).get("gold_received"):
            add_gold(interaction.user.id, 100)
            set_balance(interaction.user.id, get_balance(interaction.user.id, "silver") + 100, "silver")
            update_profile(interaction.user.id, gold_received=True)

        dest = DESTINATIONS[self.dest_key]
        embed = discord.Embed(
            title="🪙  Měšec se zlatými",
            description=(
                "Zlaté uvnitř cinkají velmi přesvědčivě\n\n"
                f"**+100** {COIN}  \u00b7  **+100** {COIN_SILVER} připsáno na tvé konto\n\n"
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

class LoadoutSelectView(TutorialView):
    """Hráč si vybere loadout (vybavení + prvotní perk)."""
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=1800)
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
            await _show_loadout_confirm(
                interaction,
                dest_key=self.dest_key,
                portrait_url=self.portrait_url,
                loadout_id=loadout_id,
            )
        return callback


async def _show_loadout_confirm(interaction, dest_key, portrait_url, loadout_id):
    """Ukáže tabulku vybavení + perku a tlačítka Potvrdit / Vybrat znovu."""
    loadout = LOADOUTS.get(loadout_id)
    if not loadout:
        await interaction.response.defer()
        return
    items_db = _loadout_items_db()
    radky = []
    for item_id, qty in loadout.get("items", []):
        nazev = items_db.get(item_id, {}).get("name", item_id)
        radky.append(f"• {nazev}" + (f"  **×{qty}**" if qty > 1 else ""))
    embed = discord.Embed(
        title=f"{loadout['emoji']}  {loadout['name']}",
        description=(
            f"*{loadout['desc']}*\n\n"
            "**Dostaneš toto vybavení:**\n" + "\n".join(radky) +
            f"\n\n**Prvotní perk:** `{_perk_name(loadout['perk'])}`\n\n"
            "Pokud souhlasíš, potvrď. Jinak se vrať a vyber jiné."
        ),
        color=0xFFD700,
    )
    if portrait_url:
        embed.set_thumbnail(url=portrait_url)
    embed.set_footer(text="⭐ Aurionis  ·  Potvrď své vybavení.")
    await interaction.response.edit_message(
        embed=embed,
        view=LoadoutConfirmView(dest_key, portrait_url, loadout_id),
    )


class LoadoutConfirmView(TutorialView):
    """Potvrzení loadoutu před výběrem perků."""
    def __init__(self, dest_key, portrait_url, loadout_id):
        super().__init__(timeout=1800)
        self.dest_key = dest_key
        self.portrait_url = portrait_url
        self.loadout_id = loadout_id

    @discord.ui.button(label="Potvrdit", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _show_perk_selection(
            interaction,
            dest_key=self.dest_key,
            portrait_url=self.portrait_url,
            loadout_id=self.loadout_id,
        )

    @discord.ui.button(label="Vybrat znovu", style=discord.ButtonStyle.secondary, emoji="↩️")
    async def reselect(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🎒  Výběr vybavení",
            description="*Vyber si startovní vybavení a prvotní perk.*",
            color=0xFFD700,
        )
        if self.portrait_url:
            embed.set_thumbnail(url=self.portrait_url)
        embed.set_footer(text="⭐ Aurionis  ·  Vyber si vybavení.")
        await interaction.response.edit_message(
            embed=embed,
            view=LoadoutSelectView(dest_key=self.dest_key, portrait_url=self.portrait_url),
        )


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
            f"Dostaneš prvotní perk: **{_perk_name(loadout['perk'])}** a startovní položky.\n\n"
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


class PerkSelectionView(TutorialView):
    """Hráč si vybere 4 perky."""
    def __init__(self, dest_key: str, portrait_url: str | None, loadout_id: str,
                 selected_perks: list[str], max_perks: int):
        super().__init__(timeout=1800)
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
            logger.exception(f"[onboard] Chyba při načtení perků: {e}")
            perks = {}

        perk_list = []
        blocked = set(self.selected_perks)
        loadout = LOADOUTS.get(self.loadout_id, {})
        if loadout.get("perk"):
            blocked.add(loadout["perk"])

        for perk_id, perk in perks.items():
            if perk_id in blocked:
                continue
            # Startovní pool = jen ZÁKLADNÍ dovednosti (smlouvání, plížení, vaření…).
            # Magie ani výzbrojové skilly sem nepatří — ty si hráč bere přes loadout.
            if perk.get("group") != "Základní":
                continue
            is_tier_one = perk_id.endswith("_1") or perk_id == "magicke_citeni"
            if is_tier_one:
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
    _f = _attach(embed, URL_PLAKAT_AURELION)
    embed.set_footer(text="⭐ Aurionis  ·  Podívej se na nástěnku.")
    await interaction.response.edit_message(
        embed=embed,
        view=StoryBeatView(
            functools.partial(_show_ready, dest_key=dest_key, portrait_url=portrait_url)
        ),
        attachments=[_f] if _f else [],
    )


async def _show_ready(interaction, dest_key, portrait_url):
    """Beat: 'Připraven/a!' tipy → nástěnka."""
    embed = discord.Embed(
        title="✨  Připraven/a!",
        description=(
            "Vybral/a sis loadout a perky.\n\n"
            "Teď už je čas vstoupit do Aurionisu.\n\n"
            "-# Tip: /staty rozdělíš body, /equip nasadíš vybavení, "
            "/perks show perky, /stats statistiky a /profile vizitka!"
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

        # Anti double-grant: pokud už loadout přidělen, nedávej znovu
        if load_json(DATA_FILE, default={}).get(user_id, {}).get("loadout_selected"):
            await _show_arion_farewell(interaction, dest_key, portrait_url)
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
        for item_id, qty in loadout.get("items", []):
            add_registered_item_to_profile(profile, item_id, qty)
        save_json(DATA_FILE, profiles)

        # Zapiš do profilu, že je hotovo
        update_profile(interaction.user.id, loadout_selected=loadout_id, perks_selected=len(additional_perks))

    except Exception as e:
        logger.exception(f"[onboard] Chyba při finalizaci tutoriálu: {e}")

    # Rozloučení s Arion → plakát Poslední Aurelion → nástěnka
    await _show_arion_farewell(interaction, dest_key, portrait_url)


# ══════════════════════════════════════════════════════════════════════════════
# KROK 10 — Nástěnka, vize, charisma hod
# ══════════════════════════════════════════════════════════════════════════════

class BulletinBoardView(TutorialView):
    """Hráč si všimne nástěnky a turnajového seznamu."""
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=1800)
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


class VisionView(TutorialView):
    """Hráč se zamotá — krátká vize. Může se pokusit si vzpomenout přes /check."""
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=1800)
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


class MemoryCheckView(TutorialView):
    """/check — hráč hází vlastní roll, Arion sleduje WIS/INT/INS."""
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=1800)
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
            view=_GuildHubEntryView(
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
            logger.exception(f"[onboard] Nepodařilo se zapsat vzpomínku: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# KROK 10b — Síň cechu: NPC hub (promluv si s lidmi, nebo odejdi)
# ══════════════════════════════════════════════════════════════════════════════

# Registr NPC v síni — přidat dalšího = přidat položku + handler do _NPC_HANDLERS
GUILD_NPCS = [
    {"id": "runar",     "label": "Promluvit s runovým mágem", "emoji": "🔮"},
    {"id": "trpaslici", "label": "Přisednout k trpaslíkům",    "emoji": "🍺"},
    {"id": "rohac",     "label": "Přisednout k muži s rohy",   "emoji": "😈"},
]


async def _show_guild_hub(interaction: discord.Interaction, dest_key: str, portrait_url: str | None = None):
    """Rozcestník v síni cechu — NPC tlačítka + odchod."""
    embed = discord.Embed(
        title="🏛️  Síň cechu",
        description=(
            "Vzpamatuješ se. Jsi pořád v síni cechu — *nikdo si ničeho nevšiml.*\n\n"
            "Kolem postává pár dobrodruhů. Někteří si tě měří pohledem, jiní se baví mezi sebou. "
            "Než vyrazíš do světa, můžeš si s někým promluvit.\n\n"
            "*Nebo prostě odejdi.*"
        ),
        color=0x8e44ad,
    )
    if portrait_url:
        embed.set_thumbnail(url=portrait_url)
    embed.set_footer(text="⭐ Aurionis  ·  Promluv si, nebo odejdi.")
    await interaction.response.edit_message(
        embed=embed,
        view=GuildHubView(dest_key, portrait_url),
        attachments=[],
    )


class _GuildNPCButton(discord.ui.Button):
    def __init__(self, npc: dict, dest_key: str, portrait_url: str | None):
        super().__init__(label=npc["label"], style=discord.ButtonStyle.secondary,
                         emoji=npc.get("emoji"), row=0)
        self.npc = npc
        self.dest_key = dest_key
        self.portrait_url = portrait_url

    async def callback(self, interaction: discord.Interaction):
        handler = _NPC_HANDLERS.get(self.npc["id"])
        if handler is None:
            await interaction.response.defer()
            return
        await handler(interaction, self.dest_key, self.portrait_url)


class GuildHubView(TutorialView):
    """Hub v síni cechu — dynamická NPC tlačítka + odchod."""
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=1800)
        self.dest_key = dest_key
        self.portrait_url = portrait_url
        for npc in GUILD_NPCS:
            self.add_item(_GuildNPCButton(npc, dest_key, portrait_url))

    @discord.ui.button(label="Odejít z cechu", style=discord.ButtonStyle.primary, emoji="🚪", row=1)
    async def leave_hub(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🚪  ..",
            description="Naposledy se rozhlédneš po síni a vykročíš ke dveřím.",
            color=0x2c3e50,
        )
        if self.portrait_url:
            embed.set_thumbnail(url=self.portrait_url)
        embed.set_footer(text="⭐ Aurionis")
        await interaction.response.edit_message(
            embed=embed,
            view=FinalEnterView(dest_key=self.dest_key, portrait_url=self.portrait_url),
            attachments=[],
        )


class _GuildHubEntryView(TutorialView):
    """Přechod z vize zpět do reality → síň cechu (hub)."""
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=1800)
        self.dest_key = dest_key
        self.portrait_url = portrait_url

    @discord.ui.button(label="Vzpamatovat se", style=discord.ButtonStyle.secondary, emoji="👁️")
    async def snap_back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _show_guild_hub(interaction, self.dest_key, self.portrait_url)


class _BackToHubView(TutorialView):
    """Návrat do síně cechu po rozhovoru s NPC."""
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=1800)
        self.dest_key = dest_key
        self.portrait_url = portrait_url

    @discord.ui.button(label="Zpět do síně", style=discord.ButtonStyle.primary, emoji="↩️")
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _show_guild_hub(interaction, self.dest_key, self.portrait_url)


# ── NPC: Runový mág ───────────────────────────────────────────────────────────
async def _show_npc_runar(interaction: discord.Interaction, dest_key: str, portrait_url: str | None = None):
    if _npc_first_visit(interaction.user.id, "runar"):
        desc = (
            "*Podsaditý muž v bohatě zdobeném rouchu se opírá o sloup. "
            "V dlani mu líně víří chuchvalec fialové runové energie. "
            "Když si tě všimne, zazubí se od ucha k uchu.*\n\n"
            "**„Hej ty! Co koukáš jak péro z ptáka…“**\n\n"
            "**„Vypadáš zmateně. Ty vůbec nevypadáš jako někdo, kdo ví, jak funguje magie… "
            "Já jo. Hehe.“**\n\n"
            "**„Ale neboj, já nejsem žádnej chamtivec… Chceš to slyšet?“**"
        )
    else:
        desc = (
            "*Mág tě zmerčí a protáhne obličej.*\n\n"
            "**„Á, ty zvědavče. Zase runy? No dobrá — ptej se…“**"
        )
    embed = discord.Embed(title="🔮  Runový mág", description=desc, color=0x8e44ad)
    _f = _attach(embed, "npc_runar.png")
    embed.set_footer(text="⭐ Aurionis  ·  Co uděláš?")
    await interaction.response.edit_message(
        embed=embed,
        view=NpcRunarView(dest_key, portrait_url),
        attachments=[_f] if _f else [],
    )


class NpcRunarView(TutorialView):
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=1800)
        self.dest_key = dest_key
        self.portrait_url = portrait_url

    @discord.ui.button(label="Chci to slyšet", style=discord.ButtonStyle.success, emoji="👂")
    async def listen(self, interaction: discord.Interaction, button: discord.ui.Button):
        view  = RunarMonologueView(self.dest_key, self.portrait_url, page=0)
        embed = view._embed()
        _f    = _attach(embed, "npc_runar.png")
        await interaction.response.edit_message(
            embed=embed, view=view, attachments=[_f] if _f else [])

    @discord.ui.button(label="Ignorovat", style=discord.ButtonStyle.secondary, emoji="🙄")
    async def ignore(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🔮  Runový mág",
            description="**„Ok.“**\n\n*Pokrčí rameny a znovu se opře o sloup.*",
            color=0x8e44ad,
        )
        await interaction.response.edit_message(
            embed=embed, view=_BackToHubView(self.dest_key, self.portrait_url), attachments=[])


# ── Runový mág: monolog o runách (stránkovaný, ukecanej) ──────────────────────
_RUNAR_MONO = [
    {"kind": "next", "text":
        "**„Jak používat magii je tvá otázka?“**\n\n"
        "„Na to mám jednoduchou odpověď…“\n\n"
        "**„Runy!“**"},
    {"kind": "interject", "opts": ["…runové kameny?", "(mlčet)"], "text":
        "„Runy jsou ve světě magie všude kolem nás…“\n\n"
        "„Svitek? Runy. Zbraně se speciálním efektem? Runy. To magické tetování, "
        "co dává nějakému šílenci nadlidské schopnosti? Runy.“\n\n"
        "„Šutry, co mají na sobě runy? Eh… co by to tak asi mohlo být…“"},
    {"kind": "next", "text":
        "*Než stačíš pořádně otevřít pusu, přeruší tě.*\n\n"
        "**„—Ano ano! Runové kameny!“**\n\n"
        "„Ehm ehm… Runy ovšem nemůže kdokoliv dát kamkoliv a pak to jakkoliv "
        "využívat. Mají svoje pravidla…“"},
    {"kind": "next", "text":
        "„Určité věci použití run na nich vyrytých nesnesou dobře. Například svitky — "
        "pokud je nedáš do grimoáru, většinou se ti po jednom použití rozpadnou v ruce.“\n\n"
        "„A když se runy vyryjí na člověka? Ty můžou způsobit až smrt — při větším "
        "množství, někdy i při malém…“"},
    {"kind": "next", "text":
        "„Proto runy nejčastěji používáme na hůlkách, speciálních kamenech a na "
        "ostatních věcech, co jejich sílu snesou.“"},
    {"kind": "interject", "opts": ["Takže když…", "(mlčet)"], "text":
        "„Taky bych mohl dodat, že runy rozdělujeme na **pasivní** a **aktivní**.“\n\n"
        "„Aktivní jsou většinou třeba kouzla v hůlkách — a většinou žerou manu. "
        "Pasivní bývají na zbroji — mečích, brnění, lukách…“\n\n"
        "„Toto ovšem není pravidlem…“"},
    {"kind": "end", "text":
        "*Nenechá tě dokončit.*\n\n"
        "**„—Pšt! Ještě jsem neskončil.“**\n\n"
        "„Runy jsou komplikovaná věc. Neměl by sis se žádnýma silnýma runama "
        "zahrávat, pokud nejsi pod dozorem experta…“"},
]


class RunarMonologueView(TutorialView):
    """Ukecanej monolog runového mága — stránkování + interjekce (přeruší tě)."""
    def __init__(self, dest_key: str, portrait_url: str | None = None, page: int = 0):
        super().__init__(timeout=1800)
        self.dest_key = dest_key
        self.portrait_url = portrait_url
        self.page = page
        self._build()

    def _build(self):
        self.clear_items()
        p = _RUNAR_MONO[self.page]
        if p["kind"] == "next":
            b = discord.ui.Button(label="Poslouchat dál", style=discord.ButtonStyle.secondary, emoji="➡️")
            b.callback = self._advance
            self.add_item(b)
        elif p["kind"] == "interject":
            for opt in p["opts"]:
                b = discord.ui.Button(label=opt, style=discord.ButtonStyle.secondary)
                b.callback = self._advance
                self.add_item(b)
        else:  # end
            b = discord.ui.Button(label="Zpět do síně", style=discord.ButtonStyle.success, emoji="✅")
            b.callback = self._end
            self.add_item(b)

    def _embed(self):
        return discord.Embed(title="🔮  Runový mág",
                             description=_RUNAR_MONO[self.page]["text"], color=0x8e44ad)

    async def _advance(self, interaction: discord.Interaction):
        self.page += 1
        self._build()
        embed = self._embed()
        _f = _attach(embed, "npc_runar.png")
        await interaction.response.edit_message(embed=embed, view=self, attachments=[_f] if _f else [])

    async def _end(self, interaction: discord.Interaction):
        await _show_guild_hub(interaction, self.dest_key, self.portrait_url)


# ── NPC: Trpaslíci z Kazad'horu (větvený dialog + CHA check o láhev) ───────────
def _npc_first_visit(user_id: int, npc_id: str) -> bool:
    """True při prvním rozhovoru s NPC (a poznamená si to). False = už s ním mluvil."""
    data = load_json(DATA_FILE, default={})
    prof = data.setdefault(pkey(user_id), {})
    seen = prof.setdefault("tutorial_npc_seen", [])
    if npc_id in seen:
        return False
    seen.append(npc_id)
    save_json(DATA_FILE, data)
    return True


class NodeDialogueView(TutorialView):
    """Sdílený základ uzlových NPC dialogů (větvení + speciální akce).
    Podtřída dodá: TITLE, COLOR, IMAGE, NODES a metody _kind_<x> / _target_<x>."""
    TITLE = ""
    COLOR = 0x000000
    IMAGE = None
    NODES: dict = {}

    def __init__(self, dest_key: str, portrait_url: str | None = None, node: str = "intro"):
        super().__init__(timeout=1800)
        self.dest_key = dest_key
        self.portrait_url = portrait_url
        self.node = node
        self._build()

    def _build(self):
        self.clear_items()
        n = self.NODES[self.node]
        kind = n.get("kind")
        if kind:
            b = discord.ui.Button(label=n.get("button", "Pokračovat"),
                                  style=n.get("button_style", discord.ButtonStyle.primary))
            b.callback = self._make_kind(kind)
            self.add_item(b)
            return
        for label, target in n["opts"]:
            b = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
            b.callback = self._make_nav(target)
            self.add_item(b)

    def _embed(self, text: str | None = None):
        return discord.Embed(
            title=self.TITLE,
            description=text if text is not None else self.NODES[self.node]["text"],
            color=self.COLOR,
        )

    async def _edit(self, interaction: discord.Interaction, text: str | None = None):
        embed = self._embed(text)
        _f = _attach(embed, self.IMAGE)
        await interaction.response.edit_message(embed=embed, view=self, attachments=[_f] if _f else [])

    async def _goto_node(self, interaction: discord.Interaction, node: str, text: str | None = None):
        self.node = node
        self._build()
        await self._edit(interaction, text)

    def _make_nav(self, target: str):
        async def cb(interaction: discord.Interaction):
            await self._goto(interaction, target)
        return cb

    def _make_kind(self, kind: str):
        async def cb(interaction: discord.Interaction):
            await getattr(self, f"_kind_{kind}")(interaction)
        return cb

    async def _goto(self, interaction: discord.Interaction, target: str):
        if target == "__hub__":
            await _show_guild_hub(interaction, self.dest_key, self.portrait_url)
            return
        handler = getattr(self, f"_target_{target}", None)
        if handler is not None:
            await handler(interaction)
            return
        await self._goto_node(interaction, target)


_DWARF_TITLE = "🍺  Trpaslíci z Kazad'horu"
_DWARF_NODES = {
    "intro": {
        "text": "*Podsaditá parta trpaslíků u stolu zvedne korbele. Ten největší — "
                "rusý plnovous, nos jak brambora — na tebe zamává.*\n\n"
                "„Helehme se! Ty seš tu novej, co? **Herdek fagot**, vypadáš jak "
                "čerstvě vytaženej z kejdy!“",
        "opts": [("Já jsem…", "borin"), ("…mlčet", "borin")],
    },
    "reintro": {
        "text": "„Á, zas ty! **Herdek fagot**, dáš si eště jednu?“",
        "opts": [("Jo s chutí", "drink1"), ("Nepiju", "nodrink"), ("…", "nodrink")],
    },
    "borin": {
        "text": "„Já jsem **Borin**, tamhle **Thrain**, **Gundrik** a nejmenší z nás – "
                "**Dwalin**. Banda jak z Kazad'horu, heh!“\n\n"
                "„Jsme dobrodruzi, zrovna jako ty, chlapče. A máme tu železný pravidlo: "
                "**prvně chlast, pak práce!** Tak co, dáš si štamprli, než ti kejdy zmrznou?“",
        "opts": [("Jo s chutí", "drink1"), ("Nepiju", "nodrink"), ("…", "nodrink")],
    },
    "drink1": {
        "text": "*Borin ti naleje štamprli staré trpasličí pálenky — tak silné, že by "
                "probudila i mrtvýho gryfa. Pořádně tě to prohnalo.*",
        "opts": [("To je síla!", "drink2"), ("…", "drink2")],
    },
    "drink2": {
        "text": "„Heh! To je kvalitní trpasličí pálenka od našich bratří z **Kazad'horu**. "
                "Ne žádnej patok, co tu ta kočka rozlejvá.“",
        "opts": [("Kazad'hor?", "lore"), ("…mlčet", "lore")],
    },
    "lore": {
        "text": "„Ejhle kejhák, ty jsi o Kazad'horu fakt neslyšel?! Největší trpasličí "
                "město široko daleko!“\n\n"
                "„Hluboko v dole stejnýho jména — tam, kde kámen zpívá a kov se rodí. "
                "Náš domov, naše pýcha… naše špajzka na pivo!“",
        "opts": [("Jak se dostanu do Kazad'horu?", "teleport")],
    },
    "teleport": {
        "text": "„Jo, tvoje největší šance je koupit si jeden z těch nablýskanejch "
                "**teleportačních svitků**. Lidi je prodávaj draze, ale funguje to. "
                "Teda… pokud máš trochu štěstí.“",
        "opts": [("🧪 „Ta pálenka byla dobrá…“", "cha")],
    },
    "cha": {
        "kind": "cha", "button": "🧪 Zkusit to  ·  1d20 + CHA",
        "text": "*Pálenka ti ještě hřeje v krku. Možná kdybys trpaslíky správně upoval, "
                "ukápla by ti láhev na cestu…*",
    },
    "nodrink": {
        "text": "*Trpaslíci se napijí bez tebe.*\n\n"
                "„No jak chceš, tvoje smůla. Ty toho moc nenamluvíš, co? **Herdek fagot**, "
                "takovej tichej typ…“",
        "opts": [("Rozhlédnout se", "minihub")],
    },
    "minihub": {
        "text": "„Tak co ještě potřebuješ, chlapče?“",
        "opts": [("Potřebuju lepší zbraň", "zbran"),
                 ("Potřebuju práci", "prace"),
                 ("Odejít od trpaslíků", "farewell")],
    },
    "zbran": {
        "text": "„Eh, slyšel jsem, že **lumenijskej kovář** prodává základní vybavení… "
                "Šunt to je, ale poslouží.“\n\n"
                "„Jestli chceš pořádný železo, zajdi za nějakým trpasličím kovářem! "
                "Ti vědí, jak ukovat čepel, co ti neupadne po prvním švihu.“",
        "opts": [("Zpět", "minihub")],
    },
    "prace": {
        "text": "„A nech mě hádat — jsi zelenáč, na kterýho nezbyl úkol na nástěnce.“\n\n"
                "„Zkus **strážnici**, prej tam platěj slušně. Nebo se poptej lidí po městě — "
                "někdo vždycky potřebuje pomocnou ruku… nebo meč.“",
        "opts": [("Zpět", "minihub")],
    },
    "farewell": {
        "text": "„Tak se měj, chlapče! A někdy se zastav — ať z tebe není takovej "
                "němej balvan.“",
        "opts": [("Zpět do síně", "__hub__")],
    },
}


class DwarfDialogueView(NodeDialogueView):
    """Trpaslíci — pití/nepití, lore, CHA check o láhev, mini-hub."""
    TITLE = _DWARF_TITLE
    COLOR = 0xb9770e
    IMAGE = "npc_trpaslici.png"
    NODES = _DWARF_NODES

    async def _kind_cha(self, interaction: discord.Interaction):
        uid  = pkey(interaction.user.id)
        data = load_json(DATA_FILE, default={})
        prof = data.setdefault(uid, {})
        cha  = prof.get("stats", {}).get("CHA", 0)
        die  = random.randint(1, 20)
        total = die + cha
        cap = f"-# 🧪 Charisma — 1d20 + CHA → **{die}** + {cha} = **{total}**"
        already = prof.get("dwarf_bottle", False)
        if total >= 11 and not already:
            add_registered_item_to_profile(prof, "trpaslici_palenka", 1)
            prof["dwarf_bottle"] = True
            save_json(DATA_FILE, data)
            text = (f"{cap}  ✔️\n\n**+1 Trpasličí pálenka**\n\n"
                    "„Tak si vezmi láhev — na nás, na přátelství! Ať ti to zahřeje kejdy, "
                    "až budeš bloudit po světě.“")
        elif total >= 11 and already:
            text = (f"{cap}  ✔️\n\n„Ale ale, jednu láhev už u tebe vidím! "
                    "Nebuď chamtivec, chlapče. Heh!“")
        else:
            text = (f"{cap}  ❌\n\n„Taky že je to kvalita! Ale láhev si nech zajít chuť — "
                    "ta je jen pro nás, heh.“")
        await self._goto_node(interaction, "minihub", text)


async def _show_npc_trpaslici(interaction: discord.Interaction, dest_key: str, portrait_url: str | None = None):
    node  = "intro" if _npc_first_visit(interaction.user.id, "trpaslici") else "reintro"
    view  = DwarfDialogueView(dest_key, portrait_url, node=node)
    embed = view._embed()
    _f    = _attach(embed, view.IMAGE)
    await interaction.response.edit_message(embed=embed, view=view, attachments=[_f] if _f else [])


# ── NPC: Muž s rohy (provokace → páka STR → odměna) ───────────────────────────
_HORNED_TITLE = "😈  Muž s rohy"
_HORNED_NODES = {
    "intro": {
        "text": "*U stolu sedí muž s démonními rohy, korbel v ruce. Když k němu "
                "přistoupíš, líně zvedne pohled.*\n\n**„Co chceš?“**",
        "opts": [("Jsem tu nový…", "r_new"), ("Čau.", "r_hi"), ("…mlčet.", "r_silent")],
    },
    "reintro": {
        "text": "*Sotva k němu zamíříš, protočí panenky.*\n\n„Zase ty? Co zas chceš.“",
        "opts": [("Jsi protivnej jak prdel.", "provoke"),
                 ("Nebudu tě rušit.", "__hub__"),
                 ("…mlčet.", "stare")],
    },
    "r_new":    {"text": "„To mě nezajímá. Odprejskni.“", "opts": [("(zůstat stát)", "escalate")]},
    "r_hi":     {"text": "„Tak vidíš, pozdravil jsi. Můžeš jít.“", "opts": [("(zůstat stát)", "escalate")]},
    "r_silent": {"text": "*Chvíli tě měří pohledem, pak taky mlčí a odvrátí zrak.*",
                 "opts": [("(zůstat stát)", "escalate")]},
    "escalate": {
        "text": "*Ani se nehneš. Přimhouří oči.*",
        "opts": [("Jsi protivnej jak prdel.", "provoke"),
                 ("Nebudu tě rušit.", "__hub__"),
                 ("…mlčet.", "stare")],
    },
    "provoke": {
        "text": "„Abych ti brzo nezlomil všechny kosti, co máš v těle. Zmiz mi z očí.“",
        "opts": [("Vsadím se, že jsi slaboch.", "challenge"), ("…mlčet.", "__hub__")],
    },
    "stare": {"text": "„Co je? Nezírej na mě tak.“", "opts": [("…mlčet.", "__hub__")]},
    "challenge": {
        "text": "*„Já ti ukážu, kdo je slaboch!“ Prudce se zvedne, připravený tě zmlátit — "
                "ale když zahlédne Arionin výraz, honem si to rozmyslí a zase dosedne.*\n\n"
                "**„Vyzývám tě na páku. Ukážu ti svou sílu.“**",
        "opts": [("Přijímám.", "duel"), ("Nechci.", "decline")],
    },
    "decline": {"text": "„A pak kdo je tu slaboch.“", "opts": [("Odejít", "__hub__")]},
    "duel": {"kind": "str_duel", "button": "💪 Zapřít se  ·  1d20 + STR",
             "button_style": discord.ButtonStyle.danger,
             "text": "*Opřete se lokty o stůl. Sevře ti dlaň jak svěrák a zakření se.*"},
    "reward": {"text": "…", "opts": [("A co odměna za výhru?", "reward_ask"), ("(Odejít)", "__hub__")]},
    "reward_ask": {"text": "„…Když ti dám odměnu, dáš mi pokoj?“",
                   "opts": [("Ano.", "reward_yes"), ("Ne.", "reward_no")]},
    "reward_no": {"text": "„Radši tě nechám být…“\n\n*Vražedný pohled v jeho očích "
                          "naznačuje, že by tu brzy mohlo dojít k tragédii.*",
                  "opts": [("Odejít", "__hub__")]},
    "duel_lose": {"text": "…", "opts": [("Odejít", "__hub__")]},
    "reward_done": {"text": "…", "opts": [("Odejít", "__hub__")]},
}


class HornedDialogueView(NodeDialogueView):
    """Muž s rohy — provokační strom, páka na STR, jednorázová odměna."""
    TITLE = _HORNED_TITLE
    COLOR = 0x922b21
    IMAGE = "npc_rohac.png"
    NODES = _HORNED_NODES

    async def _kind_str_duel(self, interaction: discord.Interaction):
        prof   = load_json(DATA_FILE, default={}).get(pkey(interaction.user.id), {})
        my_str = prof.get("stats", {}).get("STR", 0)
        my_die = random.randint(1, 20)
        my     = my_die + my_str
        npc    = random.randint(1, 20) + 3          # NPC bonus +3
        cap = f"-# 💪 Páka — ty **{my}** ({my_die}+{my_str} STR) vs. on **{npc}**"
        if my > npc:                                # remíza → NPC vyhrává
            await self._goto_node(interaction, "reward", f"{cap}  ✔️\n\n„…Ubohé. Odejdi pryč.“")
        else:
            await self._goto_node(interaction, "duel_lose", f"{cap}  ❌\n\n„Máš ruce jako párátka… Pche.“")

    async def _target_reward_yes(self, interaction: discord.Interaction):
        uid  = pkey(interaction.user.id)
        data = load_json(DATA_FILE, default={})
        prof = data.setdefault(uid, {})
        if not prof.get("rohac_reward"):
            add_gold(interaction.user.id, 30)
            prof["rohac_reward"] = True
            save_json(DATA_FILE, data)
            text = ("„A už mě nech být.“\n\n**+30 🪙**\n\n"
                    "*„Díky.“ Vezmeš zlato a otočíš se k odchodu.*")
        else:
            text = "„Už jsem ti dal dost. Zmiz.“"
        await self._goto_node(interaction, "reward_done", text)


async def _show_npc_rohac(interaction: discord.Interaction, dest_key: str, portrait_url: str | None = None):
    node  = "intro" if _npc_first_visit(interaction.user.id, "rohac") else "reintro"
    view  = HornedDialogueView(dest_key, portrait_url, node=node)
    embed = view._embed()
    _f    = _attach(embed, view.IMAGE)
    await interaction.response.edit_message(embed=embed, view=view, attachments=[_f] if _f else [])


# Registr handlerů NPC (musí být až po definici funkcí)
_NPC_HANDLERS = {
    "runar":     _show_npc_runar,
    "trpaslici": _show_npc_trpaslici,
    "rohac":     _show_npc_rohac,
}


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

class FinalEnterView(TutorialView):
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=1800)
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
                    logger.exception(f"[onboard] Nepodařilo se přidat roli destinace: {e}")

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
            logger.exception(f"[onboard] Auto-quest chyba: {e}")

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
                    logger.exception(f"[onboard] Nepodařilo se poslat uvítání do hub kanálu: {e}")

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
                    logger.exception(f"[onboard] Nepodařilo se přidat do chat kanálu: {e}")

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
            logger.exception(f"[onboard] Nepodařilo se zapsat do deníku: {e}")

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
            logger.exception(f"[onboard] Nepodařilo se udělit tutorial achievement: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# KROK 12 — Příjezd: Ulice
# ══════════════════════════════════════════════════════════════════════════════

class ArrivalStreetView(TutorialView):
    def __init__(self, dest_key: str, portrait_url: str | None = None):
        super().__init__(timeout=1800)
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
        _f = _attach(embed, dest.get("image"))
        if self.portrait_url:
            embed.set_thumbnail(url=self.portrait_url)
        embed.set_footer(text=f"⭐ Aurionis  ·  Vítej v {dest['name']}.")

        await interaction.response.edit_message(
            embed=embed,
            view=FirstStepView(),
            attachments=[_f] if _f else [],
        )


class FirstStepView(TutorialView):
    def __init__(self):
        super().__init__(timeout=1800)

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
        _f = _attach(embed, URL_TUTORIAL_END)
        embed.set_footer(text="⭐ Aurionis")
        await interaction.response.edit_message(embed=embed, view=None, attachments=[_f] if _f else [])


# ══════════════════════════════════════════════════════════════════════════════
# VAROVÁNÍ — před spuštěním tutoriálu
# ══════════════════════════════════════════════════════════════════════════════

class TutorialWarningView(TutorialView):
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
        _f = _attach(embed, URL_PLAKAT_HVEZDA)
        await interaction.response.send_message(embed=embed, view=TutorialPartOneView(), ephemeral=True, **({"file": _f} if _f else {}))

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
        _attach(embed, URL_PLAKAT_HVEZDA)
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
            logger.exception('[onboard] potlačená chyba')

        if msg_id:
            try:
                old_msg = await tutorial_channel.fetch_message(msg_id)
                _ef = _img(URL_PLAKAT_HVEZDA)
                await old_msg.edit(embed=embed, view=TutorialWarningView(), attachments=[_ef] if _ef else [])
                return
            except Exception:
                logger.exception('[onboard] potlačená chyba')

        _nf = _img(URL_PLAKAT_HVEZDA)
        new_msg = await tutorial_channel.send(embed=embed, view=TutorialWarningView(), **({"file": _nf} if _nf else {}))
        try:
            save_json(TUTORIAL_MSG_FILE, {"message_id": new_msg.id})
        except Exception:
            logger.exception('[onboard] potlačená chyba')

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
            
            for item_id, qty in loadout_data.get("items", []):
                add_registered_item_to_profile(profile, item_id, qty)
            
            save_json(DATA_FILE, profiles)
            
            embed = discord.Embed(
                title="✅  Loadout přidělen",
                description=(
                    f"**{target_user.mention}** ({loadout}) nyní má:\n\n"
                    + "\n".join((f"• {iid} ×{q}" if q > 1 else f"• {iid}") for iid, q in loadout_data.get("items", []))
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