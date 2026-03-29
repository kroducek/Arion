import discord
from discord.ext import commands
from discord import app_commands

from src.utils.paths import REPUTATION as DATA_FILE
from src.utils.json_utils import load_json, save_json

DM_ROLE_NAME = "DM"

# ══════════════════════════════════════════════════════════════════════════════
# DATA
# Formát:
# {
#   "guild_id": {
#     "factions": ["Lumenie", "Temný řád"],
#     "players": {
#       "user_id": { "Lumenie": 10, "Temný řád": -5 }
#     }
#   }
# }
# ══════════════════════════════════════════════════════════════════════════════

def _load() -> dict:
    return load_json(DATA_FILE)

def _save(data: dict):
    save_json(DATA_FILE, data)

def _guild(data: dict, guild_id: int) -> dict:
    gid = str(guild_id)
    data.setdefault(gid, {"factions": [], "players": {}})
    return data[gid]

def _is_dm(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    return any(r.name == DM_ROLE_NAME for r in interaction.user.roles)

# ══════════════════════════════════════════════════════════════════════════════
# AUTOCOMPLETE
# ══════════════════════════════════════════════════════════════════════════════

async def _faction_autocomplete(interaction: discord.Interaction, current: str):
    data    = _load()
    guild   = _guild(data, interaction.guild.id)
    options = [f for f in guild["factions"] if current.lower() in f.lower()]
    return [app_commands.Choice(name=f, value=f) for f in options[:25]]

# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class ReputationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    rep = app_commands.Group(name="rep", description="Systém reputace frakcí")

    # ── /rep create ──────────────────────────────────────────────────────────
    @rep.command(name="create", description="[DM] Vytvoří novou frakci reputace")
    @app_commands.describe(nazev="Název frakce (např. Lumenie)")
    async def rep_create(self, interaction: discord.Interaction, nazev: str):
        if not _is_dm(interaction):
            await interaction.response.send_message("❌ Jen DM.", ephemeral=True)
            return
        data  = _load()
        guild = _guild(data, interaction.guild.id)
        if nazev in guild["factions"]:
            await interaction.response.send_message(f"❌ Frakce **{nazev}** už existuje.", ephemeral=True)
            return
        guild["factions"].append(nazev)
        _save(data)
        await interaction.response.send_message(
            f"✅ Frakce **{nazev}** byla vytvořena.", ephemeral=True
        )

    # ── /rep delete ──────────────────────────────────────────────────────────
    @rep.command(name="delete", description="[DM] Smaže frakci i veškerou reputaci hráčů v ní")
    @app_commands.describe(frakce="Frakce k smazání")
    @app_commands.autocomplete(frakce=_faction_autocomplete)
    async def rep_delete(self, interaction: discord.Interaction, frakce: str):
        if not _is_dm(interaction):
            await interaction.response.send_message("❌ Jen DM.", ephemeral=True)
            return
        data  = _load()
        guild = _guild(data, interaction.guild.id)
        if frakce not in guild["factions"]:
            await interaction.response.send_message(f"❌ Frakce **{frakce}** neexistuje.", ephemeral=True)
            return
        guild["factions"].remove(frakce)
        for uid in guild["players"]:
            guild["players"][uid].pop(frakce, None)
        _save(data)
        await interaction.response.send_message(
            f"🗑️ Frakce **{frakce}** byla smazána.", ephemeral=True
        )

    # ── /rep add ─────────────────────────────────────────────────────────────
    @rep.command(name="add", description="[DM] Přidá hráči reputaci ve frakci")
    @app_commands.describe(
        hrac="Hráč",
        frakce="Frakce",
        hodnota="Počet bodů (záporné číslo = odebere)",
    )
    @app_commands.autocomplete(frakce=_faction_autocomplete)
    async def rep_add(
        self,
        interaction: discord.Interaction,
        hrac: discord.Member,
        frakce: str,
        hodnota: int,
    ):
        if not _is_dm(interaction):
            await interaction.response.send_message("❌ Jen DM.", ephemeral=True)
            return
        data  = _load()
        guild = _guild(data, interaction.guild.id)
        if frakce not in guild["factions"]:
            await interaction.response.send_message(
                f"❌ Frakce **{frakce}** neexistuje. Vytvoř ji přes `/rep create`.", ephemeral=True
            )
            return
        uid = str(hrac.id)
        guild["players"].setdefault(uid, {})
        guild["players"][uid].setdefault(frakce, 0)
        old = guild["players"][uid][frakce]
        guild["players"][uid][frakce] += hodnota
        new = guild["players"][uid][frakce]
        _save(data)

        sign = "+" if hodnota >= 0 else ""
        arrow = "📈" if hodnota >= 0 else "📉"
        await interaction.response.send_message(
            f"{arrow} **{hrac.display_name}** — **{frakce}**: `{old}` → `{new}` ({sign}{hodnota})",
            ephemeral=True,
        )

    # ── /rep set ─────────────────────────────────────────────────────────────
    @rep.command(name="set", description="[DM] Nastaví hráči reputaci ve frakci na přesnou hodnotu")
    @app_commands.describe(hrac="Hráč", frakce="Frakce", hodnota="Nová hodnota")
    @app_commands.autocomplete(frakce=_faction_autocomplete)
    async def rep_set(
        self,
        interaction: discord.Interaction,
        hrac: discord.Member,
        frakce: str,
        hodnota: int,
    ):
        if not _is_dm(interaction):
            await interaction.response.send_message("❌ Jen DM.", ephemeral=True)
            return
        data  = _load()
        guild = _guild(data, interaction.guild.id)
        if frakce not in guild["factions"]:
            await interaction.response.send_message(
                f"❌ Frakce **{frakce}** neexistuje.", ephemeral=True
            )
            return
        uid = str(hrac.id)
        guild["players"].setdefault(uid, {})
        guild["players"][uid][frakce] = hodnota
        _save(data)
        await interaction.response.send_message(
            f"✏️ **{hrac.display_name}** — **{frakce}** nastaven na `{hodnota}`.",
            ephemeral=True,
        )

    # ── /rep show ────────────────────────────────────────────────────────────
    @rep.command(name="show", description="Zobrazí reputaci hráče u všech frakcí")
    @app_commands.describe(hrac="Hráč (výchozí: ty)")
    async def rep_show(self, interaction: discord.Interaction, hrac: discord.Member | None = None):
        target = hrac or interaction.user
        # Cizí profil → jen DM
        if target.id != interaction.user.id and not _is_dm(interaction):
            await interaction.response.send_message("❌ Jen DM může zobrazit cizí reputaci.", ephemeral=True)
            return

        data  = _load()
        guild = _guild(data, interaction.guild.id)
        uid   = str(target.id)
        reps  = guild["players"].get(uid, {})

        if not guild["factions"]:
            await interaction.response.send_message("❌ Žádné frakce zatím neexistují.", ephemeral=True)
            return

        lines = []
        for f in guild["factions"]:
            val = reps.get(f, 0)
            bar = _rep_bar(val)
            lines.append(f"**{f}**\n{bar}  `{val:+d}`")

        embed = discord.Embed(
            title=f"📜 Reputace — {target.display_name}",
            description="\n\n".join(lines) if lines else "*Žádná reputace.*",
            color=0xf0a500,
        )
        embed.set_footer(text="✨ Aurionis ✨")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /rep list ────────────────────────────────────────────────────────────
    @rep.command(name="list", description="[DM] Zobrazí všechny hráče a jejich reputaci u frakce")
    @app_commands.describe(frakce="Frakce")
    @app_commands.autocomplete(frakce=_faction_autocomplete)
    async def rep_list(self, interaction: discord.Interaction, frakce: str):
        if not _is_dm(interaction):
            await interaction.response.send_message("❌ Jen DM.", ephemeral=True)
            return
        data  = _load()
        guild = _guild(data, interaction.guild.id)
        if frakce not in guild["factions"]:
            await interaction.response.send_message(f"❌ Frakce **{frakce}** neexistuje.", ephemeral=True)
            return

        rows = []
        for uid, reps in guild["players"].items():
            val = reps.get(frakce, 0)
            if val == 0:
                continue
            member = interaction.guild.get_member(int(uid))
            name   = member.display_name if member else f"<{uid}>"
            rows.append((val, name))

        rows.sort(reverse=True)
        if not rows:
            desc = "*Žádný hráč nemá reputaci v této frakci.*"
        else:
            desc = "\n".join(f"`{v:+4d}`  {n}" for v, n in rows)

        embed = discord.Embed(
            title=f"📜 Reputace — {frakce}",
            description=desc,
            color=0xf0a500,
        )
        embed.set_footer(text="✨ Aurionis ✨")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _rep_bar(val: int, width: int = 10) -> str:
    """Vizuální pruh reputace od -100 do +100."""
    clamped = max(-100, min(100, val))
    center  = width // 2
    filled  = round(abs(clamped) / 100 * center)
    if clamped >= 0:
        bar = "░" * center + "█" * filled + "░" * (center - filled)
    else:
        bar = "░" * (center - filled) + "█" * filled + "░" * center
    return f"`{bar}`"


async def setup(bot):
    await bot.add_cog(ReputationCog(bot))
