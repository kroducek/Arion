import discord
from discord.ext import commands
from discord import app_commands
import logging

from src.utils.paths import PROFILES as PROFILES_FILE
from src.utils.json_utils import load_json, save_json
from src.utils.audit import log_action
from src.database.characters import pkey

logger = logging.getLogger("Ranks")

ARION_NAME = "Aurionis"

# ══════════════════════════════════════════════════════════════════════════════
# LADĚNÍ — všechno, co budeš chtít měnit, je tady nahoře
# ══════════════════════════════════════════════════════════════════════════════

# Žebříček od nejhoršího po nejlepší. Index = pořadí.
RANK_LADDER: list[str] = [
    "F3", "F2", "F1",
    "E3", "E2", "E1",
    "D3", "D2", "D1",
    "C3", "C2", "C1",
    "B3", "B2", "B1",
    "A3", "A2", "A1",
    "S", "S+",
]

STARTING_RANK = "F3"

# Obtížnost questu → kolik bodů ranku dá.
DIFFICULTY: dict[str, dict] = {
    "easy":   {"label": "🟢 Snadný",  "points": 1},
    "normal": {"label": "🟡 Střední", "points": 2},
    "hard":   {"label": "🔴 Těžký",   "points": 3},
    "deadly": {"label": "💀 Smrtící", "points": 5},
}
DEFAULT_DIFFICULTY = "normal"

# Kolik bodů je potřeba na POSTUP z ranku dané třídy (písmeno).
# Roste — na plochých 5 by 20 ranků prolétlo moc rychle.
RANK_COST: dict[str, int] = {
    "F": 5, "E": 6, "D": 8, "C": 10, "B": 13, "A": 16, "S": 20,
}

# Jak se jmenují Discord role. Bot je NEVYTVÁŘÍ — hledá je podle jména.
# Zkouší postupně tyhle tvary, první nalezená vyhrává.
ROLE_NAME_PATTERNS: list[str] = [
    "{rank}",              # "F3"
    "Rank {rank}",         # "Rank F3"
    "Dobrodruh {rank}",    # "Dobrodruh F3"
]

# ══════════════════════════════════════════════════════════════════════════════


def _load() -> dict:
    return load_json(PROFILES_FILE, default={})

def _save(data: dict):
    save_json(PROFILES_FILE, data)

def _profile(data: dict, uid: str) -> dict:
    return data.setdefault(uid, {})


def rank_index(rank: str) -> int:
    """Pozice v žebříčku. Neznámý rank → 0 (start)."""
    try:
        return RANK_LADDER.index(rank)
    except ValueError:
        return 0

def rank_class(rank: str) -> str:
    """Písmeno třídy: 'F3' → 'F', 'S+' → 'S'."""
    return (rank or STARTING_RANK)[0].upper()

def points_needed(rank: str) -> int | None:
    """Kolik bodů je třeba na postup z tohoto ranku. None = maximum (S+)."""
    if rank_index(rank) >= len(RANK_LADDER) - 1:
        return None
    return RANK_COST.get(rank_class(rank), 5)

def next_rank(rank: str) -> str | None:
    i = rank_index(rank)
    return RANK_LADDER[i + 1] if i + 1 < len(RANK_LADDER) else None

def quest_points(difficulty: str | None) -> int:
    return DIFFICULTY.get(difficulty or DEFAULT_DIFFICULTY, {}).get("points", 0)


def get_rank(user_id: int) -> tuple[str, int]:
    """(rank, body v rámci ranku) aktivní postavy."""
    p = _profile(_load(), pkey(user_id))
    return p.get("rank", STARTING_RANK), int(p.get("rank_points", 0) or 0)


def add_rank_points(user_id: int, pts: int) -> dict:
    """Přičte body ranku aktivní postavě a případně povýší (i vícekrát naráz).

    Vrací: {'old_rank','new_rank','ranked_up','ranks_gained','points','needed'}
    """
    data = _load()
    uid  = pkey(user_id)
    p    = _profile(data, uid)

    rank   = p.get("rank", STARTING_RANK)
    points = int(p.get("rank_points", 0) or 0) + max(0, int(pts))
    old    = rank
    gained = 0

    # postup může přeskočit i víc ranků naráz (velké body / doplatek)
    while True:
        need = points_needed(rank)
        if need is None or points < need:
            break                       # maximum, nebo ještě nemá dost
        points -= need
        rank    = next_rank(rank)
        gained += 1

    if points_needed(rank) is None:
        points = 0                      # na S+ se body nesbírají

    p["rank"]        = rank
    p["rank_points"] = points
    _save(data)

    return {
        "old_rank":     old,
        "new_rank":     rank,
        "ranked_up":    gained > 0,
        "ranks_gained": gained,
        "points":       points,
        "needed":       points_needed(rank),
    }


