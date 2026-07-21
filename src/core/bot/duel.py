"""
/duel @hráč <sázka> — Textová tahová 1v1 aréna. Minigame pro ArionBOT.
"""
import asyncio
import random
import discord
from discord.ext import commands
from discord import app_commands

from src.utils.paths import ECONOMY as ECONOMY_FILE, DUEL_SCORES as DUEL_SCORES_FILE
from src.logic.economy import minigame_file, minigame_coin, get_minigame_currency, COIN_GOLD, COIN_SILVER
from src.utils.json_utils import load_json, save_json
from src.core.dnd.achievements import grant_achievement, announce_achievement, has_achievement

COIN = "<:goldcoin:1490171741237018795>"

# ── Bojové třídy ──────────────────────────────────────────────────────────────

CLASSES: dict[str, dict] = {
    "Monk": {
        "emoji": "🥷", "hp": 135, "stamina": 120, "furioku_max": 170, "recover": 40,
        "dmg_mod": 1.00, "color": 0xE67E22,
        "guard_absorb": 0.38,
        "passive": "Meditativní tok — Furioku aura chráni před dmg; Meditace obnoví 30 HP",
        "lore": "Disciplinovaný bojovník těla i ducha. Nikdy neutíká od boje.",
        "basic_name": "Meditace",           "basic_desc": "Obnov 30 HP a 10 sta",              "basic_cd": 3,
        "ult_name":   "Duch bouře",         "ult_desc":   "~63 dmg + 🌀 CONFUSION 1 kolo",     "ult_charge_max": 5,
    },
    "Knight": {
        "emoji": "🛡️", "hp": 180, "stamina": 80, "furioku_max": 200, "recover": 25,
        "dmg_mod": 1.10, "color": 0x95A5A6,
        "guard_absorb": 0.52,
        "passive": "Železná pevnost — nejvyšší furioku v aréně",
        "lore": "Obrněný válečník. Pomalý. Neúprosný.",
        "basic_name": "Požehnání",          "basic_desc": "Obnov 45 sta",                      "basic_cd": 3,
        "ult_name":   "Úder spravedlnosti", "ult_desc":   "~72 dmg + 💫 STUN 1 kolo, ignoruje štít", "ult_charge_max": 5,
    },
    "Rogue": {
        "emoji": "🗡️", "hp": 120, "stamina": 105, "furioku_max": 160, "recover": 35,
        "dmg_mod": 0.95, "color": 0x2C3E50,
        "guard_absorb": 0.20,
        "passive": "Stínový krok — úskok vyhýbá VŠEM útokům + free counter",
        "lore": "Rychlý a zákeřný. Kdo ho uvidí, je mrtvý.",
        "basic_name": "Jedová čepel",       "basic_desc": "☠️ POISON 3 kola (15/kolo)",          "basic_cd": 3,
        "ult_name":   "Zákeřný úder",       "ult_desc":   "~81 dmg + 🩸 BLEED 2 kola, nelze blokovat", "ult_charge_max": 4,
    },
    "Berserker": {
        "emoji": "🪓", "hp": 160, "stamina": 90, "furioku_max": 165, "recover": 30,
        "dmg_mod": 1.35, "color": 0xE74C3C,
        "guard_absorb": 0.25,
        "passive": "Krvavý hněv — pod 30 % HP: dmg +50 %",
        "lore": "Šílený válečník. Čím méně HP, tím nebezpečnější.",
        "basic_name": "Bojový řev",         "basic_desc": "Příští útok +80 % (viditelné!)",     "basic_cd": 4,
        "ult_name":   "Zběsilost",          "ult_desc":   "3 kola: 2× útok, nelze štítit, -8 HP/kolo", "ult_charge_max": 4,
    },
    "Guardian": {
        "emoji": "⚜️", "hp": 175, "stamina": 85, "furioku_max": 190, "recover": 30,
        "dmg_mod": 1.00, "color": 0x27AE60,
        "guard_absorb": 0.55,
        "passive": "Trny — štít vrací 10 dmg útočníkovi (15 při critical)",
        "lore": "Neproniknutelný. Protiúder je smrtící.",
        "basic_name": "Železný hrad",       "basic_desc": "35 HP absorb shield, neotevírá",    "basic_cd": 3,
        "ult_name":   "Odvetný úder",       "ult_desc":   "Příší útok na tebe → 0 dmg + 3× zpět",  "ult_charge_max": 5,
    },
    "Duelist": {
        "emoji": "🤺", "hp": 130, "stamina": 100, "furioku_max": 165, "recover": 35,
        "dmg_mod": 1.05, "color": 0x9B59B6,
        "guard_absorb": 0.35,
        "passive": "Přesné oko — klam ignoruje štít úplně, plný dmg",
        "lore": "Elegantní. Každá akce je kalkulovaná.",
        "basic_name": "Přesný výpad",       "basic_desc": "~40 dmg přímý, nelze blokovat",     "basic_cd": 2,
        "ult_name":   "Dokonalý souboj",    "ult_desc":   "Riposte stance: příší útok → 150 % counter", "ult_charge_max": 4,
    },
    "Gladiator": {
        "emoji": "🏛️", "hp": 155, "stamina": 90, "furioku_max": 175, "recover": 28,
        "dmg_mod": 1.20, "color": 0xB8860B,
        "guard_absorb": 0.42,
        "passive": "Arénní pes — heavy útoky způsobují bonus dmg",
        "lore": "Vychován v písku a krvi. Aréna je jeho chrám. Všechno ostatní je příprava.",
        "basic_name": "Krvavý řez",         "basic_desc": "25 dmg přímý, nelze blokovat",      "basic_cd": 3,
        "ult_name":   "Gladiátorský tanec", "ult_desc":   "3 rychlé rány — ~76 dmg celkem",    "ult_charge_max": 4,
    },
    "Cyborg": {
        "emoji": "🤖", "hp": 140, "stamina": 95, "furioku_max": 165, "recover": 30,
        "dmg_mod": 1.05, "color": 0x00BFFF,
        "guard_absorb": 0.38,
        "passive": "Přesný mechanismus — Laserová střela se nabíjí každé kolo (CD 1)",
        "lore": "Polovina člověka, polovina stroje. Žádný cit, žádná únava — jen výpočty.",
        "basic_name": "Laserová střela",    "basic_desc": "20 dmg přímý + 40% 🔥 BURN 2 kola, nelze blokovat", "basic_cd": 1,
        "ult_name":   "Výboj",             "ult_desc":   "4×18 dmg, poté stamina → 0",         "ult_charge_max": 4,
    },
    "Vampire": {
        "emoji": "🧛", "hp": 120, "stamina": 85, "furioku_max": 160, "recover": 28,
        "dmg_mod": 1.05, "color": 0x6A0DAD,
        "guard_absorb": 0.25,
        "passive": "Krvavý pakt — každý útok vrátí 15 % způsobeného dmg jako HP",
        "lore": "Smrt je jen práh. Za ním je něco mnohem horšího — a ty to právě potkáváš.",
        "basic_name": "Krvavý políbek",     "basic_desc": "35 dmg + heal ~12 HP + 30% 💤 SLEEP, nelze blokovat", "basic_cd": 3,
        "ult_name":   "Noční hostina",      "ult_desc":   "~68 dmg + heal ~24 HP, nelze blokovat",           "ult_charge_max": 5,
    },
    "Warlock": {
        "emoji": "🔮", "hp": 110, "stamina": 85, "furioku_max": 155, "recover": 28,
        "dmg_mod": 1.00, "color": 0x4B0082,
        "guard_absorb": 0.22,
        "passive": "Krvavý pakt — každý zásah přidá CURSE stack (+5 dmg na útok, max ×3)",
        "lore": "Podepsal smlouvu, jejíž podmínky nikdy nečetl. Teď z ní žije — nebo umírá.",
        "basic_name": "Hexe",           "basic_desc": "20 % max HP soupeře jako přímý dmg, nelze blokovat",  "basic_cd": 2,
        "ult_name":   "Duše za duši",   "ult_desc":   "Prohodí aktuální HP obou hráčů",                      "ult_charge_max": 5,
    },
}

CLASS_NAMES = list(CLASSES.keys())

# ── Intent text (zobrazí se nad ActionView) ───────────────────────────────────

INTENT_TEXT: dict[str, str] = {
    "Monk":      "🥷 *Dýchá klidně. Každý pohyb je záměrný.*",
    "Knight":    "🛡️ *Zaujímá pevný postoj. Čeká na správný okamžik.*",
    "Rogue":     "🗡️ *Krouží kolem. Hledá mezeru v obraně.*",
    "Berserker": "🪓 *Svírá zbraň. Krev v očích.*",
    "Guardian":  "⚜️ *Štít zapřen. Nepohne se z místa.*",
    "Duelist":   "🤺 *Analyzuje každý pohyb soupeře. Čeká na chybu.*",
    "Gladiator":    "🏛️ *Krok za krokem. Čeká na správný moment.*",
    "Cyborg":       "🤖 *Systémy aktivovány. Cíl uzamčen. Střelba povolena.*",
    "Vampire":      "🧛 *Oči žhnou rudě. Voní krev — tvoje.*",
    "Warlock":      "🔮 *Rty se pohybují. Smlouva hoří. Pakt je aktivní.*",
}
INTENT_CRITICAL: dict[str, str] = {
    "Monk":      "🥷 *Krvácí... ale dech je stále klidný. Klid před bouří.*",
    "Knight":    "🛡️ *Potácí se. Ale štít stále drží. Brnění zkrvavené.*",
    "Rogue":     "🗡️ *Schoulí se do tmy. Teď nebo nikdy.*",
    "Berserker": "🪓 *KREV. BOLEST. ŠÍLENSTVÍ. Teď to začíná!*",
    "Guardian":  "⚜️ *Opírá se o štít. Krvácí. Ale necouvne.*",
    "Duelist":   "🤺 *Zraněn — ale oči nikdy nepřestaly číst soupeře.*",
    "Gladiator":    "🏛️ *Krvácí — ale oči žhnou. Aréna to vidí.*",
    "Cyborg":       "🤖 *Přehřátí systémů. Chladicí selhání. Funkce omezeny. Pokračuji.*",
    "Vampire":      "🧛 *Krvácí — a v očích se rozhoří něco temného. Nebezpečnější než kdy dřív.*",
    "Warlock":      "🔮 *Krvácí. Ale smlouva zesiluje — každý zásah ho dělá smrtelnějším.*",
}
INTENT_BERSERK: str = "🪓 *ZBĚSILOST — útočí bez zastavení. Zastavit ho nelze.*"

# ── Critical log (přidá se do logu při zásahu pod 30 % HP) ───────────────────

CRITICAL_LINES: dict[str, list[str]] = {
    "Monk": [
        "*{n} zakymácí... a pokračuje. Dech. Jen dech.*",
        "*{n} krvácí — ale mysl zůstává jasná.*",
        "*Bolest je jen pocit. {n} se soustředí.*",
        "*{n} zavírá oči na zlomek vteřiny. Pak znovu otevírá — klidné.*",
    ],
    "Knight": [
        "*{n} zaklesne zuby. Brnění je zkrvavené, ale drží.*",
        "*{n} se potácí — a přesto nezahodil štít.*",
        "*Každý úder ho posílá zpět o krok. Ale nikdy o dva.*",
        "*{n} krvácí. Musí vydržet. Vydrží.*",
    ],
    "Rogue": [
        "*{n} krvácí. Ale oči zůstávají chladné.*",
        "*{n} ustoupí do tmy. Kritický stav.*",
        "*Zranění je smrtelné — pokud ho nechá zabít. {n} nepodvolí.*",
        "*{n} si otírá krev z tváře. Úsměv mizí.*",
    ],
    "Berserker": [
        "*{n} se skoro usmívá. Teď to začíná.*",
        "*{n} — krev ho jen rozzuřuje. VÍC.*",
        "*Každý zásah jen přilévá oleje. {n} řve.*",
        "*Bolest? {n} to necítí. Vidí jen soupeře.*",
    ],
    "Guardian": [
        "*{n} se opře o štít. Nedá se.*",
        "*{n} krvácí, ale nohy stojí pevně.*",
        "*Štít se tepe. {n} se netřese.*",
        "*I zkrvavený {n} neustoupí ani o krok.*",
    ],
    "Duelist": [
        "*{n} si otře krev. Postoj je stále přesný.*",
        "*{n} zraněn — oči nikdy nepřestaly číst.*",
        "*Krev mu stéká po ruce. Nevadí. Soustředí se.*",
        "*{n} se usmívá. Takhle souboj teprve začíná.*",
    ],
    "Gladiator": [
        "*{n} krvácí na písku. Tohle ho nezastaví.*",
        "*Rány na těle {n} — každá z nich odměněna dvěma zpět.*",
        "*{n} slyší arénu. To ho drží na nohách.*",
        "*Krev a písek. {n} byl stvořen pro tenhle okamžik.*",
    ],
    "Cyborg": [
        "*{n} se přehřívá — chlazení na limitech. Systém přesto pokračuje.*",
        "*Kritické poškození struktury. {n} přepočítává strategii.*",
        "*Varování: kapacita na 20 %. {n} ignoruje výzvy k zastavení.*",
        "*{n} — chyba systému. Hrubá síla jako záloha.*",
    ],
    "Vampire": [
        "*{n} krvácí — ale oči žhnou rudě. Nezastaví ho to.*",
        "*Čím blíže smrti, tím hladovější. {n} to cítí.*",
        "*{n} se sotva drží. Každá kapka krve ho jen dráždí.*",
        "*Bolest je jen připomínka, že stále žije. {n} se usmívá.*",
    ],
    "Warlock": [
        "*{n} krvácí — a smlouva mu to vrátí trojnásobně.*",
        "*Každý zásah jen posiluje prokletí. {n} to ví.*",
        "*Na pokraji. Ale pakt ještě nebyl naplněn.*",
        "*{n} se lopotí. Temná energie ho drží pohromadě.*",
    ],
}

