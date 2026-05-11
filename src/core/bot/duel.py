"""
/duel @hráč <sázka> — Textová tahová 1v1 aréna. Minigame pro ArionBOT.
"""
import asyncio
import random
import discord
from discord.ext import commands
from discord import app_commands

from src.utils.paths import ECONOMY as ECONOMY_FILE
from src.utils.json_utils import load_json, save_json

COIN = "<:goldcoin:1490171741237018795>"

# ── Bojové třídy ──────────────────────────────────────────────────────────────

CLASSES: dict[str, dict] = {
    "Monk": {
        "emoji": "🥷", "hp": 85, "stamina": 120, "recover": 40,
        "dmg_mod": 1.00, "color": 0xE67E22,
        "passive": "Meditative Flow — recover obnovuje 40 staminy",
        "lore": "Disciplinovaný bojovník těla i ducha. Nikdy neutíká od boje.",
    },
    "Knight": {
        "emoji": "🛡️", "hp": 120, "stamina": 80, "recover": 25,
        "dmg_mod": 1.15, "color": 0x95A5A6,
        "passive": "Iron Fortress — guard absorbuje extra 20 % damage",
        "lore": "Obrněný válečník. Pomalý. Neúprosný.",
    },
    "Rogue": {
        "emoji": "🗡️", "hp": 75, "stamina": 105, "recover": 35,
        "dmg_mod": 0.95, "color": 0x2C3E50,
        "passive": "Shadow Step — dodge vyhýbá i lehkým útokům",
        "lore": "Rychlý a zákeřný. Kdo ho uvidí, je mrtvý.",
    },
    "Berserker": {
        "emoji": "🪓", "hp": 100, "stamina": 90, "recover": 30,
        "dmg_mod": 1.35, "color": 0xE74C3C,
        "passive": "Blood Rage — pod 30 HP: poškození +50 %",
        "lore": "Šílený válečník. Čím méně HP, tím nebezpečnější.",
    },
    "Guardian": {
        "emoji": "⚜️", "hp": 110, "stamina": 85, "recover": 30,
        "dmg_mod": 1.00, "color": 0x27AE60,
        "passive": "Thorns — guard vrací 10 damage útočníkovi",
        "lore": "Neproniknutelný. Protiúder je smrtící.",
    },
    "Duelist": {
        "emoji": "🤺", "hp": 80, "stamina": 100, "recover": 35,
        "dmg_mod": 1.05, "color": 0x9B59B6,
        "passive": "Perfect Parry — parry counter +50 % damage",
        "lore": "Elegantní. Každá akce je kalkulovaná.",
    },
}

CLASS_NAMES = list(CLASSES.keys())

# ── Akce ─────────────────────────────────────────────────────────────────────

STAM_COSTS = {
    "attack": 15, "heavy": 25, "guard": 10,
    "parry": 20,  "feint": 12, "dodge": 15, "recover": 0,
}

BTN_CFG = [
    ("attack",  discord.ButtonStyle.red,     "⚔️ Attack"),
    ("heavy",   discord.ButtonStyle.red,     "🪓 Heavy"),
    ("guard",   discord.ButtonStyle.green,   "🛡️ Guard"),
    ("parry",   discord.ButtonStyle.green,   "⚡ Parry"),
    ("feint",   discord.ButtonStyle.blurple, "🎭 Feint"),
    ("dodge",   discord.ButtonStyle.blurple, "💨 Dodge"),
    ("recover", discord.ButtonStyle.grey,    "💚 Recover"),
]

BASE_ATK   = 20
BASE_HEAVY = 35
PARRY_CTR  = 15

# ── Fighter & DuelState ───────────────────────────────────────────────────────

class Fighter:
    def __init__(self, member: discord.Member, cls_name: str):
        self.member   = member
        self.cls_name = cls_name
        cls           = CLASSES[cls_name]
        self.hp       = cls["hp"]
        self.max_hp   = cls["hp"]
        self.stamina  = cls["stamina"]
        self.max_sta  = cls["stamina"]
        self.action: str | None = None

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def exhausted(self) -> bool:
        return self.stamina < 5