def set_rank(user_id: int, rank: str) -> bool:
    """Natvrdo nastaví rank (admin). Body vynuluje."""
    if rank not in RANK_LADDER:
        return False
    data = _load()
    p    = _profile(data, pkey(user_id))
    p["rank"]        = rank
    p["rank_points"] = 0
    _save(data)
    return True


# ── Discord role ──────────────────────────────────────────────────────────────

def find_rank_role(guild: discord.Guild, rank: str) -> discord.Role | None:
    """Najde roli pro rank podle jména. Bot role NEVYTVÁŘÍ."""
    wanted = [pat.format(rank=rank).lower() for pat in ROLE_NAME_PATTERNS]
    for role in guild.roles:
        if role.name.lower() in wanted:
            return role
    return None

async def sync_rank_role(member: discord.Member, new_rank: str) -> tuple[bool, str]:
    """Dá hráči roli nového ranku a sundá role všech ostatních ranků.

    Vrací (uspěch, popis). Neúspěch NIKDY neshodí volajícího — jen se zaloguje.
    """
    guild = member.guild
    target = find_rank_role(guild, new_rank)
    if target is None:
        msg = f"Role pro rank **{new_rank}** na serveru neexistuje — vytvoř ji ručně."
        logger.warning(f"[ranks] chybí role pro rank {new_rank} (guild {guild.id})")
        return False, msg

    # všechny ostatní rank role, co hráč má
    others = []
    for r in RANK_LADDER:
        if r == new_rank:
            continue
        role = find_rank_role(guild, r)
        if role and role in member.roles:
            others.append(role)

    try:
        if others:
            await member.remove_roles(*others, reason="Změna ranku")
        if target not in member.roles:
            await member.add_roles(target, reason=f"Rank up → {new_rank}")
        return True, f"Role **{target.name}** přidělena."
    except discord.Forbidden:
        logger.warning(f"[ranks] chybí oprávnění na role (guild {guild.id})")
        return False, "Bot nemá právo spravovat role (nebo je role výš než bot)."
    except Exception:
        logger.exception("[ranks] sync_rank_role selhal")
        return False, "Přidělení role selhalo."


