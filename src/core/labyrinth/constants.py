"""Konstanty pro Door Labyrinth."""

MIN_PLAYERS = 4
MAX_PLAYERS = 10

DARK_ROOM_CHANCE = 0.30

DOOR_COLORS = [
    ("🔴", "Červené"),
    ("🟡", "Žluté"),
    ("🟢", "Zelené"),
    ("🔵", "Modré"),
]

INNOCENT_ROLES = ["detektiv", "doktor", "skaut", "technik", "blázen"]
MURDERER_ROLES = ["manipulátor", "pastičkář", "sériový vrah"]

ALL_ITEMS = ["baterka", "zapalovač", "svíčka", "kanystr"]
WEAPON_ITEMS = ["nůž", "baseballka", "sekáček", "vrtačka"]

ITEM_EMOJI = {
    "pistole":        "🔫",
    "nůž":            "🔪",
    "baterka":        "🔦",
    "zapalovač":      "🪔",
    "svíčka":         "🕯️",
    "klíč":           "🗝️",
    "klíč od truhly": "🗝️",
    "lékárnička":     "💊",
    "skener":         "📡",
    "amulet":         "🔮",
    "baseballka":     "🏏",
    "sekáček":        "🪓",
    "vrtačka":        "🔩",
    "mačeta":         "🗡️",
    "kanystr":        "⛽",
}

ROOM_DESCRIPTIONS = [
    "Stěny jsou pokryté vlhkým mechem. Vzduch páchne hnilobou a starým dřevem.",
    "Rozbitá lucerna se houpe ze stropu. Její světlo vrhá klikaté stíny.",
    "Na podlaze leží rozházené listiny. Některé jsou potřísněné tmavou skvrnou.",
    "Místnost je ledová. Tvůj dech se mění v páru. Ticho je omračující.",
    "Z trhliny ve zdi prosákla voda a vytvořila louži uprostřed pokoje.",
    "Starý nábytek je převrhnutý. Někdo tu byl nedávno – velmi spěchal.",
    "Na stěně je vyryto číslo. Kdo to tu zanechal a proč?",
    "Vzduch voní po síře. Někde daleko zakřičel pták, pak zase ticho.",
    "Podlahová prkna skřípu pod každým krokem. Nejsi tu sám.",
    "V rohu stojí opuštěná klec. Dveře jsou dokořán. Uvnitř – prázdno.",
    "Záclony visí roztrhané před zazděným oknem. Světlo sem neproniká.",
    "Na stole stojí svíčka dohořívající do posledního plamene. Čas se krátí.",
    "Zdi jsou polepeny mapami s vymazanými lokacemi. Někdo nechce, abys věděl/a.",
    "Skrz štěrbinu ve stropě kape voda v pravidelném rytmu. Tikání hodinek smrti.",
    "Dveře za tebou zavřely s hluchým dusnem. Zpět cesta nevede.",
    "Na podlaze jsou stopy – příliš malé na to, aby patřily někomu lidskému.",
    "Místnost zapáchá po chemikáliích. Někdo tu připravoval něco nechutného.",
    "Ve zdi je díra velká jako pěst. Skrz ni vidíš jen tmu.",
    "Strop je nízký a stěny se zdají přibližovat. Nebo se to jen zdá?",
    "Opadaná barva ze zdí tvoří podivné vzory. Čím déle se díváš, tím víc vidíš.",
    "Koberec je přeložen. Pod ním jsou vyryté symboly, jejichž smysl neznáš.",
    "Řetěz visí ze stropu bez zámku. Byl tu kdysi někdo přivázán?",
    "Skleněná vitrina je rozbitá. Co v ní bylo, teď chybí.",
]

DARK_ROOM_DESCRIPTIONS = [
    "Absolutní tma. Vzduch je tísnivý a studený jako v hrobě.",
    "Tma pohltí vše. Neslyšíš nic — nebo snad ano?",
    "Žádné světlo sem neproniklo. Orientuješ se hmatem a dechem.",
    "V naprosté tmě se zdá, že stěny se přibližují.",
    "Záblesk za víčky. Pak zase tma. Byl to odraz, nebo pohyb?",
    "Tma jako smůla — taková, která skrývá záměrně.",
    "Krůček za krůčkem, tápáš vpřed. Cítíš, že tu není sám/sama.",
    "Nepřátelská tma. Dýcháš mělce, abys neslyšel/a vlastní srdce.",
]

CODE_LORE = [
    "Na omítce je vyryto číslo. Kdo to tu zanechal?",
    "Pod kobercem nacházíš útržek papíru s napsaným číslem.",
    "Grafiti na zdi — mezi symboly vystupuje číslo.",
    "Starý nápis nad dveřmi skrývá číslo, dnes už sotva čitelné.",
    "Na tabulce u dveří je vyznačeno číslo. Vypadá úředně.",
    "Rozbitá klávesnice na zdi ukazuje poslední stisknuté číslo.",
    "V knize na polici nacházíš záložku s ručně psaným číslem.",
    "Krví načmáraná cifra na stropě. Čí to ruka?",
    "Číslo vyryté do kovu dveří — hlubokými tahy.",
    "Na dně prázdné sklenice leží lísteček s číslem.",
]

MAP_SIZES = {
    "3x3": (3, 3),
    "4x4": (4, 4),
    "4x6": (4, 6),
    "5x5": (5, 5),
}