class DuelState:
    def __init__(self, f1: Fighter, f2: Fighter, bet: int, channel: discord.TextChannel):
        self.f1      = f1
        self.f2      = f2
        self.bet     = bet
        self.channel = channel
        self.round   = 0
        self.done    = False
        self._lock   = asyncio.Lock()
        self.arena_msg: discord.Message | None = None

    def both_chose(self) -> bool:
        return self.f1.action is not None and self.f2.action is not None

# ── Active duels registry ─────────────────────────────────────────────────────

_active: dict[int, DuelState] = {}

def _register(state: DuelState):
    _active[state.f1.member.id] = state
    _active[state.f2.member.id] = state

def _cleanup(state: DuelState):
    _active.pop(state.f1.member.id, None)
    _active.pop(state.f2.member.id, None)
    state.done = True

# ── Vizuální helpers ──────────────────────────────────────────────────────────

def _bar(cur: int, max_: int, n: int = 10) -> str:
    filled = max(0, round(n * max(0, cur) / max_))
    return "█" * filled + "░" * (n - filled)

def _hp_icon(hp: int, max_hp: int) -> str:
    r = hp / max_hp
    return "🟢" if r > 0.55 else ("🟡" if r > 0.25 else "🔴")

def _fighter_bar(f: Fighter) -> str:
    cls  = CLASSES[f.cls_name]
    hi   = _hp_icon(max(0, f.hp), f.max_hp)
    return (
        f"{cls['emoji']} **{f.member.display_name}** — {f.cls_name}\n"
        f"`HP  [{_bar(f.hp, f.max_hp)}]` {hi} {max(0, f.hp)}/{f.max_hp}\n"
        f"`STA [{_bar(f.stamina, f.max_sta)}]` ⚡ {max(0, f.stamina)}/{f.max_sta}"
    )

def _hp_warning(f: Fighter) -> str | None:
    pct = f.hp / f.max_hp
    if pct <= 0.15: return f"☠️ **{f.member.display_name}** se sotva drží na nohou..."
    if pct <= 0.28: return f"⚠️ **{f.member.display_name}** je těžce raněn!"
    return None

# ── Damage resolution ─────────────────────────────────────────────────────────

def _rdm(base: int, var: int = 4) -> int:
    return base + random.randint(-var, var)

def _eff(f: Fighter, base: int) -> int:
    stam_mod  = max(0.5, f.stamina / f.max_sta)
    class_mod = CLASSES[f.cls_name]["dmg_mod"]
    rage_mod  = 1.5 if f.cls_name == "Berserker" and f.hp <= 30 else 1.0
    return max(1, round(base * class_mod * stam_mod * rage_mod))

def _atk(f: Fighter)  -> int: return _eff(f, _rdm(BASE_ATK))
def _hvy(f: Fighter)  -> int: return _eff(f, _rdm(BASE_HEAVY, 5))
def _ctr(f: Fighter)  -> int:
    mult = 1.5 if f.cls_name == "Duelist" else 1.0
    return max(1, round(PARRY_CTR * mult * CLASSES[f.cls_name]["dmg_mod"]))

def _guard_absorb(f: Fighter, raw: int) -> int:
    absorb = 0.55 if f.cls_name == "Knight" else 0.35
    return round(raw * (1 - absorb))

