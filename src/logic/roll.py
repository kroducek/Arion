import discord
from discord.ext import commands
from discord import app_commands
import random, re, os, json, logging, math, asyncio

from src.core.dnd.roll_stats import record_roll
from src.utils.paths import PROFILES as DATA_FILE, PERKS as PERKS_FILE, PLAYER_PERKS as PLAYER_PERKS_FILE
from src.logic.stats import STAT_LABELS  # single source of truth

# ══════════════════════════════════════════════════════════════════════════════
# KONFIGURACE
# ══════════════════════════════════════════════════════════════════════════════
STAT_NAMES  = {
    'STR': 'Síla',
    'DEX': 'Obratnost',
    'INS': 'Instinkty',
    'INT': 'Inteligence',
    'CHA': 'Charisma',
    'WIS': 'Moudrost',
}

# Všechny checkable atributy kromě ATK a DEF
CHECK_ATTRS = STAT_LABELS + ['HP', 'HUNGER']

# Check: roll ≤ ceil(stat × dice_max / MAX_STAT) → úspěch
# top 20% rozsahu kostky = kritický neúspěch (pokud už ne úspěch)
MAX_STAT = 20


# ══════════════════════════════════════════════════════════════════════════════
# DATOVÁ VRSTVA
# ══════════════════════════════════════════════════════════════════════════════

from src.utils.json_utils import load_json

def _load_profile(user_id: int) -> dict:
    """Bezpečně načte profil hráče."""
    try:
        data = load_json(DATA_FILE, default={})
        return data.get(str(user_id), {})
    except Exception:
        return {}

def _get_stat_val(profile: dict, attr: str) -> int:
    if attr in STAT_LABELS:
        return profile.get("stats", {}).get(attr, 0)
    if attr == "HP":
        return profile.get("hp_cur", profile.get("hp_max", 50))
    if attr == "HUNGER":
        return profile.get("hunger_cur", profile.get("hunger_max", 10))
    return 0

# ══════════════════════════════════════════════════════════════════════════════
# PERKY — zobrazení pod výsledkem checku
# ══════════════════════════════════════════════════════════════════════════════

_PERK_EMOJI = {
    "Furioku": "👻", "Magie": "🔮", "Pasivky": "🛡️",
    "Temnota": "🌑", "Světlo": "☀️", "Základní": "📚",
    "Výzbroj": "⚔️", "Unikátní": "⭐",
}

def _get_roll_perks(user_id: int, stats: list[str]) -> list[dict]:
    """Vrátí hráčovy perky, které mají alespoň jeden ze statů v roll_tags."""
    try:
        all_perks = load_json(PERKS_FILE, default={})
        player_data = load_json(PLAYER_PERKS_FILE, default={})
    except Exception:
        return []
    
    owned_ids = player_data.get(str(user_id), {}).get("perks", [])
    seen: set[str] = set()
    result = []
    for pid in owned_ids:
        p = all_perks.get(pid)
        if p and pid not in seen and any(s in p.get("roll_tags", []) for s in stats):
            seen.add(pid)
            result.append(p)
    return result

# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class Dice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="roll", description="Epický hod kostkami (např. 1d20+2d4+5-2)")
    @app_commands.describe(
        hod="Zadej kombinaci, např. 1d20+2d4+5 nebo 2d10-2",
        check="Volitelný atribut check — porovná hod s tvou hodnotou statu",
        check2="Druhý atribut pro kombinovaný check (průměr obou statů)",
    )
    @app_commands.choices(check=[
        app_commands.Choice(name=a, value=a) for a in CHECK_ATTRS
    ])
    @app_commands.choices(check2=[
        app_commands.Choice(name=a, value=a) for a in CHECK_ATTRS
    ])
    async def roll(
        self,
        interaction: discord.Interaction,
        hod:    str,
        check:  app_commands.Choice[str] = None,
        check2: app_commands.Choice[str] = None,
    ):
        # ── Parsování kostek ──────────────────────────────────────────────────
        raw_input = hod.lower().replace(" ", "")
        if not raw_input:
            await interaction.response.send_message(
                "❌ Hvězdy nerozumí tvému zápisu. Zkus např. `1d20+5` ✧", ephemeral=True
            )
            return

        tokens = re.findall(r'([+-]?(?:\d+d\d+|\d+))', raw_input)
        if not tokens:
            tokens = re.findall(r'([+-]?(?:\d+d\d+|\d+))', "+" + raw_input)
        if not tokens:
            await interaction.response.send_message(
                "❌ Temná magie narušila tvůj hod. Zkontroluj formát! (Např. 1d20+2d6+4) ✧", ephemeral=True
            )
            return

        total_sum        = 0
        all_rolls_detail = []
        is_nat_20        = False
        is_nat_1         = False
        is_d20           = False
        dice_max         = 0   # největší kostka použitá v hodu (pro check scaling)

        try:
            for token in tokens:
                multiplier  = 1
                clean_token = token
                if token.startswith('+'):
                    clean_token = token[1:]
                elif token.startswith('-'):
                    multiplier  = -1
                    clean_token = token[1:]

                if 'd' in clean_token:
                    num_dice, sides = map(int, clean_token.split('d'))
                    if multiplier == 1:
                        dice_max = max(dice_max, sides)
                    if num_dice > 100 or sides > 1000:
                        raise ValueError("Příliš mnoho moci.")
                    current_rolls = [random.randint(1, sides) for _ in range(num_dice)]
                    if sides == 20 and num_dice == 1:
                        is_d20 = True
                        if current_rolls[0] == 20: is_nat_20 = True
                        if current_rolls[0] == 1:  is_nat_1  = True
                    total_sum += sum(current_rolls) * multiplier
                    all_rolls_detail.append(
                        f"{'+' if multiplier == 1 else '-'}{num_dice}d{sides}"
                        f"({', '.join(map(str, current_rolls))})"
                    )
                else:
                    val = int(clean_token)
                    total_sum += val * multiplier
                    all_rolls_detail.append(f"{'+' if multiplier == 1 else '-'}{val}")

        except Exception:
            await interaction.response.send_message(
                "❌ Temná magie narušila tvůj hod. Zkontroluj formát! (Např. 1d20+2d6+4) ✧", ephemeral=True
            )
            return

        roll_stats = record_roll(
            interaction.guild.id,
            interaction.user.id,
            nat20=is_nat_20,
            nat1=is_nat_1,
            hit24=(total_sum == 24),
            is_check=(check is not None),
            is_d20=is_d20,
        )
        try:
            from src.core.dnd.achievements import check_roll_achievements
            await check_roll_achievements(interaction.guild.id, interaction.user, interaction.channel, roll_stats)
        except Exception as _e:
            print(f"[roll] achievement check chyba: {_e}")

        details = "\n".join(all_rolls_detail)
        if len(details) > 1024:
            details = "Příliš mnoho kostek..."

        # ── Bez checku → normální embed ───────────────────────────────────────
        if check is None:
            color       = discord.Color.red()
            special_msg = ""
            if is_nat_20:
                color       = discord.Color.green()
                special_msg = "\n✨ **NATURAL 20!**"
            elif is_nat_1:
                color       = discord.Color.black()
                special_msg = "\n💀 **NATURAL 1!**"

            embed = discord.Embed(
                title="🎲",
                description=f"Vyvolený: {interaction.user.mention}{special_msg}",
                color=color,
            )
            embed.add_field(name="📜 Rozbor hodu", value=f"```diff\n{details}\n```", inline=False)
            embed.add_field(name="", value=f"# 🏆 **{total_sum}**", inline=False)
            embed.set_footer(text="✨ Aurionis ✨")
            await interaction.response.send_message(embed=embed)
            return

        # ── S checkem — musíme defer kvůli chartgeneration ───────────────────
        await interaction.response.defer()

        # Sestavíme seznam checkovaných atributů (1 nebo 2)
        check_attrs = [check.value]
        if check2 is not None and check2.value != check.value:
            check_attrs.append(check2.value)

        profile = _load_profile(interaction.user.id)
        if not profile:
            await interaction.followup.send(
                "❌ Nemáš registrovanou postavu. Použij `/onboard`.", ephemeral=True
            )
            return

        dm = dice_max if dice_max > 0 else 20

        # Kombinovaný název a hodnota statu
        attr_names = [STAT_NAMES.get(a, a) for a in check_attrs]
        attr_name  = " + ".join(attr_names)

        raw_vals  = [_get_stat_val(profile, a) for a in check_attrs]
        stat_val  = math.ceil(sum(raw_vals) / len(raw_vals))  # průměr, zaokrouhleno nahoru

        # Patička — HP/HUNGER ukazuje max, staty jen hodnotu
        foot_parts = []
        for a, v in zip(check_attrs, raw_vals):
            if a == "HP":
                foot_parts.append(f"HP {v}/{profile.get('hp_max', 50)}")
            elif a == "HUNGER":
                foot_parts.append(f"Hlad {v}/{profile.get('hunger_max', 10)}")
            else:
                foot_parts.append(f"{STAT_NAMES.get(a, a)} {v}")
        if len(check_attrs) == 2:
            foot_parts.append(f"∅ {stat_val}")
        footer_stats = "  +  ".join(foot_parts)

        check_color   = 0x00cc66 if is_nat_20 else (0x111111 if is_nat_1 else 0xf0a500)
        check_special = ""
        if is_nat_20:
            check_special = "\n✨ **NATURAL 20!**"
        elif is_nat_1:
            check_special = "\n💀 **NATURAL 1!**"

        embed = discord.Embed(
            title="🎲",
            description=f"Vyvolený: {interaction.user.mention}{check_special}",
            color=check_color,
        )
        embed.add_field(name="📜 Rozbor hodu", value=f"```diff\n{details}\n```", inline=False)
        embed.add_field(name="", value=f"# 🎲 **{total_sum}**", inline=False)

        stat_attrs = [a for a in check_attrs if a in STAT_LABELS]
        if stat_attrs:
            roll_perks = _get_roll_perks(interaction.user.id, stat_attrs)
            if roll_perks:
                lines = []
                for p in roll_perks:
                    emoji  = _PERK_EMOJI.get(p.get("group", ""), "✨")
                    bonus  = p.get("bonus", 0)
                    b_str  = f" **+{bonus}**" if bonus else ""
                    desc   = p.get("desc", "")
                    short  = desc[:75] + ("…" if len(desc) > 75 else "")
                    lines.append(f"{emoji} **{p['name']}**{b_str} — {short}")
                embed.add_field(name="✨ Perky", value="\n".join(lines), inline=False)

        embed.set_footer(text=f"{footer_stats}  ·  ✨ Aurionis ✨")
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Dice(bot))
