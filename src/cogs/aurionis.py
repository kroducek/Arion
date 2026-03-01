"""
Aurionis Cog - Hlavní rozcestník pro ArionBot
Tento soubor obsahuje základní info, ping, kroniku a turnajový systém.
Zbytek mechanik (Roll, Combat, Party, Countdown) je ve vlastních souborech.
"""
import discord
import random  # <--- Tohle chybělo pro funkci random.choice
from discord.ext import commands
from discord import app_commands

class Aurionis(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Výchozí seznam účastníků turnaje
        self.tournament_players = ["Gabriel", "Hao", "Darryn"]

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"✅ Arion Kronika je připravena k zápisu!")

    # --- ZÁKLADNÍ PŘÍKAZY ---

    @app_commands.command(name="ping", description="Zjistí, jak rychle Arion přiběhne")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🐾 *Arion nastraží uši!* Přiběhla jsem za **{latency}ms**, mňau!")

    @app_commands.command(name="meow", description="Interact with Arion")
    async def meow(self, interaction: discord.Interaction):
        responses = [
            "🐱 *Arion se ti otřela o nohu a spokojeně zamňoukala*",
            "🧶 *Arion ti přinesla virtuální klubíčko. Chce si hrát!*",
            "💤 *Arion spí na tvé klávesnici. Teď nic nenapíšeš*",
            "✨ *Arion upřeně hledí do prázdna za tebou. Vidí něco, co ty ne*",
            "🐾 *Arion ti vyskočila na rameno a jemně tě kousla do ucha*",
            "🐱 *Arion se svalila na záda a ukazuje bříško. Je to past?*",
            "🌙 *Arion tiše přede a její srst slabě světluje v barvách Aurionisu*",
            "🐭 *Arion ti přinesla ulovenou mechanickou myš. Je na sebe hrdá*",
            "🥛 *Arion vylila tvou virtuální kávu. Jen se na tebe drze podívala*",
            "📦 *Arion našla krabici od tvého nového procesoru a okamžitě se do ní nasáčkovala*",
            "🐈 *Arion se protahuje. Vypadá nekonečně dlouhá*",
            "💨 *Arion dostala 'zoomies' a proběhla tvým kanálem rychlostí světla*",
            "👀 *Arion tě sleduje zpoza rohu. Má rozšířené zorničky*",
            "🦋 *Arion se snaží chytit digitálního motýla*",
            "🧼 *Arion si pečlivě olizuje tlapku a ignoruje tvou existenci*",
            "👑 *Arion si sedla na tvůj pomyslný trůn. Teď vládne ona*",
            "🌌 *Arion ti tlapkou ukazuje na vzdálenou hvězdu v systému Aurionis*",
            "🥯 *Arion ukradla tvou svačinu a utekla s ní pod postel*",
            "🛸 *Arion se snaží ulovit laserové ukazovátko z jiné dimenze*",
            "📡 *Arion zachytila signál z hlubokého vesmíru a teď zmateně mňouká na router*",
            "🌵 *Arion se pokusila očichat kaktus. Teď uraženě sedí v koutě*",
            "🍞 *Arion se složila do dokonalého tvaru bochníku chleba*",
            "🧿 *Arioniny oči na vteřinu zazářily jako supernovy*",
            "🎵 *Arion začala příst v rytmu tvé oblíbené hudby*",
            "🧛 *Arion na tebe vybafla ze stínu. Skoro ti vyskočilo srdce*",
            "🧊 *Arion tlapkou shazuje virtuální kostky ledu ze stolu. Jen tak*",
            "🧶 *Arion se zamotala do kabelů od tvého setupu. Pomoz jí!*",
            "💤 *Arion chrápe tak hlasitě, že to vibruje s celým serverem*",
            "🎀 *Arion si hraje s tvým kurzorem myši. Skoro jsi kliknul jinam!*",
            "🧠 *Arion vypadá, že právě pochopila smysl vesmíru. Pak se začala honit za ocasem*",
            "🕵️ *Arion ti prohledává kapsy. Hledá pamlsky, ne důkazy*",
            "🌈 *Arion proskočila duhou a teď chvíli zanechává barevné stopy*",
            "🛑 *Arion si lehla přímo na cestu tvému dalšímu příkazu*",
            "💎 *Arion ti přinesla zářící krystal z hlubin Aurionisu*",
            "🌋 *Arion shodila tvou klávesnici do imaginární lávy*",
            "🛸 *Arion byla na vteřinu unesena UFO, ale vrátili ji, protože moc mňoukala*",
            "🍟 *Arion ti olízla hranolku. Už ji asi nebudeš chtít*",
            "🧹 *Arion útočí na koště. Je to její úhlavní nepřítel*",
            "🌡️ *Arion je tak huňatá, že zvýšila teplotu v kanálu o 2 stupně*",
            "🖤 *Arion se ti schovala do stínu. Vidíš jen její svítící oči*"
        ]
        await interaction.response.send_message(random.choice(responses))

    @app_commands.command(name="kronika", description="Arion kronika (Nápověda)")
    async def help(self, interaction: discord.Interaction):
        """Přehled všech funkcí Arion"""
        embed = discord.Embed(
            title="📚 Arion osobní kronika",
            description="Mňau! Vítej v mojí kronice! Všechno, co umím, jsem zapsala sem. Tady jsou tvé možnosti:",
            color=0xFFA500
        )

        embed.add_field(
            name="🎲 ROLL SYSTEM",
            value="`/roll` - Hod kostkami\n`/check` - Prověří tvé schopnosti",
            inline=True
        )
        embed.add_field(
            name="⚔️ COMBAT SYSTEM",
            value="`/combat` - Start boje\n`/next` - Další tah v pořadí",
            inline=True
        )
        embed.add_field(
            name="🤝 PARTY SYSTEM",
            value="`/party_legacy` - Správa členů\n`/party set` - Nastavení vzhledu a cílů",
            inline=True
        )
        embed.add_field(
            name="📖 DENÍK & POSTAVY",
            value=(
                "`/diary add` - Nový zápis do deníku\n"
                "`/diary show` - Zobraz svůj deník\n"
                "`/profile` - Profil tvé postavy\n"
                "`/quests` - Aktivní questy"
            ),
            inline=True
        )
        embed.add_field(
            name="💰 GOLD SYSTEM",
            value=(
                "`/g` - Tvůj aktuální zlatý\n"
                "`/gdaily` - Denní odměna\n"
                "`/gsend` - Pošli zlato hráči\n"
                "`/gleaderboard` - Žebříček bohatství"
            ),
            inline=True
        )
        embed.add_field(
            name="🏆 TURNAJ",
            value=(
                "`/tournament list` - Vyvolení co postoupili do druhého kola\n"
                "`/vyvoleni list` - Seznam všech dobrodruhů"
            ),
            inline=True
        )
        embed.add_field(
            name="🎮 MINIHRY",
            value=(
                "`/kostky match` - Připoj se do lobby\n"
                "`/kostky start` - Spustit hru (leader)\n"
                "`/kostky score` - Aktuální skóre\n"
                "`/story_create` - Psaná minihra"
            ),
            inline=True
        )
        embed.add_field(
            name="🐾 Ostatní",
            value=(
                "`/ping` - Latence bota\n"
                "`/meow` - Pozdravit Arion\n"
                "`/poll` - Vytvořit hlasování s tlačítky\n"
                "`/countdown` - Spustí odpočet\n"
                "**Warp Gate** - Vstup do HUB kanálu pro vlastní voice"
            ),
            inline=False
        )

        embed.set_footer(text="Arion tě provází světem Aurionis | v1.2")
        await interaction.response.send_message(embed=embed)

    # --- VYVOLENÍ (Seznam postav) ---

    vyvoleni_group = app_commands.Group(name="vyvoleni", description="Seznam vyvolených dobrodruhů")

    @vyvoleni_group.command(name="list", description="Zobrazí všechny zaregistrované postavy")
    async def vyvoleni_list(self, interaction: discord.Interaction):
        import json, os
        DATA_FILE = "profiles.json"
        if not os.path.exists(DATA_FILE):
            await interaction.response.send_message("Zatím nikdo není zapsán v knize osudu.", ephemeral=True)
            return
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            data = {}

        if not data:
            await interaction.response.send_message("Zatím nikdo není zapsán v knize osudu.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📖 Kniha osudu — Vyvolení",
            description="*Arion listuje tlustou živoucí knihou a čte jména nahlas...*",
            color=0xFFD700
        )

        lines = []
        for uid, profile in data.items():
            name = profile.get("name", "—")
            rank = profile.get("rank", "F3")
            member = interaction.guild.get_member(int(uid))
            discord_tag = f" <@{uid}>" if member else ""
            lines.append(f"**{name}** · `{rank}`{discord_tag}")

        # Rozděl na chunky kvůli limitu pole (1024 znaků)
        chunk, chunks = [], []
        for line in lines:
            if sum(len(l) + 1 for l in chunk) + len(line) > 950:
                chunks.append(chunk)
                chunk = []
            chunk.append(line)
        if chunk:
            chunks.append(chunk)

        for i, ch in enumerate(chunks):
            embed.add_field(
                name=f"Zapsaní dobrodruzi {f'({i+1})' if len(chunks) > 1 else ''}",
                value="\n".join(ch),
                inline=False
            )

        embed.set_footer(text=f"Celkem zapsáno: {len(data)} dobrodruhů | Aurionis: Act II")
        await interaction.response.send_message(embed=embed)

    # --- TURNAJOVÝ SYSTÉM (Hvězdy) ---

    tournament_group = app_commands.Group(name="tournament", description="Správa turnaje Hvězdy")

    @tournament_group.command(name="list", description="Zobrazí vyvolené ve druhém kole")
    async def tournament_list(self, interaction: discord.Interaction):
        """Zobrazí aktuální hráče/NPCs v turnaji"""
        players_list = "\n".join([f"• {p}" for p in self.tournament_players]) if self.tournament_players else "• Zatím nikdo..."
        
        embed = discord.Embed(
            title="✨ Turnaj Hvězdy",
            description="**Vyvolení, co se aktuálně dostali do druhého kola turnaje:**",
            color=0xFFD700
        )
        embed.add_field(name="Seznam postupujících:", value=players_list, inline=False)
        embed.set_footer(text="Arion bedlivě sleduje Turnaj o Krále hvězdy")
        
        await interaction.response.send_message(embed=embed)

    @tournament_group.command(name="add", description="Přidá jméno do turnaje")
    async def tournament_add(self, interaction: discord.Interaction, jmeno: str):
        if jmeno in self.tournament_players:
            await interaction.response.send_message(f"🐾 *Mňau?* `{jmeno}` už v kronice zapsaného mám!")
        else:
            self.tournament_players.append(jmeno)
            await interaction.response.send_message(f"✅ *Arion zapsala nové jméno do kroniky.* `{jmeno}` postoupil do druhého kola!")

    @tournament_group.command(name="remove", description="Odebere jméno z turnaje")
    async def tournament_remove(self, interaction: discord.Interaction, jmeno: str):
        if jmeno in self.tournament_players:
            self.tournament_players.remove(jmeno)
            await interaction.response.send_message(f"❌ *Arion přemázla jméno tlapkou...* `{jmeno}` byl z turnaje vyřazen.")
        else:
            await interaction.response.send_message(f"🐾 *Mňau?* `{jmeno}` v mém seznamu není, nepoužili jste špatný inkoust?")

async def setup(bot: commands.Bot):
    await bot.add_cog(Aurionis(bot))