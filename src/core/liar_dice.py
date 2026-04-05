"""
Kostka lháře — Liar's Dice minihra pro ArionBot

Pravidla:
  • Každý hráč hází 5d6 — soukromě (DM nebo ephemeral tlačítko).
  • Střídáte se v tvrzeních: „Na stole je aspoň Nx čísloY."
  • „Vyšší" sázka = více kostek, NEBO stejný počet + vyšší číslo.
  • Akce: Vsadit / Zavolat Bluff.
  • Bluff: total < bid → sázející ztrácí kostku; total ≥ bid → volající ztrácí.
  • Kdo ztratí všechny kostky je vyřazen. Poslední přeživší vítězí + bere pot.
  • Pořadí se každé kolo rotuje (první jde na konec).
"""

import random
import discord
from discord.ext import commands
from discord import app_commands

from src.utils.json_utils import load_json, save_json
from src.utils.paths import (
    LIAR_SCORES  as SCORES_FILE,
    ECONOMY      as ECONOMY_FILE,
)

# ── Dice image (volitelné) ────────────────────────────────────────────────────
try:
    from src.utils.dice_image import build_dice_image
    DICE_IMAGES = True
except Exception:
    DICE_IMAGES = False

# ── Konstanty ─────────────────────────────────────────────────────────────────
MIN_PLAYERS  = 2
MAX_PLAYERS  = 6
INITIAL_DICE = 5
COIN         = "<:goldcoin:1490171741237018795>"

DICE_EMOJI = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}


# ══════════════════════════════════════════════════════════════════════════════
# DATA HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _load_scores() -> dict:    return load_json(SCORES_FILE)

def _save_scores(data: dict):  save_json(SCORES_FILE, data)

def _load_eco() -> dict:       return load_json(ECONOMY_FILE)

def _save_eco(data: dict):     save_json(ECONOMY_FILE, data)


# ══════════════════════════════════════════════════════════════════════════════
# HERNÍ HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _roll(n: int) -> list[int]:
    return [random.randint(1, 6) for _ in range(n)]

def _fmt_emoji(dice: list[int]) -> str:
    return " ".join(DICE_EMOJI[d] for d in sorted(dice))

def _active(game: dict) -> list[str]:
    return [u for u in game["players"] if game["dice_count"].get(u, 0) > 0]

def _count_face(game: dict, face: int) -> int:
    """Celkový počet kostek s hodnotou face u všech aktivních hráčů."""
    return sum(game["dice"].get(uid, []).count(face) for uid in _active(game))

def _bid_is_higher(new_count: int, new_face: int, prev: dict) -> bool:
    """
    Nová sázka je 'vyšší' pokud:
      • počet je vyšší (počet > prev_count), NEBO
      • stejný počet a vyšší číslo (počet == prev_count AND face > prev_face)
    """
    pc, pf = prev["count"], prev["face"]
    return new_count > pc or (new_count == pc and new_face > pf)

def _next_active_index(game: dict, from_index: int) -> int:
    n   = len(game["players"])
    idx = (from_index + 1) % n
    for _ in range(n):
        if game["dice_count"].get(game["players"][idx], 0) > 0:
            return idx
        idx = (idx + 1) % n
    return from_index



# ══════════════════════════════════════════════════════════════════════════════
# MODAL — zadání sázky
# ══════════════════════════════════════════════════════════════════════════════

