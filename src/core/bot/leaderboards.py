"""
leaderboards.py — centrální žebříčky přes JEDNU persistentní zprávu.

Cesta: src/core/bot/leaderboards.py
Přidej do main_bot.py BOT_COGS:  "src.core.bot.leaderboards"

Proč soběstačné (čte JSON přímo, neimportuje cizí cog-buildery):
  Žebříčky patří napříč DVĚMA botům (minihry = ArionBOT, XP = ArionDND).
  Jedna hub zpráva ale žije v jednom botovi. Oba boti sdílí volume, takže
  čteme score/profil soubory přímo — funguje bez ohledu na hostitele.

UI:
  #leaderboards drží jednu stálou zprávu s jedním tlačítkem „📊 Otevřít
  žebříčky". Klik pošle EPHEMERAL rozcestník (select) — hráč si vybere
  žebříček a zobrazí se jen jemu (nespamuje kanál). Přežije restart.
"""
import discord
from discord.ext import commands
from discord import app_commands
import logging

from src.utils.paths import PROFILES as PROFILES_FILE
from src.utils.json_utils import load_json, save_json

logger = logging.getLogger("Leaderboards")

# Kanál s hub zprávou
LEADERBOARD_CHANNEL_ID = 1527136386325545020

# Perzistentní stav (id zprávy) — ať ji po restartu najdeme a nevytváříme duplikát
_STATE_FILE_NAME = "leaderboards_hub.json"

def _state_file() -> str:
    from src.utils.paths import data
    return data(_STATE_FILE_NAME)

def _load_state() -> dict:
    return load_json(_state_file(), default={})

def _save_state(d: dict):
    save_json(_state_file(), d)


# ── cesty ke score souborům (na sdíleném volume) ──────────────────────────────
def _data(name: str) -> str:
    from src.utils.paths import data
    return data(name)

MEDALS = ["🥇", "🥈", "🥉"]

def _medal(i: int) -> str:
    return MEDALS[i] if i < 3 else f"**{i+1}.**"

def _name_for(guild, uid: str) -> str:
    """Účtové jméno z Discordu — pro žebříčky klíčované na bare uid."""
    base = uid.split(":")[0]
    member = guild.get_member(int(base)) if guild and base.isdigit() else None
    if member:
        return member.display_name
    # neznámý účet (není v guildě / smazaný) — zkrácené id, ať to nezabírá řádek
    short = base[-4:] if base.isdigit() else base
    return f"Neznámý #{short}"


# Cache profilů v rámci jednoho renderu (ať nečteme soubor pro každý řádek)
def _load_profiles_cache() -> dict:
    return load_json(PROFILES_FILE, default={})

def _char_name_for(guild, pkey_str: str, profiles: dict | None = None) -> str:
    """Jméno KONKRÉTNÍ postavy (uid:slot) z jejího profilu.

    Klíč je pkey = 'uid:slot'. Jméno bereme z profile['name'] — jinak by dvě
    postavy jednoho hráče ukázaly stejné (aktivní) Discord jméno. Fallback:
    Discord jméno účtu, pak holé id.
    """
    profiles = profiles if profiles is not None else _load_profiles_cache()
    prof = profiles.get(pkey_str) or {}
    name = prof.get("name")
    if name:
        return name
    return _name_for(guild, pkey_str)


# ══════════════════════════════════════════════════════════════════════════════
# EMBED BUILDERY  (každý čte svůj JSON přímo)
# ══════════════════════════════════════════════════════════════════════════════

def _minigame_embed(guild, score_file: str, title: str, color: int,
                    currency: str = "silver") -> discord.Embed:
    """Společný tvar minihry: {uid: {profit_gold, profit_silver, wins, games}}."""
    icon   = "🟡" if currency == "gold" else "⚪"
    scores = load_json(_data(score_file), default={})
    rows   = [(uid, rec.get(f"profit_{currency}", 0), rec.get("wins", 0), rec.get("games", 0))
              for uid, rec in scores.items()]
    rows.sort(key=lambda r: r[1], reverse=True)

    lines = []
    for i, (uid, profit, wins, games) in enumerate(rows[:10]):
        sign = "+" if profit >= 0 else ""
        lines.append(f"{_medal(i)} **{_name_for(guild, uid)}** — "
                     f"{sign}{profit} {icon}  ·  {wins}W/{games}")
    embed = discord.Embed(title=title, description="\n".join(lines) or "Zatím nikdo nehrál.",
                          color=color)
    embed.set_footer(text=f"Podle čistého profitu ({'zlato' if currency=='gold' else 'stříbro'})")
    return embed


