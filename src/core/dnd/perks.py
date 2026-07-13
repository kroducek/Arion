import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import random
import logging
from datetime import date
from typing import Optional

from src.utils.paths import PERKS, PLAYER_PERKS, ODHALENI_POOL as ODHALENI_POOL_FILE
from src.database.characters import pkey
from src.utils.audit import log_action
from src.utils.json_utils import load_json, save_json

logger = logging.getLogger("Perks")

ARION_NAME = "Aurionis"

# ── Skupiny a barvy ───────────────────────────────────────────────────────────

GROUP_ORDER = ["Furioku", "Magie", "Pasivky", "Útočné", "Posilovací", "Rovnováha", "Temnota", "Světlo", "Základní", "Výzbroj", "Unikátní"]
GROUP_EMOJI = {
    "Furioku":    "👻",
    "Magie":      "🔮",
    "Pasivky":    "🛡️",
    "Útočné":     "🗡️",
    "Posilovací": "💪",
    "Rovnováha":  "⚖️",
    "Temnota":    "🌑",
    "Světlo":     "☀️",
    "Základní":   "📚",
    "Výzbroj":    "⚔️",
    "Unikátní":   "⭐",
}
GROUP_COLOR = {
    "Furioku":    0x7B68EE,
    "Magie":      0x9B59B6,
    "Pasivky":    0x95A5A6,
    "Útočné":     0xC0392B,
    "Posilovací": 0xE67E22,
    "Rovnováha":  0x1ABC9C,
    "Temnota":    0x2C2F33,
    "Světlo":     0xFFD700,
    "Základní":   0x5D6D7E,
    "Výzbroj":    0xB7950B,
    "Unikátní":   0xFF6B35,
}

# ── Seed databáze perků ───────────────────────────────────────────────────────
# unique=True   → perk není v náhodném poolu, zobrazí se v sekci Unikátní
# learnable=True → perk není v náhodném poolu, získá se pouze učením (Základní / Výzbroj)