class BidModal(discord.ui.Modal, title="Vsadit tvrzení"):
    count_in = discord.ui.TextInput(
        label="Počet kostek",
        placeholder="Kolik kusů? (číslo)",
        max_length=3,
    )
    face_in = discord.ui.TextInput(
        label="Číslo na kostce (1–6)",
        placeholder="Jaká hodnota? (1–6)",
        max_length=1,
    )

    def __init__(self, cog, channel_id: int):
        super().__init__()
        self.cog        = cog
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        game = self.cog.active_games.get(self.channel_id)
        if not game or game["phase"] != "bidding":
            await interaction.followup.send("Hra neprobíhá.", ephemeral=True)
            return

        uid = str(interaction.user.id)
        if uid != game["players"][game["turn_index"]]:
            await interaction.followup.send("Nejsi na tahu.", ephemeral=True)
            return

        try:
            count = int(self.count_in.value.strip())
            face  = int(self.face_in.value.strip())
        except ValueError:
            await interaction.followup.send("❌ Zadej platná čísla.", ephemeral=True)
            return

        if face < 1 or face > 6:
            await interaction.followup.send("❌ Číslo kostky musí být 1–6.", ephemeral=True)
            return
        if count < 1:
            await interaction.followup.send("❌ Počet musí být aspoň 1.", ephemeral=True)
            return

        prev = game.get("current_bid")
        if prev and not _bid_is_higher(count, face, prev):
            await interaction.followup.send(
                f"❌ Sázka musí být **vyšší** než předchozí "
                f"({prev['count']}× {DICE_EMOJI[prev['face']]} `{prev['face']}`).\n"
                f"Zvyš počet, nebo zachovej počet a zvyš číslo.",
                ephemeral=True,
            )
            return

        game["current_bid"]      = {"count": count, "face": face}
        game["last_bidder_uid"]  = uid
        game["turn_index"]       = _next_active_index(game, game["turn_index"])

        await interaction.followup.send("✅ Tvrzení zadáno!", ephemeral=True)
        channel = interaction.client.get_channel(self.channel_id)
        if channel:
            await self.cog._send_turn_embed(channel, game)


# ══════════════════════════════════════════════════════════════════════════════
# VIEW — akce na tahu
# ══════════════════════════════════════════════════════════════════════════════

