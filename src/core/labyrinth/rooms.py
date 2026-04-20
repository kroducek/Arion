"""Systém vlastních místností — předdefinované šablony s garantovaným obsahem."""

import random

# Šablony vlastních místností.
# Každá šablona může přepsat popis a/nebo zaručit určité předměty/funkce.
CUSTOM_ROOM_TEMPLATES: list[dict] = [
    {
        "name": "Zbrojnice",
        "description": (
            "Prázdné zbraňové stojany lemují stěny. Nic tu nezbylo — "
            "nebo snad přece?"
        ),
        "guaranteed_items": ["nůž"],
        "has_chest": False,
        "has_ghost_arion": False,
    },
    {
        "name": "Laboratoř",
        "description": (
            "Reagencie jsou rozlité po pracovním stole. Zastaralý "
            "přístroj tiše bliká v rohu místnosti."
        ),
        "guaranteed_items": ["zapalovač"],
        "has_chest": False,
        "has_ghost_arion": False,
    },
    {
        "name": "Archiv",
        "description": (
            "Regály plné prachových svazků se tyčí ke stropu. "
            "Mezi listy dokumentů se skrývají tajemství."
        ),
        "guaranteed_items": [],
        "has_chest": True,
        "has_ghost_arion": False,
    },
    {
        "name": "Kaple",
        "description": (
            "Rozbitý oltář a převrácené lavice. Temné skvrny na dlažbě "
            "svědčí o čemsi, co se tu stalo."
        ),
        "guaranteed_items": ["svíčka", "zapalovač"],
        "has_chest": False,
        "has_ghost_arion": False,
    },
    {
        "name": "Kotelna",
        "description": (
            "Obří kotel s prasklým potrubím. Vzduch je horký a dusný. "
            "Někde tu musí být palivo."
        ),
        "guaranteed_items": ["kanystr"],
        "has_chest": False,
        "has_ghost_arion": False,
    },
    {
        "name": "Vězeňská cela",
        "description": (
            "Mříže jsou otevřené — zajatec utekl nebo byl odveden. "
            "Na podlaze jsou vyryty čárky počítající dny."
        ),
        "guaranteed_items": [],
        "has_chest": False,
        "has_ghost_arion": False,
    },
    {
        "name": "Temná kaple Arion",
        "description": (
            "Černé svíčky, vyhaslé. Na stěně je vyryto jméno: *Arion*. "
            "Vzduch vibruje přízračnou energií."
        ),
        "guaranteed_items": [],
        "has_chest": False,
        "has_ghost_arion": True,
        "force_dark": True,
    },
]


def apply_custom_rooms(game: dict, n_custom: int = 2) -> None:
    """Náhodně přiřadí šablony do n_custom ne-exitových, ne-startovních místností."""
    room_ids = list(game["map"].keys())
    start_room = room_ids[0]
    exit_room = game.get("exit_room", "")

    eligible = [
        r for r in room_ids
        if r != start_room and r != exit_room
    ]
    if not eligible:
        return

    # Nekombinuj ghost_arion šablonu pokud ghost_arion_used je již False (byl spawnut)
    ghost_used = game.get("ghost_arion_used") is not None

    chosen_rooms = random.sample(eligible, min(n_custom, len(eligible)))
    chosen_templates = random.sample(CUSTOM_ROOM_TEMPLATES, min(len(chosen_rooms), len(CUSTOM_ROOM_TEMPLATES)))

    for room_id, template in zip(chosen_rooms, chosen_templates):
        room = game["map"][room_id]

        # Přepsat popis
        room["description"] = template["description"]
        room["custom_name"] = template.get("name")

        # Přidat garantované předměty (pokud v místnosti ještě nejsou)
        for item in template.get("guaranteed_items", []):
            if item not in room["items"]:
                room["items"].append(item)

        # Truhla (přepíše případnou existující, pokud již není)
        if template.get("has_chest") and not room.get("chest"):
            from .constants import WEAPON_ITEMS
            room["chest"] = {
                "locked": True,
                "contents": ["kanystr", random.choice(WEAPON_ITEMS)],
            }
            game["chest_room"] = room_id

        # Ghost Arion (jen pokud ještě nebyl umístěn v jiné místnosti)
        if template.get("has_ghost_arion") and not ghost_used:
            # Odeber ghost z případné předchozí místnosti
            for r_id, r_data in game["map"].items():
                r_data["ghost_arion"] = False
            room["ghost_arion"] = True
            room["dark"] = True
            game["ghost_arion_used"] = False

        if template.get("force_dark"):
            room["dark"] = True
            room["candle_lit"] = False
