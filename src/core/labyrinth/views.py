"""Discord Views a Modaly pro Door Labyrinth.

Rozložení tlačítek v PersonalActionView (max 5 řádků, 0-4):
  Řádek 0 — průzkum:    Prohledat, Skenovat
  Řádek 1 — exit/kanystr: Útěk, Oznámit EXIT, Vložit kanystr
  Řádek 2 — boj:        Vystřelit, Masová vražda
  Řádek 3 — předměty/těla: Oživit, Prohledat těla, Nechat věc, Otevřít truhlu, Osvobodit
  Řádek 4 — speciální:  Zapálit svíčku, Hlasování, Položit past, Teleport Arion
"""

from __future__ import annotations

import asyncio
import random
import discord
from typing import TYPE_CHECKING

from .constants import ITEM_EMOJI, DOOR_COLORS, MAP_SIZES, CODE_LORE, ALL_ITEMS
from .helpers import alive_players, innocents_alive, item_list_str, render_map

if TYPE_CHECKING:
    from .cog import LabyrinthCog


# ── Modal: zadání kódu při útěku ──────────────────────────────────────────────

class ExitCodeModal(discord.ui.Modal, title="🔐 Zadej únikový kód"):
    code_input = discord.ui.TextInput(
        label="Číslice kódu (mezerami nebo dohromady)",
        placeholder="např.  3 7 2 5  nebo  3725",
        required=True,
        max_length=60,
    )

    def __init__(self, cog: LabyrinthCog, game: dict, channel_id: int, uid: str):
        super().__init__()
        self.cog = cog
        self.game = game
        self.channel_id = channel_id
        self.uid = uid

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.code_input.value.strip().replace(",", "").replace(" ", "")
        digits = [int(c) for c in raw if c.isdigit()]
        correct = sorted(self.game.get("exit_code", []))
        if sorted(digits) == correct:
            channel = (
                interaction.guild.get_channel(self.channel_id)
                or interaction.client.get_channel(self.channel_id)
            )
            await interaction.response.defer(ephemeral=True)
            await self.cog._handle_escape(self.channel_id, self.uid, channel)
            await interaction.followup.send("🚪 Uprchl/a jsi z labyrintu!", ephemeral=True)
        else:
            found_str = " ".join(str(n) for n in self.game.get("found_codes", []))
            await interaction.response.send_message(
                f"❌ **Nesprávný kód!** Zkontroluj zadaná čísla a zkus znovu.\n"
                f"*Kolektivní kód: `{found_str}`*",
                ephemeral=True,
            )


# ── Tutorial ready view ───────────────────────────────────────────────────────

class TutorialReadyView(discord.ui.View):
    def __init__(self, players: list[discord.Member], cog: LabyrinthCog, channel_id: int):
        super().__init__(timeout=90)
        self._players: set[int] = {m.id for m in players}
        self._ready: set[int] = set()
        self._event: asyncio.Event = asyncio.Event()
        self._cog = cog
        self._channel_id = channel_id

    @discord.ui.button(label="✅ Připraven/a", style=discord.ButtonStyle.success,
                       custom_id="lab_tutorial_ready")
    async def ready_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if uid not in self._players:
            await interaction.response.send_message("Nejsi součástí této hry.", ephemeral=True)
            return
        self._ready.add(uid)
        remaining = len(self._players) - len(self._ready)
        if remaining > 0:
            await interaction.response.send_message(
                f"✅ Připraven/a! Čekáme ještě na **{remaining}** hráče.",
                ephemeral=True,
            )
        else:
            await interaction.response.defer()
            self._event.set()

    async def on_timeout(self):
        self._event.set()

    async def wait_ready(self):
        await self._event.wait()


# ── Lobby ─────────────────────────────────────────────────────────────────────

