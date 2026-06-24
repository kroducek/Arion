import asyncio
import discord
from discord.ext import commands
from discord import app_commands

from src.utils.paths import (
    PROFILES, TAKEDOWNS, ECONOMY, DIARIES, PLAYER_PERKS, REPUTATION, CHARACTERS,
)
from src.utils.json_utils import load_json, save_json
from src.database.characters import list_chars, ckey

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

DM_ROLE_NAME = "DM"

def _is_dm(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    return any(r.name == DM_ROLE_NAME for r in interaction.user.roles)

def _get_count() -> int:
    data = load_json(TAKEDOWNS, default={"count": 0})
    return data.get("count", 0)

def _increment_count() -> int:
    data = load_json(TAKEDOWNS, default={"count": 0})
    data["count"] = data.get("count", 0) + 1
    save_json(TAKEDOWNS, data)
    return data["count"]

def _char_keys(member_id) -> list:
    """
    Všechny datové klíče postav účtu ('<id>:<slot>') napříč sloty.
    Defensivně přidá i legacy varianty ('<id>' a '<id>:1') — kdyby něco
    nebylo zmigrované, ať to takedown taky uklidí.
    """
    keys = [ckey(member_id, s) for s in list_chars(member_id).keys()]
    for legacy in (str(member_id), ckey(member_id, "1")):
        if legacy not in keys:
            keys.append(legacy)
    return keys

def _wipe_inventory(member_id) -> None:
    """Vyprázdní inventář/poznámky/výbavu u VŠECH postav účtu."""
    profiles = load_json(PROFILES, default={})
    changed = False
    for key in _char_keys(member_id):
        profile = profiles.get(key)
        if not profile:
            continue
        profile["inventory"] = []
        profile["notes"] = []
        if "equipment" in profile:
            profile["equipment"] = {k: None for k in profile["equipment"]}
        changed = True
    if changed:
        save_json(PROFILES, profiles)

def _wipe_profile(member_id) -> None:
    """
    Smaže VŠECHNY postavy účtu: profil, gold, deník, perky, reputaci na každém
    slotu + záznam v registru postav. (Stříbro/prach/achievementy = účtové,
    nesahá se na ně.)
    """
    keys = _char_keys(member_id)
    for path in (PROFILES, ECONOMY, DIARIES, PLAYER_PERKS):
        d = load_json(path, default={})
        if any(k in d for k in keys):
            for k in keys:
                d.pop(k, None)
            save_json(path, d)
    # reputace: {gid: {players: {key: ...}}}
    rep = load_json(REPUTATION, default={})
    changed = False
    for gid, gdata in rep.items():
        if not isinstance(gdata, dict):
            continue
        players = gdata.get("players", {})
        for k in keys:
            if k in players:
                players.pop(k, None)
                changed = True
    if changed:
        save_json(REPUTATION, rep)
    # registr postav — smaž celý záznam účtu
    chars = load_json(CHARACTERS, default={})
    if str(member_id) in chars:
        chars.pop(str(member_id), None)
        save_json(CHARACTERS, chars)

# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class TakedownCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="takedown", description="[DM] Arion provede Takedown na hráče.")
    @app_commands.describe(member="Hráč, který se zprotivil Arion")
    async def takedown(self, interaction: discord.Interaction, member: discord.Member):
        if not _is_dm(interaction):
            await interaction.response.send_message("❌ Nemáš oprávnění.", ephemeral=True)
            return

        # Okamžitě potvrdíme interakci — Discord má 3s timeout
        await interaction.response.defer(ephemeral=True)

        ch = interaction.channel
        uid = member.id          # wipe-all jede přes syrové id (všechny sloty)
        color_red = 0xC0392B

        # Potvrzení vidí jen DM
        await interaction.followup.send(
            f"⚔️ Takedown zahájen na {member.mention}.", ephemeral=True
        )

        async def say(text: str, delay: float = 1.8):
            await asyncio.sleep(delay)
            try:
                await ch.send(text)
            except discord.HTTPException:
                pass

        async def embed(title: str, desc: str, delay: float = 2.2):
            await asyncio.sleep(delay)
            try:
                e = discord.Embed(title=title, description=desc, color=color_red)
                await ch.send(embed=e)
            except discord.HTTPException:
                pass

        # 1
        await say("Takedown, Takedown, Takedown-down-do-do...", delay=0.5)
        # 2
        await say("Arion shows the world!")
        # 3
        await say("That this is Takedown!")
        # 4
        await embed(
            "⚔️ Takedown zahájen",
            f"Hráč {member.mention} se zprotivil **Arion** a čeká ho **Takedown**.",
        )
        # 5
        await say("'Cause I see your real face, and it's ugly as sin")
        # 6
        await say("Time to put you in your place, 'cause you're rotten within")
        # 7
        await say("When your patterns start to show")
        # 8
        await say("It makes the hatred wanna grow outta my veins")

        # 9 — smazání inventáře
        _wipe_inventory(uid)
        await embed(
            "🗑️ Inventář smazán",
            f"Inventář hráče {member.mention} byl **smazán**.",
        )

        # 10
        await say("I don't think you're ready for the takedown")
        # 11
        await say("Break you into pieces in a world of pain 'cause you're all the same")

        # 12 — smazání profilu
        _wipe_profile(uid)
        await embed(
            "💀 Profil smazán",
            f"Profil hráče {member.mention} byl **smazán**.",
        )

        # 13
        await say("Yeah, it's a takedown")
        # 14
        await say("A demon with no feelings don't deserve to live, it's so obvious")
        # 15
        await say("I'ma gear up...")

        # 16 — ban
        try:
            await member.ban(reason=f"Takedown — provedl {interaction.user}")
            ban_text = f"Hráč {member.mention} byl **permanentně zabanován**."
        except discord.Forbidden:
            ban_text = f"Hráč {member.mention} — ban se nezdařil (chybí oprávnění)."

        await embed("🔨 Permanentní ban", ban_text)

        # 17
        await say("....and take you down")

        # 18 — počítadlo
        total = _increment_count()
        await embed(
            "✅ Takedown dokončen",
            f"Arion provedla momentálně **{total}** Takedownů.",
        )


async def setup(bot):
    await bot.add_cog(TakedownCog(bot))