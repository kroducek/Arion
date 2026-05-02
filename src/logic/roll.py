import discord
from discord.ext import commands
from discord import app_commands
import random, re, io, os, json, logging, math, asyncio
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from src.core.dnd.roll_stats import record_roll
from src.utils.paths import PROFILES as DATA_FILE
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

# ── Paleta grafu ─────────────────────────────────────────────────────────────
BG_FIGURE = '#1a1b1e'
BG_POLAR  = '#111214'
C_GRID    = '#2e3035'
C_HERO    = '#f0a500'
C_CRIT    = '#ff2244'
C_OK      = '#00e87a'
C_FAIL    = '#ff4455'
C_CRIT_HIT = '#cc0033'
C_LABEL   = '#e0e0e0'


# ══════════════════════════════════════════════════════════════════════════════
# DATOVÁ VRSTVA
# ══════════════════════════════════════════════════════════════════════════════

def _load_profile(user_id: int) -> dict:
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get(str(user_id), {})
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
# VIZUALIZACE — radar chart (jen pro STAT_LABELS)
# ══════════════════════════════════════════════════════════════════════════════

def _radar_chart(stats: dict, roll_val: int, check_stats: list, dice_max: int = 20) -> io.BytesIO:
    matplotlib.use('Agg')

    n      = len(STAT_LABELS)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    ac     = angles + [angles[0]]

    eff = {s: float(stats.get(s, 0)) for s in STAT_LABELS}

    # Pevný scale = MAX_STAT (20) — hexagon i hod jsou vždy na stejné škále
    # Stat 15/20 = 75 % osy, hod 12/20 = 60 % osy — vizuálně srovnatelné
    scale = float(MAX_STAT)

    def n_(v: float) -> float:
        return min(v / scale, 1.0)

    # Průměrný threshold checkovaných statů
    check_stat_vals = [eff.get(cs, 0) for cs in check_stats if cs in STAT_LABELS]
    avg_stat  = sum(check_stat_vals) / max(len(check_stat_vals), 1)
    stat_ref  = float(max(1, math.ceil(avg_stat * dice_max / MAX_STAT)))
    # Threshold normalizovaný na stejnou škálu
    threshold_r = n_(avg_stat)   # = stat/MAX_STAT — odpovídá hexagonu

    # Úspěch = hod ≤ threshold
    is_success = roll_val <= stat_ref
    C_ROLL = C_OK if is_success else C_FAIL

    # ── Menší canvas — Discord řeší preview max ~400 px ───────────────────────
    fig = plt.figure(figsize=(4, 4), dpi=100)
    ax  = fig.add_subplot(111, polar=True)
    fig.patch.set_facecolor(BG_FIGURE)
    ax.set_facecolor(BG_POLAR)
    ax.set_ylim(0, 1.0)
    ax.set_yticks([])
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=C_GRID, linewidth=0.6, alpha=0.5)
    ax.spines['polar'].set_color(C_GRID)
    ax.spines['polar'].set_linewidth(0.6)

    # Mřížka — 4 prsteny (25 / 50 / 75 / 100 %)
    for r in [0.25, 0.5, 0.75, 1.0]:
        pts = [r] * n + [r]
        ax.plot(ac, pts, color=C_GRID,
                linewidth=1.0 if r == 1.0 else 0.5,
                alpha=0.9 if r == 1.0 else 0.35, zorder=1)

    # Threshold ring — plný kruh ve výšce průměrného statu checkovaných os
    if check_stat_vals:
        thresh_pts = [threshold_r] * n + [threshold_r]
        ax.plot(ac, thresh_pts, color='#aa77ff',
                linewidth=1.4, linestyle='--', alpha=0.75, zorder=2)

    # Hráčův hexagon
    hv = [n_(eff[s]) for s in STAT_LABELS] + [n_(eff[STAT_LABELS[0]])]
    ax.fill(ac, hv, color=C_HERO, alpha=0.15, zorder=3)
    ax.plot(ac, hv, color=C_HERO, linewidth=1.8, alpha=0.9, zorder=4)
    ax.scatter(angles, [n_(eff[s]) for s in STAT_LABELS],
               color=C_HERO, s=22, zorder=5, alpha=0.9, edgecolors='none')

    # Bod hodu — na ose první checkované statistiky, barva = výsledek
    first_cs = next((cs for cs in check_stats if cs in STAT_LABELS), None)
    theta_roll = angles[STAT_LABELS.index(first_cs)] if first_cs else angles[0]
    rv = n_(roll_val)
    ax.plot([theta_roll, theta_roll], [0, rv],
            color=C_ROLL, linewidth=2.0, alpha=0.85, zorder=6)
    # Záře
    ax.scatter([theta_roll], [rv], color=C_ROLL, s=160, zorder=7, alpha=0.10, edgecolors='none')
    ax.scatter([theta_roll], [rv], color=C_ROLL, s=70,  zorder=8, alpha=0.20, edgecolors='none')
    # Hlavní bod
    ax.scatter([theta_roll], [rv], color=C_ROLL, s=55, zorder=9,
               edgecolors=BG_FIGURE, linewidths=1.0)

    # Popisky — checkované staty v závorkách, ostatní normálně
    labels = []
    for s in STAT_LABELS:
        name = STAT_NAMES.get(s, s)
        val  = int(round(eff[s]))
        labels.append(f"[ {name} ]\n{val}" if s in check_stats else f"{name}\n{val}")

    ax.set_xticks(angles)
    ax.set_xticklabels(labels, color=C_LABEL, size=7.5, weight='bold')
    ax.set_yticklabels([])
    ax.tick_params(axis='x', pad=7)

    plt.tight_layout(pad=0.3)
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight',
                facecolor=fig.get_facecolor(), dpi=100)
    buf.seek(0)
    plt.close(fig)
    return buf

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

        record_roll(
            interaction.guild.id,
            interaction.user.id,
            nat20=is_nat_20,
            nat1=is_nat_1,
            hit24=(total_sum == 24),
            is_check=(check is not None),
        )

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

        # ── Check na staty z hexagramu → radar chart ──────────────────────────
        radar_attrs = [a for a in check_attrs if a in STAT_LABELS]
        if radar_attrs:
            stats      = profile.get("stats", {s: 0 for s in STAT_LABELS})
            chart_file = None
            try:
                loop       = asyncio.get_event_loop()
                buf        = await loop.run_in_executor(
                    None, _radar_chart, stats, total_sum, check_attrs, dm
                )
                chart_file = discord.File(buf, filename="check.png")
            except Exception:
                logging.exception("[roll/check] Graf selhal")

            # Zobraz hodnoty jednotlivých statů v patičce
            if len(check_attrs) == 2 and check_attrs[1] in STAT_LABELS:
                footer_stats = f"{attr_names[0]} {raw_vals[0]}  +  {attr_names[1]} {raw_vals[1]}  =  ∅ {stat_val}"
            else:
                footer_stats = f"{attr_name} {stat_val}"

            # nat1 / nat20 pro check embed
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
            embed.set_footer(text=f"{footer_stats}  ·  ✨ Aurionis ✨")
            if chart_file:
                embed.set_image(url="attachment://check.png")

            kwargs: dict = {"embed": embed}
            if chart_file:
                kwargs["file"] = chart_file
            await interaction.followup.send(**kwargs)

        # ── Check na HP / HUNGER → jednoduché srovnání bez grafu ─────────────
        else:
            stat_parts = []
            for a, v in zip(check_attrs, raw_vals):
                if a == "HP":
                    stat_parts.append(f"HP {v}/{profile.get('hp_max', 50)}")
                elif a == "HUNGER":
                    stat_parts.append(f"Hlad {v}/{profile.get('hunger_max', 10)}")
                else:
                    stat_parts.append(f"{STAT_NAMES.get(a, a)} {v}")
            stat_display = "  +  ".join(stat_parts)

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
            embed.set_footer(text=f"{stat_display}  ·  ✨ Aurionis ✨")
            await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Dice(bot))
