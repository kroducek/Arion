import discord
from discord.ext import commands

class VoiceControlView(discord.ui.View):
    def __init__(self, channel, owner):
        super().__init__(timeout=None)
        self.channel = channel
        self.owner = owner
        self.locked = False

    @discord.ui.button(label="Lock/Unlock", style=discord.ButtonStyle.secondary, emoji="🔒")
    async def lock_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.owner:
            return await interaction.response.send_message("You are not the owner of this galaxy!", ephemeral=True)

        self.locked = not self.locked
        overwrite = self.channel.overwrites_for(interaction.guild.default_role)
        overwrite.connect = not self.locked
        await self.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        
        status = "Locked 🔒" if self.locked else "Unlocked 🔓"
        await interaction.response.send_message(f"Channel is now **{status}**.", ephemeral=True)

    @discord.ui.button(label="Hide/Show", style=discord.ButtonStyle.secondary, emoji="👁️")
    async def hide_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.owner:
            return await interaction.response.send_message("You are not the owner of this galaxy!", ephemeral=True)

        overwrite = self.channel.overwrites_for(interaction.guild.default_role)
        current_view = overwrite.view_channel if overwrite.view_channel is not None else True
        overwrite.view_channel = not current_view
        await self.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        
        status = "Hidden 👻" if not overwrite.view_channel else "Visible 👀"
        await interaction.response.send_message(f"Channel is now **{status}**.", ephemeral=True)

    @discord.ui.button(label="Rename", style=discord.ButtonStyle.primary, emoji="📝")
    async def rename_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.owner:
            return await interaction.response.send_message("Only the architect can rename this place!", ephemeral=True)
        
        # Modal pro přejmenování
        modal = RenameModal(self.channel)
        await interaction.response.send_modal(modal)

class RenameModal(discord.ui.Modal, title="Rename your Galaxy"):
    name_input = discord.ui.TextInput(label="New Name", placeholder="Enter new channel name...", min_length=2, max_length=20)

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        await self.channel.edit(name=f"✨ {self.name_input.value}")
        await interaction.response.send_message(f"Channel renamed to **{self.name_input.value}**!", ephemeral=True)

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.hub_channel_id = 1473317631049072847 # <--- SEM VLOŽ ID SVÉHO JOIN-TO-CREATE KANÁLU
        self.temp_channels = {} # Dictionary {channel_id: owner_id}

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # 1. TVORBA KANÁLU
        if after.channel and after.channel.id == self.hub_channel_id:
            guild = member.guild
            category = after.channel.category
            
            new_channel = await guild.create_voice_channel(
                name=f"✨ {member.display_name}'s Galaxy",
                category=category
            )
            
            await member.move_to(new_channel)
            self.temp_channels[new_channel.id] = member.id

            # Poslání ovládacího panelu do textového chatu voice kanálu
            view = VoiceControlView(new_channel, member)
            embed = discord.Embed(
                title="Galaxy Control Panel",
                description=f"Welcome to your temporary star system, {member.mention}!\nUse the buttons below to manage your privacy.",
                color=discord.Color.purple()
            )
            await new_channel.send(embed=embed, view=view)

        # 2. MAZÁNÍ KANÁLU
        if before.channel and before.channel.id in self.temp_channels:
            if len(before.channel.members) == 0:
                await before.channel.delete(reason="Galaxy collapsed (empty)")
                del self.temp_channels[before.channel.id]

async def setup(bot):
    await bot.add_cog(Voice(bot))