_SEED_PERKS: dict[str, dict] = {
    # ── Furioku ──────────────────────────────────────────────────────────────
    "furioku_promena": {
        "name": "Furioku: Proměna",
        "group": "Furioku",
        "passive": False,
        "unique": False,
        "desc": "Proměníš se v duši, máš přesně dvě použití na den. Jedno na proměnu v duši a jedno na proměnu zpět v člověka.",
        "subdesc": None,
        "cooldown_uses": 2,
        "cooldown_type": "daily",
    },
    "furioku_odhaleni": {
        "name": "Furioku: Odhalení",
        "group": "Furioku",
        "passive": False,
        "unique": False,
        "desc": "Okolo tvé ruky se objeví malí duchové (rarita podle lokace), duchy můžeš následně pohltit či jinak využít.",
        "subdesc": None,
        "cooldown_uses": 2,
        "cooldown_type": "daily",
    },
    "furioku_kombinovany_utok": {
        "name": "Furioku: Kombinovaný útok",
        "group": "Furioku",
        "passive": True,
        "unique": False,
        "desc": "Ty a ten, se kterým útok provádíš, můžete zkombinovat své útoky do jednoho kombinovaného.",
        "subdesc": "Vyžaduje, aby oba vlastnili tento perk.",
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "furioku_zrychleni": {
        "name": "Furioku: Zrychlení",
        "group": "Furioku",
        "passive": True,
        "unique": False,
        "desc": "Ve formě duše se můžeš pohybovat velmi rychle. Ve formě humanoida vyžaduje aktivaci furioku.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "furioku_odrazeni": {
        "name": "Furioku: Odražení",
        "group": "Furioku",
        "passive": True,
        "unique": False,
        "desc": "Pokud je tvá furioku větší než soupeřova, odrazíš ho. Ve formě duše nevyžaduje aktivaci. Odražení nedává dmg, max. následky (fall).",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "furioku_jednota": {
        "name": "Furioku: Jednota",
        "group": "Furioku",
        "passive": True,
        "unique": False,
        "desc": "Ty a Duch, se kterým máš vytvořené pouto, dokážete sjednotit své duše a pracovat v Jednotě.",
        "subdesc": "Furioku se v Jednotě sloučí. Můžeš využívat speciální schopnosti a atributy ducha.",
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "furioku_trhlina": {
        "name": "Furioku: Trhlina",
        "group": "Furioku",
        "passive": False,
        "unique": False,
        "desc": "Multidimenzionální trhlina tě vezme na jedno místo, kam si hra myslí, že chceš nejvíc. Velmi nebezpečné používat.",
        "subdesc": None,
        "cooldown_uses": 1,
        "cooldown_type": "daily",
    },
    "furioku_obrana": {
        "name": "Furioku: Obrana",
        "group": "Furioku",
        "passive": True,
        "unique": False,
        "desc": "Využiješ své furioku jako auru na obranu těla. Funguje jako DEF — vynaložená furioku poskytuje ekvivalentní bonus k obraně.",
        "subdesc": "Využiješ např. 10 furioku → +10 DEF. DMG ničí využívanou furioku.",
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    # ── Magie ─────────────────────────────────────────────────────────────────
    "zprava": {
        "name": "Zpráva",
        "group": "Magie",
        "passive": False,
        "unique": False,
        "desc": "Můžeš poslat magický dopis někomu, s kým máš blízký vztah. Funguje přes celou mapu a osoba ti může odpovědět nazpět.",
        "subdesc": None,
        "cooldown_uses": 1,
        "cooldown_type": "daily",
    },
    "magicke_citeni": {
        "name": "Magické cítění I.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Cítíš přítomnost magie ve svém okolí — její směr, intenzitu a neklid. Hod na WIS při aktivním zaměření.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "mana_sensing_2": {
        "name": "Magické cítění II.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Rozlišíš typ, sílu i zdroj magie ve svém okolí. Hod na WIS s výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "mana_sensing_3": {
        "name": "Magické cítění III.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Vidíš magické proudy jasně a dokážeš je sledovat až ke zdroji. Hod na WIS s dvojitou výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    # ── Pasivky ───────────────────────────────────────────────────────────────
    "instinkt_preziti": {
        "name": "Instinkt přežití",
        "group": "Pasivky",
        "passive": True,
        "unique": False,
        "desc": "Tělo i mysl reagují dřív než rozum. Při odhalování pastí +2 k instincts.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "ohnizdorny": {
        "name": "Ohnivzdorný",
        "group": "Pasivky",
        "passive": True,
        "unique": False,
        "desc": "Oheň ti již nemůže ublížit.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "zabry": {
        "name": "Žábry",
        "group": "Pasivky",
        "passive": True,
        "unique": False,
        "desc": "Magické žábry ti narostou vždy, když budeš pod vodou. Umíš dýchat pod vodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "farmar": {
        "name": "Farmář",
        "group": "Pasivky",
        "passive": True,
        "unique": False,
        "desc": "Země ti přeje. Pokud vlastníš farmu, každá zasazená úroda dozraje během jednoho dne.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    # ── Temnota ───────────────────────────────────────────────────────────────
    "temna_pritomnost": {
        "name": "Temná přítomnost",
        "group": "Temnota",
        "passive": False,
        "unique": False,
        "desc": "Okamžitě ucítíš přítomnost živých bytostí až do kilometru daleko a temnota tě k nim dovede.",
        "subdesc": None,
        "cooldown_uses": 2,
        "cooldown_type": "daily",
    },
    # ── Světlo ────────────────────────────────────────────────────────────────
    "vyslanec_svetla": {
        "name": "Vyslanec světla",
        "group": "Světlo",
        "passive": True,
        "unique": False,
        "desc": "Jsi imunní vůči temnotě — temné útoky tě nezasáhnou, kletby na tebe nefungují.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "pozehani": {
        "name": "Požehnání",
        "group": "Světlo",
        "passive": False,
        "unique": False,
        "desc": "Pokud je den a svítí slunce, můžeš načerpat požehnání od světla. +10 heal HP, +10 heal mana. Zvyšuje jakýkoliv ohnivý DMG o 1d2, pokud jsi požehnán.",
        "subdesc": None,
        "cooldown_uses": 1,
        "cooldown_type": "daily",
    },
    "svetlo_lumeniovo": {
        "name": "Světlo Lumeniovo",
        "group": "Světlo",
        "passive": False,
        "unique": False,
        "desc": "Na pár minut (15–20) vytvoříš levitující kouli světla, která se pohybuje tam, kam ty jdeš, a osvěcuje prostor kolem tebe.",
        "subdesc": None,
        "cooldown_uses": 2,
        "cooldown_type": "daily",
    },
    # ── Základní dovednosti (learnable, nejsou v náhodném poolu) ────────────
    "stealth_1": {
        "name": "Plížení I.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Umíš se tiše plížit. Hod na instincts.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "stealth_2": {
        "name": "Plížení II.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Pohybuješ se rychleji a výrazně tišeji. Hod na instincts s výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "stealth_3": {
        "name": "Plížení III.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistr ticha — dokážeš se pohybovat zcela nehlučně. Hod na instincts s dvojitou výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "stealing_1": {
        "name": "Kapsářství I.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Umíš okrádat lidi přímo za denního světla. Hod na instincts.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "stealing_2": {
        "name": "Kapsářství II.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Zkušenější ruka — krádeže jdou rychleji a nenápadněji. Hod na instincts s výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "stealing_3": {
        "name": "Kapsářství III.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistr kapsářství — dokážeš okrádat i ostražité osoby. Hod na instincts s dvojitou výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "lockpicking_1": {
        "name": "Otevírání zámků I.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Lockpicking mechanika: 5d3 — aspoň tři stejná čísla = úspěch.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "lockpicking_2": {
        "name": "Otevírání zámků II.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Lockpicking mechanika: 6d3 — aspoň tři stejná čísla = úspěch.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "lockpicking_3": {
        "name": "Otevírání zámků III.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Lockpicking mechanika: 7d3 — aspoň tři stejná čísla = úspěch.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "acrobacy_1": {
        "name": "Akrobacie I.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Jsi hbitý a dokážeš ustát pád z výšky či vylézt vysokou stěnu. Hod na DEX.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "acrobacy_2": {
        "name": "Akrobacie II.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Pokročilá hbitost — zvládáš složitější pohybové výzvy. Hod na DEX s výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "acrobacy_3": {
        "name": "Akrobacie III.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistr pohybu — téměř žádný pohybový úkol ti nečiní problém. Hod na DEX s dvojitou výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "blacksmithing_1": {
        "name": "Kovářství I.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Umíš kovat základní předměty a opravovat výstroj. Kovářství mechanika.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "blacksmithing_2": {
        "name": "Kovářství II.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Pokročilé kovářství — dokážeš tvořit kvalitnější zbraně a zbroje.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "blacksmithing_3": {
        "name": "Kovářství III.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistr kovář — tvoříš výjimečné předměty s unikátními vlastnostmi.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "cooking_1": {
        "name": "Vaření I.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Dokážeš vytvořit kvalitnější jídla s lepšími efekty.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "cooking_2": {
        "name": "Vaření II.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Pokročilé vaření — jídla mají silnější bonusy a vydrží déle.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "cooking_3": {
        "name": "Vaření III.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistrovská kuchyně — dokážeš uvařit vzácná jídla s výjimečnými efekty.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "alchemy_1": {
        "name": "Alchymie I.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Dokážeš vytvořit základní lektvary a poznat základní byliny.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "alchemy_2": {
        "name": "Alchymie II.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Pokročilá alchymie — silnější lektvary a rozpoznání vzácnějších bylin.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "alchemy_3": {
        "name": "Alchymie III.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistr alchymie — dokážeš vytvořit unikátní lektvary a jedy.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "animal_handling_1": {
        "name": "Porozumění zvířatům I.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Umíš pracovat se zvířaty. Bonding hod na CHA.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "animal_handling_2": {
        "name": "Porozumění zvířatům II.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Hlubší porozumění — zvládáš i splašená nebo divoká zvířata. Hod na CHA s výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "animal_handling_3": {
        "name": "Porozumění zvířatům III.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistr se zvířaty — dokážeš zkrotit téměř jakékoliv zvíře. Hod na CHA s dvojitou výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "learning_1": {
        "name": "Učení I.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Učíš se rychleji z knih, přednášek a mentorů.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "learning_2": {
        "name": "Učení II.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Pokročilé učení — vstřebuješ znalosti výrazně rychleji než ostatní.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "learning_3": {
        "name": "Učení III.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Fotografická paměť — ovládáš i složité dovednosti za zlomek běžného času.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "bartering_1": {
        "name": "Smlouvání I.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Umíš smlouvat s obchodníky o lepší ceny. Hod na CHA.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "bartering_2": {
        "name": "Smlouvání II.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Pokročilé smlouvání — přesvědčíš i tvrdohlavé prodejce. Hod na CHA s výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "bartering_3": {
        "name": "Smlouvání III.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistr vyjednávání — dokážeš získat výjimečné ceny a podmínky. Hod na CHA s dvojitou výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "night_vision_1": {
        "name": "Noční zrak I.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Ve tmě vidíš na krátkou vzdálenost jako za šera.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "night_vision_2": {
        "name": "Noční zrak II.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Ve tmě vidíš jasně až na střední vzdálenost.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "night_vision_3": {
        "name": "Noční zrak III.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Ve tmě vidíš téměř stejně jako za dne na velkou vzdálenost.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "tracking_1": {
        "name": "Stopování I.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Dokážeš stopovat cíl v přírodě. Hod na instincts.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "tracking_2": {
        "name": "Stopování II.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Rozpoznáš i starší stopy a dokážeš stopovat v obtížném terénu. Hod na instincts s výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "tracking_3": {
        "name": "Stopování III.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistr stopař — dokážeš sledovat téměř jakoukoliv stopu. Hod na instincts s dvojitou výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "survival_1": {
        "name": "Přežití I.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Dokážeš přežít v divočině — najít jídlo, vodu a přístřeší. Hod na instincts.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "survival_2": {
        "name": "Přežití II.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Zkušený přeživší — zvládáš i nehostinné podmínky. Hod na instincts s výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "survival_3": {
        "name": "Přežití III.",
        "group": "Základní",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistr přežití — divočina je tvůj domov. Hod na instincts s dvojitou výhodou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    # ── Výzbroj (potřebné pro use itemů, learnable) ───────────────────────────
    "strelba_1": {
        "unlocks_skill": {"id": "strelba", "name": "Střelba", "gives": None},
        "name": "Boj se střelnými zbraněmi I.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Potřebný perk pro použití střelných zbraní (luky, kuše, pušky).",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "crossbow_1": {
        "unlocks_skill": {"id": "strelba", "name": "Střelba", "gives": None},
        "name": "Boj s kuší I.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Potřebný perk pro použití kuší.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "dual_wielding": {
        "name": "Boj se dvěma zbraněmi I.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": False,
        "sp_cost": 1,
        "desc": "Otevření slotu druhá pomocná ruka.",
        "subdesc": ("Jednoruční zbraň nyní nemusíš držet v obouch rukách. Ve své druhé ruce "
                    "můžeš držet — dýku, štít, louč, lampu atd."),
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "dual_wielding_2": {
        "name": "Boj se dvěma zbraněmi II.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": False,
        "sp_cost": 5,
        "desc": "Otevření slotu druhá vedlejší ruka.",
        "subdesc": ("Nyní můžeš v obou rukách držet cokoliv, co není obouruční zbraň nebo předmět, "
                    "který bys musel držet obouma rukama. Můžeš mít v rukou například dva meče, "
                    "meč a katanu, dvě jednoruční kuše atd."),
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "dual_wielding_3": {
        "name": "Boj se dvěma zbraněmi III.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": False,
        "sp_cost": 20,
        "desc": "Otevření slotu druhá hlavní ruka.",
        "subdesc": ("Dosáhl jsi téměř vrcholu boje se dvěma zbraněmi. Dokážeš držet dvě obouruční "
                    "zbraně. (Výjimka — luky)"),
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "one_handed_1": {
        "unlocks_skill": {"id": "lehke_zbrane", "name": "Lehké zbraně", "gives": None},
        "name": "Boj s jednoručními zbraněmi I.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Potřebný perk pro použití jednoručních zbraní.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "one_handed_2": {
        "name": "Boj s jednoručními zbraněmi II.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Pokročilé ovládání jednoručních zbraní. Bonus k útočným hodům.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "one_handed_3": {
        "name": "Boj s jednoručními zbraněmi III.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistrné ovládání jednoručních zbraní. Vyšší bonus k útočným hodům.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "two_handed_1": {
        "unlocks_skill": {"id": "tezke_zbrane", "name": "Těžké zbraně", "gives": None},
        "name": "Boj s obouručními zbraněmi I.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Potřebný perk pro použití obouručních zbraní.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "two_handed_2": {
        "name": "Boj s obouručními zbraněmi II.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Pokročilé ovládání obouručních zbraní. Bonus k útočným hodům.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "two_handed_3": {
        "name": "Boj s obouručními zbraněmi III.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistrné ovládání obouručních zbraní. Vyšší bonus k útočným hodům.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "light_armor_1": {
        "unlocks_skill": {"id": "lehka_zbroj", "name": "Lehká zbroj", "gives": None},
        "name": "Lehké brnění I.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Potřebný perk pro nošení lehkého brnění.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "light_armor_2": {
        "name": "Lehké brnění II.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Pohyb v lehkém brnění je přirozený. Malý bonus k DEF.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "light_armor_3": {
        "name": "Lehké brnění III.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistrné nošení lehkého brnění. Vyšší bonus k DEF.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "heavy_armor_1": {
        "unlocks_skill": {"id": "tezka_zbroj", "name": "Těžká zbroj", "gives": None},
        "name": "Těžké brnění I.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Potřebný perk pro nošení těžkého brnění.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "heavy_armor_2": {
        "name": "Těžké brnění II.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Pohyb v těžkém brnění je přirozený. Malý bonus k DEF.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "heavy_armor_3": {
        "name": "Těžké brnění III.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistrné nošení těžkého brnění. Vyšší bonus k DEF.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "dual_wielding_1": {
        "name": "Boj dvěma zbraněmi I.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Potřebný perk pro boj dvěma zbraněmi zároveň.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "dual_wielding_2": {
        "name": "Boj dvěma zbraněmi II.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Pokročilý boj dvěma zbraněmi. Snížení penalizace k útokům.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "dual_wielding_3": {
        "name": "Boj dvěma zbraněmi III.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistrné ovládání dvou zbraní. Žádná penalizace k útokům.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "archery_1": {
        "unlocks_skill": {"id": "strelba", "name": "Střelba", "gives": None},
        "name": "Lukostřelba I.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Potřebný perk pro použití luků.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "archery_2": {
        "name": "Lukostřelba II.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Pokročilá lukostřelba. Bonus k útočným hodům.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "archery_3": {
        "name": "Lukostřelba III.",
        "group": "Výzbroj",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Mistrná lukostřelba. Vyšší bonus k útočným hodům.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "rune_basics_1": {
        "name": "Základy run I.",
        "group": "Magie",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Základní ovládání runové magie — hůlky a svitky.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "fire_magic_1": {
        "name": "Ohnivá magie I.",
        "group": "Magie",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Základní ovládání ohnivé magie. Umíš sesílat jednoduché ognivé kouzla.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "ice_magic_1": {
        "name": "Ledová magie I.",
        "group": "Magie",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Základní ovládání ledové magie. Umíš sesílat jednoduché mrazivé kouzla.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "healing_magic_1": {
        "name": "Uzdravovací magie I.",
        "group": "Magie",
        "passive": True,
        "unique": False,
        "learnable": True,
        "desc": "Základní ovládání uzdravovací magie. Umíš léčit zranění svou manou.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    # ── Unikátní (nejsou v náhodném poolu) ───────────────────────────────────
    "restart": {
        "name": "Restart",
        "group": "Unikátní",
        "passive": True,
        "unique": True,
        "desc": "Pokud zemřeš, Noxarath tě oživí a objevíš se na náhodném místě. Ztratíš část XP a sanity.",
        "subdesc": None,
        "cooldown_uses": 0,
        "cooldown_type": None,
    },
    "vahy_spravedlnosti": {
        "name": "Váhy spravedlnosti",
        "group": "Unikátní",
        "passive": False,
        "unique": True,
        "desc": "Nad nepřítelem vytvoříš magické váhy, které ho soudí za jeho činy.",
        "subdesc": None,
        "cooldown_uses": 2,
        "cooldown_type": "daily",
    },
}

_SYNC_FIELDS = {"name", "group", "passive", "unique", "learnable", "desc", "subdesc", "cooldown_uses", "cooldown_type"}
_LEGACY_IDS  = {"terra", "ignis", "zaklady_bendingu", "vaha_svobody"}

# roll_tags a bonus pro seed perky — aplikují se v migraci
_SEED_ROLL_TAGS: dict[str, list[str]] = {
    "magicke_citeni":  ["WIS"], "mana_sensing_2": ["WIS"], "mana_sensing_3": ["WIS"],
    "stealth_1":       ["INS"], "stealth_2":      ["INS"], "stealth_3":      ["INS"],
    "stealing_1":      ["INS"], "stealing_2":     ["INS"], "stealing_3":     ["INS"],
    "lockpicking_1":   ["INS"], "lockpicking_2":  ["INS"], "lockpicking_3":  ["INS"],
    "acrobacy_1":      ["DEX"], "acrobacy_2":     ["DEX"], "acrobacy_3":     ["DEX"],
    "blacksmithing_1": ["STR"], "blacksmithing_2":["STR"], "blacksmithing_3":["STR"],
    "cooking_1":       ["WIS"], "cooking_2":      ["WIS"], "cooking_3":      ["WIS"],
    "alchemy_1":       ["INT"], "alchemy_2":      ["INT"], "alchemy_3":      ["INT"],
    "animal_handling_1":["CHA"],"animal_handling_2":["CHA"],"animal_handling_3":["CHA"],
    "learning_1":      ["INT"], "learning_2":     ["INT"], "learning_3":     ["INT"],
    "bartering_1":     ["CHA"], "bartering_2":    ["CHA"], "bartering_3":    ["CHA"],
    "night_vision_1":  ["INS"], "night_vision_2": ["INS"], "night_vision_3": ["INS"],
    "tracking_1":      ["INS"], "tracking_2":     ["INS"], "tracking_3":     ["INS"],
    "survival_1":      ["INS"], "survival_2":     ["INS"], "survival_3":     ["INS"],
    "instinkt_preziti":["INS"], "temna_pritomnost":["INS"],
    "one_handed_1":    ["STR"], "one_handed_2":   ["STR"], "one_handed_3":   ["STR"],
    "two_handed_1":    ["STR"], "two_handed_2":   ["STR"], "two_handed_3":   ["STR"],
    "light_armor_1":   ["DEX"], "light_armor_2":  ["DEX"], "light_armor_3":  ["DEX"],
    "heavy_armor_1":   ["STR"], "heavy_armor_2":  ["STR"], "heavy_armor_3":  ["STR"],
    "dual_wielding_1": ["DEX"], "dual_wielding_2":["DEX"], "dual_wielding_3":["DEX"],
    "archery_1":       ["DEX"], "archery_2":      ["DEX"], "archery_3":      ["DEX"],
    "fire_magic_1":    ["INT"], "ice_magic_1":    ["INT"], "healing_magic_1":["WIS"],
}

_SEED_BONUS: dict[str, int] = {
    "magicke_citeni": 1,  "mana_sensing_2": 2,  "mana_sensing_3": 3,
    "stealth_1": 1,       "stealth_2": 2,        "stealth_3": 3,
    "stealing_1": 1,      "stealing_2": 2,       "stealing_3": 3,
    "lockpicking_1": 1,   "lockpicking_2": 2,    "lockpicking_3": 3,
    "acrobacy_1": 1,      "acrobacy_2": 2,       "acrobacy_3": 3,
    "blacksmithing_1": 1, "blacksmithing_2": 2,  "blacksmithing_3": 3,
    "cooking_1": 1,       "cooking_2": 2,        "cooking_3": 3,
    "alchemy_1": 1,       "alchemy_2": 2,        "alchemy_3": 3,
    "animal_handling_1": 1,"animal_handling_2": 2,"animal_handling_3": 3,
    "learning_1": 1,      "learning_2": 2,       "learning_3": 3,
    "bartering_1": 1,     "bartering_2": 2,      "bartering_3": 3,
    "night_vision_1": 1,  "night_vision_2": 2,   "night_vision_3": 3,
    "tracking_1": 1,      "tracking_2": 2,       "tracking_3": 3,
    "survival_1": 1,      "survival_2": 2,       "survival_3": 3,
    "one_handed_1": 1,    "one_handed_2": 2,     "one_handed_3": 3,
    "two_handed_1": 1,    "two_handed_2": 2,     "two_handed_3": 3,
    "light_armor_1": 1,   "light_armor_2": 2,    "light_armor_3": 3,
    "heavy_armor_1": 1,   "heavy_armor_2": 2,    "heavy_armor_3": 3,
    "dual_wielding_1": 1, "dual_wielding_2": 2,  "dual_wielding_3": 3,
    "archery_1": 1,       "archery_2": 2,        "archery_3": 3,
    "fire_magic_1": 1,    "ice_magic_1": 1,      "healing_magic_1": 1,
}

# ── Odhalení loot pool ───────────────────────────────────────────────────────

_DEFAULT_ODHALENI_POOL: list[dict] = [
    {"id": "maly_duch_ohne",     "name": "Malý duch ohně",     "element": "ohen",    "base_fury": 5,  "size": "malý"},
    {"id": "velky_duch_ohne",    "name": "Velký duch ohně",    "element": "ohen",    "base_fury": 10, "size": "velký"},
    {"id": "maly_duch_vody",     "name": "Malý duch vody",     "element": "voda",    "base_fury": 5,  "size": "malý"},
    {"id": "velky_duch_vody",    "name": "Velký duch vody",    "element": "voda",    "base_fury": 10, "size": "velký"},
    {"id": "maly_duch_zeme",     "name": "Malý duch země",     "element": "zeme",    "base_fury": 5,  "size": "malý"},
    {"id": "velky_duch_zeme",    "name": "Velký duch země",    "element": "zeme",    "base_fury": 10, "size": "velký"},
    {"id": "maly_duch_vzduchu",  "name": "Malý duch vzduchu",  "element": "vzduch",  "base_fury": 5,  "size": "malý"},
    {"id": "velky_duch_vzduchu", "name": "Velký duch vzduchu", "element": "vzduch",  "base_fury": 10, "size": "velký"},
    {"id": "maly_duch_svetla",   "name": "Malý duch světla",   "element": "svetlo",  "base_fury": 5,  "size": "malý"},
    {"id": "velky_duch_svetla",  "name": "Velký duch světla",  "element": "svetlo",  "base_fury": 10, "size": "velký"},
    {"id": "maly_duch_temnoty",  "name": "Malý duch temnoty",  "element": "temnota", "base_fury": 5,  "size": "malý"},
    {"id": "velky_duch_temnoty", "name": "Velký duch temnoty", "element": "temnota", "base_fury": 10, "size": "velký"},
]


def load_odhaleni_pool() -> list[dict]:
    """Načte loot pool. Pokud neexistuje, vytvoří výchozí."""
    try:
        data = load_json(ODHALENI_POOL_FILE, default=None)
        if not isinstance(data, list):
            save_json(ODHALENI_POOL_FILE, _DEFAULT_ODHALENI_POOL)
            return list(_DEFAULT_ODHALENI_POOL)
        return data
    except Exception:
        return list(_DEFAULT_ODHALENI_POOL)


def save_odhaleni_pool(pool: list[dict]) -> None:
    save_json(ODHALENI_POOL_FILE, pool)


def _fury_roll_bonus(roll: int) -> int:
    """Bonus furioka za 1d20 — přičítá se k base_fury ducha."""
    if roll == 1:  return 0
    if roll <= 5:  return 2
    if roll <= 10: return 5
    if roll <= 15: return 8
    if roll <= 19: return 12
    return 20  # nat20


# ── Storage ───────────────────────────────────────────────────────────────────

def load_perks() -> dict:
    """Thread-safe load perks database."""
    return load_json(PERKS, default={})

def save_perks(data: dict):
    """Thread-safe save perks database."""
    save_json(PERKS, data)

def _deleted_perks_path():
    try:
        return os.path.join(os.path.dirname(PERKS), "deleted_perks.json")
    except Exception:
        return None

def load_deleted_perks() -> set:
    p = _deleted_perks_path()
    if not p:
        return set()
    try:
        return set(load_json(p, default=[]))
    except Exception:
        return set()

def save_deleted_perks(ids) -> None:
    p = _deleted_perks_path()
    if p:
        save_json(p, sorted(ids))


def load_player_perks() -> dict:
    """Thread-safe load player perks."""
    return load_json(PLAYER_PERKS, default={})

def save_player_perks(data: dict):
    """Thread-safe save player perks."""
    save_json(PLAYER_PERKS, data)

def _get_player(uid_str: str, data: dict) -> dict:
    data.setdefault(uid_str, {"perks": [], "cooldowns": {}, "progress": {}})
    p = data[uid_str]
    p.setdefault("perks", [])
    p.setdefault("cooldowns", {})
    p.setdefault("progress", {})
    return p

async def _check_perk_collector(member, channel, perks_list) -> None:
    """Po přidání perku ověří achievement 'Sběratel schopností' (100+ perků)."""
    try:
        from src.core.dnd.achievements import check_perk_collector_achievement
        await check_perk_collector_achievement(member, channel, len(perks_list))
    except Exception:
        logger.exception("[perks] check achievementu Sběratel schopností selhal")

# ── Level-up helpers ──────────────────────────────────────────────────────────

_NEXT_TIER: dict[str, str] = {
    "magicke_citeni": "mana_sensing_2", "mana_sensing_2": "mana_sensing_3",
    # dual_wielding nemá suffix _1, takže řetěz musí být explicitní
    "dual_wielding": "dual_wielding_2", "dual_wielding_2": "dual_wielding_3",
}

# ── SP upgrady perků (⭐ ve /staty) ────────────────────────────────────────────

# Řetězce perků kupovatelných za SP. Vždy tři tiery: (I, II, III).
SP_PERK_CHAINS: list[tuple[str, str, str]] = [
    ("dual_wielding", "dual_wielding_2", "dual_wielding_3"),
]

def owned_perks(user_id: int) -> list[str]:
    """Perky AKTIVNÍ postavy (pkey), s fallbackem na starý účtový klíč."""
    pp = load_player_perks()
    out: list[str] = []
    try:
        out += list(pp.get(pkey(user_id), {}).get("perks", []))
    except Exception:
        logger.exception(f"[perks] owned_perks: pkey({user_id}) selhal")
    out += list(pp.get(str(user_id), {}).get("perks", []))
    return out

def hand_tier(user_id: int) -> int:
    """Kolikátý tier boje se dvěma zbraněmi hráč má (0 = žádný, 3 = max)."""
    owned = owned_perks(user_id)
    if "dual_wielding_3" in owned:
        return 3
    if "dual_wielding_2" in owned:
        return 2
    if "dual_wielding" in owned:
        return 1
    return 0

def sp_perk_cost(perk_id: str, perks_db: Optional[dict] = None) -> int:
    """SP cena perku (0 = nekupovatelný za SP)."""
    db = perks_db if perks_db is not None else load_perks()
    p  = db.get(perk_id) or _SEED_PERKS.get(perk_id, {})
    try:
        return int(p.get("sp_cost", 0) or 0)
    except (TypeError, ValueError):
        return 0

def next_sp_upgrade(chain: tuple[str, str, str], owned: list[str]) -> Optional[str]:
    """Další tier v řetězci, který si hráč může koupit. None = má už max."""
    for pid in chain:
        if pid not in owned:
            return pid
    return None

def _next_tier_id(perk_id: str) -> str | None:
    if perk_id in _NEXT_TIER:
        return _NEXT_TIER[perk_id]
    for suf, nxt in [("_1", "_2"), ("_2", "_3")]:
        if perk_id.endswith(suf):
            return perk_id[:-2] + nxt
    return None

PROGRESS_MAX = 5

def _progress_bar(used: int, max_: int = PROGRESS_MAX) -> str:
    used = min(used, max_)
    return f"`{'▰' * used}{'▱' * (max_ - used)}` {used}/{max_}"

# ── Migrace ───────────────────────────────────────────────────────────────────

def _load_connections():
    """Načte uložená propojení perků do runtime _NEXT_TIER dict."""
    perks = load_perks()
    for from_id, to_id in perks.get("_connections", {}).items():
        if from_id not in _NEXT_TIER:
            _NEXT_TIER[from_id] = to_id


def _migrate_perks():
    perks   = load_perks()
    changed = False
    for lid in _LEGACY_IDS:
        if lid in perks:
            del perks[lid]
            changed = True
    for pid in list(perks.keys()):
        if pid == "_connections":
            continue  # přeskoč interní klíč
    _deleted = load_deleted_perks()
    for pid, seed in _SEED_PERKS.items():
        if pid not in perks:
            if pid in _deleted:
                continue          # smazaný seed perk — neobnovuj
            perks[pid] = seed
            changed = True
        else:
            for field in _SYNC_FIELDS:
                if perks[pid].get(field) != seed.get(field):
                    perks[pid][field] = seed[field]
                    changed = True
    for pid in perks:
        if not perks[pid].get("roll_tags"):
            perks[pid]["roll_tags"] = _SEED_ROLL_TAGS.get(pid, [])
            changed = True
        seed_bonus = _SEED_BONUS.get(pid, 0)
        if perks[pid].get("bonus", -1) != seed_bonus:
            perks[pid]["bonus"] = seed_bonus
            changed = True
    if changed:
        save_perks(perks)
        print("[perks] Migrace dokončena.")

# ── Cooldown helpers ──────────────────────────────────────────────────────────

def _check_and_use_cooldown(player: dict, perk_id: str, perk: dict) -> tuple[bool, str]:
    today = date.today().isoformat()
    cd    = player["cooldowns"].get(perk_id, {"used": 0, "date": today})
    if cd["date"] != today:
        cd = {"used": 0, "date": today}
    used = cd["used"]
    max_ = perk.get("cooldown_uses", 0)
    if max_ > 0 and used >= max_:
        return False, f"Dnes již použito **{used}/{max_}×**. Reset při půlnoci."
    if max_ > 0:
        cd["used"] = used + 1
        cd["date"] = today
        player["cooldowns"][perk_id] = cd
    return True, ""

def _cooldown_bar(used: int, max_: int) -> str:
    return f"`{'▰' * used}{'▱' * (max_ - used)}` · {used}/{max_}×"

def _cooldown_status(player: dict, perk_id: str, perk: dict) -> str:
    max_ = perk.get("cooldown_uses", 0)
    if max_ == 0:
        return ""
    today = date.today().isoformat()
    cd    = player.get("cooldowns", {}).get(perk_id, {"used": 0, "date": today})
    used  = cd["used"] if cd.get("date") == today else 0
    done  = " ✅" if used >= max_ else ""
    return f"⏳ {_cooldown_bar(used, max_)}{done} dnes"

# ── Announce helpers ──────────────────────────────────────────────────────────

def _perk_announce_embed(member: discord.Member, perk_id: str, perk: dict, used: int) -> discord.Embed:
    group  = perk.get("group", "")
    color  = GROUP_COLOR.get(group, 0xFFD700)
    gemoji = GROUP_EMOJI.get(group, "✨")
    max_   = perk.get("cooldown_uses", 0)

    desc = f"### {gemoji} {perk['name']}\n{perk['desc']}"
    if perk.get("subdesc"):
        desc += f"\n-# {perk['subdesc']}"
    if max_ > 0:
        desc += f"\n\n⏳ {_cooldown_bar(used, max_)} dnes"

    embed = discord.Embed(
        title=f"✨ {member.display_name} aktivoval perk!",
        description=desc,
        color=color,
    )
    embed.set_footer(text=f"⭐ {ARION_NAME}")
    return embed

async def _dm_perk(member: discord.Member, perk: dict, perk_id: str):
    group  = perk.get("group", "")
    gemoji = GROUP_EMOJI.get(group, "✨")
    color  = GROUP_COLOR.get(group, 0xFFD700)
    desc   = f"**{perk['name']}**\n{perk['desc']}"
    if perk.get("subdesc"):
        desc += f"\n-# {perk['subdesc']}"
    max_  = perk.get("cooldown_uses", 0)
    embed = discord.Embed(
        title=f"{gemoji}  Získal/a jsi perk!",
        description=desc,
        color=color,
    )
    if max_ > 0:
        embed.add_field(name="⏳ Cooldown", value=f"{max_}×/den", inline=True)
    embed.set_footer(text=f"⭐ {ARION_NAME}  ·  Použij /perk use k aktivaci")
    try:
        await member.send(embed=embed)
    except discord.Forbidden:
        pass

# ── Modaly ────────────────────────────────────────────────────────────────────

# ── Views ─────────────────────────────────────────────────────────────────────

class PerkListView(discord.ui.View):
    """Stránkovaný seznam perků pro /perks list."""

    def __init__(self, pages: list[tuple[str, str, int]], requester_id: int):
        super().__init__(timeout=120)
        self.pages        = pages
        self.idx          = 0
        self.requester_id = requester_id
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.prev_btn.disabled = (self.idx == 0)
        self.next_btn.disabled = (self.idx == len(self.pages) - 1)

    def build_embed(self) -> discord.Embed:
        group, content, color = self.pages[self.idx]
        # tvrdá pojistka: Discord popis usekne nad 4096 znaků TIŠE — radši ořízneme viditelně
        if len(content) > 4096:
            content = content[:4085].rsplit("\n", 1)[0] + "\n-# …"
        embed = discord.Embed(title=f"📋 Databáze perků — {group}", description=content, color=color)
        embed.set_footer(text=f"Strana {self.idx + 1}/{len(self.pages)}  ·  ⭐ {ARION_NAME}")
        return embed

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary, custom_id="perklist_prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("*Toto není tvůj seznam.*", ephemeral=True)
            return
        self.idx -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary, custom_id="perklist_next")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("*Toto není tvůj seznam.*", ephemeral=True)
            return
        self.idx += 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class OdhaleniRollView(discord.ui.View):
    """Druhý krok Odhalení — hráč hodí 1d20, duch se přidá do kolekce."""

    def __init__(self, uid: str, element: str, spirit_name: str, base_fury: int = 5):
        super().__init__(timeout=60)
        self.uid         = uid
        self.element     = element
        self.spirit_name = spirit_name
        self.base_fury   = base_fury
        self.done        = False

    @discord.ui.button(label="🎲 Hodit 1d20", style=discord.ButtonStyle.primary, custom_id="odhaleni_roll")
    async def roll_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("*Tohle není tvoje aktivace.*", ephemeral=True)
            return
        if self.done:
            return
        self.done = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        roll  = random.randint(1, 20)
        bonus = _fury_roll_bonus(roll)
        fury  = self.base_fury + bonus
        nat20 = (roll == 20)
        nat1  = (roll == 1)

        # Přidej ducha do profilu
        from src.utils.json_utils import load_json, save_json as _sj
        from src.utils.paths import PROFILES as _PF
        import datetime
        data    = load_json(_PF, default={})
        # duch patří AKTIVNÍ postavě (pkey), ne celému účtu (holé uid).
        # self.uid zůstává holé uid jen pro kontrolu identity výše.
        try:
            _pk = pkey(int(self.uid))
        except Exception:
            logger.exception(f"[perks] Odhalení: pkey({self.uid}) selhal — fallback na holé uid")
            _pk = self.uid
        profile = data.setdefault(_pk, {})
        spirits = profile.setdefault("spirits", [])
        try:
            from src.logic.spirits import rank_xp_threshold as _rxt
            xp_thresh = _rxt(1)
        except Exception:
            xp_thresh = 100
        spirits.append({
            "name":         self.spirit_name,
            "rank":         1,
            "fury":         fury,
            "element":      self.element,
            "description":  "Duch zjevený skrze Furioku: Odhalení.",
            "xp":           0,
            "xp_threshold": xp_thresh,
            "total_xp":     0,
            "created_at":   datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        })
        _sj(_PF, data)

        try:
            from src.logic.spirits import ELEMENTS as _EL
            info  = _EL.get(self.element, {})
            emoji = info.get("emoji", "👻")
            color = info.get("color", 0x7B68EE)
        except Exception:
            emoji, color = "👻", 0x7B68EE

        nat_line = ""
        if nat20: nat_line = "\n✨ **NATURAL 20! Duch je výjimečně silný!**"
        elif nat1: nat_line = "\n💀 **Natural 1 — duch je velmi slabý...**"

        embed = discord.Embed(
            title=f"{emoji} {self.spirit_name} byl pohlcen!",
            description=(
                f"Hodil/a jsi **{roll}** na 1d20.{nat_line}\n\n"
                f"🔋 Základní furioka: **{self.base_fury}**\n"
                f"✨ Bonus za hod: **+{bonus}**\n"
                f"💥 Celkem: **{fury} furioku**\n\n"
                f"Duch přidán do tvé kolekce — `/duch-seznam`"
            ),
            color=color,
        )
        await interaction.followup.send(embed=embed)


class OdhaleniView(discord.ui.View):
    """První krok Odhalení — výběr jednoho ze tří duchů z loot poolu."""

    def __init__(self, uid: str, spirits: list[dict]):
        super().__init__(timeout=60)
        self.uid    = uid
        self.chosen = False
        try:
            from src.logic.spirits import ELEMENTS as _EL
        except Exception:
            _EL = {}
        for spirit in spirits:
            element   = spirit["element"]
            name      = spirit["name"]
            base_fury = spirit.get("base_fury", 5)
            size      = spirit.get("size", "")
            emoji     = _EL.get(element, {}).get("emoji", "👻")
            btn = discord.ui.Button(
                label=f"{emoji} {name}",
                style=discord.ButtonStyle.primary,
                custom_id=f"odhaleni_{spirit.get('id', element)}",
            )
            btn.callback = self._make_callback(element, name, base_fury, size)
            self.add_item(btn)

    def _make_callback(self, element: str, name: str, base_fury: int, size: str):
        async def callback(interaction: discord.Interaction):
            if str(interaction.user.id) != self.uid:
                await interaction.response.send_message("*Tohle není tvoje aktivace.*", ephemeral=True)
                return
            if self.chosen:
                return
            self.chosen = True
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(view=self)
            try:
                from src.logic.spirits import ELEMENTS as _EL
                info  = _EL.get(element, {})
                emoji = info.get("emoji", "👻")
                color = info.get("color", 0x7B68EE)
            except Exception:
                emoji, color = "👻", 0x7B68EE
            size_label = f" *({size})*" if size else ""
            embed = discord.Embed(
                title=f"{emoji} Zvolil/a jsi {name}!",
                description=(
                    f"Duch **{name}**{size_label} ({element}) přistoupil blíže.\n\n"
                    f"🔋 Základní furioka: **{base_fury}**\n"
                    f"Hoď 1d20 — bonus se přičte k základní furioku."
                ),
                color=color,
            )
            await interaction.followup.send(
                embed=embed,
                view=OdhaleniRollView(uid=self.uid, element=element, spirit_name=name, base_fury=base_fury),
            )
        return callback


# ── Cog ───────────────────────────────────────────────────────────────────────

class PerksCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _migrate_perks()
        _load_connections()

    # ── /perks skupina ───────────────────────────────────────────────────────

    perks_group = app_commands.Group(name="perks", description="Perky hráčů")

    @perks_group.command(name="show", description="Zobraz perky hráče")
    @app_commands.describe(member="Hráč (výchozí: ty)")
    async def perks_show(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target      = member or interaction.user
        all_perks   = load_perks()
        player_data = load_player_perks()
        player      = _get_player(pkey(target.id), player_data)
        owned       = player["perks"]

        if not owned:
            is_self = target.id == interaction.user.id
            msg = "Nemáš žádné perky." if is_self else f"**{target.display_name}** nemá žádné perky."
            await interaction.response.send_message(msg, ephemeral=True)
            return

        # Roztřiď perky do skupin podle group field — stejné skupiny jako /perk add
        grouped: dict[str, list[tuple[str, dict]]] = {g: [] for g in GROUP_ORDER}
        no_group: list[tuple[str, dict]] = []

        for pid in owned:
            p = all_perks.get(pid)
            if not p or pid == "_connections":
                continue
            grp = p.get("group", "")
            if grp in grouped:
                grouped[grp].append((pid, p))
            else:
                no_group.append((pid, p))

        def fmt_entry(pid: str, p: dict) -> list[str]:
            passive_tag = "  *(pasivní)*" if p.get("passive") else ""
            cd_str      = _cooldown_status(player, pid, p)
            sub_parts: list[str] = []
            if cd_str:
                sub_parts.append(cd_str)
            if p.get("learnable") and _next_tier_id(pid):
                prog = player.get("progress", {}).get(pid, 0)
                sub_parts.append(f"⬆️ {_progress_bar(prog)}")
            sub_parts.append(f"`{pid}`")
            return [
                f"▸ **{p['name']}**{passive_tag}",
                "-# " + "  ·  ".join(sub_parts),
            ]

        # Sestav embed — každá skupina = jeden embed field
        is_self = target.id == interaction.user.id
        title   = "Tvoje perky" if is_self else f"Perky — {target.display_name}"
        color   = 0x7B68EE  # výchozí, přebije se barvou první neprázdné skupiny

        embed = discord.Embed(title=f"🏷️ {title}", color=color)

        first_color_set = False
        for grp in GROUP_ORDER:
            entries = grouped.get(grp, [])
            if not entries:
                continue
            if not first_color_set:
                embed.color = GROUP_COLOR.get(grp, 0x7B68EE)
                first_color_set = True
            gemoji   = GROUP_EMOJI.get(grp, "▸")
            lines: list[str] = []
            for pid, p in entries:
                lines.extend(fmt_entry(pid, p))
            embed.add_field(
                name=f"{gemoji} {grp}",
                value="\n".join(lines),

                inline=False,
            )

        # Perky bez skupiny (fallback)
        if no_group:
            lines = []
            for pid, p in no_group:
                lines.extend(fmt_entry(pid, p))
            embed.add_field(name="❓ Ostatní", value="\n".join(lines), inline=False)


        embed.set_footer(text=f"Celkem perků: {len(owned)}  ·  /perk use — aktivuj perk  ·  ⭐ {ARION_NAME}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @perks_group.command(name="give", description="Přiřaď perk hráči (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(perk_id="ID perku", member="Hráč")
    async def perks_give(self, interaction: discord.Interaction, perk_id: str, member: discord.Member):
        all_perks = load_perks()
        if perk_id not in all_perks:
            await interaction.response.send_message(f"Perk `{perk_id}` neexistuje.", ephemeral=True)
            return
        player_data = load_player_perks()
        player      = _get_player(pkey(member.id), player_data)
        if perk_id in player["perks"]:
            await interaction.response.send_message(
                f"{member.mention} už má **{all_perks[perk_id]['name']}**.", ephemeral=True
            )
            return
        player["perks"].append(perk_id)
        save_player_perks(player_data)
        await _check_perk_collector(member, interaction.channel, player["perks"])
        log_action("perk_give", interaction.user.display_name, member.display_name, perk_id)

        perk   = all_perks[perk_id]
        await _dm_perk(member, perk, perk_id)

        group  = perk.get("group", "")
        gemoji = GROUP_EMOJI.get(group, "✨")
        color  = GROUP_COLOR.get(group, 0xFFD700)
        desc   = f"### {gemoji} {perk['name']}\n{perk['desc']}"
        if perk.get("subdesc"):
            desc += f"\n-# {perk['subdesc']}"
        embed = discord.Embed(title="📋  Perk přiřazen", description=desc, color=color)
        embed.add_field(name="Hráč", value=member.mention, inline=True)
        embed.set_footer(text=f"⭐ {ARION_NAME}  ·  ID: {perk_id}")
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Perk **{perk['name']}** přiřazen {member.mention}.", ephemeral=True
        )

    @perks_group.command(name="list", description="Seznam všech perků v databázi (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def perks_list(self, interaction: discord.Interaction):
        perks = load_perks()
        if not perks:
            await interaction.response.send_message("Databáze perků je prázdná.", ephemeral=True)
            return

        groups: dict[str, list[tuple[str, dict]]] = {}
        ungrouped: list[tuple[str, dict]] = []
        for pid, p in perks.items():
            if pid == "_connections":
                continue
            g = p.get("group", "")
            if g in GROUP_ORDER:
                groups.setdefault(g, []).append((pid, p))
            else:
                ungrouped.append((pid, p))

        # Discord description má limit 4096 znaků — delší se TIŠE usekne (chybějící perky
        # + uříznutý poslední řádek). Skupinu proto stránkujeme jako batoh.
        PAGE_CHAR_BUDGET = 3800   # rezerva pod 4096
        PAGE_MAX_PERKS   = 15

        def _paginate(title: str, entries: list[tuple[str, dict]], color: int,
                      fmt) -> list[tuple[str, str, int]]:
            """Rozseká skupinu na tolik stran, kolik je potřeba."""
            out: list[tuple[str, str, int]] = []
            buf: list[str] = []
            used = 0
            count = 0
            for pid, p in entries:
                block = fmt(pid, p)                 # list řádků jednoho perku
                blen  = sum(len(l) + 1 for l in block)
                if buf and (used + blen > PAGE_CHAR_BUDGET or count >= PAGE_MAX_PERKS):
                    out.append((title, "\n".join(buf), color))
                    buf, used, count = [], 0, 0
                buf.extend(block)
                used  += blen
                count += 1
            if buf:
                out.append((title, "\n".join(buf), color))
            # když je stran víc, očísluj je v nadpisu (Základní (2/3))
            if len(out) > 1:
                out = [(f"{t} ({i + 1}/{len(out)})", c, col)
                       for i, (t, c, col) in enumerate(out)]
            return out

        def _fmt_full(pid: str, p: dict) -> list[str]:
            passive_tag = " *(pasivní)*" if p.get("passive") else ""
            unique_tag  = " ⭐" if p.get("unique") else ""
            max_        = p.get("cooldown_uses", 0)
            cd_tag      = f" · ⏳ {max_}×/den" if max_ > 0 else ""
            return [f"▸ **{p['name']}**{passive_tag}{unique_tag}{cd_tag}", f"-# `{pid}`"]

        def _fmt_plain(pid: str, p: dict) -> list[str]:
            return [f"▸ **{p['name']}**", f"-# `{pid}`"]

        pages: list[tuple[str, str, int]] = []
        for g in GROUP_ORDER:
            if g not in groups:
                continue
            gemoji = GROUP_EMOJI.get(g, "▸")
            color  = GROUP_COLOR.get(g, 0x7B68EE)
            pages += _paginate(f"{gemoji} {g}", groups[g], color, _fmt_full)

        if ungrouped:
            pages += _paginate("✨ Ostatní", ungrouped, 0x7B68EE, _fmt_plain)

        if not pages:
            await interaction.response.send_message("Databáze perků je prázdná.", ephemeral=True)
            return

        view  = PerkListView(pages, requester_id=interaction.user.id)
        embed = view.build_embed()
        embed.set_author(name=f"Celkem perků: {len(perks)}")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # ── /give-random-perk ─────────────────────────────────────────────────────

    @app_commands.command(name="give-random-perk", description="Dej hráči náhodný perk (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hráč který dostane perk")
    async def give_random_perk(self, interaction: discord.Interaction, member: discord.Member):
        all_perks   = load_perks()
        player_data = load_player_perks()
        player      = _get_player(pkey(member.id), player_data)
        owned       = set(player["perks"])
        available   = [pid for pid, p in all_perks.items() if pid not in owned and not p.get("unique") and not p.get("learnable")]

        if not available:
            await interaction.response.send_message(
                f"{member.mention} už vlastní všechny dostupné perky z náhodného poolu.", ephemeral=True
            )
            return

        chosen_id = random.choice(available)
        chosen    = all_perks[chosen_id]
        player["perks"].append(chosen_id)
        save_player_perks(player_data)
        await _check_perk_collector(member, interaction.channel, player["perks"])
        log_action("perk_random", interaction.user.display_name, member.display_name, chosen_id)

        await _dm_perk(member, chosen, chosen_id)

        # Nat20 stat (read-only, jen pro flavor)
        nat20_line = ""
        try:
            from src.core.dnd.roll_stats import get_stats
            stats = get_stats(interaction.guild.id, member.id)
            nat20 = stats.get("nat20", 0)
            if nat20 > 0:
                nat20_line = f"\n-# {member.display_name} hodil již **{nat20}** nat20!"
        except Exception:
            pass

        embed = discord.Embed(
            title="🎲  Náhodný perk!",
            description=f"{member.mention} právě získal nový perk.{nat20_line}",
            color=0x7B68EE,
        )
        embed.set_footer(text=f"⭐ {ARION_NAME}  ·  Detaily v DM")
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Perk **{chosen['name']}** (`{chosen_id}`) přiřazen {member.mention}.", ephemeral=True
        )

    # ── /reset-perky ──────────────────────────────────────────────────────────

    @app_commands.command(name="reset-perky", description="[Admin] Smaže perky hráči (aktivní postavě) nebo všem.")
    @app_commands.describe(member="Hráč (prázdné = všichni)")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_perky_cmd(self, interaction: discord.Interaction, member: discord.Member | None = None):
        player_data = load_player_perks()
        if member:
            # smaž per-character (pkey) klíč i starý účtový (holé uid) — ať po překlíčování
            # nezůstane duch, který by se protáhl přes bare-uid fallback v available_skills
            removed = []
            for key in (pkey(member.id), str(member.id)):
                if key in player_data:
                    del player_data[key]
                    removed.append(key)
            save_player_perks(player_data)
            log_action("reset_perky", interaction.user.display_name, member.display_name, ",".join(removed))
            if removed:
                keys = ", ".join(f"`{k}`" for k in removed)
                await interaction.response.send_message(
                    f"✅ Perky {member.mention} smazány ({keys}).\n"
                    "-# Skilly z nich zmizí až po `/reset-stats`.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"ℹ️ {member.mention} nemá žádné perky k smazání.", ephemeral=True
                )
        else:
            n = len(player_data)
            player_data.clear()
            save_player_perks(player_data)
            log_action("reset_perky", interaction.user.display_name, "ALL", str(n))
            await interaction.response.send_message(
                f"♻️ Perky smazány **všem** ({n} záznamů).\n"
                "-# Přegrantuj a nech hráče projít `/reset-stats`.",
                ephemeral=True,
            )

    # ── /perk skupina ─────────────────────────────────────────────────────────

    perk_group = app_commands.Group(name="perk", description="Správa a použití perků")

    @perk_group.command(name="give", description="Přiřaď konkrétní perk hráči (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(perk_id="ID perku", member="Hráč")
    async def perk_give(self, interaction: discord.Interaction, perk_id: str, member: discord.Member):
        all_perks = load_perks()
        if perk_id not in all_perks:
            await interaction.response.send_message(f"Perk `{perk_id}` neexistuje.", ephemeral=True)
            return
        player_data = load_player_perks()
        player      = _get_player(pkey(member.id), player_data)
        if perk_id in player["perks"]:
            await interaction.response.send_message(
                f"{member.mention} už má **{all_perks[perk_id]['name']}**.", ephemeral=True
            )
            return
        player["perks"].append(perk_id)
        save_player_perks(player_data)
        await _check_perk_collector(member, interaction.channel, player["perks"])
        log_action("perk_give", interaction.user.display_name, member.display_name, perk_id)

        perk   = all_perks[perk_id]
        await _dm_perk(member, perk, perk_id)

        group  = perk.get("group", "")
        gemoji = GROUP_EMOJI.get(group, "✨")
        color  = GROUP_COLOR.get(group, 0xFFD700)
        desc   = f"### {gemoji} {perk['name']}\n{perk['desc']}"
        if perk.get("subdesc"):
            desc += f"\n-# {perk['subdesc']}"
        embed = discord.Embed(title="📋  Perk přiřazen", description=desc, color=color)
        embed.add_field(name="Hráč", value=member.mention, inline=True)
        embed.set_footer(text=f"⭐ {ARION_NAME}  ·  ID: {perk_id}")
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Perk **{perk['name']}** přiřazen {member.mention}.", ephemeral=True
        )

    @perk_group.command(name="add", description="Vytvoř nový perk pomocí slash příkazu (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        perk_id="ID perku (např. fire_magic_1)",
        name="Jméno perku",
        description="Popis co perk dělá",
        group="Skupina (Furioku, Magie, Pasivky, Temnota, Světlo, Základní, Výzbroj, Unikátní)",
        passive="Je to pasivní perk? (true/false)",
        unique="Je to unikátní? (true/false)",
        equip="Lze vybavit? (true/false, default false)",
        learnable="Lze učit (tier up)? (true/false, default false)",
        cooldown_uses="Počet použití (default 0 pro pasivky)",
        cooldown_type="Typ cooldownu: daily, weekly, combat, turn (default none)",
        unlock_skill_id="ID skillu, který perk odemyká (snake_case, prázdné = žádný)",
        unlock_skill_name="Název skillu (prázdné = použije jméno perku)",
        unlock_skill_gives="Co skill dává: none / mana / hp (default none)",
    )
    async def perk_add(
        self,
        interaction: discord.Interaction,
        perk_id: str,
        name: str,
        description: str,
        group: str,
        passive: str,
        unique: str,
        equip: str = "false",
        learnable: str = "false",
        cooldown_uses: int = 0,
        cooldown_type: str = "none",
        unlock_skill_id: str = "",
        unlock_skill_name: str = "",
        unlock_skill_gives: str = "none",
    ):
        try:
            # Zvaliduj group
            valid_groups = GROUP_ORDER
            if group not in valid_groups:
                await interaction.response.send_message(
                    f"❌ Neznámá skupina: `{group}`. Platné: {', '.join(valid_groups)}", ephemeral=True
                )
                return

            # Parse booleans
            passive_bool = passive.lower() in ["true", "yes", "1"]
            unique_bool = unique.lower() in ["true", "yes", "1"]
            equip_bool = equip.lower() in ["true", "yes", "1"]
            learnable_bool = learnable.lower() in ["true", "yes", "1"]
            cooldown_type_final = cooldown_type if cooldown_type != "none" else None

            perks = load_perks()
            if perk_id in perks:
                await interaction.response.send_message(
                    f"❌ Perk `{perk_id}` již existuje.", ephemeral=True
                )
                return

            perks[perk_id] = {
                "name": name,
                "group": group,
                "passive": passive_bool,
                "unique": unique_bool,
                "desc": description,
                "subdesc": None,
                "cooldown_uses": cooldown_uses if not passive_bool else 0,
                "cooldown_type": cooldown_type_final if not passive_bool else None,
            }
            if equip_bool:
                perks[perk_id]["equip"] = True
            if learnable_bool:
                perks[perk_id]["learnable"] = True

            usid = unlock_skill_id.strip().lower().replace(" ", "_")
            if usid:
                _gives = unlock_skill_gives.strip().lower()
                perks[perk_id]["unlocks_skill"] = {
                    "id":    usid,
                    "name":  unlock_skill_name.strip() or name,
                    "gives": _gives if _gives in ("mana", "hp") else None,
                }

            save_perks(perks)
            log_action("perk_add", interaction.user.display_name, "-", perk_id)

            color = GROUP_COLOR.get(group, 0xFFD700)
            gemoji = GROUP_EMOJI.get(group, "✨")
            desc = f"### {gemoji} {name}\n{description}"
            embed = discord.Embed(title="📚  Nový perk vytvořen", description=desc, color=color)
            embed.add_field(name="ID", value=f"`{perk_id}`", inline=True)
            embed.add_field(name="Pasivní?", value="Ano" if passive_bool else "Ne", inline=True)
            embed.add_field(name="Unikátní?", value="Ano" if unique_bool else "Ne", inline=True)
            if equip_bool:
                embed.add_field(name="Lze vybavit?", value="Ano", inline=True)
            if learnable_bool:
                embed.add_field(name="Learnable?", value="Ano", inline=True)
            if usid:
                _gtxt = {"mana": " · +mana", "hp": " · +HP"}.get(perks[perk_id]["unlocks_skill"]["gives"], "")
                embed.add_field(name="Odemyká skill",
                                value=f"{perks[perk_id]['unlocks_skill']['name']} `{usid}`{_gtxt}", inline=True)
            if cooldown_uses and cooldown_type_final:
                embed.add_field(name="Cooldown", value=f"{cooldown_uses}x {cooldown_type_final}", inline=True)
            embed.set_footer(text=f"⭐ {ARION_NAME}  ·  Nový perk: {perk_id}")
            await interaction.channel.send(embed=embed)
            await interaction.response.send_message(f"✅ Perk **{name}** (`{perk_id}`) vytvořen.", ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Chyba: ```\n{str(e)}\n```", ephemeral=True
            )

    @perk_group.command(name="remove", description="Odeber perk hráči (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(perk_id="ID perku", member="Hráč")
    async def perk_remove(self, interaction: discord.Interaction, perk_id: str, member: discord.Member):
        player_data = load_player_perks()
        player      = _get_player(pkey(member.id), player_data)
        if perk_id not in player["perks"]:
            all_perks = load_perks()
            name = all_perks.get(perk_id, {}).get("name", perk_id)
            await interaction.response.send_message(f"{member.mention} nemá **{name}**.", ephemeral=True)
            return
        player["perks"].remove(perk_id)
        player["cooldowns"].pop(perk_id, None)
        save_player_perks(player_data)
        all_perks = load_perks()
        name = all_perks.get(perk_id, {}).get("name", perk_id)
        log_action("perk_remove", interaction.user.display_name, member.display_name, perk_id)
        await interaction.response.send_message(
            f"✅ Perk **{name}** odebrán {member.mention}.", ephemeral=True
        )

    @perk_group.command(name="reset", description="Resetuj cooldowny hráče nebo všech (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hráč (prázdné = reset všech)")
    async def perk_reset(self, interaction: discord.Interaction, member: discord.Member | None = None):
        player_data = load_player_perks()
        if member:
            player = _get_player(pkey(member.id), player_data)
            player["cooldowns"] = {}
            save_player_perks(player_data)
            await interaction.response.send_message(
                f"✅ Cooldowny {member.mention} resetovány.", ephemeral=True
            )
        else:
            for uid_str in player_data:
                player_data[uid_str]["cooldowns"] = {}
            save_player_perks(player_data)
            await interaction.response.send_message(
                "✅ Cooldowny všech hráčů resetovány.", ephemeral=True
            )

    @perk_group.command(name="progress", description="Přidej bod do progress baru perku (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(perk_id="ID perku (musí být learnable)", member="Hráč", amount="Počet bodů (výchozí 1)")
    async def perk_progress(self, interaction: discord.Interaction, perk_id: str, member: discord.Member, amount: int = 1):
        await interaction.response.defer(ephemeral=True)
        all_perks   = load_perks()
        player_data = load_player_perks()
        player      = _get_player(pkey(member.id), player_data)

        if perk_id not in player["perks"]:
            await interaction.followup.send(f"{member.mention} nemá perk `{perk_id}`.", ephemeral=True)
            return
        perk = all_perks.get(perk_id)
        if not perk:
            await interaction.followup.send(f"Perk `{perk_id}` není v databázi.", ephemeral=True)
            return
        if not perk.get("learnable"):
            await interaction.followup.send(f"Perk `{perk_id}` není learnable — nelze levelovat.", ephemeral=True)
            return
        next_id = _next_tier_id(perk_id)
        if not next_id:
            await interaction.followup.send(f"**{perk['name']}** je už na maximálním tieru (III.).", ephemeral=True)
            return

        current = player["progress"].get(perk_id, 0) + amount
        if current >= PROGRESS_MAX:
            # Auto-evolve
            next_perk = all_perks.get(next_id)
            player["perks"].remove(perk_id)
            player["progress"].pop(perk_id, None)
            if next_id not in player["perks"]:
                player["perks"].append(next_id)
            save_player_perks(player_data)
            log_action("perk_evolve", interaction.user.display_name, member.display_name, f"{perk_id} → {next_id}")

            group  = (next_perk or perk).get("group", "")
            color  = GROUP_COLOR.get(group, 0xFFD700)
            gemoji = GROUP_EMOJI.get(group, "✨")
            next_name = next_perk["name"] if next_perk else next_id
            desc = (
                f"### {gemoji} {perk['name']} → **{next_name}**\n"
                f"{next_perk['desc'] if next_perk else ''}\n\n"
                f"{'▰' * PROGRESS_MAX} {PROGRESS_MAX}/{PROGRESS_MAX} ✅"
            )
            embed = discord.Embed(title=f"⬆️ {member.display_name} — LEVEL UP!", description=desc, color=color)
            embed.set_footer(text=f"⭐ {ARION_NAME}  ·  Nový tier: {next_name}")
            await interaction.channel.send(embed=embed)
            await interaction.followup.send(f"✅ Perk evolvnutý: **{perk['name']}** → **{next_name}**.", ephemeral=True)
        else:
            player["progress"][perk_id] = current
            save_player_perks(player_data)
            bar = _progress_bar(current)
            await interaction.followup.send(
                f"✅ Progres přidán — **{perk['name']}** {bar}  ({member.display_name})", ephemeral=True
            )

    @perk_group.command(name="connect", description="Propoj základní perky I. II. III. (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        perk_1="ID perku I. tier (výchozí/základní)",
        perk_2="ID perku II. tier (volitelné)",
        perk_3="ID perku III. tier (volitelné)",
    )
    async def perk_connect(
        self,
        interaction: discord.Interaction,
        perk_1: str,
        perk_2: str = "",
        perk_3: str = "",
    ):
        """
        Propojí perky do řetězce I → II → III tak, že /perk progress
        automaticky evolvuje na správný další tier.
        Funguje pro perky jejichž ID nesleduje _1/_2/_3 konvenci.
        Uloží mapping do NEXT_TIER v runtime (a trvale do perks.json pod klíčem "_connect").
        """
        await interaction.response.defer(ephemeral=True)
        all_perks = load_perks()

        # Validace — všechny zadané perky musí existovat
        ids = [p.strip() for p in [perk_1, perk_2, perk_3] if p.strip()]
        if len(ids) < 2:
            await interaction.followup.send("❌ Zadej alespoň perk I. a II. tier.", ephemeral=True)
            return

        missing = [pid for pid in ids if pid not in all_perks]
        if missing:
            await interaction.followup.send(
                f"❌ Perky nenalezeny v databázi: `{'`, `'.join(missing)}`", ephemeral=True
            )
            return

        # Zkontroluj, že jsou všechny learnable
        not_learnable = [pid for pid in ids if not all_perks[pid].get("learnable")]
        if not_learnable:
            names = ", ".join(f"**{all_perks[p]['name']}**" for p in not_learnable)
            await interaction.followup.send(
                f"❌ Tyto perky nejsou `learnable` — nastav jim `learnable=true` přes `/perk edit` nejdřív:\n{names}",

                ephemeral=True,
            )
            return

        # Ulož propojení do perks.json pod speciálním klíčem "_connections"
        connections: dict = all_perks.get("_connections", {})
        changed_pairs = []
        for i in range(len(ids) - 1):
            from_id = ids[i]
            to_id   = ids[i + 1]
            old_target = connections.get(from_id)
            connections[from_id] = to_id
            # Aktualizuj i runtime _NEXT_TIER dict
            _NEXT_TIER[from_id] = to_id
            changed_pairs.append((from_id, to_id, old_target))

        all_perks["_connections"] = connections
        save_perks(all_perks)

        # Embednout přehled propojení
        lines = []
        for from_id, to_id, old_target in changed_pairs:
            from_name = all_perks[from_id]["name"]
            to_name   = all_perks[to_id]["name"]
            old_str   = f" *(bylo: `{old_target}`)*" if old_target and old_target != to_id else ""
            lines.append(f"▸ **{from_name}** → **{to_name}**{old_str}")

        chain_names = " → ".join(all_perks[pid]["name"] for pid in ids)
        embed = discord.Embed(
            title="🔗 Perky propojeny",
            description=f"Řetězec: {chain_names}\n\n" + "\n".join(lines),



            color=0x1ABC9C,
        )
        embed.set_footer(text=f"⭐ {ARION_NAME}  ·  /perk progress nyní evolvuje správně")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @perk_connect.autocomplete("perk_1")
    @perk_connect.autocomplete("perk_2")
    @perk_connect.autocomplete("perk_3")
    async def _autocomplete_connect(self, interaction: discord.Interaction, current: str):
        perks = load_perks()
        return [
            app_commands.Choice(name=f"{p['name']} ({pid})", value=pid)
            for pid, p in perks.items()
            if pid != "_connections"
            and (current.lower() in pid.lower() or current.lower() in p.get("name", "").lower())
        ][:25]

    @perk_group.command(name="edit", description="Uprav existující perk v databázi (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        perk_id="ID perku k úpravě",
        name="Nový název (prázdné = beze změny)",
        description="Nový popis (prázdné = beze změny)",
        group="Nová skupina (prázdné = beze změny)",
        subdesc="Subdesc (prázdné = beze změny, '-' = smazat)",
        cooldown_uses="Počet použití/den (-1 = beze změny)",
        passive="Pasivní? true/false (prázdné = beze změny)",
        unique="Unikátní? true/false (prázdné = beze změny)",
        learnable="Learnable? true/false (prázdné = beze změny)",
        unlock_skill_id="ID odemykaného skillu (prázdné = beze změny, 'none' = odebrat)",
        unlock_skill_name="Název skillu (jen když měníš unlock_skill_id)",
        unlock_skill_gives="Co skill dává: none / mana / hp",
    )
    async def perk_edit(
        self,
        interaction: discord.Interaction,
        perk_id: str,
        name: str = "",
        description: str = "",
        group: str = "",
        subdesc: str = "",
        cooldown_uses: int = -1,
        passive: str = "",
        unique: str = "",
        learnable: str = "",
        unlock_skill_id: str = "",
        unlock_skill_name: str = "",
        unlock_skill_gives: str = "none",
    ):
        perks = load_perks()
        if perk_id not in perks:
            await interaction.response.send_message(f"❌ Perk `{perk_id}` neexistuje.", ephemeral=True)
            return
        p = perks[perk_id]
        changed = []

        def _b(v):
            return v.strip().lower() in ("true", "yes", "1")

        if name.strip():
            p["name"] = name.strip(); changed.append("název")
        if description.strip():
            p["desc"] = description.strip(); changed.append("popis")
        if group.strip():
            if group.strip() not in GROUP_ORDER:
                await interaction.response.send_message(
                    f"❌ Neznámá skupina. Platné: {', '.join(GROUP_ORDER)}", ephemeral=True)
                return
            p["group"] = group.strip(); changed.append("skupina")
        if subdesc.strip():
            p["subdesc"] = None if subdesc.strip() == "-" else subdesc.strip(); changed.append("subdesc")
        if cooldown_uses >= 0:
            p["cooldown_uses"] = cooldown_uses
            p["cooldown_type"] = "daily" if cooldown_uses > 0 else None
            changed.append("cooldown")
        if passive.strip():
            p["passive"] = _b(passive); changed.append("passive")
        if unique.strip():
            p["unique"] = _b(unique); changed.append("unique")
        if learnable.strip():
            p["learnable"] = _b(learnable); changed.append("learnable")

        usid = unlock_skill_id.strip().lower().replace(" ", "_")
        if usid:
            if usid in ("none", "-", "smazat"):
                p.pop("unlocks_skill", None); changed.append("skill odebrán")
            else:
                _g = unlock_skill_gives.strip().lower()
                p["unlocks_skill"] = {
                    "id":    usid,
                    "name":  unlock_skill_name.strip() or p.get("name", usid),
                    "gives": _g if _g in ("mana", "hp") else None,
                }
                changed.append("odemyká skill")

        if not changed:
            await interaction.response.send_message("Nic ke změně (všechna pole prázdná).", ephemeral=True)
            return
        save_perks(perks)
        await interaction.response.send_message(
            f"✅ Perk **{p['name']}** (`{perk_id}`) upraven: {', '.join(changed)}.", ephemeral=True)

    @perk_group.command(name="tags", description="Nastav roll_tags pro perk — staty kde se zobrazí pod /roll check (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(perk_id="ID perku", tags="Staty oddělené čárkou, např. INS,DEX (prázdné = žádné)")
    async def perk_tags(self, interaction: discord.Interaction, perk_id: str, tags: str = ""):
        perks = load_perks()
        if perk_id not in perks:
            await interaction.response.send_message(f"Perk `{perk_id}` neexistuje.", ephemeral=True)
            return
        valid = {"STR", "DEX", "INS", "INT", "CHA", "WIS"}
        parsed = [t.strip().upper() for t in tags.split(",") if t.strip()]
        invalid = [t for t in parsed if t not in valid]
        if invalid:
            await interaction.response.send_message(
                f"❌ Neznámé staty: `{', '.join(invalid)}`. Povolené: STR, DEX, INS, INT, CHA, WIS.", ephemeral=True
            )
            return
        perks[perk_id]["roll_tags"] = parsed
        save_perks(perks)
        name = perks[perk_id].get("name", perk_id)
        tag_str = ", ".join(parsed) if parsed else "—"
        await interaction.response.send_message(
            f"✅ **{name}** — roll tagy nastaveny: `{tag_str}`", ephemeral=True
        )

    @perk_tags.autocomplete("perk_id")
    async def _autocomplete_tags_id(self, interaction: discord.Interaction, current: str):
        perks = load_perks()
        return [
            app_commands.Choice(name=f"{p['name']} ({pid})", value=pid)
            for pid, p in perks.items()
            if current.lower() in pid.lower() or current.lower() in p.get("name", "").lower()
        ][:25]

    @perk_group.command(name="delete", description="Smaž perk z databáze (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(perk_id="ID perku ke smazání")
    async def perk_delete(self, interaction: discord.Interaction, perk_id: str):
        perks = load_perks()
        if perk_id not in perks:
            await interaction.response.send_message(f"Perk `{perk_id}` neexistuje.", ephemeral=True)
            return
        name = perks[perk_id].get("name", perk_id)
        del perks[perk_id]
        save_perks(perks)
        if perk_id in _SEED_PERKS:        # ať se seed perk nevrátí startovním re-syncem
            d = load_deleted_perks(); d.add(perk_id); save_deleted_perks(d)
        await interaction.response.send_message(
            f"✅ Perk **{name}** (`{perk_id}`) smazán z databáze.", ephemeral=True)

    @perk_group.command(name="detail", description="Zobraz detailní info o perku")
    @app_commands.describe(perk_id="Perk k zobrazení")
    async def perk_detail(self, interaction: discord.Interaction, perk_id: str):
        perks = load_perks()
        if perk_id not in perks:
            await interaction.response.send_message(f"Perk `{perk_id}` neexistuje.", ephemeral=True)
            return
        p = perks[perk_id]

        group  = p.get("group", "")
        gemoji = GROUP_EMOJI.get(group, "✨")
        color  = GROUP_COLOR.get(group, 0xFFD700)

        passive_line = "🔒 Pasivní" if p.get("passive") else "⚡ Aktivní"
        if p.get("unique"):
            unique_line = "⭐ Unikátní"
        elif p.get("learnable"):
            unique_line = "📚 Pouze učením"
        else:
            unique_line = "🎲 V náhodném poolu"
        max_         = p.get("cooldown_uses", 0)
        cd_line      = f"{max_}×/den" if max_ > 0 else "—"

        desc = f"### {gemoji} {p['name']}\n{p['desc']}"
        if p.get("subdesc"):
            desc += f"\n-# {p['subdesc']}"

        embed = discord.Embed(description=desc, color=color)
        embed.add_field(name="Typ",       value=passive_line, inline=True)
        embed.add_field(name="⏳ Cooldown", value=cd_line,     inline=True)
        embed.add_field(name="Dostupnost", value=unique_line,  inline=True)
        embed.set_footer(text=f"⭐ {ARION_NAME}  ·  ID: {perk_id}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @perk_group.command(name="use", description="Aktivuj perk")
    @app_commands.describe(perk_id="Perk k aktivaci")
    async def perk_use(self, interaction: discord.Interaction, perk_id: str):
        all_perks   = load_perks()
        player_data = load_player_perks()
        player      = _get_player(pkey(interaction.user.id), player_data)

        if perk_id not in player["perks"]:
            await interaction.response.send_message("Tento perk nevlastníš.", ephemeral=True)
            return
        if perk_id not in all_perks:
            await interaction.response.send_message("Perk nenalezen v databázi.", ephemeral=True)
            return

        perk = all_perks[perk_id]
        if perk.get("passive"):
            await interaction.response.send_message(
                f"**{perk['name']}** je pasivní perk — aktivuje se automaticky, nelze ho ručně použít.",
                ephemeral=True,
            )
            return

        ok, err_msg = _check_and_use_cooldown(player, perk_id, perk)
        if not ok:
            await interaction.response.send_message(
                f"⏳ **Cooldown aktivní** — {err_msg}", ephemeral=True
            )
            return

        save_player_perks(player_data)
        today = date.today().isoformat()
        cd    = player["cooldowns"].get(perk_id, {})
        used  = cd.get("used", 0) if cd.get("date") == today else 0

        # ── Speciální: Furioku: Odhalení ─────────────────────────────────────
        if perk_id == "furioku_odhaleni":
            pool = load_odhaleni_pool()
            if len(pool) < 3:
                await interaction.response.send_message(
                    "❌ Loot pool má méně než 3 duchy. Přidej přes `/perks odhaleni-add`.", ephemeral=True,
                )
                return
            selections = random.sample(pool, 3)

            try:
                from src.logic.spirits import ELEMENTS as _EL
            except Exception:
                _EL = {}
            lines = []
            for s in selections:
                info       = _EL.get(s["element"], {})
                size_label = f" *({s['size']})*" if s.get("size") else ""
                lines.append(f"{info.get('emoji','👻')} **{s['name']}**{size_label} — 🔋 {s['base_fury']} + 1d20 bonus")

            embed = discord.Embed(
                title="👻 Furioku: Odhalení",
                description=(
                    "Okolo tvé ruky se zjeví tři duchové.\n"
                    "Vyber jednoho — hodíš **1d20** a bonus se přičte k základní furioku.\n\n"
                    + "\n".join(lines)
                ),
                color=0x7B68EE,
            )
            embed.set_footer(text=f"⏳ {_cooldown_bar(used, perk.get('cooldown_uses', 2))} dnes  ·  ⭐ {ARION_NAME}")
            await interaction.response.send_message(embed=embed, view=OdhaleniView(uid=str(interaction.user.id), spirits=selections))
            return

        embed = _perk_announce_embed(interaction.user, perk_id, perk, used)
        await interaction.response.send_message(embed=embed)

    # ── Autocomplete ──────────────────────────────────────────────────────────

    @perks_group.command(name="odhaleni-add", description="Přidej ducha do loot poolu Odhalení (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        name="Jméno ducha (např. Velký duch bouře)",
        element="Element ducha",
        base_fury="Základní furioka (k ní se přičte 1d20 bonus)",
        size="Velikost / typ (např. malý, velký, legendární)",
        spirit_id="Unikátní ID (snake_case, např. velky_duch_bure). Výchozí = z názvu.",
    )
    @app_commands.choices(element=[
        app_commands.Choice(name="🔥 Oheň",    value="ohen"),
        app_commands.Choice(name="💧 Voda",    value="voda"),
        app_commands.Choice(name="🪨 Země",    value="zeme"),
        app_commands.Choice(name="🌬️ Vzduch",  value="vzduch"),
        app_commands.Choice(name="✨ Světlo",  value="svetlo"),
        app_commands.Choice(name="🌑 Temnota", value="temnota"),
        app_commands.Choice(name="⚖️ Rovnováha", value="rovnovaha"),
        app_commands.Choice(name="🌀 Prázdnota", value="prazdnota"),
        app_commands.Choice(name="💥 Chaos",   value="chaos"),
    ])
    async def perks_odhaleni_add(
        self, interaction: discord.Interaction,
        name: str, element: str, base_fury: int,
        size: str = "", spirit_id: str = "",
    ):
        if base_fury < 0:
            await interaction.response.send_message("❌ base_fury musí být ≥ 0.", ephemeral=True)
            return

        sid  = spirit_id.strip().lower().replace(" ", "_") or name.lower().replace(" ", "_")
        pool = load_odhaleni_pool()

        if any(s.get("id") == sid for s in pool):
            await interaction.response.send_message(f"❌ Duch s ID `{sid}` už v poolu je.", ephemeral=True)
            return

        entry = {"id": sid, "name": name, "element": element, "base_fury": base_fury, "size": size}
        pool.append(entry)
        save_odhaleni_pool(pool)

        try:
            from src.logic.spirits import ELEMENTS as _EL
            emoji = _EL.get(element, {}).get("emoji", "👻")
        except Exception:
            emoji = "👻"

        embed = discord.Embed(
            title="✅ Duch přidán do loot poolu",
            description=(
                f"{emoji} **{name}** (`{sid}`)\n"
                f"Element: {element}  ·  Základní furioka: **{base_fury}**"
                + (f"  ·  Velikost: {size}" if size else "")
                + f"\n\nPool nyní obsahuje **{len(pool)}** duchů."
            ),
            color=0x2ECC71,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @perks_group.command(name="odhaleni-list", description="Zobraz loot pool Odhalení (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def perks_odhaleni_list(self, interaction: discord.Interaction):
        pool = load_odhaleni_pool()
        if not pool:
            await interaction.response.send_message("Pool je prázdný.", ephemeral=True)
            return
        try:
            from src.logic.spirits import ELEMENTS as _EL
        except Exception:
            _EL = {}
        lines = []
        for s in pool:
            emoji      = _EL.get(s["element"], {}).get("emoji", "👻")
            size_label = f" *({s['size']})*" if s.get("size") else ""
            lines.append(f"{emoji} **{s['name']}**{size_label} — 🔋 {s['base_fury']}  `-# {s['id']}`")
        embed = discord.Embed(
            title=f"👻 Loot pool Odhalení — {len(pool)} duchů",
            description="\n".join(lines),
            color=0x7B68EE,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @perk_give.autocomplete("perk_id")
    @perk_edit.autocomplete("perk_id")
    @perk_delete.autocomplete("perk_id")
    @perks_give.autocomplete("perk_id")
    @perk_progress.autocomplete("perk_id")
    async def perk_db_autocomplete(self, interaction: discord.Interaction, current: str):
        perks = load_perks()
        return [
            app_commands.Choice(name=f"{p['name']} ({pid})", value=pid)
            for pid, p in perks.items()
            if current.lower() in pid.lower() or current.lower() in p.get("name", "").lower()
        ][:25]

    @perk_remove.autocomplete("perk_id")
    @perk_use.autocomplete("perk_id")
    async def perk_owned_autocomplete(self, interaction: discord.Interaction, current: str):
        all_perks   = load_perks()
        player_data = load_player_perks()
        player      = _get_player(pkey(interaction.user.id), player_data)
        owned       = player["perks"]
        return [
            app_commands.Choice(
                name=f"{all_perks[pid]['name']} ({pid})" if pid in all_perks else pid,
                value=pid,
            )
            for pid in owned
            if current.lower() in pid.lower()
            or (pid in all_perks and current.lower() in all_perks[pid].get("name", "").lower())
        ][:25]


# ══════════════════════════════════════════════════════════════════════════════
# SP UPGRADY PERKŮ — ⭐ embed otevřený ze /staty
# ══════════════════════════════════════════════════════════════════════════════

class PerkUpgradeView(discord.ui.View):
    """Nákup perkových tierů za SP. Vždy tři tiery na řetězec."""

    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self._build()

    def _build(self) -> None:
        self.clear_items()
        db    = load_perks()
        owned = owned_perks(self.user_id)
        for chain in SP_PERK_CHAINS:
            nxt = next_sp_upgrade(chain, owned)
            if not nxt:
                continue   # má už tier III
            perk = db.get(nxt) or _SEED_PERKS.get(nxt, {})
            cost = sp_perk_cost(nxt, db)
            btn  = discord.ui.Button(
                label=f"⭐ {perk.get('name', nxt)} — {cost} SP"[:80],
                style=discord.ButtonStyle.blurple,
            )
            btn.callback = self._make_buy(nxt)
            self.add_item(btn)

    def build_embed(self) -> discord.Embed:
        from src.logic.stats import _load, _profile
        sp    = _profile(_load(), pkey(self.user_id)).get("sp", 0)
        db    = load_perks()
        owned = owned_perks(self.user_id)

        lines: list[str] = []
        for chain in SP_PERK_CHAINS:
            for pid in chain:
                perk = db.get(pid) or _SEED_PERKS.get(pid, {})
                cost = sp_perk_cost(pid, db)
                name = perk.get("name", pid)
                sub  = perk.get("subdesc") or perk.get("desc") or ""
                if pid in owned:
                    lines.append(f"✅ **{name}**")
                elif pid == next_sp_upgrade(chain, owned):
                    lines.append(f"⭐ **{name}** — **{cost} SP**")
                else:
                    lines.append(f"🔒 ~~{name}~~ — {cost} SP")
                if sub:
                    lines.append(f"-# {sub}")
            lines.append("")

        desc = (f"Máš **{sp}** volných ⚡ SP.\n\n" + "\n".join(lines)).strip()
        if len(desc) > 4096:
            desc = desc[:4085].rsplit("\n", 1)[0] + "\n-# …"
        embed = discord.Embed(title="⭐ Upgrady perků", description=desc, color=0xFFD700)
        embed.set_footer(text=f"⚡ {sp} SP  ·  ⭐ {ARION_NAME}")
        return embed

    def _make_buy(self, perk_id: str):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ Toto není tvůj výběr.", ephemeral=True)
                return
            try:
                from src.logic.stats import spend_sp_amount, _load, _profile
                db   = load_perks()
                perk = db.get(perk_id) or _SEED_PERKS.get(perk_id, {})
                name = perk.get("name", perk_id)
                cost = sp_perk_cost(perk_id, db)

                player_data = load_player_perks()
                player      = _get_player(pkey(self.user_id), player_data)
                if perk_id in player["perks"]:
                    await interaction.response.send_message(f"ℹ️ **{name}** už máš.", ephemeral=True)
                    return

                have = _profile(_load(), pkey(self.user_id)).get("sp", 0)
                if not spend_sp_amount(self.user_id, cost):
                    await interaction.response.send_message(
                        f"❌ Na **{name}** potřebuješ **{cost} SP** (máš {have}).", ephemeral=True)
                    return

                # nižší tier nahradíme vyšším (drží se jen aktuální tier)
                for chain in SP_PERK_CHAINS:
                    if perk_id in chain:
                        for lower in chain[:chain.index(perk_id)]:
                            if lower in player["perks"]:
                                player["perks"].remove(lower)
                        break
                player["perks"].append(perk_id)
                save_player_perks(player_data)
                log_action("perk_buy_sp", interaction.user.display_name,
                           interaction.user.display_name, f"{perk_id} ({cost} SP)")
                await _check_perk_collector(interaction.user, interaction.channel, player["perks"])

                view  = PerkUpgradeView(self.user_id)
                embed = view.build_embed()
                embed.description = f"✅ Koupeno: **{name}** (−{cost} SP)\n\n" + embed.description
                await interaction.response.edit_message(embed=embed, view=view)
            except discord.errors.NotFound:
                logger.warning(f"[PerkUpgradeView] zpráva pryč (user {self.user_id})")
            except Exception:
                logger.exception(f"[PerkUpgradeView] nákup {perk_id} selhal")
                try:
                    await interaction.response.send_message("❌ Nákup selhal.", ephemeral=True)
                except Exception:
                    pass
        return cb


async def setup(bot):
    await bot.add_cog(PerksCog(bot))