async def award_quest_rank(member: discord.Member, difficulty: str | None,
                           channel=None) -> dict | None:
    """Odmění hráče body ranku za splněný quest. Ohlásí rank up.

    Voláno z /quest status → dokončený. Chyba tu NESMÍ shodit uzavření questu.
    """
    try:
        pts = quest_points(difficulty)
        if pts <= 0:
            return None
        res = add_rank_points(member.id, pts)
        if not res["ranked_up"]:
            return res

        ok, role_msg = await sync_rank_role(member, res["new_rank"])

        embed = discord.Embed(
            title="🎖️  Povýšení dobrodruha!",
            description=(f"{member.mention} postoupil/a "
                         f"**{res['old_rank']} → {res['new_rank']}**"),
            color=0xFFD700,
        )
        need = res["needed"]
        embed.add_field(
            name="Postup",
            value=(f"{res['points']} / {need} bodů" if need else "**Maximální rank!**"),
            inline=True,
        )
        if not ok:
            embed.add_field(name="⚠️ Role", value=role_msg, inline=False)
        embed.set_footer(text=f"⭐ {ARION_NAME}")

        if channel:
            try:
                await channel.send(embed=embed)
            except Exception:
                logger.exception("[ranks] oznámení rank upu selhalo")
        try:
            await member.send(embed=embed)
        except discord.Forbidden:
            pass
        return res
    except Exception:
        logger.exception(f"[ranks] award_quest_rank selhal (user {member.id})")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class RanksCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    rank_group = app_commands.Group(name="rank", description="Rank dobrodruha")

    @rank_group.command(name="show", description="Zobrazí rank a postup.")
    @app_commands.describe(member="Hráč (výchozí: ty)")
    async def rank_show(self, interaction: discord.Interaction,
                        member: discord.Member | None = None):
        target = member or interaction.user
        rank, points = get_rank(target.id)
        need = points_needed(rank)
        idx  = rank_index(rank)

        if need is None:
            progress = "**Maximální rank** — výš už to nejde."
        else:
            filled = int(round(points / need * 10)) if need else 0
            bar = "█" * filled + "░" * (10 - filled)
            progress = f"`{bar}`  {points} / {need} bodů"

        embed = discord.Embed(
            title=f"🎖️  Rank — {target.display_name}",
            description=(f"### {rank}\n"
                         f"-# Stupeň {idx + 1} z {len(RANK_LADDER)}\n\n{progress}"),
            color=0xFFD700,
        )
        nxt = next_rank(rank)
        if nxt:
            embed.set_footer(text=f"Další: {nxt}  ·  ⭐ {ARION_NAME}")
        else:
            embed.set_footer(text=f"⭐ {ARION_NAME}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @rank_group.command(name="set", description="[Admin] Nastaví rank hráči.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hráč", rank="Nový rank")
    async def rank_set(self, interaction: discord.Interaction,
                       member: discord.Member, rank: str):
        await interaction.response.defer(ephemeral=True)
        if not set_rank(member.id, rank):
            await interaction.followup.send(f"❌ Rank `{rank}` neexistuje.", ephemeral=True)
            return
        ok, role_msg = await sync_rank_role(member, rank)
        log_action("rank_set", interaction.user.display_name, member.display_name, rank)
        msg = f"✅ {member.mention} má nyní rank **{rank}**."
        if not ok:
            msg += f"\n-# ⚠️ {role_msg}"
        await interaction.followup.send(msg, ephemeral=True)

    @rank_group.command(name="points", description="[Admin] Přidá body ranku hráči.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hráč", points="Kolik bodů přidat")
    async def rank_points(self, interaction: discord.Interaction,
                          member: discord.Member, points: int):
        await interaction.response.defer(ephemeral=True)
        res = add_rank_points(member.id, points)
        log_action("rank_points", interaction.user.display_name,
                   member.display_name, str(points))
        msg = f"✅ {member.mention} +{points} bodů ranku."
        if res["ranked_up"]:
            ok, role_msg = await sync_rank_role(member, res["new_rank"])
            msg += f"\n🎖️ Povýšení: **{res['old_rank']} → {res['new_rank']}**"
            if not ok:
                msg += f"\n-# ⚠️ {role_msg}"
        need = res["needed"]
        msg += f"\n-# Stav: {res['points']} / {need} bodů" if need else "\n-# Maximální rank."
        await interaction.followup.send(msg, ephemeral=True)

    @rank_group.command(name="roles-check",
                        description="[Admin] Zkontroluje, které rank role na serveru chybí.")
    @app_commands.checks.has_permissions(administrator=True)
    async def rank_roles_check(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        found, missing = [], []
        for r in RANK_LADDER:
            role = find_rank_role(interaction.guild, r)
            (found if role else missing).append(role.name if role else r)

        desc = f"**Nalezeno ({len(found)}/{len(RANK_LADDER)}):**\n"
        desc += ", ".join(f"`{r}`" for r in found) if found else "—"
        if missing:
            desc += f"\n\n**Chybí ({len(missing)}):**\n" + ", ".join(f"`{r}`" for r in missing)
            pats = ", ".join(f"`{p.format(rank='F3')}`" for p in ROLE_NAME_PATTERNS)
            desc += f"\n\n-# Bot role nevytváří. Pojmenuj je jedním z tvarů: {pats}"
        else:
            desc += "\n\n✅ Všechny rank role existují."

        embed = discord.Embed(title="🎖️  Kontrola rank rolí", description=desc, color=0xFFD700)
        await interaction.response.is_done() or None
        await interaction.followup.send(embed=embed, ephemeral=True)

    @rank_set.autocomplete("rank")
    async def rank_autocomplete(self, interaction: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=r, value=r)
            for r in RANK_LADDER
            if current.lower() in r.lower()
        ][:25]


async def setup(bot):
    await bot.add_cog(RanksCog(bot))