def resolve_round(state: DuelState) -> list[str]:
    """Resolves one round. Returns list of narrative lines."""
    f1, f2  = state.f1, state.f2
    a1, a2  = f1.action, f2.action
    n1, n2  = f1.member.display_name, f2.member.display_name

    # Stamina cost
    f1.stamina = max(0, f1.stamina - STAM_COSTS.get(a1, 0))
    f2.stamina = max(0, f2.stamina - STAM_COSTS.get(a2, 0))

    # Recover bonus
    if a1 == "recover": f1.stamina = min(f1.max_sta, f1.stamina + CLASSES[f1.cls_name]["recover"])
    if a2 == "recover": f2.stamina = min(f2.max_sta, f2.stamina + CLASSES[f2.cls_name]["recover"])

    d1 = 0  # damage to f1
    d2 = 0  # damage to f2
    log: list[str] = []

    # ── pair helpers ──────────────────────────────────────────────────────────
    # akt = attacker fighter, def = defender fighter
    # returns (dmg_to_defender, dmg_to_attacker)
    def guard_hit(atk: Fighter, grd: Fighter, raw: int):
        dmg   = _guard_absorb(grd, raw)
        thorns = 10 if grd.cls_name == "Guardian" else 0
        log.append(f"🛡️ **{grd.member.display_name}** blokuje — přijímá pouze **{dmg}** damage!")
        if thorns: log.append(f"✀ Thorns vrací **{thorns}** damage útočníkovi!")
        return dmg, thorns

    def parry_hit(pry: Fighter, atk: Fighter, bonus: float = 1.0):
        ctr = round(_ctr(pry) * bonus)
        log.append(f"⚡ **{pry.member.display_name}** PARUJE — counter strike za **{ctr}**!")
        return ctr  # damage dealt to attacker

    # ── RECOVER (mutual) ──────────────────────────────────────────────────────
    if a1 == "recover" and a2 == "recover":
        log.append("💚 Oba si oddechnou. **Napětí stoupá.**")

    elif a1 == "recover":
        log.append(f"💚 **{n1}** nabírá dech...")
        if a2 in ("attack", "heavy", "feint"):
            dmg = (_hvy(f2) if a2 == "heavy" else _atk(f2))
            dmg = round(dmg * 1.3)
            d1  = dmg
            log.append(f"💀 **{n2}** trestá recovery — **{dmg}** damage!")
        else:
            log.append(f"*{n2} nezaútočil.*")

    elif a2 == "recover":
        log.append(f"💚 **{n2}** nabírá dech...")
        if a1 in ("attack", "heavy", "feint"):
            dmg = (_hvy(f1) if a1 == "heavy" else _atk(f1))
            dmg = round(dmg * 1.3)
            d2  = dmg
            log.append(f"💀 **{n1}** trestá recovery — **{dmg}** damage!")
        else:
            log.append(f"*{n1} nezaútočil.*")

    # ── GUARD vs X ────────────────────────────────────────────────────────────
    elif a1 == "guard" and a2 == "guard":
        log.append("🛡️ Oba zvedají štíty — **pat**. Napětí stoupá...")

    elif a1 == "guard":
        if a2 == "attack":
            d1, d2 = guard_hit(f2, f1, _atk(f2))
        elif a2 == "heavy":
            raw = round(_hvy(f2) * 1.3)
            d1, d2 = guard_hit(f2, f1, raw)
            log.append(f"*Heavy útok proniká obranou!*")
        elif a2 == "feint":
            d1 = round(_atk(f2) * 0.85)
            log.append(f"🎭 **{n2}** FEINTUJE kolem guárdu — **{d1}** damage!")
        elif a2 in ("parry", "dodge"):
            log.append("Žádný z bojovníků nezaútočil.")
        else:
            log.append("Klid.")

    elif a2 == "guard":
        if a1 == "attack":
            d2, d1 = guard_hit(f1, f2, _atk(f1))
        elif a1 == "heavy":
            raw = round(_hvy(f1) * 1.3)
            d2, d1 = guard_hit(f1, f2, raw)
            log.append(f"*Heavy útok proniká obranou!*")
        elif a1 == "feint":
            d2 = round(_atk(f1) * 0.85)
            log.append(f"🎭 **{n1}** FEINTUJE kolem guárdu — **{d2}** damage!")
        elif a1 in ("parry", "dodge"):
            log.append("Žádný z bojovníků nezaútočil.")
        else:
            log.append("Klid.")

    # ── PARRY vs X ────────────────────────────────────────────────────────────
    elif a1 == "parry" and a2 == "parry":
        log.append("⚡ Oba jdou na parry — **čepele se zamknou!** Pat.")

    elif a1 == "parry":
        if a2 in ("attack", "heavy"):
            bonus = 1.5 if a2 == "heavy" else 1.0
            d2 = parry_hit(f1, f2, bonus)
            log.append(f"*{n2}'s útok je odražen!*")
        elif a2 == "feint":
            d1 = _atk(f2)
            log.append(f"🎭 **{n2}** FEINTUJE — **{n1}** paruje vzduch! **{d1}** damage!")
        elif a2 == "dodge":
            log.append("Oba čtou stejný moment — žádný kontakt.")
        else:
            log.append(f"**{n1}** čeká na útok... ale {n2} nezaútočil.")

    elif a2 == "parry":
        if a1 in ("attack", "heavy"):
            bonus = 1.5 if a1 == "heavy" else 1.0
            d1 = parry_hit(f2, f1, bonus)
            log.append(f"*{n1}'s útok je odražen!*")
        elif a1 == "feint":
            d2 = _atk(f1)
            log.append(f"🎭 **{n1}** FEINTUJE — **{n2}** paruje vzduch! **{d2}** damage!")
        elif a1 == "dodge":
            log.append("Oba čtou stejný moment — žádný kontakt.")
        else:
            log.append(f"**{n2}** čeká na útok... ale {n1} nezaútočil.")

    # ── DODGE vs X ────────────────────────────────────────────────────────────
    elif a1 == "dodge" and a2 == "dodge":
        log.append("💨 Oba uhýbají — kroužení. Žádný kontakt.")

    elif a1 == "dodge":
        if a2 == "heavy":
            log.append(f"💨 **{n1}** vykročí stranou — heavy mine!")
        elif a2 == "attack":
            if f1.cls_name == "Rogue":
                log.append(f"💨 **{n1}** *(Rogue passive)* — plný dodge i na light útok!")
            else:
                d1 = round(_atk(f2) * 0.45)
                log.append(f"💨 **{n1}** částečně uhýbá — **{d1}** damage!")
        elif a2 == "feint":
            if f1.cls_name == "Rogue":
                log.append(f"💨 **{n1}** čte feint — mizí!")
            else:
                d1 = round(_atk(f2) * 0.45)
                log.append(f"🎭 **{n2}** feintuje, **{n1}** nestačí — **{d1}** damage!")
        else:
            log.append(f"**{n1}** uhýbá — ale {n2} nezaútočil.")

    elif a2 == "dodge":
        if a1 == "heavy":
            log.append(f"💨 **{n2}** vykročí stranou — heavy mine!")
        elif a1 == "attack":
            if f2.cls_name == "Rogue":
                log.append(f"💨 **{n2}** *(Rogue passive)* — plný dodge i na light útok!")
            else:
                d2 = round(_atk(f1) * 0.45)
                log.append(f"💨 **{n2}** částečně uhýbá — **{d2}** damage!")
        elif a1 == "feint":
            if f2.cls_name == "Rogue":
                log.append(f"💨 **{n2}** čte feint — mizí!")
            else:
                d2 = round(_atk(f1) * 0.45)
                log.append(f"🎭 **{n1}** feintuje, **{n2}** nestačí — **{d2}** damage!")
        else:
            log.append(f"**{n2}** uhýbá — ale {n1} nezaútočil.")

    # ── FEINT vs FEINT ────────────────────────────────────────────────────────
    elif a1 == "feint" and a2 == "feint":
        d1 = _atk(f2); d2 = _atk(f1)
        log.append(f"🎭 Oba feintují — oba zaútočí! **{d2}** / **{d1}** damage.")

    # ── ATTACK vs X ───────────────────────────────────────────────────────────
    elif a1 == "attack" and a2 == "attack":
        d1 = _atk(f2); d2 = _atk(f1)
        log.append(f"⚔️ **{n1}** và **{n2}** — čepele se kříží!")
        log.append(f"*Oba bojovníci si vymění údery. **{d2}** / **{d1}** damage.*")

    elif a1 == "attack" and a2 == "feint":
        d1 = _atk(f2); d2 = _atk(f1)
        log.append(f"⚔️ **{n1}** zaútočí — **{n2}** zároveň feintuje. Oba zasáhnou!")

    elif a1 == "feint" and a2 == "attack":
        d1 = _atk(f2); d2 = _atk(f1)
        log.append(f"🎭 **{n1}** feintuje — **{n2}** zároveň zaútočí. Oba zasáhnou!")

    # ── HEAVY vs X ────────────────────────────────────────────────────────────
    elif a1 == "heavy" and a2 == "heavy":
        d1 = _hvy(f2); d2 = _hvy(f1)
        log.append("💥 **MASIVNÍ KOLIZE** — oba heavy útočí!")
        log.append(f"*Aréna se třese. **{d2}** / **{d1}** damage.*")

    elif a1 == "heavy" and a2 == "attack":
        d1 = _atk(f2); d2 = _hvy(f1)
        log.append(f"⚔️ **{n2}** zaútočí rychle — **{n1}**'s heavy také dopadá!")

    elif a1 == "attack" and a2 == "heavy":
        d1 = _hvy(f2); d2 = _atk(f1)
        log.append(f"⚔️ **{n1}** zaútočí rychle — **{n2}**'s heavy také dopadá!")

    elif a1 == "heavy" and a2 == "feint":
        d1 = _atk(f2); d2 = _hvy(f1)
        log.append(f"🪓 **{n1}**'s heavy je příliš odhodlaný — **{n2}** zasáhne feintnem!")

    elif a1 == "feint" and a2 == "heavy":
        d1 = _hvy(f2); d2 = _atk(f1)
        log.append(f"🪓 **{n2}**'s heavy je příliš odhodlaný — **{n1}** zasáhne feintnem!")

    else:
        log.append("Boj pokračuje...")

    # Apply damage
    f1.hp -= d1
    f2.hp -= d2

    if d1 == 0 and d2 == 0:
        log.append("*Žádné poškození.*")

    f1.action = None
    f2.action = None
    return log