# ── Akce ─────────────────────────────────────────────────────────────────────

STAM_COSTS = {
    "attack": 15, "heavy": 25, "guard": 10,
    "feint": 12,  "dodge": 15, "recover": 0,
    "basic": 0,   "ultimate": 0,
    "hp_potion": 0, "sta_potion": 0,
    "furioku_heal": 0,
    "stimulant": 0, "stun": 0,
}

_ABILITY_ACTIONS = frozenset(("basic", "ultimate", "hp_potion", "sta_potion", "furioku_heal", "stimulant", "stun"))

BASE_ATK    = 22
BASE_HEAVY  = 28
RIPOSTE_CTR = 15

GUARD_LIGHT_ABSORB = 0.92  # fixed high absorb for light attacks — guard is near-immune to normal hits

# ── Status effects ────────────────────────────────────────────────────────────

STATUS_EMOJIS: dict[str, str] = {
    "bleed":     "🩸",
    "poison":    "☠️",
    "stun":      "💫",
    "burn":      "🔥",
    "confusion": "🌀",
    "sleep":     "💤",
}
STATUS_LABELS: dict[str, str] = {
    "bleed":     "BLEEDING",
    "poison":    "POISON",
    "stun":      "STUN",
    "burn":      "BURN",
    "confusion": "CONFUSION",
    "sleep":     "SLEEP",
}
STATUS_DMG: dict[str, int] = {   # per-round damage for DoT statuses
    "bleed":  8,
    "poison": 15,
    "burn":   10,
}

# ── Fighter ───────────────────────────────────────────────────────────────────

class Fighter:
    def __init__(self, member: discord.Member, cls_name: str):
        self.member      = member
        self.cls_name    = cls_name
        cls              = CLASSES[cls_name]
        self.hp          = cls["hp"]
        self.max_hp      = cls["hp"]
        self.stamina     = cls["stamina"]
        self.max_sta     = cls["stamina"]
        self.ult_charge  = 0
        self.berserk:      int  = 0
        self.riposte:      bool = False
        self.buff_heavy:   bool = False
        self.buff_poison:  int  = 0
        self.buff_absorb:  bool = False
        self.shield_hp:    int  = 0
        self.buff_reflect:  bool = False
        self.reflect_used:  bool = False
        self.furioku        = cls.get("furioku_max", 0)
        self.max_furioku    = cls.get("furioku_max", 0)
        self.furioku_invest: int  = 0
        self.furioku_shield: bool = True   # True = furioku absorbuje dmg pasivně
        self.cooldowns: dict[str, int] = {"basic": 0}
        self.bag:       dict[str, int] = {"hp_potion": 1, "sta_potion": 1, "stimulant": 2}
        self.statuses:    dict[str, int] = {}   # status_name → rounds_remaining
        self.curse_stacks: int          = 0    # Warlock passive — max 3
        self.action: str | None = None

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def exhausted(self) -> bool:
        return self.stamina < 5

    @property
    def critical(self) -> bool:
        return self.hp > 0 and self.hp <= self.max_hp * 0.30


# ── DuelState ─────────────────────────────────────────────────────────────────

class DuelState:
    def __init__(self, f1: Fighter, f2: Fighter, bet: int, channel: discord.TextChannel):
        self.f1        = f1
        self.f2        = f2
        self.bet       = bet
        self.channel   = channel
        self.round     = 0
        self.done      = False
        self._lock     = asyncio.Lock()
        self.arena_msg: discord.Message | None = None
        self.last_a1: str | None = None
        self.last_a2: str | None = None
        self.round_logs: list[tuple[int, list[str]]] = []

    def both_chose(self) -> bool:
        return self.f1.action is not None and self.f2.action is not None


# ── Registry ──────────────────────────────────────────────────────────────────

_active:   dict[int, DuelState] = {}
_pending:  set[int]             = set()   # hráči v class selection (před registrací do _active)
_eco_lock: asyncio.Lock         = asyncio.Lock()

def _register(state: DuelState):
    _active[state.f1.member.id] = state
    _active[state.f2.member.id] = state

def _cleanup(state: DuelState):
    _active.pop(state.f1.member.id, None)
    _active.pop(state.f2.member.id, None)
    state.done = True

# ── Leaderboard ───────────────────────────────────────────────────────────────

def _load_duel_scores() -> dict:
    return load_json(DUEL_SCORES_FILE) or {}

def _save_duel_scores(data: dict):
    save_json(DUEL_SCORES_FILE, data)

def _duel_migrate(rec: dict):
    """Starý jednotný 'profit' → profit_silver."""
    if "profit" in rec and "profit_silver" not in rec:
        rec["profit_silver"] = rec.pop("profit")


def _duel_profit(rec: dict, currency: str) -> int:
    if currency == "silver" and "profit_silver" not in rec and "profit" in rec:
        return rec.get("profit", 0)
    return rec.get(f"profit_{currency}", 0)


def _record_result(winner_id: int, loser_id: int, bet: int, currency: str = None) -> int:
    if currency is None:
        currency = get_minigame_currency()
    scores = _load_duel_scores()
    wk, lk = str(winner_id), str(loser_id)
    for uid in (wk, lk):
        rec = scores.setdefault(uid, {"wins": 0, "losses": 0, "streak": 0})
        _duel_migrate(rec)
    scores[wk]["wins"]   += 1
    scores[lk]["losses"] += 1
    pkey = f"profit_{currency}"
    scores[wk][pkey] = scores[wk].get(pkey, 0) + bet
    scores[lk][pkey] = scores[lk].get(pkey, 0) - bet
    scores[wk]["streak"] = scores[wk].get("streak", 0) + 1
    scores[lk]["streak"] = 0
    _save_duel_scores(scores)
    return scores[wk]["streak"]


def _duel_leaderboard_embed(guild, currency: str = "silver") -> discord.Embed:
    icon  = COIN_GOLD if currency == "gold" else COIN_SILVER
    cname = "Zlaťáky" if currency == "gold" else "Stříbrňáky"
    scores = _load_duel_scores()
    if not scores:
        return discord.Embed(
            title="⚔️  Duel — Žebříček",
            description="Zatím žádné duely na tomto serveru.\n*Buď první!*",
            color=0x1a1a2e,
        ).set_footer(text="⭐ Aurionis")

    top = sorted(scores.items(), key=lambda x: (-x[1].get("wins", 0), -_duel_profit(x[1], currency)))[:10]
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines  = []
    for i, (uid, s) in enumerate(top):
        member = guild.get_member(int(uid)) if guild else None
        name   = member.display_name if member else f"<@{uid}>"
        wins   = s.get("wins", 0); losses = s.get("losses", 0)
        profit = _duel_profit(s, currency); streak = s.get("streak", 0)
        total  = wins + losses
        ratio  = f"{round(wins/total*100)} %" if total else "—"
        profit_str = (f"+{profit}" if profit > 0 else str(profit)) if profit else "—"
        streak_str = f"  ·  🔥 {streak} v řadě" if streak >= 2 else ""
        lines.append(
            f"{medals[i]} **{name}**\n"
            f"┣ 🏆 {wins}V / {losses}P  ·  {ratio} winrate{streak_str}\n"
            f"┗ 💰 Profit: **{profit_str}** {icon if profit else ''}"
        )
    embed = discord.Embed(
        title=f"⚔️  Duel — Žebříček ({cname})",
        description="\n\n".join(lines),
        color=0x1a1a2e,
    )
    embed.set_footer(text="⭐ Aurionis  ·  Top 10 duelistů")
    return embed


class DuelLeaderboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Zlaťáky", emoji="🟡", style=discord.ButtonStyle.secondary)
    async def gold_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=_duel_leaderboard_embed(interaction.guild, "gold"), view=self)

    @discord.ui.button(label="Stříbrňáky", emoji="⚪", style=discord.ButtonStyle.secondary)
    async def silver_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=_duel_leaderboard_embed(interaction.guild, "silver"), view=self)

# ── Vizuální helpers ──────────────────────────────────────────────────────────

def _bar(cur: int, max_: int, n: int = 10) -> str:
    filled = max(0, round(n * max(0, cur) / max_)) if max_ > 0 else 0
    return "█" * filled + "░" * (n - filled)

def _ult_bar(charge: int, max_: int) -> str:
    return "▰" * charge + "▱" * (max_ - charge)

def _hp_icon(hp: int, max_hp: int) -> str:
    r = hp / max_hp if max_hp > 0 else 0
    return "🟢" if r > 0.55 else ("🟡" if r > 0.25 else "🔴")

def _fighter_bar(f: Fighter) -> str:
    cls   = CLASSES[f.cls_name]
    hi    = _hp_icon(max(0, f.hp), f.max_hp)
    fi    = "💜" if f.furioku > f.max_furioku * 0.5 else ("🟠" if f.furioku > f.max_furioku * 0.2 else "🔴")
    max_c = cls["ult_charge_max"]
    ub    = _ult_bar(f.ult_charge, max_c)
    ready = " ✨ READY!" if f.ult_charge >= max_c else f" {f.ult_charge}/{max_c}"

    tags = []
    if f.berserk > 0:        tags.append(f"🔥 BERSERK {f.berserk}")
    if f.riposte:            tags.append("⚡ RIPOSTE")
    if f.buff_heavy:         tags.append("💢 NABITO")
    if f.shield_hp > 0:      tags.append(f"🛡️ SHIELD {f.shield_hp}")
    if f.curse_stacks > 0:   tags.append(f"🔮 KLETBA ×{f.curse_stacks}")
    if f.critical:           tags.append("🩸 CRITICAL")
    if f.furioku_invest > 0: tags.append(f"💜 invest {f.furioku_invest}")
    for _st, _r in f.statuses.items():
        _e = STATUS_EMOJIS.get(_st, "?")
        _l = STATUS_LABELS.get(_st, _st.upper())
        tags.append(f"{_e} {_l}{'!' if _r <= 1 else f' {_r}'}")
    tag_line = ("  " + "  ".join(tags)) if tags else ""

    bag_line = ""
    if any(f.bag.values()):
        items = []
        if f.bag.get("hp_potion"):  items.append(f"🧪×{f.bag['hp_potion']}")
        if f.bag.get("sta_potion"): items.append(f"⚡×{f.bag['sta_potion']}")
        bag_line = f"\n-# 🎒 {' '.join(items)}"

    return (
        f"{cls['emoji']} **{f.member.display_name}** — {f.cls_name}{tag_line}\n"
        f"`HP  [{_bar(f.hp, f.max_hp)}]` {hi} {max(0, f.hp)}/{f.max_hp}\n"
        f"`STA [{_bar(f.stamina, f.max_sta)}]` ⚡ {max(0, f.stamina)}/{f.max_sta}\n"
        f"`FUR [{_bar(f.furioku, f.max_furioku)}]` {fi} {max(0, f.furioku)}/{f.max_furioku}\n"
        f"`ULT [{ub}]`{ready}{bag_line}"
    )

def _hp_warning(f: Fighter) -> str | None:
    pct = f.hp / f.max_hp if f.max_hp > 0 else 0
    if pct <= 0.15: return f"☠️ **{f.member.display_name}** se sotva drží na nohou..."
    if pct <= 0.28: return f"⚠️ **{f.member.display_name}** je těžce raněn!"
    return None

# ── Damage resolution ─────────────────────────────────────────────────────────

def _rdm(base: int, var: int = 4) -> int:
    return base + random.randint(-var, var)

def _eff(f: Fighter, base: int) -> int:
    stam_mod  = max(0.5, f.stamina / f.max_sta) if f.max_sta > 0 else 0.5
    class_mod = CLASSES[f.cls_name]["dmg_mod"]
    rage_mod  = 1.5 if f.cls_name == "Berserker" and f.critical else 1.0
    boost_mod = 1.8 if f.buff_heavy else 1.0
    crit_mod  = 1.20 if f.critical and f.cls_name == "Duelist" else 1.0
    f.buff_heavy = False
    return max(1, round(base * class_mod * stam_mod * rage_mod * boost_mod * crit_mod))

def _atk(f: Fighter) -> int: return _eff(f, _rdm(BASE_ATK))
def _hvy(f: Fighter) -> int: return _eff(f, _rdm(BASE_HEAVY, 5))

def _riposte_ctr(f: Fighter) -> int:
    mult = 1.5 if f.cls_name == "Duelist" else 1.0
    return max(1, round(RIPOSTE_CTR * mult * CLASSES[f.cls_name]["dmg_mod"]))

def _guard_absorb(f: Fighter, raw: int) -> tuple[int, int]:
    absorb = CLASSES[f.cls_name]["guard_absorb"]
    if f.buff_absorb:
        absorb = min(0.88, absorb + 0.5)
        f.buff_absorb = False
    if f.critical and f.cls_name == "Knight":
        absorb = min(0.75, absorb + 0.10)
    return round(raw * (1 - absorb)), 15

