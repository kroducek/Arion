"""Sběratelský systém karet pro ArionBot."""

import discord
import os
import uuid
import random
import string
import math
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timedelta
from discord.ext import commands
from discord import app_commands
import asyncio
from functools import partial
from src.utils.paths import CARDS_DIR, CARDS_DATA, CARDS_INVENTORY, CARDS_FRAMES, FRAMES_INVENTORY, data as _data
from src.core.cards.card_image import apply_frame_to_card
from src.core.cards.card_render import render_card_showcase, render_album_grid
from src.utils.json_utils import load_json, save_json
from src.utils.embeds import create_error_embed
from src.logic.profile import load_data as profile_load, save_data as profile_save
from src.logic.inventory import _load_profiles as inv_load, _save_profiles as inv_save
from src.logic.economy import _load_economy as load_economy, _save_economy as save_economy, add_balance
from src.core.dnd.achievements import grant_achievement, announce_achievement, has_achievement
from src.utils.admin_gate import admin_only

CARDS_WORK = _data("cards_work.json")
CARDS_REBORN_STATE = _data("cards_reborn_state")
# ---------------------------------------------------------------------------
# Konstanty
# ---------------------------------------------------------------------------

# Jednotná fialová pro obecné/dekorativní embedy (přehledy, potvrzení, hlavičky).
# Rarity/kolekce/bedny/rámečky si nechávají svou vlastní barvu — ta nese význam.
BRAND_PURPLE = 0x9B59B6

from src.core.cards.card_rules import (
    RARITIES, QUALITIES, DUST_VALUES, QUALITY_MULTIPLIERS,
    RARITY_ORDER, QUALITY_ORDER, roll_rarity, roll_quality, migrate_qualities,
    rarity_chances,
)


# ---------------------------------------------------------------------------
# Sdílená logika pro spálení karty (/cards burn i tlačítko Spálit po summonu)
# ---------------------------------------------------------------------------

class BurnError(Exception):
    """Základ pro chyby při pokusu spálit kartu."""


class CardNotFoundError(BurnError):
    """Karta s daným ID neexistuje v inventáři."""


class NotCardOwnerError(BurnError):
    """Karta nepatří hráči, který ji zkouší spálit."""


class CardOnExpeditionError(BurnError):
    """Karta je momentálně na výpravě, nejde spálit."""


def calculate_dust(rarity: str, quality: str) -> int:
    """Spočítá, kolik Hvězdného prachu karta dá při spálení — čím vyšší rarita a kvalita, tím víc."""
    base_dust = DUST_VALUES.get(rarity, 1)
    mult = QUALITY_MULTIPLIERS.get(quality, 1.0)
    return max(1, int(base_dust * mult))


def burn_card_by_id(uid: str, unique_id: str) -> dict:
    """
    Spálí kartu hráče a připíše mu Hvězdný prach. Vrací
    {"name", "rarity", "quality", "dust"}. Vyhazuje CardNotFoundError,
    NotCardOwnerError nebo CardOnExpeditionError podle situace.
    """
    inv = load_inventory()
    if unique_id not in inv:
        raise CardNotFoundError(unique_id)

    card = inv[unique_id]
    if card.get("owner_id") != uid:
        raise NotCardOwnerError(unique_id)

    works = load_json(CARDS_WORK, default={})
    user_work = works.get(uid)
    if user_work and unique_id in user_work.get("cards", []):
        raise CardOnExpeditionError(unique_id)

    # Odstraň z profilu, pokud je aktivní
    profiles = profile_load()
    if uid in profiles and profiles[uid].get("active_card_id") == unique_id:
        profiles[uid]["active_card_id"] = None
        profile_save(profiles)

    rarity = card.get("rarity", "uncommon")
    quality = card.get("quality", "normal")
    total_dust = calculate_dust(rarity, quality)
    card_name = card.get("name", unique_id)

    add_balance(uid, total_dust, "stardust")

    del inv[unique_id]
    save_json(CARDS_INVENTORY, inv)

    return {"name": card_name, "rarity": rarity, "quality": quality, "dust": total_dust}