class TurnView(discord.ui.View):
    def __init__(self, cog, channel_id: int, has_bid: bool):
        super().__init__(timeout=600)
        self.cog        = cog
        self.channel_id = channel_id

        if not has_bid:
            b = discord.ui.Button(
                label="🎲 Vsadit tvrzení",
                style=discord.ButtonStyle.primary,
                custom_id="ld_bid",
            )
            b.callback = self._bid_cb
            self.add_item(b)
        else:
            r = discord.ui.Button(
                label="⬆️ Navýšit tvrzení",
                style=discord.ButtonStyle.primary,
                custom_id="ld_raise",
            )
            r.callback = self._bid_cb
            self.add_item(r)

            bl = discord.ui.Button(
                label="🚨 Lžeš!",
                style=discord.ButtonStyle.danger,
                custom_id="ld_bluff",
            )
            bl.callback = self._bluff_cb
            self.add_item(bl)

            tr = discord.ui.Button(
                label="✅ Říkáš pravdu",
                style=discord.ButtonStyle.success,
                custom_id="ld_truth",
            )
            tr.callback = self._truth_cb
            self.add_item(tr)

        show = discord.ui.Button(
            label="👁 Moje kostky",
            style=discord.ButtonStyle.secondary,
            custom_id="ld_show",
        )
        show.callback = self._show_cb
        self.add_item(show)

    def _get_game_if_my_turn(self, interaction: discord.Interaction):
        """Synchronní check — vrátí game dict nebo None."""
        game = self.cog.active_games.get(self.channel_id)
        if not game:
            return None
        if str(interaction.user.id) != game["players"][game["turn_index"]]:
            return None
        return game

    async def _bid_cb(self, interaction: discord.Interaction):
        game = self._get_game_if_my_turn(interaction)
        if game is None:
            await interaction.response.send_message("Nejsi na tahu!", ephemeral=True)
            return
        await interaction.response.send_modal(BidModal(self.cog, self.channel_id))

    async def _bluff_cb(self, interaction: discord.Interaction):
        game = self._get_game_if_my_turn(interaction)
        if game is None:
            await interaction.response.send_message("Nejsi na tahu!", ephemeral=True)
            return
        if not game.get("current_bid"):
            await interaction.response.send_message("Není co zpochybňovat!", ephemeral=True)
            return
        await interaction.response.defer()
        self.stop()
        await self.cog._resolve_bluff(interaction.channel, game, str(interaction.user.id))

    async def _truth_cb(self, interaction: discord.Interaction):
        game = self._get_game_if_my_turn(interaction)
        if game is None:
            await interaction.response.send_message("Nejsi na tahu!", ephemeral=True)
            return
        if not game.get("current_bid"):
            await interaction.response.send_message("Není žádné aktivní tvrzení.", ephemeral=True)
            return
        await interaction.response.defer()
        self.stop()
        await self.cog._resolve_truth(interaction.channel, game, str(interaction.user.id))

    async def _show_cb(self, interaction: discord.Interaction):
        game = self.cog.active_games.get(self.channel_id)
        if not game:
            await interaction.response.send_message("Hra skončila.", ephemeral=True)
            return
        uid  = str(interaction.user.id)
        dice = game["dice"].get(uid)
        if not dice:
            await interaction.response.send_message("Nejsi v této hře nebo nemáš kostky.", ephemeral=True)
            return

        emoji_str = _fmt_emoji(dice)
        content   = (
            f"🎲 **Tvoje kostky:** {emoji_str}\n"
            f"-# {len(dice)} kostek  ·  vidíš jen ty"
        )
        if DICE_IMAGES:
            try:
                buf  = build_dice_image(sorted(dice))
                file = discord.File(buf, filename="kostky.png")
                await interaction.response.send_message(content=content, file=file, ephemeral=True)
                return
            except Exception:
                pass
        await interaction.response.send_message(content=content, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# LOBBY VIEW
# ══════════════════════════════════════════════════════════════════════════════

class LiarLobby(discord.ui.View):
    def __init__(self, cog, author: discord.Member, bet: int):
        super().__init__(timeout=None)
        self.cog       = cog
        self.author    = author
        self.bet       = bet
        self.players   = [author]
        self.paid: set[str] = set()

        # Autor platí hned
        if bet > 0:
            uid = str(author.id)
            eco = _load_eco()
            eco[uid] = eco.get(uid, 0) - bet
            _save_eco(eco)
            self.paid.add(uid)

    def _embed(self) -> discord.Embed:
        pot = self.bet * len(self.paid) if self.bet > 0 else 0
        embed = discord.Embed(
            title="🎲 Kostka lháře — Lobby",
            description=(
                "*Každý hráč hodí 5 kostkami v tajnosti. "
                "Tvrdíš, kolik kostek určité hodnoty leží na stole u všech hráčů "
                "dohromady — ale nevíš, co mají ostatní.*\n\n"
                "**Jak sázet výš:**\n"
                "▸ Zvýšit počet kostek (3×4 → 4×4)\n"
                "▸ Nebo stejný počet + vyšší číslo (3×4 → 3×5)\n\n"
                "**Lžeš!** — zpochybni poslední tvrzení:\n"
                "▸ Měl pravdu → ty ztrácíš kostku\n"
                "▸ Lhal → on ztrácí kostku\n\n"
                "Kdo ztratí všechny kostky, je vyřazen. Poslední přeživší vítězí."
            ),
            color=0xE74C3C,
        )
        names = "\n".join(f"• {p.display_name}" for p in self.players)
        embed.add_field(name=f"Hráči ({len(self.players)}/{MAX_PLAYERS})", value=names, inline=True)
        if self.bet > 0:
            embed.add_field(name="Sázka", value=f"{self.bet} {COIN} každý", inline=True)
            embed.add_field(name="Pot",   value=f"{pot} {COIN}", inline=True)
        embed.set_footer(text=f"Min. {MIN_PLAYERS} hráči  ·  kostky si zobrazíš tlačítkem 👁 Moje kostky")
        return embed

    @discord.ui.button(label="Připojit se", style=discord.ButtonStyle.success, custom_id="ld_join")
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in [p.id for p in self.players]:
            await interaction.response.send_message("Už jsi v lobby!", ephemeral=True)
            return
        if len(self.players) >= MAX_PLAYERS:
            await interaction.response.send_message(f"Lobby je plné ({MAX_PLAYERS}).", ephemeral=True)
            return

        uid = str(interaction.user.id)
        if self.bet > 0:
            eco = _load_eco()
            if eco.get(uid, 0) < self.bet:
                await interaction.response.send_message(
                    f"❌ Nemáš dost zlaťáků! Potřebuješ **{self.bet}** {COIN}.", ephemeral=True
                )
                return
            eco[uid] = eco.get(uid, 0) - self.bet
            _save_eco(eco)
            self.paid.add(uid)

        self.players.append(interaction.user)
        await interaction.response.edit_message(embed=self._embed())

    @discord.ui.button(label="Odejít", style=discord.ButtonStyle.secondary, custom_id="ld_leave")
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.author.id:
            await interaction.response.send_message("Zakladatel nemůže odejít. Použij Zrušit.", ephemeral=True)
            return
        if interaction.user.id not in [p.id for p in self.players]:
            await interaction.response.send_message("Nejsi v lobby.", ephemeral=True)
            return

        uid = str(interaction.user.id)
        if self.bet > 0 and uid in self.paid:
            eco = _load_eco()
            eco[uid] = eco.get(uid, 0) + self.bet
            _save_eco(eco)
            self.paid.discard(uid)

        self.players = [p for p in self.players if p.id != interaction.user.id]
        await interaction.response.edit_message(embed=self._embed())

    @discord.ui.button(label="▶ Start", style=discord.ButtonStyle.primary, custom_id="ld_start")
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Pouze zakladatel může spustit hru!", ephemeral=True)
            return
        if len(self.players) < MIN_PLAYERS:
            await interaction.response.send_message(f"Potřebuješ aspoň {MIN_PLAYERS} hráče!", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(
            content="🎲 **Kostka lháře** — Hra začíná!", embed=None, view=None
        )
        pot = self.bet * len(self.paid)
        await self.cog._start_game(interaction.channel, self.players, self.bet, pot)

    @discord.ui.button(label="🚫 Zrušit", style=discord.ButtonStyle.danger, custom_id="ld_cancel_lobby")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Pouze zakladatel nebo admin.", ephemeral=True)
            return
        if self.bet > 0 and self.paid:
            eco = _load_eco()
            for uid in self.paid:
                eco[uid] = eco.get(uid, 0) + self.bet
            _save_eco(eco)
        self.stop()
        await interaction.response.edit_message(content="🚫 Lobby zrušeno. Sázky vráceny.", embed=None, view=None)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN COG
# ══════════════════════════════════════════════════════════════════════════════

class LiarDiceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot          = bot
        self.active_games: dict = {}

    # ── Start hry ────────────────────────────────────────────────────────────

    async def _start_game(self, channel: discord.TextChannel,
                          players: list[discord.Member], bet: int, pot: int):
        random.shuffle(players)
        uids = [str(p.id) for p in players]

        game = {
            "phase":           "bidding",
            "players":         uids,
            "dice":            {},
            "dice_count":      {u: INITIAL_DICE for u in uids},
            "current_bid":     None,
            "last_bidder_uid": None,
            "turn_index":      0,
            "round":           0,
            "bet":             bet,
            "pot":             pot,
        }
        self.active_games[channel.id] = game
        await self._begin_round(channel, game)

    # ── Kolo ─────────────────────────────────────────────────────────────────

    async def _begin_round(self, channel: discord.TextChannel, game: dict):
        game["round"] += 1

        # Rotace pořadí od druhého kola
        if game["round"] > 1:
            game["players"] = game["players"][1:] + [game["players"][0]]

        # Nastav první index na aktivního hráče
        for i, uid in enumerate(game["players"]):
            if game["dice_count"].get(uid, 0) > 0:
                game["turn_index"] = i
                break

        # Hod kostek
        for uid in _active(game):
            game["dice"][uid] = _roll(game["dice_count"][uid])

        game["current_bid"]     = None
        game["last_bidder_uid"] = None
        game["phase"]           = "bidding"

        await self._send_turn_embed(channel, game)

    # ── Turn embed ───────────────────────────────────────────────────────────

    async def _send_turn_embed(self, channel: discord.TextChannel, game: dict):
        current_uid    = game["players"][game["turn_index"]]
        current_member = channel.guild.get_member(int(current_uid))
        bid            = game.get("current_bid")

        embed = discord.Embed(
            title=f"🎲 Kostka lháře — Kolo {game['round']}",
            color=0xE74C3C,
        )

        lines = []
        for uid in game["players"]:
            m     = channel.guild.get_member(int(uid))
            name  = m.display_name if m else uid
            count = game["dice_count"].get(uid, 0)
            if count == 0:
                lines.append(f"~~{name}~~ 💀")
            else:
                arrow = "▶️ " if uid == current_uid else "\u00a0\u00a0\u00a0"
                lines.append(f"{arrow}**{name}** {'🎲' * count} `{count}`")

        embed.add_field(name="Hráči", value="\n".join(lines), inline=False)

        if bid:
            bidder      = channel.guild.get_member(int(game["last_bidder_uid"]))
            bidder_name = bidder.display_name if bidder else "?"
            fe          = DICE_EMOJI[bid["face"]]
            embed.add_field(
                name="Aktuální tvrzení",
                value=f"**{bid['count']}×** {fe} `{bid['face']}`\n— vsadil/a **{bidder_name}**",
                inline=True,
            )
        else:
            embed.add_field(name="Aktuální tvrzení", value="*(začátek kola)*", inline=True)

        mention = current_member.mention if current_member else current_uid
        embed.add_field(name="Na tahu", value=f"➡️ {mention}", inline=True)

        if game["bet"] > 0:
            embed.add_field(name="Pot", value=f"{game['pot']} {COIN}", inline=True)

        total = sum(game["dice_count"].get(u, 0) for u in _active(game))
        embed.set_footer(text=f"Celkem kostek na stole: {total}  ·  👁 Moje kostky = zobrazí tvé kostky")

        view = TurnView(self, channel.id, bid is not None)
        await channel.send(embed=embed, view=view)

    # ── Bluff ────────────────────────────────────────────────────────────────

    async def _resolve_bluff(self, channel: discord.TextChannel, game: dict, caller_uid: str):
        bid   = game["current_bid"]
        face  = bid["face"]
        total = _count_face(game, face)
        fe    = DICE_EMOJI[face]

        reveal_lines = self._build_reveal_lines(channel, game, face)
        was_bluff    = total < bid["count"]

        if was_bluff:
            loser_uid    = game["last_bidder_uid"]
            result_text  = (
                f"💥 **LHANÍ ODHALENO!** Na stole bylo jen **{total}×** {fe}, "
                f"ale tvrzení bylo **{bid['count']}×**.\n"
                f"Sázející ztrácí kostku."
            )
            color = 0x2ECC71
        else:
            loser_uid    = caller_uid
            result_text  = (
                f"✅ **PRAVDA!** Na stole bylo **{total}×** {fe} "
                f"(≥ tvrzených {bid['count']}×).\n"
                f"Volající ztrácí kostku."
            )
            color = 0xE74C3C

        embed = discord.Embed(
            title="🎲 Odhalení kostek",
            description="\n".join(reveal_lines),
            color=color,
        )
        embed.add_field(name="Výsledek", value=result_text, inline=False)
        await channel.send(embed=embed)

        await self._process_loss(channel, game, [loser_uid])

    # ── Pravda ───────────────────────────────────────────────────────────────

    async def _resolve_truth(self, channel: discord.TextChannel, game: dict, caller_uid: str):
        bid   = game["current_bid"]
        face  = bid["face"]
        total = _count_face(game, face)
        fe    = DICE_EMOJI[face]

        reveal_lines = self._build_reveal_lines(channel, game, face)
        exact = total == bid["count"]

        if exact:
            caller      = channel.guild.get_member(int(caller_uid))
            caller_name = caller.display_name if caller else caller_uid
            result_text = (
                f"🎯 **PŘESNĚ!** Na stole bylo přesně **{total}×** {fe}.\n"
                f"**{caller_name}** měl/a pravdu — všichni ostatní ztrácí kostku."
            )
            color      = 0x2ECC71
            loser_uids = [u for u in _active(game) if u != caller_uid]
        else:
            result_text = (
                f"❌ **ŠPATNĚ!** Na stole bylo **{total}×** {fe}, "
                f"tvrzení bylo **{bid['count']}×** — nesedí přesně.\n"
                f"Volající ztrácí kostku."
            )
            color      = 0xE74C3C
            loser_uids = [caller_uid]

        embed = discord.Embed(
            title="🎲 Odhalení kostek",
            description="\n".join(reveal_lines),
            color=color,
        )
        embed.add_field(name="Výsledek", value=result_text, inline=False)
        await channel.send(embed=embed)

        await self._process_loss(channel, game, loser_uids)

    # ── Ztráta kostky / konec ─────────────────────────────────────────────────

    async def _process_loss(self, channel: discord.TextChannel, game: dict, loser_uids: list[str]):
        lines = []
        for uid in loser_uids:
            game["dice_count"][uid] = max(0, game["dice_count"].get(uid, 0) - 1)
            m    = channel.guild.get_member(int(uid))
            name = m.display_name if m else uid
            left = game["dice_count"][uid]
            if left == 0:
                lines.append(f"💀 **{name}** přišel/přišla o poslední kostku — **vyřazen/a!**")
            else:
                lines.append(f"🎲 **{name}** má teď `{left}` kostek.")

        if lines:
            await channel.send("\n".join(lines))

        active = _active(game)
        if len(active) <= 1:
            winner_uid = active[0] if active else None
            await self._end_game(channel, game, winner_uid)
        else:
            await self._begin_round(channel, game)

    # ── Konec hry ────────────────────────────────────────────────────────────

    async def _end_game(self, channel: discord.TextChannel, game: dict, winner_uid: str | None):
        pot = game.get("pot", 0)

        if winner_uid:
            member = channel.guild.get_member(int(winner_uid))
            name   = member.display_name if member else winner_uid

            scores             = _load_scores()
            scores[winner_uid] = scores.get(winner_uid, 0) + 1
            _save_scores(scores)

            if pot > 0:
                eco = _load_eco()
                eco[winner_uid] = eco.get(winner_uid, 0) + pot
                _save_eco(eco)

            desc = (
                f"**{name}** přežil/a jako poslední a vyhrál/a Kostku lháře!\n"
                f"Celková vítězství: **{scores[winner_uid]}**"
            )
            if pot > 0:
                desc += f"\n🏆 Výhra: **{pot}** {COIN}"
            color  = 0xF1C40F
            thumb  = member.display_avatar.url if member else None
        else:
            desc  = "Všichni hráči byli vyřazeni najednou — remíza! Sázky zůstávají v potu."
            color = 0x95A5A6
            thumb = None

        del self.active_games[channel.id]

        embed = discord.Embed(title="🏆 Konec hry!", description=desc, color=color)
        if thumb:
            embed.set_thumbnail(url=thumb)
        await channel.send(embed=embed)

    # ── Utility ──────────────────────────────────────────────────────────────

    def _build_reveal_lines(self, channel: discord.TextChannel,
                             game: dict, face: int) -> list[str]:
        fe    = DICE_EMOJI[face]
        lines = []
        for uid in _active(game):
            m        = channel.guild.get_member(int(uid))
            name     = m.display_name if m else uid
            dice     = game["dice"].get(uid, [])
            exact   = dice.count(face)
            emoji_s = _fmt_emoji(dice)
            lines.append(f"**{name}**: {emoji_s}  →  {exact}× {fe}")
        return lines

    # ══════════════════════════════════════════════════════════════════════════
    # SLASH PŘÍKAZY
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="liar_dice", description="Zahájí Kostku lháře (Liar's Dice)")
    @app_commands.describe(sazka="Sázka v zlaťácích (0 = bez sázky)")
    async def cmd_start(self, interaction: discord.Interaction, sazka: int = 0):
        if interaction.channel.id in self.active_games:
            await interaction.response.send_message("Tady už jedna hra běží!", ephemeral=True)
            return
        if sazka < 0:
            await interaction.response.send_message("Sázka nesmí být záporná.", ephemeral=True)
            return
        if sazka > 0:
            uid = str(interaction.user.id)
            eco = _load_eco()
            if eco.get(uid, 0) < sazka:
                await interaction.response.send_message(
                    f"❌ Nemáš dost zlaťáků! Potřebuješ **{sazka}** {COIN}.", ephemeral=True
                )
                return

        view = LiarLobby(self, interaction.user, sazka)
        await interaction.response.send_message(embed=view._embed(), view=view)

    @app_commands.command(name="liar_cancel", description="[Admin] Zruší probíhající Kostku lháře")
    async def cmd_cancel(self, interaction: discord.Interaction):
        if interaction.channel.id not in self.active_games:
            await interaction.response.send_message("Žádná hra neběží.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Pouze admin může zrušit hru.", ephemeral=True)
            return
        del self.active_games[interaction.channel.id]
        await interaction.response.send_message("🛑 Hra zrušena.")

    @app_commands.command(name="liar_leaderboard", description="Žebříček vítězů Kostky lháře")
    async def cmd_leaderboard(self, interaction: discord.Interaction):
        scores = _load_scores()
        if not scores:
            await interaction.response.send_message("Zatím nikdo nevyhrál.", ephemeral=True)
            return

        sorted_s = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        medals   = ["🥇", "🥈", "🥉"]
        lines    = []
        for i, (uid, wins) in enumerate(sorted_s[:10]):
            medal  = medals[i] if i < 3 else f"`{i + 1}.`"
            member = interaction.guild.get_member(int(uid))
            name   = member.display_name if member else f"<@{uid}>"
            w      = "výhra" if wins == 1 else "výher"
            lines.append(f"{medal} **{name}** — {wins} {w}")

        embed = discord.Embed(
            title="🏆 Kostka lháře — Žebříček",
            description="\n".join(lines),
            color=0xF1C40F,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(LiarDiceCog(bot))