# ── Embed builders ────────────────────────────────────────────────────────────

CROWD_LINES = [
    "Dav jásá!", "Aréna zní výkřiky!", "Krev na písku.",
    "Nikdo neopouští svá místa.", "Napětí je hmatatelné.",
]

FINISHERS = [
    "padá na kolena — aréna ztichne.",
    "se zhroutí pod posledním úderem.",
    "zakolísá — a padá.",
    "je poražen. Aréna exploduje!",
    "nemůže vstát. Je po všem.",
]

def build_arena_embed(state: DuelState, round_log: list[str] | None = None) -> discord.Embed:
    f1, f2  = state.f1, state.f2
    parts: list[str] = []

    if round_log:
        sep  = "━" * 22
        parts.append(f"`{sep}`")
        parts.append(f"**Kolo {state.round}** — {random.choice(CROWD_LINES)}")
        parts.extend(round_log)
        parts.append(f"`{sep}`")
        parts.append("")

    parts += [_fighter_bar(f1), "", _fighter_bar(f2)]

    for f in [f1, f2]:
        w = _hp_warning(f)
        if w:
            parts.append("")
            parts.append(w)

    if not round_log:
        parts.append("")
        parts.append("-# *Oba hráči volí akci...*")

    embed = discord.Embed(
        title=f"⚔️  {f1.member.display_name}  vs  {f2.member.display_name}",
        description="\n".join(parts),
        color=0x1a1a2e,
    )
    footer = f"⭐ Aurionis  ·  Kolo {state.round}"
    if state.bet:
        footer += f"  ·  Sázka: {state.bet} {COIN}"
    embed.set_footer(text=footer)
    return embed