class LabyrinthLobby(discord.ui.View):
    def __init__(self, cog: LabyrinthCog, author: discord.Member):
        super().__init__(timeout=None)
        self.cog = cog
        self.author = author
        self.players: list[discord.Member] = [author]
        self.map_size: tuple[int, int] = (4, 4)
        self._add_size_select()

    def _add_size_select(self):
        options = [
            discord.SelectOption(label="3×3 (9 místností)", value="3x3"),
            discord.SelectOption(label="4×4 (16 místností)", value="4x4", default=True),
            discord.SelectOption(label="4×6 (24 místností)", value="4x6"),
            discord.SelectOption(label="5×5 (25 místností)", value="5x5"),
        ]
        select = discord.ui.Select(
            placeholder="Velikost mapy…",
            options=options,
            custom_id="lab_map_size",
            row=0,
        )
        select.callback = self._size_selected
        self.add_item(select)

    async def _size_selected(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Pouze zakladatel volí mapu.", ephemeral=True)
            return
        value = interaction.data["values"][0]
        self.map_size = MAP_SIZES[value]
        await interaction.response.edit_message(embed=self._embed())

    def _embed(self) -> discord.Embed:
        from .constants import MIN_PLAYERS, MAX_PLAYERS
        rows, cols = self.map_size
        names = "\n".join(f"• {p.display_name}" for p in self.players)
        embed = discord.Embed(
            title="🚪 Door Labyrinth — Lobby",
            description=(
                "Sociálně-dedukční hra. Jeden hráč je **Vrah**, ostatní jsou **Nevinní**.\n"
                "Unikni přes výstup (generátor + kód) nebo odhal vraha!\n\n"
                "**Třídy nevinných:** Detektiv 🕵️ · Doktor 💊 · Skaut 👁️ · Technik 📡 · Blázen 🃏\n"
                "**Třídy vraha:** Manipulátor 🎭 · Pastičkář 🪤 · Sériový vrah 🔪\n"
            ),
            color=0x8B0000,
        )
        embed.add_field(name=f"Hráči ({len(self.players)}/{MAX_PLAYERS})", value=names, inline=True)
        embed.add_field(name="Mapa", value=f"{rows}×{cols} ({rows * cols} místností)", inline=True)
        embed.set_footer(text=f"Min. {MIN_PLAYERS} hráčů | Zakladatel spouští hru")
        return embed

    @discord.ui.button(label="Připojit se", style=discord.ButtonStyle.success,
                       custom_id="lab_join", row=1)
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from .constants import MAX_PLAYERS
        if interaction.user.id in [p.id for p in self.players]:
            await interaction.response.send_message("Už jsi v lobby!", ephemeral=True)
            return
        if len(self.players) >= MAX_PLAYERS:
            await interaction.response.send_message("Lobby je plné.", ephemeral=True)
            return
        self.players.append(interaction.user)
        await interaction.response.edit_message(embed=self._embed())

    @discord.ui.button(label="Odejít", style=discord.ButtonStyle.secondary,
                       custom_id="lab_leave", row=1)
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.author.id:
            await interaction.response.send_message("Zakladatel nemůže odejít.", ephemeral=True)
            return
        if interaction.user.id not in [p.id for p in self.players]:
            await interaction.response.send_message("Nejsi v lobby.", ephemeral=True)
            return
        self.players = [p for p in self.players if p.id != interaction.user.id]
        await interaction.response.edit_message(embed=self._embed())

    @discord.ui.button(label="▶ Spustit", style=discord.ButtonStyle.primary,
                       custom_id="lab_start_btn", row=1)
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from .constants import MIN_PLAYERS
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Pouze zakladatel spouští hru.", ephemeral=True)
            return
        if len(self.players) < MIN_PLAYERS:
            await interaction.response.send_message(
                f"Potřebuješ alespoň {MIN_PLAYERS} hráče!", ephemeral=True
            )
            return
        self.stop()
        await interaction.response.edit_message(
            content="🚪 **Door Labyrinth** — Hra se připravuje…", embed=None, view=None
        )
        await self.cog._init_game(interaction.channel, self.players, self.map_size)

    @discord.ui.button(label="🔧 Test (Admin)", style=discord.ButtonStyle.secondary,
                       custom_id="lab_test_btn", row=2)
    async def test_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Pouze admin.", ephemeral=True)
            return
        bot_member = interaction.guild.me
        test_players = [interaction.user, bot_member]
        self.stop()
        await interaction.response.edit_message(
            content="🔧 **Door Labyrinth** — Testovací spuštění (ty=Detektiv, bot=Vrah)…",
            embed=None, view=None,
        )
        await self.cog._init_game(
            interaction.channel, test_players, (3, 3),
            test_admin_uid=str(interaction.user.id),
        )

    @discord.ui.button(label="🚫 Zrušit", style=discord.ButtonStyle.danger,
                       custom_id="lab_cancel_lobby", row=2)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_admin = interaction.user.guild_permissions.administrator
        if interaction.user.id != self.author.id and not is_admin:
            await interaction.response.send_message("Pouze zakladatel nebo admin.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(content="🚫 Lobby zrušeno.", embed=None, view=None)


# ── Výběr dveří ───────────────────────────────────────────────────────────────

class DoorChoiceView(discord.ui.View):
    def __init__(self, cog: LabyrinthCog, game: dict, room_id: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.game = game
        self.room_id = room_id
        self.channel_id: int = game["channel_id"]
        self.door_data: list[tuple[str, int, str, str]] = []
        self.chosen: set[str] = {
            uid for uid in game["map"][room_id]["players"]
            if game["players"].get(uid, {}).get("trapped")
        }
        self._build_buttons()

    def _build_buttons(self):
        room = self.game["map"][self.room_id]
        connections = room["connections"]
        alive_count = len(alive_players(self.game))
        capacities = [random.randint(1, max(alive_count, 2)) for _ in connections]
        colors = random.sample(DOOR_COLORS, min(len(connections), len(DOOR_COLORS)))
        while len(colors) < len(connections):
            colors.append(random.choice(DOOR_COLORS))

        self.door_data = []
        for i, (target_id, cap) in enumerate(zip(connections, capacities)):
            emoji, color_name = colors[i]
            self.door_data.append((target_id, cap, emoji, color_name))
            btn = discord.ui.Button(
                label=f"{emoji} {color_name} [{cap}] → {target_id}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"door_{self.room_id}_{target_id}",
                row=min(i // 2, 1),
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)

        stay_btn = discord.ui.Button(
            label="🏠 Zůstat",
            style=discord.ButtonStyle.secondary,
            custom_id=f"stay_{self.room_id}",
            row=2,
        )
        stay_btn.callback = self._stay_callback
        self.add_item(stay_btn)

        inv_btn = discord.ui.Button(
            label="🎒 Inventář",
            style=discord.ButtonStyle.secondary,
            custom_id=f"inv_{self.room_id}",
            row=2,
        )
        inv_btn.callback = self._inv_callback
        self.add_item(inv_btn)

    async def _inv_callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        pdata = self.game["players"].get(uid)
        if not pdata:
            await interaction.response.send_message("Nejsi hráčem.", ephemeral=True)
            return
        items_str = item_list_str(pdata["items"], pdata)
        found = sorted(self.game.get("found_codes", []))
        total_codes = self.game.get("total_codes", 6)
        nums_str = ", ".join(str(n) for n in found) or "žádná"
        gen_fuel = self.game.get("generator_fuel", 0)
        gen_str = "✅ Spuštěn" if self.game.get("generator_started") else f"⛽ {gen_fuel}/3"
        await interaction.response.send_message(
            f"**🎒 Tvůj inventář:**\n"
            f"Předměty: {items_str}\n"
            f"🔢 Kolektivní kód: {nums_str} *({len(found)}/{total_codes})*\n"
            f"🔌 Generátor: {gen_str}",
            ephemeral=True,
        )

    def _make_callback(self, door_index: int):
        async def callback(interaction: discord.Interaction):
            uid = str(interaction.user.id)
            pdata = self.game["players"].get(uid)
            if not pdata or not pdata["alive"]:
                await interaction.response.send_message("Nejsi aktivní hráč.", ephemeral=True)
                return
            if pdata["room"] != self.room_id:
                await interaction.response.send_message("Nejsi v této místnosti.", ephemeral=True)
                return
            if uid in self.chosen:
                await interaction.response.send_message("Dveře jsi už zvolil/a.", ephemeral=True)
                return
            if pdata.get("trapped"):
                await interaction.response.send_message(
                    "🪤 Jsi chycen/a v pasti! Nemůžeš se pohnout toto kolo.",
                    ephemeral=True,
                )
                return

            target_id, cap, emoji, color_name = self.door_data[door_index]
            if cap <= 0:
                await interaction.response.send_message(
                    f"Dveře {emoji} jsou plné – zvol jiné.", ephemeral=True
                )
                return

            self.door_data[door_index] = (target_id, cap - 1, emoji, color_name)
            self.chosen.add(uid)
            pdata["door_assignment"] = target_id
            self.game["pending_choices"] -= 1

            await self._refresh_buttons(interaction)
            await interaction.followup.send(
                f"✅ Zvolil/a jsi **{emoji} {color_name}** → **{target_id}**",
                ephemeral=True,
            )

            if self.game["pending_choices"] <= 0 and not self.game.get("movement_triggered"):
                self.game["movement_triggered"] = True
                await self.cog._execute_movement(self.channel_id)

        return callback

    async def _stay_callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        pdata = self.game["players"].get(uid)
        if not pdata or not pdata["alive"]:
            await interaction.response.send_message("Nejsi aktivní hráč.", ephemeral=True)
            return
        if pdata["room"] != self.room_id:
            await interaction.response.send_message("Nejsi v této místnosti.", ephemeral=True)
            return
        if uid in self.chosen:
            await interaction.response.send_message("Rozhodnutí jsi už učinil/a.", ephemeral=True)
            return
        if pdata.get("trapped"):
            await interaction.response.send_message(
                "🪤 Jsi chycen/a v pasti — automaticky zůstáváš.", ephemeral=True
            )
            return

        self.chosen.add(uid)
        pdata["door_assignment"] = self.room_id
        self.game["pending_choices"] -= 1

        await interaction.response.send_message(
            f"🏠 Zůstáváš v místnosti **{self.room_id}**.", ephemeral=True
        )
        if self.game["pending_choices"] <= 0 and not self.game.get("movement_triggered"):
            self.game["movement_triggered"] = True
            await self.cog._execute_movement(self.channel_id)

    async def _refresh_buttons(self, interaction: discord.Interaction):
        self.clear_items()
        for i, (target_id, cap, emoji, color_name) in enumerate(self.door_data):
            disabled = cap <= 0
            btn = discord.ui.Button(
                label=f"{emoji} {color_name} [{cap}] → {target_id}",
                style=discord.ButtonStyle.secondary if not disabled else discord.ButtonStyle.danger,
                custom_id=f"door_{self.room_id}_{target_id}_r{i}",
                disabled=disabled,
                row=min(i // 2, 1),
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)
        stay_btn = discord.ui.Button(
            label="🏠 Zůstat", style=discord.ButtonStyle.secondary,
            custom_id=f"stay_{self.room_id}_r", row=2,
        )
        stay_btn.callback = self._stay_callback
        self.add_item(stay_btn)
        inv_btn = discord.ui.Button(
            label="🎒 Inventář", style=discord.ButtonStyle.secondary,
            custom_id=f"inv_{self.room_id}_r", row=2,
        )
        inv_btn.callback = self._inv_callback
        self.add_item(inv_btn)
        await interaction.response.edit_message(view=self)

    async def on_timeout(self):
        game = self.game
        if game.get("movement_triggered"):
            return
        for uid in alive_players(game):
            pdata = game["players"][uid]
            if pdata["room"] == self.room_id and uid not in self.chosen:
                pdata["door_assignment"] = self.room_id
                game["pending_choices"] -= 1
        channel = self.cog.bot.get_channel(self.channel_id)
        if channel:
            room = game["map"].get(self.room_id, {})
            tid = room.get("thread_id")
            if tid:
                thread = channel.guild.get_channel_or_thread(tid)
                if thread:
                    asyncio.create_task(
                        thread.send("⏱️ Čas na výběr dveří vypršel — kolo se přesouvá…")
                    )
        if game["pending_choices"] <= 0 and not game.get("movement_triggered"):
            game["movement_triggered"] = True
            if channel:
                asyncio.create_task(self.cog._execute_movement(self.channel_id))
            else:
                async def _retry():
                    await asyncio.sleep(1)
                    ch = self.cog.bot.get_channel(self.channel_id)
                    if ch:
                        await self.cog._execute_movement(self.channel_id)
                asyncio.create_task(_retry())


# ── View akcí místnosti (veřejný) ────────────────────────────────────────────

class RoomActionView(discord.ui.View):
    """Veřejný gateway embed — každý hráč si otevře svůj ephemeral panel."""

    def __init__(self, cog: LabyrinthCog, game: dict, room_id: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.game = game
        self.room_id = room_id
        self.channel_id: int = game["channel_id"]

        actions_btn = discord.ui.Button(
            label="🎯 Moje akce",
            style=discord.ButtonStyle.primary,
            custom_id=f"lab_myactions_{room_id}",
            row=0,
        )
        actions_btn.callback = self._open_personal_panel
        self.add_item(actions_btn)

        done_btn = discord.ui.Button(
            label="✅ Zakončit tah",
            style=discord.ButtonStyle.success,
            custom_id=f"lab_done_{room_id}",
            row=0,
        )
        done_btn.callback = self._done_cb
        self.add_item(done_btn)

    async def _open_personal_panel(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        pdata = self.game["players"].get(uid)
        if not pdata or not pdata["alive"]:
            await interaction.response.send_message("Nejsi aktivní hráč.", ephemeral=True)
            return
        if pdata["room"] != self.room_id:
            await interaction.response.send_message("Nejsi v této místnosti.", ephemeral=True)
            return
        panel = PersonalActionView(self.cog, self.game, self.room_id, uid)
        inv_str = item_list_str(pdata["items"], pdata) or "žádné"
        found = sorted(self.game.get("found_codes", []))
        total = self.game.get("total_codes", 6)
        gen_fuel = self.game.get("generator_fuel", 0)
        gen_str = "✅ Spuštěn" if self.game.get("generator_started") else f"⛽ {gen_fuel}/3"
        murderer_uid = self.game.get("murderer_uid", "")
        is_murderer = uid == murderer_uid
        extra_info = ""
        if is_murderer:
            inn_count = len(innocents_alive(self.game))
            extra_info = f"\n🎯 Zbývá **{inn_count}** nevinných."
        else:
            if self.game.get("exit_opened"):
                extra_info = f"\n🚪 EXIT OTEVŘEN — místnost **{self.game['exit_room']}**"
            elif self.game.get("exit_announced"):
                extra_info = f"\n📍 EXIT: místnost **{self.game['exit_announced']}**"
        map_str = render_map(self.game, self.room_id, hide_exit=is_murderer)
        room = self.game["map"][self.room_id]
        candle_hint = ""
        if (
            "svíčka" in pdata["items"]
            and "zapalovač" in pdata["items"]
            and not room.get("candle_lit")
            and not room.get("dark")
        ):
            candle_hint = "\n💡 *Svíčka se dá zapálit pouze v tmavé místnosti.*"
        await interaction.response.send_message(
            f"**🎯 Tvoje akce — Místnost {self.room_id}**\n"
            f"🎒 Inventář: {inv_str}\n"
            f"🔌 Generátor: {gen_str} | 🔢 Kód: {', '.join(str(n) for n in found) or '—'} ({len(found)}/{total})"
            f"{extra_info}{candle_hint}\n{map_str}",
            view=panel,
            ephemeral=True,
        )

    async def _done_cb(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        pdata = self.game["players"].get(uid)
        if not pdata or not pdata["alive"]:
            await interaction.response.send_message("Nejsi aktivní hráč.", ephemeral=True)
            return
        if pdata["room"] != self.room_id:
            await interaction.response.send_message("Nejsi v této místnosti.", ephemeral=True)
            return
        done_set = self.game.get("actions_done", set())
        if uid in done_set:
            await interaction.response.send_message("Tah jsi už zakončil/a.", ephemeral=True)
            return
        done_set.add(uid)
        self.game["actions_done"] = done_set
        await interaction.response.send_message("✅ Tah zakončen. Čekáš na ostatní.", ephemeral=True)
        alive_uids = set(alive_players(self.game))
        if alive_uids.issubset(done_set):
            event = self.game.get("round_done_event")
            if event and not event.is_set():
                event.set()


# ── Osobní panel akcí (ephemeral) ────────────────────────────────────────────

class PersonalActionView(discord.ui.View):
    """Ephemeral panel akcí přizpůsobený konkrétnímu hráči.

    Pevné řádky (0-4):
      0 — průzkum
      1 — exit/kanystr
      2 — boj
      3 — předměty/těla
      4 — speciální
    """

    def __init__(self, cog: LabyrinthCog, game: dict, room_id: str, uid: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.game = game
        self.room_id = room_id
        self.uid = uid
        self.channel_id: int = game["channel_id"]

        pdata = game["players"][uid]
        room = game["map"][room_id]
        alive_here = [u for u in room["players"] if game["players"][u]["alive"]]
        murderer_uid = game.get("murderer_uid", "")

        # ── Řádek 0: průzkum ──────────────────────────────────────────────────
        search_btn = discord.ui.Button(
            label="🔍 Prohledat místnost",
            style=discord.ButtonStyle.primary,
            custom_id=f"pa_search_{uid}_{room_id}",
            row=0,
        )
        search_btn.callback = self._search_cb
        self.add_item(search_btn)

        if pdata["role"] == "technik" and "skener" in pdata["items"] and not pdata.get("scanned_this_round"):
            scan_btn = discord.ui.Button(
                label="📡 Skenovat",
                style=discord.ButtonStyle.primary,
                custom_id=f"pa_scan_{uid}_{room_id}",
                row=0,
            )
            scan_btn.callback = self._scan_cb
            self.add_item(scan_btn)

        # ── Řádek 1: exit / kanystr ───────────────────────────────────────────
        if room["is_exit"] and uid != murderer_uid:
            exit_btn = discord.ui.Button(
                label="🚪 Pokus o útěk",
                style=discord.ButtonStyle.success,
                custom_id=f"pa_escape_{uid}_{room_id}",
                row=1,
            )
            exit_btn.callback = self._escape_cb
            self.add_item(exit_btn)

            if not game.get("exit_announced"):
                ann_btn = discord.ui.Button(
                    label="📢 Oznámit EXIT",
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"pa_announce_{uid}_{room_id}",
                    row=1,
                )
                ann_btn.callback = self._announce_cb
                self.add_item(ann_btn)

        if (
            room["is_exit"]
            and uid != murderer_uid
            and "kanystr" in pdata["items"]
            and not game.get("generator_started")
        ):
            fuel = game.get("generator_fuel", 0)
            fuel_btn = discord.ui.Button(
                label=f"⛽ Vložit kanystr ({fuel}/3)",
                style=discord.ButtonStyle.primary,
                custom_id=f"pa_fuel_{uid}_{room_id}",
                row=1,
            )
            fuel_btn.callback = self._deposit_fuel_cb
            self.add_item(fuel_btn)

        # ── Řádek 2: boj ──────────────────────────────────────────────────────
        if "pistole" in pdata["items"] and pdata.get("pistol_cooldown", 0) == 0 and len(alive_here) >= 2:
            shoot_btn = discord.ui.Button(
                label="🔫 Vystřelit",
                style=discord.ButtonStyle.danger,
                custom_id=f"pa_shoot_{uid}_{room_id}",
                row=2,
            )
            shoot_btn.callback = self._shoot_cb
            self.add_item(shoot_btn)

        if (
            uid == murderer_uid
            and pdata["role"] == "sériový vrah"
            and not pdata.get("mass_kill_used")
            and len([u for u in alive_here if u != uid]) >= 2
        ):
            mass_btn = discord.ui.Button(
                label="💀 Masová vražda (1×)",
                style=discord.ButtonStyle.danger,
                custom_id=f"pa_mass_{uid}_{room_id}",
                row=2,
            )
            mass_btn.callback = self._mass_murder_cb
            self.add_item(mass_btn)

        # ── Řádek 3: předměty / těla ──────────────────────────────────────────
        if pdata["role"] == "doktor" and "lékárnička" in pdata["items"] and room["bodies"] and not pdata.get("revived_this_game"):
            revive_btn = discord.ui.Button(
                label="💊 Oživit mrtvolu",
                style=discord.ButtonStyle.secondary,
                custom_id=f"pa_revive_{uid}_{room_id}",
                row=3,
            )
            revive_btn.callback = self._revive_cb
            self.add_item(revive_btn)

        bodies_with_items = [b for b in room["bodies"] if b.get("items")]
        if bodies_with_items:
            loot_btn = discord.ui.Button(
                label="⚰️ Prohledat těla",
                style=discord.ButtonStyle.secondary,
                custom_id=f"pa_loot_{uid}_{room_id}",
                row=3,
            )
            loot_btn.callback = self._loot_bodies_cb
            self.add_item(loot_btn)

        if pdata["items"] and room["bodies"]:
            drop_btn = discord.ui.Button(
                label="📤 Nechat věc",
                style=discord.ButtonStyle.secondary,
                custom_id=f"pa_drop_{uid}_{room_id}",
                row=3,
            )
            drop_btn.callback = self._drop_item_cb
            self.add_item(drop_btn)

        chest = room.get("chest")
        if chest and chest["locked"] and "klíč od truhly" in pdata["items"]:
            chest_btn = discord.ui.Button(
                label="🗝️ Otevřít truhlu",
                style=discord.ButtonStyle.success,
                custom_id=f"pa_chest_{uid}_{room_id}",
                row=3,
            )
            chest_btn.callback = self._chest_open_cb
            self.add_item(chest_btn)

        trapped_others = [u for u in alive_here if game["players"][u].get("trapped") and u != uid]
        if trapped_others:
            free_btn = discord.ui.Button(
                label="🔓 Osvobodit",
                style=discord.ButtonStyle.success,
                custom_id=f"pa_free_{uid}_{room_id}",
                row=3,
            )
            free_btn.callback = self._free_cb
            self.add_item(free_btn)

        # ── Řádek 4: speciální ────────────────────────────────────────────────
        has_lighter = "zapalovač" in pdata["items"] and pdata.get("zapalovač_uses", 3) > 0
        if room.get("dark") and not room.get("candle_lit") and "svíčka" in pdata["items"] and has_lighter:
            candle_btn = discord.ui.Button(
                label="🕯️ Zapálit svíčku",
                style=discord.ButtonStyle.secondary,
                custom_id=f"pa_candle_{uid}_{room_id}",
                row=4,
            )
            candle_btn.callback = self._candle_cb
            self.add_item(candle_btn)

        if room.get("vote_room") and not game.get("vote_used") and uid != murderer_uid:
            vote_btn = discord.ui.Button(
                label="🔴 Spustit hlasování",
                style=discord.ButtonStyle.danger,
                custom_id=f"pa_vote_{uid}_{room_id}",
                row=4,
            )
            vote_btn.callback = self._vote_trigger_cb
            self.add_item(vote_btn)

        if uid == murderer_uid and pdata["role"] == "pastičkář" and not room.get("trap"):
            trap_btn = discord.ui.Button(
                label="🪤 Položit past",
                style=discord.ButtonStyle.danger,
                custom_id=f"pa_trap_{uid}_{room_id}",
                row=4,
            )
            trap_btn.callback = self._trap_place_cb
            self.add_item(trap_btn)

        if room.get("ghost_arion") and not game.get("ghost_arion_used"):
            if not room.get("dark") or room.get("candle_lit"):
                arion_btn = discord.ui.Button(
                    label="🐱 Teleportovat s Arion",
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"pa_arion_{uid}_{room_id}",
                    row=4,
                )
                arion_btn.callback = self._arion_teleport_cb
                self.add_item(arion_btn)

    # ── Prohledání ────────────────────────────────────────────────────────────

    async def _search_cb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = self.uid
        pdata = self.game["players"].get(uid)
        if pdata.get("searched_this_round"):
            await interaction.followup.send("Už jsi toto kolo prohledal/a.", ephemeral=True)
            return

        room = self.game["map"][self.room_id]

        if room.get("dark") and not room.get("candle_lit"):
            if "baterka" not in pdata["items"]:
                await interaction.followup.send(
                    "🌑 **Naprostá tma!** Potřebuješ 🔦 baterku nebo zapálenou 🕯️ svíčku.",
                    ephemeral=True,
                )
                return
            pdata["items"].remove("baterka")
            results_dark = ["🔦 *Zapnul/a jsi baterku — záblesk světla, pak opět tma. Baterka se zničila.*"]
            if room["last_round_players"]:
                names = [self.game["players"][u]["name"]
                         for u in room["last_round_players"] if u in self.game["players"]]
                if names:
                    results_dark.append(
                        f"🔦 *Ve světle baterky vidíš stopy:* Minulé kolo tu bylo: **{', '.join(names)}**"
                    )
            results = results_dark
        else:
            results = []

        pdata["searched_this_round"] = True
        is_technik = pdata["role"] == "technik"
        base_chance = 0.60 if is_technik else 0.40

        if room["items"] and random.random() < base_chance:
            found_item = room["items"].pop(0)
            pdata["items"].append(found_item)
            results.append(f"Nalezl/a jsi: **{ITEM_EMOJI.get(found_item, '?')} {found_item}**!")

        chest = room.get("chest")
        if chest and chest["locked"] and "klíč od truhly" not in pdata["items"]:
            key_chance = 0.35 if is_technik else 0.15
            if random.random() < key_chance:
                pdata["items"].append("klíč od truhly")
                results.append("🗝️ *Za trhlinou ve zdi jsi našel/la* **klíč od truhly**!")

        code_found_now = False
        is_murderer = uid == self.game.get("murderer_uid")
        if room["code_number"] is not None and not room.get("code_found") and not is_murderer:
            num = room["code_number"]
            room["code_found"] = True
            self.game["found_codes"].append(num)
            pdata["code_numbers"].append(num)
            lore = random.choice(CODE_LORE)
            results.append(f"🔍 *{lore}*\n→ Číslo přidáno do kolektivního kódu.")
            code_found_now = True
        elif room["code_number"] is not None and not room.get("code_found") and is_murderer:
            results.append("🔍 *Nalezl/a jsi nápis, ale nedává ti smysl.*")

        if not results:
            results.append("*Prohledal/a jsi místnost. Nic zajímavého.*")

        items_str = item_list_str(pdata["items"], pdata)
        found_codes = sorted(self.game.get("found_codes", []))
        total_codes = self.game.get("total_codes", 6)
        results.append(f"\n**🎒 Inventář:** {items_str}")
        results.append(f"🔢 Kolektivní kód: {', '.join(str(n) for n in found_codes) or '—'} ({len(found_codes)}/{total_codes})")
        await interaction.followup.send("\n".join(results), ephemeral=True)

        if code_found_now:
            thread_id = room["thread_id"]
            if thread_id:
                rt = interaction.client.get_channel(thread_id) or interaction.guild.get_channel_or_thread(thread_id)
                if rt:
                    nums_str = ", ".join(str(n) for n in found_codes)
                    try:
                        await rt.send(f"🔢 *Kód aktualizován:* **{nums_str}** *({len(found_codes)}/{total_codes})*")
                    except Exception:
                        pass

    # ── Útěk ─────────────────────────────────────────────────────────────────

    async def _escape_cb(self, interaction: discord.Interaction):
        uid = self.uid
        if not self.game.get("exit_opened"):
            if not self.game.get("generator_started"):
                fuel = self.game.get("generator_fuel", 0)
                await interaction.response.send_message(
                    f"❌ Generátor nebyl spuštěn. Vložte ⛽ **3 kanystry** ({fuel}/3 vloženo).",
                    ephemeral=True,
                )
                return
            found = self.game.get("found_codes", [])
            total_codes = self.game.get("total_codes", 6)
            if len(found) < total_codes:
                await interaction.response.send_message(
                    f"❌ Kód: **{len(found)}/{total_codes}**. Chybí ještě **{total_codes - len(found)}** čísel.",
                    ephemeral=True,
                )
                return
            modal = ExitCodeModal(self.cog, self.game, self.channel_id, uid)
            await interaction.response.send_modal(modal)
            return
        # Exit already open — free passage
        channel = (
            interaction.guild.get_channel(self.channel_id)
            or interaction.client.get_channel(self.channel_id)
        )
        if not channel:
            await interaction.response.send_message("❌ Interní chyba — kanál nenalezen.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.cog._handle_escape(self.channel_id, uid, channel)
        await interaction.followup.send("🚪 Uprchl/a jsi z labyrintu!", ephemeral=True)

    # ── Oznámení EXITu ────────────────────────────────────────────────────────

    async def _announce_cb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = self.uid
        pdata = self.game["players"][uid]
        if self.game.get("exit_announced"):
            await interaction.followup.send("EXIT byl již oznámen.", ephemeral=True)
            return
        self.game["exit_announced"] = self.room_id
        channel = (
            interaction.guild.get_channel(self.channel_id)
            or interaction.client.get_channel(self.channel_id)
        )
        if channel:
            total_codes = self.game.get("total_codes", 6)
            await channel.send(
                f"📍 **{pdata['name']}** nalezl/a **EXIT**!\n"
                f"*Pro útěk: ⛽ 3 kanystry do generátoru + {total_codes} čísel kódu.*"
            )
        await interaction.followup.send("✅ EXIT oznámen.", ephemeral=True)

    # ── Vložení kanystru ──────────────────────────────────────────────────────

    async def _deposit_fuel_cb(self, interaction: discord.Interaction):
        ch = (
            interaction.guild.get_channel(self.channel_id)
            or interaction.client.get_channel(self.channel_id)
        )
        ok, msg = await self.cog._handle_fuel_deposit(self.game, self.room_id, self.uid, ch)
        if ok:
            new_panel = PersonalActionView(self.cog, self.game, self.room_id, self.uid)
            try:
                await interaction.response.edit_message(content=f"⛽ {msg}", view=new_panel)
            except Exception:
                await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    # ── Střelba ───────────────────────────────────────────────────────────────

    async def _shoot_cb(self, interaction: discord.Interaction):
        uid = self.uid
        pdata = self.game["players"][uid]
        if pdata.get("shot_this_round"):
            await interaction.response.send_message("Už jsi v tomto kole vystřelil/a.", ephemeral=True)
            return
        room = self.game["map"][self.room_id]
        targets = [u for u in room["players"] if u != uid and self.game["players"].get(u, {}).get("alive")]
        if not targets:
            await interaction.response.send_message("V místnosti není nikdo jiný.", ephemeral=True)
            return
        options = [discord.SelectOption(label=self.game["players"][t]["name"], value=t, emoji="🎯") for t in targets]
        select = discord.ui.Select(placeholder="Vyber cíl…", options=options, custom_id=f"pa_shoot_sel_{uid}")

        async def sel_cb(sel_interaction: discord.Interaction):
            if str(sel_interaction.user.id) != uid:
                await sel_interaction.response.send_message("To není tvá pistole.", ephemeral=True)
                return
            await sel_interaction.response.defer(ephemeral=True)
            ch = (
                sel_interaction.guild.get_channel(self.channel_id)
                or sel_interaction.client.get_channel(self.channel_id)
            )
            await self.cog._handle_shoot(self.channel_id, uid, sel_interaction.data["values"][0], ch)

        select.callback = sel_cb
        v = discord.ui.View(timeout=60)
        v.add_item(select)
        await interaction.response.send_message("🔫 Vyber cíl:", view=v, ephemeral=True)

    # ── Oživení ───────────────────────────────────────────────────────────────

    async def _revive_cb(self, interaction: discord.Interaction):
        uid = self.uid
        room = self.game["map"][self.room_id]
        options = [
            discord.SelectOption(label=f"{b['name']} (kolo {b['round']})", value=b["uid"], emoji="💀")
            for b in room["bodies"]
        ]
        select = discord.ui.Select(placeholder="Koho oživit?", options=options, custom_id=f"pa_rev_sel_{uid}")

        async def sel_cb(sel_interaction: discord.Interaction):
            if str(sel_interaction.user.id) != uid:
                await sel_interaction.response.send_message("To není tvoje lékárnička.", ephemeral=True)
                return
            await sel_interaction.response.defer(ephemeral=True)
            ch = (
                sel_interaction.guild.get_channel(self.channel_id)
                or sel_interaction.client.get_channel(self.channel_id)
            )
            await self.cog._handle_revive(self.channel_id, uid, sel_interaction.data["values"][0], self.room_id, ch)

        select.callback = sel_cb
        v = discord.ui.View(timeout=60)
        v.add_item(select)
        await interaction.response.send_message("💊 Koho chceš oživit?", view=v, ephemeral=True)

    # ── Skenování ─────────────────────────────────────────────────────────────

    async def _scan_cb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = self.uid
        pdata = self.game["players"][uid]
        if pdata.get("scanned_this_round"):
            await interaction.followup.send("Skener jsi už v tomto kole použil/a.", ephemeral=True)
            return
        pdata["scanned_this_round"] = True
        results = []
        if "amulet" not in pdata["items"] and random.random() < 0.10:
            pdata["items"].append("amulet")
            results.append("🔮 **Amulet Druhé Naděje** — vzácný nález!\n*Po tvé smrti budeš oživen/a jakmile vrah opustí místnost.*")
        else:
            drobnosti = [i for i in ALL_ITEMS if i not in pdata["items"]]
            if drobnosti and random.random() < 0.55:
                found = random.choice(drobnosti)
                pdata["items"].append(found)
                results.append(f"📡 Skener zachytil signál!\nNalezeno: **{ITEM_EMOJI.get(found, '?')} {found}**")
            else:
                results.append("📡 *Skener nezachytil nic zajímavého.*")
        results.append(f"\n**🎒 Inventář:** {item_list_str(pdata['items'])}")
        await interaction.followup.send("\n".join(results), ephemeral=True)

    # ── Zapálit svíčku ────────────────────────────────────────────────────────

    async def _candle_cb(self, interaction: discord.Interaction):
        ch = (
            interaction.guild.get_channel(self.channel_id)
            or interaction.client.get_channel(self.channel_id)
        )
        ok, msg = await self.cog._light_candle_cb(self.game, self.room_id, self.uid, ch)
        await interaction.response.send_message(msg, ephemeral=True)

    # ── Hlasování ─────────────────────────────────────────────────────────────

    async def _vote_trigger_cb(self, interaction: discord.Interaction):
        ch = (
            interaction.guild.get_channel(self.channel_id)
            or interaction.client.get_channel(self.channel_id)
        )
        ok, msg = await self.cog._vote_trigger_cb(self.game, self.room_id, self.uid, ch)
        await interaction.response.send_message(msg, ephemeral=True)

    # ── Past ──────────────────────────────────────────────────────────────────

    async def _trap_place_cb(self, interaction: discord.Interaction):
        ch = (
            interaction.guild.get_channel(self.channel_id)
            or interaction.client.get_channel(self.channel_id)
        )
        ok, msg = await self.cog._trap_place_cb(self.game, self.room_id, self.uid, ch)
        await interaction.response.send_message(msg, ephemeral=True)

    # ── Osvobodit ─────────────────────────────────────────────────────────────

    async def _free_cb(self, interaction: discord.Interaction):
        uid = self.uid
        room = self.game["map"][self.room_id]
        trapped_others = [u for u in room["players"] if self.game["players"][u].get("trapped") and u != uid]
        if not trapped_others:
            await interaction.response.send_message("Nikdo tu není v pasti.", ephemeral=True)
            return
        ch = (
            interaction.guild.get_channel(self.channel_id)
            or interaction.client.get_channel(self.channel_id)
        )
        ok, msg = await self.cog._free_cb(self.game, self.room_id, uid, trapped_others[0], ch)
        await interaction.response.send_message(msg, ephemeral=True)

    # ── Masová vražda ─────────────────────────────────────────────────────────

    async def _mass_murder_cb(self, interaction: discord.Interaction):
        uid = self.uid
        room = self.game["map"][self.room_id]
        others = [u for u in room["players"] if self.game["players"][u]["alive"] and u != uid]
        if len(others) < 2:
            await interaction.response.send_message("Potřebuješ alespoň 2 oběti.", ephemeral=True)
            return
        options = [
            discord.SelectOption(label=self.game["players"][u]["name"], value=u, emoji="💀")
            for u in others
        ]
        select = discord.ui.Select(
            placeholder="Vyber přesně 2 oběti…",
            options=options[:25],
            min_values=2,
            max_values=min(2, len(others)),
            custom_id=f"pa_mass_sel_{uid}",
        )

        async def sel_cb(sel_interaction: discord.Interaction):
            if str(sel_interaction.user.id) != uid:
                await sel_interaction.response.send_message("To není tvůj výběr.", ephemeral=True)
                return
            await sel_interaction.response.defer(ephemeral=True)
            chosen = sel_interaction.data["values"]
            ch = (
                sel_interaction.guild.get_channel(self.channel_id)
                or sel_interaction.client.get_channel(self.channel_id)
            )
            await self.cog._handle_mass_murder(self.channel_id, uid, chosen, ch)
            await sel_interaction.followup.send("💀 Masová vražda provedena.", ephemeral=True)

        select.callback = sel_cb
        v = discord.ui.View(timeout=60)
        v.add_item(select)
        await interaction.response.send_message(
            "💀 **Masová vražda** — vyber přesně 2 oběti:", view=v, ephemeral=True
        )

    # ── Prohledat těla ────────────────────────────────────────────────────────

    async def _loot_bodies_cb(self, interaction: discord.Interaction):
        room = self.game["map"][self.room_id]
        pdata = self.game["players"][self.uid]
        all_body_items: list[tuple[str, int]] = []
        for bi, body in enumerate(room["bodies"]):
            for item in body.get("items", []):
                all_body_items.append((item, bi))
        if not all_body_items:
            await interaction.response.send_message("Na tělech nic není.", ephemeral=True)
            return
        options = [
            discord.SelectOption(
                label=f"{ITEM_EMOJI.get(item, '?')} {item}",
                value=f"{bi}:{item}",
                description=f"U těla: {room['bodies'][bi]['name']}",
            )
            for item, bi in all_body_items[:25]
        ]
        select = discord.ui.Select(
            placeholder="Vyber předmět k sebrání…",
            options=options,
            custom_id=f"pa_loot_sel_{self.uid}",
        )

        async def sel_cb(sel_interaction: discord.Interaction):
            if str(sel_interaction.user.id) != self.uid:
                await sel_interaction.response.send_message("To není tvůj výběr.", ephemeral=True)
                return
            val = sel_interaction.data["values"][0]
            bi_str, item_name = val.split(":", 1)
            bi = int(bi_str)
            body = room["bodies"][bi]
            if item_name not in body.get("items", []):
                await sel_interaction.response.send_message("Předmět již není u těla.", ephemeral=True)
                return
            body["items"].remove(item_name)
            pdata["items"].append(item_name)
            await sel_interaction.response.send_message(
                f"⚰️ Sebral/a jsi **{ITEM_EMOJI.get(item_name, '?')} {item_name}** z těla **{body['name']}**.",
                ephemeral=True,
            )

        select.callback = sel_cb
        v = discord.ui.View(timeout=60)
        v.add_item(select)
        await interaction.response.send_message("⚰️ **Prohledávání těl** — co chceš sebrat?", view=v, ephemeral=True)

    # ── Nechat věc u těla ─────────────────────────────────────────────────────

    async def _drop_item_cb(self, interaction: discord.Interaction):
        pdata = self.game["players"][self.uid]
        room = self.game["map"][self.room_id]
        if not pdata["items"]:
            await interaction.response.send_message("Nemáš žádné předměty.", ephemeral=True)
            return
        options = [
            discord.SelectOption(label=f"{ITEM_EMOJI.get(i, '?')} {i}", value=i)
            for i in pdata["items"]
        ]
        select = discord.ui.Select(
            placeholder="Vyber předmět k ponechání…",
            options=options[:25],
            custom_id=f"pa_drop_sel_{self.uid}",
        )

        async def sel_cb(sel_interaction: discord.Interaction):
            if str(sel_interaction.user.id) != self.uid:
                await sel_interaction.response.send_message("To není tvůj výběr.", ephemeral=True)
                return
            item_name = sel_interaction.data["values"][0]
            if item_name not in pdata["items"]:
                await sel_interaction.response.send_message("Předmět už nemáš.", ephemeral=True)
                return
            pdata["items"].remove(item_name)
            if room["bodies"]:
                room["bodies"][0].setdefault("items", []).append(item_name)
                dest = f"u těla **{room['bodies'][0]['name']}**"
            else:
                room["items"].append(item_name)
                dest = "na podlaze místnosti"
            await sel_interaction.response.send_message(
                f"📤 Nechal/a jsi **{ITEM_EMOJI.get(item_name, '?')} {item_name}** {dest}.",
                ephemeral=True,
            )

        select.callback = sel_cb
        v = discord.ui.View(timeout=60)
        v.add_item(select)
        await interaction.response.send_message("📤 **Nechat věc** — co chceš odložit?", view=v, ephemeral=True)

    # ── Otevřít truhlu ────────────────────────────────────────────────────────

    async def _chest_open_cb(self, interaction: discord.Interaction):
        room = self.game["map"][self.room_id]
        chest = room.get("chest")
        if not chest or not chest["locked"]:
            await interaction.response.send_message("Truhla je již otevřena.", ephemeral=True)
            return
        pdata = self.game["players"][self.uid]
        if "klíč od truhly" not in pdata["items"]:
            await interaction.response.send_message("Nemáš klíč od truhly.", ephemeral=True)
            return
        pdata["items"].remove("klíč od truhly")
        chest["locked"] = False
        contents = chest.get("contents", [])
        room["items"].extend(contents)
        contents_str = ", ".join(f"{ITEM_EMOJI.get(i, '?')} {i}" for i in contents)
        await interaction.response.send_message(
            f"🗝️ **Truhla otevřena!** Uvnitř: **{contents_str}** — přidáno do místnosti.",
            ephemeral=True,
        )
        thread_id = room.get("thread_id")
        if thread_id:
            rt = interaction.client.get_channel(thread_id) or interaction.guild.get_channel_or_thread(thread_id)
            if rt:
                try:
                    await rt.send(f"📦 **{pdata['name']}** otevřel/a truhlu! Obsah: **{contents_str}** — leží v místnosti.")
                except Exception:
                    pass

    # ── Teleport s Duchem Arion ───────────────────────────────────────────────

    async def _arion_teleport_cb(self, interaction: discord.Interaction):
        if self.game.get("ghost_arion_used"):
            await interaction.response.send_message("Arion již zmizela.", ephemeral=True)
            return
        room_ids = [rid for rid in self.game["map"] if rid != self.room_id]
        options = [discord.SelectOption(label=f"Místnost {rid}", value=rid) for rid in sorted(room_ids)]
        select = discord.ui.Select(
            placeholder="Vyber místnost…",
            options=options[:25],
            custom_id=f"pa_arion_sel_{self.uid}",
        )

        async def sel_cb(sel_interaction: discord.Interaction):
            if str(sel_interaction.user.id) != self.uid:
                await sel_interaction.response.send_message("To není tvůj výběr.", ephemeral=True)
                return
            if self.game.get("ghost_arion_used"):
                await sel_interaction.response.send_message("Arion již zmizela.", ephemeral=True)
                return
            dest = sel_interaction.data["values"][0]
            self.game["ghost_arion_used"] = True
            self.game["map"][self.room_id]["ghost_arion"] = False
            pdata = self.game["players"][self.uid]
            old_room = pdata["room"]
            if self.uid in self.game["map"][old_room]["players"]:
                self.game["map"][old_room]["players"].remove(self.uid)
            pdata["room"] = dest
            self.game["map"][dest]["players"].append(self.uid)
            ch = (
                sel_interaction.guild.get_channel(self.channel_id)
                or sel_interaction.client.get_channel(self.channel_id)
            )
            if ch:
                dest_thread_id = self.game["map"][dest].get("thread_id")
                if dest_thread_id:
                    dest_thread = ch.guild.get_channel_or_thread(dest_thread_id)
                    if dest_thread:
                        try:
                            await dest_thread.add_user(sel_interaction.user)
                        except Exception:
                            pass
            await sel_interaction.response.send_message(
                f"🐱 **Arion tě teleportovala do místnosti {dest}!** Přesunul/a ses okamžitě.",
                ephemeral=True,
            )

        select.callback = sel_cb
        v = discord.ui.View(timeout=60)
        v.add_item(select)
        await interaction.response.send_message(
            "🐱 **Arion nabízí teleport.** Zvol místnost:", view=v, ephemeral=True
        )


# ── View pro vraha: zabít ─────────────────────────────────────────────────────

class MurderView(discord.ui.View):
    def __init__(self, cog: LabyrinthCog, game: dict, murderer_uid: str, victim_uid: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.game = game
        self.murderer_uid = murderer_uid
        self.victim_uid = victim_uid
        self.channel_id: int = game["channel_id"]
        self.used = False

    @discord.ui.button(label="🔪 Zabít", style=discord.ButtonStyle.danger,
                       custom_id="lab_murder")
    async def murder_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.murderer_uid:
            await interaction.response.send_message("Toto tlačítko není pro tebe.", ephemeral=True)
            return
        if self.used:
            await interaction.response.send_message("Akce již proběhla.", ephemeral=True)
            return
        self.used = True
        self.stop()
        await interaction.response.defer(ephemeral=True)
        ch = (
            interaction.guild.get_channel(self.channel_id)
            or interaction.client.get_channel(self.channel_id)
        )
        await self.cog._handle_murder(self.channel_id, self.murderer_uid, self.victim_uid, ch)
        await interaction.followup.send("Hotovo.", ephemeral=True)

    async def on_timeout(self):
        self.used = True
