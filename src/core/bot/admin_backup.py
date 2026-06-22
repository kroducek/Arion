"""
DOČASNÉ — /backup_data : zazipuje celý DATA_DIR a pošle ho adminovi do DM.

Umístění:  src/core/bot/admin_backup.py
Aktivace:  přidej řádek  "src.core.bot.admin_backup",  do seznamu BOT_COGS v main_bot.py
Po migraci: smaž tento soubor a odeber ten řádek ze seznamu.

Pozn.: zip jde do DM (ne do kanálu), protože obsahuje data všech hráčů.
"""
import io
import os
import time
import zipfile

import discord
from discord import app_commands
from discord.ext import commands

from src.utils.paths import DATA_DIR

# Limit přílohy pro ne-boostnuté servery je ~25 MB, necháme rezervu.
_MAX_BYTES = 24 * 1024 * 1024


class AdminBackupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="backup_data",
        description="[DOČASNÉ] Zazipuje všechna data a pošle ti je do DM",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def backup_data(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not os.path.isdir(DATA_DIR):
            await interaction.followup.send(
                f"❌ DATA_DIR neexistuje: `{DATA_DIR}`", ephemeral=True
            )
            return

        # Zazipovat všechny soubory v DATA_DIR do paměti
        buf = io.BytesIO()
        count = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(DATA_DIR):
                for fn in files:
                    full = os.path.join(root, fn)
                    arc = os.path.relpath(full, DATA_DIR)
                    try:
                        zf.write(full, arc)
                        count += 1
                    except Exception:
                        pass

        data = buf.getvalue()
        size = len(data)

        if count == 0:
            await interaction.followup.send(
                "❌ V DATA_DIR nejsou žádné soubory k zálohování.", ephemeral=True
            )
            return

        if size > _MAX_BYTES:
            mb = size / 1024 / 1024
            await interaction.followup.send(
                f"⚠️ Záloha má **{mb:.1f} MB** a přesahuje limit přílohy (~25 MB).\n"
                f"Použij `railway volume browse` přes CLI, nebo si vyžádej zvětšení limitu.",
                ephemeral=True,
            )
            return

        stamp = time.strftime("%Y%m%d_%H%M%S")
        fname = f"arion_backup_{stamp}.zip"
        kb = size / 1024

        # Primárně do DM (soukromě). Fallback: ephemerálně sem.
        try:
            await interaction.user.send(
                content=(
                    f"💾 **Arion záloha** — {count} souborů, {kb:.0f} KB  ·  `{stamp}`\n"
                    f"-# Ulož si přílohu na bezpečné místo. Obsahuje všechna data serveru."
                ),
                file=discord.File(io.BytesIO(data), filename=fname),
            )
            await interaction.followup.send(
                f"💾 Záloha hotová — **{count}** souborů (**{kb:.0f} KB**). "
                f"Poslal jsem ti ji do DM. 📩",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                content=(
                    f"💾 Záloha hotová (**{count}** souborů, **{kb:.0f} KB**), "
                    f"ale máš zavřené DM — posílám sem ephemerálně, **hned si ji stáhni**:"
                ),
                file=discord.File(io.BytesIO(data), filename=fname),
                ephemeral=True,
            )


async def setup(bot):
    await bot.add_cog(AdminBackupCog(bot))