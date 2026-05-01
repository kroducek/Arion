import discord
import logging
from discord.ext import commands
from discord import app_commands
from typing import Optional

from src.utils.paths import RP_ROOMS as DATA_FILE
from src.utils.json_utils import load_json, save_json

# ══════════════════════════════════════════════════════════════════════════════
# KONFIGURACE — vyplň ID kategorií dle svého serveru
# ══════════════════════════════════════════════════════════════════════════════

RP_CATEGORY_ID      = 1473317631049072844
ARCHIVE_CATEGORY_ID = 1484549162203746566

ROOM_EMOJI = "📜"  # prefix názvu kanálu

DM_ROLE_NAME = "DM"

# ══════════════════════════════════════════════════════════════════════════════
# DATA
# ══════════════════════════════════════════════════════════════════════════════

def _load() -> dict:
    return load_json(DATA_FILE)

def _save(data: dict):
    save_json(DATA_FILE, data)

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _is_dm(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    return any(r.name == DM_ROLE_NAME for r in interaction.user.roles)

def _is_creator_or_dm(interaction: discord.Interaction, room: dict) -> bool:
    return interaction.user.id == room["creator_id"] or _is_dm(interaction)

def _room_by_channel(data: dict, channel_id: int) -> tuple[Optional[str], Optional[dict]]:
    for heslo, room in data.items():
        if room.get("channel_id") == channel_id:
            return heslo, room
    return None, None

def _sanitize_name(name: str) -> str:
    return name.lower().strip().replace(" ", "-")[:50]

# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class RPManage(commands.Cog):

    rp = app_commands.Group(name="rp", description="Správa RP místností")

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    # ── /rp create ────────────────────────────────────────────────────────────

    @rp.command(name="create", description="Vytvoří soukromou RP místnost s heslem.")
    @app_commands.describe(
        name="Název místnosti (např. temny-les)",
        heslo="Heslo pro vstup — sdílej jen s hráči",
    )
    async def rp_create(self, interaction: discord.Interaction, name: str, heslo: str):
        await interaction.response.defer(ephemeral=True)

        heslo_key    = heslo.lower().strip()
        channel_name = f"{ROOM_EMOJI}｜{_sanitize_name(name)}"
        data         = _load()

        if heslo_key in data:
            await interaction.followup.send("❌ Toto heslo již používá jiná místnost.", ephemeral=True)
            return

        guild    = interaction.guild
        category = guild.get_channel(RP_CATEGORY_ID)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user:   discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }

        # Přidej bota samotného aby mohl spravovat kanál
        bot_member = guild.get_member(self.bot.user.id)
        if bot_member:
            overwrites[bot_member] = discord.PermissionOverwrite(
                view_channel=True, manage_channels=True, manage_permissions=True
            )

        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"RP místnost · soukromá",
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot nemá oprávnění vytvořit kanál.", ephemeral=True)
            return

        data[heslo_key] = {
            "channel_id": channel.id,
            "name":       channel_name,
            "creator_id": interaction.user.id,
            "members":    [interaction.user.id],
            "muted":      False,
        }
        _save(data)

        await interaction.followup.send(
            f"✅ Místnost {channel.mention} vytvořena.\n"
            f"-# Heslo: `{heslo_key}` — sdílej jen s hráči, kteří mají vstoupit.",
            ephemeral=True,
        )

    # ── /rp join ──────────────────────────────────────────────────────────────

    @rp.command(name="join", description="Vstupte do RP místnosti pomocí hesla.")
    @app_commands.describe(heslo="Heslo místnosti")
    async def rp_join(self, interaction: discord.Interaction, heslo: str):
        await interaction.response.defer(ephemeral=True)

        heslo_key = heslo.lower().strip()
        data      = _load()
        room      = data.get(heslo_key)

        if not room:
            await interaction.followup.send("❌ Nesprávné heslo nebo místnost neexistuje.", ephemeral=True)
            return

        uid = interaction.user.id
        if uid in room["members"]:
            channel = interaction.guild.get_channel(room["channel_id"])
            mention = channel.mention if channel else f"#{room['name']}"
            await interaction.followup.send(f"Jsi už v místnosti {mention}.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(room["channel_id"])
        if not channel:
            await interaction.followup.send("❌ Kanál místnosti nebyl nalezen — pravděpodobně smazán.", ephemeral=True)
            return

        # Pokud byl uživatel divák, upgraduj ho na plného člena
        was_spectator = uid in room.get("spectators", [])

        try:
            await channel.set_permissions(
                interaction.user,
                view_channel=True,
                send_messages=not room.get("muted", False),
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot nemá oprávnění upravit kanál.", ephemeral=True)
            return

        room["members"].append(uid)
        if was_spectator:
            room["spectators"].remove(uid)
        _save(data)

        msg = f"✅ Vstoupil/a jsi do místnosti {channel.mention}."
        if was_spectator:
            msg += " (upgraded z diváka na člena)"
        await interaction.followup.send(msg, ephemeral=True)

    # ── /rp kick ──────────────────────────────────────────────────────────────

    @rp.command(name="kick", description="[Tvůrce/DM] Vyhodí hráče nebo diváka z RP místnosti.")
    @app_commands.describe(member="Hráč nebo divák k vyhození")
    async def rp_kick(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        data        = _load()
        heslo, room = _room_by_channel(data, interaction.channel_id)

        if not room:
            await interaction.followup.send("❌ Tento kanál není RP místností.", ephemeral=True)
            return

        if not _is_creator_or_dm(interaction, room):
            await interaction.followup.send("❌ Jen tvůrce místnosti nebo DM může vyhazovat.", ephemeral=True)
            return

        if member.id == room["creator_id"]:
            await interaction.followup.send("❌ Nelze vyhostit tvůrce místnosti.", ephemeral=True)
            return

        is_member    = member.id in room["members"]
        is_spectator = member.id in room.get("spectators", [])

        if not is_member and not is_spectator:
            await interaction.followup.send(f"❌ **{member.display_name}** není v této místnosti.", ephemeral=True)
            return

        try:
            await interaction.channel.set_permissions(member, overwrite=None)
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot nemá oprávnění upravit kanál.", ephemeral=True)
            return

        if is_member:
            room["members"].remove(member.id)
        if is_spectator:
            room["spectators"].remove(member.id)
        _save(data)

        await interaction.followup.send(
            f"✅ **{member.display_name}** byl/a odstraněn/a z místnosti.", ephemeral=True
        )

    # ── /rp spectate ──────────────────────────────────────────────────────────

    @rp.command(name="spectate", description="Pozve hráče jako diváka — může sledovat a reagovat, ale ne psát.")
    @app_commands.describe(member="Hráč, který bude sledovat jako divák")
    async def rp_spectate(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        data        = _load()
        heslo, room = _room_by_channel(data, interaction.channel_id)

        if not room:
            await interaction.followup.send("❌ Tento kanál není RP místností.", ephemeral=True)
            return

        if interaction.user.id not in room["members"]:
            await interaction.followup.send("❌ Jen členové místnosti mohou zvát diváky.", ephemeral=True)
            return

        uid = member.id

        if uid in room["members"]:
            await interaction.followup.send(
                f"❌ **{member.display_name}** je již plnohodnotným členem místnosti.", ephemeral=True
            )
            return

        spectators = room.setdefault("spectators", [])

        if uid in spectators:
            await interaction.followup.send(f"❌ **{member.display_name}** je již divák.", ephemeral=True)
            return

        try:
            await interaction.channel.set_permissions(
                member,
                view_channel=True,
                send_messages=False,
                add_reactions=True,
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot nemá oprávnění upravit kanál.", ephemeral=True)
            return

        spectators.append(uid)
        _save(data)

        await interaction.followup.send(
            f"👁️ **{member.display_name}** byl/a přidán/a jako divák — může sledovat a reagovat, ale ne psát.",
            ephemeral=True,
        )
        await interaction.channel.send(
            f"👁️ {member.mention} byl/a přizván/a jako divák kampaně."
        )

    # ── /rp unspectate ────────────────────────────────────────────────────────

    @rp.command(name="unspectate", description="[Tvůrce/DM] Odebere diváka z místnosti.")
    @app_commands.describe(member="Divák k odebrání")
    async def rp_unspectate(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        data        = _load()
        heslo, room = _room_by_channel(data, interaction.channel_id)

        if not room:
            await interaction.followup.send("❌ Tento kanál není RP místností.", ephemeral=True)
            return

        if not _is_creator_or_dm(interaction, room):
            await interaction.followup.send("❌ Jen tvůrce místnosti nebo DM může odebírat diváky.", ephemeral=True)
            return

        if member.id not in room.get("spectators", []):
            await interaction.followup.send(f"❌ **{member.display_name}** není divák.", ephemeral=True)
            return

        try:
            await interaction.channel.set_permissions(member, overwrite=None)
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot nemá oprávnění upravit kanál.", ephemeral=True)
            return

        room["spectators"].remove(member.id)
        _save(data)

        await interaction.followup.send(
            f"✅ **{member.display_name}** byl/a odebrán/a z diváků.", ephemeral=True
        )

    # ── /rp mute ──────────────────────────────────────────────────────────────

    @rp.command(name="mute", description="[Tvůrce/DM] Ztichne nebo odtichne všechny v místnosti.")
    async def rp_mute(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        data        = _load()
        heslo, room = _room_by_channel(data, interaction.channel_id)

        if not room:
            await interaction.followup.send("❌ Tento kanál není RP místností.", ephemeral=True)
            return

        if not _is_creator_or_dm(interaction, room):
            await interaction.followup.send("❌ Jen tvůrce místnosti nebo DM může mutovat.", ephemeral=True)
            return

        muting  = not room.get("muted", False)
        guild   = interaction.guild
        channel = interaction.channel
        errors  = 0

        for uid in room["members"]:
            m = guild.get_member(uid)
            if m:
                try:
                    await channel.set_permissions(m, view_channel=True, send_messages=not muting)
                except discord.Forbidden:
                    errors += 1

        room["muted"] = muting
        _save(data)

        status = "🔇 Místnost ztišena — nikdo nemůže psát." if muting else "🔊 Místnost odtišena."
        if errors:
            status += f"\n-# Chyba u {errors} hráčů."
        await interaction.followup.send(status, ephemeral=True)

    # ── /rp info ──────────────────────────────────────────────────────────────

    @rp.command(name="info", description="[DM] Přehled všech aktivních RP místností.")
    async def rp_info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.", ephemeral=True)
            return

        data = _load()
        if not data:
            await interaction.followup.send("Žádné aktivní RP místnosti.", ephemeral=True)
            return

        guild = interaction.guild
        embed = discord.Embed(title="🎭  Aktivní RP místnosti", color=0x5865f2)

        for heslo, room in data.items():
            channel   = guild.get_channel(room["channel_id"])
            ch_str    = channel.mention if channel else f"*#{room['name']} (smazán)*"
            mute_tag  = "  🔇" if room.get("muted") else ""
            names     = []
            for uid in room.get("members", []):
                m = guild.get_member(uid)
                tag = " 👑" if uid == room["creator_id"] else ""
                names.append((m.display_name if m else f"<@{uid}>") + tag)

            spectator_names = []
            for uid in room.get("spectators", []):
                m = guild.get_member(uid)
                spectator_names.append(f"👁️ {m.display_name if m else f'<@{uid}>'}")

            all_names = names + spectator_names
            embed.add_field(
                name=f"{ch_str}{mute_tag}  ·  `{heslo}`",
                value=f"{'  '.join(all_names) if all_names else '—'}",
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /rp remove ────────────────────────────────────────────────────────────

    @rp.command(name="remove", description="[DM] Přesune aktuální RP místnost do archivu.")
    async def rp_remove(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.", ephemeral=True)
            return

        data        = _load()
        heslo, room = _room_by_channel(data, interaction.channel_id)

        if not room:
            await interaction.followup.send("❌ Tento kanál není RP místností.", ephemeral=True)
            return

        guild           = interaction.guild
        channel         = guild.get_channel(room["channel_id"])
        archive_cat     = guild.get_channel(ARCHIVE_CATEGORY_ID)

        if channel:
            try:
                new_topic = ("[ARCHIV] " + channel.topic) if channel.topic else "[ARCHIV]"
                await channel.edit(
                    category=archive_cat,
                    sync_permissions=True,
                    topic=new_topic,
                )
            except discord.Forbidden:
                await interaction.followup.send("❌ Bot nemá oprávnění přesunout kanál.", ephemeral=True)
                return

        del data[heslo]
        _save(data)

        await interaction.followup.send(
            f"✅ Místnost **#{room['name']}** přesunuta do archivu.", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(RPManage(bot))
