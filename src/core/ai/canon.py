"""Návrh kánonu se zapisuje až po potvrzení vypravěčem."""
import discord

from src.database import db


class CanonForm(discord.ui.Modal, title="Schválit zápis do lore"):
    body = discord.ui.TextInput(label="Text zápisu", style=discord.TextStyle.paragraph, max_length=1800)
    kind = discord.ui.TextInput(label="Druh: fakt / výrok / teorie", default="fakt", max_length=10)
    audience = discord.ui.TextInput(label="Viditelnost: tajné / veřejné", default="tajné", max_length=12)

    def __init__(self, draft):
        super().__init__()
        self.draft = draft
        self.body.default = draft.text[:1800]

    async def on_submit(self, interaction):
        draft = self.draft
        if not await draft.interaction_check(interaction):
            return
        kind = self.kind.value.strip().lower()
        visibility = self.audience.value.strip().lower()
        body = self.body.value.strip()
        if not body or kind not in ("fakt", "výrok", "teorie") or visibility not in ("veřejné", "tajné"):
            return await interaction.response.send_message("Oprav text, druh nebo viditelnost a otevři návrh znovu.", ephemeral=True)
        entry = dict(text=body, druh=kind, public=visibility == "veřejné",
                     sources=draft.sources, dm=interaction.user.id, channel=draft.channel)
        def approve(entries):
            entries.setdefault(str(draft.draft_id), entry)

        db.update_doc(f"arion_canon:{interaction.guild_id}", approve)
        draft.stop()
        await interaction.response.send_message("Zápis byl schválen a uložen.", ephemeral=True)


class CanonDraft(discord.ui.View):
    def __init__(self, cog, interaction, channel, text, sources):
        super().__init__(timeout=900)
        self.cog = cog
        self.owner = interaction.user.id
        self.guild = interaction.guild_id
        self.channel = channel
        self.draft_id = interaction.id
        self.text = text
        self.sources = sources

    async def interaction_check(self, interaction):
        if interaction.guild_id != self.guild or interaction.user.id != self.owner or self.is_finished():
            await interaction.response.send_message("Tento návrh už nelze upravit.", ephemeral=True)
            return False
        return await self.cog.interaction_check(interaction)

    @discord.ui.button(label="Upravit a schválit", style=discord.ButtonStyle.primary)
    async def approve(self, interaction, button):
        await interaction.response.send_modal(CanonForm(self))
