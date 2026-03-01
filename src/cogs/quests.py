import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from datetime import datetime

QUESTS_FILE = "quests.json"
DIARY_FILE  = "diaries.json"

ARION_NAME = "Arion"   # jméno podepisující soukromé zprávy


# ── Pomocné funkce ─────────────────────────────────────────────────────────────

def load_quests() -> dict:
    """Formát: { "quest_name": { "info": str, "members": [int, ...], "added": str } }"""
    if os.path.exists(QUESTS_FILE):
        try:
            with open(QUESTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_quests(data: dict):
    with open(QUESTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_diaries() -> dict:
    if os.path.exists(DIARY_FILE):
        try:
            with open(DIARY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_diaries(data: dict):
    with open(DIARY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def today() -> str:
    return datetime.now().strftime("%d.%m.")

def diary_quest_line(name: str, info: str) -> str:
    return f"📜 QUEST [{today()}]: {name} — {info}"


# ── View: tlačítko QUESTY v deníku ────────────────────────────────────────────

class DiaryQuestView(discord.ui.View):
    """Přidá tlačítko QUESTY k zobrazenému deníku."""

    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

    @discord.ui.button(label="📜 QUESTY", style=discord.ButtonStyle.primary)
    async def show_quests(self, interaction: discord.Interaction, button: discord.ui.Button):
        quests = load_quests()

        # Filtruj jen questy, kde je tento hráč
        user_quests = {
            name: data
            for name, data in quests.items()
            if self.user_id in data.get("members", [])
        }

        if not user_quests:
            await interaction.response.send_message(
                "Nemáš žádné aktivní questy.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="📜 Tvoje aktivní questy",
            color=0x2E8B57
        )
        for name, data in user_quests.items():
            embed.add_field(
                name=f"**{name}**",
                value=f"{data['info']}\n-# Přidáno: {data.get('added', '?')}",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Quests Cog ────────────────────────────────────────────────────────────────

class QuestsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    quest_group = app_commands.Group(name="quest", description="Správa questů")

    # ── /quests ───────────────────────────────────────────────────────────────

    @app_commands.command(name="quests", description="Zobraz všechny aktivní questy a jejich účastníky")
    async def quests_list(self, interaction: discord.Interaction):
        quests = load_quests()

        if not quests:
            await interaction.response.send_message(
                "Momentálně nejsou žádné aktivní questy.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="📜 Aktivní questy",
            color=0x2E8B57
        )

        for name, data in quests.items():
            member_mentions = []
            for uid in data.get("members", []):
                member = interaction.guild.get_member(uid)
                member_mentions.append(member.display_name if member else f"<@{uid}>")

            members_str = ", ".join(member_mentions) if member_mentions else "*nikdo*"
            embed.add_field(
                name=f"**{name}**",
                value=f"{data['info']}\n👥 {members_str}\n-# Přidáno: {data.get('added', '?')}",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

    # ── /quest add ────────────────────────────────────────────────────────────

    @quest_group.command(name="add", description="Vytvoř nový quest a přidej ho hráčům do deníků")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        name="Název questu",
        info="Popis / info questu",
        members="Hráči oddělení mezerou (zmínka)"
    )
    async def quest_add(
        self,
        interaction: discord.Interaction,
        name: str,
        info: str,
        members: str
    ):
        await interaction.response.defer(ephemeral=True)

        quests = load_quests()
        if name in quests:
            await interaction.followup.send(
                f"Quest s názvem **{name}** již existuje. Zvol jiný název nebo ho nejdřív odeber.",
                ephemeral=True
            )
            return

        # Parsuj zmíněné členy ze stringu (např. "<@123> <@456>")
        guild = interaction.guild
        member_ids: list[int] = []
        for word in members.split():
            # Podpora <@ID> i <@!ID>
            uid_str = word.strip("<@!>")
            if uid_str.isdigit():
                m = guild.get_member(int(uid_str))
                if m:
                    member_ids.append(m.id)

        if not member_ids:
            await interaction.followup.send(
                "Nepodařilo se najít žádné platné členy serveru. Použij @zmínku.",
                ephemeral=True
            )
            return

        # Ulož quest
        quests[name] = {
            "info": info,
            "members": member_ids,
            "added": today()
        }
        save_quests(quests)

        # Zapiš do deníků a pošli DM
        diaries = load_diaries()
        line = diary_quest_line(name, info)
        dm_errors: list[str] = []

        for uid in member_ids:
            uid_str = str(uid)
            entries = diaries.get(uid_str, [])
            entries.append(line)
            diaries[uid_str] = entries

            # DM od Ariona
            member = guild.get_member(uid)
            if member:
                try:
                    dm_embed = discord.Embed(
                        title="📜 Nový zápis v deníku",
                        description=f"**{name}**\n{info}",
                        color=0x8B6914
                    )
                    dm_embed.set_footer(text=ARION_NAME)
                    await member.send(embed=dm_embed)
                except discord.Forbidden:
                    dm_errors.append(member.display_name)

        save_diaries(diaries)

        # Odpověď adminovi
        names_str = ", ".join(
            guild.get_member(uid).display_name if guild.get_member(uid) else str(uid)
            for uid in member_ids
        )
        msg = f"✅ Quest **{name}** byl přidán a zapsán do deníků: {names_str}."
        if dm_errors:
            msg += f"\n⚠️ Nepodařilo se odeslat DM: {', '.join(dm_errors)} (mají zakázané DM)."

        await interaction.followup.send(msg, ephemeral=True)

    # ── /quest remove ─────────────────────────────────────────────────────────

    @quest_group.command(name="remove", description="Odeber quest z databáze a ze všech deníků")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(name="Název questu k odebrání")
    async def quest_remove(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)

        quests = load_quests()
        if name not in quests:
            await interaction.followup.send(
                f"Quest **{name}** neexistuje.", ephemeral=True
            )
            return

        member_ids = quests[name].get("members", [])
        del quests[name]
        save_quests(quests)

        # Odstraň ze všech deníků záznamy obsahující tento quest
        diaries = load_diaries()
        removed_from = 0
        for uid in member_ids:
            uid_str = str(uid)
            if uid_str in diaries:
                before = len(diaries[uid_str])
                diaries[uid_str] = [
                    e for e in diaries[uid_str]
                    if f"QUEST" not in e or name not in e
                ]
                if len(diaries[uid_str]) < before:
                    removed_from += 1

        save_diaries(diaries)

        await interaction.followup.send(
            f"🗑️ Quest **{name}** byl odebrán z databáze a smazán z {removed_from} deníků.",
            ephemeral=True
        )

    # ── Autocomplete pro name v /quest remove ─────────────────────────────────

    @quest_remove.autocomplete("name")
    async def quest_name_autocomplete(
        self, interaction: discord.Interaction, current: str
    ):
        quests = load_quests()
        return [
            app_commands.Choice(name=n, value=n)
            for n in quests
            if current.lower() in n.lower()
        ][:25]


async def setup(bot):
    await bot.add_cog(QuestsCog(bot))