def _critical_line(f: Fighter) -> str | None:
    lines = CRITICAL_LINES.get(f.cls_name, [])
    return random.choice(lines).format(n=f.member.display_name) if lines else None

def _apply_status(target: Fighter, status: str, rounds: int) -> str:
    current = target.statuses.get(status, 0)
    target.statuses[status] = max(current, rounds)
    e = STATUS_EMOJIS[status]
    l = STATUS_LABELS[status]
    n = target.member.display_name
    if current > 0:
        return f"{e} **{n}** — {l} obnoven! ({target.statuses[status]} kola)"
    return f"{e} **{n}** — **{l}**! ({rounds} {'kolo' if rounds == 1 else 'kola'})"

def _apply_stimulant(f: Fighter, log: list[str]):
    f.bag["stimulant"] = max(0, f.bag.get("stimulant", 0) - 1)
    n = f.member.display_name
    neg = [s for s in ("bleed", "poison", "burn", "stun", "confusion", "sleep") if s in f.statuses]
    for s in neg:
        del f.statuses[s]
    f.stamina = min(f.max_sta, f.stamina + 20)
    if neg:
        removed = ", ".join(STATUS_LABELS[s] for s in neg)
        log.append(f"💉 **{n}** — Stimulant! **+20 STA**, odstraněno: **{removed}**!")
    else:
        log.append(f"💉 **{n}** — Stimulant! **+20 STA**.")

# ── Ability handlers ──────────────────────────────────────────────────────────

def _apply_basic(f: Fighter, opp: Fighter, log: list[str]) -> int:
    cls = CLASSES[f.cls_name]
    f.cooldowns["basic"] = cls["basic_cd"]
    n = f.member.display_name
    if f.cls_name == "Monk":
        heal = 30; sta = 10
        f.hp = min(f.max_hp, f.hp + heal)
        f.stamina = min(f.max_sta, f.stamina + sta)
        log.append(f"✨ **{n}** se ponoří do klidu — vdechne, vydechne. **+{heal} HP**, **+{sta} staminy**.")
    elif f.cls_name == "Knight":
        sta = 45
        f.stamina = min(f.max_sta, f.stamina + sta)
        log.append(f"✨ **{n}** se požehná světlem — **+{sta} sta**.")
    elif f.cls_name == "Rogue":
        log.append(f"☠️ **{n}** natírá čepel jedem a bodne — {_apply_status(opp, 'poison', 3)}")
    elif f.cls_name == "Berserker":
        f.buff_heavy = True
        log.append(f"💢 **{n}** zadusí řev — energie se sbírá. Příští úder bude devastující!")
    elif f.cls_name == "Guardian":
        gained = 35
        f.shield_hp = max(f.shield_hp, gained)
        log.append(f"⚜️ **{n}** vztyčí Železný hrad — **+{gained} HP absorb shield!** Pozice není otevřena.")
    elif f.cls_name == "Duelist":
        dmg = 40 + random.randint(-3, 3)
        log.append(f"🤺 **{n}** vyrazí vpřed — přesný výpad! **{dmg}** dmg, žádná obrana!")
        return dmg
    elif f.cls_name == "Gladiator":
        dmg = 25
        log.append(f"🏛️ **{n}** — Krvavý řez! Čepel prosekne přímo. **{dmg}** dmg!")
        return dmg
    elif f.cls_name == "Cyborg":
        dmg = 20 + random.randint(-2, 2)
        log.append(f"🤖 **{n}** — Laserová střela! Paprsek z ramene. **{dmg}** dmg!")
        if random.random() < 0.40:
            log.append(_apply_status(opp, "burn", 2))
        return dmg
    elif f.cls_name == "Warlock":
        dmg = round(opp.max_hp * 0.20)
        log.append(f"🔮 **{n}** — **HEXE!** Prokletí pálí zevnitř — **{dmg}** dmg *(20 % max HP)*!")
        return dmg
    elif f.cls_name == "Vampire":
        dmg = 35 + random.randint(-3, 3)
        heal = round(dmg * 0.35)
        f.hp = min(f.max_hp, f.hp + heal)
        log.append(f"🧛 **{n}** — Krvavý políbek! Životní síla přetéká. **{dmg}** dmg + **+{heal} HP**!")
        if random.random() < 0.30:
            log.append(_apply_status(opp, "sleep", 1))
        return dmg
    return 0

def _apply_ultimate(f: Fighter, opp: Fighter, log: list[str]) -> int:
    f.ult_charge = 0
    n = f.member.display_name
    if f.cls_name == "Monk":
        dmg = 63 + random.randint(-5, 5)
        log.append(f"💥 **{n}** — **DUCH BOUŘE!** Energie exploduje z každého póru — **{dmg}** dmg!")
        log.append(_apply_status(opp, "confusion", 1))
        return dmg
    elif f.cls_name == "Knight":
        dmg = 72 + random.randint(-5, 5)
        log.append(f"💥 **{n}** — **ÚDER SPRAVEDLNOSTI!** Meč padá z výše, bez milosti — **{dmg}** dmg, žádný štít!")
        log.append(_apply_status(opp, "stun", 1))
        return dmg
    elif f.cls_name == "Rogue":
        dmg = 81 + random.randint(-5, 5)
        log.append(f"💥 **{n}** — **ZÁKEŘNÝ ÚDER!** Z temnoty, tam kde nikdo nečekal — **{dmg}** dmg!")
        log.append(_apply_status(opp, "bleed", 2))
        return dmg
    elif f.cls_name == "Berserker":
        f.berserk = 3
        log.append(f"💥 **{n}** — **ZBĚSILOST!** Přichází šílenství. **3 kola berserk módu!** Aréna se chvěje.")
        return 0
    elif f.cls_name == "Guardian":
        if f.reflect_used:
            dmg = 45 + random.randint(-5, 5)
            log.append(f"💥 **{n}** — **ODVETNÝ ÚDER!** Reflect již použit — silný přímý úder místo. **{dmg}** dmg!")
            return dmg
        f.buff_reflect = True
        log.append(f"💥 **{n}** — **ODVETNÝ ÚDER!** Štít se rozžhaví. Příší útok letí zpět 2×. ⚜️")
        return 0
    elif f.cls_name == "Duelist":
        f.riposte = True
        log.append(f"💥 **{n}** — **DOKONALÝ SOUBOJ!** Čepel se ponoří do ticha. Riposte stance. ⚡")
        return 0
    elif f.cls_name == "Gladiator":
        r1 = _rdm(25, 4); r2 = _rdm(25, 4); r3 = _rdm(26, 4)
        dmg = r1 + r2 + r3
        log.append(f"💥 **{n}** — **GLADIÁTORSKÝ TANEC!** Tři rychlé rány — **{r1}** + **{r2}** + **{r3}** = **{dmg}** dmg!")
        return dmg
    elif f.cls_name == "Cyborg":
        hits = [18 + random.randint(-2, 2) for _ in range(4)]
        dmg = sum(hits)
        f.stamina = 0
        log.append(f"💥 **{n}** — **VÝBOJ!** Reaktor v hrudi se vybije — {' + '.join(map(str, hits))} = **{dmg}** dmg! Stamina → 0!")
        return dmg
    elif f.cls_name == "Warlock":
        old_f, old_opp = f.hp, opp.hp
        f.hp   = old_opp
        opp.hp = old_f
        log.append(f"🔮 **{n}** — **DUŠE ZA DUŠI!** Životní energie se prohodí — **{old_f} HP ↔ {old_opp} HP**!")
        return 0
    elif f.cls_name == "Vampire":
        dmg = 68 + random.randint(-5, 5)
        heal = round(dmg * 0.35)
        f.hp = min(f.max_hp, f.hp + heal)
        log.append(f"💥 **{n}** — **NOČNÍ HOSTINA!** Temnota pohltí soupeře — **{dmg}** dmg, **+{heal} HP** zpět!")
        return dmg
    return 0

def _apply_potion(f: Fighter, kind: str, log: list[str]):
    n = f.member.display_name
    f.bag[kind] -= 1
    if kind == "hp_potion":
        heal = 45
        f.hp = min(f.max_hp, f.hp + heal)
        log.append(f"🧪 **{n}** vypije lektvar léčení — **+{heal} HP**!")
    elif kind == "sta_potion":
        sta = 60
        f.stamina = min(f.max_sta, f.stamina + sta)
        log.append(f"⚡ **{n}** vypije lektvar staminy — **+{sta} staminy**!")

# ── Round resolution ──────────────────────────────────────────────────────────