def build_intro_embed(state: DuelState) -> discord.Embed:
    f1, f2 = state.f1, state.f2
    c1, c2 = CLASSES[f1.cls_name], CLASSES[f2.cls_name]
    desc = (
        f"{c1['emoji']} **{f1.member.display_name}** — *{f1.cls_name}*\n"
        f"-# {c1['passive']}\n"
        f"-# _{c1['lore']}_\n\n"
        f"{c2['emoji']} **{f2.member.display_name}** — *{f2.cls_name}*\n"
        f"-# {c2['passive']}\n"
        f"-# _{c2['lore']}_\n\n"
        f"**Oba hráči volí svou první akci!**"
    )
    embed = discord.Embed(
        title="⚔️  DUEL ZAČÍNÁ!",
        description=desc,
        color=0x1a1a2e,
    )
    if state.bet:
        embed.set_footer(text=f"💰 Sázka: {state.bet} {COIN} každý  ·  výherce bere vše")
    return embed

def build_finish_embed(winner: Fighter, loser: Fighter, bet: int) -> discord.Embed:
    wcls = CLASSES[winner.cls_name]
    desc = (
        f"{wcls['emoji']} **{winner.member.display_name}** stojí jako vítěz!\n\n"
        f"*{loser.member.display_name} {random.choice(FINISHERS)}*\n"
    )
    if bet:
        desc += f"\n💰 **{winner.member.display_name}** získává **{bet * 2}** {COIN}!"
    embed = discord.Embed(title="☠️  KONEC DUELU", description=desc, color=wcls["color"])
    embed.set_footer(text="⭐ Aurionis")
    return embed

