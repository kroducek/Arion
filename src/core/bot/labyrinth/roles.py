"""Definice rolí — ikony, popisy, startovní předměty."""

ROLE_INFO: dict[str, dict] = {
    # ── Nevinní ───────────────────────────────────────────────────────────────
    "detektiv": {
        "icon": "🕵️",
        "team": "innocent",
        "start_item": "pistole",
        "description": (
            "🕵️ **Detektiv** — začínáš s pistolí. Zastřel vraha a nevinní vyhrají.\n"
            "⚠️ **Kola 1 a 2 nemůžeš střílet** — pistole se nabíjí. "
            "Od kola 3 máš jeden výstřel. Po použití se pistole zničí."
        ),
    },
    "doktor": {
        "icon": "💊",
        "team": "innocent",
        "start_item": "lékárnička",
        "description": "💊 **Doktor** — začínáš s lékárničkou. Můžeš oživit jednoho mrtvého hráče (1× za hru).",
    },
    "skaut": {
        "icon": "👁️",
        "team": "innocent",
        "start_item": None,
        "description": (
            "👁️ **Skaut** — po každém pohybu dostaneš v DM rozšířené informace:\n"
            "• Kdo byl v tvé místnosti minulé kolo\n"
            "• Hint na směr nejbližšího kódu\n"
            "• Směr k hlasovací místnosti 🔴, truhle 📦 a Duchu Arion 🐱"
        ),
    },
    "technik": {
        "icon": "📡",
        "team": "innocent",
        "start_item": "skener",
        "description": "📡 **Technik** — máš skener. Použij ho v akční fázi pro hledání skrytých předmětů (včetně vzácného Amuletu Druhé Naděje).",
    },
    "blázen": {
        "icon": "🃏",
        "team": "innocent",
        "start_item": None,
        "description": "🃏 **Blázen** — dostaneš popis jiné třídy, ale nejsi to ty. Zjisti pravdu sám/sama.",
    },
    # ── Vrah ─────────────────────────────────────────────────────────────────
    "manipulátor": {
        "icon": "🎭",
        "team": "murderer",
        "start_item": "mačeta",
        "description": (
            "🎭 **JSI VRAH — MANIPULÁTOR!**\n"
            "Eliminuj všechny nevinné.\n"
            "**Speciální schopnost:** Vždy víš, kdo je Skaut. "
            "Když jste ve stejné místnosti, Skaut dostane příští kolo falešné informace místo pravých."
        ),
    },
    "pastičkář": {
        "icon": "🪤",
        "team": "murderer",
        "start_item": "mačeta",
        "description": (
            "🪤 **JSI VRAH — PASTIČKÁŘ!**\n"
            "Eliminuj všechny nevinné.\n"
            "**Speciální schopnost:** Můžeš pokládat pasti v místnostech. "
            "Hráč, který vstoupí do místnosti s pastí, nemůže příští kolo volit dveře. "
            "Ostatní ho mohou osvobodit. Ty dostaneš příležitost k vraždě chyceného hráče."
        ),
    },
    "sériový vrah": {
        "icon": "🔪",
        "team": "murderer",
        "start_item": "mačeta",
        "description": (
            "🔪 **JSI VRAH — SÉRIOVÝ VRAH!**\n"
            "Eliminuj všechny nevinné.\n"
            "**Speciální schopnost:** 1× za hru můžeš zabít 2 hráče najednou, "
            "i když nejsi úplně sám. Začínáš s Mačetou."
        ),
    },
}
