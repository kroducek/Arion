"""
Aurionis Cog - Hlavní rozcestník pro ArionBot
Tento soubor obsahuje základní info, ping, kroniku a turnajový systém.
Zbytek mechanik (Roll, Combat, Party, Countdown) je ve vlastních souborech.
"""
import discord
import random
import json
import os
from discord.ext import commands
from discord import app_commands

from src.utils.paths import TOURNAMENT as TOURNAMENT_FILE

def _load_tournament() -> list:
    if not os.path.exists(TOURNAMENT_FILE):
        return []
    try:
        with open(TOURNAMENT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_tournament(data: list):
    with open(TOURNAMENT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

class Aurionis(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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

    @app_commands.command(name="erase", description="Smaže všechny zprávy v této místnosti")
    @app_commands.describe(confirmation="Potvrzení smazání všech zpráv (napiš 'all')")
    async def erase(self, interaction: discord.Interaction, confirmation: str):
        if confirmation.lower() != "all":
            await interaction.response.send_message("Pro smazání všech zpráv použij '/erase all'", ephemeral=True)
            return

        # Kontrola oprávnění
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Nemáš oprávnění mazat zprávy.", ephemeral=True)
            return

        channel = interaction.channel

        # Defer odpověď, protože mazání může trvat
        await interaction.response.defer(ephemeral=True)

        try:
            # Smaž všechny zprávy (loop kvůli limitu Discordu)
            deleted_count = 0
            while True:
                deleted = await channel.purge(limit=100)
                deleted_count += len(deleted)
                if len(deleted) < 100:
                    break
            await interaction.followup.send(f"✅ Smazáno {deleted_count} zpráv v této místnosti.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Nemám oprávnění mazat zprávy v této místnosti.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Chyba při mazání: {str(e)}", ephemeral=True)

    @app_commands.command(name="kronika", description="Arion kronika (Nápověda)")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📚 Arion osobní kronika",
            description="*Arion otevře tlustou živoucí knihu a začne listovat...*\nVšechno co umím, najdeš tady:",
            color=0xFFA500
        )
        embed.add_field(
            name="🎲 ROLL & CHECK",
            value=(
                "`/roll` — Hod kostkami (1d20+2d4+5...)\n"
                "`/roll check:` — Check atributu (porovná s tvým statem)\n"
                "`/roll check: check2:` — Kombinovaný check (průměr dvou statů)\n"
                "`/show_rolls` — Statistiky tvých hodů"
            ),
            inline=False
        )
        embed.add_field(
            name="⚔️ COMBAT",
            value=(
                "`/combat_start` — Zahájit boj\n"
                "`/combat_join` — Zapojit se do boje\n"
                "`/combat_add_npc` — Přidat NPC/potvoru\n"
                "`/next` — Předat tah dalšímu\n"
                "`/combat_end` — Ukončit boj"
            ),
            inline=True
        )
        embed.add_field(
            name="🤝 PARTY",
            value=(
                "`/party` — Zobraz svou partu\n"
                "`/party set` — Nastavení party"
            ),
            inline=True
        )
        embed.add_field(
            name="📖 POSTAVA & DENÍK",
            value=(
                "`/profile` — Průkaz dobrodruha\n"
                "`/profile-edit` — Upravit průkaz\n"
                "`/eat` — Sněz jídlo z inventáře\n"
                "`/diary add/show` — Deník postavy\n"
                "`/memory show/add/remove/edit` — Vzpomínky postavy\n"
                "`/quests` — Aktivní questy\n"
                "`/quest add/status/log` — Správa questů"
            ),
            inline=False
        )
        embed.add_field(
            name="🎒 INVENTÁŘ",
            value=(
                "`/inv` — Zobraz inventář a equipment\n"
                "`/equip` — Equipni item\n"
                "`/unequip` — Sundej item ze slotu\n"
                "`/use` — Použij consumable (lektvar, jídlo...)\n"
                "`/inv-give` — Pošli item jinému hráči\n"
                "`/inv-inspect` — Detail itemu z databáze"
            ),
            inline=True
        )
        embed.add_field(
            name="💰 GOLD & SHOP",
            value=(
                "`/g` — Tvůj aktuální zůstatek\n"
                "`/gsend` — Pošli zlato hráči\n"
                "`/gleaderboard` — Žebříček bohatství\n"
                "`/gshop open` — Otevři shop"
            ),
            inline=True
        )
        embed.add_field(
            name="🏅 REPUTACE",
            value=(
                "`/rep show` — Zobraz reputaci u frakcí\n"
                "`/rep list` — Přehled hráčů ve frakci"
            ),
            inline=True
        )
        embed.add_field(
            name="🃏 TAROT",
            value=(
                "`/tarot den` — Karta dne (zdarma)\n"
                "`/tarot solo` — Soukromý výklad (50 🪙)\n"
                "`/tarot session` — Veřejná session"
            ),
            inline=True
        )
        embed.add_field(
            name="🎭 RP MÍSTNOSTI",
            value=(
                "`/rp create` — Vytvoř soukromou RP místnost\n"
                "`/rp join` — Vstup pomocí hesla\n"
                "`/rp kick` — Vyhoď hráče\n"
                "`/rp mute` — Ztichni místnost"
            ),
            inline=True
        )
        embed.add_field(
            name="🏆 TURNAJ & VYVOLENÍ",
            value=(
                "`/tournament list` — Postupující do 2. kola\n"
                "`/vyvoleni list` — Všichni zapsaní dobrodruzi"
            ),
            inline=True
        )
        embed.add_field(
            name="🎮 MINIHRY",
            value=(
                "`/kostky` — Dice minihra\n"
                "`/story create` — Psaná minihra\n"
                "`/poll` — Hlasování\n"
                "`/countdown` — Odpočet"
            ),
            inline=True
        )
        embed.add_field(
            name="⚙️ DM / ADMIN",
            value=(
                "`/vliv` — Uděl hráči Vliv (Světlo/Temnota/Rovnováha)\n"
                "`/takedown` — Arion provede Takedown\n"
                "`/erase all` — Smaže všechny zprávy v místnosti\n"
                "`/hunger-balance` — Simulace hladu v čase\n"
                "`/profile-admin-hp/mana/fury/vliv` — Nastav staty hráče\n"
                "`/rep create/add/set/delete` — Správa reputace frakcí\n"
                "`/inv-db-add/edit/find/list` — Databáze itemů\n"
                "`/inv-admin-add/remove/slots` — Inventář hráčů\n"
                "`/quest add/status/remove` — Správa questů\n"
                "`/rp info/remove` — Přehled RP místností\n"
                "`/combat_sethp/setdef/remove/setorder` — Combat admin\n"
                "`/gshop create/edit/close` — Správa shopu\n"
                "`/gadd` `/gremove` — Zlato hráčům\n"
                "`/tournament add/remove` — Správa turnaje\n"
                "`/admin-tutorial-reset` — Reset tutoriálu hráče\n"
                "`/memory admin` — Správa vzpomínek hráčů"
            ),
            inline=False
        )
        embed.add_field(
            name="🔗 Kód & Spolupráce",
            value=(
                "ArionBot je open source!\n"
                "[github.com/kroducek/Arion](https://github.com/kroducek/Arion)"
            ),
            inline=False
        )
        embed.set_footer(text="Arion tě provází světem Aurionis | Act II")
        await interaction.response.send_message(embed=embed)

    # --- VYVOLENÍ (Seznam postav) ---

    vyvoleni_group = app_commands.Group(name="vyvoleni", description="Seznam vyvolených dobrodruhů")

    @vyvoleni_group.command(name="list", description="Zobrazí všechny zaregistrované postavy")
    async def vyvoleni_list(self, interaction: discord.Interaction):
        import json
        from src.utils.paths import PROFILES as DATA_FILE
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
        players = _load_tournament()
        if players:
            lines = []
            for entry in players:
                # entry může být string (jméno) nebo int (Discord user ID)
                if isinstance(entry, int) or (isinstance(entry, str) and entry.isdigit()):
                    lines.append(f"• <@{int(entry)}>")
                else:
                    lines.append(f"• {entry}")
            players_list = "\n".join(lines)
        else:
            players_list = "• Zatím nikdo..."

        embed = discord.Embed(
            title="✨ Turnaj Hvězdy — druhé kolo",
            description="**Vyvolení, kteří postoupili do druhého kola:**",
            color=0xFFD700
        )
        embed.add_field(name=f"Postupující ({len(players)})", value=players_list, inline=False)
        embed.set_footer(text="Arion bedlivě sleduje Turnaj o Krále hvězdy")
        await interaction.response.send_message(embed=embed)

    @tournament_group.command(name="add", description="[ADMIN] Přidá hráče nebo jméno do turnaje")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        jmeno="Jméno NPC nebo vlastní text",
        hrac="Discord hráč (volitelné — místo jména)"
    )
    async def tournament_add(
        self,
        interaction: discord.Interaction,
        jmeno: str = None,
        hrac: discord.Member = None,
    ):
        if not jmeno and not hrac:
            await interaction.response.send_message("Zadej jméno nebo vyber hráče.", ephemeral=True)
            return

        players = _load_tournament()
        entry   = str(hrac.id) if hrac else jmeno
        label   = hrac.display_name if hrac else jmeno

        if entry in players or (hrac and str(hrac.id) in [str(p) for p in players]):
            await interaction.response.send_message(
                f"🐾 *Mňau?* `{label}` už v kronice zapsaného mám!", ephemeral=True
            )
            return

        players.append(entry)
        _save_tournament(players)
        await interaction.response.send_message(
            f"✅ *Arion zapsala nové jméno do kroniky.* `{label}` postoupil/a do druhého kola!"
        )

    @tournament_group.command(name="remove", description="[ADMIN] Odebere hráče nebo jméno z turnaje")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        jmeno="Jméno NPC nebo vlastní text",
        hrac="Discord hráč (volitelné)"
    )
    async def tournament_remove(
        self,
        interaction: discord.Interaction,
        jmeno: str = None,
        hrac: discord.Member = None,
    ):
        if not jmeno and not hrac:
            await interaction.response.send_message("Zadej jméno nebo vyber hráče.", ephemeral=True)
            return

        players = _load_tournament()
        entry   = str(hrac.id) if hrac else jmeno
        label   = hrac.display_name if hrac else jmeno

        # Hledej v seznamu jako string nebo int
        match = None
        for p in players:
            if str(p) == str(entry):
                match = p
                break

        if match is None:
            await interaction.response.send_message(
                f"🐾 *Mňau?* `{label}` v mém seznamu není.", ephemeral=True
            )
            return

        players.remove(match)
        _save_tournament(players)
        await interaction.response.send_message(
            f"❌ *Arion přemázla jméno tlapkou.* `{label}` byl/a z turnaje vyřazen/a."
        )

    @tournament_add.error
    @tournament_remove.error
    async def tournament_admin_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Nemáš oprávnění spravovat turnaj.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Aurionis(bot))