def resolve_round(state: DuelState) -> list[str]:
    f1, f2 = state.f1, state.f2
    a1, a2 = f1.action, f2.action
    n1, n2 = f1.member.display_name, f2.member.display_name

    log: list[str] = []
    d1 = 0
    d2 = 0

    # Cooldown decrement
    for f in (f1, f2):
        for k in list(f.cooldowns):
            if f.cooldowns[k] > 0:
                f.cooldowns[k] -= 1

    # Confusion action override (before stamina costs; stun immune)
    for f in (f1, f2):
        if f.statuses.get("confusion", 0) > 0 and f.action != "stun":
            old = f.action
            f.action = random.choice(["attack", "heavy", "guard", "dodge", "recover"])
            n = f.member.display_name
            log.append(f"🌀 **{n}** — **CONFUSION!** Místo _{_ACTION_LABEL.get(old, old)}_ provede **{_ACTION_LABEL.get(f.action, f.action)}**!")
            f.statuses["confusion"] -= 1
            if f.statuses["confusion"] <= 0:
                del f.statuses["confusion"]
    a1, a2 = f1.action, f2.action

    # Stamina costs
    f1.stamina = max(0, f1.stamina - STAM_COSTS.get(a1, 0))
    f2.stamina = max(0, f2.stamina - STAM_COSTS.get(a2, 0))

    # Recover bonus
    if a1 == "recover":
        cls1 = CLASSES[f1.cls_name]
        f1.stamina = min(f1.max_sta, f1.stamina + cls1["recover"])
        log.append(f"💚 **{n1}** couvne a nabere dech — **+{cls1['recover']} sta**.")
    if a2 == "recover":
        cls2 = CLASSES[f2.cls_name]
        f2.stamina = min(f2.max_sta, f2.stamina + cls2["recover"])
        log.append(f"💚 **{n2}** couvne a nabere dech — **+{cls2['recover']} sta**.")

    # Furioku heal pre-pass
    if a1 == "furioku_heal":
        heal = min(f1.furioku_invest, f1.furioku)
        f1.furioku = max(0, f1.furioku - heal)
        f1.hp = min(f1.max_hp, f1.hp + heal)
        f1.furioku_invest = 0
        log.append(f"💜 **{n1}** kanalizuje auru do léčení — **+{heal} HP**! (furioku: {f1.furioku}/{f1.max_furioku})")
    if a2 == "furioku_heal":
        heal = min(f2.furioku_invest, f2.furioku)
        f2.furioku = max(0, f2.furioku - heal)
        f2.hp = min(f2.max_hp, f2.hp + heal)
        f2.furioku_invest = 0
        log.append(f"💜 **{n2}** kanalizuje auru do léčení — **+{heal} HP**! (furioku: {f2.furioku}/{f2.max_furioku})")

    # Status DoT tick (bleed, poison, burn)
    for f, is_f1 in ((f1, True), (f2, False)):
        n = f.member.display_name
        for status in list(f.statuses):
            dmg_per = STATUS_DMG.get(status, 0)
            if dmg_per == 0:
                continue
            if is_f1:
                d1 += dmg_per
            else:
                d2 += dmg_per
            f.statuses[status] -= 1
            e, l = STATUS_EMOJIS[status], STATUS_LABELS[status]
            if f.statuses[status] <= 0:
                del f.statuses[status]
                log.append(f"{e} **{n}** — {l}! **{dmg_per}** dmg. *(skončilo)*")
            else:
                log.append(f"{e} **{n}** — {l}! **{dmg_per}** dmg. ({f.statuses[status]} kola zbývá)")

    # Berserk HP drain
    if f1.berserk > 0:
        d1 += 8
        log.append(f"🔥 Šílenství stravuje **{n1}** zevnitř — **8** HP!")
    if f2.berserk > 0:
        d2 += 8
        log.append(f"🔥 Šílenství stravuje **{n2}** zevnitř — **8** HP!")

    # Nested helpers
    def do_guard(atk: Fighter, grd: Fighter, raw: int, is_heavy: bool = False) -> tuple[int, int]:
        thorns = (15 if grd.critical else 10) if grd.cls_name == "Guardian" else 0
        min_dmg = 8 if is_heavy else 5  # Minimální damage skrz štít
        if is_heavy:
            dmg, _ = _guard_absorb(grd, raw)
            dmg = max(min_dmg, dmg)  # Aplikuj minimum
            absorb_pct = round((1 - dmg / raw) * 100) if raw > 0 else 0
            log.append(f"🛡️ **{grd.member.display_name}** drží štít — heavy dopadá! **{dmg}** dmg ({absorb_pct} % pohlt).")
        else:
            dmg = max(min_dmg, round(raw * (1 - GUARD_LIGHT_ABSORB)))
            log.append(random.choice([
                f"🛡️ **{grd.member.display_name}** vztyčí štít — **BLOCKED!** Jen **{dmg}** dmg pronikne.",
                f"🛡️ Štít **{grd.member.display_name}** pohltí téměř vše — **{dmg}** dmg.",
                f"🛡️ **{grd.member.display_name}** kryje dokonale — **{dmg}** dmg proklouznout.",
            ]))
        if thorns:
            log.append(f"✀ Trny vrací **{thorns}** dmg útočníkovi!")
        return dmg, thorns

    def berserk_attack(f: Fighter, opp: Fighter) -> int:
        d1b = _atk(f); d2b = _atk(f)
        dmg = d1b + d2b
        log.append(random.choice([
            f"🪓 **{f.member.display_name}** — ZBĚSILOST! Dvě rány bez zastavení — **{d1b}** + **{d2b}** = **{dmg}** dmg!",
            f"🪓 **{f.member.display_name}** se vrhá vpřed — nikdo ho nezastaví! **{d1b}** + **{d2b}** = **{dmg}** dmg!",
            f"🪓 Šílenství **{f.member.display_name}** dosáhlo vrcholu — dva záblesky, **{dmg}** dmg celkem!",
        ]))
        if random.random() < 0.35:
            log.append(_apply_status(opp, "bleed", 2))
        return dmg

    # ── Ability/Potion pre-pass ───────────────────────────────────────────────

    ab1 = a1 in _ABILITY_ACTIONS and not (a1 == "basic" and f1.cls_name == "Guardian")
    ab2 = a2 in _ABILITY_ACTIONS and not (a2 == "basic" and f2.cls_name == "Guardian")

    if a1 in ("hp_potion", "sta_potion"): _apply_potion(f1, a1, log)
    if a2 in ("hp_potion", "sta_potion"): _apply_potion(f2, a2, log)
    if a1 == "stimulant": _apply_stimulant(f1, log)
    if a2 == "stimulant": _apply_stimulant(f2, log)

    if a1 == "basic":
        d2 += _apply_basic(f1, f2, log)
    if a2 == "basic":
        d1 += _apply_basic(f2, f1, log)

    if a1 == "ultimate":
        raw = _apply_ultimate(f1, f2, log)
        d2 += raw
    if a2 == "ultimate":
        raw = _apply_ultimate(f2, f1, log)
        d1 += raw

    # ── Ability user is OPEN to normal attacks ────────────────────────────────

    if ab1 and not ab2:
        if a2 in ("attack", "heavy"):
            raw = _hvy(f2) if a2 == "heavy" else _atk(f2)
            d1 += raw
            if a2 == "heavy":
                log.append(f"🪓 **{n2}** trestá otevřenou pozici — **CRUSH! {raw}** dmg!")
            else:
                log.append(f"⚔️ **{n2}** trestá otevřenou pozici — **{raw}** dmg!")
        elif a2 == "feint":
            raw = _atk(f2); d1 += raw
            log.append(f"🎭 **{n2}** pronáší klam na otevřeného soupeře — **{raw}** dmg!")
        elif a2 == "guard":
            log.append(f"*{n2} zvedá štít — nebylo co blokovat.*")
        elif a2 == "dodge":
            log.append(f"*{n2} uhýbá do strany — {n1} neútočil.*")
        # a2 == "recover": already logged above

    elif not ab1 and ab2:
        if a1 in ("attack", "heavy"):
            raw = _hvy(f1) if a1 == "heavy" else _atk(f1)
            d2 += raw
            if a1 == "heavy":
                log.append(f"🪓 **{n1}** trestá otevřenou pozici — **CRUSH! {raw}** dmg!")
            else:
                log.append(f"⚔️ **{n1}** trestá otevřenou pozici — **{raw}** dmg!")
        elif a1 == "feint":
            raw = _atk(f1); d2 += raw
            log.append(f"🎭 **{n1}** pronáší klam na otevřeného soupeře — **{raw}** dmg!")
        elif a1 == "guard":
            log.append(f"*{n1} zvedá štít — nebylo co blokovat.*")
        elif a1 == "dodge":
            log.append(f"*{n1} uhýbá do strany — {n2} neútočil.*")
        # a1 == "recover": already logged above

    elif not ab1 and not ab2:

        # ── Berserk mode override ─────────────────────────────────────────────
        if f1.berserk > 0 and a1 in ("attack", "heavy", "feint"):
            raw = berserk_attack(f1, f2)
            d2 += raw
            f1.berserk -= 1
            if a2 in ("attack", "heavy"):
                c = _hvy(f2) if a2 == "heavy" else _atk(f2)
                d1 += c
                log.append(f"⚔️ **{n2}** odpovídá na šílenství — **{c}** dmg!")
            elif a2 == "feint":
                c = _atk(f2); d1 += c
                log.append(f"🎭 **{n2}** proklouzne obranou zběsilce — **{c}** dmg!")
            elif a2 == "guard":
                log.append(f"🛡️ **{n2}** zvedá štít — zběsilost proniká skrz! Nelze blokovat.")
            elif a2 == "dodge":
                if f2.cls_name == "Rogue":
                    d2 -= raw
                    free_dmg = round(_atk(f2) * 0.7); d1 += free_dmg
                    log.append(f"💨 **MISS!** **{n2}** *(Stínový krok)* — uhýbá i zběsilosti! Protiúder za **{free_dmg}** dmg!")
                else:
                    log.append(f"💨 **{n2}** se pokouší uhýbat — zběsilost je příliš rychlá.")

        elif f2.berserk > 0 and a2 in ("attack", "heavy", "feint"):
            raw = berserk_attack(f2, f1)
            d1 += raw
            f2.berserk -= 1
            if a1 in ("attack", "heavy"):
                c = _hvy(f1) if a1 == "heavy" else _atk(f1)
                d2 += c
                log.append(f"⚔️ **{n1}** odpovídá na šílenství — **{c}** dmg!")
            elif a1 == "feint":
                c = _atk(f1); d2 += c
                log.append(f"🎭 **{n1}** proklouzne obranou zběsilce — **{c}** dmg!")
            elif a1 == "guard":
                log.append(f"🛡️ **{n1}** zvedá štít — zběsilost proniká skrz! Nelze blokovat.")
            elif a1 == "dodge":
                if f1.cls_name == "Rogue":
                    d1 -= raw
                    free_dmg = round(_atk(f1) * 0.7); d2 += free_dmg
                    log.append(f"💨 **MISS!** **{n1}** *(Stínový krok)* — uhýbá i zběsilosti! Protiúder za **{free_dmg}** dmg!")
                else:
                    log.append(f"💨 **{n1}** se pokouší uhýbat — zběsilost je příliš rychlá.")

        # ── Duelist riposte check ─────────────────────────────────────────────
        elif f1.riposte and a2 in ("attack", "heavy"):
            ctr = round(_riposte_ctr(f1) * 1.5)
            dmg_in = _hvy(f2) if a2 == "heavy" else _atk(f2)
            d1 += round(dmg_in * 0.2)
            d2 += ctr
            f1.riposte = False
            log.append(f"⚡ **{n1}** číhal na tento moment — **RIPOSTE!** Blesk zpět za **{ctr}** dmg!")
            log.append(f"*{n1} pohltí útok — inkasuje jen **{round(dmg_in * 0.2)}** dmg.*")

        elif f1.riposte and a2 == "feint":
            raw = _atk(f2) if f2.cls_name != "Duelist" else round(_atk(f2) / 0.85)
            extra = " *(Přesné oko!)*" if f2.cls_name == "Duelist" else ""
            d1 += raw
            f1.riposte = False
            log.append(f"🎭 **{n2}** pronáší klam — riposte stance propadá! **{raw}** dmg!{extra}")

        elif f2.riposte and a1 in ("attack", "heavy"):
            ctr = round(_riposte_ctr(f2) * 1.5)
            dmg_in = _hvy(f1) if a1 == "heavy" else _atk(f1)
            d2 += round(dmg_in * 0.2)
            d1 += ctr
            f2.riposte = False
            log.append(f"⚡ **{n2}** číhal na tento moment — **RIPOSTE!** Blesk zpět za **{ctr}** dmg!")
            log.append(f"*{n2} pohltí útok — inkasuje jen **{round(dmg_in * 0.2)}** dmg.*")

        elif f2.riposte and a1 == "feint":
            raw = _atk(f1) if f1.cls_name != "Duelist" else round(_atk(f1) / 0.85)
            extra = " *(Přesné oko!)*" if f1.cls_name == "Duelist" else ""
            d2 += raw
            f2.riposte = False
            log.append(f"🎭 **{n1}** pronáší klam — riposte stance propadá! **{raw}** dmg!{extra}")

        # ── Guardian reflect stance ───────────────────────────────────────────
        elif f1.buff_reflect and a2 in ("attack", "heavy", "feint"):
            raw = _hvy(f2) if a2 == "heavy" else _atk(f2)
            tripled = raw * 3
            d2 += tripled
            f1.buff_reflect = False
            f1.reflect_used = True
            log.append(f"⚜️ **{n1}** — **ODVETNÝ ÚDER!** Absorbuje sílu a vrací ji trojnásobně — **{tripled}** dmg! *(3×{raw})*")
            log.append(f"*{n1} stojí bez újmy.*")

        elif f2.buff_reflect and a1 in ("attack", "heavy", "feint"):
            raw = _hvy(f1) if a1 == "heavy" else _atk(f1)
            tripled = raw * 3
            d1 += tripled
            f2.buff_reflect = False
            f2.reflect_used = True
            log.append(f"⚜️ **{n2}** — **ODVETNÝ ÚDER!** Absorbuje sílu a vrací ji trojnásobně — **{tripled}** dmg! *(3×{raw})*")
            log.append(f"*{n2} stojí bez újmy.*")

        # ── Normal matrix ─────────────────────────────────────────────────────

        elif a1 == "recover" and a2 == "recover":
            log.append(random.choice([
                "*Oba si oddechnou. Napětí v aréně stoupá...*",
                "*Krátká přestávka. Aréna drží dech.*",
                "*Oba couvnou. Souboj ještě neskončil.*",
            ]))

        elif a1 == "recover":
            if a2 in ("attack", "heavy", "feint"):
                raw = round((_hvy(f2) if a2 == "heavy" else _atk(f2)) * 1.3)
                d1 += raw
                if a2 == "heavy":
                    log.append(f"💀 **{n2}** trestá recovery těžkým úderem — **CRUSH! {raw}** dmg!")
                else:
                    log.append(f"💀 ⚔️ **{n2}** trestá otevřenou pozici — **{raw}** dmg bez milosti!")
            else:
                log.append(f"*{n2} se drží zpátky.*")

        elif a2 == "recover":
            if a1 in ("attack", "heavy", "feint"):
                raw = round((_hvy(f1) if a1 == "heavy" else _atk(f1)) * 1.3)
                d2 += raw
                if a1 == "heavy":
                    log.append(f"💀 **{n1}** trestá recovery těžkým úderem — **CRUSH! {raw}** dmg!")
                else:
                    log.append(f"💀 ⚔️ **{n1}** trestá otevřenou pozici — **{raw}** dmg bez milosti!")
            else:
                log.append(f"*{n1} se drží zpátky.*")

        elif a1 == "guard" and a2 == "guard":
            log.append(random.choice([
                "🛡️ Oba zvedají štíty — pat. Ticho v aréně.",
                "🛡️ Štít na štít. Nikdo neútočí.",
                "🛡️ Čekání. Oba se brání, nikam nespěchají.",
            ]))

        elif a1 == "guard":
            if a2 == "attack":
                dmg, t = do_guard(f2, f1, _atk(f2)); d1 += dmg; d2 += t
            elif a2 == "heavy":
                dmg, t = do_guard(f2, f1, _hvy(f2), is_heavy=True); d1 += dmg; d2 += t
            elif a2 == "feint":
                raw = _atk(f2) if f2.cls_name != "Duelist" else round(_atk(f2) / 0.85)
                extra = " *(Přesné oko!)*" if f2.cls_name == "Duelist" else ""
                log.append(f"🎭 **{n2}** feintuje — štít brání vzduch! **{raw}** dmg proniká!{extra}")
                d1 += raw
            else:
                log.append(f"*{n2} nezaútočil na štít {n1}.*")

        elif a2 == "guard":
            if a1 == "attack":
                dmg, t = do_guard(f1, f2, _atk(f1)); d2 += dmg; d1 += t
            elif a1 == "heavy":
                dmg, t = do_guard(f1, f2, _hvy(f1), is_heavy=True); d2 += dmg; d1 += t
            elif a1 == "feint":
                raw = _atk(f1) if f1.cls_name != "Duelist" else round(_atk(f1) / 0.85)
                extra = " *(Přesné oko!)*" if f1.cls_name == "Duelist" else ""
                log.append(f"🎭 **{n1}** feintuje — štít brání vzduch! **{raw}** dmg proniká!{extra}")
                d2 += raw
            else:
                log.append(f"*{n1} nezaútočil na štít {n2}.*")

        elif a1 == "dodge" and a2 == "dodge":
            log.append(random.choice([
                "💨 Oba proplují kolem — kroužení. Žádný kontakt.",
                "💨 Tanec stínů. Ani jeden nezaútočil.",
                "💨 Obě postavy se mihotají — bez výsledku.",
            ]))

        elif a1 == "dodge":
            if a2 in ("attack", "heavy"):
                if f1.cls_name == "Rogue":
                    free_dmg = round(_atk(f1) * 0.7)
                    d2 += free_dmg
                    log.append(f"💨 **MISS!** **{n1}** *(Stínový krok)* — mizí v okamžiku útoku! Protiúder za **{free_dmg}** dmg!")
                elif a2 == "heavy":
                    if random.random() < 0.25:
                        free_dmg = round(_atk(f1) * 0.8); d2 += free_dmg
                        log.append(f"💨 **PERFECT DODGE** — **{n1}** mizí z heavy! Protiúder za **{free_dmg}** dmg!")
                    else:
                        log.append(f"💨 **MISS!** **{n1}** vykročí ze dráhy sekyry — heavy mine!")
                else:
                    dmg = round(_atk(f2) * 0.30); d1 += dmg
                    log.append(f"💨 **{n1}** uhýbá — **{dmg}** dmg clippí ramenem.")
            elif a2 == "feint":
                if f1.cls_name == "Rogue":
                    log.append(f"💨 **MISS!** **{n1}** čte feint — mizí beze stopy.")
                else:
                    dmg = round(_atk(f2) * 0.30); d1 += dmg
                    log.append(f"🎭 **{n2}** feintuje — clippí uhýbajícího **{n1}** za **{dmg}** dmg.")
            else:
                log.append(f"*{n1} uhýbá — ale {n2} nezaútočil.*")

        elif a2 == "dodge":
            if a1 in ("attack", "heavy"):
                if f2.cls_name == "Rogue":
                    free_dmg = round(_atk(f2) * 0.7)
                    d1 += free_dmg
                    log.append(f"💨 **MISS!** **{n2}** *(Stínový krok)* — mizí v okamžiku útoku! Protiúder za **{free_dmg}** dmg!")
                elif a1 == "heavy":
                    if random.random() < 0.25:
                        free_dmg = round(_atk(f2) * 0.8); d1 += free_dmg
                        log.append(f"💨 **PERFECT DODGE** — **{n2}** mizí z heavy! Protiúder za **{free_dmg}** dmg!")
                    else:
                        log.append(f"💨 **MISS!** **{n2}** vykročí ze dráhy sekyry — heavy mine!")
                else:
                    dmg = round(_atk(f1) * 0.30); d2 += dmg
                    log.append(f"💨 **{n2}** uhýbá — **{dmg}** dmg clippí ramenem.")
            elif a1 == "feint":
                if f2.cls_name == "Rogue":
                    log.append(f"💨 **MISS!** **{n2}** čte feint — mizí beze stopy.")
                else:
                    dmg = round(_atk(f1) * 0.30); d2 += dmg
                    log.append(f"🎭 **{n1}** feintuje — clippí uhýbajícího **{n2}** za **{dmg}** dmg.")
            else:
                log.append(f"*{n2} uhýbá — ale {n1} nezaútočil.*")

        elif a1 == "feint" and a2 == "feint":
            t1 = _atk(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append(random.choice([
                f"🎭 Oba feintují — oba se přeříznou! **{t2}** / **{t1}** dmg.",
                f"🎭 Klam za klam — ani jeden nepočítal s tímhle. **{t2}** / **{t1}** dmg.",
                f"🎭 Simultánní klam — vzájemný zásah. **{t2}** / **{t1}** dmg.",
            ]))

        elif a1 == "attack" and a2 == "attack":
            t1 = _atk(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append(random.choice([
                f"⚔️ **{n1}** a **{n2}** se vrhají vpřed — čepele se střetají! **{t2}** / **{t1}** dmg.",
                f"⚔️ Střet uprostřed arény — ani jeden necouvl! **{t2}** / **{t1}** dmg.",
                f"⚔️ **{n1}** útočí — **{n2}** odpovídá bez váhání. **{t2}** / **{t1}** dmg.",
                f"⚔️ Ocel na ocel. Oba zasáhnou — **{t2}** / **{t1}** dmg.",
            ]))

        elif a1 == "attack" and a2 == "feint":
            t1 = _atk(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append(random.choice([
                f"⚔️ **{n1}** zaútočí — **{n2}** zároveň prolézá obranou. Oba zasáhnou. **{t2}** / **{t1}** dmg.",
                f"🎭 **{n2}** feintuje, ale **{n1}** se nevzdal útoku — oba inkasují. **{t2}** / **{t1}** dmg.",
            ]))

        elif a1 == "feint" and a2 == "attack":
            t1 = _atk(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append(random.choice([
                f"🎭 **{n1}** feintuje — **{n2}** zároveň prolézá. Oba zasáhnou. **{t2}** / **{t1}** dmg.",
                f"⚔️ **{n2}** zaútočí — **{n1}** feintuje, ale oba si vymění rány. **{t2}** / **{t1}** dmg.",
            ]))

        elif a1 == "heavy" and a2 == "heavy":
            t1 = _hvy(f2); t2 = _hvy(f1)
            d1 += t1; d2 += t2
            log.append(random.choice([
                f"💥 **MASIVNÍ KOLIZE** — oba heavy se střetají! **{t2}** / **{t1}** dmg. Postoje otřeseny.",
                f"💥 Otřes v aréně. Dva heavy dopadají ve stejný okamžik — **{t2}** / **{t1}** dmg.",
                f"💥 Aréna se třese. Žádný necouvnul — **{t2}** / **{t1}** dmg.",
            ]))

        elif a1 == "heavy" and a2 == "attack":
            t1 = _atk(f2); t2 = _hvy(f1)
            d1 += t1; d2 += t2
            log.append(f"⚔️ **{n2}** útočí rychle — **{t1}** dmg. Ale heavy od **{n1}** dopadá — 💥 **CRUSH! {t2}** dmg!")

        elif a1 == "attack" and a2 == "heavy":
            t1 = _hvy(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append(f"⚔️ **{n1}** útočí rychle — **{t2}** dmg. Ale heavy od **{n2}** dopadá — 💥 **CRUSH! {t1}** dmg!")

        elif a1 == "heavy" and a2 == "feint":
            t1 = _atk(f2); t2 = _hvy(f1)
            d1 += t1; d2 += t2
            log.append(f"🎭 **{n2}** proklouzne obranou — **{t1}** dmg. Heavy od **{n1}** přesto dopadá — 💥 **CRUSH! {t2}** dmg!")

        elif a1 == "feint" and a2 == "heavy":
            t1 = _hvy(f2); t2 = _atk(f1)
            d1 += t1; d2 += t2
            log.append(f"🎭 **{n1}** proklouzne obranou — **{t2}** dmg. Heavy od **{n2}** přesto dopadá — 💥 **CRUSH! {t1}** dmg!")

        else:
            log.append("*Boj pokračuje... nikdo nespěchá.*")

    # ── Furioku invest bonus damage ───────────────────────────────────────────
    if a1 in ("attack", "heavy", "feint") and not ab1 and f1.furioku_invest > 0:
        bonus = min(f1.furioku_invest, f1.furioku)
        if bonus > 0:
            f1.furioku -= bonus
            d2 += bonus
            log.append(f"💜 **{n1}** uvolní auru do útoku — **+{bonus}** dmg!")
    if a2 in ("attack", "heavy", "feint") and not ab2 and f2.furioku_invest > 0:
        bonus = min(f2.furioku_invest, f2.furioku)
        if bonus > 0:
            f2.furioku -= bonus
            d1 += bonus
            log.append(f"💜 **{n2}** uvolní auru do útoku — **+{bonus}** dmg!")

    # ── Vampire life steal (15 % of damage dealt on attack/heavy/feint) ─────────
    if f1.cls_name == "Vampire" and d2 > 0 and a1 in ("attack", "heavy", "feint"):
        steal = round(d2 * 0.15)
        if steal > 0:
            f1.hp = min(f1.max_hp, f1.hp + steal)
            log.append(f"🩸 **{n1}** nasaje trochu síly — **+{steal} HP**!")
    if f2.cls_name == "Vampire" and d1 > 0 and a2 in ("attack", "heavy", "feint"):
        steal = round(d1 * 0.15)
        if steal > 0:
            f2.hp = min(f2.max_hp, f2.hp + steal)
            log.append(f"🩸 **{n2}** nasaje trochu síly — **+{steal} HP**!")

    # ── Gladiator heavy BLEED proc (50 %) ────────────────────────────────────
    if a1 == "heavy" and f1.cls_name == "Gladiator" and d2 > 0 and random.random() < 0.50:
        log.append(_apply_status(f2, "bleed", 1))
    if a2 == "heavy" and f2.cls_name == "Gladiator" and d1 > 0 and random.random() < 0.50:
        log.append(_apply_status(f1, "bleed", 1))

    # ── Feint CONFUSION proc (25 %) ───────────────────────────────────────────
    if a1 == "feint" and d2 > 0 and random.random() < 0.25:
        log.append(_apply_status(f2, "confusion", 1))
    if a2 == "feint" and d1 > 0 and random.random() < 0.25:
        log.append(_apply_status(f1, "confusion", 1))

    # ── Warlock curse bonus on offensive attacks ──────────────────────────────
    if a1 in ("attack", "heavy", "feint") and f1.cls_name == "Warlock" and d2 > 0 and f1.curse_stacks > 0:
        bonus = f1.curse_stacks * 5
        d2 += bonus
        log.append(f"🔮 **{n1}** — Prokletí posiluje! **+{bonus} dmg** (kletba ×{f1.curse_stacks})")
    if a2 in ("attack", "heavy", "feint") and f2.cls_name == "Warlock" and d1 > 0 and f2.curse_stacks > 0:
        bonus = f2.curse_stacks * 5
        d1 += bonus
        log.append(f"🔮 **{n2}** — Prokletí posiluje! **+{bonus} dmg** (kletba ×{f2.curse_stacks})")

    # uložit dmg před absorbcemi pro Warlock curse akumulaci
    orig_d1, orig_d2 = d1, d2

    # ── Physical shield absorbs damage first (Guardian) ─────────────────────
    if d1 > 0 and f1.shield_hp > 0:
        absorbed = min(f1.shield_hp, d1)
        f1.shield_hp -= absorbed
        d1 -= absorbed
        rem = f" (zbývá {f1.shield_hp})" if f1.shield_hp > 0 else " — **štít prolomem!**"
        log.append(f"🛡️ **{n1}** — Železný hrad pohlcuje **{absorbed}** dmg!{rem}")
    if d2 > 0 and f2.shield_hp > 0:
        absorbed = min(f2.shield_hp, d2)
        f2.shield_hp -= absorbed
        d2 -= absorbed
        rem = f" (zbývá {f2.shield_hp})" if f2.shield_hp > 0 else " — **štít prolomen!**"
        log.append(f"🛡️ **{n2}** — Železný hrad pohlcuje **{absorbed}** dmg!{rem}")

    # ── Furioku shield absorbs damage before HP ───────────────────────────────
    if d1 > 0 and f1.furioku > 0 and f1.furioku_shield:
        absorbed = min(f1.furioku, d1)
        f1.furioku -= absorbed
        d1 -= absorbed
        if absorbed > 0:
            log.append(f"💜 Aura **{n1}** pohltí **{absorbed}** dmg! (furioku: {max(0, f1.furioku)}/{f1.max_furioku})")
    if d2 > 0 and f2.furioku > 0 and f2.furioku_shield:
        absorbed = min(f2.furioku, d2)
        f2.furioku -= absorbed
        d2 -= absorbed
        if absorbed > 0:
            log.append(f"💜 Aura **{n2}** pohltí **{absorbed}** dmg! (furioku: {max(0, f2.furioku)}/{f2.max_furioku})")

    # ── Apply damage ──────────────────────────────────────────────────────────

    f1.hp -= d1
    f2.hp -= d2

    # Sleep break on damage
    if d1 > 0 and "sleep" in f1.statuses:
        del f1.statuses["sleep"]
        log.append(f"😤 **{n1}** se probouzí bolestí!")
    if d2 > 0 and "sleep" in f2.statuses:
        del f2.statuses["sleep"]
        log.append(f"😤 **{n2}** se probouzí bolestí!")

    # ── Warlock curse accumulation ────────────────────────────────────────────
    if f1.cls_name == "Warlock" and orig_d1 > 0 and f1.curse_stacks < 3:
        f1.curse_stacks += 1
        log.append(f"🔮 **{n1}** — Krvavý pakt zesiluje! Kletba ×{f1.curse_stacks}")
    if f2.cls_name == "Warlock" and orig_d2 > 0 and f2.curse_stacks < 3:
        f2.curse_stacks += 1
        log.append(f"🔮 **{n2}** — Krvavý pakt zesiluje! Kletba ×{f2.curse_stacks}")

    if not log:
        log.append("*Ticho. Nikdo se nehýbá.*")

    # ── Critical state atmospheric log ────────────────────────────────────────
    if d1 > 0 and f1.critical:
        line = _critical_line(f1)
        if line: log.append(line)
    if d2 > 0 and f2.critical:
        line = _critical_line(f2)
        if line: log.append(line)

    # ── Ult charge ────────────────────────────────────────────────────────────
    atk_acts = ("attack", "heavy", "feint")
    if a1 in atk_acts and d2 > 0:
        f1.ult_charge = min(CLASSES[f1.cls_name]["ult_charge_max"], f1.ult_charge + 1)
    if a2 in atk_acts and d1 > 0:
        f2.ult_charge = min(CLASSES[f2.cls_name]["ult_charge_max"], f2.ult_charge + 1)
    if a1 == "basic" and f1.cls_name == "Duelist" and d2 > 0:
        f1.ult_charge = min(CLASSES["Duelist"]["ult_charge_max"], f1.ult_charge + 1)
    if a2 == "basic" and f2.cls_name == "Duelist" and d1 > 0:
        f2.ult_charge = min(CLASSES["Duelist"]["ult_charge_max"], f2.ult_charge + 1)

    # ── Reset furioku invest ──────────────────────────────────────────────────
    f1.furioku_invest = 0
    f2.furioku_invest = 0

    # ── Non-DoT status countdown (stun, sleep) ───────────────────────────────
    for f in (f1, f2):
        n = f.member.display_name
        if f.action == "stun":
            for status in ("stun", "sleep"):
                if status in f.statuses:
                    f.statuses[status] -= 1
                    if f.statuses[status] <= 0:
                        del f.statuses[status]
                        e = STATUS_EMOJIS[status]
                        log.append(f"{e} **{n}** — **{STATUS_LABELS[status]}** skončil!")

    # ── Telegraph ─────────────────────────────────────────────────────────────
    state.last_a1 = a1
    state.last_a2 = a2

    f1.action = None
    f2.action = None
    state.round_logs.append((state.round, list(log)))
    if len(state.round_logs) > 5:
        state.round_logs.pop(0)
    return log

# ── Embed builders ────────────────────────────────────────────────────────────

CROWD_LINES = [
    "Dav jásá!", "Aréna zní výkřiky!", "Krev na písku.",
    "Nikdo neopouští svá místa.", "Napětí je hmatatelné.",
    "Aréna drží dech.", "Bouře se schyluje.",
    "Rány duní arénou.", "Ticho před bouří.",
    "Diváci nemrkají.", "Pach krve a prachu.",
    "Tenhle boj nebude krátký.", "Ani jeden se nevzdá.",
    "Aréna tohle neviděla dlouho.",
]

FINISHERS = [
    "padá na kolena — aréna ztichne.",
    "se zhroutí pod posledním úderem.",
    "zakolísá a padá. Hotovo.",
    "je poražen. Aréna exploduje výkřiky!",
    "nemůže vstát. Duel rozhodnut.",
    "klesá k zemi — soupeř stojí.",
    "přijímá porážku. Bez slova.",
    "padá jako strom. Konec.",
    "se složí — bylo to blízko. Ale nestačilo.",
    "leží na písku. Duel skončil.",
    "nevstal. Aréna to potvrzuje potleskem.",
    "se nevzdal — ale jeho tělo rozhodlo za něj.",
]

_ACTION_LABEL: dict[str, str] = {
    "attack": "⚔️ Útok", "heavy": "🪓 Těžký útok", "guard": "🛡️ Štít",
    "feint": "🎭 Klam", "dodge": "💨 Úskok", "recover": "💚 Odpočinek",
    "basic": "✨ Schopnost", "ultimate": "💥 Ult", "furioku_heal": "💜 Fur Heal",
    "hp_potion": "🧪 HP Lektvar", "sta_potion": "⚡ Sta Lektvar",
    "stimulant": "💉 Stimulant", "stun": "💫 Stun",
}

def build_status_embed(state: DuelState, log: list[str] | None = None) -> discord.Embed:
    f1, f2 = state.f1, state.f2
    parts  = [_fighter_bar(f1), "", _fighter_bar(f2)]

    for f in (f1, f2):
        w = _hp_warning(f)
        if w: parts += ["", w]

    if log:
        parts.append("")
        parts.append(f"-# **Kolo {state.round}** — {random.choice(CROWD_LINES)}")
        for line in log:
            parts.append(f"-# {line}")

    if state.last_a1 is not None and state.round > 0:
        l1 = _ACTION_LABEL.get(state.last_a1, state.last_a1)
        l2 = _ACTION_LABEL.get(state.last_a2 or "", state.last_a2 or "?")
        parts.append(f"-# 🕹️ Kolo {state.round}: **{f1.member.display_name}** → {l1}  ·  **{f2.member.display_name}** → {l2}")

    warns = []
    if state.last_a1 == "heavy":
        warns.append(f"⚠️ {f1.member.display_name} se rozmáchá...")
    if state.last_a2 == "heavy":
        warns.append(f"⚠️ {f2.member.display_name} se rozmáchá...")
    if f1.buff_heavy:
        warns.append(f"💢 {f1.member.display_name} nabil úder!")
    if f2.buff_heavy:
        warns.append(f"💢 {f2.member.display_name} nabil úder!")
    for w in warns:
        parts.append(f"-# {w}")

    parts.append("-# Oba hráči volí akci...")

    embed = discord.Embed(
        title=f"⚔️  {f1.member.display_name}  vs  {f2.member.display_name}",
        description="\n".join(parts),
        color=0x1a1a2e,
    )
    footer = f"⭐ Aurionis  ·  Kolo {state.round + 1}"
    if state.bet: footer += f"  ·  Sázka: {state.bet} {minigame_coin()}"
    embed.set_footer(text=footer)
    return embed

def build_intro_embed(state: DuelState) -> discord.Embed:
    f1, f2 = state.f1, state.f2

    def block(f: Fighter) -> str:
        c = CLASSES[f.cls_name]
        return (
            f"{c['emoji']} **{f.member.display_name}** — *{f.cls_name}*\n"
            f"-# 🛡️ {c['passive']}\n"
            f"-# ✨ {c['basic_name']} (CD {c['basic_cd']} kola)  ·  💥 {c['ult_name']} ({c['ult_charge_max']} úderů)\n"
            f"-# _{c['lore']}_"
        )

    desc = (
        f"{block(f1)}\n\n{block(f2)}\n\n"
        f"📨 *Detaily třídy jsem odeslal do DM!*\n"
        f"🎒 Každý hráč začíná s **1× 🧪 HP lektvar**, **1× ⚡ Sta lektvar** a **2× 💉 Stimulant**.\n"
        f"**Oba hráči volí první akci!**"
    )
    embed = discord.Embed(title="⚔️  DUEL ZAČÍNÁ!", description=desc, color=0x1a1a2e)
    if state.bet:
        embed.set_footer(text=f"💰 Sázka: {state.bet} {minigame_coin()} každý  ·  výherce bere vše")
    return embed

def build_finish_embed(winner: Fighter, loser: Fighter, bet: int, log: list[str]) -> discord.Embed:
    wcls  = CLASSES[winner.cls_name]
    parts = [
        f"{wcls['emoji']} **{winner.member.display_name}** stojí jako vítěz!\n",
        f"*{loser.member.display_name} {random.choice(FINISHERS)}*",
    ]
    if bet:
        parts.append(f"\n💰 **{winner.member.display_name}** získává **{bet * 2}** {minigame_coin()}!")
    if log:
        parts.append("")
        for line in log:
            parts.append(f"-# {line}")
    embed = discord.Embed(title="☠️  KONEC DUELU", description="\n".join(parts), color=wcls["color"])
    embed.set_footer(text="⭐ Aurionis")
    return embed

def build_draw_embed(f1: Fighter, f2: Fighter, bet: int, log: list[str]) -> discord.Embed:
    parts = [
        f"*{f1.member.display_name} a {f2.member.display_name} padají ve stejnou chvíli...*\n",
        "Žádný vítěz. Žádný poražený.",
    ]
    if bet:
        parts.append(f"\n💰 Sázky vráceny — **{bet}** {minigame_coin()} každému.")
    if log:
        parts.append("")
        for line in log:
            parts.append(f"-# {line}")
    embed = discord.Embed(title="💀  REMÍZA", description="\n".join(parts), color=0x95A5A6)
    embed.set_footer(text="⭐ Aurionis")
    return embed

# ── DM helper ─────────────────────────────────────────────────────────────────

async def _dm_class_info(fighter: Fighter):
    cls  = CLASSES[fighter.cls_name]
    text = (
        f"## {cls['emoji']} Tvoje třída: **{fighter.cls_name}**\n"
        f"_{cls['lore']}_\n\n"
        f"**HP:** {cls['hp']}  ·  **Stamina:** {cls['stamina']}  ·  **Furioku:** {cls['furioku_max']}  ·  **Dmg:** {cls['dmg_mod']}×\n\n"
        f"**Pasivní schopnost:**\n> {cls['passive']}\n\n"
        f"**✨ {cls['basic_name']}** (cooldown {cls['basic_cd']} kola)\n"
        f"> {cls['basic_desc']}\n\n"
        f"**💥 {cls['ult_name']}** (nabij {cls['ult_charge_max']} úderů)\n"
        f"> {cls['ult_desc']}\n\n"
        f"**🎒 Bag:**\n"
        f"> 🧪 HP lektvar — obnov 45 HP (bere akci)\n"
        f"> ⚡ Sta lektvar — obnov 60 staminy (bere akci)\n"
        f"> 💉 Stimulant ×2 — +20 STA + odstraní VŠECHNY negativní stavy (bere akci)\n\n"
        f"**💜 Furioku** — aura chrání HP. Veškerý příchozí dmg jde nejprve do furioku, pak do HP. Nedoplní se.\n"
        f"**Invest** — +10/−10 tlačítka nastavují, kolik furioku investuješ do příštího útoku (bonus dmg) nebo léčení.\n"
        f"**Klam** ignoruje štít a dává plný dmg."
    )
    try:
        await fighter.member.send(text)
    except Exception:
        pass

# ── Views ─────────────────────────────────────────────────────────────────────

def _intent_content(state: DuelState, fighter: Fighter) -> str:
    cls = CLASSES[fighter.cls_name]
    if fighter.berserk > 0:
        intent = INTENT_BERSERK
    elif fighter.critical:
        intent = INTENT_CRITICAL.get(fighter.cls_name, "")
    else:
        intent = INTENT_TEXT.get(fighter.cls_name, "")

    status_line = ""
    if fighter.statuses:
        parts = [f"{STATUS_EMOJIS.get(s,'?')} **{STATUS_LABELS.get(s,s.upper())}** {r}" for s, r in fighter.statuses.items()]
        status_line = f"\n-# ⚠️ Stavy: {' · '.join(parts)}"

    return (
        f"{intent}\n\n"
        f"**Kolo {state.round + 1}** — Vyber akci!\n"
        f"-# STA: {fighter.stamina}/{fighter.max_sta}  ·  "
        f"FUR: {fighter.furioku}/{fighter.max_furioku}  ·  "
        f"Invest: {fighter.furioku_invest}  ·  "
        f"ULT: {fighter.ult_charge}/{cls['ult_charge_max']}"
        f"{status_line}"
    )


class ActionView(discord.ui.View):
    """Ephemeral — hráč vybírá akci."""

    def __init__(self, state: DuelState, fighter: Fighter, invest: int = 0):
        super().__init__(timeout=300)
        self.state           = state
        self.fighter         = fighter
        self.invest          = invest
        self._invest_confirm: str | None = None
        cls                  = CLASSES[fighter.cls_name]
        berserk      = fighter.berserk > 0

        # ── Row 0: Core combat + tactical ────────────────────────────────────
        row0 = [
            ("attack", discord.ButtonStyle.red,     f"⚔️ Útok  ({STAM_COSTS['attack']} sta · ~{BASE_ATK} dmg)"),
            ("heavy",  discord.ButtonStyle.red,     f"🪓 Těžký útok  ({STAM_COSTS['heavy']} sta · ~{BASE_HEAVY} dmg)"),
            ("guard",  discord.ButtonStyle.green,   f"🛡️ Štít  ({STAM_COSTS['guard']} sta · ~92 % vs light)"),
            ("feint",  discord.ButtonStyle.blurple, f"🎭 Klam  ({STAM_COSTS['feint']} sta · čte obranu)"),
            ("dodge",  discord.ButtonStyle.blurple, f"💨 Úskok  ({STAM_COSTS['dodge']} sta)"),
        ]
        for action, style, label in row0:
            disabled = berserk and action == "guard"
            btn = discord.ui.Button(label=label, style=style, row=0, disabled=disabled)
            btn.callback = self._make_cb(action)
            self.add_item(btn)

        # ── Row 1: Furioku invest controls ────────────────────────────────────
        minus_btn = discord.ui.Button(
            label="−10",
            style=discord.ButtonStyle.grey,
            disabled=invest <= 0,
            row=1,
        )
        minus_btn.callback = self._make_invest_cb(-10)
        self.add_item(minus_btn)

        display_btn = discord.ui.Button(
            label=f"💜 {invest} fur",
            style=discord.ButtonStyle.blurple,
            disabled=True,
            row=1,
        )
        self.add_item(display_btn)

        plus_btn = discord.ui.Button(
            label="+10",
            style=discord.ButtonStyle.grey,
            disabled=invest >= fighter.furioku,
            row=1,
        )
        plus_btn.callback = self._make_invest_cb(10)
        self.add_item(plus_btn)

        fheal_lbl = f"💚 FUR Heal (+{invest} HP)" if invest > 0 else "💚 FUR Heal (invest eerst)"
        fheal_btn = discord.ui.Button(
            label=fheal_lbl,
            style=discord.ButtonStyle.green if invest > 0 else discord.ButtonStyle.grey,
            disabled=invest <= 0,
            row=1,
        )
        fheal_btn.callback = self._make_cb("furioku_heal")
        self.add_item(fheal_btn)

        shield_on = fighter.furioku_shield
        shield_btn = discord.ui.Button(
            label="💜 Štít ZAP" if shield_on else "🖤 Štít VYP",
            style=discord.ButtonStyle.blurple if shield_on else discord.ButtonStyle.grey,
            row=1,
        )
        shield_btn.callback = self._make_shield_toggle_cb()
        self.add_item(shield_btn)

        # ── Row 2: Recover + Special + Bag ───────────────────────────────────
        rec_btn = discord.ui.Button(
            label=f"💚 Odpočinek  (+{cls['recover']} sta)",
            style=discord.ButtonStyle.grey,
            row=2,
        )
        rec_btn.callback = self._make_cb("recover")
        self.add_item(rec_btn)

        cd    = fighter.cooldowns.get("basic", 0)
        b_rdy = cd == 0
        b_lbl = f"✨ {cls['basic_name']}" + (f"  · {cd} kola" if not b_rdy else "")
        b_btn = discord.ui.Button(label=b_lbl, style=discord.ButtonStyle.blurple, disabled=not b_rdy, row=2)
        b_btn.callback = self._make_cb("basic")
        self.add_item(b_btn)

        ult_ready  = fighter.ult_charge >= cls["ult_charge_max"]
        ult_status = "✅ READY" if ult_ready else f"{fighter.ult_charge}/{cls['ult_charge_max']}"
        u_lbl      = f"💥 {cls['ult_name']}  ({ult_status})"
        u_btn      = discord.ui.Button(
            label=u_lbl,
            style=discord.ButtonStyle.red if ult_ready else discord.ButtonStyle.grey,
            disabled=not ult_ready,
            row=2,
        )
        u_btn.callback = self._make_cb("ultimate")
        self.add_item(u_btn)

        hp_n   = fighter.bag.get("hp_potion", 0)
        sta_n  = fighter.bag.get("sta_potion", 0)
        hp_btn = discord.ui.Button(
            label=f"🧪 HP lektvar  ({hp_n}×)",
            style=discord.ButtonStyle.green if hp_n else discord.ButtonStyle.grey,
            disabled=not hp_n,
            row=2,
        )
        hp_btn.callback = self._make_cb("hp_potion")
        self.add_item(hp_btn)

        sta_btn = discord.ui.Button(
            label=f"⚡ Sta lektvar  ({sta_n}×)",
            style=discord.ButtonStyle.blurple if sta_n else discord.ButtonStyle.grey,
            disabled=not sta_n,
            row=2,
        )
        sta_btn.callback = self._make_cb("sta_potion")
        self.add_item(sta_btn)

        # ── Row 3: Stimulant ──────────────────────────────────────────────────
        stim_n  = fighter.bag.get("stimulant", 0)
        neg_act = any(s in fighter.statuses for s in ("bleed", "poison", "burn", "stun", "confusion", "sleep"))
        stim_btn = discord.ui.Button(
            label=f"💉 Stimulant  ({stim_n}×)" + (" ← ⚠️" if neg_act else ""),
            style=(discord.ButtonStyle.green if neg_act else discord.ButtonStyle.blurple) if stim_n else discord.ButtonStyle.grey,
            disabled=not stim_n,
            row=3,
        )
        stim_btn.callback = self._make_cb("stimulant")
        self.add_item(stim_btn)

    def _make_invest_cb(self, delta: int):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.fighter.member.id:
                await interaction.response.send_message("Toto není tvůj souboj!", ephemeral=True)
                return
            if self.fighter.action is not None:
                await interaction.response.send_message("Už jsi vybral!", ephemeral=True)
                return
            if self.state.done:
                await interaction.response.send_message("Duel skončil.", ephemeral=True)
                return
            new_invest = max(0, min(self.fighter.furioku, self.invest + delta))
            await interaction.response.edit_message(
                content=_intent_content(self.state, self.fighter),
                view=ActionView(self.state, self.fighter, invest=new_invest),
            )
        return cb

    def _make_shield_toggle_cb(self):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.fighter.member.id:
                await interaction.response.send_message("Toto není tvůj souboj!", ephemeral=True)
                return
            if self.fighter.action is not None:
                await interaction.response.send_message("Už jsi vybral!", ephemeral=True)
                return
            if self.state.done:
                await interaction.response.send_message("Duel skončil.", ephemeral=True)
                return
            self.fighter.furioku_shield = not self.fighter.furioku_shield
            await interaction.response.edit_message(
                content=_intent_content(self.state, self.fighter),
                view=ActionView(self.state, self.fighter, invest=self.invest),
            )
        return cb

    def _make_cb(self, action: str):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.fighter.member.id:
                await interaction.response.send_message("Toto není tvůj souboj!", ephemeral=True)
                return
            if self.fighter.action is not None:
                await interaction.response.send_message("Už jsi vybral!", ephemeral=True)
                return
            if self.state.done:
                await interaction.response.send_message("Duel skončil.", ephemeral=True)
                return
            if self.fighter.exhausted and action not in ("recover", "guard", "basic", "ultimate", "hp_potion", "sta_potion", "furioku_heal", "stimulant"):
                await interaction.response.edit_message(
                    content=f"⚠️ **Vyčerpán!** Použij 💚 Odpočinek nebo 🛡️ Štít.\n-# STA: {self.fighter.stamina}/{self.fighter.max_sta}",
                    view=self,
                )
                return

            if self.invest > 0 and action in ("basic", "ultimate", "hp_potion", "sta_potion") and self._invest_confirm != action:
                self._invest_confirm = action
                await interaction.response.edit_message(
                    content=f"⚠️ Máš **{self.invest} fur** investovaný — tato akce ho zahodí bez efektu.\nKlikni znovu pro potvrzení.",
                    view=self,
                )
                return

            self.fighter.furioku_invest = self.invest
            self.fighter.action = action
            self.stop()

            cls = CLASSES[self.fighter.cls_name]
            label_map = {
                "attack": "Útok", "heavy": "Těžký útok", "guard": "Štít",
                "feint": "Klam", "dodge": "Úskok", "recover": "Odpočinek",
                "hp_potion": "HP lektvar", "sta_potion": "Sta lektvar",
                "furioku_heal": "Furioku Léčení",
                "stimulant": "Stimulant",
                "basic": cls["basic_name"], "ultimate": cls["ult_name"],
            }
            label = label_map.get(action, action)

            await interaction.response.edit_message(
                content=f"✅ **{label}** — čekám na soupeře...",
                view=None,
            )
            await _try_resolve(self.state)
        return cb

    async def on_timeout(self):
        if self.fighter.action is None and not self.state.done:
            self.fighter.action = "recover"
            try:
                await self.state.channel.send(
                    f"-# ⏰ {self.fighter.member.mention} nevybral akci včas — automatický **Odpočinek**.",
                )
            except Exception:
                pass
            await _try_resolve(self.state)


class ArenaView(discord.ui.View):
    def __init__(self, state: DuelState):
        super().__init__(timeout=600)
        self.state = state

        b1 = discord.ui.Button(label=f"⚔️ {state.f1.member.display_name}", style=discord.ButtonStyle.red)
        b2 = discord.ui.Button(label=f"⚔️ {state.f2.member.display_name}", style=discord.ButtonStyle.blurple)
        b1.callback = self._make_choose(state.f1)
        b2.callback = self._make_choose(state.f2)
        self.add_item(b1)
        self.add_item(b2)

        hist = discord.ui.Button(label="📜 Historie", style=discord.ButtonStyle.grey)
        hist.callback = self._history_cb
        self.add_item(hist)

    def _make_choose(self, fighter: Fighter):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != fighter.member.id:
                await interaction.response.send_message("Toto není tvůj souboj!", ephemeral=True)
                return
            if self.state.done:
                await interaction.response.send_message("Duel skončil.", ephemeral=True)
                return
            if fighter.action is not None:
                await interaction.response.send_message("✅ Akce vybrána. Čekáš na soupeře...", ephemeral=True)
                return
            if fighter.statuses.get("stun", 0) > 0:
                fighter.action = "stun"
                await interaction.response.send_message(
                    f"💫 **STUN!** Jsi omráčen — toto kolo přeskakuješ.", ephemeral=True
                )
                await _try_resolve(self.state)
                return
            if fighter.statuses.get("sleep", 0) > 0:
                fighter.action = "stun"
                await interaction.response.send_message(
                    f"💤 **SLEEP!** Spíš — toto kolo přeskakuješ.", ephemeral=True
                )
                await _try_resolve(self.state)
                return
            await interaction.response.send_message(
                content=_intent_content(self.state, fighter),
                view=ActionView(self.state, fighter),
                ephemeral=True,
            )
        return cb

    async def _history_cb(self, interaction: discord.Interaction):
        logs = self.state.round_logs
        if not logs:
            await interaction.response.send_message("-# Zatím žádná kola.", ephemeral=True)
            return
        parts = []
        for rnd, lines in logs[-3:]:
            parts.append(f"**— Kolo {rnd} —**")
            parts += [f"-# {l}" for l in lines]
            parts.append("")
        text = "\n".join(parts).strip()
        if len(text) > 1900:
            text = text[-1900:]
        await interaction.response.send_message(text, ephemeral=True)

    async def on_timeout(self):
        if not self.state.done:
            bet  = self.state.bet
            f1n  = self.state.f1.member.display_name
            f2n  = self.state.f2.member.display_name
            if bet > 0:
                async with _eco_lock:
                    eco = load_json(minigame_file(), {})
                    for f in (self.state.f1, self.state.f2):
                        uid = str(f.member.id)
                        eco[uid] = eco.get(uid, 0) + bet
                    save_json(minigame_file(), eco)
            _cleanup(self.state)
            try:
                bet_note = " Sázky vráceny." if bet > 0 else ""
                await self.state.channel.send(
                    f"⏱️ Duel **{f1n}** vs **{f2n}** byl ukončen z důvodu nečinnosti.{bet_note}"
                )
            except Exception:
                pass


# ── Rematch ───────────────────────────────────────────────────────────────────

class RematchView(discord.ui.View):
    def __init__(self, f1: Fighter, f2: Fighter, bet: int,
                 channel: discord.TextChannel, round_logs: list | None = None):
        super().__init__(timeout=60)
        self.f1         = f1
        self.f2         = f2
        self.bet        = bet
        self.channel    = channel
        self.round_logs = round_logs or []
        self._requester: int | None = None
        self._done      = False

        btn = discord.ui.Button(label="🔁 Rematch", style=discord.ButtonStyle.blurple)
        btn.callback = self._on_click
        self.add_item(btn)

        if self.round_logs:
            hist = discord.ui.Button(label="📜 Historie", style=discord.ButtonStyle.grey)
            hist.callback = self._history_cb
            self.add_item(hist)

    async def _history_cb(self, interaction: discord.Interaction):
        parts = []
        for rnd, lines in self.round_logs[-5:]:
            parts.append(f"**— Kolo {rnd} —**")
            parts += [f"-# {l}" for l in lines]
            parts.append("")
        text = "\n".join(parts).strip()
        if len(text) > 1900:
            text = text[-1900:]
        await interaction.response.send_message(text, ephemeral=True)

    async def _on_click(self, interaction: discord.Interaction):
        if interaction.user.id not in (self.f1.member.id, self.f2.member.id):
            await interaction.response.send_message("Nejsi účastník tohoto duelu.", ephemeral=True)
            return
        if self._done:
            await interaction.response.send_message("Rematch již zahájen.", ephemeral=True)
            return

        if self._requester is None:
            self._requester = interaction.user.id
            other = self.f2.member if interaction.user.id == self.f1.member.id else self.f1.member
            for item in self.children:
                item.disabled = True
            accept_btn = discord.ui.Button(label="✅ Přijmout rematch", style=discord.ButtonStyle.green)
            accept_btn.callback = self._on_accept
            self.add_item(accept_btn)
            await interaction.response.edit_message(
                content=f"🔁 **{interaction.user.display_name}** chce rematch! {other.mention}, přijmout?",
                view=self,
            )
        elif interaction.user.id == self._requester:
            await interaction.response.send_message("Čekáš na odpověď soupeře.", ephemeral=True)
        else:
            await self._launch(interaction)

    async def _on_accept(self, interaction: discord.Interaction):
        if interaction.user.id not in (self.f1.member.id, self.f2.member.id):
            await interaction.response.send_message("Nejsi účastník tohoto duelu.", ephemeral=True)
            return
        if interaction.user.id == self._requester:
            await interaction.response.send_message("Ty jsi rematch vyžádal — čekáš na soupeře.", ephemeral=True)
            return
        await self._launch(interaction)

    async def _launch(self, interaction: discord.Interaction):
        if self._done:
            return
        self._done = True
        self.stop()

        for ftr in (self.f1, self.f2):
            if ftr.member.id in _active or ftr.member.id in _pending:
                self._done = False
                await interaction.response.edit_message(content="❌ Jeden z hráčů je již v jiném duelu.", view=None)
                return

        if self.bet > 0:
            eco   = load_json(minigame_file(), {})
            c_bal = eco.get(str(self.f1.member.id), 0)
            t_bal = eco.get(str(self.f2.member.id), 0)
            if c_bal < self.bet:
                self._done = False
                await interaction.response.edit_message(
                    content=f"❌ **{self.f1.member.display_name}** nemá dost!", view=None
                )
                return
            if t_bal < self.bet:
                self._done = False
                await interaction.response.edit_message(
                    content=f"❌ **{self.f2.member.display_name}** nemá dost!", view=None
                )
                return
            eco[str(self.f1.member.id)] = c_bal - self.bet
            eco[str(self.f2.member.id)] = t_bal - self.bet
            save_json(minigame_file(), eco)

        pg = PreGame(self.f1.member, self.f2.member, self.bet, self.channel)
        _pending.add(self.f1.member.id)
        _pending.add(self.f2.member.id)
        picker_view = ClassPickerPublicView(pg)
        await interaction.response.edit_message(content=None, embed=_picker_embed(pg), view=picker_view)
        pg.picker_msg = interaction.message


class PreGame:
    """Přechodný stav — oba hráči vybírají třídu před začátkem duelu."""
    def __init__(self, challenger: discord.Member, target: discord.Member,
                 bet: int, channel: discord.TextChannel):
        self.challenger = challenger
        self.target     = target
        self.bet        = bet
        self.channel    = channel
        self.choices: dict[int, str | None] = {challenger.id: None, target.id: None}
        self.picker_msg: discord.Message | None = None
        self.started    = False
        self._lock      = asyncio.Lock()


def _build_class_overview_embed() -> discord.Embed:
    lines = []
    for name, c in CLASSES.items():
        lines.append(
            f"{c['emoji']} **{name}** — HP {c['hp']} · STA {c['stamina']} · FUR {c['furioku_max']}\n"
            f"-# ✨ {c['basic_name']}: {c['basic_desc']}  ·  💥 {c['ult_name']}: {c['ult_desc']}\n"
            f"-# _{c['lore']}_"
        )
    embed = discord.Embed(
        title="⚔️  Výběr třídy — přehled",
        description="\n\n".join(lines),
        color=0x1a1a2e,
    )
    embed.set_footer(text="Podrobnosti třídy přijdou do DM po startu duelu.")
    return embed


def _picker_embed(pg: PreGame) -> discord.Embed:
    def status(mid: int) -> str:
        if pg.choices.get(mid):
            return "✅ vybráno"
        return "*vybírá...*"

    c_stat = status(pg.challenger.id)
    t_stat = status(pg.target.id)
    both   = all(v is not None for v in pg.choices.values())
    footer = "-# Obě volby dokončeny — souboj začíná!" if both else "-# Klikni na své jméno a zvol třídu."

    desc = (
        f"**{pg.challenger.mention}** — {c_stat}\n"
        f"**{pg.target.mention}** — {t_stat}\n\n"
        f"{footer}"
    )
    embed = discord.Embed(title="⚔️  Výběr třídy", description=desc, color=0x1a1a2e)
    embed.set_footer(text="⭐ Aurionis")
    return embed


async def _start_duel_from_pregame(pg: PreGame):
    _pending.discard(pg.challenger.id)
    _pending.discard(pg.target.id)

    cls1 = pg.choices[pg.challenger.id]
    cls2 = pg.choices[pg.target.id]
    f1   = Fighter(pg.challenger, cls1)
    f2   = Fighter(pg.target,     cls2)
    state = DuelState(f1, f2, pg.bet, pg.channel)
    _register(state)

    if pg.picker_msg:
        try:
            await pg.picker_msg.edit(embed=_picker_embed(pg), view=None)
        except Exception:
            pass

    await pg.channel.send(embed=build_intro_embed(state))
    state.arena_msg = await pg.channel.send(embed=build_status_embed(state), view=ArenaView(state))
    await asyncio.gather(_dm_class_info(f1), _dm_class_info(f2), return_exceptions=True)


class ClassSelectView(discord.ui.View):
    """Ephemeral — hráč vybírá svou třídu z tlačítek."""

    def __init__(self, pg: PreGame, member: discord.Member):
        super().__init__(timeout=120)
        self.pg     = pg
        self.member = member

        for i, (cls_name, cls) in enumerate(CLASSES.items()):
            btn = discord.ui.Button(
                label=f"{cls['emoji']} {cls_name}",
                style=discord.ButtonStyle.blurple,
                row=i // 4,
            )
            btn.callback = self._make_cb(cls_name)
            self.add_item(btn)

    def _make_cb(self, cls_name: str):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.member.id:
                await interaction.response.send_message("Toto není tvůj výběr!", ephemeral=True)
                return
            if self.pg.choices.get(self.member.id) is not None:
                await interaction.response.send_message("Už jsi vybral!", ephemeral=True)
                return

            self.pg.choices[self.member.id] = cls_name
            self.stop()

            cls = CLASSES[cls_name]
            await interaction.response.edit_message(
                content=f"✅ **{cls['emoji']} {cls_name}** vybráno — čekám na soupeře...",
                view=None,
            )

            if self.pg.picker_msg:
                try:
                    new_view = ClassPickerPublicView(self.pg)
                    await self.pg.picker_msg.edit(embed=_picker_embed(self.pg), view=new_view)
                except Exception:
                    pass

            async with self.pg._lock:
                if not self.pg.started and all(v is not None for v in self.pg.choices.values()):
                    self.pg.started = True
                    await _start_duel_from_pregame(self.pg)
        return cb


class ClassPickerPublicView(discord.ui.View):
    """Veřejná — každý hráč má tlačítko pro otevření výběru třídy (ephemeral)."""

    def __init__(self, pg: PreGame):
        super().__init__(timeout=120)
        self.pg = pg

        for member in (pg.challenger, pg.target):
            chosen = pg.choices.get(member.id)
            btn = discord.ui.Button(
                label=f"{'✅' if chosen else '🎭'} {member.display_name}",
                style=discord.ButtonStyle.green if chosen else discord.ButtonStyle.blurple,
                disabled=chosen is not None,
            )
            btn.callback = self._make_cb(member)
            self.add_item(btn)

    def _make_cb(self, member: discord.Member):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != member.id:
                await interaction.response.send_message("Toto není tvůj výběr!", ephemeral=True)
                return
            if self.pg.choices.get(member.id) is not None:
                await interaction.response.send_message("✅ Třídu jsi už vybral!", ephemeral=True)
                return
            await interaction.response.send_message(
                embed=_build_class_overview_embed(),
                view=ClassSelectView(self.pg, member),
                ephemeral=True,
            )
        return cb

    async def on_timeout(self):
        _pending.discard(self.pg.challenger.id)
        _pending.discard(self.pg.target.id)


class ChallengeView(discord.ui.View):
    def __init__(self, challenger: discord.Member, target: discord.Member,
                 bet: int, channel: discord.TextChannel):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.target     = target
        self.bet        = bet
        self.channel    = channel
        self.answered   = False

    @discord.ui.button(label="⚔️ Přijmout", style=discord.ButtonStyle.red)
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("Výzva není pro tebe!", ephemeral=True)
            return
        if self.answered:
            return
        self.answered = True
        self.stop()

        if self.bet > 0:
            async with _eco_lock:
                eco   = load_json(minigame_file(), {})
                c_bal = eco.get(str(self.challenger.id), 0)
                t_bal = eco.get(str(self.target.id), 0)
                if c_bal < self.bet:
                    await interaction.response.edit_message(
                        content=f"❌ **{self.challenger.display_name}** nemá dost!", view=None
                    )
                    return
                if t_bal < self.bet:
                    await interaction.response.edit_message(
                        content=f"❌ **{self.target.display_name}** nemá dost!", view=None
                    )
                    return
                eco[str(self.challenger.id)] = c_bal - self.bet
                eco[str(self.target.id)]     = t_bal - self.bet
                save_json(minigame_file(), eco)

        pg = PreGame(self.challenger, self.target, self.bet, self.channel)
        _pending.add(self.challenger.id)
        _pending.add(self.target.id)

        picker_view = ClassPickerPublicView(pg)
        await interaction.response.edit_message(embed=_picker_embed(pg), view=picker_view)
        pg.picker_msg = interaction.message

    @discord.ui.button(label="🚫 Odmítnout", style=discord.ButtonStyle.grey)
    async def decline(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("Výzva není pro tebe!", ephemeral=True)
            return
        if self.answered:
            return
        self.answered = True
        self.stop()
        await interaction.response.edit_message(
            content=f"🚫 **{self.target.display_name}** odmítl duel.", view=None
        )

    async def on_timeout(self):
        if not self.answered:
            self.answered = True
            try:
                await self.message.edit(
                    content=f"⏱️ Výzva vypršela — **{self.target.display_name}** neodpověděl.", view=None
                )
            except Exception:
                pass

# ── Resolution loop ───────────────────────────────────────────────────────────

async def _check_duel_achievements(member: discord.Member, streak: int, channel):
    checks = [
        ("Křest krví",    streak >= 1),
        ("Neporazitelný", streak >= 10),
    ]
    for name, condition in checks:
        if condition and not has_achievement(member.id, name):
            if grant_achievement(member.id, name):
                await announce_achievement(member, channel, name)

async def _try_resolve(state: DuelState):
    if state.done or not state.both_chose():
        return
    async with state._lock:
        if state.done or not state.both_chose():
            return

        state.round += 1
        log = resolve_round(state)

        f1_dead = state.f1.hp <= 0
        f2_dead = state.f2.hp <= 0

        if state.arena_msg:
            try:
                await state.arena_msg.edit(view=None)
            except Exception:
                pass

        if f1_dead and f2_dead:
            if state.bet > 0:
                async with _eco_lock:
                    eco = load_json(minigame_file(), {})
                    for f in (state.f1, state.f2):
                        eco[str(f.member.id)] = eco.get(str(f.member.id), 0) + state.bet
                    save_json(minigame_file(), eco)
            _cleanup(state)
            await state.channel.send(
                embed=build_draw_embed(state.f1, state.f2, state.bet, log),
                view=RematchView(state.f1, state.f2, state.bet, state.channel, state.round_logs),
            )

        elif f1_dead or f2_dead:
            winner = state.f2 if f1_dead else state.f1
            loser  = state.f1 if f1_dead else state.f2

            if state.bet > 0:
                async with _eco_lock:
                    eco = load_json(minigame_file(), {})
                    wid = str(winner.member.id)
                    eco[wid] = eco.get(wid, 0) + state.bet * 2
                    save_json(minigame_file(), eco)

            streak     = _record_result(winner.member.id, loser.member.id, state.bet)
            round_logs = state.round_logs
            _cleanup(state)
            await state.channel.send(
                embed=build_finish_embed(winner, loser, state.bet, log),
                view=RematchView(winner, loser, state.bet, state.channel, round_logs),
            )
            await _check_duel_achievements(winner.member, streak, state.channel)

        else:
            for f in (state.f1, state.f2):
                if f.statuses.get("stun", 0) > 0 or f.statuses.get("sleep", 0) > 0:
                    f.action = "stun"
            state.arena_msg = await state.channel.send(
                embed=build_status_embed(state, log), view=ArenaView(state)
            )

# ── Cog ───────────────────────────────────────────────────────────────────────

class DuelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    duel_group = app_commands.Group(name="duel", description="Tahová PvP aréna")

    @duel_group.command(name="challenge", description="Vyzvi hráče na souboj s sázkou!")
    @app_commands.describe(member="Soupeř", bet="Sázka (0 = bez sázky)")
    async def duel_challenge(self, interaction: discord.Interaction,
                             member: discord.Member, bet: int = 0):
        challenger = interaction.user
        if member.id == challenger.id:
            await interaction.response.send_message("Nemůžeš vyzvat sám sebe.", ephemeral=True); return
        if member.bot:
            await interaction.response.send_message("Nemůžeš vyzvat bota.", ephemeral=True); return
        if challenger.id in _active or challenger.id in _pending:
            await interaction.response.send_message("Už jsi v aktivním duelu!", ephemeral=True); return
        if member.id in _active or member.id in _pending:
            await interaction.response.send_message(f"**{member.display_name}** je už v duelu.", ephemeral=True); return
        if bet < 0:
            await interaction.response.send_message("Sázka nesmí být záporná.", ephemeral=True); return
        if bet > 0:
            eco = load_json(minigame_file(), {})
            if eco.get(str(challenger.id), 0) < bet:
                await interaction.response.send_message(
                    f"Nemáš dost! (máš {eco.get(str(challenger.id), 0)} {minigame_coin()})", ephemeral=True
                ); return

        view    = ChallengeView(challenger, member, bet, interaction.channel)
        bet_txt = f" o **{bet}** {minigame_coin()}" if bet else ""
        embed   = discord.Embed(
            title="⚔️  Výzva k duelu!",
            description=(
                f"{challenger.mention} vyzývá {member.mention} na souboj{bet_txt}!\n\n"
                f"-# Každý si zvolí bojovou třídu. Souboj je tahový — mindgames rozhodují.\n"
                f"-# Sázka je stržena při přijetí."
            ),
            color=0xE74C3C,
        )
        embed.set_footer(text="⭐ Aurionis  ·  Výzva vyprší za 60 sekund")
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    @duel_group.command(name="classes", description="Přehled všech bojových tříd")
    async def duel_classes(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚔️  Bojové třídy",
            description="*Každá třída má unikátní pasivní schopnost, útočný styl a ult.*",
            color=0x1a1a2e,
        )
        for cls_name, cls in CLASSES.items():
            embed.add_field(
                name=f"{cls['emoji']} {cls_name}",
                value=(
                    f"-# ❤️ {cls['hp']}  ⚡ {cls['stamina']}  💜 {cls['furioku_max']}  🎯 {cls['dmg_mod']}×\n"
                    f"🛡️ _{cls['passive']}_\n"
                    f"✨ **{cls['basic_name']}** — {cls['basic_desc']}\n"
                    f"💥 **{cls['ult_name']}** — {cls['ult_desc']}"
                ),
                inline=False,
            )
        embed.set_footer(text="⭐ Aurionis  ·  /duel challenge @hráč pro výzvu")
        await interaction.response.send_message(embed=embed, ephemeral=True)



async def setup(bot: commands.Bot):
    await bot.add_cog(DuelCog(bot))