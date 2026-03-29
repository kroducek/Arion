"""
Door Labyrinth – sociálně-dedukční hra pro ArionBot
====================================================
Hráči se pohybují soukromými místnostmi (Discord vlákna) a snaží se
uniknout nebo odhalit vraha. Vrah se snaží eliminovat všechny nevinné.

Příkazy:
  /labyrinth_start         – vytvoří lobby
  /labyrinth_cancel        – admin zruší běžící hru
  /labyrinth_leaderboard   – žebříček výher
"""

import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands

from src.utils.paths import LABYRINTH_SCORES as SCORES_FILE
from src.utils.json_utils import load_json, save_json

# ══════════════════════════════════════════════════════════════════════════════
# KONSTANTY
# ══════════════════════════════════════════════════════════════════════════════

MIN_PLAYERS = 4
MAX_PLAYERS = 10

# Šance na tmavou místnost
DARK_ROOM_CHANCE = 0.30

# Barvy dveří (emoji + popisek)
DOOR_COLORS = [
    ("🔴", "Červené"),
    ("🟡", "Žluté"),
    ("🟢", "Zelené"),
    ("🔵", "Modré"),
]

# Třídy (role) nevinných hráčů
INNOCENT_ROLES = ["detektiv", "doktor", "skaut", "technik", "blázen"]

# Třídy vraha
MURDERER_ROLES = ["manipulátor", "pastičkář", "sériový vrah"]

# Předměty ve hře — běžné (spawn v místnostech)
ALL_ITEMS = ["baterka", "zapalovač", "svíčka", "kanystr"]
# Zbraně — vzácné (oddělený spawn pool)
WEAPON_ITEMS = ["nůž", "baseballka", "sekáček", "vrtačka"]

ITEM_EMOJI = {
    "pistole":    "🔫",
    "nůž":        "🔪",
    "baterka":    "🔦",
    "zapalovač":  "🪔",
    "svíčka":     "🕯️",
    "klíč":           "🗝️",
    "klíč od truhly": "🗝️",
    "lékárnička":     "💊",
    "skener":     "📡",
    "amulet":     "🔮",
    "baseballka": "🏏",
    "sekáček":    "🪓",
    "vrtačka":    "🔩",
    "mačeta":     "🗡️",
    "kanystr":    "⛽",
}

