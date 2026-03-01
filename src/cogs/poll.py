import discord
from discord.ext import commands
from discord import app_commands

class PollView(discord.ui.View):
    def __init__(self, question, options):
        super().__init__(timeout=None)  # Hlasování neskončí samo od sebe
        self.question = question
        self.options = options
        # Ukládáme hlasy: {index_volby: [id_uzivatelu]}
        self.votes = {i: [] for i in range(len(options))}

    async def update_embed(self, interaction):
        embed = discord.Embed(
            title=f"📊 Hlasování: {self.question}",
            description="Klikni na tlačítko níže a odevzdej svůj hlas",
            color=0x00ff00
        )
        
        total_votes = sum(len(v) for v in self.votes.values())
        
        for i, option in enumerate(self.options):
            count = len(self.votes[i])
            percent = (count / total_votes * 100) if total_votes > 0 else 0
            # Vizuální progress bar
            bar_length = 10
            filled = int(percent / 10)
            bar = "🟦" * filled + "⬜" * (bar_length - filled)
            
            embed.add_field(
                name=option,
                value=f"{bar} {count} hlasů ({percent:.0f}%)",
                inline=False
            )
        
        embed.set_footer(text=f"Celkem hlasovalo: {total_votes} | Arion Poll System")
        await interaction.message.edit(embed=embed, view=self)

    async def handle_vote(self, interaction: discord.Interaction, option_index: int):
        # Kontrola, jestli už uživatel hlasoval (pokud ano, smažeme starý hlas)
        user_id = interaction.user.id
        for v_list in self.votes.values():
            if user_id in v_list:
                v_list.remove(user_id)
        
        # Přidání nového hlasu
        self.votes[option_index].append(user_id)
        await interaction.response.send_message("Tvůj hlas byl zaznamenán!", ephemeral=True)
        await self.update_embed(interaction)

class Poll(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="poll", description="Vytvoří hlasování s tlačítky")
    @app_commands.describe(
        otazka="Na co se chceš zeptat?",
        volba1="První možnost",
        volba2="Druhá možnost",
        volba3="Třetí možnost (volitelné)",
        volba4="Čtvrtá možnost (volitelné)"
    )
    async def poll(self, interaction: discord.Interaction, otazka: str, volba1: str, volba2: str, volba3: str = None, volba4: str = None):
        options = [v for v in [volba1, volba2, volba3, volba4] if v is not None]
        
        if len(options) < 2:
            return await interaction.response.send_message("Musíš zadat aspoň dvě možnosti!", ephemeral=True)

        view = PollView(otazka, options)
        
        # Dynamické přidávání tlačítek podle počtu voleb
        for i, option in enumerate(options):
            btn = discord.ui.Button(label=option, custom_id=f"poll_{i}", style=discord.ButtonStyle.primary)
            
            # Definice funkce pro kliknutí (closure)
            async def create_callback(idx):
                async def callback(inter):
                    await view.handle_vote(inter, idx)
                return callback
            
            btn.callback = await create_callback(i)
            view.add_item(btn)

        embed = discord.Embed(
            title=f"📊 Hlasování: {otazka}",
            description="Klikni na tlačítko níže a odevzdej svůj hlas",
            color=0x00ff00
        )
        for opt in options:
            embed.add_field(name=opt, value="⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ 0 hlasů (0%)", inline=False)
            
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(Poll(bot))