# ── Views ─────────────────────────────────────────────────────────────────────

class ActionView(discord.ui.View):
    """Ephemeral — hráč vybírá akci."""

    def __init__(self, state: DuelState, fighter: Fighter):
        super().__init__(timeout=45)
        self.state   = state
        self.fighter = fighter
        for action, style, label in BTN_CFG:
            btn          = discord.ui.Button(label=label, style=style)
            btn.callback = self._make_cb(action)
            self.add_item(btn)

    def _make_cb(self, action: str):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.fighter.member.id:
                await interaction.response.send_message("Toto není tvůj souboj!", ephemeral=True)
                return
            if self.fighter.action is not None:
                await interaction.response.send_message("Už jsi vybral!", ephemeral=True)
                return
            if self.fighter.exhausted and action not in ("recover", "guard"):
                await interaction.response.edit_message(
                    content=f"⚠️ **Jsi vyčerpaný!** Musíš použít 💚 Recover nebo 🛡️ Guard.\n-# Stamina: {self.fighter.stamina}",
                    view=self,
                )
                return
            self.fighter.action = action
            self.stop()
            await interaction.response.edit_message(
                content=f"✅ Vybral jsi **{action}**. Čekám na soupeře...",
                view=None,
            )
            await _try_resolve(self.state)
        return cb

    async def on_timeout(self):
        if self.fighter.action is None:
            opts = ["recover"] if self.fighter.exhausted else list(STAM_COSTS.keys())
            self.fighter.action = random.choice(opts)
            await _try_resolve(self.state)


class ArenaView(discord.ui.View):
    """Veřejná — tlačítka pro výběr akce."""

    def __init__(self, state: DuelState):
        super().__init__(timeout=120)
        self.state = state
        b1 = discord.ui.Button(
            label=f"⚔️ {state.f1.member.display_name}",
            style=discord.ButtonStyle.red,
        )
        b2 = discord.ui.Button(
            label=f"⚔️ {state.f2.member.display_name}",
            style=discord.ButtonStyle.blurple,
        )
        b1.callback = self._make_choose(state.f1)
        b2.callback = self._make_choose(state.f2)
        self.add_item(b1)
        self.add_item(b2)

    def _make_choose(self, fighter: Fighter):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != fighter.member.id:
                await interaction.response.send_message("Toto není tvůj souboj!", ephemeral=True)
                return
            if self.state.done:
                await interaction.response.send_message("Duel skončil.", ephemeral=True)
                return
            if fighter.action is not None:
                await interaction.response.send_message("✅ Tvá akce je vybrána. Čekáš na soupeře...", ephemeral=True)
                return
            view = ActionView(self.state, fighter)
            sta  = fighter.stamina
            await interaction.response.send_message(
                f"**Kolo {self.state.round + 1}** — Vyber akci!\n-# Stamina: {sta}/{fighter.max_sta}",
                view=view,
                ephemeral=True,
            )
        return cb

    async def on_timeout(self):
        # Force resolve if one player chose but other timed out
        for f in [self.state.f1, self.state.f2]:
            if f.action is None and not self.state.done:
                opts = ["recover"] if f.exhausted else list(STAM_COSTS.keys())
                f.action = random.choice(opts)
        await _try_resolve(self.state)


