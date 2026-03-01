import discord
from discord.ext import commands
from discord import app_commands
import json
import os

# --- KONFIGURACE ---
ROLE_VYVOLENY_ID = 11476045900781588641  
ROLE_DOBRODRUH_F3_ID = 1476056192643104768 
URL_PLAKAT_HVEZDA = "https://i.ibb.co/XfdJxKNF/AURIONIS.jpg"
DATA_FILE = "profiles.json"

# --- POMOCNA FUNKCE PRO DATABAZI ---
def update_profile(user_id, **kwargs):
    user_id = str(user_id)
    data = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            data = {}

    if user_id not in data:
        data[user_id] = {"rank": "F3"}
    
    for key, value in kwargs.items():
        data[user_id][key] = value

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# --- POMOCNA FUNKCE PRO VSTUP DO LUMENIE ---
async def vstoupit_do_lumenie(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🏰 Brána do Lumenie",
        description=(
            "Světlo co tě oslepilo zmizí a ty se objevíš v **Lumenii** --\n"
            "Město začátku kde začínal každý slavný dobrodruh.\n\n"
            "Stojíš před cechem dobrodruhů.. proč tě světlo vyhodilo zrovna tady? "
            "Uvnitř panuje příjemný hluk, smích a hádky v jednom.\n\n"
            "**Recepce**\n"
            "Za pultem sedí tvor, kterého jsi pravděpodobně nečekal. Kočička s bronzovou srstí. "
            "Má pronikavé modré oči a na hlavě magický klobouk. Nadnáší se nad tlustou, živoucí knihou a líně na tebe mrkne.\n\n"
            "*'Arion'* vyhrkne dřív než stačíš otevřít ústa *'To jsem já.. A ty jsi?'*"
        ),
        color=0x3498db
    )
    view = GuildEntranceView()
    await interaction.response.edit_message(embed=embed, view=view)


class Onboarding(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup_tutorial", description="Spusti uvodni tutorial Aurionisu")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_tutorial(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="\u2728 Volání Hvězdy",
            description=(
                "*Ticho a prázdno.. jsi ve své mysli? Nebo putuješ nekonečným vesmírem..*\n\n"
                "Přemítáš o tom co je pro tebe realita. A pak tě oslepí jasné světlo\n\n"
                "**'Zdravím tě, Vyvolený...'**"
            ),
            color=0xFFD700
        )
        embed.set_image(url=URL_PLAKAT_HVEZDA)
        
        view = TutorialPartOneView()
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("Brána do Actu II byla vztyčena", ephemeral=True)


class TutorialPartOneView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Naslouchat hlasu", style=discord.ButtonStyle.primary, emoji="\u2728")
    async def listen(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🌌 Aurionis: Act II",
            description=(
                "Svet se mění pod tíhou nových zkoušek\n\n"
                "**Turnaj Hvězdy** byl vyhlášen a jeho vítěz si může přát cokoliv. "
                "Mocní se pohybuji ve stínech, slabí mizí beze stopy. "
                "Ti, kdo jsou zvaní **Vyvolenými**, stojí na rozhraní mezi oběma světy.\n\n"
                "*Pravda byla odhalena, ale jaká ta pravda vlastně je?*"
            ),
            color=0x2f3136
        )
        embed.add_field(
            name="❓ Než vstoupíš dál...",
            value="Byl jsi s námi od začátku nebo přicházíš jako nová tvar?"
        )
        
        view = ActSelectionView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ActSelectionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Znám příběh (Pokračovat)", style=discord.ButtonStyle.success, emoji="⚔️")
    async def old_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        await vstoupit_do_lumenie(interaction)

    @discord.ui.button(label="Chci recap Actu I.", style=discord.ButtonStyle.secondary, emoji="📖")
    async def new_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RecapView(page=1)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class RecapView(discord.ui.View):
    def __init__(self, page=1):
        super().__init__(timeout=600)
        self.page = page
        self._update_buttons()

    def _update_buttons(self):
        self.next_page.disabled = (self.page == 3)
        self.prev_page.disabled = (self.page == 1)

    def get_embed(self):
        if self.page == 1:
            embed = discord.Embed(title="👑 Kapitola I: Rozdělená koruna", color=0xe74c3c)
            embed.description = (
                "**Alice - právoplatná královna Kalexie**\n"
                "Odhalení jeji minulosti otřáslo zaklady Aurionisu. "
                "Krev starého rodu, dar dračí řeči a nárok na trůn, který nikdo nečekal.\n\n"
                "**Král Talias** jí odmítl. Nazval jí lhářkou a podvodnicí. "
                "Talias se připravuje na válku... a Aurionis čeká pod tíhou velkého turnaje"
            )
            return embed
        elif self.page == 2:
            embed = discord.Embed(title="🛡️ Kapitola II: Zrazená přísaha", color=0x3498db)
            embed.description = (
                "**Reinhardův pád?**\n"
                "Nejvyšší paladin. Symbol cti a řádu, člověk, kterému věří všichni.\n\n"
                "Zahodil insignii, odložil přísahu a vstoupil do Turnaje pro sebe. "
                "Stanu se králem hvězdy.. pro vás všechny. Pro Aurionis.\n\n"
                "Za ním zůstala práznota a obrana Kalexie v troskách."
            )
            return embed
        elif self.page == 3:
            embed = discord.Embed(title="🎭 Kapitola III: Vládce stínů", color=0x2c3e50)
            embed.description = (
                "**Muž jen si říká Vládce stínů, terorizuje svět svojí silou**\n"
                "Esenciální očistění vezme schopnosti, identitu i smysl existence.\n\n"
                "**Tragedie v Lumenii**\n"
                "Tisíce upírů přišly o svou podstatu během jediné noci. "
                "Město je plné uprchlíku, kteří ani nevědí kým jsou."
            )
            return embed

    @discord.ui.button(label="Zpět", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Dále", style=discord.ButtonStyle.secondary, emoji="➡️")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Chápu, přesun do Lumenie", style=discord.ButtonStyle.success, emoji="✅")
    async def finish_recap(self, interaction: discord.Interaction, button: discord.ui.Button):
        await vstoupit_do_lumenie(interaction)


class GuildEntranceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Odpovědět Arion", style=discord.ButtonStyle.primary, emoji="✍️")
    async def reply_arion(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NameRegistrationModal())


class NameRegistrationModal(discord.ui.Modal, title="Představení v cechu"):
    char_name = discord.ui.TextInput(
        label="Tvé jméno",
        placeholder="Jak se jmenuje tvá postava?",
        required=True,
        max_length=32
    )

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.char_name.value
        update_profile(interaction.user.id, name=new_name)
        try:
            await interaction.user.edit(nick=new_name)
        except:
            pass

        embed = discord.Embed(
            title="📜 Zápis do cechovní knihy",
            description=(
                f"'**{new_name}**?' Arion zvedne obočí,.. tedy pokud kočky obočí mají. "
                f"'Zajímave.. Mňau.. Budiž.'\n\n"
                "Tlapkou mávne vzduchem a pero se samo začne psat. Jméno se objeví na pergamenu zlatým inkoustem.\n\n"
                "*'Teď mi řekni ještě jednu věc'* pronese, aniž by zvedla oči "
                "*'Proč chceš být dobrodruhem?'*"
            ),
            color=0x2ecc71
        )
        await interaction.response.edit_message(embed=embed, view=MotivationView())


class MotivationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Odpovědět Arion", style=discord.ButtonStyle.primary, emoji="✍️")
    async def reply_motivation(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MotivationModal())


class MotivationModal(discord.ui.Modal, title="Tvá motivace"):
    motivation = discord.ui.TextInput(
        label="Proč chceš být dobrodruhem?",
        style=discord.TextStyle.paragraph,
        placeholder="Sláva, bohatství nebo něco hlubšiho?",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        motivation_text = self.motivation.value[:200]
        update_profile(interaction.user.id, motivation=motivation_text)

        embed = discord.Embed(
            title="🎖️ RANK Cechu Dobrodruhů\u016f",
            color=0x9b59b6
        )
        embed.description = (
            "Arion tě chvíli měří pohledem a pak pomalu přikývne.\n"
            "*'Zajímavé, uvidíme jestli to myslíš vážně.'*\n\n"
            "'Každý začíná na stejném místě. Rank **F3**. "
            "Odtud se dá jen stoupat pokud máš na to žaludek.'\n\n"
            "-# **F3** -> F2 -> F1 -> D3 -> D2 -> D1 -> ... -> **S+**"
        )
        embed.add_field(
            name="🖼️ Ještě jedna věc...",
            value="*'Můžu si tě nakreslit do arhivu? Miluju umění!?'*"
        )
        await interaction.response.edit_message(embed=embed, view=PortraitView())


class PortraitView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Uhm.. Tak jo? (nahrát URL)", style=discord.ButtonStyle.primary, emoji="🖼️")
    async def upload_portrait(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PortraitModal())

    @discord.ui.button(label="Ne (Pokračovat)", style=discord.ButtonStyle.secondary)
    async def skip_portrait(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finalize_registration(interaction)

    async def finalize_registration(self, interaction: discord.Interaction, portrait_url=None):
        role = interaction.guild.get_role(ROLE_DOBRODRUH_F3_ID)
        role_msg = ""
        if role:
            try:
                await interaction.user.add_roles(role)
                role_msg = f"\n\n🛡️ *Byla ti udělena role **{role.name}**.*"
            except:
                role_msg = "\n\n⚠️ *Roli se nepodarilo pridelit -- zkontroluj opravneni bota.*"

        embed = discord.Embed(
            title="✅ Vítej mezi dobrodruhy!",
            description=(
                "Arion spokojeně zamrská ocáskem a sklapne knihu.\n"
                f"'Hotovo. Jsi zapsán.'{role_msg}\n\n"
                "*Lumenie tě čeka. Snad neumřeš hned první den.*"
            ),
            color=0x2ecc71
        )
        if portrait_url:
            embed.set_image(url=portrait_url)
        
        await interaction.response.edit_message(content=None, embed=embed, view=None)


class PortraitModal(discord.ui.Modal, title="Portret postavy"):
    url = discord.ui.TextInput(
        label="Odkaz na obrazek (URL)",
        placeholder="Vloz URL obrazku...",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        update_profile(interaction.user.id, portrait_url=self.url.value)
        role = interaction.guild.get_role(ROLE_DOBRODRUH_F3_ID)
        if role:
            try:
                await interaction.user.add_roles(role)
            except:
                pass
        
        embed = discord.Embed(
            title="✅ Vítej mezi dobrodruhy!",
            description=(
                "Arion tě začne kreslit, vytvoří si magické plátno..\n"
                "'Da jí to zabrat jen malou chvilku..'\n\n"
                "*Děkuji za spolupráci.*\n\n"
                "Jsi zapsán. Lumenie tě čeka."
            ),
            color=0x2ecc71
        )
        embed.set_image(url=self.url.value)
        await interaction.response.edit_message(embed=embed, view=None)


async def setup(bot):
    await bot.add_cog(Onboarding(bot))