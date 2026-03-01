import discord
from discord.ext import commands
from discord import app_commands
import random
import re

class Dice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="roll", description="Epický hod kostkami (např. 1d20+2d4+5-2)")
    @app_commands.describe(hod="Zadej kombinaci, např. 1d20+2d4+5 nebo 2d10-2")
    async def roll(self, interaction: discord.Interaction, hod: str):

        raw_input = hod.lower().replace(" ", "")

        if not raw_input:
            await interaction.response.send_message(
                "❌ Hvězdy nerozumí tvému zápisu. Zkus např. `1d20+5` ✧",
                ephemeral=True
            )
            return

        tokens = re.findall(r'([+-]?(?:\d+d\d+|\d+))', raw_input)

        if not tokens:
            tokens = re.findall(r'([+-]?(?:\d+d\d+|\d+))', "+" + raw_input)

        if not tokens:
            await interaction.response.send_message(
                "❌ Hvězdy nerozumí tvému zápisu. Zkus např. `1d20+5` ✧",
                ephemeral=True
            )
            return

        total_sum = 0
        all_rolls_detail = []
        is_nat_20 = False
        is_nat_1 = False

        try:
            for token in tokens:

                multiplier = 1
                clean_token = token

                if token.startswith('+'):
                    clean_token = token[1:]
                elif token.startswith('-'):
                    multiplier = -1
                    clean_token = token[1:]

                if 'd' in clean_token:
                    num_dice, sides = map(int, clean_token.split('d'))

                    if num_dice > 100 or sides > 1000:
                        raise ValueError("Příliš mnoho moci.")

                    current_rolls = [random.randint(1, sides) for _ in range(num_dice)]

                    if sides == 20 and num_dice == 1:
                        if current_rolls[0] == 20:
                            is_nat_20 = True
                        if current_rolls[0] == 1:
                            is_nat_1 = True

                    total_sum += sum(current_rolls) * multiplier
                    all_rolls_detail.append(
                        f"{'+' if multiplier == 1 else '-'}{num_dice}d{sides}({', '.join(map(str, current_rolls))})"
                    )
                else:
                    val = int(clean_token)
                    total_sum += val * multiplier
                    all_rolls_detail.append(
                        f"{'+' if multiplier == 1 else '-'}{val}"
                    )

        except Exception:
            await interaction.response.send_message(
                "❌ Temná magie narušila tvůj hod. Zkontroluj formát! (Např. 1d20+2d6+4) ✧",
                ephemeral=True
            )
            return

        # === DESIGN ===

        color = discord.Color.red()
        special_msg = ""

        if is_nat_20:
            color = discord.Color.green()
            special_msg = "\n✨ **NATURAL 20!**"
        elif is_nat_1:
            color = discord.Color.black()
            special_msg = "\n💀 **NATURAL 1!**"

        embed = discord.Embed(
            title="🎲",
            description=f"Vyvolený: {interaction.user.mention}{special_msg}",
            color=color
        )

        details = "\n".join(all_rolls_detail)
        if len(details) > 1024:
            details = "Příliš mnoho kostek..."

        embed.add_field(
            name="📜 Rozbor hodu",
            value=f"```diff\n{details}\n```",
            inline=False
        )

        # Zvýrazněný výsledek (největší možné Markdown zvětšení v embedu)
        embed.add_field(
            name="",
            value=f"# 🏆 **{total_sum}**",
            inline=False
        )

        embed.set_footer(text="✨ Aurionis ✨")

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Dice(bot))