def _gold_embed(guild, currency: str = "gold") -> discord.Embed:
    """Ekonomika: {pkey: balance}. Soubory economy.json / silver.json."""
    fname = "economy.json" if currency == "gold" else "silver.json"
    icon  = "🟡" if currency == "gold" else "⚪"
    label = "Zlaťáky" if currency == "gold" else "Stříbrňáky"
    data  = load_json(_data(fname), default={})
    profiles = _load_profiles_cache()
    ranked = sorted(data.items(), key=lambda x: x[1], reverse=True)[:10]

    lines = []
    for i, (uid, bal) in enumerate(ranked):
        lines.append(f"{_medal(i)} **{_char_name_for(guild, uid, profiles)}** — **{bal}** {icon}")
    embed = discord.Embed(title=f"💰  Bohatství — {label}",
                          description="\n".join(lines) or "*Zatím tu nikdo nic nemá.*",
                          color=0xFFD700)
    return embed


def _xp_embed(guild) -> discord.Embed:
    """XP/level žebříček z profiles.json: {pkey: {level, xp, name}}."""
    data = load_json(PROFILES_FILE, default={})
    entries = []
    for uid, p in data.items():
        if not isinstance(p, dict):
            continue
        entries.append((uid, p.get("level", 0), p.get("xp", 0)))
    entries.sort(key=lambda x: (x[1], x[2]), reverse=True)

    lines = []
    for i, (uid, level, xp) in enumerate(entries[:10]):
        lines.append(f"{_medal(i)} **{_char_name_for(guild, uid, data)}** — "
                     f"úroveň **{level}**  ·  {xp:,} XP")
    embed = discord.Embed(title="⭐  Zkušenosti — úrovně",
                          description="\n".join(lines) or "*Žádní hráči ještě nemají profil.*",
                          color=0x9B59B6)
    return embed


def _wins_embed(guild, score_file: str, title: str, color: int, unit: str = "výher") -> discord.Embed:
    """Jednoduchý tvar {uid: wins} — guess, liar_dice, liar_slots."""
    scores = load_json(_data(score_file), default={})
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
    lines = [f"{_medal(i)} **{_name_for(guild, uid)}** — {wins} {unit}"
             for i, (uid, wins) in enumerate(ranked)]
    return discord.Embed(title=title, description="\n".join(lines) or "Zatím nikdo nehrál.",
                         color=color)


def _profit_wins_embed(guild, score_file: str, title: str, color: int,
                       currency: str = "silver") -> discord.Embed:
    """Tvar {uid: {wins, losses?, profit_gold, profit_silver, streak?}} — duel."""
    icon   = "🟡" if currency == "gold" else "⚪"
    scores = load_json(_data(score_file), default={})

    def _profit(rec):
        if currency == "silver" and "profit_silver" not in rec and "profit" in rec:
            return rec.get("profit", 0)
        return rec.get(f"profit_{currency}", 0)

    ranked = sorted(scores.items(),
                    key=lambda x: (-x[1].get("wins", 0), -_profit(x[1])))[:10]
    lines = []
    for i, (uid, s) in enumerate(ranked):
        wins, losses = s.get("wins", 0), s.get("losses", 0)
        profit = _profit(s)
        total  = wins + losses
        ratio  = f"{round(wins/total*100)} %" if total else "—"
        psign  = f"+{profit}" if profit > 0 else str(profit) if profit else "—"
        lines.append(f"{_medal(i)} **{_name_for(guild, uid)}** — "
                     f"{wins}V/{losses}P · {ratio}  ·  {psign} {icon if profit else ''}")
    return discord.Embed(title=title, description="\n".join(lines) or "Zatím nikdo nehrál.",
                         color=color)


