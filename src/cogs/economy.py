import discord
from discord import app_commands
from discord.ext import commands
import json
import os

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.path = "economy.json"

    def load_data(self):
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return {}
                return json.loads(content)
        except:
            return {}

    def save_data(self, data):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    @app_commands.command(name="g", description="Zobrazí tvůj počet zlaťáků")
    async def g(self, interaction: discord.Interaction):
        data = self.load_data()
        user_id = str(interaction.user.id)
        balance = data.get(user_id, 0)
        
        await interaction.response.send_message(
            f"{interaction.user.mention}, tvůj stav konta: **{balance}** <:goldcoin:1477303464781680772>"
        )

    @app_commands.command(name="gsend", description="Pošle zlaťáky jinému hráči")
    async def gsend(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount <= 0:
            return await interaction.response.send_message("Musíš poslat víc než 0!", ephemeral=True)
        if member.id == interaction.user.id:
            return await interaction.response.send_message("Nemůžeš poslat peníze sám sobě!", ephemeral=True)

        data = self.load_data()
        sender_id = str(interaction.user.id)
        receiver_id = str(member.id)

        sender_bal = data.get(sender_id, 0)
        if sender_bal < amount:
            return await interaction.response.send_message(
                f"Nemáš dost zlaťáků! (Chybí ti {amount - sender_bal} <:goldcoin:1477303464781680772>)",
                ephemeral=True
            )

        data[sender_id] = sender_bal - amount
        data[receiver_id] = data.get(receiver_id, 0) + amount
        
        self.save_data(data)
        await interaction.response.send_message(
            f"Úspěšně jsi poslal **{amount}** <:goldcoin:1477303464781680772> hráči {member.mention}."
        )

    @app_commands.command(name="gadd", description="Admin: Přidá zlaťáky hráči")
    @app_commands.checks.has_permissions(administrator=True)
    async def gadd(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount <= 0:
            return await interaction.response.send_message("Částka musí být větší než 0!", ephemeral=True)

        data = self.load_data()
        user_id = str(member.id)
        
        data[user_id] = data.get(user_id, 0) + amount
        self.save_data(data)

        await interaction.response.send_message(
            f"✅ Přidáno **{amount}** <:goldcoin:1477303464781680772> hráči {member.mention}. "
            f"(Celkem: {data[user_id]})"
        )

    @app_commands.command(name="gremove", description="Admin: Odebere zlaťáky hráči (nebo všechny)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        member="Hráč, kterému chceš odebrat zlaťáky",
        amount="Počet zlaťáků k odebrání (nebo 0 pro odebrání všech)"
    )
    async def gremove(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        data = self.load_data()
        user_id = str(member.id)
        current = data.get(user_id, 0)

        # amount == 0 znamená "odeber vše"
        if amount == 0:
            removed = current
            data[user_id] = 0
            self.save_data(data)
            return await interaction.response.send_message(
                f"🗑️ Hráči {member.mention} bylo odebráno všech **{removed}** <:goldcoin:1477303464781680772>. Konto je prázdné."
            )

        if amount < 0:
            return await interaction.response.send_message("Zadej kladné číslo (nebo 0 pro odebrání všeho)!", ephemeral=True)

        if current == 0:
            return await interaction.response.send_message(
                f"Hráč {member.mention} nemá žádné zlaťáky.", ephemeral=True
            )

        actual_removed = min(amount, current)
        data[user_id] = current - actual_removed
        self.save_data(data)

        msg = f"🗑️ Odebráno **{actual_removed}** <:goldcoin:1477303464781680772> hráči {member.mention}. (Zbývá: {data[user_id]})"
        if actual_removed < amount:
            msg += f"\n-# *(Hráč měl jen {current}, odebráno maximum.)*"
        
        await interaction.response.send_message(msg)



    @app_commands.command(name="gleaderboard", description="Top 10 nejbohatších hráčů serveru")
    async def gleaderboard(self, interaction: discord.Interaction):
        data = self.load_data()
        if not data:
            return await interaction.response.send_message("Zatím tu nikdo žádné zlatáky nemá.", ephemeral=True)

        # Seřadit podle zůstatku sestupně, vzít top 10
        sorted_players = sorted(data.items(), key=lambda x: x[1], reverse=True)[:10]

        embed = discord.Embed(
            title="🏆 Žebříček nejbohatších",
            color=0xFFD700
        )

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (user_id, balance) in enumerate(sorted_players):
            prefix = medals[i] if i < 3 else f"**{i+1}.**"
            try:
                member = interaction.guild.get_member(int(user_id))
                name = member.display_name if member else f"Neznámý ({user_id})"
            except:
                name = f"Neznámý ({user_id})"
            lines.append(f"{prefix} {name} — **{balance}** <:goldcoin:1477303464781680772>")

        embed.description = "\n".join(lines)

        # Ukaz pozici volajiciho hrace pokud neni v top 10
        caller_id = str(interaction.user.id)
        caller_rank = next((i+1 for i, (uid, _) in enumerate(sorted(data.items(), key=lambda x: x[1], reverse=True)) if uid == caller_id), None)
        caller_bal = data.get(caller_id, 0)
        if caller_rank and caller_rank > 10:
            embed.set_footer(text=f"Tvoje pozice: #{caller_rank} ({caller_bal} zlatáků)")
        elif caller_rank:
            embed.set_footer(text=f"Tvoje pozice: #{caller_rank}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="gdaily", description="Vyzvedni svou denní odměnu zlatáků")
    async def gdaily(self, interaction: discord.Interaction):
        import time

        DAILY_AMOUNT = 5
        COOLDOWN = 86400  # 24 hodin v sekundách

        # Cooldowny ulozit do separatniho souboru
        cooldown_path = "economy_daily.json"
        try:
            with open(cooldown_path, "r", encoding="utf-8") as f:
                cooldowns = json.load(f)
        except:
            cooldowns = {}

        user_id = str(interaction.user.id)
        now = int(time.time())
        last_claim = cooldowns.get(user_id, 0)
        time_left = COOLDOWN - (now - last_claim)

        if time_left > 0:
            hours = time_left // 3600
            minutes = (time_left % 3600) // 60
            return await interaction.response.send_message(
                f"⏳ Už sis dnes odměnu vyzvedl! Vrať se za **{hours}h {minutes}m**.",
                ephemeral=True
            )

        # Pridat zlataky
        data = self.load_data()
        data[user_id] = data.get(user_id, 0) + DAILY_AMOUNT
        self.save_data(data)

        # Ulozit timestamp
        cooldowns[user_id] = now
        with open(cooldown_path, "w", encoding="utf-8") as f:
            json.dump(cooldowns, f, indent=4)

        await interaction.response.send_message(
            f"🎁 Vyzvedl sis denní odměnu: **+{DAILY_AMOUNT}** <:goldcoin:1477303464781680772>\n"
            f"Celkem na kontě: **{data[user_id]}** <:goldcoin:1477303464781680772>"
        )
async def setup(bot):
    await bot.add_cog(Economy(bot))