# Popis místností – pool 20+ atmosferických textů v češtině
ROOM_DESCRIPTIONS = [
    "Stěny jsou pokryté vlhkým mechem. Vzduch páchne hnilobou a starým dřevem.",
    "Rozbitá lucerna se houpe ze stropu. Její světlo vrhá klikaté stíny.",
    "Na podlaze leží rozházené listiny. Některé jsou potřísněné tmavou skvrnou.",
    "Místnost je ledová. Tvůj dech se mění v páru. Ticho je omračující.",
    "Z trhliny ve zdi prosákla voda a vytvořila louži uprostřed pokoje.",
    "Starý nábytek je převrhnutý. Někdo tu byl nedávno – velmi spěchal.",
    "Na stěně je vyryto číslo. Kdo to tu zanechal a proč?",
    "Vzduch voní po síře. Někde daleko zakřičel ptát, pak zase ticho.",
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

# Atmosferické lore texty pro čísla kódu při prohledávání
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

# ══════════════════════════════════════════════════════════════════════════════
# DATOVÁ VRSTVA
# ══════════════════════════════════════════════════════════════════════════════

def _load_scores() -> dict:
    return load_json(SCORES_FILE) or {}

def _save_scores(data: dict):
    save_json(SCORES_FILE, data)

def _record_win(uid: str):
    scores = _load_scores()
    scores[uid] = scores.get(uid, 0) + 1
    _save_scores(scores)

# ══════════════════════════════════════════════════════════════════════════════
# HERNÍ LOGIKA – pomocné funkce
# ══════════════════════════════════════════════════════════════════════════════

def _build_map(rows: int, cols: int) -> dict:
    """Vytvoří mapu místností jako slovník. Klíče: 'A1', 'A2', 'B1', ..."""
    rooms = {}
    labels_row = [chr(ord("A") + r) for r in range(rows)]

    for r, row_label in enumerate(labels_row):
        for c in range(1, cols + 1):
            room_id = f"{row_label}{c}"
            connections = []
            # nahoru
            if r > 0:
                connections.append(f"{labels_row[r-1]}{c}")
            # dolů
            if r < rows - 1:
                connections.append(f"{labels_row[r+1]}{c}")
            # vlevo
            if c > 1:
                connections.append(f"{row_label}{c-1}")
            # vpravo
            if c < cols:
                connections.append(f"{row_label}{c+1}")

            rooms[room_id] = {
                "thread_id": None,
                "description": random.choice(ROOM_DESCRIPTIONS),
                "connections": connections,
                "players": [],
                "items": [],
                "code_number": None,
                "code_found": False,
                "bodies": [],
                "is_exit": False,
                "has_key": False,
                "last_round_players": [],
                "dark": False,
                "candle_lit": False,
                "trap": None,
                "vote_room": False,
                "chest": None,       # None nebo {"locked": True, "contents": [...]}
                "ghost_arion": False,
            }
    return rooms

def _scatter_items_and_codes(game: dict):
    """Rozmístí předměty, klíč, čísla kódu, výstup, hlasovací místnost a tmu po mapě."""
    room_ids = list(game["map"].keys())
    n_rooms = len(room_ids)
    start_room = room_ids[0]

    # ── Výstupní místnost: vždy v rohu (2 dveře = poklop, těžší najít) ─────────
    rows_g = game.get("rows", 3)
    cols_g = game.get("cols", 3)
    row_labels = [chr(ord("A") + r) for r in range(rows_g)]
    corner_ids = {
        f"{row_labels[0]}1", f"{row_labels[0]}{cols_g}",
        f"{row_labels[-1]}1", f"{row_labels[-1]}{cols_g}",
    }
    exit_candidates = [r for r in room_ids if r != start_room and r in corner_ids]
    if not exit_candidates:
        exit_candidates = [r for r in room_ids if r != start_room]
    exit_room = random.choice(exit_candidates)
    game["map"][exit_room]["is_exit"] = True
    game["exit_room"] = exit_room

    # ── Hlasovací místnost (1, ne exit ani start) ─────────────────────────────
    vote_candidates = [r for r in room_ids if r not in (start_room, exit_room)]
    if vote_candidates:
        vote_room_id = random.choice(vote_candidates)
        game["map"][vote_room_id]["vote_room"] = True
        game["vote_room_id"] = vote_room_id

    # ── Počet kódů škáluje s mapou ─────────────────────────────────────────
    n_codes = max(4, n_rooms // 4)
    game["total_codes"] = n_codes

    code_pool = [r for r in room_ids if r not in (exit_room,)]
    code_rooms = random.sample(code_pool, min(n_codes, len(code_pool)))
    game["exit_code"] = []
    for room_id in code_rooms:
        num = random.randint(0, 9)
        game["map"][room_id]["code_number"] = num
        game["exit_code"].append(num)

    non_exit_rooms = [r for r in room_ids if r != exit_room]

    # ── Tmavé místnosti (~25%, ne start, ne exit, ne místnosti s kódy) ─────────
    code_room_ids = set(code_rooms)
    dark_candidates = [r for r in room_ids if r not in (start_room, exit_room) and r not in code_room_ids]
    for room_id in dark_candidates:
        if random.random() < DARK_ROOM_CHANCE:
            game["map"][room_id]["dark"] = True

    # ── Garantovaný loot v každé neprázdné ne-exitové místnosti ─────────────────
    # Každá místnost dostane 1-2 běžné předměty (bez duplikátů)
    common_items_all = ["baterka", "zapalovač", "svíčka", "kanystr"]
    for room_id in non_exit_rooms:
        count = 1 if game["map"][room_id].get("dark") else random.randint(1, 2)
        pool = common_items_all * 2
        random.shuffle(pool)
        seen: set[str] = set()
        items: list[str] = []
        for item in pool:
            if item not in seen and len(items) < count:
                seen.add(item)
                items.append(item)
        game["map"][room_id]["items"] = items

    # ── Vzácné zbraně (1 na 3 místnosti, max 1 per místnost) ────────────────────
    n_weapons = max(1, n_rooms // 3)
    weapon_candidates = [r for r in non_exit_rooms if not game["map"][r].get("dark")]
    if len(weapon_candidates) < n_weapons:
        weapon_candidates = list(non_exit_rooms)
    for room_id in random.sample(weapon_candidates, min(n_weapons, len(weapon_candidates))):
        weapon = random.choice(WEAPON_ITEMS)
        if weapon not in game["map"][room_id]["items"]:
            game["map"][room_id]["items"].append(weapon)

    # ── Garantovat dostatek kanystru: min(6, n_rooms//2 + 2), přednost ne-tmavým ──
    # Kanystry: základ ze velikosti mapy (3 nutné + buffer ~n_rooms/4), max 10
    target_fuel = max(5, min(n_rooms // 3 + 3, 10))
    spawned_fuel = sum(1 for r in game["map"].values() for i in r["items"] if i == "kanystr")
    extra_needed = max(0, target_fuel - spawned_fuel)
    if extra_needed > 0:
        fuel_candidates = [r for r in non_exit_rooms if r != start_room and not game["map"][r].get("dark")]
        if not fuel_candidates:
            fuel_candidates = [r for r in non_exit_rooms if r != start_room]
        placed = 0
        attempts = 0
        cands = fuel_candidates[:]
        random.shuffle(cands)
        while placed < extra_needed and attempts < len(cands) * 2:
            room_id = cands[attempts % len(cands)]
            attempts += 1
            if "kanystr" not in game["map"][room_id]["items"]:
                game["map"][room_id]["items"].append("kanystr")
                placed += 1

    # ── Amulet Druhé Naděje (1–2 kusy, vzácný) ───────────────────────────────────
    amulet_count = 1 if n_rooms <= 16 else 2
    amulet_candidates = [r for r in non_exit_rooms if r != start_room]
    for room_id in random.sample(amulet_candidates, min(amulet_count, len(amulet_candidates))):
        if "amulet" not in game["map"][room_id]["items"]:
            game["map"][room_id]["items"].append("amulet")

    # ── Truhla (1 místnost, ne start, ne exit, ne temná) ─────────────────────────
    chest_candidates = [r for r in non_exit_rooms if r != start_room and not game["map"][r].get("dark")]
    if not chest_candidates:
        chest_candidates = [r for r in non_exit_rooms if r != start_room]
    if chest_candidates:
        chest_room = random.choice(chest_candidates)
        chest_weapon = random.choice(WEAPON_ITEMS)
        game["map"][chest_room]["chest"] = {
            "locked": True,
            "contents": ["kanystr", chest_weapon],
        }
        game["chest_room"] = chest_room

    # ── Duch Temné Arion (1 tmavá místnost, ne start, ne exit) ───────────────────
    dark_rooms = [r for r in non_exit_rooms if r != start_room and game["map"][r].get("dark")]
    if dark_rooms:
        ghost_room = random.choice(dark_rooms)
        game["map"][ghost_room]["ghost_arion"] = True
        game["ghost_arion_used"] = False

def _room_direction(from_id: str, to_id: str) -> str:
    """Vrátí světovou stranu z from_id do to_id (sever/jih/východ/západ)."""
    from_row = ord(from_id[0].upper()) - ord("A")
    from_col = int(from_id[1:]) - 1
    to_row   = ord(to_id[0].upper())   - ord("A")
    to_col   = int(to_id[1:])   - 1
    dr = to_row - from_row
    dc = to_col - from_col
    if abs(dr) >= abs(dc):
        return "jih" if dr > 0 else "sever"
    return "východ" if dc > 0 else "západ"

def _alive_players(game: dict) -> list:
    return [uid for uid, pdata in game["players"].items() if pdata["alive"]]

def _innocents_alive(game: dict) -> list:
    murderer_uid = game.get("murderer_uid", "")
    return [uid for uid, pdata in game["players"].items()
            if pdata["alive"] and uid != murderer_uid]

def _room_of(game: dict, uid: str) -> str:
    return game["players"][uid]["room"]

def _players_in_room(game: dict, room_id: str) -> list:
    return game["map"][room_id]["players"]

def _item_list_str(items: list) -> str:
    if not items:
        return "žádné"
    return ", ".join(f"{ITEM_EMOJI.get(i, '?')} {i}" for i in items)

def _check_win(game: dict) -> str | None:
    """Vrátí 'murderer', 'innocents', nebo None.
    - Nevinní vyhrají pokud vrah zemře NEBO všichni nevinní unikli/zemřeli a alespoň jeden unikl.
    - Vrah vyhraje pokud žádný nevinný není naživu, v čekárně ani neunikl."""
    murderer_uid = game.get("murderer_uid", "")
    murderer_alive = game["players"][murderer_uid]["alive"]

    if not murderer_alive:
        return "innocents"

    alive_inn = _innocents_alive(game)
    pending_uids = {r["uid"] for r in game.get("pending_revivals", [])}
    pending_inn = [uid for uid in pending_uids if uid != murderer_uid]

    if not alive_inn and not pending_inn:
        # Nikdo živý — zkontrolovat zda někdo unikl
        escaped_inn = [
            uid for uid, p in game["players"].items()
            if uid != murderer_uid and p.get("escaped")
        ]
        return "innocents" if escaped_inn else "murderer"

    return None


def _render_map(game: dict, current_room: str | None = None, hide_exit: bool = False) -> str:
    """Vrátí ASCII mini-mapu jako Discord code block.

    Legenda:
      [X1] = místnost kde právě jsi
       X1E = exit místnost (viditelná po oznámení)
       X1  = běžná místnost
    """
    rows = game["rows"]
    cols = game["cols"]
    gmap = game["map"]
    exit_room = game.get("exit_room", "")
    exit_announced = bool(game.get("exit_announced")) and not hide_exit
    exit_opened = bool(game.get("exit_opened")) and not hide_exit

    # Každá buňka je přesně 4 znaky (pro room_id délky 2: A1–E6)
    sep = "+" + "+".join(["----"] * cols) + "+"
    lines = [sep]

    for r in range(rows):
        row_label = chr(ord("A") + r)
        cells = []
        for c in range(1, cols + 1):
            room_id = f"{row_label}{c}"
            room = gmap[room_id]

            if room_id == current_room:
                cell = f"[{room_id}]"               # [A1]
            elif room["is_exit"] and exit_opened:
                cell = f" {room_id}O"               #  C3O  (otevřeno)
            elif room["is_exit"] and exit_announced:
                cell = f" {room_id}E"               #  C3E  (nalezeno)
            else:
                cell = f" {room_id} "               #  A1
            cells.append(cell)

        lines.append("|" + "|".join(cells) + "|")
        lines.append(sep)

    legend_parts = []
    if current_room:
        legend_parts.append(f"[{current_room}] = jsi zde")
    if exit_opened:
        legend_parts.append(f"O = EXIT OTEVŘEN ({exit_room})")
    elif exit_announced:
        legend_parts.append(f"E = EXIT nalezen ({exit_room})")
    if legend_parts:
        lines.append("  |  ".join(legend_parts))

    return "```\n" + "\n".join(lines) + "\n```"


# ══════════════════════════════════════════════════════════════════════════════
# VIEW – LOBBY
# ══════════════════════════════════════════════════════════════════════════════

MAP_SIZES = {
    "3x3": (3, 3),
    "4x4": (4, 4),
    "4x6": (4, 6),
    "5x5": (5, 5),
}

# ══════════════════════════════════════════════════════════════════════════════
# MODAL – ZADÁNÍ KÓDU PŘI ÚTĚKU
# ══════════════════════════════════════════════════════════════════════════════

class ExitCodeModal(discord.ui.Modal, title="🔐 Zadej únikový kód"):
    """Modal pro zadání kombinace čísel při pokusu o útěk."""

    code_input = discord.ui.TextInput(
        label="Číslice kódu (mezerami nebo dohromady)",
        placeholder="např.  3 7 2 5  nebo  3725",
        required=True,
        max_length=60,
    )

    def __init__(self, cog: "LabyrinthCog", game: dict, channel_id: int, uid: str):
        super().__init__()
        self.cog = cog
        self.game = game
        self.channel_id = channel_id
        self.uid = uid

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.code_input.value.strip().replace(",", "").replace(" ", "")
        digits = [int(c) for c in raw if c.isdigit()]
        correct = sorted(self.game.get("exit_code", []))
        if sorted(digits) == correct:
            channel = interaction.client.get_channel(self.channel_id)
            await interaction.response.defer(ephemeral=True)
            await self.cog._handle_escape(self.channel_id, self.uid, channel)
        else:
            found_str = " ".join(str(n) for n in self.game.get("found_codes", []))
            await interaction.response.send_message(
                f"❌ **Nesprávný kód!** Zkontroluj zadaná čísla a zkus znovu.\n"
                f"*Kolektivní kód: `{found_str}`*",
                ephemeral=True,
            )

class TutorialReadyView(discord.ui.View):
    """Zobrazí se před kolo 1 — hráči potvrdí, že jsou připraveni."""

    def __init__(self, players: list[discord.Member], cog: "LabyrinthCog", channel_id: int):
        super().__init__(timeout=90)
        self._players: set[int] = {m.id for m in players}
        self._ready: set[int] = set()
        self._event: asyncio.Event = asyncio.Event()
        self._cog = cog
        self._channel_id = channel_id

    @discord.ui.button(label="✅ Připraven/a", style=discord.ButtonStyle.success,
                       custom_id="lab_tutorial_ready")
    async def ready_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if uid not in self._players:
            await interaction.response.send_message("Nejsi součástí této hry.", ephemeral=True)
            return
        self._ready.add(uid)
        remaining = len(self._players) - len(self._ready)
        if remaining > 0:
            await interaction.response.send_message(
                f"✅ Připraven/a! Čekáme ještě na **{remaining}** hráče.",
                ephemeral=True,
            )
        else:
            await interaction.response.defer()
            self._event.set()

    async def on_timeout(self):
        self._event.set()

    async def wait_ready(self):
        await self._event.wait()


class LabyrinthLobby(discord.ui.View):
    def __init__(self, cog: "LabyrinthCog", author: discord.Member):
        super().__init__(timeout=None)
        self.cog = cog
        self.author = author
        self.players: list[discord.Member] = [author]
        self.map_size: tuple[int, int] = (4, 4)
        self._add_size_select()

    def _add_size_select(self):
        options = [
            discord.SelectOption(label="3×3 (9 místností)", value="3x3"),
            discord.SelectOption(label="4×4 (16 místností)", value="4x4", default=True),
            discord.SelectOption(label="4×6 (24 místností)", value="4x6"),
            discord.SelectOption(label="5×5 (25 místností)", value="5x5"),
        ]
        select = discord.ui.Select(
            placeholder="Velikost mapy…",
            options=options,
            custom_id="lab_map_size",
            row=0,
        )
        select.callback = self._size_selected
        self.add_item(select)

    async def _size_selected(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Pouze zakladatel volí mapu.", ephemeral=True)
            return
        value = interaction.data["values"][0]
        self.map_size = MAP_SIZES[value]
        await interaction.response.edit_message(embed=self._embed())

    def _embed(self) -> discord.Embed:
        rows, cols = self.map_size
        names = "\n".join(f"• {p.display_name}" for p in self.players)
        embed = discord.Embed(
            title="🚪 Door Labyrinth — Lobby",
            description=(
                "Sociálně-dedukční hra. Jeden hráč je **Vrah**, ostatní jsou **Nevinní**.\n"
                "Unikni přes výstup (generátor + kód) nebo odhal vraha!\n\n"
                "**Třídy nevinných:** Detektiv 🕵️ · Doktor 💊 · Skaut 👁️ · Technik 📡 · Blázen 🃏\n"
                "**Třídy vraha:** Manipulátor 🎭 · Pastičkář 🪤 · Sériový vrah 🔪\n"
            ),
            color=0x8B0000,
        )
        embed.add_field(name=f"Hráči ({len(self.players)}/{MAX_PLAYERS})", value=names, inline=True)
        embed.add_field(name="Mapa", value=f"{rows}×{cols} ({rows * cols} místností)", inline=True)
        embed.set_footer(text=f"Min. {MIN_PLAYERS} hráčů | Zakladatel spouští hru")
        return embed

    @discord.ui.button(label="Připojit se", style=discord.ButtonStyle.success,
                       custom_id="lab_join", row=1)
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in [p.id for p in self.players]:
            await interaction.response.send_message("Už jsi v lobby!", ephemeral=True)
            return
        if len(self.players) >= MAX_PLAYERS:
            await interaction.response.send_message("Lobby je plné.", ephemeral=True)
            return
        self.players.append(interaction.user)
        await interaction.response.edit_message(embed=self._embed())

    @discord.ui.button(label="Odejít", style=discord.ButtonStyle.secondary,
                       custom_id="lab_leave", row=1)
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.author.id:
            await interaction.response.send_message("Zakladatel nemůže odejít.", ephemeral=True)
            return
        if interaction.user.id not in [p.id for p in self.players]:
            await interaction.response.send_message("Nejsi v lobby.", ephemeral=True)
            return
        self.players = [p for p in self.players if p.id != interaction.user.id]
        await interaction.response.edit_message(embed=self._embed())

    @discord.ui.button(label="▶ Spustit", style=discord.ButtonStyle.primary,
                       custom_id="lab_start_btn", row=1)
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Pouze zakladatel spouští hru.", ephemeral=True)
            return
        if len(self.players) < MIN_PLAYERS:
            await interaction.response.send_message(
                f"Potřebuješ alespoň {MIN_PLAYERS} hráče!", ephemeral=True
            )
            return
        self.stop()
        await interaction.response.edit_message(
            content="🚪 **Door Labyrinth** — Hra se připravuje…", embed=None, view=None
        )
        await self.cog._init_game(interaction.channel, self.players, self.map_size)

    @discord.ui.button(label="🔧 Test (Admin)", style=discord.ButtonStyle.secondary,
                       custom_id="lab_test_btn", row=2)
    async def test_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Pouze admin.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(
            content="🔧 **Door Labyrinth** — Testovací spuštění…", embed=None, view=None
        )
        await self.cog._init_game(interaction.channel, self.players, self.map_size)

    @discord.ui.button(label="🚫 Zrušit", style=discord.ButtonStyle.danger,
                       custom_id="lab_cancel_lobby", row=2)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_admin = interaction.user.guild_permissions.administrator
        if interaction.user.id != self.author.id and not is_admin:
            await interaction.response.send_message("Pouze zakladatel nebo admin.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(content="🚫 Lobby zrušeno.", embed=None, view=None)


# ══════════════════════════════════════════════════════════════════════════════
# VIEW – VÝBĚR DVEŘÍ (pohyb)
# ══════════════════════════════════════════════════════════════════════════════

class DoorChoiceView(discord.ui.View):
    """
    Jeden View per room per kolo.
    Tlačítka = barevné dveře s kapacitami.
    Každý hráč může kliknout jednou. Kapacita se snižuje.
    Když všichni hráči globálně vyberou, spustí se pohyb.
    """

    def __init__(self, cog: "LabyrinthCog", game: dict, room_id: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.game = game
        self.room_id = room_id
        self.channel_id: int = game["channel_id"]
        # door_data: list of (target_room_id, capacity, color_emoji, color_name)
        self.door_data: list[tuple[str, int, str, str]] = []
        # Trapped hráči mají door_assignment už nastavený — nepotřebují volit
        self.chosen: set[str] = {
            uid for uid in game["map"][room_id]["players"]
            if game["players"].get(uid, {}).get("trapped")
        }
        self._build_buttons()

    def _build_buttons(self):
        room = self.game["map"][self.room_id]
        connections = room["connections"]
        # Kapacita dveří = 1..počet živých hráčů (škáluje s průběhem hry)
        alive_count = len(_alive_players(self.game))
        capacities = [random.randint(1, max(alive_count, 2)) for _ in connections]
        colors = random.sample(DOOR_COLORS, min(len(connections), len(DOOR_COLORS)))
        while len(colors) < len(connections):
            colors.append(random.choice(DOOR_COLORS))

        self.door_data = []
        for i, (target_id, cap) in enumerate(zip(connections, capacities)):
            emoji, color_name = colors[i]
            self.door_data.append((target_id, cap, emoji, color_name))
            btn = discord.ui.Button(
                label=f"{emoji} {color_name} [{cap}] → {target_id}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"door_{self.room_id}_{target_id}",
                row=min(i // 2, 1),
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)

        stay_btn = discord.ui.Button(
            label="🏠 Zůstat",
            style=discord.ButtonStyle.secondary,
            custom_id=f"stay_{self.room_id}",
            row=2,
        )
        stay_btn.callback = self._stay_callback
        self.add_item(stay_btn)

        inv_btn = discord.ui.Button(
            label="🎒 Inventář",
            style=discord.ButtonStyle.secondary,
            custom_id=f"inv_{self.room_id}",
            row=2,
        )
        inv_btn.callback = self._inv_callback
        self.add_item(inv_btn)

    async def _inv_callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        pdata = self.game["players"].get(uid)
        if not pdata:
            await interaction.response.send_message("Nejsi hráčem.", ephemeral=True)
            return
        items_str = _item_list_str(pdata["items"])
        found = sorted(self.game.get("found_codes", []))
        total_codes = self.game.get("total_codes", 6)
        nums_str = ", ".join(str(n) for n in found) or "žádná"
        gen_fuel = self.game.get("generator_fuel", 0)
        gen_str = "✅ Spuštěn" if self.game.get("generator_started") else f"⛽ {gen_fuel}/3"
        await interaction.response.send_message(
            f"**🎒 Tvůj inventář:**\n"
            f"Předměty: {items_str}\n"
            f"🔢 Kolektivní kód: {nums_str} *({len(found)}/{total_codes})*\n"
            f"🔌 Generátor: {gen_str}",
            ephemeral=True,
        )

    def _make_callback(self, door_index: int):
        async def callback(interaction: discord.Interaction):
            uid = str(interaction.user.id)
            # Kontrola: hráč musí být v této místnosti a nesmí ještě vybrat
            pdata = self.game["players"].get(uid)
            if not pdata or not pdata["alive"]:
                await interaction.response.send_message("Nejsi aktivní hráč.", ephemeral=True)
                return
            if pdata["room"] != self.room_id:
                await interaction.response.send_message("Nejsi v této místnosti.", ephemeral=True)
                return
            if uid in self.chosen:
                await interaction.response.send_message("Dveře jsi už zvolil/a.", ephemeral=True)
                return

            # Trapped hráč nemůže volit dveře (může jen zůstat)
            if pdata.get("trapped"):
                await interaction.response.send_message(
                    "🪤 Jsi chycen/a v pasti! Nemůžeš se pohnout toto kolo. Čekej, nebo tě někdo osvobodí.",
                    ephemeral=True,
                )
                return

            target_id, cap, emoji, color_name = self.door_data[door_index]
            if cap <= 0:
                await interaction.response.send_message(
                    f"Dveře {emoji} jsou plné – zvol jiné.", ephemeral=True
                )
                return

            # Snížit kapacitu
            self.door_data[door_index] = (target_id, cap - 1, emoji, color_name)
            self.chosen.add(uid)

            # Uložit volbu hráče
            pdata["door_assignment"] = target_id
            self.game["pending_choices"] -= 1

            # Obnovit tlačítka + soukromé potvrzení
            await self._refresh_buttons(interaction)
            await interaction.followup.send(
                f"✅ Zvolil/a jsi **{emoji} {color_name}** → **{target_id}**",
                ephemeral=True,
            )

            # Race condition guard: spustit pohyb jen jednou
            if self.game["pending_choices"] <= 0 and not self.game.get("movement_triggered"):
                self.game["movement_triggered"] = True
                await self.cog._execute_movement(self.channel_id)

        return callback

    async def _stay_callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        pdata = self.game["players"].get(uid)
        if not pdata or not pdata["alive"]:
            await interaction.response.send_message("Nejsi aktivní hráč.", ephemeral=True)
            return
        if pdata["room"] != self.room_id:
            await interaction.response.send_message("Nejsi v této místnosti.", ephemeral=True)
            return
        if uid in self.chosen:
            await interaction.response.send_message("Rozhodnutí jsi už učinil/a.", ephemeral=True)
            return
        if pdata.get("trapped"):
            await interaction.response.send_message(
                "🪤 Jsi chycen/a v pasti — automaticky zůstáváš, nepotřebuješ klikat.", ephemeral=True
            )
            return

        self.chosen.add(uid)
        pdata["door_assignment"] = self.room_id
        self.game["pending_choices"] -= 1

        await interaction.response.send_message(
            f"🏠 Zůstáváš v místnosti **{self.room_id}**.", ephemeral=True
        )
        if self.game["pending_choices"] <= 0 and not self.game.get("movement_triggered"):
            self.game["movement_triggered"] = True
            await self.cog._execute_movement(self.channel_id)

    async def _refresh_buttons(self, interaction: discord.Interaction):
        """Přepíše popisky tlačítek (kapacity) a deaktivuje plné dveře."""
        self.clear_items()
        for i, (target_id, cap, emoji, color_name) in enumerate(self.door_data):
            disabled = cap <= 0
            btn = discord.ui.Button(
                label=f"{emoji} {color_name} [{cap}] → {target_id}",
                style=discord.ButtonStyle.secondary if not disabled else discord.ButtonStyle.danger,
                custom_id=f"door_{self.room_id}_{target_id}_r{i}",
                disabled=disabled,
                row=min(i // 2, 1),
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)
        stay_btn = discord.ui.Button(
            label="🏠 Zůstat",
            style=discord.ButtonStyle.secondary,
            custom_id=f"stay_{self.room_id}_r",
            row=2,
        )
        stay_btn.callback = self._stay_callback
        self.add_item(stay_btn)
        inv_btn = discord.ui.Button(
            label="🎒 Inventář",
            style=discord.ButtonStyle.secondary,
            custom_id=f"inv_{self.room_id}_r",
            row=2,
        )
        inv_btn.callback = self._inv_callback
        self.add_item(inv_btn)
        await interaction.response.edit_message(view=self)

    async def on_timeout(self):
        """Pokud hráči nevyberou dveře včas, zůstanou v aktuální místnosti."""
        game = self.game
        if game.get("movement_triggered"):
            return
        alive = _alive_players(game)
        for uid in alive:
            pdata = game["players"][uid]
            if pdata["room"] == self.room_id and uid not in self.chosen:
                pdata["door_assignment"] = self.room_id  # zůstat
                game["pending_choices"] -= 1
        channel = self.cog.bot.get_channel(self.channel_id)
        # Upozornit místnost, že čas vypršel
        if channel:
            room = game["map"].get(self.room_id, {})
            tid = room.get("thread_id")
            if tid:
                thread = channel.guild.get_channel_or_thread(tid)
                if thread:
                    asyncio.create_task(
                        thread.send("⏱️ Čas na výběr dveří vypršel — kolo se přesouvá…")
                    )
        if game["pending_choices"] <= 0 and not game.get("movement_triggered"):
            game["movement_triggered"] = True  # nastaven vždy, i když channel je None
            if channel:
                asyncio.create_task(self.cog._execute_movement(self.channel_id))
            else:
                # Pokusit se znovu — channel mohl být dočasně uncached
                async def _retry():
                    await asyncio.sleep(1)
                    ch = self.cog.bot.get_channel(self.channel_id)
                    if ch:
                        await self.cog._execute_movement(self.channel_id)
                asyncio.create_task(_retry())


# ══════════════════════════════════════════════════════════════════════════════
# VIEW – AKCE V MÍSTNOSTI
# ══════════════════════════════════════════════════════════════════════════════

class RoomActionView(discord.ui.View):
    """Veřejný gateway embed v místnostním vlákně — každý hráč si otevře svůj panel."""

    def __init__(self, cog: "LabyrinthCog", game: dict, room_id: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.game = game
        self.room_id = room_id
        self.channel_id: int = game["channel_id"]

        actions_btn = discord.ui.Button(
            label="🎯 Moje akce",
            style=discord.ButtonStyle.primary,
            custom_id=f"lab_myactions_{room_id}",
            row=0,
        )
        actions_btn.callback = self._open_personal_panel
        self.add_item(actions_btn)

        done_btn = discord.ui.Button(
            label="✅ Zakončit tah",
            style=discord.ButtonStyle.success,
            custom_id=f"lab_done_{room_id}",
            row=0,
        )
        done_btn.callback = self._done_cb
        self.add_item(done_btn)

    async def _open_personal_panel(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        pdata = self.game["players"].get(uid)
        if not pdata or not pdata["alive"]:
            await interaction.response.send_message("Nejsi aktivní hráč.", ephemeral=True)
            return
        if pdata["room"] != self.room_id:
            await interaction.response.send_message("Nejsi v této místnosti.", ephemeral=True)
            return
        panel = PersonalActionView(self.cog, self.game, self.room_id, uid)
        inv_str = _item_list_str(pdata["items"]) or "žádné"
        found = sorted(self.game.get("found_codes", []))
        total = self.game.get("total_codes", 6)
        gen_fuel = self.game.get("generator_fuel", 0)
        gen_str = "✅ Spuštěn" if self.game.get("generator_started") else f"⛽ {gen_fuel}/3"
        murderer_uid = self.game.get("murderer_uid", "")
        is_murderer = uid == murderer_uid
        # Exit lokace — jen pro nevinné; počet nevinných — jen pro vraha
        extra_info = ""
        if is_murderer:
            inn_count = len(_innocents_alive(self.game))
            extra_info = f"\n🎯 Zbývá **{inn_count}** nevinných."
        else:
            if self.game.get("exit_opened"):
                extra_info = f"\n🚪 EXIT OTEVŘEN — místnost **{self.game['exit_room']}**"
            elif self.game.get("exit_announced"):
                extra_info = f"\n📍 EXIT: místnost **{self.game['exit_announced']}**"
        map_str = _render_map(self.game, self.room_id, hide_exit=is_murderer)
        room = self.game["map"][self.room_id]
        candle_hint = ""
        if (
            "svíčka" in pdata["items"]
            and "zapalovač" in pdata["items"]
            and not room.get("candle_lit")
            and not room.get("dark")
        ):
            candle_hint = "\n💡 *Svíčka se dá zapálit pouze v tmavé místnosti.*"
        await interaction.response.send_message(
            f"**🎯 Tvoje akce — Místnost {self.room_id}**\n"
            f"🎒 Inventář: {inv_str}\n"
            f"🔌 Generátor: {gen_str} | 🔢 Kód: {', '.join(str(n) for n in found) or '—'} ({len(found)}/{total})"
            f"{extra_info}{candle_hint}\n{map_str}",
            view=panel,
            ephemeral=True,
        )

    async def _done_cb(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        pdata = self.game["players"].get(uid)
        if not pdata or not pdata["alive"]:
            await interaction.response.send_message("Nejsi aktivní hráč.", ephemeral=True)
            return
        if pdata["room"] != self.room_id:
            await interaction.response.send_message("Nejsi v této místnosti.", ephemeral=True)
            return
        done_set = self.game.get("actions_done", set())
        if uid in done_set:
            await interaction.response.send_message("Tah jsi už zakončil/a.", ephemeral=True)
            return
        done_set.add(uid)
        self.game["actions_done"] = done_set
        await interaction.response.send_message("✅ Tah zakončen. Čekáš na ostatní.", ephemeral=True)
        alive_uids = set(_alive_players(self.game))
        if alive_uids.issubset(done_set):
            event = self.game.get("round_done_event")
            if event and not event.is_set():
                event.set()


# ══════════════════════════════════════════════════════════════════════════════
# VIEW – OSOBNÍ PANEL AKCÍ (ephemeral, per-hráč)
# ══════════════════════════════════════════════════════════════════════════════

class PersonalActionView(discord.ui.View):
    """Ephemeral panel s akcemi přizpůsobenými konkrétnímu hráči."""

    def __init__(self, cog: "LabyrinthCog", game: dict, room_id: str, uid: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.game = game
        self.room_id = room_id
        self.uid = uid
        self.channel_id: int = game["channel_id"]

        pdata = game["players"][uid]
        room = game["map"][room_id]
        alive_here = [u for u in room["players"] if game["players"][u]["alive"]]
        murderer_uid = game.get("murderer_uid", "")

        row = 0

        # Prohledat — vždy
        search_btn = discord.ui.Button(
            label="🔍 Prohledat místnost",
            style=discord.ButtonStyle.primary,
            custom_id=f"pa_search_{uid}_{room_id}",
            row=row,
        )
        search_btn.callback = self._search_cb
        self.add_item(search_btn)

        # EXIT akce — pouze nevinní v exit místnosti
        if room["is_exit"] and uid != murderer_uid:
            row += 1
            exit_btn = discord.ui.Button(
                label="🚪 Pokus o útěk",
                style=discord.ButtonStyle.success,
                custom_id=f"pa_escape_{uid}_{room_id}",
                row=row,
            )
            exit_btn.callback = self._escape_cb
            self.add_item(exit_btn)
            if not game.get("exit_announced"):
                ann_btn = discord.ui.Button(
                    label="📢 Oznámit EXIT",
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"pa_announce_{uid}_{room_id}",
                    row=row,
                )
                ann_btn.callback = self._announce_cb
                self.add_item(ann_btn)

        # Vložit kanystr — exit místnost, má kanystr, generátor ještě neběží, jen nevinní
        if room["is_exit"] and uid != murderer_uid and "kanystr" in pdata["items"] and not game.get("generator_started"):
            fuel = game.get("generator_fuel", 0)
            row += 1
            fuel_btn = discord.ui.Button(
                label=f"⛽ Vložit kanystr ({fuel}/3)",
                style=discord.ButtonStyle.primary,
                custom_id=f"pa_fuel_{uid}_{room_id}",
                row=row,
            )
            fuel_btn.callback = self._deposit_fuel_cb
            self.add_item(fuel_btn)

        # Střílet — má pistoli, cooldown vypršel, jsou tu jiní živí
        if "pistole" in pdata["items"] and pdata.get("pistol_cooldown", 0) == 0 and len(alive_here) >= 2:
            row += 1
            shoot_btn = discord.ui.Button(
                label="🔫 Vystřelit",
                style=discord.ButtonStyle.danger,
                custom_id=f"pa_shoot_{uid}_{room_id}",
                row=row,
            )
            shoot_btn.callback = self._shoot_cb
            self.add_item(shoot_btn)

        # Prohledat těla — jsou tu mrtvoly s předměty
        bodies_with_items = [b for b in room["bodies"] if b.get("items")]
        if bodies_with_items:
            row += 1
            loot_btn = discord.ui.Button(
                label="⚰️ Prohledat těla",
                style=discord.ButtonStyle.secondary,
                custom_id=f"pa_loot_{uid}_{room_id}",
                row=row,
            )
            loot_btn.callback = self._loot_bodies_cb
            self.add_item(loot_btn)

        # Nechat věc u těla — hráč má itemy a jsou tu mrtvoly
        if pdata["items"] and room["bodies"]:
            row += 1
            drop_btn = discord.ui.Button(
                label="📤 Nechat věc",
                style=discord.ButtonStyle.secondary,
                custom_id=f"pa_drop_{uid}_{room_id}",
                row=row,
            )
            drop_btn.callback = self._drop_item_cb
            self.add_item(drop_btn)

        # Oživit — doktor s lékárničkou, jsou tu mrtvoly
        if pdata["role"] == "doktor" and "lékárnička" in pdata["items"] and room["bodies"] and not pdata.get("revived_this_game"):
            row += 1
            revive_btn = discord.ui.Button(
                label="💊 Oživit mrtvolu",
                style=discord.ButtonStyle.secondary,
                custom_id=f"pa_revive_{uid}_{room_id}",
                row=row,
            )
            revive_btn.callback = self._revive_cb
            self.add_item(revive_btn)

        # Skenovat — technik se skenerem
        if pdata["role"] == "technik" and "skener" in pdata["items"] and not pdata.get("scanned_this_round"):
            row += 1
            scan_btn = discord.ui.Button(
                label="📡 Skenovat",
                style=discord.ButtonStyle.primary,
                custom_id=f"pa_scan_{uid}_{room_id}",
                row=row,
            )
            scan_btn.callback = self._scan_cb
            self.add_item(scan_btn)

        # Zapálit svíčku — tmavá místnost + svíčka + zapalovač
        if room.get("dark") and not room.get("candle_lit") and "svíčka" in pdata["items"] and "zapalovač" in pdata["items"]:
            row += 1
            candle_btn = discord.ui.Button(
                label="🕯️ Zapálit svíčku",
                style=discord.ButtonStyle.secondary,
                custom_id=f"pa_candle_{uid}_{room_id}",
                row=row,
            )
            candle_btn.callback = self._candle_cb
            self.add_item(candle_btn)

        # Hlasování — hlasovací místnost, ještě nebylo, jen nevinní
        if room.get("vote_room") and not game.get("vote_used") and uid != murderer_uid:
            row += 1
            vote_btn = discord.ui.Button(
                label="🔴 Spustit hlasování",
                style=discord.ButtonStyle.danger,
                custom_id=f"pa_vote_{uid}_{room_id}",
                row=row,
            )
            vote_btn.callback = self._vote_trigger_cb
            self.add_item(vote_btn)

        # Pastičkář — položit past (jen vrah-pastičkář)
        if uid == murderer_uid and pdata["role"] == "pastičkář" and not room.get("trap"):
            row += 1
            trap_btn = discord.ui.Button(
                label="🪤 Položit past",
                style=discord.ButtonStyle.danger,
                custom_id=f"pa_trap_{uid}_{room_id}",
                row=row,
            )
            trap_btn.callback = self._trap_place_cb
            self.add_item(trap_btn)

        # Osvobodit — někdo jiný v místnosti je v pasti
        trapped_others = [u for u in alive_here if game["players"][u].get("trapped") and u != uid]
        if trapped_others:
            row += 1
            free_btn = discord.ui.Button(
                label="🔓 Osvobodit",
                style=discord.ButtonStyle.success,
                custom_id=f"pa_free_{uid}_{room_id}",
                row=row,
            )
            free_btn.callback = self._free_cb
            self.add_item(free_btn)

        # Masová vražda — sériový vrah, ≥2 oběti, ještě nepoužito
        if uid == murderer_uid and pdata["role"] == "sériový vrah" and not pdata.get("mass_kill_used"):
            others_here = [u for u in alive_here if u != uid]
            if len(others_here) >= 2:
                row += 1
                mass_btn = discord.ui.Button(
                    label="💀 Masová vražda (1×)",
                    style=discord.ButtonStyle.danger,
                    custom_id=f"pa_mass_{uid}_{room_id}",
                    row=row,
                )
                mass_btn.callback = self._mass_murder_cb
                self.add_item(mass_btn)

        # Otevřít truhlu — v místnosti je zamčená truhla, hráč má klíč
        chest = room.get("chest")
        if chest and chest["locked"] and "klíč od truhly" in pdata["items"]:
            row += 1
            chest_btn = discord.ui.Button(
                label="🗝️ Otevřít truhlu",
                style=discord.ButtonStyle.success,
                custom_id=f"pa_chest_{uid}_{room_id}",
                row=row,
            )
            chest_btn.callback = self._chest_open_cb
            self.add_item(chest_btn)

        # Duch Arion — tmavá místnost s duchem, teleport (1× za hru)
        if room.get("ghost_arion") and not game.get("ghost_arion_used"):
            can_see = not room.get("dark") or room.get("candle_lit") or "baterka" in pdata["items"]
            if can_see:
                row += 1
                arion_btn = discord.ui.Button(
                    label="🐱 Teleportovat s Arion",
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"pa_arion_{uid}_{room_id}",
                    row=row,
                )
                arion_btn.callback = self._arion_teleport_cb
                self.add_item(arion_btn)

    # ── Prohledání ────────────────────────────────────────────────────────────

    async def _search_cb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = self.uid
        pdata = self.game["players"].get(uid)
        if pdata.get("searched_this_round"):
            await interaction.followup.send("Už jsi toto kolo prohledal/a.", ephemeral=True)
            return

        room = self.game["map"][self.room_id]

        if room.get("dark") and not room.get("candle_lit") and "baterka" not in pdata["items"]:
            await interaction.followup.send(
                "🌑 **Naprostá tma!** Potřebuješ 🔦 baterku nebo zapálenou 🕯️ svíčku.",
                ephemeral=True,
            )
            return

        pdata["searched_this_round"] = True
        results = []
        is_technik = pdata["role"] == "technik"
        base_chance = 0.60 if is_technik else 0.40

        if room["items"] and random.random() < base_chance:
            found_item = room["items"].pop(0)
            pdata["items"].append(found_item)
            results.append(f"Nalezl/a jsi: **{ITEM_EMOJI.get(found_item, '?')} {found_item}**!")

        # ── Klíč od truhly (pokud je v místnosti truhla a zamčená) ────────────
        chest = room.get("chest")
        if chest and chest["locked"] and "klíč od truhly" not in pdata["items"]:
            key_chance = 0.35 if is_technik else 0.15
            if random.random() < key_chance:
                pdata["items"].append("klíč od truhly")
                results.append("🗝️ *Za trhlinou ve zdi jsi našel/la* **klíč od truhly**!")

        code_found_now = False
        is_murderer = uid == self.game.get("murderer_uid")
        if room["code_number"] is not None and not room.get("code_found") and not is_murderer:
            num = room["code_number"]
            room["code_found"] = True
            self.game["found_codes"].append(num)
            pdata["code_numbers"].append(num)
            lore = random.choice(CODE_LORE)
            results.append(f"🔍 *{lore}*\n→ Číslo přidáno do kolektivního kódu.")
            code_found_now = True
        elif room["code_number"] is not None and not room.get("code_found") and is_murderer:
            # Vrah kód přeskočí — označit jako nalezený bez přidání do poolu
            results.append("🔍 *Nalezl/a jsi nápis, ale nedává ti smysl.*")

        if "baterka" in pdata["items"] and room["last_round_players"]:
            names = [self.game["players"][u]["name"]
                     for u in room["last_round_players"] if u in self.game["players"]]
            if names:
                results.append(f"🔦 *Baterka odhalí stopy:* V tomto kole tu bylo: **{', '.join(names)}**")

        if not results:
            results.append("*Prohledal/a jsi místnost. Nic zajímavého.*")

        items_str = _item_list_str(pdata["items"])
        found_codes = sorted(self.game.get("found_codes", []))
        total_codes = self.game.get("total_codes", 6)
        results.append(f"\n**🎒 Inventář:** {items_str}")
        results.append(f"🔢 Kolektivní kód: {', '.join(str(n) for n in found_codes) or '—'} ({len(found_codes)}/{total_codes})")
        await interaction.followup.send("\n".join(results), ephemeral=True)

        if code_found_now:
            thread_id = room["thread_id"]
            if thread_id:
                rt = interaction.client.get_channel(thread_id) or interaction.guild.get_channel_or_thread(thread_id)
                if rt:
                    nums_str = ", ".join(str(n) for n in found_codes)
                    try:
                        await rt.send(f"🔢 *Kód aktualizován:* **{nums_str}** *({len(found_codes)}/{total_codes})*")
                    except Exception:
                        pass

    # ── Útěk ─────────────────────────────────────────────────────────────────

    async def _escape_cb(self, interaction: discord.Interaction):
        uid = self.uid
        if not self.game.get("exit_opened"):
            if not self.game.get("generator_started"):
                fuel = self.game.get("generator_fuel", 0)
                await interaction.response.send_message(
                    f"❌ Generátor nebyl spuštěn. Vložte ⛽ **3 kanystry** ({fuel}/3 vloženo).",
                    ephemeral=True,
                )
                return
            found = self.game.get("found_codes", [])
            total_codes = self.game.get("total_codes", 6)
            if len(found) < total_codes:
                await interaction.response.send_message(
                    f"❌ Kód: **{len(found)}/{total_codes}**. Chybí ještě **{total_codes - len(found)}** čísel.",
                    ephemeral=True,
                )
                return
            # Generátor spuštěn + kód kompletní → Modal pro zadání kódu
            modal = ExitCodeModal(self.cog, self.game, self.channel_id, uid)
            await interaction.response.send_modal(modal)
            return
        # Exit je již otevřen — volný průchod
        await interaction.response.defer(ephemeral=True)
        channel = interaction.client.get_channel(self.channel_id)
        await self.cog._handle_escape(self.channel_id, uid, channel)

    # ── Oznámení EXITu ───────────────────────────────────────────────────────

    async def _announce_cb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = self.uid
        pdata = self.game["players"][uid]
        if self.game.get("exit_announced"):
            await interaction.followup.send("EXIT byl již oznámen.", ephemeral=True)
            return
        self.game["exit_announced"] = self.room_id
        channel = interaction.client.get_channel(self.channel_id)
        if channel:
            total_codes = self.game.get("total_codes", 6)
            await channel.send(
                f"📍 **{pdata['name']}** nalezl/a **EXIT**!\n"
                f"*Pro útěk: ⛽ 3 kanystry do generátoru + {total_codes} čísel kódu.*"
            )
        await interaction.followup.send("✅ EXIT oznámen.", ephemeral=True)

    # ── Vložení kanystru do generátoru ───────────────────────────────────────

    async def _deposit_fuel_cb(self, interaction: discord.Interaction):
        ch = interaction.client.get_channel(self.channel_id)
        ok, msg = await self.cog._handle_fuel_deposit(self.game, self.room_id, self.uid, ch)
        if ok:
            # Přebuduj panel — tlačítko zmizí (hráč nemá kanystr / generátor spuštěn)
            new_panel = PersonalActionView(self.cog, self.game, self.room_id, self.uid)
            try:
                await interaction.response.edit_message(content=f"⛽ {msg}", view=new_panel)
            except Exception:
                await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    # ── Střelba ──────────────────────────────────────────────────────────────

    async def _shoot_cb(self, interaction: discord.Interaction):
        uid = self.uid
        pdata = self.game["players"][uid]
        if pdata.get("shot_this_round"):
            await interaction.response.send_message("Už jsi v tomto kole vystřelil/a.", ephemeral=True)
            return
        room = self.game["map"][self.room_id]
        targets = [u for u in room["players"] if u != uid and self.game["players"].get(u, {}).get("alive")]
        if not targets:
            await interaction.response.send_message("V místnosti není nikdo jiný.", ephemeral=True)
            return
        options = [discord.SelectOption(label=self.game["players"][t]["name"], value=t, emoji="🎯") for t in targets]
        select = discord.ui.Select(placeholder="Vyber cíl…", options=options, custom_id=f"pa_shoot_sel_{uid}")

        async def sel_cb(sel_interaction: discord.Interaction):
            if str(sel_interaction.user.id) != uid:
                await sel_interaction.response.send_message("To není tvá pistole.", ephemeral=True)
                return
            await sel_interaction.response.defer(ephemeral=True)
            ch = sel_interaction.client.get_channel(self.channel_id)
            await self.cog._handle_shoot(self.channel_id, uid, sel_interaction.data["values"][0], ch)

        select.callback = sel_cb
        v = discord.ui.View(timeout=60)
        v.add_item(select)
        await interaction.response.send_message("🔫 Vyber cíl:", view=v, ephemeral=True)

    # ── Oživení ──────────────────────────────────────────────────────────────

    async def _revive_cb(self, interaction: discord.Interaction):
        uid = self.uid
        room = self.game["map"][self.room_id]
        options = [
            discord.SelectOption(label=f"{b['name']} (kolo {b['round']})", value=b["uid"], emoji="💀")
            for b in room["bodies"]
        ]
        select = discord.ui.Select(placeholder="Koho oživit?", options=options, custom_id=f"pa_rev_sel_{uid}")

        async def sel_cb(sel_interaction: discord.Interaction):
            if str(sel_interaction.user.id) != uid:
                await sel_interaction.response.send_message("To není tvoje lékárnička.", ephemeral=True)
                return
            await sel_interaction.response.defer(ephemeral=True)
            ch = sel_interaction.client.get_channel(self.channel_id)
            await self.cog._handle_revive(self.channel_id, uid, sel_interaction.data["values"][0], self.room_id, ch)

        select.callback = sel_cb
        v = discord.ui.View(timeout=60)
        v.add_item(select)
        await interaction.response.send_message("💊 Koho chceš oživit?", view=v, ephemeral=True)

    # ── Skenování ────────────────────────────────────────────────────────────

    async def _scan_cb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = self.uid
        pdata = self.game["players"][uid]
        if pdata.get("scanned_this_round"):
            await interaction.followup.send("Skener jsi už v tomto kole použil/a.", ephemeral=True)
            return
        pdata["scanned_this_round"] = True
        results = []
        if "amulet" not in pdata["items"] and random.random() < 0.10:
            pdata["items"].append("amulet")
            results.append("🔮 **Amulet Druhé Naděje** — vzácný nález!\n*Po tvé smrti budeš oživen/a jakmile vrah opustí místnost.*")
        else:
            drobnosti = [i for i in ALL_ITEMS if i not in pdata["items"]]
            if drobnosti and random.random() < 0.55:
                found = random.choice(drobnosti)
                pdata["items"].append(found)
                results.append(f"📡 Skener zachytil signál!\nNalezeno: **{ITEM_EMOJI.get(found, '?')} {found}**")
            else:
                results.append("📡 *Skener nezachytil nic zajímavého.*")
        results.append(f"\n**🎒 Inventář:** {_item_list_str(pdata['items'])}")
        await interaction.followup.send("\n".join(results), ephemeral=True)

    # ── Zapálit svíčku ────────────────────────────────────────────────────────

    async def _candle_cb(self, interaction: discord.Interaction):
        ch = interaction.client.get_channel(self.channel_id)
        ok, msg = await self.cog._light_candle_cb(self.game, self.room_id, self.uid, ch)
        await interaction.response.send_message(msg, ephemeral=True)

    # ── Hlasování ─────────────────────────────────────────────────────────────

    async def _vote_trigger_cb(self, interaction: discord.Interaction):
        ch = interaction.client.get_channel(self.channel_id)
        ok, msg = await self.cog._vote_trigger_cb(self.game, self.room_id, self.uid, ch)
        await interaction.response.send_message(msg, ephemeral=True)

    # ── Past ──────────────────────────────────────────────────────────────────

    async def _trap_place_cb(self, interaction: discord.Interaction):
        ch = interaction.client.get_channel(self.channel_id)
        ok, msg = await self.cog._trap_place_cb(self.game, self.room_id, self.uid, ch)
        await interaction.response.send_message(msg, ephemeral=True)

    # ── Osvobodit ─────────────────────────────────────────────────────────────

    async def _free_cb(self, interaction: discord.Interaction):
        uid = self.uid
        room = self.game["map"][self.room_id]
        trapped_others = [u for u in room["players"] if self.game["players"][u].get("trapped") and u != uid]
        if not trapped_others:
            await interaction.response.send_message("Nikdo tu není v pasti.", ephemeral=True)
            return
        ch = interaction.client.get_channel(self.channel_id)
        ok, msg = await self.cog._free_cb(self.game, self.room_id, uid, trapped_others[0], ch)
        await interaction.response.send_message(msg, ephemeral=True)

    # ── Masová vražda ─────────────────────────────────────────────────────────

    async def _mass_murder_cb(self, interaction: discord.Interaction):
        uid = self.uid
        room = self.game["map"][self.room_id]
        others = [u for u in room["players"] if self.game["players"][u]["alive"] and u != uid]
        if len(others) < 2:
            await interaction.response.send_message("Potřebuješ alespoň 2 oběti.", ephemeral=True)
            return

        options = [
            discord.SelectOption(label=self.game["players"][u]["name"], value=u, emoji="💀")
            for u in others
        ]
        select = discord.ui.Select(
            placeholder="Vyber přesně 2 oběti…",
            options=options[:25],
            min_values=2,
            max_values=min(2, len(others)),
            custom_id=f"pa_mass_sel_{uid}",
        )

        async def sel_cb(sel_interaction: discord.Interaction):
            if str(sel_interaction.user.id) != uid:
                await sel_interaction.response.send_message("To není tvůj výběr.", ephemeral=True)
                return
            await sel_interaction.response.defer(ephemeral=True)
            chosen = sel_interaction.data["values"]
            ch = sel_interaction.client.get_channel(self.channel_id)
            await self.cog._handle_mass_murder(self.channel_id, uid, chosen, ch)
            await sel_interaction.followup.send("💀 Masová vražda provedena.", ephemeral=True)

        select.callback = sel_cb
        v = discord.ui.View(timeout=60)
        v.add_item(select)
        await interaction.response.send_message(
            "💀 **Masová vražda** — vyber přesně 2 oběti:", view=v, ephemeral=True
        )

    # ── Prohledat těla ────────────────────────────────────────────────────────

    async def _loot_bodies_cb(self, interaction: discord.Interaction):
        room = self.game["map"][self.room_id]
        pdata = self.game["players"][self.uid]
        all_body_items: list[tuple[str, int]] = []  # (item, body_index)
        for bi, body in enumerate(room["bodies"]):
            for item in body.get("items", []):
                all_body_items.append((item, bi))
        if not all_body_items:
            await interaction.response.send_message("Na tělech nic není.", ephemeral=True)
            return
        options = [
            discord.SelectOption(
                label=f"{ITEM_EMOJI.get(item, '?')} {item}",
                value=f"{bi}:{item}",
                description=f"U těla: {room['bodies'][bi]['name']}",
            )
            for item, bi in all_body_items[:25]
        ]
        select = discord.ui.Select(
            placeholder="Vyber předmět k sebrání…",
            options=options,
            custom_id=f"pa_loot_sel_{self.uid}",
        )

        async def sel_cb(sel_interaction: discord.Interaction):
            if str(sel_interaction.user.id) != self.uid:
                await sel_interaction.response.send_message("To není tvůj výběr.", ephemeral=True)
                return
            val = sel_interaction.data["values"][0]
            bi_str, item_name = val.split(":", 1)
            bi = int(bi_str)
            body = room["bodies"][bi]
            if item_name not in body.get("items", []):
                await sel_interaction.response.send_message("Předmět již není u těla.", ephemeral=True)
                return
            body["items"].remove(item_name)
            pdata["items"].append(item_name)
            await sel_interaction.response.send_message(
                f"⚰️ Sebral/a jsi **{ITEM_EMOJI.get(item_name, '?')} {item_name}** z těla **{body['name']}**.",
                ephemeral=True,
            )

        select.callback = sel_cb
        v = discord.ui.View(timeout=60)
        v.add_item(select)
        await interaction.response.send_message("⚰️ **Prohledávání těl** — co chceš sebrat?", view=v, ephemeral=True)

    # ── Nechat věc u těla ─────────────────────────────────────────────────────

    async def _drop_item_cb(self, interaction: discord.Interaction):
        pdata = self.game["players"][self.uid]
        room = self.game["map"][self.room_id]
        if not pdata["items"]:
            await interaction.response.send_message("Nemáš žádné předměty.", ephemeral=True)
            return
        options = [
            discord.SelectOption(label=f"{ITEM_EMOJI.get(i, '?')} {i}", value=i)
            for i in pdata["items"]
        ]
        select = discord.ui.Select(
            placeholder="Vyber předmět k ponechání…",
            options=options[:25],
            custom_id=f"pa_drop_sel_{self.uid}",
        )

        async def sel_cb(sel_interaction: discord.Interaction):
            if str(sel_interaction.user.id) != self.uid:
                await sel_interaction.response.send_message("To není tvůj výběr.", ephemeral=True)
                return
            item_name = sel_interaction.data["values"][0]
            if item_name not in pdata["items"]:
                await sel_interaction.response.send_message("Předmět už nemáš.", ephemeral=True)
                return
            pdata["items"].remove(item_name)
            # Nechat na nejbližším těle nebo na podlaze místnosti
            if room["bodies"]:
                room["bodies"][0].setdefault("items", []).append(item_name)
                dest = f"u těla **{room['bodies'][0]['name']}**"
            else:
                room["items"].append(item_name)
                dest = "na podlaze místnosti"
            await sel_interaction.response.send_message(
                f"📤 Nechal/a jsi **{ITEM_EMOJI.get(item_name, '?')} {item_name}** {dest}.",
                ephemeral=True,
            )

        select.callback = sel_cb
        v = discord.ui.View(timeout=60)
        v.add_item(select)
        await interaction.response.send_message("📤 **Nechat věc** — co chceš odložit?", view=v, ephemeral=True)

    # ── Otevřít truhlu ────────────────────────────────────────────────────────

    async def _chest_open_cb(self, interaction: discord.Interaction):
        room = self.game["map"][self.room_id]
        chest = room.get("chest")
        if not chest or not chest["locked"]:
            await interaction.response.send_message("Truhla je již otevřena.", ephemeral=True)
            return
        pdata = self.game["players"][self.uid]
        if "klíč od truhly" not in pdata["items"]:
            await interaction.response.send_message("Nemáš klíč od truhly.", ephemeral=True)
            return
        pdata["items"].remove("klíč od truhly")
        chest["locked"] = False
        contents = chest.get("contents", [])
        room["items"].extend(contents)
        contents_str = ", ".join(f"{ITEM_EMOJI.get(i, '?')} {i}" for i in contents)
        await interaction.response.send_message(
            f"🗝️ **Truhla otevřena!** Uvnitř: **{contents_str}** — přidáno do místnosti.",
            ephemeral=True,
        )
        thread_id = room.get("thread_id")
        if thread_id:
            rt = interaction.client.get_channel(thread_id) or interaction.guild.get_channel_or_thread(thread_id)
            if rt:
                try:
                    await rt.send(f"📦 **{pdata['name']}** otevřel/a truhlu! Obsah: **{contents_str}** — leží v místnosti.")
                except Exception:
                    pass

    # ── Teleport s Duchem Arion ───────────────────────────────────────────────

    async def _arion_teleport_cb(self, interaction: discord.Interaction):
        if self.game.get("ghost_arion_used"):
            await interaction.response.send_message("Arion již zmizela.", ephemeral=True)
            return
        room_ids = [rid for rid in self.game["map"] if rid != self.room_id]
        options = [discord.SelectOption(label=f"Místnost {rid}", value=rid) for rid in sorted(room_ids)]
        select = discord.ui.Select(
            placeholder="Vyber místnost…",
            options=options[:25],
            custom_id=f"pa_arion_sel_{self.uid}",
        )

        async def sel_cb(sel_interaction: discord.Interaction):
            if str(sel_interaction.user.id) != self.uid:
                await sel_interaction.response.send_message("To není tvůj výběr.", ephemeral=True)
                return
            if self.game.get("ghost_arion_used"):
                await sel_interaction.response.send_message("Arion již zmizela.", ephemeral=True)
                return
            dest = sel_interaction.data["values"][0]
            self.game["ghost_arion_used"] = True
            self.game["map"][self.room_id]["ghost_arion"] = False
            pdata = self.game["players"][self.uid]
            old_room = pdata["room"]
            if self.uid in self.game["map"][old_room]["players"]:
                self.game["map"][old_room]["players"].remove(self.uid)
            pdata["room"] = dest
            self.game["map"][dest]["players"].append(self.uid)
            ch = sel_interaction.client.get_channel(self.channel_id)
            if ch:
                dest_thread_id = self.game["map"][dest].get("thread_id")
                if dest_thread_id:
                    dest_thread = ch.guild.get_channel_or_thread(dest_thread_id)
                    if dest_thread:
                        try:
                            await dest_thread.add_user(sel_interaction.user)
                        except Exception:
                            pass
            await sel_interaction.response.send_message(
                f"🐱 **Arion tě teleportovala do místnosti {dest}!** Přesunul/a ses okamžitě.",
                ephemeral=True,
            )

        select.callback = sel_cb
        v = discord.ui.View(timeout=60)
        v.add_item(select)
        await interaction.response.send_message(
            "🐱 **Arion nabízí teleport.** Zvol místnost:", view=v, ephemeral=True
        )


# ══════════════════════════════════════════════════════════════════════════════
# VIEW – VRAH: TLAČÍTKO ZABÍT
# ══════════════════════════════════════════════════════════════════════════════

class MurderView(discord.ui.View):
    def __init__(self, cog: "LabyrinthCog", game: dict, murderer_uid: str, victim_uid: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.game = game
        self.murderer_uid = murderer_uid
        self.victim_uid = victim_uid
        self.channel_id: int = game["channel_id"]
        self.used = False

    @discord.ui.button(label="🔪 Zabít", style=discord.ButtonStyle.danger,
                       custom_id="lab_murder")
    async def murder_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.murderer_uid:
            await interaction.response.send_message("Toto tlačítko není pro tebe.", ephemeral=True)
            return
        if self.used:
            await interaction.response.send_message("Akce již proběhla.", ephemeral=True)
            return
        self.used = True
        self.stop()
        await interaction.response.defer(ephemeral=True)
        ch = interaction.client.get_channel(self.channel_id)
        await self.cog._handle_murder(self.channel_id, self.murderer_uid, self.victim_uid, ch)
        await interaction.followup.send("Hotovo.", ephemeral=True)

    async def on_timeout(self):
        self.used = True


# ══════════════════════════════════════════════════════════════════════════════
# HLAVNÍ COG
# ══════════════════════════════════════════════════════════════════════════════

class LabyrinthCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # channel_id → game dict
        self.active_games: dict[int, dict] = {}
        # channel_id → {room_id: DoorChoiceView}
        self._door_views: dict[int, dict[str, DoorChoiceView]] = {}

    # ── Inicializace hry ─────────────────────────────────────────────────────

    async def _init_game(self, channel: discord.TextChannel,
                         players: list[discord.Member],
                         map_size: tuple[int, int]):
        rows, cols = map_size
        random.shuffle(players)

        # Přiřadit role
        murderer = players[0]
        innocents = players[1:]

        murderer_role = random.choice(MURDERER_ROLES)

        roles_pool = INNOCENT_ROLES[:]
        random.shuffle(roles_pool)

        player_data: dict[str, dict] = {}
        for i, m in enumerate(players):
            uid = str(m.id)
            if m.id == murderer.id:
                role = murderer_role
            else:
                role = roles_pool[(i - 1) % len(roles_pool)]
            player_data[uid] = {
                "name": m.display_name,
                "role": role,
                "room": "",
                "alive": True,
                "escaped": False,
                "items": [],
                "code_numbers": [],
                "has_key": False,
                "searched_this_round": False,
                "scanned_this_round": False,
                "shot_this_round": False,
                "shoot_target": None,
                "door_assignment": None,
                "trapped": False,
                "mass_kill_used": False,
                "pistol_cooldown": 0,
                "revived_this_game": False,
                "fake_role": None,   # Pro blázen: role, za kterou se vydává
            }

        # Startovní předměty podle role
        murderer_uid_str = str(murderer.id)
        for uid, pdata in player_data.items():
            if uid == murderer_uid_str:
                pdata["items"].append("mačeta")
            elif pdata["role"] == "detektiv":
                pdata["items"].append("pistole")
                pdata["pistol_cooldown"] = 2  # Nemůže střílet první kolo (init=2, klesne na 1 po kole 1, na 0 po kole 2)
            elif pdata["role"] == "technik":
                pdata["items"].append("skener")
            elif pdata["role"] == "doktor":
                pdata["items"].append("lékárnička")

        game_map = _build_map(rows, cols)
        room_ids = list(game_map.keys())

        game: dict = {
            "phase": "running",
            "round": 0,
            "guild_id": channel.guild.id,
            "channel_id": channel.id,
            "rows": rows,
            "cols": cols,
            "spectator_thread_id": None,
            "map": game_map,
            "players": player_data,
            "murderer_uid": str(murderer.id),
            "exit_room": "",
            "exit_code": [],
            "total_codes": 6,
            "pending_choices": 0,
            "movement_triggered": False,
            "pending_revivals": [],
            "found_codes": [],
            "vote_used": False,
            "vote_room_id": None,
            "vote_data": None,
            "traps": {},
            "generator_fuel": 0,
            "generator_started": False,
        }

        _scatter_items_and_codes(game)

        # Všichni hráči začínají ve stejné místnosti (první = A1)
        start_room = room_ids[0]
        for uid in player_data:
            player_data[uid]["room"] = start_room
            game_map[start_room]["players"].append(uid)

        self.active_games[channel.id] = game

        # Vytvořit spectator vlákno
        try:
            spec_thread = await channel.create_thread(
                name="👁️ Divácká tribuna",
                type=discord.ChannelType.private_thread,
                invitable=False,
            )
            game["spectator_thread_id"] = spec_thread.id
            await spec_thread.send(
                "Toto vlákno je pro vyřazené hráče. Mohou sledovat, ale ne hrát."
            )
        except Exception as e:
            print(f"[Labyrinth] Chyba při vytváření spectator vlákna: {e}")

        # Vytvořit vlákna pro místnosti
        occupied = set(p["room"] for p in player_data.values())
        n_codes = game.get("total_codes", 6)
        tutorial_embed = discord.Embed(
            title="🚪 Door Labyrinth — Jak se hraje",
            description=(
                "Nacházíte se v záhadném labyrintu. **Jeden z vás je Vrah.**\n\n"
                f"**Cíl nevinných:** Spusťte generátor (⛽ 3 kanystry) + najděte {n_codes} čísel kódu, zadejte kód a unikněte přes EXIT — "
                "nebo odhalte vraha (pistolí nebo hlasováním).\n"
                "**Cíl vraha:** Eliminuj všechny nevinné.\n\n"
                "**Pohyb (každé kolo):**\n"
                "Každé dveře mají kapacitu — číslo určuje, kolik hráčů jimi může projít. "
                "Klikni na barevné tlačítko dveří nebo zůstaň.\n\n"
                "**Prohledání místnosti:**\n"
                "Odkryje předměty, čísla kódu (skrytá ve stopách, grafiti, nápisech) "
                "a atmosferické záchytné body. ⚠️ Tmavé místnosti vyžadují 🔦 baterku nebo 🕯️ svíčku.\n\n"
                "**Zabíjení:**\n"
                "Vrah může zaútočit, pokud je sám s obětí (nebo Pastičkář s chycenou obětí). "
                "Pistole zabije ihned. Zbraně (nůž, baseballka, sekáček, vrtačka) dávají **50% šanci zabít vraha**. "
                "⚠️ Vrahova **Mačeta** přebíjí všechny zbraně.\n\n"
                "**Generátor:** EXIT je uzamčen. Tři ⛽ kanystry musí být vloženy do generátoru v exit místnosti — "
                "pak lze zadat kód a uprchnout.\n\n"
                "**Hlasování:** Speciální místnost má 🔴 červené tlačítko — aktivuje globální hlasování o vrahovi.\n\n"
                "**Třídy nevinných:** Detektiv 🕵️ (pistole) · Doktor 💊 (lékárnička) · "
                "Skaut 👁️ (info zpravodaj) · Technik 📡 (skener + vzácné předměty)\n"
                "**Třídy vraha:** Manipulátor 🎭 · Pastičkář 🪤 · Sériový vrah 🔪\n\n"
                f"*Mapa: {rows}×{cols} místností. Všichni začínáte společně — pak se cesty rozejdou.*"
            ),
            color=0x8B0000,
        )
        ready_view = TutorialReadyView(players, self, channel.id)
        await channel.send(
            embed=tutorial_embed,
            view=ready_view,
            content=f"📖 Přečtěte si pravidla a klikněte **✅ Připraven/a**. Hra začne, jakmile jsou všichni připraveni (nebo za 90 s automaticky).",
        )
        await channel.send(
            f"🚪 **Door Labyrinth** — Vytvářejí se místnosti ({rows}×{cols})…"
        )
        for room_id in room_ids:
            if room_id not in occupied:
                continue  # vytváří se jen obsazené místnosti (ostatní vzniknou při příchodu)
            await self._ensure_room_thread(channel, game, room_id)
            await asyncio.sleep(0.5)  # rate limit prevence

        # Najít Skauta pro Manipulátora
        skaut_uid = next(
            (uid for uid, p in player_data.items() if p["role"] == "skaut"),
            None
        )

        # DM hráčům jejich role
        for m in players:
            uid = str(m.id)
            pdata = player_data[uid]
            role = pdata["role"]
            murderer_role_texts = {
                "manipulátor": (
                    "🎭 **JSI VRAH — MANIPULÁTOR!**\n"
                    "Eliminuj všechny nevinné.\n"
                    "**Speciální schopnost:** Vždy víš, kdo je Skaut. "
                    "Když jste ve stejné místnosti, Skaut dostane příští kolo falešné informace místo pravých."
                ),
                "pastičkář": (
                    "🪤 **JSI VRAH — PASTIČKÁŘ!**\n"
                    "Eliminuj všechny nevinné.\n"
                    "**Speciální schopnost:** Můžeš pokládat pasti v místnostech. "
                    "Hráč, který vstoupí do místnosti s pastí, nemůže příští kolo volit dveře. "
                    "Ostatní ho mohou osvobodit. Ty dostaneš příležitost k vraždě chyceného hráče."
                ),
                "sériový vrah": (
                    "🔪 **JSI VRAH — SÉRIOVÝ VRAH!**\n"
                    "Eliminuj všechny nevinné.\n"
                    "**Speciální schopnost:** 1× za hru můžeš zabít 2 hráče najednou, "
                    "i když nejsi úplně sám. Začínáš s Mačetou."
                ),
            }
            innocent_role_texts = {
                "detektiv": (
                    "🕵️ **Detektiv** — začínáš s pistolí. Zastřel vraha a nevinní vyhrají.\n"
                    "⚠️ **Kola 1 a 2 nemůžeš střílet** — pistole se nabíjí. "
                    "Od kola 3 máš jeden výstřel. Po použití se pistole zničí."
                ),
                "doktor":   "💊 **Doktor** — začínáš s lékárničkou. Můžeš oživit jednoho mrtvého hráče (1× za hru).",
                "skaut":    (
                    "👁️ **Skaut** — po každém pohybu dostaneš v DM rozšířené informace:\n"
                    "• Kdo byl v tvé místnosti minulé kolo\n"
                    "• Hint na směr nejbližšího kódu\n"
                    "• Směr k hlasovací místnosti 🔴, truhle 📦 a Duchu Arion 🐱"
                ),
                "technik":  "📡 **Technik** — máš skener. Použij ho v akční fázi pro hledání skrytých předmětů (včetně vzácného Amuletu Druhé Naděje).",
            }
            if uid == str(murderer.id):
                role_text = murderer_role_texts.get(role, "💀 **JSI VRAH!**")
            elif role == "blázen":
                # Blázen dostane popis náhodné jiné nevinné role (klam)
                fake = random.choice([r for r in innocent_role_texts])
                player_data[uid]["fake_role"] = fake
                role_text = innocent_role_texts[fake]
            else:
                role_text = innocent_role_texts.get(role, "Nevinný")

            dm_embed = discord.Embed(
                title="🚪 Door Labyrinth — Tvoje role",
                description=f"{role_text}\n\nHra začala v {channel.mention}!",
                color=0x8B0000 if uid == str(murderer.id) else 0x1E90FF,
            )
            dm_embed.add_field(
                name="Tvoje předměty",
                value=_item_list_str(pdata["items"]) or "žádné",
                inline=False,
            )
            dm_embed.set_footer(text="Tuto zprávu vidíš jen ty.")

            # Manipulátor dostane jméno Skauta
            if uid == str(murderer.id) and role == "manipulátor" and skaut_uid:
                skaut_name = player_data[skaut_uid]["name"]
                dm_embed.add_field(
                    name="🎯 Skaut je:",
                    value=f"**{skaut_name}**",
                    inline=False,
                )

            try:
                await m.send(embed=dm_embed)
            except discord.Forbidden:
                pass

        # Přidat hráče do jejich startovních vláken
        for m in players:
            uid = str(m.id)
            pdata = player_data[uid]
            room_id = pdata["room"]
            thread_id = game["map"][room_id]["thread_id"]
            if thread_id:
                thread = channel.guild.get_channel_or_thread(thread_id)
                if thread:
                    try:
                        await thread.add_user(m)
                    except Exception:
                        pass

        # Čekat na ready potvrzení všech hráčů (nebo timeout 90s)
        await ready_view.wait_ready()
        await channel.send("⚔️ **Všichni jsou připraveni — hra začíná!**")

        # Zahájit kolo 1
        await self._start_round(channel.id)

    # ── Vlákno místnosti ─────────────────────────────────────────────────────

    async def _ensure_room_thread(self, channel: discord.TextChannel,
                                   game: dict, room_id: str) -> discord.Thread | None:
        """Zajistí existenci Discord vlákna pro místnost. Vytvoří ho pokud chybí."""
        room = game["map"][room_id]
        if room["thread_id"]:
            existing = channel.guild.get_channel_or_thread(room["thread_id"])
            if existing:
                return existing

        room_label = f"🚪 Místnost {room_id}"
        try:
            thread = await channel.create_thread(
                name=room_label,
                type=discord.ChannelType.private_thread,
                invitable=False,
            )
            room["thread_id"] = thread.id
            return thread
        except Exception as e:
            print(f"[Labyrinth] Chyba při vytváření vlákna {room_id}: {e}")
            return None

    # ── Kolo ─────────────────────────────────────────────────────────────────

    async def _start_round(self, channel_id: int):
        game = self.active_games.get(channel_id)
        if not game:
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            return

        game["round"] += 1
        current_round = game["round"]

        # ── Auto-odhalení exitu (pokud ho nikdo nenalezl po N kolech) ───────────
        n_rooms_total = len(game["map"])
        auto_reveal_at = max(3, n_rooms_total // 3)
        if current_round == auto_reveal_at and not game.get("exit_announced"):
            exit_room_id = game["exit_room"]
            game["exit_announced"] = exit_room_id
            murderer_uid_auto = game.get("murderer_uid", "")
            for uid, pdata_auto in game["players"].items():
                if not pdata_auto["alive"] or uid == murderer_uid_auto:
                    continue
                tid = game["map"][pdata_auto["room"]].get("thread_id")
                if tid:
                    rt = channel.guild.get_channel_or_thread(tid)
                    if rt:
                        try:
                            await rt.send(
                                f"🧭 **Záhadná síla vede vaše kroky…** EXIT se nachází v místnosti **{exit_room_id}**."
                            )
                        except Exception:
                            pass

        # Reset per-round flagů
        for pdata in game["players"].values():
            pdata["searched_this_round"] = False
            pdata["scanned_this_round"] = False
            pdata["shot_this_round"] = False
            pdata["shoot_target"] = None
            pdata["door_assignment"] = None
            if pdata.get("pistol_cooldown", 0) > 0:
                pdata["pistol_cooldown"] -= 1

        # ── Amulet Druhé Naděje: oživení čekajících hráčů ──────────────────
        murderer_pdata = game["players"].get(game["murderer_uid"], {})
        murderer_room = murderer_pdata.get("room") if murderer_pdata.get("alive") else None
        still_pending = []
        for revival in game.get("pending_revivals", []):
            r_uid = revival["uid"]
            r_room_id = revival["room_id"]
            revival_round = revival.get("round", 0)
            force_revive = (current_round - revival_round) >= 3
            if murderer_room != r_room_id or force_revive:
                # Vrah odešel — oživit
                r_pdata = game["players"][r_uid]
                r_pdata["alive"] = True
                r_pdata["room"] = r_room_id
                game["map"][r_room_id]["players"].append(r_uid)
                game["map"][r_room_id]["bodies"] = [
                    b for b in game["map"][r_room_id]["bodies"] if b["uid"] != r_uid
                ]
                r_member = channel.guild.get_member(int(r_uid))
                if r_member:
                    r_tid = game["map"][r_room_id]["thread_id"]
                    if r_tid:
                        r_thread = channel.guild.get_channel_or_thread(r_tid)
                        if r_thread:
                            try:
                                await r_thread.add_user(r_member)
                                await r_thread.send(
                                    f"🔮 **{r_pdata['name']}** byl/a oživena Amuletem Druhé Naděje!"
                                )
                            except Exception:
                                pass
                    try:
                        await r_member.send(
                            f"🔮 Amulet tě oživil! Vrah opustil místnost **{r_room_id}**. Jsi zpět ve hře!"
                        )
                    except discord.Forbidden:
                        pass
            else:
                still_pending.append(revival)
        game["pending_revivals"] = still_pending

        # Spočítat počet živých hráčů, kteří budou vybírat
        alive = _alive_players(game)
        game["pending_choices"] = len(alive)
        game["movement_triggered"] = False

        # Chycení hráči automaticky zůstanou — nepočítají se jako čekající na výběr dveří
        for uid in alive:
            pdata = game["players"][uid]
            if pdata.get("trapped"):
                pdata["door_assignment"] = pdata["room"]
                game["pending_choices"] = max(0, game["pending_choices"] - 1)

        # DM pro vraha — počet zbývajících nevinných (bez stavu kódu)
        m_uid = game["murderer_uid"]
        # Vrahův stav se zobrazuje v jeho osobním panelu (žádný DM)

        # Pro každou obsazenou místnost – zahodit dveřní view a vytvořit nový
        self._door_views[channel_id] = {}
        occupied_rooms = set(game["players"][uid]["room"] for uid in alive)

        for room_id in occupied_rooms:
            room = game["map"][room_id]
            thread_id = room["thread_id"]
            if not thread_id:
                thread = await self._ensure_room_thread(channel, game, room_id)
                if not thread:
                    continue
            else:
                thread = channel.guild.get_channel_or_thread(thread_id)
                if not thread:
                    continue

            # Sestavit popis stavu místnosti
            players_here = [
                game["players"][u]["name"]
                for u in room["players"]
                if game["players"][u]["alive"]
            ]
            bodies_here = []
            for b in room["bodies"]:
                body_loot = _item_list_str(b.get("items", []))
                loot_str = f" — u těla: {body_loot}" if body_loot else ""
                bodies_here.append(
                    f"💀 Tělo hráče **{b['name']}** (leží tu {current_round - b['round']} kol){loot_str}"
                )

            room_desc = room["description"]
            items_desc = _item_list_str(room["items"])

            embed = discord.Embed(
                title=f"Kolo {current_round} — Místnost {room_id}",
                description=room_desc,
                color=0x4B0082,
            )
            embed.add_field(name="Hráči v místnosti",
                            value=", ".join(players_here) or "nikdo", inline=False)
            if bodies_here:
                embed.add_field(name="Těla", value="\n".join(bodies_here), inline=False)
            connections = room["connections"]
            n_doors = len(connections)
            dice_flavor = (
                f"Před vámi stojí {n_doors} {'dveře' if n_doors == 2 else 'dveří' if n_doors >= 5 else 'dveře'}. "
                "Arion hodí kostkami — číslo na každé kostce udává kapacitu průchodu."
            )
            exit_notice = ""
            if game.get("exit_opened"):
                exit_notice = "\n🚪 **EXIT JE OTEVŘEN! Vstup volný pro všechny!**"
            elif game.get("exit_announced"):
                exit_notice = "\n📍 **EXIT byl nalezen** — zkontroluj svůj panel akcí."
            embed.add_field(name="🎲 Pohyb", value=dice_flavor + exit_notice, inline=False)
            if room.get("chest"):
                chest = room["chest"]
                chest_status = "🔒 **Zamčená truhla** — prohledej místnost, možná najdeš klíč." if chest["locked"] else "📦 **Truhla je otevřena.**"
                embed.add_field(name="📦 Truhla", value=chest_status, inline=False)
            if room.get("ghost_arion") and not game.get("ghost_arion_used"):
                embed.add_field(name="🐱 Duch Temné Arion", value="*Přízračná kočka zahalená temnou aurou se na tebe dívá. Něco nabízí…*", inline=False)
            if room["is_exit"] and game.get("exit_announced"):
                gen_fuel = game.get("generator_fuel", 0)
                if game.get("generator_started"):
                    gen_field = "✅ **Generátor běží!** Zadej kód a unikni."
                else:
                    missing = 3 - gen_fuel
                    gen_field = f"⛽ **Generátor: {gen_fuel}/3** — chybí {missing} {'kanystr' if missing == 1 else 'kanystry' if missing <= 4 else 'kanystru'}"
                embed.add_field(name="🔌 Generátor", value=gen_field, inline=False)
            embed.add_field(name="🗺️ Mapa", value=_render_map(game, room_id, hide_exit=True), inline=False)
            trapped_here = [game["players"][u]["name"] for u in room["players"]
                            if game["players"][u]["alive"] and game["players"][u].get("trapped")]
            footer_text = "Zvol dveře | 🎒 Inventář → tlačítko níže"
            if trapped_here:
                embed.add_field(
                    name="🪤 Hráči v pasti",
                    value=f"{', '.join(trapped_here)} — nemohou odejít",
                    inline=False,
                )
            embed.set_footer(text=footer_text)

            view = DoorChoiceView(self, game, room_id)
            self._door_views[channel_id][room_id] = view
            await thread.send(embed=embed, view=view)

            # Skaut: rozšířené informace (nebo falešné, pokud Manipulátor ve stejné místnosti)
            murderer_role_here = game["players"][game["murderer_uid"]]["role"]
            manipulator_in_room = (
                murderer_role_here == "manipulátor"
                and game["players"][game["murderer_uid"]].get("alive")
                and game["players"][game["murderer_uid"]]["room"] == room_id
            )
            scouts_here = [
                u for u in room["players"]
                if game["players"][u]["alive"] and game["players"][u]["role"] == "skaut"
            ]
            for scout_uid in scouts_here:
                scout_member = channel.guild.get_member(int(scout_uid))
                if not scout_member:
                    continue
                if manipulator_in_room:
                    # Manipulátor zkorumpuje informace Skauta — falešná jména jen z živých
                    alive_uids = _alive_players(game)
                    fake_names = [game["players"][u]["name"]
                                  for u in random.sample(alive_uids, min(2, len(alive_uids)))]
                    scout_name = game["players"][scout_uid]["name"]
                    try:
                        await scout_member.send(
                            f"👁️ **Skaut — Místnost {room_id}:**\n"
                            f"Minulé kolo tu bylo: **{', '.join(fake_names)}**"
                        )
                    except discord.Forbidden:
                        pass
                    # Potvrdit Manipulátorovi, že korupce proběhla
                    m_uid = game["murderer_uid"]
                    m_member = channel.guild.get_member(int(m_uid))
                    if m_member:
                        try:
                            await m_member.send(
                                f"🎭 **Korupce úspěšná!** Skaut **{scout_name}** v místnosti {room_id} "
                                f"dostal falešné informace místo pravých."
                            )
                        except discord.Forbidden:
                            pass
                else:
                    # Hint na směr k nejbližším nenalezeným kódům
                    code_hints = []
                    for r_id, r_data in game["map"].items():
                        if r_data.get("code_number") is not None and not r_data.get("code_found"):
                            code_hints.append(_room_direction(room_id, r_id))
                    hint_str = (
                        f"\n🔍 Hint: nenalezené kódy jsou směrem {', '.join(sorted(set(code_hints))[:2])}"
                        if code_hints else ""
                    )
                    # Hint na hlasovací místnost
                    vote_room_id = game.get("vote_room_id")
                    if vote_room_id and not game.get("vote_used") and vote_room_id != room_id:
                        hint_str += f"\n🔴 Hlasovací místnost je směrem **{_room_direction(room_id, vote_room_id)}**"
                    # Hint na truhlu
                    chest_room_id = game.get("chest_room")
                    if chest_room_id and game["map"][chest_room_id].get("chest", {}).get("locked") and chest_room_id != room_id:
                        hint_str += f"\n📦 Truhla je směrem **{_room_direction(room_id, chest_room_id)}**"
                    # Hint na Ducha Arion
                    if not game.get("ghost_arion_used"):
                        ghost_room = next(
                            (r for r, d in game["map"].items() if d.get("ghost_arion")), None
                        )
                        if ghost_room and ghost_room != room_id:
                            hint_str += f"\n🐱 Duch Arion je někde směrem **{_room_direction(room_id, ghost_room)}**"
                    if current_round == 1:
                        # Kolo 1 — žádné pohyby minulé kolo, dáme startovní intel
                        dark_count = sum(1 for r in game["map"].values() if r.get("dark"))
                        total_codes = game.get("total_codes", 6)
                        try:
                            await scout_member.send(
                                f"👁️ **Skaut — Kolo 1, Startovní intel:**\n"
                                f"Mapa má **{dark_count}** tmavých místností (nelze prohledat bez 🔦 baterky nebo 🕯️ svíčky).\n"
                                f"Celkem čísel kódu k nalezení: **{total_codes}**{hint_str}"
                            )
                        except discord.Forbidden:
                            pass
                    else:
                        prev_names = [game["players"][u]["name"]
                                      for u in room["last_round_players"]
                                      if u in game["players"]]
                        try:
                            await scout_member.send(
                                f"👁️ **Skaut — Místnost {room_id}:**\n"
                                f"Minulé kolo tu bylo: **{', '.join(prev_names) or 'nikdo'}**{hint_str}"
                            )
                        except discord.Forbidden:
                            pass

        # ── Souhrn kola v hlavním kanálu ──────────────────────────────────
        found_codes = game.get("found_codes", [])
        total_codes = game.get("total_codes", 6)
        round_embed = discord.Embed(
            title=f"🚪 Kolo {current_round} — přehled",
            color=0x4B0082,
        )
        round_embed.add_field(
            name="🟢 Živí hráči",
            value=str(len(alive)),
            inline=True,
        )
        round_embed.add_field(
            name="🔢 Kód",
            value=f"{len(found_codes)}/{total_codes}",
            inline=True,
        )
        gen_fuel = game.get("generator_fuel", 0)
        gen_status = (
            "✅ Běží" if game.get("generator_started")
            else f"⛽ {gen_fuel}/3"
        )
        round_embed.add_field(name="🔌 Generátor", value=gen_status, inline=True)
        await channel.send(embed=round_embed)

        # ── Spectator stats ────────────────────────────────────────────────
        spec_id = game.get("spectator_thread_id")
        if spec_id:
            spec_thread = channel.guild.get_channel_or_thread(spec_id)
            if spec_thread:
                alive_names  = [game["players"][u]["name"] for u in alive]
                dead_names   = [p["name"] for p in game["players"].values()
                                if not p["alive"] and not p.get("escaped")]
                escaped_names = [p["name"] for p in game["players"].values()
                                 if p.get("escaped")]
                spec_embed = discord.Embed(
                    title=f"📊 Kolo {current_round} — Přehled hry",
                    color=0x555555,
                )
                spec_embed.add_field(
                    name=f"🟢 Živí ({len(alive_names)})",
                    value=", ".join(alive_names) or "—",
                    inline=False,
                )
                if escaped_names:
                    spec_embed.add_field(
                        name=f"🏃 Uprchlí ({len(escaped_names)})",
                        value=", ".join(escaped_names),
                        inline=False,
                    )
                if dead_names:
                    spec_embed.add_field(
                        name=f"💀 Mrtví ({len(dead_names)})",
                        value=", ".join(dead_names),
                        inline=False,
                    )
                try:
                    await spec_thread.send(embed=spec_embed)
                except Exception:
                    pass

    # ── Pohyb ────────────────────────────────────────────────────────────────

    async def _execute_movement(self, channel_id: int):
        """Provede pohyb všech hráčů do zvolených místností."""
        game = self.active_games.get(channel_id)
        if not game:
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            return

        # Uložit last_round_players pro každou místnost
        for room_id, room in game["map"].items():
            room["last_round_players"] = list(room["players"])

        alive = _alive_players(game)
        movements: dict[str, tuple[str, str]] = {}  # uid -> (from_room, to_room)

        for uid in alive:
            pdata = game["players"][uid]
            dest = pdata.get("door_assignment")
            if not dest or pdata.get("trapped"):
                # Hráč nevybral nebo je v pasti – zůstane
                dest = pdata["room"]
            movements[uid] = (pdata["room"], dest)

        # Odpojit hráče ze starých místností, přidat do nových
        for room in game["map"].values():
            room["players"] = []

        for uid, (from_room, to_room) in movements.items():
            pdata = game["players"][uid]
            pdata["room"] = to_room
            game["map"][to_room]["players"].append(uid)

        # Zajistit vlákna pro nové místnosti a přesunout členy
        for uid, (from_room, to_room) in movements.items():
            if from_room == to_room:
                continue
            member = channel.guild.get_member(int(uid))
            if not member:
                continue

            # Odebrat z původního vlákna
            old_tid = game["map"][from_room]["thread_id"]
            if old_tid:
                old_thread = channel.guild.get_channel_or_thread(old_tid)
                if old_thread:
                    try:
                        await old_thread.remove_user(member)
                    except Exception:
                        pass

            # Přidat do nového vlákna
            room_data = game["map"][to_room]
            if not room_data["thread_id"]:
                new_thread = await self._ensure_room_thread(channel, game, to_room)
                await asyncio.sleep(0.3)
            else:
                new_thread = channel.guild.get_channel_or_thread(room_data["thread_id"])
            if new_thread:
                try:
                    await new_thread.add_user(member)
                except Exception:
                    pass

        # Reset trapped flag po pohybu — byl platný jen jedno kolo
        for uid in _alive_players(game):
            game["players"][uid]["trapped"] = False

        # Arrival events: vražda, akce
        await self._process_arrivals(channel_id)

    # ── Příchody ─────────────────────────────────────────────────────────────

    async def _process_arrivals(self, channel_id: int):
        game = self.active_games.get(channel_id)
        if not game:
            return

        channel = self.bot.get_channel(channel_id)
        murderer_uid = game["murderer_uid"]
        murderer_pdata = game["players"].get(murderer_uid, {})

        # ── Pasti: zachytit příchozí hráče ───────────────────────────────────
        for room_id, trap_info in list(game.get("traps", {}).items()):
            room = game["map"].get(room_id)
            if not room:
                continue
            players_here = [u for u in room["players"] if game["players"][u]["alive"]]
            for uid in players_here:
                if uid == murderer_uid:
                    continue  # vrah nemůže být chycen svou vlastí pastí
                pdata = game["players"][uid]
                if not pdata.get("trapped"):
                    pdata["trapped"] = True
                    thread_id = room["thread_id"]
                    if thread_id:
                        rt = channel.guild.get_channel_or_thread(thread_id)
                        if rt:
                            try:
                                await rt.send(
                                    f"🪤 **{pdata['name']}** se chytil/a do pasti! "
                                    f"Příští kolo se nemůže pohnout."
                                )
                            except Exception:
                                pass
                    member = channel.guild.get_member(int(uid))
                    if member:
                        try:
                            await member.send(
                                f"🪤 Chytil/a jsi se do pasti v místnosti **{room_id}**! "
                                f"Toto kolo se nemůžeš pohnout."
                            )
                        except discord.Forbidden:
                            pass
            # Pokud Pastičkář v místnosti a je tu chycená oběť
            if murderer_pdata.get("alive") and murderer_pdata.get("room") == room_id:
                trapped_victims = [u for u in players_here
                                   if game["players"][u].get("trapped") and u != murderer_uid]
                if trapped_victims:
                    victim_uid = trapped_victims[0]
                    murderer_member = channel.guild.get_member(int(murderer_uid))
                    if murderer_member:
                        view = MurderView(self, game, murderer_uid, victim_uid)
                        victim_name = game["players"][victim_uid]["name"]
                        try:
                            await murderer_member.send(
                                f"🪤 **{victim_name}** je chycen/a v pasti v místnosti {room_id}!\n"
                                f"Máš 60 sekund na rozhodnutí.",
                                view=view,
                            )
                        except discord.Forbidden:
                            pass
            # Past je jednorázová — smazat po aktivaci
            game["traps"].pop(room_id, None)
            room["trap"] = None

        # Zkontrolovat příležitost k vraždě:
        # Vrah je naživu a je sám s přesně jedním hráčem
        if murderer_pdata.get("alive"):
            m_room = murderer_pdata["room"]
            players_with_murderer = [
                u for u in game["map"][m_room]["players"]
                if game["players"][u]["alive"]
            ]
            if len(players_with_murderer) == 2:
                victim_uid = next(u for u in players_with_murderer if u != murderer_uid)
                # Pošli vrahoví ephemeral tlačítko DM
                murderer_member = channel.guild.get_member(int(murderer_uid))
                if murderer_member:
                    view = MurderView(self, game, murderer_uid, victim_uid)
                    victim_name = game["players"][victim_uid]["name"]
                    try:
                        await murderer_member.send(
                            f"🔪 Jsi sám/sama s **{victim_name}** v místnosti {m_room}!\n"
                            f"Máš 60 sekund na rozhodnutí.",
                            view=view,
                        )
                    except discord.Forbidden:
                        pass

        # Odeslat action view do každé obsazené místnosti
        await asyncio.sleep(1)  # krátká pauza před akcemi
        alive = _alive_players(game)
        occupied_rooms = set(game["players"][uid]["room"] for uid in alive)

        # Event pro předčasné ukončení kola (všichni zakončili tah)
        round_event = asyncio.Event()
        game["round_done_event"] = round_event
        game["actions_done"] = set()

        for room_id in occupied_rooms:
            room = game["map"][room_id]
            thread_id = room["thread_id"]
            if not thread_id:
                continue
            thread = channel.guild.get_channel_or_thread(thread_id)
            if not thread:
                continue

            players_here = [
                game["players"][u]["name"]
                for u in room["players"]
                if game["players"][u]["alive"]
            ]
            action_view = RoomActionView(self, game, room_id)
            await thread.send(
                f"**Kolo {game['round']} — Fáze akcí**\n"
                f"Hráči v místnosti: {', '.join(players_here)}\n"
                f"⏱️ Máte **60 sekund** na akce, nebo klikněte ✅ Zakončit tah.",
                view=action_view,
            )

        # Počkat max 60 sekund — zkrátí se jakmile všichni zakončí tah
        try:
            await asyncio.wait_for(round_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass

        if channel_id not in self.active_games:
            return  # hra skončila

        # Pokud hlasování stále probíhá — pozastavit pohyb a čekat (max 200 s)
        if game.get("vote_in_progress") and game.get("vote_event"):
            try:
                await asyncio.wait_for(game["vote_event"].wait(), timeout=200)
            except asyncio.TimeoutError:
                game["vote_in_progress"] = False

        if channel_id not in self.active_games:
            return  # hra skončila během hlasování

        win = _check_win(game)
        if win:
            await self._end_game(channel_id, win)
        else:
            await self._start_round(channel_id)

    # ── Zapálení svíčky ───────────────────────────────────────────────────────

    async def _light_candle_cb(self, game: dict, room_id: str,
                                uid: str, channel: discord.TextChannel):
        pdata = game["players"].get(uid)
        if not pdata or not pdata["alive"]:
            return False, "Nejsi aktivní hráč."
        room = game["map"][room_id]
        if not room.get("dark") or room.get("candle_lit"):
            return False, "V místnosti není tma nebo svíčka již hoří."
        if "svíčka" not in pdata["items"]:
            return False, "❌ Nemáš svíčku."
        if "zapalovač" not in pdata["items"]:
            return False, "❌ Nemáš zapalovač."
        pdata["items"].remove("svíčka")
        room["candle_lit"] = True
        thread_id = room["thread_id"]
        if thread_id:
            rt = channel.guild.get_channel_or_thread(thread_id)
            if rt:
                try:
                    await rt.send(
                        f"🕯️ **{pdata['name']}** zapálil/a svíčku! Místnost **{room_id}** je nyní osvětlena."
                    )
                except Exception:
                    pass
        return True, "✅ Svíčka zapálena! Místnost je nyní trvale osvětlena."

    # ── Hlasování ────────────────────────────────────────────────────────────

    async def _vote_trigger_cb(self, game: dict, room_id: str,
                                triggerer_uid: str, channel: discord.TextChannel):
        if game.get("vote_used"):
            return False, "Hlasování již proběhlo."
        game["vote_used"] = True
        game["vote_in_progress"] = True
        game["vote_event"] = asyncio.Event()
        triggerer_name = game["players"][triggerer_uid]["name"]

        alive = _alive_players(game)
        innocents_in_vote = [u for u in alive if u != game["murderer_uid"]]
        suspect_options = [
            discord.SelectOption(label=game["players"][u]["name"], value=u, emoji="👤")
            for u in alive
        ]
        if not suspect_options:
            game["vote_in_progress"] = False
            game["vote_event"].set()
            return False, "Žádní hráči k obvinění."

        await channel.send(
            f"🔴 **{triggerer_name}** stiskl/a červené tlačítko v místnosti {room_id}!\n"
            f"**Globální hlasování!** Nevinní mají **60 sekund** na poradní vlákno — pak proběhne tajné DM hlasování.\n"
            f"⏸️ *Pohyb v labyrintu je dočasně pozastaven do výsledku hlasování.*"
        )

        async def run_vote():
            def _end_vote():
                game["vote_in_progress"] = False
                if "vote_event" in game:
                    game["vote_event"].set()

            # ── Konferenční vlákno pro diskuzi (60 s) ──────────────────────
            conf_thread = None
            try:
                conf_thread = await channel.create_thread(
                    name="🗳️ Poradní vlákno — Kdo je vrah?",
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                )
                for inn_uid in innocents_in_vote:
                    member = channel.guild.get_member(int(inn_uid))
                    if member:
                        try:
                            await conf_thread.add_user(member)
                        except Exception:
                            pass
                await conf_thread.send(
                    "🗳️ **Poradní vlákno** — máte **60 sekund** na diskuzi.\n"
                    "Vrah zde není přítomen. Po uplynutí času dostanete DM s hlasovacím lístkem."
                )
            except Exception as e:
                print(f"[Labyrinth] Konferenční vlákno: {e}")

            await asyncio.sleep(60)

            if conf_thread:
                try:
                    await conf_thread.send("⏱️ Diskuze skončila. Probíhá tajné hlasování v DM…")
                    await conf_thread.edit(archived=True)
                except Exception:
                    pass

            # ── Helper: odeslat hlasovací DMs ──────────────────────────────
            async def send_vote_dms(options: list, v_counts: dict,
                                    v_voted: set, v_lock, suffix: str):
                for u in innocents_in_vote:
                    member = channel.guild.get_member(int(u))
                    if not member:
                        continue
                    select = discord.ui.Select(
                        placeholder="Kdo je vrah?",
                        options=options[:25],
                        custom_id=f"vote_sel_{u}_{suffix}",
                    )

                    async def make_cb(voter_uid: str):
                        async def cb(si: discord.Interaction):
                            if str(si.user.id) != voter_uid:
                                await si.response.send_message("To není tvůj hlas.", ephemeral=True)
                                return
                            async with v_lock:
                                if voter_uid in v_voted:
                                    await si.response.send_message("Už jsi hlasoval/a.", ephemeral=True)
                                    return
                                v_voted.add(voter_uid)
                                v_counts[si.data["values"][0]] = v_counts.get(si.data["values"][0], 0) + 1
                            await si.response.send_message("✅ Tvůj hlas byl zaznamenán.", ephemeral=True)
                        return cb

                    select.callback = await make_cb(u)
                    v_view = discord.ui.View(timeout=60)
                    v_view.add_item(select)
                    header = (
                        "🗳️ **Druhé kolo hlasování** (remíza) — vyber z remízujících:"
                        if suffix == "r2" else "🗳️ **Hlasování!** Kdo je vrah?"
                    )
                    try:
                        await member.send(header, view=v_view)
                    except discord.Forbidden:
                        pass

            # ── Helper: vyhodnotit výsledek ────────────────────────────────
            async def resolve(counts: dict, is_retry: bool = False):
                if not counts:
                    await channel.send(
                        "🔴 Hlasování skončilo bez výsledku — nikdo nehlasoval.\n**Hra pokračuje!** Vrah je stále na svobodě. 🔪"
                    )
                    _end_vote()
                    return

                max_v = max(counts.values())
                top = [u for u, c in counts.items() if c == max_v]

                if len(top) > 1 and not is_retry:
                    names_tied = ", ".join(game["players"][u]["name"] for u in top)
                    await channel.send(
                        f"🤝 **Remíza!** Nejvíce hlasů dostali: **{names_tied}**.\n"
                        f"**Druhé kolo hlasování** — hlasujte pouze mezi nimi."
                    )
                    r2_counts: dict[str, int] = {}
                    r2_lock = asyncio.Lock()
                    r2_voted: set[str] = set()
                    tied_opts = [
                        discord.SelectOption(label=game["players"][u]["name"], value=u, emoji="👤")
                        for u in top
                    ]
                    await send_vote_dms(tied_opts, r2_counts, r2_voted, r2_lock, suffix="r2")
                    await asyncio.sleep(60)
                    await resolve(r2_counts, is_retry=True)
                    return

                if len(top) > 1:
                    await channel.send(
                        "🤝 Ani druhé kolo nepřineslo shodu. **Nikdo nebyl odhalen — hra pokračuje!** 🔪"
                    )
                    _end_vote(game)
                    return
                else:
                    accused_uid = top[0]

                accused_name = game["players"][accused_uid]["name"]
                correct = accused_uid == game["murderer_uid"]
                result_lines = [
                    f"**{game['players'][u]['name']}**: {c} hlasů"
                    for u, c in sorted(counts.items(), key=lambda x: x[1], reverse=True)
                ]
                embed = discord.Embed(
                    title="🗳️ Výsledky hlasování",
                    description="\n".join(result_lines),
                    color=0x27AE60 if correct else 0x8B0000,
                )
                embed.add_field(name="Obviněný", value=f"**{accused_name}**", inline=True)
                embed.add_field(
                    name="Výsledek",
                    value="✅ Správně! Vrah odhalen!" if correct else "❌ Špatně! Vrah unikl.",
                    inline=True,
                )
                await channel.send(embed=embed)
                _end_vote()
                if correct:
                    await self._end_game(channel.id, "innocents")
                else:
                    await channel.send("**Hra pokračuje!** Vrah je stále na svobodě. 🔪")

            # ── Hlavní kolo hlasování ──────────────────────────────────────
            vote_counts: dict[str, int] = {}
            vote_lock = asyncio.Lock()
            voted_uids: set[str] = set()
            await send_vote_dms(suspect_options, vote_counts, voted_uids, vote_lock, suffix="r1")
            await asyncio.sleep(60)
            await resolve(vote_counts)

        asyncio.create_task(run_vote())
        return True, "✅ Poradní vlákno se otevírá — za 60 sekund dostanete DM s hlasovacím lístkem."

    # ── Položení pasti ───────────────────────────────────────────────────────

    async def _trap_place_cb(self, game: dict, room_id: str,
                              uid: str, channel: discord.TextChannel):
        if uid != game["murderer_uid"]:
            return False, "Pouze Pastičkář může klást pasti."
        if game["players"][uid]["role"] != "pastičkář":
            return False, "Pouze Pastičkář může klást pasti."
        room = game["map"][room_id]
        if room.get("trap"):
            return False, "V místnosti již past je."
        room["trap"] = {"placed_by": uid, "round": game["round"]}
        game["traps"][room_id] = room["trap"]
        return True, f"🪤 Past byla položena v místnosti **{room_id}**."

    # ── Vložení kanystru do generátoru ───────────────────────────────────────

    async def _handle_fuel_deposit(self, game: dict, room_id: str,
                                    uid: str, channel: discord.TextChannel | None):
        if not channel:
            return False, "Interní chyba — kanál nenalezen."
        pdata = game["players"].get(uid)
        if not pdata or not pdata["alive"]:
            return False, "Nejsi aktivní hráč."
        if uid == game.get("murderer_uid"):
            return False, "❌ Tuto akci nemůžeš provést."
        if game.get("generator_started"):
            return False, "Generátor už běží."
        if "kanystr" not in pdata["items"]:
            return False, "❌ Nemáš kanystr."
        room = game["map"][room_id]
        if not room.get("is_exit"):
            return False, "Generátor je pouze u výstupu."

        pdata["items"].remove("kanystr")
        game["generator_fuel"] = game.get("generator_fuel", 0) + 1
        fuel = game["generator_fuel"]

        thread_id = room.get("thread_id")
        rt = channel.guild.get_channel_or_thread(thread_id) if thread_id else None

        if fuel >= 3:
            game["generator_started"] = True
            total_codes = game.get("total_codes", 6)
            found = len(game.get("found_codes", []))
            await channel.send(
                f"🔌 **GENERÁTOR SPUŠTĚN!** Dveře EXITu jsou pod proudem!\n"
                f"Nevinní mohou uniknout zadáním kódu ({found}/{total_codes} čísel nalezeno)."
            )
            if rt:
                try:
                    await rt.send(
                        f"🔌 **Generátor se nastartoval!** {pdata['name']} vložil/a poslední kanystr."
                    )
                except Exception:
                    pass
            return True, "✅ Třetí kanystr vložen — **generátor startuje!**"

        # Ještě není 3
        if rt:
            try:
                await rt.send(
                    f"⛽ **{pdata['name']}** vložil/a kanystr do generátoru. "
                    f"Palivo: **{fuel}/3**"
                )
            except Exception:
                pass
        return True, f"⛽ Kanystr vložen. Palivo generátoru: **{fuel}/3**. Potřeba ještě {3 - fuel}."

    # ── Osvobození z pasti ───────────────────────────────────────────────────

    async def _free_cb(self, game: dict, room_id: str,
                        liberator_uid: str, target_uid: str,
                        channel: discord.TextChannel):
        target = game["players"].get(target_uid)
        if not target or not target.get("trapped"):
            return False, "Tento hráč není v pasti."
        target["trapped"] = False
        lib_name = game["players"][liberator_uid]["name"]
        tgt_name = target["name"]
        thread_id = game["map"][room_id]["thread_id"]
        if thread_id:
            rt = channel.guild.get_channel_or_thread(thread_id)
            if rt:
                try:
                    await rt.send(f"🔓 **{lib_name}** osvobodil/a **{tgt_name}** z pasti!")
                except Exception:
                    pass
        return True, f"🔓 **{tgt_name}** byl/a osvobozen/a."

    # ── Masová vražda (Sériový vrah) ─────────────────────────────────────────

    async def _handle_mass_murder(self, channel_id: int, murderer_uid: str,
                                   victim_uids: list[str], channel: discord.TextChannel):
        game = self.active_games.get(channel_id)
        if not game:
            return
        murderer_pdata = game["players"].get(murderer_uid)
        if not murderer_pdata or murderer_pdata.get("mass_kill_used"):
            return
        murderer_pdata["mass_kill_used"] = True

        killed_names = []
        for victim_uid in victim_uids[:2]:
            victim = game["players"].get(victim_uid)
            if not victim or not victim["alive"]:
                continue
            victim["alive"] = False
            room_id = victim["room"]
            body_items = victim["items"][:]
            victim["items"].clear()
            game["map"][room_id]["bodies"].append({
                "uid": victim_uid, "round": game["round"], "name": victim["name"], "items": body_items,
            })
            if victim_uid in game["map"][room_id]["players"]:
                game["map"][room_id]["players"].remove(victim_uid)
            killed_names.append(victim["name"])
            victim_member = channel.guild.get_member(int(victim_uid))
            await self._move_to_spectator(channel_id, victim_uid, victim_member, channel)

        if killed_names:
            m_room = murderer_pdata["room"]
            thread_id = game["map"][m_room]["thread_id"]
            if thread_id:
                rt = channel.guild.get_channel_or_thread(thread_id)
                if rt:
                    try:
                        await rt.send(
                            f"💀💀 **Masová vražda!** **{', '.join(killed_names)}** "
                            f"byli zabiti jedním úderem!"
                        )
                    except Exception:
                        pass

        win = _check_win(game)
        if win:
            await self._end_game(channel_id, win)

    # ── Střelba ──────────────────────────────────────────────────────────────

    async def _handle_shoot(self, channel_id: int, shooter_uid: str,
                             target_uid: str, channel: discord.TextChannel):
        game = self.active_games.get(channel_id)
        if not game:
            return

        shooter = game["players"].get(shooter_uid)
        target = game["players"].get(target_uid)
        if not shooter or not target:
            return
        if not target["alive"]:
            return

        if shooter.get("pistol_cooldown", 0) > 0:
            return  # server-side guard — nemělo by nastat za normálních podmínek
        shooter["shot_this_round"] = True
        shooter["shoot_target"] = target_uid
        if "pistole" in shooter["items"]:
            shooter["items"].remove("pistole")  # jednorázový výstřel

        # Zasažen
        target["alive"] = False
        room_id = target["room"]
        body_items_t = target["items"][:]
        target["items"].clear()
        game["map"][room_id]["bodies"].append({
            "uid": target_uid,
            "round": game["round"],
            "name": target["name"],
            "items": body_items_t,
        })
        if target_uid in game["map"][room_id]["players"]:
            game["map"][room_id]["players"].remove(target_uid)

        target_member = channel.guild.get_member(int(target_uid))
        shooter_member = channel.guild.get_member(int(shooter_uid))

        # Oznámení ve vlákně
        room_thread_id = game["map"][room_id]["thread_id"]
        if room_thread_id:
            rt = channel.guild.get_channel_or_thread(room_thread_id)
            if rt:
                await rt.send(
                    f"💥 **{shooter['name']}** vystřelil/a! **{target['name']}** byl/a zasažen/a a zemřel/a!"
                )

        # Přesunout do spectator vlákna
        await self._move_to_spectator(channel_id, target_uid, target_member, channel)

        # Pokud byl zabit vrah – konec
        if target_uid == game["murderer_uid"]:
            if room_thread_id:
                rt = channel.guild.get_channel_or_thread(room_thread_id)
                if rt:
                    await rt.send("🎉 **Vrah byl zastřelen! Nevinní vyhráli!**")
            await self._end_game(channel_id, "innocents")
        else:
            win = _check_win(game)
            if win:
                await self._end_game(channel_id, win)

    # ── Vražda ───────────────────────────────────────────────────────────────

    async def _handle_murder(self, channel_id: int, murderer_uid: str,
                              victim_uid: str, channel: discord.TextChannel):
        game = self.active_games.get(channel_id)
        if not game:
            return

        victim = game["players"].get(victim_uid)
        if not victim or not victim["alive"]:
            return

        murderer_pdata_check = game["players"].get(murderer_uid, {})
        has_machete = "mačeta" in murderer_pdata_check.get("items", [])

        # Zbraně obrany (50% šance zabít vraha) — Mačeta je přebíjí
        defense_weapons = [w for w in ["nůž", "baseballka", "sekáček", "vrtačka"]
                           if w in victim.get("items", [])]
        if defense_weapons and not has_machete and random.random() < 0.5:
            used_weapon = defense_weapons[0]
            victim["items"].remove(used_weapon)
            murderer_pdata = game["players"][murderer_uid]
            murderer_pdata["alive"] = False
            m_room = murderer_pdata["room"]
            m_body_items = murderer_pdata["items"][:]
            murderer_pdata["items"].clear()
            game["map"][m_room]["bodies"].append({
                "uid": murderer_uid,
                "round": game["round"],
                "name": murderer_pdata["name"],
                "items": m_body_items,
            })
            if murderer_uid in game["map"][m_room]["players"]:
                game["map"][m_room]["players"].remove(murderer_uid)

            victim_member = channel.guild.get_member(int(victim_uid))
            murderer_member = channel.guild.get_member(int(murderer_uid))
            if victim_member:
                try:
                    await victim_member.send(
                        f"⚔️ Tvá **{ITEM_EMOJI.get(used_weapon, '🔪')} {used_weapon}** zasáhla! "
                        f"**{murderer_pdata['name']}** (vrah) zemřel/a! Nevinní vyhráli!"
                    )
                except discord.Forbidden:
                    pass

            rt_id = game["map"][m_room]["thread_id"]
            if rt_id:
                rt = channel.guild.get_channel_or_thread(rt_id)
                if rt:
                    await rt.send(
                        f"⚔️ **{victim['name']}** použil/a {ITEM_EMOJI.get(used_weapon, '🔪')} {used_weapon}! "
                        f"**{murderer_pdata['name']}** byl/a zabit/a — byl/a to Vrah!"
                    )
            await self._move_to_spectator(channel_id, murderer_uid, murderer_member, channel)
            await self._end_game(channel_id, "innocents")
            return

        # Oběť zemřela
        victim["alive"] = False
        room_id = victim["room"]
        body_items_v = victim["items"][:]
        victim["items"].clear()
        game["map"][room_id]["bodies"].append({
            "uid": victim_uid,
            "round": game["round"],
            "name": victim["name"],
            "items": body_items_v,
        })
        if victim_uid in game["map"][room_id]["players"]:
            game["map"][room_id]["players"].remove(victim_uid)

        victim_member = channel.guild.get_member(int(victim_uid))
        rt_id = game["map"][room_id]["thread_id"]
        if rt_id:
            rt = channel.guild.get_channel_or_thread(rt_id)
            if rt:
                await rt.send(
                    f"💀 **{victim['name']}** byl/a nalezen/a mrtvý/á. "
                    f"Tělo leží v místnosti {room_id}."
                )

        # Amulet Druhé Naděje – přidat do fronty oživení
        if "amulet" in victim["items"]:
            victim["items"].remove("amulet")
            game.setdefault("pending_revivals", []).append({
                "uid": victim_uid,
                "room_id": room_id,
                "name": victim["name"],
                "round": game["round"],
            })
            if victim_member:
                try:
                    await victim_member.send(
                        f"🔮 **Amulet Druhé Naděje** se aktivoval! "
                        f"Budeš oživen/a, jakmile vrah opustí místnost **{room_id}**."
                    )
                except discord.Forbidden:
                    pass
            # Amulet hráče "zachrání" — nevolat _move_to_spectator
        else:
            await self._move_to_spectator(channel_id, victim_uid, victim_member, channel)

        # Doktor může oživit (pokud má lékárničku) – zpráva do jeho vlákna
        doctors_alive = [
            u for u, p in game["players"].items()
            if p["alive"] and p["role"] == "doktor" and "lékárnička" in p["items"]
        ]
        for doc_uid in doctors_alive:
            doc_room_id = game["players"][doc_uid]["room"]
            doc_thread_id = game["map"][doc_room_id].get("thread_id")
            if doc_thread_id:
                doc_thread = channel.guild.get_channel_or_thread(doc_thread_id)
                if doc_thread:
                    try:
                        doc_member = channel.guild.get_member(int(doc_uid))
                        mention = doc_member.mention if doc_member else "Doktore"
                        await doc_thread.send(
                            f"💊 {mention} — **{victim['name']}** zemřel/a! Máš lékárničku – "
                            f"můžeš ho oživit příkazem v místnosti kde leží tělo."
                        )
                    except Exception:
                        pass

        win = _check_win(game)
        if win:
            await self._end_game(channel_id, win)

    # ── Oživení (Doktor) ─────────────────────────────────────────────────────

    async def _handle_revive(self, channel_id: int, doctor_uid: str, target_uid: str,
                              room_id: str, channel: discord.TextChannel):
        game = self.active_games.get(channel_id)
        if not game:
            return

        doctor = game["players"].get(doctor_uid)
        target = game["players"].get(target_uid)
        if not doctor or not target:
            return
        if doctor.get("revived_this_game"):
            return

        room = game["map"][room_id]

        # Odeber tělo z místnosti
        room["bodies"] = [b for b in room["bodies"] if b["uid"] != target_uid]

        # Oživení
        target["alive"] = True
        target["room"] = room_id
        room["players"].append(target_uid)
        doctor["items"].remove("lékárnička")
        doctor["revived_this_game"] = True

        # Přidat oživenému hráče do vlákna
        target_member = channel.guild.get_member(int(target_uid))
        if target_member:
            thread_id = room["thread_id"]
            if thread_id:
                thread = channel.guild.get_channel_or_thread(thread_id)
                if thread:
                    try:
                        await thread.add_user(target_member)
                    except Exception:
                        pass
            try:
                await target_member.send(
                    f"💊 **{doctor['name']}** tě oživil/a! Jsi zpět v místnosti **{room_id}**."
                )
            except discord.Forbidden:
                pass

        # Oznámení v místnosti
        thread_id = room["thread_id"]
        if thread_id:
            rt = channel.guild.get_channel_or_thread(thread_id)
            if rt:
                await rt.send(
                    f"💊 **{doctor['name']}** použil/a lékárničku a oživil/a **{target['name']}**!"
                )

    # ── Útěk ─────────────────────────────────────────────────────────────────

    async def _handle_escape(self, channel_id: int, uid: str,
                              channel: discord.TextChannel):
        game = self.active_games.get(channel_id)
        if not game:
            return

        pdata = game["players"][uid]
        pdata["alive"] = False
        pdata["escaped"] = True

        room_id = pdata["room"]
        if uid in game["map"][room_id]["players"]:
            game["map"][room_id]["players"].remove(uid)

        member = channel.guild.get_member(int(uid))

        # První útěk otevře dveře pro všechny
        if not game.get("exit_opened"):
            game["exit_opened"] = True
            await channel.send(
                f"🚪 **{pdata['name']}** zadal/a správný kód!\n"
                f"**EXIT JE OTEVŘEN!** Ostatní nevinní se nyní mohou volně pokusit o útěk bez kódu!"
            )
        else:
            await channel.send(
                f"🏃 **{pdata['name']}** uprchl/a otevřenými dveřmi!"
            )

        rt_id = game["map"][room_id]["thread_id"]
        if rt_id:
            rt = channel.guild.get_channel_or_thread(rt_id)
            if rt:
                await rt.send(f"🚪 **{pdata['name']}** prošel/la výstupem a unikl/a!")

        # Přesunout do spectator vlákna jako "bezpečný"
        await self._move_to_spectator(channel_id, uid, member, channel, escaped=True)

        # Hra končí jen pokud nikdo živý (nebo v čekárně) nezbyl — jinak pokračuje
        win = _check_win(game)
        if win:
            await self._end_game(channel_id, win)

    # ── Přesun do diváků ─────────────────────────────────────────────────────

    async def _move_to_spectator(self, channel_id: int, uid: str,
                                  member: discord.Member | None,
                                  channel: discord.TextChannel,
                                  escaped: bool = False):
        game = self.active_games.get(channel_id)
        if not game or not member:
            return

        spec_id = game.get("spectator_thread_id")
        if spec_id:
            spec_thread = channel.guild.get_channel_or_thread(spec_id)
            if spec_thread:
                try:
                    await spec_thread.add_user(member)
                    status = "uprchl/a" if escaped else "byl/a eliminován/a"
                    await spec_thread.send(f"👁️ **{member.display_name}** {status}.")
                except Exception:
                    pass

        if not escaped:
            try:
                await member.send(
                    "💀 **Byl/a jsi vyřazen/a z labyrintu.**\n"
                    "Byl/a jsi přesunut/a do divácké tribuny — sleduj průběh hry, "
                    "ale nekomunikuj s aktivními hráči."
                )
            except discord.Forbidden:
                pass

        # Odebrat ze všech místnostních vláken
        for room in game["map"].values():
            if uid in room["players"]:
                room["players"].remove(uid)
            tid = room["thread_id"]
            if tid:
                rt = channel.guild.get_channel_or_thread(tid)
                if rt:
                    try:
                        await rt.remove_user(member)
                    except Exception:
                        pass

    # ── Konec hry ────────────────────────────────────────────────────────────

    async def _end_game(self, channel_id: int, winner: str):
        game = self.active_games.pop(channel_id, None)
        if not game:
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            return

        # Zrušená hra — jen archivuj, nezapisuj výhry
        if winner == "_cancelled":
            for room in game["map"].values():
                tid = room["thread_id"]
                if tid:
                    try:
                        rt = channel.guild.get_channel_or_thread(tid)
                        if rt:
                            await rt.edit(archived=True)
                    except Exception:
                        pass
            self._door_views.pop(channel_id, None)
            return

        murderer_uid = game["murderer_uid"]
        murderer_name = game["players"][murderer_uid]["name"]

        if winner == "innocents":
            title = "🏆 Nevinní vyhráli!"
            desc = "Podařilo se jim uniknout nebo odhalit vraha."
            color = 0x27AE60
            # Výhra: hráč unikl NEBO přežil (vrah eliminován hlasováním/pistolí)
            for uid, p in game["players"].items():
                if uid != murderer_uid and (p.get("escaped") or p.get("alive")):
                    _record_win(uid)
        else:
            title = "💀 Vrah zvítězil!"
            desc = f"**{murderer_name}** eliminoval/a všechny nevinné. Nikdo neunikl."
            color = 0x8B0000
            _record_win(murderer_uid)

        # Odhalení
        reveal_lines = []
        for uid, pdata in game["players"].items():
            if uid == murderer_uid:
                status_emoji = "🔪"
                status_label = "VRAH"
            elif pdata.get("escaped"):
                status_emoji = "🏃"
                status_label = "unikl/a"
            elif pdata.get("alive"):
                status_emoji = "👤"
                status_label = "přežil/a"
            else:
                status_emoji = "💀"
                status_label = "zabit/a"
            role_display = pdata["role"]
            if pdata["role"] == "blázen" and pdata.get("fake_role"):
                role_display = f"blázen *(myslel/a sis, že jsi {pdata['fake_role']})*"
            reveal_lines.append(
                f"{status_emoji} **{pdata['name']}** — {role_display} *({status_label})*"
            )

        embed = discord.Embed(title=title, description=desc, color=color)
        embed.add_field(name="Vrah byl", value=f"💀 **{murderer_name}**", inline=True)
        embed.add_field(name="Kol odehráno", value=str(game["round"]), inline=True)
        embed.add_field(
            name="Odhalení rolí",
            value="\n".join(reveal_lines),
            inline=False,
        )
        await channel.send(embed=embed)

        # Archivovat vlákna místností
        for room in game["map"].values():
            tid = room["thread_id"]
            if tid:
                try:
                    rt = channel.guild.get_channel_or_thread(tid)
                    if rt:
                        await rt.send("🔒 Hra skončila. Toto vlákno bude archivováno.")
                        await rt.edit(archived=True)
                except Exception:
                    pass

        # Archivovat spectator vlákno
        spec_id = game.get("spectator_thread_id")
        if spec_id:
            try:
                st = channel.guild.get_channel_or_thread(spec_id)
                if st:
                    await st.edit(archived=True)
            except Exception:
                pass

        # Vyčistit door views
        self._door_views.pop(channel_id, None)

    # ══════════════════════════════════════════════════════════════════════════
    # SLASH PŘÍKAZY
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(
        name="labyrinth_start",
        description="Vytvoří lobby pro Door Labyrinth (sociálně-dedukční hra)"
    )
    async def labyrinth_start(self, interaction: discord.Interaction):
        if interaction.channel.id in self.active_games:
            await interaction.response.send_message(
                "V tomto kanálu už hra běží!", ephemeral=True
            )
            return

        view = LabyrinthLobby(self, interaction.user)
        await interaction.response.send_message(embed=view._embed(), view=view)

    @app_commands.command(
        name="labyrinth_cancel",
        description="[Admin] Zruší běžící hru Door Labyrinth"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def labyrinth_cancel(self, interaction: discord.Interaction):
        game = self.active_games.get(interaction.channel.id)
        if not game:
            await interaction.response.send_message("Žádná hra neběží.", ephemeral=True)
            return

        await interaction.response.defer()
        await self._end_game(interaction.channel.id, "_cancelled")
        # _end_game popped the game, re-pop in case it wasn't the same channel
        self.active_games.pop(interaction.channel.id, None)
        await interaction.followup.send("🚫 Hra byla zrušena adminem.")

    @labyrinth_cancel.error
    async def cancel_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Jen admin může zrušit hru.", ephemeral=True
            )

    @app_commands.command(
        name="labyrinth_leaderboard",
        description="Žebříček výher Door Labyrinth"
    )
    async def labyrinth_leaderboard(self, interaction: discord.Interaction):
        scores = _load_scores()
        if not scores:
            await interaction.response.send_message(
                "Žebříček je zatím prázdný.", ephemeral=True
            )
            return

        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
        medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
        lines = []
        for i, (uid, wins) in enumerate(top):
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"<@{uid}>"
            lines.append(f"{medals[i]} **{name}** — {wins} výher")

        embed = discord.Embed(
            title="🚪 Door Labyrinth — Žebříček",
            description="\n".join(lines),
            color=0x8B0000,
        )
        embed.set_footer(text="Top 10 | počet výher")
        await interaction.response.send_message(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# SETUP
# ══════════════════════════════════════════════════════════════════════════════

async def setup(bot: commands.Bot):
    await bot.add_cog(LabyrinthCog(bot))