def _kostky_embed(guild, currency: str = "silver") -> discord.Embed:
    """Kostky jsou GUILD-scoped: {guild_id: {uid: {wins, profit_*}}}."""
    icon = "🟡" if currency == "gold" else "⚪"
    alld = load_json(_data("kostky_leaderboard.json"), default={})
    gid  = str(guild.id) if guild else None
    data = alld.get(gid, {}) if gid else {}

    def _profit(rec):
        if currency == "silver" and "profit_silver" not in rec and "profit" in rec:
            return rec.get("profit", 0)
        return rec.get(f"profit_{currency}", 0)

    ranked = sorted(data.items(), key=lambda x: (-x[1].get("wins", 0), -_profit(x[1])))[:10]
    lines = []
    for i, (uid, s) in enumerate(ranked):
        profit = _profit(s)
        psign  = f"+{profit}" if profit > 0 else str(profit) if profit else "—"
        lines.append(f"{_medal(i)} **{_name_for(guild, uid)}** — "
                     f"{s.get('wins',0)}V  ·  {psign} {icon if profit else ''}")
    return discord.Embed(title="🎲  Kostky — žebříček",
                         description="\n".join(lines) or "Zatím nikdo nehrál.",
                         color=0xE67E22)


# Registr žebříčků: key → (label pro select, emoji, builder, má měnový přepínač?)
BOARDS = {
    "gold": {
        "label": "Bohatství (zlato/stříbro)", "emoji": "💰",
        "builder": lambda guild, cur: _gold_embed(guild, cur), "toggle": True,
    },
    "xp": {
        "label": "Zkušenosti (úrovně)", "emoji": "⭐",
        "builder": lambda guild, cur: _xp_embed(guild), "toggle": False,
    },
    "battleships": {
        "label": "Lodě", "emoji": "⚓",
        "builder": lambda guild, cur: _minigame_embed(
            guild, "battleships_scores.json", "⚓  Lodě — žebříček", 0x3B6EA5, cur),
        "toggle": True,
    },
    "blackjack": {
        "label": "Blackjack", "emoji": "🃏",
        "builder": lambda guild, cur: _minigame_embed(
            guild, "blackjack_scores.json", "🃏  Blackjack — žebříček", 0x1E8449, cur),
        "toggle": True,
    },
    "tictactoe": {
        "label": "Piškvorky", "emoji": "⭕",
        "builder": lambda guild, cur: _minigame_embed(
            guild, "tictactoe_scores.json", "⭕  Piškvorky — žebříček", 0x9B59B6, cur),
        "toggle": True,
    },
    "kostky": {
        "label": "Kostky", "emoji": "🎲",
        "builder": lambda guild, cur: _kostky_embed(guild, cur),
        "toggle": True,
    },
    "duel": {
        "label": "Duely", "emoji": "⚔️",
        "builder": lambda guild, cur: _profit_wins_embed(
            guild, "duel_scores.json", "⚔️  Duel — žebříček", 0x1A1A2E, cur),
        "toggle": True,
    },
    "guess": {
        "label": "Hádej kdo", "emoji": "🔍",
        "builder": lambda guild, cur: _wins_embed(
            guild, "guess_scores.json", "🔍  Hádej kdo — žebříček", 0x9B59B6),
        "toggle": False,
    },
    "liar_dice": {
        "label": "Kostka lháře", "emoji": "🎭",
        "builder": lambda guild, cur: _wins_embed(
            guild, "liar_scores.json", "🎭  Kostka lháře — žebříček", 0xF1C40F),
        "toggle": False,
    },
    "liar_slots": {
        "label": "Liar Slots", "emoji": "🎰",
        "builder": lambda guild, cur: _wins_embed(
            guild, "liar_slots_scores.json", "🎰  Liar Slots — žebříček", 0xFFD700),
        "toggle": False,
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# EPHEMERAL ROZCESTNÍK  (select + volitelný přepínač měny)
# ══════════════════════════════════════════════════════════════════════════════

class BoardSelect(discord.ui.Select):
    def __init__(self, current: str | None = None):
        options = [
            discord.SelectOption(label=meta["label"], value=key, emoji=meta["emoji"],
                                 default=(key == current))
            for key, meta in BOARDS.items()
        ]
        super().__init__(placeholder="🏆 Vyber žebříček…", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        view = DispatcherView(selected=key)
        embed = BOARDS[key]["builder"](interaction.guild, "gold")
        await interaction.response.edit_message(embed=embed, view=view)


class DispatcherView(discord.ui.View):
    """Ephemeral rozcestník — žije jen pro toho, kdo klikl (timeout ok)."""
    def __init__(self, selected: str | None = None):
        super().__init__(timeout=300)
        self.selected = selected
        self.add_item(BoardSelect(current=selected))

        # měnový přepínač jen u žebříčků, co ho mají
        if selected and BOARDS[selected]["toggle"]:
            self.add_item(self._toggle_btn("🟡 Zlato", "gold"))
            self.add_item(self._toggle_btn("⚪ Stříbro", "silver"))

    def _toggle_btn(self, label: str, currency: str) -> discord.ui.Button:
        btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, row=1)
        async def cb(interaction: discord.Interaction):
            embed = BOARDS[self.selected]["builder"](interaction.guild, currency)
            await interaction.response.edit_message(embed=embed, view=self)
        btn.callback = cb
        return btn


# ══════════════════════════════════════════════════════════════════════════════
# PERSISTENTNÍ HUB ZPRÁVA  (jedno tlačítko, přežije restart)
# ══════════════════════════════════════════════════════════════════════════════

class HubView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)   # persistent

    @discord.ui.button(label="Otevřít žebříčky", emoji="📊",
                       style=discord.ButtonStyle.primary,
                       custom_id="leaderboards:open")
    async def open_boards(self, interaction: discord.Interaction, _b):
        # výchozí: rovnou ukaž první žebříček (bohatství) + rozcestník
        first = next(iter(BOARDS))
        embed = BOARDS[first]["builder"](interaction.guild, "gold")
        await interaction.response.send_message(
            embed=embed, view=DispatcherView(selected=first), ephemeral=True)


def _hub_embed() -> discord.Embed:
    lines = [f"{meta['emoji']} **{meta['label']}**" for meta in BOARDS.values()]
    embed = discord.Embed(
        title="🏆  Síň slávy Aurionisu",
        description=("Klikni na **📊 Otevřít žebříčky** a vyber si.\n"
                     "Zobrazí se jen tobě — nezaneseme kanál.\n\n"
                     + "\n".join(lines)),
        color=0xFFD700,
    )
    embed.set_footer(text="⭐ Aurionis")
    return embed


class Leaderboards(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # zaregistruj persistentní view, ať tlačítko funguje i po restartu
        self.bot.add_view(HubView())

    lb = app_commands.Group(name="leaderboards", description="Žebříčky (admin)")

    @lb.command(name="setup", description="[Admin] Vyvěsí/obnoví hub zprávu žebříčků v tomto kanálu.")
    @app_commands.checks.has_permissions(administrator=True)
    async def lb_setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        state = _load_state()

        # zkus najít a přepsat existující zprávu, ať nevzniká duplikát
        old_ch = state.get("channel_id")
        old_msg = state.get("message_id")
        if old_ch and old_msg:
            try:
                ch = self.bot.get_channel(old_ch) or await self.bot.fetch_channel(old_ch)
                msg = await ch.fetch_message(old_msg)
                await msg.edit(embed=_hub_embed(), view=HubView())
                await interaction.followup.send(
                    f"♻️ Hub žebříčků obnoven v {ch.mention}.", ephemeral=True)
                return
            except Exception:
                pass   # stará zpráva pryč → vytvoř novou

        msg = await interaction.channel.send(embed=_hub_embed(), view=HubView())
        _save_state({"channel_id": interaction.channel.id, "message_id": msg.id})
        await interaction.followup.send(
            "✅ Hub žebříčků vyvěšen. Tlačítko přežije restart.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Leaderboards(bot))