class KeepBurnView(discord.ui.View):
    """
    Tlačítka Nechat / Spálit zobrazená pod čerstvě summonovanou kartou.
    Bez odpovědi do timeoutu se karta jednoduše nechává (bezpečný default).
    """

    def __init__(self, uid: str, unique_id: str, card: dict, timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.uid = uid
        self.unique_id = unique_id
        self.card = card
        self.message: Optional[discord.Message] = None

        dust = calculate_dust(card.get("rarity", "uncommon"), card.get("quality", "normal"))
        self.burn_button.label = f"Spálit (+{dust} ✨)"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message(
                "Tohle rozhodnutí je jen na majiteli karty.", ephemeral=True
            )
            return False
        return True

    async def _lock(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="🎒 Nechat", style=discord.ButtonStyle.success)
    async def keep_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._lock(interaction)
        await interaction.followup.send(
            f"🎒 **{self.card.get('name')}** zůstává ve tvém inventáři.", ephemeral=True
        )

    @discord.ui.button(label="🔥 Spálit", style=discord.ButtonStyle.danger)
    async def burn_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._lock(interaction)
        try:
            result = burn_card_by_id(self.uid, self.unique_id)
        except CardNotFoundError:
            await interaction.followup.send("❌ Karta už mezitím zmizela z inventáře.", ephemeral=True)
            return
        except NotCardOwnerError:
            await interaction.followup.send("❌ Tahle karta ti nepatří.", ephemeral=True)
            return
        except CardOnExpeditionError:
            await interaction.followup.send("❌ Karta je momentálně na výpravě, nejde spálit.", ephemeral=True)
            return

        await interaction.followup.send(
            f"🔥 **{result['name']}** spálena za **{result['dust']}× Hvězdný prach ✨**.",
            ephemeral=True,
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


# ---------------------------------------------------------------------------
# Obchod mezi hráči (/cards trade) — obě strany musí potvrdit najednou
# ---------------------------------------------------------------------------

TRADE_MAX_CARDS = 15
TRADE_TIMEOUT = 600.0  # 10 minut na sestavení a potvrzení obchodu


def _parse_trade_card_ids(raw: str) -> list:
    """Rozparsuje čárkou oddělený seznam ID karet — ořízne mezery, odstraní duplicity."""
    seen = []
    for part in raw.split(","):
        cid = part.strip()
        if cid and cid not in seen:
            seen.append(cid)
    return seen


def _resolve_trade_cards(owner_uid: str, unique_ids: list) -> Tuple[dict, list]:
    """
    Ověří vlastnictví a obchodovatelnost karet.
    Vrací (platné {unique_id: card}, chybové řádky pro neplatné).
    """
    inv = load_inventory()
    works = load_json(CARDS_WORK, default={})
    user_work = works.get(owner_uid)
    on_expedition = set(user_work.get("cards", [])) if user_work else set()

    valid = {}
    errors = []
    for cid in unique_ids:
        card = inv.get(cid)
        if card is None:
            errors.append(f"`{cid}` — neexistuje.")
        elif card.get("owner_id") != owner_uid:
            errors.append(f"`{cid}` — není tvoje.")
        elif cid in on_expedition:
            errors.append(f"`{cid}` — je na výpravě, nejde obchodovat.")
        else:
            valid[cid] = card
    return valid, errors


class TradeView(discord.ui.View):
    """
    Obousměrný obchod — kdokoliv z dvojice může přes `/cards trade` přidat
    nebo přepsat svou nabídku (protinabídka), i poté co druhá strana napsala
    jako první. Karty se reálně přepíšou, až obě strany klikněte na Potvrdit;
    jakákoliv změna nabídky obě potvrzení zruší. Kdokoliv může obchod kdykoliv
    zrušit. Bez odezvy do timeoutu se nic nepřesune.
    """

    def __init__(self, cog: "Cards", key: frozenset,
                 first_user: discord.abc.User, second_user: discord.abc.User,
                 first_cards: dict, timeout: float = TRADE_TIMEOUT):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.key = key
        self.users = {first_user.id: first_user, second_user.id: second_user}
        self.offers = {first_user.id: first_cards, second_user.id: {}}
        self.confirmed = {first_user.id: False, second_user.id: False}
        self.done = False
        self.message: Optional[discord.Message] = None

    def other_id(self, uid: int) -> int:
        return next(u for u in self.users if u != uid)

    def set_offer(self, uid: int, cards: dict):
        """Nastaví/přepíše nabídku hráče a zruší obě potvrzení — podmínky se změnily."""
        self.offers[uid] = cards
        for u in self.confirmed:
            self.confirmed[u] = False

    def build_embed(self, *, note: str = None, color: int = BRAND_PURPLE) -> discord.Embed:
        embed = discord.Embed(title="🤝 Obchod mezi hráči", color=color)
        for uid, user in self.users.items():
            cards = self.offers[uid]
            if cards:
                lines = []
                for cid, card in cards.items():
                    rarity = card.get("rarity", "uncommon")
                    rarity_emoji = RARITIES.get(rarity, RARITIES["uncommon"])["emoji"]
                    qual = card.get("quality", "normal")
                    qual_emoji = QUALITIES.get(qual, QUALITIES["normal"])["emoji"]
                    lines.append(
                        f"{rarity_emoji}{qual_emoji} **{card.get('name', '?')}** "
                        f"*(#{card.get('print_number', '?')})* — `{cid}`"
                    )
                value = "\n".join(lines)
            else:
                value = "*(zatím nic nenabídl/a)*"
            embed.add_field(name=f"Nabídka — {user.display_name}", value=value, inline=False)

        embed.add_field(
            name="Potvrzení",
            value="\n".join(
                f"{'✅' if self.confirmed[uid] else '⬜'} {user.display_name}"
                for uid, user in self.users.items()
            ),
            inline=False,
        )
        embed.set_footer(
            text=note or (
                "Kdokoliv může přidat/upravit nabídku přes `/cards trade` — "
                "obě strany pak musí znovu potvrdit."
            )
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.users:
            await interaction.response.send_message("Tohle není tvůj obchod.", ephemeral=True)
            return False
        return True

    async def _finish(self, interaction: discord.Interaction, embed: discord.Embed):
        for child in self.children:
            child.disabled = True
        self.done = True
        self.cog.active_trades.pop(self.key, None)
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="✅ Potvrdit", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed[interaction.user.id] = True

        if not all(self.confirmed.values()):
            await interaction.response.edit_message(embed=self.build_embed())
            return

        # Obě strany potvrdily — než se karty reálně přepíšou, ověř znovu obě
        # nabídky (mezitím mohla karta zmizet / jít na výpravu / být spálena).
        errors = []
        revalidated = {}
        for uid, cards in self.offers.items():
            valid, uid_errors = _resolve_trade_cards(str(uid), list(cards.keys()))
            revalidated[uid] = valid
            errors.extend(uid_errors)

        if errors:
            embed = self.build_embed(
                note="Obchod zrušen — některé karty už nejsou dostupné.", color=0xE74C3C,
            )
            embed.add_field(name="⚠️ Problém", value="\n".join(errors), inline=False)
            await self._finish(interaction, embed)
            return

        inv = load_inventory()
        profiles = profile_load()
        profiles_changed = False

        for uid, cards in revalidated.items():
            if not cards:
                continue
            recipient_uid = str(self.other_id(uid))
            owner_uid = str(uid)
            owner_profile = profiles.get(owner_uid)
            for cid in cards:
                inv[cid]["owner_id"] = recipient_uid
                if owner_profile and owner_profile.get("active_card_id") == cid:
                    owner_profile["active_card_id"] = None
                    profiles_changed = True

        save_json(CARDS_INVENTORY, inv)
        if profiles_changed:
            profile_save(profiles)

        embed = self.build_embed(note="✅ Obchod dokončen!", color=0x2ECC71)
        await self._finish(interaction, embed)

        for uid in self.offers:
            member = interaction.guild.get_member(int(uid)) if interaction.guild else None
            await check_collection_achievement(member, interaction.channel, inv)

    @discord.ui.button(label="❌ Zrušit", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = self.build_embed(
            note=f"❌ Obchod zrušil/a {interaction.user.display_name}.", color=BRAND_PURPLE,
        )
        await self._finish(interaction, embed)

    async def on_timeout(self):
        if self.done:
            return
        self.cog.active_trades.pop(self.key, None)
        for child in self.children:
            child.disabled = True
        if self.message:
            embed = self.build_embed(note="⌛ Obchod vypršel — nic se nepřesunulo.", color=BRAND_PURPLE)
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass


# ---------------------------------------------------------------------------
# Stránkování inventáře (/cards inventory)
# ---------------------------------------------------------------------------

INVENTORY_PAGE_SIZE = 10


def build_inventory_embed(target, sorted_cards: list, page: int, page_size: int = INVENTORY_PAGE_SIZE) -> discord.Embed:
    """Sestaví jednu stránku embedu inventáře pro daného hráče."""
    total = len(sorted_cards)
    total_pages = max(1, math.ceil(total / page_size))
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    chunk = sorted_cards[start:start + page_size]

    embed = discord.Embed(
        title=f"🎴 Karty — {target.display_name}",
        description=f"Celkem: **{total}** karet",
        color=BRAND_PURPLE,
    )
    for i, (unique_id, card) in enumerate(chunk, start=start + 1):
        rarity = card.get("rarity", "uncommon")
        rarity_emoji = RARITIES.get(rarity, RARITIES["uncommon"])["emoji"]
        qual = card.get("quality", "normal")
        qual_data = QUALITIES.get(qual, QUALITIES["normal"])
        frame_text = f"\nRámeček: {card['frame']}" if card.get("frame") else ""
        embed.add_field(
            name=f"{i}. {card.get('name', '?')} (Print #{card.get('print_number', '?')})",
            value=(
                f"ID: `{unique_id}`\n"
                f"Rarita: {rarity.capitalize()} {rarity_emoji}  ·  "
                f"Kvalita: {qual_data['emoji']} {qual_data['name']}"
                f"{frame_text}"
            ),
            inline=False,
        )
    if total_pages > 1:
        embed.set_footer(text=f"Stránka {page + 1}/{total_pages}")
    return embed


class InventoryPaginatorView(discord.ui.View):
    """Tlačítka ⬅️ / ➡️ pro procházení víc stránek inventáře."""

    def __init__(self, invoker_id: int, target, sorted_cards: list, page_size: int = INVENTORY_PAGE_SIZE, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.invoker_id = invoker_id
        self.target = target
        self.sorted_cards = sorted_cards
        self.page_size = page_size
        self.page = 0
        self.total_pages = max(1, math.ceil(len(sorted_cards) / page_size))
        self.message: Optional[discord.Message] = None
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.total_pages - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                "Stránkovat může jen ten, kdo příkaz spustil.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="⬅️ Předchozí", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(
            embed=build_inventory_embed(self.target, self.sorted_cards, self.page, self.page_size),
            view=self,
        )

    @discord.ui.button(label="Další ➡️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total_pages - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(
            embed=build_inventory_embed(self.target, self.sorted_cards, self.page, self.page_size),
            view=self,
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


EXPEDITIONS = {
    "hlidka": {"name": "Hlídka ve městě",      "reward":  5, "hours":  6, "emoji": "🛡️",  "description": "Střežení městských bran"},
    "tabor":  {"name": "Táborový kemp",       "reward":  8, "hours": 12, "emoji": "🏕️", "description": "Řídící tábor v pustině"},
    "lov":    {"name": "Lov monster",         "reward": 12, "hours": 20, "emoji": "🐺", "description": "Hon na nebezpečné bestie"},
    "gilda":  {"name": "Úkol pro gildu",      "reward": 20, "hours": 36, "emoji": "📜", "description": "Speciální úkol pro gildu"},
    "bitva":  {"name": "Velká bitva",         "reward": 35, "hours": 48, "emoji": "⚔️",  "description": "Cesta na válečné bojiště — vysoké riziko!"},
}

COLLECTIONS = {
    "unworthy": {"color": 0x2C2F33, "emoji": "💀", "description": "Nevolaní — padlí a zapomenutí"},
    "worthy":   {"color": 0x99AAB5, "emoji": "⚔️",  "description": "Hrdinové Aurionisu"},
    "queen":    {"color": 0xFF69B4, "emoji": "👑",  "description": "Královna a její dvůr"},
    "chosen":   {"color": 0xE74C3C, "emoji": "🔥",  "description": "Vyvolení — ti, jenž nesou osud"},
    "jesters":  {"color": 0x9B59B6, "emoji": "🃏",  "description": "Šašci — ti, co nosí pravdu ve lži"},
    "first-beings":  {"color": 0x9B59B6, "emoji": "⚜️",  "description": "Původní - ti, jenž tu jsou od počátku"},
    "shadows":  {"color": 0x9B59B6, "emoji": "👤",  "description": "Stíny - Neunikneš stínům v tvém srdci"},
    "witches":  {"color": 0x9B59B6, "emoji": "♦️",  "description": "Hříšné čarodějky patřící pod Sedm smrtelných hříchů"},
    "angels":  {"color": 0x9B59B6, "emoji": "☀️",  "description": "Andělé věří, že můžou zničit veškeré zlo"},
}
SEED_CARDS = [
    {"id": 1, "name": "Alice Aurelion", "description": "Mystická postava z Aurionisu s aurou tajemství.",    "image": "unworthy_alice_aurelion.png", "collection": "unworthy"},
    {"id": 2, "name": "Enel",           "description": "Kdo ví co za tajemství v sobě skrývá.",              "image": "unworthy_enel.png",           "collection": "unworthy"},
    {"id": 3, "name": "Kaiser Vexx",    "description": "Kdo ví co za tajemství v sobě skrývá.",              "image": "unworthy_kaiser_vexx.png",    "collection": "unworthy"},
    {"id": 4, "name": "Nyx",            "description": "Vyvolená postava, která promlouvá skrze stíny.",     "image": "chosen_one_nyx.png",          "collection": "chosen"},
    {"id": 5, "name": "Darrin",         "description": "Hrdina nesoucí břímě vyvoleného.",                   "image": "chosen_one_darrin.png",       "collection": "chosen"},
    {"id": 6, "name": "Karl von Ulrich", "description": "Poutník, jehož minulost odvál severní vítr.", "image": "unworthy_karl_von_ulrich.png", "collection": "unworthy"},
    {"id": 7, "name": "Arion", "description": "Malý čaroděj s osudem větším než celý Aurionis.", "image": "unworthy_arion.png", "collection": "unworthy"},
    {"id": 8, "name": "Hádankář",       "description": "Jeho síla je nezměrná, možná největší na tomto světě…", "image": "hadankar.png",           "collection": "jesters"},
    {"id": 9, "name": "Hádankář",       "description": "Jeho síla je nezměrná, možná největší na tomto světě…", "image": "snajpy_hadankar.png",    "collection": "jesters"},
    {"id": 10, "name": "Reinhard",       "description": "Nejvyšší paladin, který nikdy neprohrál v souboji.", "image": "reinhard.png",               "collection": "chosen"},
    {"id": 11, "name": "Klaus",       "description": "Krutý temný rytíř samozvankyně.", "image": "klaus.png",               "collection": "first-beings"},
    {"id": 12, "name": "Vlad",       "description": "Mocný upíří lord z Valgherijské pevnosti.", "image": "vlad.png",               "collection": "first-beings"},
    {"id": 13, "name": "Freya",       "description": "Heretická čarodějka pocházející z počátku času.", "image": "freya.png",               "collection": "first-beings"},
    {"id": 14, "name": "Marcel",       "description": "Marcel jen vůdcem většiny svobodných upírů.", "image": "marcel.png",               "collection": "first-beings"},
    {"id": 15, "name": "Vládce stínů",       "description": "Jediná cesta k rovnováze je skrze stíny", "image": "gabriel.png",               "collection": "shadows"},
    {"id": 16, "name": "Alice Aurelion",       "description": "Poslední čistá krev z královského rodu Aurionisu", "image": "alice_queen.png",               "collection": "queen"},
    {"id": 17, "name": "Noxarath",       "description": "Čarodějka smrti a bohyně temnoty.", "image": "noxarath.png",               "collection": "witches"},
    {"id": 18, "name": "Embra",       "description": "Čarodějka hněvu, jenž byla zostuzena", "image": "embra.png",               "collection": "witches"},
    {"id": 19, "name": "Hádankář",       "description": "Jeho síla je nezměrná, možná největší na tomto světě…", "image": "hadankar2.png",               "collection": "jesters"},
    {"id": 20, "name": "Hao",       "description": "Nejsilnější vyvolený a rank 1 dobrodruh.", "image": "hao.png",               "collection": "worthy"},
    {"id": 21, "name": "Bojový šašek",       "description": "Šašek jenž vyhledává silné soupeře", "image": "bojovy_sasek.png",               "collection": "jesters"},
    {"id": 22, "name": "Elegantní šašek",       "description": "Šašek jenž je známý svou touhou hrát hry", "image": "elegantni_sasek.png",               "collection": "jesters"},
    {"id": 23, "name":"Jason Harvey",       "description": "Říká se, že mu ženy a hádankáři padají k nohám", "image": "jason.png",               "collection": "unworthy"},
    {"id": 24, "name": "Malý šašek",       "description": "Šašek jenž často asistuje ostatním šaškům", "image": "maly_sasek.png",               "collection": "jesters"},
    {"id": 25, "name": "Marco",       "description": "Vůdce Andělů, frakce věří, že zlo musí být zničeno", "image": "marco.png",               "collection": "angels"},
    {"id": 26, "name": "Draculis",       "description": "Ten lepší z původních jenž ovládá krev svých nepřátel", "image": "draculis.png",               "collection": "first-beings"},
    {"id": 27, "name": "Kocour",       "description": "Mluvící kocour a zároveň vyvolený dobrodruh", "image": "kocour.png",               "collection": "chosen"},
    {"id": 28, "name": "Žolo",       "description": "Vodní mág jenž byl vyvolený učastnit se turnaje", "image": "zolo.png",               "collection": "chosen"},
    {"id": 29, "name": "Levitující šašek",       "description": "Miluje chaos, často napodobuje emoce a výrazy ostatních", "image": "letajici_sasek.png",               "collection": "jesters"},
    {"id": 30, "name": "Remi",       "description": "Vyvolená služka jenž po smrti svého pána ztratila cestu", "image": "remi.png",               "collection": "chosen"},
    {"id": 31, "name": "Hao",       "description": "Nejsilnější vyvolený jenž okolo sebe shromažďuje silné jedince", "image": "hao2.png",               "collection": "chosen"},

]

# ---------------------------------------------------------------------------
# Rankovací tabulky pro album
# ---------------------------------------------------------------------------

QUALITY_RANK = {q: i for i, q in enumerate(QUALITY_ORDER)}
RARITY_RANK  = {r: i for i, r in enumerate(RARITY_ORDER)}


def get_best_card_for_template(uid: str, card_id: int, inventory: dict) -> "dict | None":
    """
    Vrátí nejlepší instanci karty daného hráče pro šablonu card_id.
    Nejlepší = nejnižší rank rarity, pak nejnižší rank kvality (pristine > excellent > normal > poor > damaged).
    Vrátí None pokud hráč danou kartu nevlastní.
    """
    owned = [
        inst for inst in inventory.values()
        if inst.get("owner_id") == uid and inst.get("card_id") == card_id
    ]
    if not owned:
        return None
    return min(
        owned,
        key=lambda c: (
            RARITY_RANK.get(c.get("rarity", "uncommon"), 99),
            QUALITY_RANK.get(c.get("quality", "normal"), 99),
        ),
    )


COLLECTION_ACHIEVEMENT = "Začátek kolekce"


def completed_collections(uid: str, inventory: "dict | None" = None,
                          cards_db: "list | None" = None) -> list[str]:
    """Kolekce, ze kterých hráč vlastní všechny vzory (duplikáty se nepočítají)."""
    inv = load_inventory() if inventory is None else inventory
    db  = load_json(CARDS_DATA, default=[]) if cards_db is None else cards_db

    owned = {c.get("card_id") for c in inv.values() if c.get("owner_id") == str(uid)}
    by_collection: dict[str, set] = {}
    for tmpl in db:
        coll = tmpl.get("collection")
        if coll:
            by_collection.setdefault(coll, set()).add(tmpl.get("id"))

    return [coll for coll, ids in by_collection.items() if ids <= owned]


async def check_collection_achievement(member, channel, inventory: "dict | None" = None) -> bool:
    """Udělí „Začátek kolekce“ za první kompletně dokončenou kolekci v albu."""
    if member is None or has_achievement(member.id, COLLECTION_ACHIEVEMENT):
        return False
    if not completed_collections(str(member.id), inventory):
        return False
    if not grant_achievement(member.id, COLLECTION_ACHIEVEMENT):
        return False
    await announce_achievement(member, channel, COLLECTION_ACHIEVEMENT)
    return True


def _ensure_nocard_png() -> str:
    """
    Zajistí, že CARDS_DIR/nocard.png existuje. Pokud ne, vygeneruje ho programově.
    Vrátí absolutní cestu k souboru.
    """
    path = os.path.join(CARDS_DIR, "nocard.png")
    if os.path.exists(path):
        return path

    try:
        from PIL import Image, ImageDraw
        from src.logic.profile_render import _font

        W, H = 1024, 1536
        img = Image.new("RGBA", (W, H), (14, 14, 22, 255))
        draw = ImageDraw.Draw(img)

        # Tmavý gradient
        for y in range(H):
            t = y / H
            c = int(14 + 12 * t)
            draw.line([(0, y), (W, y)], fill=(c, c, c + 8, 255))

        # Rámeček
        draw.rounded_rectangle(
            (18, 18, W - 18, H - 18),
            radius=28,
            outline=(55, 55, 75, 255),
            width=6,
        )
        draw.rounded_rectangle(
            (28, 28, W - 28, H - 28),
            radius=22,
            outline=(40, 40, 55, 180),
            width=2,
        )

        # Velký otazník uprostřed
        cx, cy = W // 2, H // 2
        q_font_big = _font(360, serif=True)
        draw.text((cx, cy - 80), "?", font=q_font_big, fill=(45, 45, 62, 255), anchor="mm")
        draw.text((cx, cy - 80), "?", font=q_font_big, fill=(72, 72, 98, 220), anchor="mm")

        # ???? text
        q_font_med = _font(90)
        draw.text((cx, cy + 330), "????", font=q_font_med, fill=(80, 80, 105, 255), anchor="mm")

        # Vykřičník badge nahoře
        badge_font = _font(60)
        draw.rounded_rectangle(
            (cx - 80, 60, cx + 80, 148),
            radius=24,
            fill=(22, 22, 32, 220),
            outline=(60, 60, 82, 255),
            width=2,
        )
        draw.text((cx, 104), "!", font=badge_font, fill=(100, 100, 125, 255), anchor="mm")

        # Spodní nápis
        footer_font = _font(50)
        draw.text((cx, H - 70), "NEZNÁMÁ KARTA", font=footer_font, fill=(65, 65, 88, 255), anchor="mm")

        os.makedirs(CARDS_DIR, exist_ok=True)
        img.save(path)
        print(f"[cards] nocard.png vygenerován: {path}")
    except Exception as e:
        print(f"[cards] Nepodařilo se vygenerovat nocard.png: {e}")

    return path


# ---------------------------------------------------------------------------
# Pomocné funkce
# ---------------------------------------------------------------------------


def ensure_cards_data():
    """Provede verzované Cards Reborn migrace a udržuje seed katalog aktuální."""
    state = load_json(CARDS_REBORN_STATE, default={})
    version = state.get("version", 0)
 
    if version < 1:
        save_json(CARDS_DATA, SEED_CARDS)
        save_json(CARDS_INVENTORY, {})
 
        profiles = profile_load()
        changed = False
        for profile in profiles.values():
            if profile.get("active_card_id") is not None:
                profile["active_card_id"] = None
                changed = True
        if changed:
            profile_save(profiles)
 
        version = 1
        save_json(CARDS_REBORN_STATE, {"version": version})
 
    if version < 2:
        save_json(CARDS_WORK, {})
        version = 2
        save_json(CARDS_REBORN_STATE, {"version": version})
 
    cards = load_json(CARDS_DATA, default=[])
    seeds_by_id = {seed["id"]: seed for seed in SEED_CARDS}
    custom_cards = [card for card in cards if card.get("id") not in seeds_by_id]
    updated_cards = SEED_CARDS + custom_cards
    if updated_cards != cards:
        save_json(CARDS_DATA, updated_cards)



def ensure_frames_data():
    """Zajistí, aby soubor cards_frames.json existoval a obsahoval alespoň výchozí rámeček."""
    frames = load_json(CARDS_FRAMES, default=[])
    if not frames:
        save_json(CARDS_FRAMES, [
            {
                "id": "riddler_frame",
                "name": "Riddler Rámeček",
                "image": "riddler_frame.png",
                "color": "#FF6B9D",
                "rarity_exclusive": None,
            }
        ])

def generate_unique_id() -> str:
    """Generuje náhodné unikátní ID (8 znaků)."""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=8))
 
def get_card_by_id(card_id: int):
    """Vrátí šablonu karty podle ID, nebo None."""
    for card in load_json(CARDS_DATA, default=[]):
        if card.get("id") == card_id:
            return card
    return None


def load_inventory() -> dict:
    """
    Načte CARDS_INVENTORY a tiše odfiltruje jakékoliv poškozené záznamy
    (např. staré položky uložené dřívější buggy verzí kódu ve špatném
    formátu). Díky tomu jedna vadná položka nesloží žádný příkaz, který
    přes inventář iteruje, a soubor se navíc sám vyčistí, jakmile se
    příště zapíše zpět přes save_json(CARDS_INVENTORY, ...).
    """
    raw = load_json(CARDS_INVENTORY, default={})
    return {k: v for k, v in raw.items() if isinstance(v, dict)}



def get_card_image_path(image_filename: str):
    """Vrátí absolutní cestu k obrázku karty, nebo None pokud soubor neexistuje."""
    if not image_filename:
        return None
    path = os.path.join(CARDS_DIR, image_filename)
    return path if os.path.exists(path) else None
  
  
def get_frame_by_id(frame_id: str):
    """Vrátí data rámečku podle ID, nebo None."""
    for frame in load_json(CARDS_FRAMES, default=[]):
        if frame.get("id") == frame_id:
            return frame
    return None

def _rgb(color: int) -> tuple:
    """Rozloží celočíselnou barvu embedu na (r, g, b)."""
    return ((color >> 16) & 255, (color >> 8) & 255, color & 255)
 
def build_showcase_image(card: dict, unique_id: str, owner_name: str = None,
                         frame_id: str = None, tickets: str = None, image=None):
    """
    Vyrenderuje kartu jako jeden obrázek (art + kompaktní detaily).
    Vrátí BytesIO s PNG, nebo None pokud art karty chybí.
    """
    art = image if image is not None else get_card_image_path(card.get("image"))
    if art is None:
        return None
 
    rarity = card.get("rarity", "uncommon")
    rarity_data = RARITIES.get(rarity, RARITIES["uncommon"])
    quality = card.get("quality", "normal")
    quality_data = QUALITIES.get(quality, QUALITIES["normal"])
    collection = card.get("collection")
    coll_data = COLLECTIONS.get(collection, {}) if collection else {}
 
    try:
        date_text = datetime.fromisoformat(card.get("created_at", "")).strftime("%d. %m. %Y")
    except Exception:
        date_text = "—"
 
    rows = [("Tisk", f"#{card.get('print_number', '?')}")]
    if collection:
        rows.append(("Kolekce", collection.capitalize()))
    if owner_name:
        rows.append(("Vlastník", owner_name))
    if tickets:
        rows.append(("Lístky štěstí", tickets))
    rows.append(("Rámeček", frame_id or "Žádný"))
    rows.append(("Vytisknuto", date_text))
 
    footer = coll_data.get("description") or "Aurionis"
 
    return render_card_showcase(
        art,
        card.get("name", "?"),
        card.get("description", ""),
        _rgb(rarity_data["color"]),
        [
            (rarity.capitalize(), _rgb(rarity_data["color"])),
            (quality_data["name"], _rgb(quality_data["color"])),
        ],
        rows,
        unique_id,
        footer=footer,
        frame_id=frame_id,
    )
 
def grant_random_card(
    uid: str,
    *,
    tickets: int,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Přidělí hráči náhodnou kartu a uloží ji do databáze.
    """

    inventory = load_inventory()
    result = draw_random_card(uid, load_json(CARDS_DATA, default=[]), inventory,
                              tickets=tickets)
    if result:
        unique_id, card = result
        inventory[unique_id] = card
        save_json(CARDS_INVENTORY, inventory)
    return result


def draw_random_card(uid, all_cards, inventory, *, tickets):
    """Create an instance without writing; callers can commit it atomically."""
    if not all_cards:
        return None

    rarity = roll_rarity(tickets)
    quality = roll_quality()

    card_template = random.choice(all_cards)

    unique_id = generate_unique_id()
    while unique_id in inventory:
        unique_id = generate_unique_id()

    # -----------------------------------------------------------------
    # 4. Sestavení a uložení instance karty — stejný formát jako /cards print
    # -----------------------------------------------------------------
    max_print = max(
        (c.get("print_number", 0) for c in inventory.values() if c.get("card_id") == card_template.get("id")),
        default=0,
    )
    card_instance = {
        "card_id":              card_template.get("id"),
        "name":                 card_template.get("name"),
        "description":          card_template.get("description"),
        "image":                card_template.get("image"),
        "collection":           card_template.get("collection"),
        "rarity":               rarity,
        "quality":              quality,
        "print_number":         max_print + 1,
        "owner_id":             uid,
        "frame":                None,
        "created_at":           datetime.now().isoformat(),
    }

    # -----------------------------------------------------------------
    # 5. Návrat výsledku
    # -----------------------------------------------------------------
    return unique_id, card_instance

# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Cards(commands.Cog):
    """Sběratelský systém karet."""
 
    def __init__(self, bot):
        self.bot = bot
        self.active_trades: Dict[frozenset, "TradeView"] = {}
 
    cards_group = app_commands.Group(name="cards", description="Sběratelský systém karet")

    # -----------------------------------------------------------------------
    # Admin příkazy
    # -----------------------------------------------------------------------

    @cards_group.command(name="print", description="[ADMIN] Vytisknout novou kartu")
    @admin_only()
    @app_commands.describe(
        card_id="ID karty z databáze",
        rarity="Rarita karty",
        owner="Discord hráč — vlastník (volitelné)",
        count="Kolik kopií vytisknout (výchozí: 1)",
    )
    @app_commands.choices(rarity=[
        app_commands.Choice(name="Uncommon",  value="uncommon"),
        app_commands.Choice(name="Common",    value="common"),
        app_commands.Choice(name="Rare",      value="rare"),
        app_commands.Choice(name="Epic",      value="epic"),
        app_commands.Choice(name="Legendary", value="legendary"),
        app_commands.Choice(name="Mythic", value="mythic"),
    ])
    async def print_card(
        self,
        interaction: discord.Interaction,
        card_id: int,
        rarity: str,
        owner: discord.Member = None,
        count: int = 1,
    ):
        """Admin příkaz pro tisk nové karty do inventáře."""
        if not 1 <= count <= 50:
            await interaction.response.send_message("Počet musí být mezi 1 a 50.", ephemeral=True)
            return

        card_template = get_card_by_id(card_id)
        if not card_template:
            await interaction.response.send_message(f"Karta s ID **{card_id}** neexistuje.", ephemeral=True)
            return

        owner_id = str(owner.id) if owner else None
        inventory = load_inventory()

        max_print = max(
            (c.get("print_number", 0) for c in inventory.values() if c.get("card_id") == card_id),
            default=0,
        )

        created = []
        for _ in range(count):
            unique_id = generate_unique_id()
            while unique_id in inventory:
                unique_id = generate_unique_id()

            quality = roll_quality()

            max_print += 1
            inventory[unique_id] = {
                "card_id":      card_id,
                "name":         card_template.get("name"),
                "description":  card_template.get("description"),
                "image":        card_template.get("image"),
                "collection":   card_template.get("collection"),
                "rarity":       rarity,
                "quality":      quality,
                "print_number": max_print,
                "owner_id":     owner_id,
                "frame":        None,
                "created_at":   datetime.now().isoformat(),
            }
            created.append(unique_id)

        save_json(CARDS_INVENTORY, inventory)

        owner_mention = f"<@{owner_id}>" if owner_id else "—"
        embed = discord.Embed(
            title="✅ Karty vytištěny",
            description=(
                f"**{card_template.get('name')}** × {count}\n"
                f"Rarita: {rarity.capitalize()} {RARITIES[rarity]['emoji']}\n"
                f"Vlastník: {owner_mention}"
            ),
            color=RARITIES[rarity]["color"],
        )
        ids_value = ", ".join(created)
        if len(ids_value) > 1000:
            ids_value = ids_value[:1000] + f"\n… a {len(created) - ids_value[:1000].count(',') - 1} dalších"
        embed.add_field(name="🆔 Unikátní IDs", value=ids_value, inline=False)
        await interaction.response.send_message(embed=embed)

        if owner:
            await check_collection_achievement(owner, interaction.channel, inventory)

    @cards_group.command(name="db_add", description="[ADMIN] Přidat novou kartu do databáze vzorů")
    @admin_only()
    @app_commands.describe(
        name="Jméno karty",
        description="Popis karty",
        collection="Kolekce, do které karta patří",
        image="Název souboru obrázku (např. chosen_nyx.png)",
        attachment="Nahraj obrázek přímo z Discordu (uloží se pod zadaným názvem)",
    )
    @app_commands.choices(collection=[
        app_commands.Choice(name="Unworthy — Nevolaní",         value="unworthy"),
        app_commands.Choice(name="Worthy — Hrdinové Aurionisu", value="worthy"),
        app_commands.Choice(name="Queen — Královna a dvůr",     value="queen"),
        app_commands.Choice(name="Chosen — Vyvolení",           value="chosen"),
    ])
    async def db_add(
        self,
        interaction: discord.Interaction,
        name: str,
        description: str,
        collection: str,
        image: str,
        attachment: discord.Attachment = None,
    ):
        """[ADMIN] Přidá novou kartu do databáze vzorů karet."""
        cards = load_json(CARDS_DATA, default=[])

        # Duplicitní jméno
        if any(c.get("name", "").lower() == name.strip().lower() for c in cards):
            await interaction.response.send_message(
                f"Karta se jménem **{name}** již v databázi existuje.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Ověř bezpečnost názvu souboru — žádné cesty nebo separátory
        safe_image = image.strip()
        if any(ch in safe_image for ch in ("/", "\\", "..")):
            await interaction.followup.send("❌ Neplatný název souboru — nepoužívej lomítka ani '..'.", ephemeral=True)
            return
        image_status = ""
        if attachment:
            if not attachment.content_type or not attachment.content_type.startswith("image/"):
                await interaction.followup.send("❌ Příloha není obrázek. Použij PNG nebo JPG.", ephemeral=True)
                return
            try:
                dest = os.path.join(CARDS_DIR, safe_image)
                image_data = await attachment.read()
                with open(dest, "wb") as f:
                    f.write(image_data)
                image_status = "✅ uložen z přílohy"
            except Exception as e:
                await interaction.followup.send(f"❌ Nepodařilo se uložit obrázek: {e}", ephemeral=True)
                return
        else:
            if get_card_image_path(safe_image):
                image_status = "✅ nalezen v adresáři"
            else:
                image_status = "⚠️ soubor nenalezen — karta nebude zobrazitelná"

        # Přiděl nové ID
        next_id = max((c.get("id", 0) for c in cards), default=0) + 1

        new_card = {
            "id":          next_id,
            "name":        name.strip(),
            "description": description.strip(),
            "image":       safe_image,
            "collection":  collection,
        }
        cards.append(new_card)
        save_json(CARDS_DATA, cards)

        coll_data = COLLECTIONS[collection]
        embed = discord.Embed(
            title="✅ Karta přidána do databáze",
            description=f"{coll_data['emoji']} **{new_card['name']}**\n*{new_card['description']}*",
            color=coll_data["color"],
        )
        embed.add_field(name="🆔 Nové ID",   value=f"**#{next_id}**",                             inline=True)
        embed.add_field(name="📚 Kolekce",   value=f"{coll_data['emoji']} {collection.capitalize()}", inline=True)
        embed.add_field(name="🖼️ Obrázek",  value=f"`{new_card['image']}`\n{image_status}",       inline=True)
        embed.set_footer(text=f"Použij /cards print {next_id} <rarita> pro vytisknutí první kopie.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @cards_group.command(name="create_frame", description="[ADMIN] Přidat nový rámeček do databáze")
    @admin_only()
    @app_commands.describe(
        frame_id="Unikátní ID rámečku (použije se v /cards give_frame a /cards upgrade_frame)",
        name="Zobrazovaný název rámečku",
        image="Název souboru PNG (např. riddler_frame.png) — pokud jsi ho už nahrál ručně na server",
        color="Barva rámečku v hex formátu (např. #FF6B9D) — výchozí bílá",
        rarity_exclusive="Omezit rámeček jen na určitou raritu karty (volitelné)",
        attachment="Nebo rovnou nahraj PNG přímo z Discordu — uloží se pod zadaným 'image' názvem",
    )
    @app_commands.choices(rarity_exclusive=[
        app_commands.Choice(name="Uncommon",  value="uncommon"),
        app_commands.Choice(name="Common",    value="common"),
        app_commands.Choice(name="Rare",      value="rare"),
        app_commands.Choice(name="Epic",      value="epic"),
        app_commands.Choice(name="Legendary", value="legendary"),
        app_commands.Choice(name="Mythic", value="mythic"),
    ])
    async def create_frame(
        self,
        interaction: discord.Interaction,
        frame_id: str,
        name: str,
        image: str,
        color: str = "#FFFFFF",
        rarity_exclusive: str = None,
        attachment: discord.Attachment = None,
    ):
        """[ADMIN] Přidá nový rámeček do CARDS_FRAMES bez ruční editace JSON."""
        frame_id = frame_id.strip().lower().replace(" ", "_")
        frames = load_json(CARDS_FRAMES, default=[])

        if any(f.get("id") == frame_id for f in frames):
            await interaction.response.send_message(
                f"Rámeček s ID `{frame_id}` už existuje.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Ověř bezpečnost názvu souboru — žádné cesty ani separátory
        safe_image = image.strip()
        if any(ch in safe_image for ch in ("/", "\\", "..")):
            await interaction.followup.send("❌ Neplatný název souboru — nepoužívej lomítka ani '..'.", ephemeral=True)
            return

        # Ověř formát barvy
        hex_color = color.strip().lstrip("#")
        if len(hex_color) != 6 or any(c not in string.hexdigits for c in hex_color):
            await interaction.followup.send("❌ Barva musí být v hex formátu, např. `#FF6B9D`.", ephemeral=True)
            return

        image_status = ""
        if attachment:
            if not attachment.content_type or not attachment.content_type.startswith("image/"):
                await interaction.followup.send("❌ Příloha není obrázek. Použij PNG.", ephemeral=True)
                return
            try:
                dest = os.path.join(CARDS_DIR, safe_image)
                image_data = await attachment.read()
                with open(dest, "wb") as f:
                    f.write(image_data)
                image_status = "✅ uložen z přílohy"
            except Exception as e:
                await interaction.followup.send(f"❌ Nepodařilo se uložit obrázek: {e}", ephemeral=True)
                return
        else:
            # Rámečky nemají vlastní resolver cesty jako karty (get_card_image_path
            # kontroluje CARDS_DIR) — pokud jsi PNG nahrál jinam, tohle upozornění
            # bude falešně negativní, ale registraci to neblokuje.
            if get_card_image_path(safe_image):
                image_status = "✅ nalezen v adresáři karet"
            else:
                image_status = "⚠️ v adresáři karet nenalezen — zkontroluj, že leží tam, kde ho čeká apply_frame_to_card"

        new_frame = {
            "id": frame_id,
            "name": name.strip(),
            "image": safe_image,
            "color": f"#{hex_color.upper()}",
            "rarity_exclusive": rarity_exclusive,
        }
        frames.append(new_frame)
        save_json(CARDS_FRAMES, frames)

        embed = discord.Embed(
            title="✅ Rámeček přidán do databáze",
            description=f"**{new_frame['name']}**",
            color=int(hex_color, 16),
        )
        embed.add_field(name="🆔 ID", value=f"`{frame_id}`", inline=True)
        embed.add_field(name="🖼️ Obrázek", value=f"`{safe_image}`\n{image_status}", inline=True)
        embed.add_field(
            name="🔒 Exkluzivní pro raritu",
            value=rarity_exclusive.capitalize() if rarity_exclusive else "Žádná",
            inline=True,
        )
        embed.set_footer(text=f"Otestuj přes /cards give_frame @hráč {frame_id}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _ac_frame_id(self, interaction: discord.Interaction, current: str):
        """Autocomplete pro frame_id — hledá podle jména i ID rámečku."""
        frames = load_json(CARDS_FRAMES, default=[])
        cur = current.lower().strip()
        out = []
        for f in frames:
            fid  = f.get("id", "")
            name = f.get("name", fid)
            if cur and cur not in fid.lower() and cur not in name.lower():
                continue
            out.append(app_commands.Choice(name=f"{name} ({fid})"[:100], value=fid))
        return out[:25]

    @cards_group.command(name="list_frames", description="[ADMIN] Zobrazit všechny rámečky v databázi")
    @admin_only()
    async def list_frames(self, interaction: discord.Interaction):
        """[ADMIN] Přehled všech rámečků — obrázek, exkluzivita, kolik karet/hráčů je používá."""
        frames = load_json(CARDS_FRAMES, default=[])
        if not frames:
            await interaction.response.send_message("Databáze rámečků je prázdná.", ephemeral=True)
            return

        inv = load_inventory()
        frames_inv = load_json(FRAMES_INVENTORY, default={})

        embed = discord.Embed(
            title="🖼️ Databáze rámečků",
            description=f"Celkem: **{len(frames)}** rámečků",
            color=BRAND_PURPLE,
        )
        for f in frames[:25]:
            fid = f.get("id", "?")
            equipped_count = sum(1 for c in inv.values() if c.get("frame") == fid)
            holding_count  = sum(1 for owned in frames_inv.values() if any(x.get("id") == fid for x in owned))
            image_status = "✅" if get_card_image_path(f.get("image", "")) else "⚠️ soubor chybí"
            rarity_text = f.get("rarity_exclusive", "").capitalize() if f.get("rarity_exclusive") else "Žádná"
            embed.add_field(
                name=f"{f.get('name', '?')}  ·  `{fid}`",
                value=(
                    f"🖼️ `{f.get('image', '?')}` {image_status}\n"
                    f"🎨 {f.get('color', '#FFFFFF')}  ·  🔒 Rarita: {rarity_text}\n"
                    f"🎴 Nasazeno na kartách: **{equipped_count}**  ·  🎒 V inventářích: **{holding_count}**"
                ),
                inline=False,
            )
        if len(frames) > 25:
            embed.set_footer(text=f"⚠️ Zobrazeno prvních 25 z {len(frames)} rámečků")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @cards_group.command(name="delete_frame", description="[ADMIN] Smazat rámeček z databáze")
    @admin_only()
    @app_commands.describe(
        frame_id="Rámeček ke smazání",
        force="Smazat i když je nasazený na kartách nebo v inventářích hráčů (výchozí: ne)",
    )
    @app_commands.autocomplete(frame_id=_ac_frame_id)
    async def delete_frame(self, interaction: discord.Interaction, frame_id: str, force: bool = False):
        """
        [ADMIN] Odstraní rámeček z CARDS_FRAMES. Bez `force` odmítne smazání,
        pokud je rámeček zrovna nasazený na nějaké kartě (ať ho nejde ztratit
        omylem) — s `force:True` ho z těch karet i inventářů čistě odebere.

        Slouží i jako obchozí cesta pro "edit": smaž a založ znovu přes
        /cards create_frame se stejným ID.
        """
        frames = load_json(CARDS_FRAMES, default=[])
        frame = next((f for f in frames if f.get("id") == frame_id), None)
        if frame is None:
            await interaction.response.send_message(f"Rámeček `{frame_id}` neexistuje.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        inv = load_inventory()
        equipped_on = [cid for cid, card in inv.items() if card.get("frame") == frame_id]

        frames_inv = load_json(FRAMES_INVENTORY, default={})
        holders = [uid for uid, owned in frames_inv.items() if any(f.get("id") == frame_id for f in owned)]

        if equipped_on and not force:
            preview = ", ".join(f"`{cid}`" for cid in equipped_on[:10])
            more = f" (+{len(equipped_on) - 10} dalších)" if len(equipped_on) > 10 else ""
            await interaction.followup.send(
                f"⚠️ Rámeček **{frame.get('name')}** je nasazený na {len(equipped_on)} kartě/kartách: "
                f"{preview}{more}\nPoužij `force: True`, pokud ho chceš i tak smazat — kartám se rámeček odebere.",
                ephemeral=True,
            )
            return

        if equipped_on:
            for cid in equipped_on:
                inv[cid]["frame"] = None
            save_json(CARDS_INVENTORY, inv)

        if holders:
            for uid in holders:
                frames_inv[uid] = [f for f in frames_inv[uid] if f.get("id") != frame_id]
            save_json(FRAMES_INVENTORY, frames_inv)

        frames.remove(frame)
        save_json(CARDS_FRAMES, frames)

        msg = f"🗑️ Rámeček **{frame.get('name')}** (`{frame_id}`) byl smazán z databáze."
        if equipped_on:
            msg += f"\n↩️ Odebrán z {len(equipped_on)} karet."
        if holders:
            msg += f"\n🎒 Odstraněn z inventáře {len(holders)} hráčů."
        await interaction.followup.send(msg, ephemeral=True)

    @cards_group.command(name="give_frame", description="[ADMIN] Dát rámeček jednomu nebo více hráčům")
    @admin_only()
    @app_commands.describe(
        users="Hráči oddělení mezerou nebo zatagování (např. @hráč1 @hráč2 ...)",
        frame_id="Rámeček — napiš pár písmen jména a vyber z nabídky",
    )
    @app_commands.autocomplete(frame_id=_ac_frame_id)
    async def give_frame(self, interaction: discord.Interaction, users: str, frame_id: str):
        """Admin příkaz pro přidání rámečku do inventáře jednoho nebo více hráčů."""
        frame = get_frame_by_id(frame_id)
        if not frame:
            await interaction.response.send_message(f"Rámeček `{frame_id}` neexistuje.", ephemeral=True)
            return

        # Parsuj uživatele z textu (tagování nebo ID) — stejně jako /summon give
        user_ids = []
        for mention in users.split():
            if mention.startswith("<@") and mention.endswith(">"):
                user_ids.append(mention.strip("<@!>"))
            elif mention.isdigit():
                user_ids.append(mention)

        if not user_ids:
            await interaction.response.send_message(
                "❌ Žádní hráči nenalezeni. Použij `/cards give_frame @hráč1 @hráč2 ... frame_id`",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        frames_inv = load_json(FRAMES_INVENTORY, default={})
        results = []
        for uid in user_ids:
            try:
                user = await self.bot.fetch_user(int(uid))
                user_label = user.mention
            except Exception:
                user_label = f"ID:{uid}"

            owned = frames_inv.setdefault(uid, [])
            if any(f.get("id") == frame_id for f in owned):
                results.append(f"⚠️ {user_label} — už **{frame.get('name')}** má")
                continue

            owned.append({"id": frame_id, "name": frame.get("name")})
            results.append(f"✅ {user_label} — přidán **{frame.get('name')}**")

        save_json(FRAMES_INVENTORY, frames_inv)

        embed = discord.Embed(
            title="🖼️ Rámeček rozdán",
            description="\n".join(results),
            color=0x00FF00,
        )
        await interaction.followup.send(embed=embed)

    @cards_group.command(name="remove_card", description="[ADMIN] Smazat kartu úplně z inventáře")
    @admin_only()
    @app_commands.describe(unique_id="Unikátní ID karty k odstranění")
    async def remove_card(self, interaction: discord.Interaction, unique_id: str):
        """Admin příkaz pro úplné smazání instance karty z inventáře."""
        inventory = load_inventory()

        if unique_id not in inventory:
            await interaction.response.send_message(f"Karta `{unique_id}` neexistuje.", ephemeral=True)
            return

        card_name = inventory[unique_id].get("name", unique_id)
        owner_id = inventory[unique_id].get("owner_id")

        # Varování pokud je karta na výpravě
        works = load_json(CARDS_WORK, default={})
        on_work = owner_id and any(
            unique_id in w.get("cards", [])
            for w in works.values()
        )

        del inventory[unique_id]
        save_json(CARDS_INVENTORY, inventory)

        # Vyčisti profilovou referenci pokud existuje
        if owner_id:
            profiles = profile_load()
            if profiles.get(owner_id, {}).get("active_card_id") == unique_id:
                profiles[owner_id]["active_card_id"] = None
                profile_save(profiles)

        embed = discord.Embed(
            title="🗑️ Karta smazána",
            description=f"**{card_name}** (ID: `{unique_id}`) byla úplně odstraněna.",
            color=0xFF0000,
        )
        if on_work:
            embed.add_field(
                name="⚠️ Pozor",
                value="Karta byla na aktivní výpravě. Data výpravy zůstávají — hráč dostane odměnu za prázdné ID.",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    # -----------------------------------------------------------------------
    # Hráčské příkazy — inventář a karty
    # -----------------------------------------------------------------------

    @cards_group.command(name="inventory", description="Zobrazit své karty")
    @app_commands.describe(user="Hráč (volitelné — výchozí jsi ty)")
    async def show_inventory(self, interaction: discord.Interaction, user: discord.Member = None):
        """Zobrazí inventář hráče se stránkováním, pokud má víc karet, než se vejde na jednu stránku."""
        target = user or interaction.user
        uid = str(target.id)

        inv = load_inventory()
        user_cards = [(cid, card) for cid, card in inv.items() if card.get("owner_id") == uid]

        if not user_cards:
            await interaction.response.send_message(f"{target.mention} nemá žádné karty.", ephemeral=True)
            return

        # Stabilní pořadí podle čísla tisku, ať se karty mezi stránkami nepřehazují
        user_cards.sort(key=lambda item: item[1].get("print_number", 0))

        embed = build_inventory_embed(target, user_cards, page=0)

        if len(user_cards) <= INVENTORY_PAGE_SIZE:
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        view = InventoryPaginatorView(invoker_id=interaction.user.id, target=target, sorted_cards=user_cards)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @cards_group.command(name="show", description="Zobrazit konkrétní kartu")
    @app_commands.describe(unique_id="Unikátní ID karty", frame="ID rámečku (volitelné — přepíše uložený)")
    async def show_card(self, interaction: discord.Interaction, unique_id: str, frame: str = None):
        """Zobrazí konkrétní kartu — nový formát s rendeovanou kartou."""
        inv = load_inventory()

        if unique_id not in inv:
            await interaction.response.send_message(f"Karta s ID `{unique_id}` neexistuje.", ephemeral=True)
            return

        card = inv[unique_id]
        card_owner_id = card.get("owner_id")

        if card_owner_id and card_owner_id != str(interaction.user.id) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Přístup odepřen", "Tato karta ti nepatří."), ephemeral=True
            )
            return

        selected_frame = frame or card.get("frame")
        await interaction.response.defer()

        try:
            loop = asyncio.get_running_loop()
            
            # Vyrenderuj kartu s detaily (nový formát jako summon)
            showcase = await loop.run_in_executor(
                None,
                partial(
                    build_showcase_image,
                    card,
                    unique_id,
                    owner_name=None,
                    frame_id=selected_frame,
                ),
            )
            
            if showcase is None:
                await interaction.followup.send(
                    f"❌ Obrázek karty s ID `{unique_id}` nebyl nalezen.",
                    ephemeral=True
                )
                return

            # Pošli renderovanou kartu jako obrázek
            await interaction.followup.send(
                content=f"🎴 **{card.get('name')}**",
                file=discord.File(showcase, filename="card.png"),
            )
            
        except Exception as e:
            await interaction.followup.send(f"❌ Chyba při zobrazení karty: {e}", ephemeral=True)

    async def _ac_owned_frame_id(self, interaction: discord.Interaction, current: str):
        """Autocomplete pro /cards upgrade — nabídne jen rámečky, co hráč doopravdy vlastní."""
        frames_inv = load_json(FRAMES_INVENTORY, default={})
        owned = frames_inv.get(str(interaction.user.id), [])
        cur = current.lower().strip()
        out = []
        for f in owned:
            fid  = f.get("id", "")
            name = f.get("name", fid)
            if cur and cur not in fid.lower() and cur not in name.lower():
                continue
            out.append(app_commands.Choice(name=f"{name} ({fid})"[:100], value=fid))
        return out[:25]

    @cards_group.command(name="upgrade", description="Nasadit rámeček na kartu")
    @app_commands.describe(unique_id="ID karty", frame="Rámeček z tvého inventáře")
    @app_commands.autocomplete(frame=_ac_owned_frame_id)
    async def upgrade_frame(self, interaction: discord.Interaction, unique_id: str, frame: str):
        """Aplikuje rámeček na kartu (rámeček se spotřebuje)."""
        uid = str(interaction.user.id)
        inv = load_inventory()
        frames_inv = load_json(FRAMES_INVENTORY, default={})

        if unique_id not in inv:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Karta nenalezena", f"ID `{unique_id}` neexistuje."), ephemeral=True
            )
            return

        card = inv[unique_id]
        if card.get("owner_id") != uid:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Přístup odepřen", "Tato karta ti nepatří."), ephemeral=True
            )
            return

        # Karta na výpravě?
        works = load_json(CARDS_WORK, default={})
        user_work = works.get(uid)
        if user_work and unique_id in user_work.get("cards", []):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nelze upravit", "Karta je momentálně na výpravě!"),
                ephemeral=True,
            )
            return

        user_frames = frames_inv.get(uid, [])
        if frame not in [f.get("id") for f in user_frames]:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Rámeček nenalezen", f"Rámeček `{frame}` nemáš v inventáři."), ephemeral=True
            )
            return

        card["frame"] = frame
        inv[unique_id] = card
        save_json(CARDS_INVENTORY, inv)

        frames_inv[uid] = [f for f in user_frames if f.get("id") != frame]
        save_json(FRAMES_INVENTORY, frames_inv)

        frame_data = get_frame_by_id(frame)
        frame_name = frame_data.get("name") if frame_data else frame
        await interaction.response.send_message(
            f"✅ Rámeček **{frame_name}** nasazen na kartu **{card.get('name', unique_id)}** (spotřebován z inventáře).",
            ephemeral=True,
        )

    @cards_group.command(name="frames", description="Rámečky ve tvém inventáři")
    async def show_frames(self, interaction: discord.Interaction):
        """Zobrazí rámečky v inventáři hráče."""
        uid = str(interaction.user.id)
        frames_inv = load_json(FRAMES_INVENTORY, default={})
        user_frames = frames_inv.get(uid, [])

        all_frames = load_json(CARDS_FRAMES, default=[])

        if not all_frames:
            await interaction.response.send_message("Žádné rámečky nejsou v databázi.", ephemeral=True)
            return

        embed = discord.Embed(title="📦 Rámečky", color=BRAND_PURPLE)

        owned_ids = {f.get("id") for f in user_frames}
        for f in all_frames:
            rarity_text = f" · Vyžaduje: {f['rarity_exclusive']}" if f.get("rarity_exclusive") else ""
            owned_mark = " ✅" if f.get("id") in owned_ids else ""
            embed.add_field(
                name=f"{f.get('name')}{owned_mark}",
                value=f"ID: `{f.get('id')}`{rarity_text}",
                inline=False,
            )

        embed.set_footer(text=f"Vlastníš: {len(user_frames)} z {len(all_frames)} rámečků.")
        await interaction.response.send_message(embed=embed)

    # -----------------------------------------------------------------------
    # Info & databáze
    # -----------------------------------------------------------------------

    @cards_group.command(name="info", description="Vítej v Aurionisu — přehled systému karet")
    async def cards_info(self, interaction: discord.Interaction):
        """Uvítací embed s kompletním přehledem kartového systému."""
        cards = load_json(CARDS_DATA, default=[])
        inv = load_inventory()

        rarity_counts = {}
        collection_counts = {}
        for c in inv.values():
            r = c.get("rarity", "uncommon")
            rarity_counts[r] = rarity_counts.get(r, 0) + 1
            col = c.get("collection", "—")
            collection_counts[col] = collection_counts.get(col, 0) + 1

        embed = discord.Embed(
            title="⚜️  Vítej v Aurionisu!",
            description=(
                "*Sbírej, vyměňuj a obdivuj karty z říše Aurionisu.*\n"
                "*Každá karta je unikátní a nese příběh svého světa.*\n\u200b"
            ),
            color=BRAND_PURPLE,
        )

        embed.add_field(name="🖨️ Celkem vytisknuto", value=f"**{len(inv)}** karet",      inline=True)
        embed.add_field(name="🎴 Unikátních vzorů",   value=f"**{len(cards)}** karet",    inline=True)
        embed.add_field(name="\u200b",                value="\u200b",                      inline=True)

        coll_lines = [
            f"{cdata['emoji']} **{cid.capitalize()}** — {collection_counts.get(cid, 0)} ks"
            for cid, cdata in COLLECTIONS.items()
        ]
        embed.add_field(name="📚 Sady v oběhu", value="\n".join(coll_lines), inline=True)

        rarity_lines = [
            f"{rdata['emoji']} **{rid.capitalize()}** — {rarity_counts.get(rid, 0)} ks"
            for rid, rdata in RARITIES.items()
        ]
        embed.add_field(name="✨ Rarity v oběhu", value="\n".join(rarity_lines), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        quality_lines = [
            f"{qdata['emoji']} **{qdata['name']}** — ×{QUALITY_MULTIPLIERS[qid]:.1f} prachu"
            for qid, qdata in QUALITIES.items()
        ]
        embed.add_field(name="💎 Kvality karet", value="\n".join(quality_lines), inline=True)

        base, boosted = rarity_chances(1), rarity_chances(10)
        embed.add_field(
            name="🎟️ Šance na raritu · 1 → 10 lístků",
            value="\n".join(f"{rid.capitalize()}: **{base[rid]:g}% → {boosted[rid]:.2f}%**"
                            for rid in RARITIES), inline=False,
        )
        embed.add_field(
            name="Kvalita · nezávislá na lístcích",
            value="Damaged 10% · Poor 20% · Normal 40% · Excellent 20% · Pristine 10%",
            inline=False,
        )

        dust_lines = [
            f"{RARITIES[rid]['emoji']} {rid.capitalize()} — **{val}** prachu"
            for rid, val in DUST_VALUES.items()
        ]
        embed.add_field(name="🔥 Hodnota při spálení", value="\n".join(dust_lines), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        exp_lines = [
            f"{exp['emoji']} **{exp['name']}** — {exp['hours']}h · +{exp['reward']} zl./kartu"
            for exp in EXPEDITIONS.values()
        ]
        embed.add_field(name="⚔️ Výpravy", value="\n".join(exp_lines), inline=False)

        commands_text = (
            "`/cards inventory` — tvé karty\n"
            "`/cards show <id>` — detail karty\n"
            "`/cards album <kolekce>` — vizuální album kolekce\n"
            "`/cards profile` — profilová karta\n"
            "`/cards set_profile <id>` — nastav profilovou kartu\n"
            "`/cards burn <id>` — spálit kartu za prach\n"
            "`/cards work` — přehled výpravy\n"
            "`/cards work_send` — vyslat karty\n"
            "`/cards work_claim` — vyzvednout odměnu\n"
            "`/cards gallery` — přehled kolekcí\n"
            "`/cards list` — databáze karet"
        )
        embed.add_field(name="📖 Příkazy", value=commands_text, inline=False)
        embed.set_footer(text="⚜️ Aurionis Sběratelský Systém  •  /cards info")
        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="list", description="Dostupné vzory karet v databázi")
    async def list_cards(self, interaction: discord.Interaction):
        """Zobrazí seznam všech dostupných vzorů karet."""
        cards = load_json(CARDS_DATA, default=[])

        if not cards:
            await interaction.response.send_message("Žádné karty nejsou v databázi.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎴 Databáze karet",
            description="Použij `/cards print <id> <rarita>` pro vytisknutí kopie.",
            color=BRAND_PURPLE,
        )
        for card in cards:
            coll = card.get("collection", "—")
            coll_emoji = COLLECTIONS.get(coll, {}).get("emoji", "")
            embed.add_field(
                name=f"#{card.get('id')} — {card.get('name', '?')}  {coll_emoji}",
                value=card.get("description", "—"),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="gallery", description="Alba kolekcí — přehled sad a karet")
    @app_commands.describe(collection="Sada (volitelné) — zobrazí detail kolekce")
    @app_commands.choices(collection=[
        app_commands.Choice(name="Unworthy — Nevolaní",         value="unworthy"),
        app_commands.Choice(name="Worthy — Hrdinové Aurionisu", value="worthy"),
        app_commands.Choice(name="Queen — Královna a dvůr",     value="queen"),
        app_commands.Choice(name="Chosen — Vyvolení",           value="chosen"),
    ])
    async def gallery(self, interaction: discord.Interaction, collection: str = None):
        """Přehled kolekcí nebo detail jedné sady."""
        cards_db = load_json(CARDS_DATA, default=[])
        inv = load_inventory()

        if collection:
            collection = collection.lower()
            coll_data = COLLECTIONS.get(collection)
            if not coll_data:
                await interaction.response.send_message(
                    f"Neznámá kolekce `{collection}`. Dostupné: {', '.join(COLLECTIONS.keys())}", ephemeral=True
                )
                return

            templates = [c for c in cards_db if c.get("collection") == collection]
            instances = [c for c in inv.values() if c.get("collection") == collection]

            rarity_counts = {}
            for inst in instances:
                r = inst.get("rarity", "uncommon")
                rarity_counts[r] = rarity_counts.get(r, 0) + 1

            embed = discord.Embed(
                title=f"{coll_data['emoji']}  Kolekce: {collection.capitalize()}",
                description=f"*{coll_data['description']}*",
                color=coll_data["color"],
            )
            embed.add_field(name="🎴 Vzorů v sadě",       value=f"**{len(templates)}**",   inline=True)
            embed.add_field(name="🖨️ Celkem vytisknuto",  value=f"**{len(instances)}**",   inline=True)
            embed.add_field(name="\u200b",                  value="\u200b",                  inline=True)

            if rarity_counts:
                rarity_lines = [
                    f"{RARITIES[rid]['emoji']} {rid.capitalize()} — {cnt} ks"
                    for rid, cnt in rarity_counts.items()
                    if cnt
                ]
                embed.add_field(name="✨ Rarity v oběhu", value="\n".join(rarity_lines), inline=False)

            if templates:
                for tmpl in templates:
                    tid = tmpl.get("id")
                    copies = sum(1 for inst in instances if inst.get("card_id") == tid)
                    embed.add_field(
                        name=f"#{tid} — {tmpl.get('name', '?')}",
                        value=f"{tmpl.get('description', '—')}\n*{copies} ks v oběhu*",
                        inline=False,
                    )
            else:
                embed.add_field(name="Karty", value="Žádné vzory v této kolekci.", inline=False)

            embed.set_footer(text="⚜️ Aurionis  •  /cards gallery pro přehled všech sad")
            await interaction.response.send_message(embed=embed)

        else:
            embed = discord.Embed(
                title="📚  Galerie Aurionisu",
                description="*Přehled všech kolekcí — jejich obsah a stav v oběhu.*",
                color=BRAND_PURPLE,
            )
            for cid, cdata in COLLECTIONS.items():
                templates_count = sum(1 for c in cards_db if c.get("collection") == cid)
                printed_count   = sum(1 for c in inv.values() if c.get("collection") == cid)
                embed.add_field(
                    name=f"{cdata['emoji']}  {cid.capitalize()}",
                    value=(
                        f"*{cdata['description']}*\n"
                        f"🎴 Vzorů: **{templates_count}**  ·  🖨️ Vytisknuto: **{printed_count}**\n"
                        f"`/cards gallery {cid}`"
                    ),
                    inline=False,
                )
            embed.set_footer(text="⚜️ Aurionis Sběratelský Systém")
            await interaction.response.send_message(embed=embed)

    @cards_group.command(name="album", description="Zobrazit své album karát dané kolekce")
    @app_commands.describe(
        collection="Kolekce k zobrazení",
        user="Hráč (volitelné — výchozí jsi ty)",
    )
    @app_commands.choices(collection=[
        app_commands.Choice(name="Unworthy — Nevolaní",             value="unworthy"),
        app_commands.Choice(name="Worthy — Hrdinové Aurionisu",     value="worthy"),
        app_commands.Choice(name="Queen — Královna a dvůr",         value="queen"),
        app_commands.Choice(name="Chosen — Vyvolení",               value="chosen"),
        app_commands.Choice(name="Jesters — Šašci",                 value="jesters"),
        app_commands.Choice(name="First-beings — Původní bytosti",  value="first-beings"),
        app_commands.Choice(name="Shadows — Stíny",                 value="shadows"),
        app_commands.Choice(name="Witches — Čarodějky",             value="witches"),
        app_commands.Choice(name="Angels — Andělé",                 value="angels"),
    ])
    async def show_album(
        self,
        interaction: discord.Interaction,
        collection: str,
        user: discord.Member = None,
    ):
        """Zobrazí osobní album hráče pro danou kolekci jako vizuální mřížku karet."""
        target = user or interaction.user
        uid = str(target.id)

        collection = collection.lower()
        coll_data = COLLECTIONS.get(collection)
        if not coll_data:
            await interaction.response.send_message(
                f"Neznámá kolekce `{collection}`.", ephemeral=True
            )
            return

        # Načteme šablony dané kolekce
        cards_db = load_json(CARDS_DATA, default=[])
        templates = [c for c in cards_db if c.get("collection") == collection]

        if not templates:
            await interaction.response.send_message(
                f"Kolekce **{collection.capitalize()}** zatím neobsahuje žádné karty.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            inv = load_inventory()
            nocard_path = os.path.join(CARDS_DIR, "nocard.png")

            # Sestavíme seznam (šablona, nejlepší_instance|None)
            album_cards = [
                (tmpl, get_best_card_for_template(uid, tmpl["id"], inv))
                for tmpl in templates
            ]

            owned_count = sum(1 for _, inst in album_cards if inst is not None)

            # Barva kolekce jako RGB tuple
            col_hex = coll_data["color"]
            col_rgb = ((col_hex >> 16) & 255, (col_hex >> 8) & 255, col_hex & 255)

            loop = asyncio.get_running_loop()
            album_img = await loop.run_in_executor(
                None,
                partial(
                    render_album_grid,
                    collection.capitalize(),
                    coll_data["emoji"],
                    coll_data["description"],
                    col_rgb,
                    album_cards,
                    nocard_path if os.path.exists(nocard_path) else None,
                ),
            )

            embed = discord.Embed(
                title=f"{coll_data['emoji']} Album — {collection.capitalize()}",
                description=(
                    f"*{coll_data['description']}*\n"
                    f"**{owned_count}/{len(templates)}** karet získáno"
                ),
                color=coll_data["color"],
            )
            embed.set_author(
                name=target.display_name,
                icon_url=target.display_avatar.url,
            )
            embed.set_image(url="attachment://album.png")
            embed.set_footer(text="⚜️ Aurionis  •  /cards album")

            await interaction.followup.send(
                embed=embed,
                file=discord.File(album_img, filename="album.png"),
                ephemeral=True,
            )

            await check_collection_achievement(target, interaction.channel, inv)

        except Exception as e:
            await interaction.followup.send(f"❌ Chyba při generování alba: {e}", ephemeral=True)

    # -----------------------------------------------------------------------
    # Profil
    # -----------------------------------------------------------------------

    @cards_group.command(name="set_profile", description="Nastaví kartu jako svou profilovou")
    @app_commands.describe(unique_id="Unikátní ID karty")
    async def set_profile_card(self, interaction: discord.Interaction, unique_id: str):
        """Nastaví profilovou kartu hráče."""
        uid = str(interaction.user.id)
        inv = load_inventory()

        if unique_id not in inv:
            await interaction.response.send_message(f"Karta s ID `{unique_id}` neexistuje.", ephemeral=True)
            return

        card = inv[unique_id]
        if card.get("owner_id") != uid:
            await interaction.response.send_message("Tato karta ti nepatří.", ephemeral=True)
            return

        profiles = profile_load()
        if uid not in profiles:
            profiles[uid] = {}
        profiles[uid]["active_card_id"] = unique_id
        profile_save(profiles)

        await interaction.response.send_message(
            f"✅ Karta **{card.get('name')}** (Print #{card.get('print_number', '?')}) nastavena jako tvá profilová karta!",
            ephemeral=True,
        )

    @cards_group.command(name="profile", description="Zobrazit svou (nebo cizí) profilovou kartu")
    @app_commands.describe(user="Hráč (volitelné — výchozí jsi ty)")
    async def show_profile_card(self, interaction: discord.Interaction, user: discord.Member = None):
        """Zobrazí nastavenou profilovou kartu hráče."""
        target = user or interaction.user
        uid = str(target.id)

        profiles = profile_load()
        active_card_id = profiles.get(uid, {}).get("active_card_id")

        if not active_card_id:
            msg = "Nemáš nastavenou profilovou kartu." if not user else f"{target.mention} nemá nastavenou profilovou kartu."
            await interaction.response.send_message(
                f"{msg} Nastav ji pomocí `/cards set_profile <id>`.", ephemeral=True
            )
            return

        inv = load_inventory()
        if active_card_id not in inv:
            # Karta byla spálena nebo smazána — vyčisti referenci
            profiles[uid]["active_card_id"] = None
            profile_save(profiles)
            await interaction.response.send_message(
                "Profilová karta již neexistuje (byla spálena nebo smazána). Nastav novou pomocí `/cards set_profile <id>`.",
                ephemeral=True,
            )
            return

        card = inv[active_card_id]
        await interaction.response.defer()

        try:
            loop = asyncio.get_running_loop()
            
            # Vyrenderuj kartu s detaily (nový formát)
            showcase = await loop.run_in_executor(
                None,
                partial(
                    build_showcase_image,
                    card,
                    active_card_id,
                    owner_name=None,
                    frame_id=card.get("frame"),
                ),
            )
            
            if showcase is None:
                await interaction.followup.send("Obrázek karty nebyl nalezen.", ephemeral=True)
                return

            rarity = card.get("rarity", "uncommon")
            rarity_data = RARITIES.get(rarity, RARITIES["uncommon"])

            embed = discord.Embed(
                title=f"🃏 Profilová karta — {target.display_name}",
                description=f"{rarity_data['emoji']} **{card.get('name', '?')}**",
                color=rarity_data["color"],
            )
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.set_image(url="attachment://card.png")
            embed.set_footer(text="⚜️ Aurionis")

            await interaction.followup.send(embed=embed, file=discord.File(showcase, filename="card.png"))
        except Exception as e:
            await interaction.followup.send(f"❌ Chyba při zobrazení karty: {e}", ephemeral=True)

    # -----------------------------------------------------------------------
    # Spálení
    # -----------------------------------------------------------------------

    @cards_group.command(name="burn", description="Spálit kartu a získat Hvězdný prach")
    @app_commands.describe(unique_id="Unikátní ID karty ke spálení")
    async def burn_card(self, interaction: discord.Interaction, unique_id: str):
        """Spálí kartu hráče a připíše mu Hvězdný prach."""
        uid = str(interaction.user.id)

        try:
            result = burn_card_by_id(uid, unique_id)
        except CardNotFoundError:
            await interaction.response.send_message(f"Karta s ID `{unique_id}` neexistuje.", ephemeral=True)
            return
        except NotCardOwnerError:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Přístup odepřen", "Tato karta ti nepatří."), ephemeral=True
            )
            return
        except CardOnExpeditionError:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nelze spálit", "Karta je momentálně na výpravě! Nejprve si vyzvedni odměnu."),
                ephemeral=True,
            )
            return

        rarity, qual, total_dust = result["rarity"], result["quality"], result["dust"]
        mult = QUALITY_MULTIPLIERS.get(qual, 1.0)

        embed = discord.Embed(
            title="🔥 Karta spálena",
            description=(
                f"Spálil jsi **{result['name']}** (ID: `{unique_id}`).\n"
                f"Duše karty se rozpadla na **{total_dust}× Hvězdný prach**."
            ),
            color=BRAND_PURPLE,
        )
        qual_data = QUALITIES.get(qual, QUALITIES["normal"])
        embed.add_field(name="Rarita",  value=f"{RARITIES.get(rarity, {}).get('emoji', '')} {rarity.capitalize()}", inline=True)
        embed.add_field(name="Kvalita", value=f"{qual_data['emoji']} {qual_data['name']} (×{mult:.1f})",             inline=True)
        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="trade", description="Nabídnout/upravit obchod s hráčem — obě strany musí potvrdit")
    @app_commands.describe(
        user="Hráč, se kterým obchoduješ",
        karty="ID karet oddělená čárkou, např. ab12cd34,ef56gh78",
    )
    async def trade_cards(self, interaction: discord.Interaction, user: discord.Member, karty: str):
        """
        Založí obchod, nebo — pokud už mezi vámi jeden běží — přidá/přepíše
        tvou nabídku jako protinabídku ve stejné zprávě.
        """
        me = interaction.user

        if user.id == me.id:
            await interaction.response.send_message("❌ Nemůžeš obchodovat sám se sebou.", ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message("❌ S boty se obchodovat nedá.", ephemeral=True)
            return

        unique_ids = _parse_trade_card_ids(karty)
        if not unique_ids:
            await interaction.response.send_message("❌ Zadej aspoň jedno ID karty.", ephemeral=True)
            return
        if len(unique_ids) > TRADE_MAX_CARDS:
            await interaction.response.send_message(
                f"❌ Najednou lze nabídnout maximálně {TRADE_MAX_CARDS} karet.", ephemeral=True
            )
            return

        valid_cards, errors = _resolve_trade_cards(str(me.id), unique_ids)
        if errors:
            await interaction.response.send_message(
                "❌ Tyhle karty nejde nabídnout:\n" + "\n".join(errors), ephemeral=True
            )
            return

        key = frozenset({me.id, user.id})
        existing = self.active_trades.get(key)

        if existing is not None and not existing.done:
            # Protinabídka do už běžícího obchodu — přepíše mou předchozí
            # nabídku (pokud jsem nějakou dal) a vynuluje obě potvrzení.
            existing.set_offer(me.id, valid_cards)
            try:
                await existing.message.edit(embed=existing.build_embed(), view=existing)
            except discord.HTTPException:
                pass
            await interaction.response.send_message(
                "✏️ Nabídka aktualizována — mrkni na obchodní zprávu výše.", ephemeral=True
            )
            return

        view = TradeView(self, key, me, user, valid_cards)
        self.active_trades[key] = view
        embed = view.build_embed()
        await interaction.response.send_message(
            content=f"{user.mention}, {me.mention} ti navrhuje obchod!",
            embed=embed,
            view=view,
        )
        view.message = await interaction.original_response()

    # -----------------------------------------------------------------------
    # Výpravy
    # -----------------------------------------------------------------------

    @cards_group.command(name="pool", description="Dej hráči jednu náhodnou kartu z pool")
    @admin_only()
    @app_commands.describe(user="Hráč, kterému chceš kartu dát")
    async def pool_card(self, interaction: discord.Interaction, user: discord.Member):
        """[ADMIN] Dá hráči jednu náhodnou kartu z dostupného pool."""
        uid = str(user.id)
        cards_db = load_json(CARDS_DATA, default=[])
        
        if not cards_db:
            await interaction.response.send_message("Databáze karet je prázdná!", ephemeral=True)
            return

        rarity = roll_rarity()
        quality = roll_quality()

        # Random karta z DB
        card_template = random.choice(cards_db)
        card_id = card_template.get("id")

        # Přidej do inventáře
        inventory = load_inventory()
        unique_id = generate_unique_id()
        while unique_id in inventory:
            unique_id = generate_unique_id()

        max_print = max(
            (c.get("print_number", 0) for c in inventory.values() if c.get("card_id") == card_id),
            default=0,
        ) + 1

        inventory[unique_id] = {
            "card_id":      card_id,
            "name":         card_template.get("name"),
            "description":  card_template.get("description"),
            "image":        card_template.get("image"),
            "collection":   card_template.get("collection"),
            "rarity":       rarity,
            "quality":      quality,
            "print_number": max_print,
            "owner_id":     uid,
            "frame":        None,
            "created_at":   datetime.now().isoformat(),
        }
        save_json(CARDS_INVENTORY, inventory)

        # Veřejný embed
        rarity_data = RARITIES.get(rarity, RARITIES["uncommon"])
        quality_data = QUALITIES.get(quality, QUALITIES["normal"])
        coll_data = COLLECTIONS.get(card_template.get("collection"), {})

        embed = discord.Embed(
            title=f"🎴 **Získal jsi: {card_template.get('name')}!**",
            description=f"*{card_template.get('description', '')}*",
            color=rarity_data["color"],
        )
        embed.add_field(name="👤 Hráč",     value=user.mention,                                       inline=True)
        embed.add_field(name="✨ Rarita",   value=f"{rarity_data['emoji']} {rarity.capitalize()}",   inline=True)
        embed.add_field(name="💎 Kvalita", value=f"{quality_data['emoji']} {quality_data['name']}",  inline=True)
        if coll_data:
            embed.add_field(name="📚 Kolekce", value=f"{coll_data.get('emoji', '')} {card_template.get('collection', 'N/A').capitalize()}", inline=True)
        embed.add_field(name="🖨️ Tisk",    value=f"**#{max_print}**",                                inline=True)
        embed.add_field(name="🆔 ID",      value=f"`{unique_id}`",                                  inline=True)
        embed.set_footer(text="⚜️ Aurionis  •  Karta přidána do tvého inventáře")
        embed.set_thumbnail(url=user.display_avatar.url)

        await interaction.response.send_message(embed=embed)
        await check_collection_achievement(user, interaction.channel, inventory)

    @cards_group.command(name="work", description="Přehled výpravy — stav nebo dostupné expedice")
    async def work_hub(self, interaction: discord.Interaction):
        """Zobrazí stav aktivní výpravy, nebo přehled dostupných expedic."""
        uid = str(interaction.user.id)
        works = load_json(CARDS_WORK, default={})

        if uid in works:
            work = works[uid]
            exp = EXPEDITIONS.get(work.get("type"))
            if not exp:
                # Poškozená data výpravy
                await interaction.response.send_message(
                    "⚠️ Data tvé výpravy jsou poškozena. Kontaktuj admina.", ephemeral=True
                )
                return

            end_time = datetime.fromisoformat(work["end_time"])
            finished = datetime.now() >= end_time

            # Výpočet očekávané odměny
            card_count = len(work["cards"])
            base_reward = exp["reward"] * card_count
            bonus_mult = 1.25 if card_count >= 3 else (1.10 if card_count == 2 else 1.0)
            expected_reward = int(base_reward * bonus_mult)
            
            embed = discord.Embed(
                title=f"{exp['emoji']} Probíhá výprava: {exp['name']}",
                description=f"*{exp['description']}*",
                color=0x2ecc71 if finished else BRAND_PURPLE,
            )
            embed.add_field(name="🎴 Počet karet", value=f"**{card_count}**", inline=True)
            embed.add_field(name="💵 Odměna/kartu", value=f"**{exp['reward']}** zl", inline=True)
            embed.add_field(name="✨ Očekávaný zisk", value=f"**{expected_reward}** zl" + (f" (+{int((bonus_mult-1.0)*100)}%)" if bonus_mult > 1.0 else ""), inline=True)
            embed.add_field(name="⏰ Návrat", value=f"<t:{int(end_time.timestamp())}:R>", inline=False)

            inv = load_inventory()
            cards_text = "\n".join(
                f"`{cid}` — {inv[cid].get('name', '?')}" if cid in inv else f"`{cid}`"
                for cid in work["cards"]
            )
            embed.add_field(name="🎴 Vyslané karty", value=cards_text or "—", inline=False)

            if finished:
                embed.add_field(
                    name="✅ Výprava skončila!",
                    value="Použij `/cards work_claim` pro vyzvednutí odměny.",
                    inline=False,
                )
        else:
            embed = discord.Embed(
                title="⚔️ Výpravné centrum",
                description="Nemáš žádnou aktivní výpravu. Vyšli karty pomocí `/cards work_send`.\n🎁 **Bonus: Pošli více karet = více zisku!** (+10% za 2, +25% za 3)\n\u200b",
                color=BRAND_PURPLE,
            )
            for exp_id, exp in EXPEDITIONS.items():
                embed.add_field(
                    name=f"{exp['emoji']} {exp['name']}",
                    value=f"⏱️ {exp['hours']}h  •  💵 +{exp['reward']} zl/kartu\n*{exp['description']}*\n`/cards work_send {exp_id}`",
                    inline=False,
                )
            embed.set_footer(text="Delší expedice = vyšší odměny. Pošli až 3 karty pro bonus!")

        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="work_send", description="Vyšle až 3 karty na výpravu za zlatem")
    @app_commands.describe(
        vyprava="Typ výpravy",
        card1="ID první karty",
        card2="ID druhé karty (volitelné)",
        card3="ID třetí karty (volitelné)",
    )
    @app_commands.choices(vyprava=[
        app_commands.Choice(name="🛡️ Hlídka (6h / +5 Zl)",          value="hlidka"),
        app_commands.Choice(name="🏕️ Táborový kemp (12h / +8 Zl)",   value="tabor"),
        app_commands.Choice(name="🐺 Lov monster (20h / +12 Zl)",    value="lov"),
        app_commands.Choice(name="📜 Úkol pro gildu (36h / +20 Zl)", value="gilda"),
        app_commands.Choice(name="⚔️ Velká bitva (48h / +35 Zl)",    value="bitva"),
    ])
    async def work_send(
        self,
        interaction: discord.Interaction,
        vyprava: str,
        card1: str,
        card2: str = None,
        card3: str = None,
    ):
        """Vyšle karty hráče na expedici."""
        uid = str(interaction.user.id)
        works = load_json(CARDS_WORK, default={})

        if uid in works:
            await interaction.response.send_message(
                "Již máš aktivní výpravu! Zkontroluj ji přes `/cards work`.", ephemeral=True
            )
            return

        card_ids = [c for c in [card1, card2, card3] if c]
        if len(set(card_ids)) != len(card_ids):
            await interaction.response.send_message("Nemůžeš poslat stejnou kartu víckrát!", ephemeral=True)
            return

        inv = load_inventory()
        for cid in card_ids:
            if cid not in inv or inv[cid].get("owner_id") != uid:
                await interaction.response.send_message(
                    f"Karta s ID `{cid}` ti nepatří nebo neexistuje.", ephemeral=True
                )
                return

        exp = EXPEDITIONS.get(vyprava)
        if not exp:
            await interaction.response.send_message("Neznámý typ výpravy.", ephemeral=True)
            return

        now = datetime.now()
        end_time = now + timedelta(hours=exp["hours"])
        works[uid] = {
            "type":       vyprava,
            "cards":      card_ids,
            "start_time": now.isoformat(),
            "end_time":   end_time.isoformat(),
        }
        save_json(CARDS_WORK, works)

        card_names = ", ".join(inv[cid].get("name", cid) for cid in card_ids)
        
        # Výpočet očekávané odměny s bonusem
        base_reward = exp['reward'] * len(card_ids)
        bonus_mult = 1.25 if len(card_ids) >= 3 else (1.10 if len(card_ids) == 2 else 1.0)
        expected_reward = int(base_reward * bonus_mult)
        bonus_text = ""
        if bonus_mult > 1.0:
            bonus_text = f" (+ {int((bonus_mult - 1.0) * 100)}% bonus!)"
        
        embed = discord.Embed(
            title=f"{exp['emoji']} Výprava zahájena: {exp['name']}",
            description=f"*{exp['description']}*",
            color=BRAND_PURPLE,
        )
        embed.add_field(name="🎴 Vyslané karty", value=card_names, inline=False)
        embed.add_field(name="⏱️ Trvání", value=f"**{exp['hours']}h**", inline=True)
        embed.add_field(name="💵 Očekávaná odměna", value=f"**{expected_reward}** zl{bonus_text}", inline=True)
        embed.add_field(name="⏰ Návrat", value=f"<t:{int(end_time.timestamp())}:R>", inline=False)
        embed.set_footer(text="Vyzvednout odměnu si můžeš pomocí /cards work_claim")
        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="work_status", description="Stav tvé aktuální výpravy")
    async def work_status(self, interaction: discord.Interaction):
        """Zobrazí stav probíhající výpravy."""
        uid = str(interaction.user.id)
        works = load_json(CARDS_WORK, default={})

        if uid not in works:
            await interaction.response.send_message(
                "Nemáš žádnou aktivní výpravu. Použij `/cards work_send`.", ephemeral=True
            )
            return

        work = works[uid]
        exp = EXPEDITIONS.get(work.get("type"))
        if not exp:
            await interaction.response.send_message(
                "⚠️ Data tvé výpravy jsou poškozena. Kontaktuj admina.", ephemeral=True
            )
            return

        end_time = datetime.fromisoformat(work["end_time"])
        finished = datetime.now() >= end_time

        # Výpočet očekávané odměny
        card_count = len(work["cards"])
        base_reward = exp["reward"] * card_count
        bonus_mult = 1.25 if card_count >= 3 else (1.10 if card_count == 2 else 1.0)
        expected_reward = int(base_reward * bonus_mult)

        embed = discord.Embed(
            title=f"{exp['emoji']} Probíhá výprava: {exp['name']}",
            description=f"*{exp['description']}*",
            color=0x2ecc71 if finished else BRAND_PURPLE,
        )
        embed.add_field(name="🎴 Počet karet", value=f"**{card_count}**", inline=True)
        embed.add_field(name="💵 Odměna/kartu", value=f"**{exp['reward']}** zl", inline=True)
        embed.add_field(name="✨ Očekávaný zisk", value=f"**{expected_reward}** zl" + (f" (+{int((bonus_mult-1.0)*100)}%)" if bonus_mult > 1.0 else ""), inline=True)
        embed.add_field(name="⏰ Návrat", value=f"<t:{int(end_time.timestamp())}:R>", inline=False)
        
        if finished:
            embed.add_field(
                name="✅ Výprava skončila!",
                value="Použij `/cards work_claim` pro vyzvednutí odměny.",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    @cards_group.command(name="work_claim", description="Vyzvednout odměnu z dokončené výpravy")
    async def work_claim(self, interaction: discord.Interaction):
        """Vyzvedne odměnu za dokončenou výpravu."""
        uid = str(interaction.user.id)
        works = load_json(CARDS_WORK, default={})

        if uid not in works:
            await interaction.response.send_message("Nemáš žádnou aktivní výpravu.", ephemeral=True)
            return

        work = works[uid]
        exp = EXPEDITIONS.get(work.get("type"))
        if not exp:
            await interaction.response.send_message(
                "⚠️ Data tvé výpravy jsou poškozena. Kontaktuj admina.", ephemeral=True
            )
            return

        end_time = datetime.fromisoformat(work["end_time"])
        if datetime.now() < end_time:
            await interaction.response.send_message(
                f"Výprava ještě neskončila! Návrat: <t:{int(end_time.timestamp())}:R>", ephemeral=True
            )
            return

        # Výpočet odměny s bonusem za počet karet
        card_count = len(work["cards"])
        base_reward = exp["reward"] * card_count
        
        # Bonus: 10% za 2 karty, 25% za 3 karty
        bonus_multiplier = 1.0
        if card_count == 2:
            bonus_multiplier = 1.10
        elif card_count >= 3:
            bonus_multiplier = 1.25
        
        reward = int(base_reward * bonus_multiplier)

        eco = load_economy()
        eco[uid] = eco.get(uid, 0) + reward
        save_economy(eco)

        del works[uid]
        save_json(CARDS_WORK, works)

        # Build embed s detaily
        embed = discord.Embed(
            title="💰 Výprava dokončena",
            description=f"Tvé karty se v pořádku vrátily z **{exp['name']}**!",
            color=BRAND_PURPLE,
        )
        embed.add_field(name="🎴 Počet karet", value=f"**{card_count}**", inline=True)
        embed.add_field(name="💵 Odměna na kartu", value=f"**{exp['reward']}** zl", inline=True)
        if bonus_multiplier > 1.0:
            bonus_pct = int((bonus_multiplier - 1.0) * 100)
            embed.add_field(name="🎁 Bonus", value=f"+{bonus_pct}% (víc karet = víc zisku!)", inline=True)
        embed.add_field(name="✨ Celkem", value=f"**{reward} zlaťáků**", inline=False, )
        embed.set_footer(text=f"Základní: {int(base_reward)} zl" if bonus_multiplier > 1.0 else "")
        await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def setup(bot):
    """Registruje cog do bota."""
    migrate_qualities()
    ensure_cards_data()
    ensure_frames_data()
    _ensure_nocard_png()
    _migrate_stardust_to_economy()
    await bot.add_cog(Cards(bot))


def _migrate_stardust_to_economy():
    """
    Jednorázový sběr: starý 'Hvězdný prach' jako free item v inventářích
    převede na novou měnu stardust v economy a item odstraní.
    Idempotentní — po převedení už žádné itemy nezůstanou, takže opakované
    spuštění (každý restart) nic neudělá.
    """
    try:
        profiles = inv_load()
    except Exception:
        return

    changed = False
    for uid, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        # Prach může být v profile["inventory"] i ve storages["inventory"]
        lists = []
        if isinstance(profile.get("inventory"), list):
            lists.append(profile["inventory"])
        storages = profile.get("storages")
        if isinstance(storages, dict) and isinstance(storages.get("inventory"), list):
            if storages["inventory"] is not profile.get("inventory"):
                lists.append(storages["inventory"])

        total = 0
        for inv in lists:
            kept = []
            for item in inv:
                if item.get("type") == "free" and item.get("name") == "Hvězdný prach":
                    total += int(item.get("qty", 0))
                else:
                    kept.append(item)
            inv[:] = kept  # uprav list in-place

        if total > 0:
            add_balance(uid, total, "stardust")
            changed = True

    if changed:
        inv_save(profiles)
        print("[cards] Migrace Hvězdného prachu do economy dokončena.")