class ChallengeView(discord.ui.View):
    """Výzva k duelu — přijmout / odmítnout."""

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

        # Economy check & deduct
        if self.bet > 0:
            eco = load_json(ECONOMY_FILE, {})
            c_bal = eco.get(str(self.challenger.id), 0)
            t_bal = eco.get(str(self.target.id), 0)
            if c_bal < self.bet:
                await interaction.response.edit_message(
                    content=f"❌ **{self.challenger.display_name}** nemá dost zlatých pro sázku!", view=None
                )
                return
            if t_bal < self.bet:
                await interaction.response.edit_message(
                    content=f"❌ **{self.target.display_name}** nemá dost zlatých pro sázku!", view=None
                )
                return
            eco[str(self.challenger.id)] = c_bal - self.bet
            eco[str(self.target.id)]     = t_bal - self.bet
            save_json(ECONOMY_FILE, eco)

        # Assign random classes
        cls1, cls2 = random.sample(CLASS_NAMES, 2)
        f1    = Fighter(self.challenger, cls1)
        f2    = Fighter(self.target,     cls2)
        state = DuelState(f1, f2, self.bet, self.channel)
        _register(state)

        # Intro embed + arena
        await interaction.response.edit_message(embed=build_intro_embed(state), view=None)
        state.arena_msg = await self.channel.send(
            embed=build_arena_embed(state), view=ArenaView(state)
        )

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

        if f1_dead or f2_dead:
            winner = state.f2 if f1_dead else state.f1
            loser  = state.f1 if f1_dead else state.f2
            _cleanup(state)

            if state.bet > 0:
                eco = load_json(ECONOMY_FILE, {})
                wid = str(winner.member.id)
                eco[wid] = eco.get(wid, 0) + state.bet * 2
                save_json(ECONOMY_FILE, eco)

            arena_embed = build_arena_embed(state, log)
            if state.arena_msg:
                await state.arena_msg.edit(embed=arena_embed, view=None)
            await state.channel.send(embed=build_finish_embed(winner, loser, state.bet))
        else:
            arena_embed = build_arena_embed(state, log)
            new_view    = ArenaView(state)
            if state.arena_msg:
                await state.arena_msg.edit(embed=arena_embed, view=new_view)
            else:
                state.arena_msg = await state.channel.send(embed=arena_embed, view=new_view)

# ── Cog ───────────────────────────────────────────────────────────────────────

class DuelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="duel", description="Vyzvi hráče na souboj s sázkou!")
    @app_commands.describe(member="Soupeř", bet="Sázka v zlatých (0 = bez sázky)")
    async def duel(self, interaction: discord.Interaction,
                   member: discord.Member, bet: int = 0):
        challenger = interaction.user

        if member.id == challenger.id:
            await interaction.response.send_message("Nemůžeš vyzvat sám sebe.", ephemeral=True)
            return
        if member.bot:
            await interaction.response.send_message("Nemůžeš vyzvat bota.", ephemeral=True)
            return
        if challenger.id in _active:
            await interaction.response.send_message("Už jsi v aktivním duelu!", ephemeral=True)
            return
        if member.id in _active:
            await interaction.response.send_message(f"**{member.display_name}** je už v duelu.", ephemeral=True)
            return
        if bet < 0:
            await interaction.response.send_message("Sázka nesmí být záporná.", ephemeral=True)
            return
        if bet > 0:
            eco   = load_json(ECONOMY_FILE, {})
            bal   = eco.get(str(challenger.id), 0)
            if bal < bet:
                await interaction.response.send_message(
                    f"Nemáš dost zlatých! (máš {bal} {COIN}, potřebuješ {bet})", ephemeral=True
                )
                return

        view = ChallengeView(challenger, member, bet, interaction.channel)
        bet_txt = f" o **{bet}** {COIN}" if bet else ""
        embed = discord.Embed(
            title="⚔️  Výzva k duelu!",
            description=(
                f"{challenger.mention} vyzývá {member.mention} na souboj{bet_txt}!\n\n"
                f"-# Obdržíš náhodnou bojovou třídu. Souboj je tahový — mindgames rozhodují.\n"
                f"-# Sázka je stržena při přijetí."
            ),
            color=0xE74C3C,
        )
        embed.set_footer(text="⭐ Aurionis  ·  Výzva vyprší za 60 sekund")
        msg = await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(DuelCog(bot))
