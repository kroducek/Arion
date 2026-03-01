import discord
from discord.ext import commands
import io
import random
import matplotlib
import numpy as np

class Check(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="check", description="Provede Alignment Check postavy.")
    async def check(self, ctx: commands.Context):
        await ctx.defer()

        try:
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt

            # 1. DEFINICE ATRIBUTŮ (LUCK odstraněn z grafu)
            labels = ['STR', 'DEX', 'INS', 'INT', 'CHA', 'WIS']
            n_attr = len(labels)

            # 2. SKRYTÝ STAT ŠTĚSTÍ (LUCK) - ovlivňuje výkon hrdiny
            # Rozsah 1-10, kde 5 je průměr.
            luck_stat = random.randint(1, 10)
            # Modifikátor štěstí (přepočet na bonus/postih k atributům)
            luck_mod = (luck_stat - 5) // 2 

            # 3. ZÁKLADNÍ STATY (Budoucí napojení na DB)
            base_stats = [random.randint(3, 9) for _ in range(n_attr)]
            
            # Aplikace štěstí na staty postavy (postava podává výkon podle svého štěstí)
            stats_hero = [max(1, s + luck_mod) for s in base_stats]
            
            # 4. NÁROČNOST ÚKOLU / MISE
            stats_task = [random.randint(4, 10) for _ in range(n_attr)]
            
            # Výpočet synchronizace (%)
            covered = sum(min(h, t) for h, t in zip(stats_hero, stats_task))
            total = sum(stats_task)
            alignment = (covered / total) * 100

            # --- PŘÍPRAVA RADARU ---
            angles = np.linspace(0, 2 * np.pi, n_attr, endpoint=False).tolist()
            angles += angles[:1] # Uzavření kruhu
            
            plot_hero = stats_hero + [stats_hero[0]]
            plot_task = stats_task + [stats_task[0]]

            # Dynamická barva podle úspěchu
            if alignment > 85: color_theme = '#00ff88'   # Excelentní
            elif alignment > 50: color_theme = '#ff8c00' # Standard
            else: color_theme = '#ff3333'               # Slabá synchronizace

            plt.style.use('dark_background')
            fig = plt.figure(figsize=(6, 6))
            ax = fig.add_subplot(111, polar=True)
            fig.patch.set_facecolor('#2b2d31')
            ax.set_facecolor('#1e1f22')

            # Vykreslení zón
            ax.fill(angles, plot_task, color='white', alpha=0.1, label="Challenge")
            ax.plot(angles, plot_task, color='white', linewidth=1, alpha=0.3)
            ax.fill(angles, plot_hero, color=color_theme, alpha=0.4, label="Hero")
            ax.plot(angles, plot_hero, color=color_theme, linewidth=2)

            # Nastavení vzhledu
            ax.set_xticks(angles[:-1])
            ax.set_xticklabels(labels, color='white', size=11, weight='bold')
            ax.set_yticklabels([])
            ax.grid(color='#404249', linestyle='--')

            # Konverze do souboru
            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor())
            buf.seek(0)
            plt.close(fig)

            # --- EMBED ---
            file = discord.File(buf, filename="check.png")
            embed = discord.Embed(
                title="📡 CHARACTER ALIGNMENT SCAN",
                description=f"Celková úroveň synchronizace: **{alignment:.1f}%**",
                color=int(color_theme.replace('#', '0x'), 16)
            )

            # Slovní vyjádření Štěstí místo Fate Rollu
            if luck_stat >= 9: luck_desc = "🌟 Výjimečná konjunkce (Štěstěna září)"
            elif luck_stat >= 7: luck_desc = "📈 Příznivé okolnosti"
            elif luck_stat >= 4: luck_desc = "⚖️ Stabilní vliv (Neutrální)"
            elif luck_stat >= 2: luck_desc = "📉 Nepříznivé interference"
            else: luck_desc = "💀 Kritická nesouhra (Naprostá smůla)"

            embed.add_field(name="Aktuální vliv Štěstí (LUCK)", value=luck_desc, inline=False)
            embed.set_image(url="attachment://check.png")
            embed.set_footer(text=f"Sken dokončen • ID: {ctx.author.id}")

            if ctx.interaction:
                await ctx.interaction.followup.send(embed=embed, file=file)
            else:
                await ctx.send(embed=embed, file=file)

        except Exception as e:
            print(f"Error v checku: {e}")
            if ctx.interaction: await ctx.interaction.followup.send("Skenování selhalo.")

async def setup(bot):
    await bot.add_cog(Check(bot))