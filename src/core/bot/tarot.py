"""
Tarot cog pro ArionBot
Arion vykládá tarotové karty — Velká Arkána (22 karet).

Příkazy:
  /tarot solo otazka:   — soukromé věštění, poplatek 50 zlatých
  /tarot session        — otevře veřejné lobby, ostatní se připojí a zaplatí
                          Arion pak vykládá postupně jednomu po druhém

Spread: 3 karty (Minulost – Přítomnost – Budoucnost)
Obrácené karty: 30% šance
Obrázky: src/assets/tarot/0_blazen.png ... 21_svet.png
"""

import discord
import os
import random
import asyncio
import json
from discord.ext import commands
from discord import app_commands

from src.utils.paths import ECONOMY as ECONOMY_PATH, TAROT_DIR
POPLATEK     = 50
MAX_SESSION  = 8
GOLD_EMOJI   = "<:goldcoin:1490171741237018795>"

def load_eco():
    if not os.path.exists(ECONOMY_PATH):
        return {}
    try:
        with open(ECONOMY_PATH, "r", encoding="utf-8") as f:
            c = f.read().strip()
            return json.loads(c) if c else {}
    except Exception:
        return {}

def save_eco(data):
    with open(ECONOMY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def deduct(uid, amount):
    data = load_eco()
    key  = str(uid)
    if data.get(key, 0) < amount:
        return False
    data[key] -= amount
    save_eco(data)
    return True

def balance(uid):
    return load_eco().get(str(uid), 0)

CARDS = [
    {"id":0,"file":"0_blazen.png","name":"0 — Blázen","name_rev":"0 — Blázen ᛉ","emoji":"🃏",
     "keywords":"Nový začátek · Risk · Nevinnost · Svoboda","keywords_rev":"Ukvapenost · Lehkomyslnost · Paralýza strachem",
     "upright":"Blázen stojí na pokraji útesu a usmívá se. Neví co ho čeká — a přesto kráčí. Tato karta přináší čistou, netknutou energii nového začátku. Není to nerozum — je to odvaha důvěřovat procesu i bez mapy. Otevři se tomu, co přichází. Cesta se ukáže až pod nohama.",
     "reversed":"Blázen obrácený varuje před dvěma extrémy: buď jednáš bez jakéhokoli rozmyslu a riskuješ zbytečně, nebo tě strach ze selhání úplně paralyzoval. Podívej se co tě drží — je to moudrost, nebo jen strach z pádu?"},
    {"id":1,"file":"1_mag.png","name":"I — Mág","name_rev":"I — Mág ᛉ","emoji":"🔮",
     "keywords":"Manifestace · Vůle · Akce · Schopnosti","keywords_rev":"Manipulace · Pochybnosti · Nevyužitý potenciál",
     "upright":"Mág stojí za stolem s nástroji čtyř živlů. Má vše co potřebuje — a ví to. Tato karta je výzvou k činu. Přestaň plánovat a začni tvořit. Vůle propojená se záměrem je nejsilnější magií jaká existuje.",
     "reversed":"Energie je tam, ale někde uniká. Možná používáš talent k manipulaci místo k tvorbě, nebo pochybuješ o sobě natolik, že vůbec nezačneš. Mág obrácený se ptá: k čemu skutečně míříš svou sílu?"},
    {"id":2,"file":"2_veleknezka.png","name":"II — Velekněžka","name_rev":"II — Velekněžka ᛉ","emoji":"🌙",
     "keywords":"Intuice · Podvědomí · Tajemství · Trpělivost","keywords_rev":"Potlačená intuice · Skryté informace · Povrchnost",
     "upright":"Velekněžka sedí mezi dvěma sloupy světla a stínu. Za ní splývá závoj, který skrývá to co není připraveno být odhaleno. Tato karta říká: přestaň hledat odpovědi venku. Ticho, sen, pocit před myšlenkou — to je cesta k pravdě, kterou teď hledáš.",
     "reversed":"Velekněžka obrácená znamená že ignoruješ varovné signály přicházející tišší cestou. Možná jsi příliš v analytickém rozumu. Nebo někdo kolem tebe skrývá důležité informace. Naslouchej tomu co se říká mezi řádky."},
    {"id":3,"file":"3_cisarovna.png","name":"III — Císařovna","name_rev":"III — Císařovna ᛉ","emoji":"🌿",
     "keywords":"Hojnost · Tvorba · Péče · Příroda · Plodnost","keywords_rev":"Zanedbání · Přepečlivost · Tvůrčí blok",
     "upright":"Císařovna sedí uprostřed kvetoucí přírody. Vše kolem ní roste, zraje, rozkvétá. Je zosobněním tvůrčí síly. Projekt, vztah, nápad který teď neseš v sobě — je připraven růst. Pečuj o něj s laskavostí.",
     "reversed":"Buď zanedbáváš péči o sebe a o to co tvoříš, nebo se v péči topíš a dusíš tím co chceš ochránit. Císařovna obrácená se ptá: daješ bez přijímání? Najdi rovnováhu toku."},
    {"id":4,"file":"4_cisar.png","name":"IV — Císař","name_rev":"IV — Císař ᛉ","emoji":"👑",
     "keywords":"Struktura · Autorita · Disciplína · Řád","keywords_rev":"Tyranie · Rigidita · Slabost · Chaos",
     "upright":"Císař sedí na trůně z kamene. Jeho energie je neochvějná, pevná, otcovská. Vezmi odpovědnost a vytvoř pevné základy. Disciplína není trest — je to forma péče o svou budoucnost.",
     "reversed":"Buď jsi v zajetí rigidity — pravidel co tě dusí — nebo chybí jakákoliv struktura a vše se rozpadá v chaosu. Císař obrácený se ptá: kdo nebo co v tvém životě zneužívá autoritu? A jsi to ty sám?"},
    {"id":5,"file":"5_veleknez.png","name":"V — Velekněz","name_rev":"V — Velekněz ᛉ","emoji":"⛪",
     "keywords":"Tradice · Duchovní vedení · Instituce · Učení","keywords_rev":"Dogma · Konformismus · Vzdor vůči systému",
     "upright":"Velekněz sedí mezi dvěma sloupy a žehná těm kdo před ním klečí. Je prostředníkem mezi světem lidí a vyšším řádem. V tuto chvíli ti může pomoci mentor, tradice nebo komunita. Neboj se přijmout vedení od moudrých.",
     "reversed":"Dogma tě svazuje. Nebo naopak: bouříš se proti všem systémům i těm co by ti pomohly. Velekněz obrácený tě vyzývá: hledej svou vlastní duchovní pravdu, ne tu co ti byla předána hotová."},
    {"id":6,"file":"6_milenci.png","name":"VI — Milenci","name_rev":"VI — Milenci ᛉ","emoji":"💞",
     "keywords":"Volba · Hodnoty · Vztah · Soulad","keywords_rev":"Disharmonie · Vyhýbání se rozhodnutí · Konflikt hodnot",
     "upright":"Milenci nestojí jen před milostnou volbou — stojí před volbou která definuje kým jsou. Vyber to co je v hlubokém souladu s tvými hodnotami, ne to co je pohodlné nebo očekávané. Autentická volba přináší autentický život.",
     "reversed":"Vyhýbáš se rozhodnutí které je nutné učinit. Nebo jsi se rozhodl v rozporu se sebou samým. Milenci obrácení se ptají: co ti brání vybrat si to co skutečně chceš? Strach? Nebo závazky co přežily svůj čas?"},
    {"id":7,"file":"7_vuz.png","name":"VII — Vůz","name_rev":"VII — Vůz ᛉ","emoji":"🏆",
     "keywords":"Vítězství · Kontrola · Vůle · Pohyb vpřed","keywords_rev":"Ztráta kontroly · Agrese · Rozptýlenost",
     "upright":"Vůz táhnou dvě sfingy — světlá a tmavá. Vezoucí je neřídí uzdičkami ale čistou vůlí. Vítězství je možné, ale jen pokud ovládneš obě strany sebe — světlo i stín, rozum i emoce. Soustřeď se a jeď.",
     "reversed":"Sfingové táhnou různými směry. Ztratil jsi kontrolu nad situací, emocemi nebo svým směřováním. Vůz obrácený říká: zastav. Dřív než budeš pokračovat, zjisti kam vlastně jedeš a proč."},
    {"id":8,"file":"8_sila.png","name":"VIII — Síla","name_rev":"VIII — Síla ᛉ","emoji":"🦁",
     "keywords":"Odvaha · Trpělivost · Soucit · Vnitřní síla","keywords_rev":"Pochybnosti · Strach · Potlačená síla",
     "upright":"Žena klidně a laskavě drží čelisti lva. Nepotřebuje zbraně. Pravá síla je vnitřní — trpělivost, soucit a tichá odhodlanost. Zvládneš co tě čeká — ne silou, ale klidem a laskavostí vůči sobě.",
     "reversed":"Pochybuješ o sobě natolik že svou sílu ani nevytáhneš. Nebo jednáš z pozice strachu a přílišné kontroly. Síla obrácená říká: tvá vnitřní stabilita není pryč. Jen se k ní teď nedostáváš. Hledej ji v tichu."},
    {"id":9,"file":"9_poustevnik.png","name":"IX — Poustevník","name_rev":"IX — Poustevník ᛉ","emoji":"🕯️",
     "keywords":"Introspekce · Samota · Hledání · Moudrost","keywords_rev":"Izolace · Útěk · Odmítání pomoci",
     "upright":"Poustevník stojí sám na horském vrcholu. V ruce drží lucernu — svítí si sám na cestu, ale také ostatním. Potřebuješ ticho a prostor sám pro sebe. Odpověď, kterou hledáš, se nenachází v hluku světa.",
     "reversed":"Izoluješ se příliš — uzavřel ses od lidí a od pomoci. Nebo utíkáš před sebou samým do neustálého pohybu. Poustevník obrácený říká: najdi zdravou míru. Samota léčí, ale izolace ničí."},
    {"id":10,"file":"10_kolo_stesti.png","name":"X — Kolo štěstí","name_rev":"X — Kolo štěstí ᛉ","emoji":"☸️",
     "keywords":"Osud · Cykly · Změna · Příležitost","keywords_rev":"Smůla · Odpor vůči změně · Uváznutí v cyklu",
     "upright":"Kolo se točí — vždy se točilo, vždy se točit bude. Teď se otáčí ve tvůj prospěch. Využij tuto vlnu, ale nezapomínej že kola se vždy otočí. Nic není věčné, ani špatné ani dobré.",
     "reversed":"Kolo se otáčí špatným směrem — nebo se zdá že stojí. Možná se bráníš změně která je nevyhnutelná. Nelpi na výsledku. Ptej se: co se z tohoto cyklu mohu naučit?"},
    {"id":11,"file":"11_spravedlnost.png","name":"XI — Spravedlnost","name_rev":"XI — Spravedlnost ᛉ","emoji":"⚖️",
     "keywords":"Pravda · Karma · Odpovědnost · Rovnováha","keywords_rev":"Nespravedlnost · Vyhýbání se odpovědnosti · Nepoctivost",
     "upright":"Spravedlnost sedí s mečem a vahami. Nemá pásku přes oči — vidí vše jasně. Karma je v pohybu: co jsi zasel, to sklidíš. Je čas přijmout odpovědnost za svá rozhodnutí a jednat s absolutní poctivostí.",
     "reversed":"Někde je nerovnováha která se neřeší. Možná se vyhýbáš odpovědnosti, nebo byl výsledek nespravedlivý. Spravedlnost obrácená říká: přiznej si pravdu — i tu nepříjemnou. Bez poctivosti nepřijde uzdravení."},
    {"id":12,"file":"12_viselec.png","name":"XII — Viselec","name_rev":"XII — Viselec ᛉ","emoji":"🙃",
     "keywords":"Pauza · Oběť · Jiný úhel pohledu · Přijetí","keywords_rev":"Zbytečná oběť · Odpor vůči pauze · Stagnace",
     "upright":"Viselec visí na stromě — dobrovolně. Kolem hlavy má záři. Tato karta není o utrpení — je o vědomé pauze. Zkus se podívat na svou situaci z úplně jiného úhlu pohledu. Odpověď leží tam kde jsi ještě nehledal.",
     "reversed":"Obětoval ses pro nic, nebo stále nedokážeš pustit co tě táhne dolů. Nebo se vzpíráš nutné pauze. Viselec obrácený říká: dost zbytečné oběti. Sestup a jednej."},
    {"id":13,"file":"13_smrt.png","name":"XIII — Smrt","name_rev":"XIII — Smrt ᛉ","emoji":"🌑",
     "keywords":"Konec · Transformace · Přechod · Nezbytná změna","keywords_rev":"Odpor vůči konci · Stagnace · Strach ze změny",
     "upright":"Smrt jede na bílém koni a před ní vše ustupuje. V tarotu tato karta málokdy znamená fyzickou smrt. Znamená nevyhnutelný konec jedné kapitoly, aby mohla začít jiná. Pusť to co ti již neslouží. Za koncem vždy čeká nové ráno.",
     "reversed":"Bráníš se konci který je dávno nutný. Lpíš na něčem co tě již nepotřebuje. Smrt obrácená říká: strach ze změny je vždy horší než změna sama. Co musí zemřít, aby se mohlo zrodit něco nového?"},
    {"id":14,"file":"14_mirnost.png","name":"XIV — Mírnost","name_rev":"XIV — Mírnost ᛉ","emoji":"🏺",
     "keywords":"Rovnováha · Trpělivost · Integrace · Léčení","keywords_rev":"Netrpělivost · Přehnanost · Disharmonie",
     "upright":"Anděl přelévá vodu z jedné nádoby do druhé — pomalu, klidně, s dokonalou přesností. Mírnost říká: léčení probíhá. Nespěchej. Harmonické spojení protikladů přináší to co silou nikdy nezískaš.",
     "reversed":"Jsi mimo rovnováhu — přeháníš v jednom směru a zanedbáváš druhý. Možná jsi příliš netrpělivý. Mírnost obrácená říká: zpomal. Co se rozbilo spěchem, se opraví jedině časem a klidem."},
    {"id":15,"file":"15_dabel.png","name":"XV — Ďábel","name_rev":"XV — Ďábel ᛉ","emoji":"😈",
     "keywords":"Spoutání · Závislost · Stín · Materialismus","keywords_rev":"Probuzení · Osvobozování · Uvědomění si pout",
     "upright":"Ďábel sedí na trůně a pod ním jsou dva lidé přivázáni řetězy — ale řetězy jsou volné. Mohli by odejít. Tato karta ukazuje na vzorce a závislosti které sám udržuješ. Co tě drží? A je to skutečně tak pevné jak si myslíš?",
     "reversed":"Začínáš se probouzet. Ďábel obrácený je pozitivní znamení — vidíš řetězy které sis sám nasadil a začínáš je sundávat. Pokračuj v tomto probuzení. Cesta ze stínu začíná tím že ho pojmenuješ."},
    {"id":16,"file":"16_vez.png","name":"XVI — Věž","name_rev":"XVI — Věž ᛉ","emoji":"⚡",
     "keywords":"Náhlý šok · Destrukce iluzí · Zjevení · Osvobození","keywords_rev":"Odvrácená katastrofa · Odpor vůči přestavbě · Odložený kolaps",
     "upright":"Blesk udeří do věže postavené na špatných základech. Věž je jedna z nejobávanějších karet — ale není to trest, je to osvobození. Co padá, bylo postaveno na lži. Z trosek lze postavit něco pevnějšího a pravdivějšího.",
     "reversed":"Katastrofě jsi se zatím vyhnul — nebo ji jen odsouvíš. Základy se hroutí i když to není vidět. Máš čas jednat dobrovolně dřív než blesk udeří sám. Lépe vědomá přestavba než náhlý pád."},
    {"id":17,"file":"17_hvezda.png","name":"XVII — Hvězda","name_rev":"XVII — Hvězda ᛉ","emoji":"⭐",
     "keywords":"Naděje · Léčení · Inspirace · Obnova víry","keywords_rev":"Ztráta naděje · Zklamání · Izolace od světla",
     "upright":"Po Věži přichází Hvězda. Žena klečí u vody a lije ji zpět do země — dává aniž by ztrácela. Jsi na správné cestě. Obnov důvěru v sebe a v proces. Světlo které teď vidíš není klam — je to skutečný záblesk budoucnosti.",
     "reversed":"Ztratil jsi naději nebo se uzavřel světlu které je kolem tebe. Hvězda obrácená říká: světlo tam stále je. Nevidíš ho ne proto že zmizelo, ale proto že ses odvrátil."},
    {"id":18,"file":"18_luna.png","name":"XVIII — Luna","name_rev":"XVIII — Luna ᛉ","emoji":"🌕",
     "keywords":"Iluze · Podvědomí · Nejistota · Sny","keywords_rev":"Rozptylující se mlha · Odhalení pravdy · Vynořující se jasnost",
     "upright":"Luna osvětluje cestu, ale slabě. Co vidíš nemusí být reálné. Tvé strachy tě matou. Nečiň teď velká rozhodnutí — počkej až se mlha rozptýlí a pravda se vynořuje sama.",
     "reversed":"Mlha se začíná rozptylovat. Luna obrácená přináší postupné odhalení — iluze padají a pravda se vynořuje na povrch. To čeho ses bál nemusí být tak hrozivé jak se zdálo ve tmě."},
    {"id":19,"file":"19_slunce.png","name":"XIX — Slunce","name_rev":"XIX — Slunce ᛉ","emoji":"☀️",
     "keywords":"Radost · Úspěch · Vitalita · Jasnost · Dětská energie","keywords_rev":"Přehnaný optimismus · Neschopnost radosti · Zatemněné světlo",
     "upright":"Dítě jede na koni pod zářícím sluncem s rozevřenou náručí. Slunce přináší radost, vitalitu, úspěch a jasnost. Věci se vyvíjejí dobře. Užij si toto světlo naplno — zasloužil sis ho.",
     "reversed":"Radost a světlo tam jsou — ale ty je buď nevidíš nebo si je nedovoluješ cítit. Slunce obrácené říká pouze jedno: dovol si být šťastný. Štěstí není zrada — je to tvé přirozené právo."},
    {"id":20,"file":"20_soud.png","name":"XX — Soud","name_rev":"XX — Soud ᛉ","emoji":"🎺",
     "keywords":"Znovuzrození · Volání osudu · Uzavření · Probuzení","keywords_rev":"Ignorování volání · Sebezapření · Odložené zúčtování",
     "upright":"Anděl troubí na trubku a z rakví vstávají lidé — proměnění, připravení. Slyšíš v sobě hlas který tě volá k něčemu většímu? K jiné cestě, k uzavření starého, k přijetí nové identity? Odpověz. Čas je teď.",
     "reversed":"Ignoruješ volání které k tobě přichází. Možná se bojíš toho co by přijetí obnášelo. Soud obrácený říká: sebezapření tě neochrání. Volání neutichne — jen hořkne."},
    {"id":21,"file":"21_svet.png","name":"XXI — Svět","name_rev":"XXI — Svět ᛉ","emoji":"🌍",
     "keywords":"Naplnění · Integrace · Dokončení · Oslava","keywords_rev":"Nedokončené věci · Strach z uzavření · Ještě jeden krok",
     "upright":"Tanečnice obklopená věncem. Vše je v harmonii. Dosáhl jsi konce jednoho velkého cyklu. Integruj vše co jsi prožil, oslav a buď vděčný. Tohle je skutečné vítězství — dokonalé uzavření před novým, větším začátkem.",
     "reversed":"Jsi těsně u cíle — a přesto stojíš. Strach z uzavření, pocit že nejsi dost hotov. Svět obrácený říká klidně a pevně: ještě jeden krok. Udělej ho."},
]

POSITION_NAMES = ["Minulost", "Přítomnost", "Budoucnost"]
POSITION_DESC  = [
    "Energie a události které tě sem přivedly. Co formovalo tuto situaci.",
    "Kde se teď nacházíš. Jádro toho čím právě procházíš.",
    "Kam tvá energie přirozeně míří — pokud půjdeš současnou cestou.",
]
POSITION_EMOJI = ["⬅️", "🎯", "➡️"]

ARION_INTROS = [
    "*Arion pomalu rozloží tři karty na stůl čelí dolů a přimhouří modré oči.*\n***'Každá karta je zrcadlo. Ne věštba.'***",
    "*Arion si olízne tlapku a začne míchat balíček s překvapivou elegancí.*\n***'Zeptej se. A pak hlavně naslouchej.'***",
    "*Arion vytáhne ze šuplíku starou dřevěnou kazetu. Karty jsou staré — a cítíš to.*\n***'Dobře. Podíváme se co říkají.'***",
    "*Arion se zavřenýma očima přejede tlapkou přes balíček. Tři karty sama vyskočí na stůl.*\n***'Tarot neodpovídá. Tarot naslouchá.'***",
    "*Arion zapálí svíčku. Vzduch se pootočí. Pak pomalu, bez spěchu, vytáhne tři karty.*\n***'Karty nečtou budoucnost. Čtou tebe.'***",
    "*Arion tiše přikývne, zamíchá a rozloží — jako by to dělala stokrát denně.*\n***'Co se má ukázat, ukáže se vždy.'***",
]

ARION_BETWEEN = [
    "*Arion si mezi výklady otře tlapku a chvíli mlčí...*",
    "*Arion nakloní hlavu, sahá po balíčku a začíná znovu míchat.*",
    "*Arion přikývne.* ***'Další.'*** *A znovu začíná.*",
    "*Chvíle ticha. Pak Arion rozloží nové karty.*",
    "*Svíčka zašumí. Arion na ni ani nepodívá — už míchá.*",
]

active_sessions = {}

def draw_three():
    cards   = random.sample(CARDS, 3)
    flipped = [random.random() < 0.30 for _ in range(3)]
    return list(zip(cards, flipped))

def _dynamic_summary(drawn, otazka):
    """Generuje celkový výklad který jmenuje konkrétní karty a reaguje na otázku."""
    names = [(c["name_rev"] if r else c["name"]) for c, r in drawn]
    past, present, future = names

    # Kombinační komentáře — čím více karet padne z těžkých arcán, tím ostřejší tón
    heavy = {"XIII — Smrt", "XVI — Věž", "XV — Ďábel", "X — Kolo štěstí ᛉ",
             "XIII — Smrt ᛉ", "XVI — Věž ᛉ", "XV — Ďábel ᛉ"}
    light = {"XIX — Slunce", "XVII — Hvězda", "XXI — Svět",
             "XIX — Slunce ᛉ", "XVII — Hvězda ᛉ", "XXI — Svět ᛉ"}

    heavy_count = sum(1 for n in names if n in heavy)
    light_count = sum(1 for n in names if n in light)

    if heavy_count >= 2:
        tone = "Těžké karty. Ale tarot nevynáší rozsudky — ukazuje tlak který už cítíš."
    elif light_count >= 2:
        tone = "Světlé karty — ale pozor, světlo v tarotu není zárukou, je to směr."
    elif drawn[2][1]:  # budoucnost obrácená
        tone = "Budoucnost obrácená neznačí špatný konec — značí energii která ještě nenašla cestu ven."
    elif drawn[0][1]:  # minulost obrácená
        tone = "Minulost obrácená — co tě sem přivedlo, nebylo přímočaré. A to je v pořádku."
    else:
        tone = "Tři karty, tři vrstvy jednoho příběhu."

    summary = (
        f"{tone}\n\n"
        f"**{past}** tě formovala — ať už si to přiznal/a nebo ne. "
        f"**{present}** je to čím právě procházíš, jádro situace. "
        f"**{future}** naznačuje kam tvá energie přirozeně míří — "
        f"pokud půjdeš současnou cestou.\n\n"
        f"*Zeptal/a ses: \"{otazka}\"*\n"
        f"Karty neodpověděly. Ukázaly tě."
    )
    return summary


def reading_embed(member_name, otazka, drawn):
    intro = random.choice(ARION_INTROS)
    embed = discord.Embed(
        title=f"🃏 Výklad pro {member_name}",
        description=(
            f"{intro}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Otázka:** *{otazka}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=0x2c3e50
    )
    for i, (card, rev) in enumerate(drawn):
        name     = card["name_rev"] if rev else card["name"]
        meaning  = card["reversed"] if rev else card["upright"]
        keywords = card["keywords_rev"] if rev else card["keywords"]
        rev_tag  = " 🔄" if rev else ""
        embed.add_field(
            name=f"{POSITION_EMOJI[i]} {POSITION_NAMES[i]} — {card['emoji']} {name}{rev_tag}",
            value=f"-# *{POSITION_DESC[i]}*\n-# {keywords}\n\n{meaning}",
            inline=False
        )
    has_reversed = any(r for _, r in drawn)
    rev_note = "\n-# *🔄 Obrácená karta neznamená špatnou energii — znamená energii obrácenou dovnitř nebo zablokovanou.*" if has_reversed else ""
    embed.add_field(
        name="🌀 Celkový výklad",
        value=_dynamic_summary(drawn, otazka) + rev_note,
        inline=False
    )
    embed.set_footer(text="Arion osobní kronika | Tarot — Velká Arkána · Tři karty")
    return embed

async def send_reading(channel, member_name, otazka, drawn, mention=""):
    """Pošle výklad — intro embed, pak každá karta zvlášť s obrázkem, pak celkový výklad."""
    intro = random.choice(ARION_INTROS)

    # ── Intro embed s otázkou ──────────────────────────────────────────────────
    intro_embed = discord.Embed(
        title=f"🃏 Výklad pro {member_name}",
        description=(
            f"{intro}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Otázka:** *{otazka}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=0x2c3e50
    )
    intro_embed.set_footer(text="Arion osobní kronika | Tarot — Velká Arkána · Tři karty")

    if mention:
        await channel.send(content=mention, embed=intro_embed)
    else:
        await channel.send(embed=intro_embed)

    # ── Každá karta zvlášť — napětí před odhalením ────────────────────────────
    for i, (card, rev) in enumerate(drawn):
        await asyncio.sleep(1.5)
        name     = card["name_rev"] if rev else card["name"]
        meaning  = card["reversed"] if rev else card["upright"]
        keywords = card["keywords_rev"] if rev else card["keywords"]
        rev_tag  = " 🔄" if rev else ""

        card_embed = discord.Embed(
            title=f"{POSITION_EMOJI[i]} {POSITION_NAMES[i]} — {card['emoji']} {name}{rev_tag}",
            description=f"-# *{POSITION_DESC[i]}*\n-# {keywords}\n\n{meaning}",
            color=0x2c3e50,
        )

        path = os.path.join(TAROT_DIR, card["file"])
        if os.path.exists(path):
            f = discord.File(path, filename=card["file"])
            card_embed.set_image(url=f"attachment://{card['file']}")
            await channel.send(embed=card_embed, file=f)
        else:
            await channel.send(embed=card_embed)

    # ── Celkový výklad ─────────────────────────────────────────────────────────
    await asyncio.sleep(1.5)
    has_reversed = any(r for _, r in drawn)
    rev_note = "\n-# *🔄 Obrácená karta neznamená špatnou energii — znamená energii obrácenou dovnitř nebo zablokovanou.*" if has_reversed else ""
    summary_embed = discord.Embed(
        title="🌀 Celkový výklad",
        description=_dynamic_summary(drawn, otazka) + rev_note,
        color=0x2c3e50,
    )
    summary_embed.set_footer(text="Arion osobní kronika | Tarot — Velká Arkána · Tři karty")
    await channel.send(embed=summary_embed)

def lobby_embed_build(s, guild):
    count = len(s["queue"])
    embed = discord.Embed(
        title="🔮 Tarotová session — Lobby",
        description=(
            "*Arion připravuje karty a svíčky...*\n\n"
            f"**Poplatek:** {POPLATEK} {GOLD_EMOJI} za výklad\n"
            f"**Spread:** Tři karty — Minulost · Přítomnost · Budoucnost\n\n"
            "Připoj se tlačítkem níže a zadej svou otázku. "
            "Host spustí výklad až bude lobby připravena."
        ),
        color=0x2c3e50
    )
    if count == 0:
        embed.add_field(name="Přihlášení", value="*Zatím nikdo...*", inline=False)
    else:
        lines = []
        for i, (uid, _) in enumerate(s["queue"]):
            m = guild.get_member(uid)
            lines.append(f"{i+1}. {m.display_name if m else uid}")
        embed.add_field(name=f"Přihlášení ({count}/{MAX_SESSION})", value="\n".join(lines), inline=False)
    embed.set_footer(text="Arion osobní kronika | Tarot — Velká Arkána")
    return embed

class TarotQuestionModal(discord.ui.Modal, title="Tvá otázka pro Arion"):
    otazka = discord.ui.TextInput(
        label="Otázka pro karty",
        placeholder="Otevřená otázka — ne ano/ne. Např: Co mě teď nejvíc ovlivňuje?",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=200
    )
    def __init__(self, gid):
        super().__init__()
        self.gid = gid

    async def on_submit(self, interaction: discord.Interaction):
        gid = self.gid
        uid = interaction.user.id
        if gid not in active_sessions:
            await interaction.response.send_message("Session již neexistuje.", ephemeral=True)
            return
        s = active_sessions[gid]
        if uid in s["paid"]:
            await interaction.response.send_message("Už jsi zaplacen!", ephemeral=True)
            return
        if len(s["queue"]) >= MAX_SESSION:
            await interaction.response.send_message("Session je plná.", ephemeral=True)
            return
        if not deduct(uid, POPLATEK):
            bal = balance(uid)
            await interaction.response.send_message(
                f"Nemáš dost zlatých. Potřebuješ **{POPLATEK}** {GOLD_EMOJI}, máš **{bal}** {GOLD_EMOJI}.",
                ephemeral=True
            )
            return
        s["paid"].add(uid)
        s["queue"].append((uid, self.otazka.value))
        await interaction.response.send_message(
            f"✅ Zaplaceno **{POPLATEK}** {GOLD_EMOJI}. Jsi v řadě č. **{len(s['queue'])}**.\n"
            "*Arion přijala tvou otázku a přikývla.*",
            ephemeral=True
        )
        try:
            if "lobby_msg" in s:
                await s["lobby_msg"].edit(embed=lobby_embed_build(s, interaction.guild))
        except Exception:
            pass

class TarotLobbyView(discord.ui.View):
    def __init__(self, session_gid):
        super().__init__(timeout=1800)   # 30 minut
        self.session_gid = session_gid

    async def on_timeout(self):
        # Cleanup — aby nová session mohla vzniknout
        active_sessions.pop(self.session_gid, None)

    @discord.ui.button(label="🔮 Připojit se a zaplatit 50 zlatých", style=discord.ButtonStyle.primary)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = interaction.guild_id
        uid = interaction.user.id
        if gid not in active_sessions:
            await interaction.response.send_message("Session již neexistuje.", ephemeral=True)
            return
        s = active_sessions[gid]
        if s["active"]:
            await interaction.response.send_message("Arion právě vykládá — na tuto session je pozdě.", ephemeral=True)
            return
        if uid in s["paid"]:
            await interaction.response.send_message("Už jsi zaplacen a v řadě!", ephemeral=True)
            return
        if len(s["queue"]) >= MAX_SESSION:
            await interaction.response.send_message("Session je plná.", ephemeral=True)
            return
        await interaction.response.send_modal(TarotQuestionModal(gid))

    @discord.ui.button(label="▶️ Spustit výklad (host)", style=discord.ButtonStyle.success)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = interaction.guild_id
        uid = interaction.user.id
        if gid not in active_sessions:
            await interaction.response.send_message("Session neexistuje.", ephemeral=True)
            return
        s = active_sessions[gid]
        if uid != s["host_id"]:
            await interaction.response.send_message("Výklad může spustit jen host session.", ephemeral=True)
            return
        if not s["queue"]:
            await interaction.response.send_message("Nikdo se nepřipojil.", ephemeral=True)
            return
        if s["active"]:
            await interaction.response.send_message("Výklad už probíhá.", ephemeral=True)
            return
        s["active"] = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        channel = interaction.channel
        n = len(s["queue"])
        await channel.send(
            f"🃏 *Arion zamíchá karty, zhasne světlo a začíná...*\n"
            f"*Dnes čeká výklad celkem **{n}** {'osoby' if n == 1 else 'osob'}.*"
        )
        await asyncio.sleep(2)
        for idx, (member_id, otazka) in enumerate(s["queue"]):
            if idx > 0:
                await channel.send(random.choice(ARION_BETWEEN))
                await asyncio.sleep(2)
            drawn  = draw_three()
            member = interaction.guild.get_member(member_id)
            name   = member.display_name if member else str(member_id)
            mention = member.mention if member else str(member_id)
            await send_reading(channel, name, otazka, drawn, mention=mention)
            await asyncio.sleep(3)
        await channel.send(
            "🐾 *Arion složí balíček, sfouká svíčku a zamrská ocáskem.*\n"
            "***'Hotovo. Co jsi slyšel/a, nes v sobě — ne jako osud, ale jako zrcadlo.'***"
        )
        del active_sessions[gid]

class Tarot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    tarot_group = app_commands.Group(name="tarot", description="Arion vykládá tarotové karty")

    @tarot_group.command(name="den", description="Jedna karta na dnešní den — zdarma")
    async def tarot_den(self, interaction: discord.Interaction):
        await interaction.response.defer()
        card, rev = random.choice(CARDS), random.random() < 0.30
        name     = card["name_rev"] if rev else card["name"]
        meaning  = card["reversed"] if rev else card["upright"]
        keywords = card["keywords_rev"] if rev else card["keywords"]
        rev_tag  = " 🔄" if rev else ""

        DEN_INTROS = [
            "*Arion zamíchá balíček, zavře oči a jedním pohybem vytáhne jednu kartu.*\n***'Co ti dnes přinese den?'***",
            "*Arion položí ruku na balíček. Chvíle ticha. Pak jednu kartu otočí.*\n***'Tady je tvůj den.'***",
            "*Arion bez jediného slova vytáhne kartu a položí ji před tebe.*\n***'Nech to na sobě.'***",
            "*Arion přejede tlapkou přes balíček. Jedna karta se sama posune dopředu.*\n***'To není náhoda.'***",
        ]

        embed = discord.Embed(
            title="🌅 Karta dne",
            description=(
                f"{random.choice(DEN_INTROS)}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=0x2c3e50
        )
        embed.add_field(
            name=f"{card['emoji']} {name}{rev_tag}",
            value=f"-# {keywords}\n\n{meaning}",
            inline=False
        )
        if rev:
            embed.add_field(
                name="",
                value="-# *🔄 Obrácená karta neznamená špatnou energii — znamená energii obrácenou dovnitř nebo zablokovanou.*",
                inline=False
            )
        embed.set_footer(text="Arion osobní kronika | Tarot — Velká Arkána · Karta dne")

        path = os.path.join(TAROT_DIR, card["file"])
        if os.path.exists(path):
            f = discord.File(path, filename=card["file"])
            embed.set_image(url=f"attachment://{card['file']}")
            await interaction.followup.send(embed=embed, file=f)
        else:
            await interaction.followup.send(embed=embed)

    @tarot_group.command(name="solo", description=f"Soukromý výklad — Arion ti vyloží 3 karty (poplatek {POPLATEK} zlatých)")
    @app_commands.describe(otazka="Tvá otázka pro karty — otevřená, ne ano/ne")
    async def tarot_solo(self, interaction: discord.Interaction, otazka: str):
        uid = interaction.user.id
        bal = balance(uid)
        if bal < POPLATEK:
            await interaction.response.send_message(
                f"Nemáš dost zlatých. Věštění stojí **{POPLATEK}** {GOLD_EMOJI}, ty máš **{bal}** {GOLD_EMOJI}.",
                ephemeral=True
            )
            return
        await interaction.response.defer()
        # Deduct až po defer — aby hráč nepřišel o zlaté při Discord chybě
        if not deduct(uid, POPLATEK):
            await interaction.followup.send(
                f"Nemáš dost zlatých. Věštění stojí **{POPLATEK}** {GOLD_EMOJI}.",
                ephemeral=True
            )
            return
        drawn = draw_three()
        await send_reading(interaction.channel, interaction.user.display_name, otazka, drawn)

    @tarot_group.command(name="session", description="Otevře veřejnou tarotovou session — ostatní se připojí a zaplatí")
    async def tarot_session(self, interaction: discord.Interaction):
        gid = interaction.guild_id
        uid = interaction.user.id
        if gid in active_sessions:
            await interaction.response.send_message("Na serveru již probíhá tarotová session.", ephemeral=True)
            return
        s = {"channel_id": interaction.channel_id, "host_id": uid,
             "queue": [], "paid": set(), "active": False}
        active_sessions[gid] = s
        view  = TarotLobbyView(gid)
        embed = lobby_embed_build(s, interaction.guild)
        await interaction.response.send_message(embed=embed, view=view)
        active_sessions[gid]["lobby_msg"] = await interaction.original_response()

async def setup(bot: commands.Bot):
    await bot.add_cog(Tarot(bot))