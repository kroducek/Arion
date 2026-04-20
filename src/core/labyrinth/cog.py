"""Hlavní herní logika — LabyrinthCog."""

import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands

from .constants import (
    MIN_PLAYERS, MAX_PLAYERS, INNOCENT_ROLES, MURDERER_ROLES,
    ITEM_EMOJI, WEAPON_ITEMS,
)
from .data import load_scores, record_win
from .helpers import (
    build_map, scatter_items_and_codes,
    alive_players, innocents_alive, item_list_str,
    room_direction, check_win, render_map, delete_after,
)
from .roles import ROLE_INFO
from .rooms import apply_custom_rooms
from .views import (
    LabyrinthLobby, TutorialReadyView, DoorChoiceView,
    RoomActionView, MurderView,
)


class LabyrinthCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_games: dict[int, dict] = {}
        self._door_views: dict[int, dict[str, DoorChoiceView]] = {}

    # ── Inicializace hry ─────────────────────────────────────────────────────

    async def _init_game(self, channel: discord.TextChannel,
                         players: list[discord.Member],
                         map_size: tuple[int, int]):
        rows, cols = map_size
        random.shuffle(players)

        murderer = players[0]
        murderer_role = random.choice(MURDERER_ROLES)

        roles_pool = INNOCENT_ROLES[:]
        random.shuffle(roles_pool)

        player_data: dict[str, dict] = {}
        for i, m in enumerate(players):
            uid = str(m.id)
            if m.id == murderer.id:
                role = murderer_role
            else:
                role = roles_pool[(i - 1) % len(roles_pool)]
            player_data[uid] = {
                "name": m.display_name,
                "role": role,
                "room": "",
                "alive": True,
                "escaped": False,
                "items": [],
                "code_numbers": [],
                "has_key": False,
                "searched_this_round": False,
                "scanned_this_round": False,
                "shot_this_round": False,
                "shoot_target": None,
                "door_assignment": None,
                "trapped": False,
                "mass_kill_used": False,
                "pistol_cooldown": 0,
                "revived_this_game": False,
                "fake_role": None,
            }

        murderer_uid_str = str(murderer.id)
        for uid, pdata in player_data.items():
            role_data = ROLE_INFO.get(pdata["role"], {})
            start_item = role_data.get("start_item")
            if start_item:
                pdata["items"].append(start_item)
            if pdata["role"] == "detektiv":
                pdata["pistol_cooldown"] = 2

        game_map = build_map(rows, cols)
        room_ids = list(game_map.keys())

        game: dict = {
            "phase": "running",
            "round": 0,
            "guild_id": channel.guild.id,
            "channel_id": channel.id,
            "rows": rows,
            "cols": cols,
            "spectator_thread_id": None,
            "map": game_map,
            "players": player_data,
            "murderer_uid": murderer_uid_str,
            "exit_room": "",
            "exit_code": [],
            "total_codes": 6,
            "pending_choices": 0,
            "movement_triggered": False,
            "pending_revivals": [],
            "found_codes": [],
            "vote_used": False,
            "vote_room_id": None,
            "vote_data": None,
            "traps": {},
            "generator_fuel": 0,
            "generator_started": False,
        }

        scatter_items_and_codes(game)
        apply_custom_rooms(game, n_custom=2)

        start_room = room_ids[0]
        for uid in player_data:
            player_data[uid]["room"] = start_room
            game_map[start_room]["players"].append(uid)

        self.active_games[channel.id] = game

        try:
            spec_thread = await channel.create_thread(
                name="👁️ Divácká tribuna",
                type=discord.ChannelType.private_thread,
                invitable=False,
            )
            game["spectator_thread_id"] = spec_thread.id
            await spec_thread.send("Toto vlákno je pro vyřazené hráče. Mohou sledovat, ale ne hrát.")
        except Exception as e:
            print(f"[Labyrinth] Spectator vlákno: {e}")

        occupied = set(p["room"] for p in player_data.values())
        n_codes = game.get("total_codes", 6)
        tutorial_embed = discord.Embed(
            title="🚪 Door Labyrinth — Jak se hraje",
            description=(
                "Nacházíte se v záhadném labyrintu. **Jeden z vás je Vrah.**\n\n"
                f"**Cíl nevinných:** Spusťte generátor (⛽ 3 kanystry) + najděte {n_codes} čísel kódu, zadejte kód a unikněte přes EXIT — "
                "nebo odhalte vraha (pistolí nebo hlasováním).\n"
                "**Cíl vraha:** Eliminuj všechny nevinné.\n\n"
                "**Pohyb (každé kolo):**\n"
                "Každé dveře mají kapacitu — číslo určuje, kolik hráčů jimi může projít. "
                "Klikni na barevné tlačítko dveří nebo zůstaň.\n\n"
                "**Prohledání místnosti:**\n"
                "Odkryje předměty, čísla kódu a atmosferické záchytné body. "
                "⚠️ Tmavé místnosti vyžadují 🔦 baterku nebo 🕯️ svíčku.\n\n"
                "**Zabíjení:**\n"
                "Vrah může zaútočit, pokud je sám s obětí (nebo Pastičkář s chycenou obětí). "
                "Pistole zabije ihned. Zbraně (nůž, baseballka, sekáček, vrtačka) dávají **50% šanci zabít vraha**. "
                "⚠️ Vrahova **Mačeta** přebíjí všechny zbraně.\n\n"
                "**Generátor:** EXIT je uzamčen. Tři ⛽ kanystry musí být vloženy do generátoru v exit místnosti — "
                "pak lze zadat kód a uprchnout.\n\n"
                "**Hlasování:** Speciální místnost má 🔴 červené tlačítko — aktivuje globální hlasování o vrahovi.\n\n"
                "**Třídy nevinných:** Detektiv 🕵️ (pistole) · Doktor 💊 (lékárnička) · "
                "Skaut 👁️ (info zpravodaj) · Technik 📡 (skener + vzácné předměty)\n"
                "**Třídy vraha:** Manipulátor 🎭 · Pastičkář 🪤 · Sériový vrah 🔪\n\n"
                f"*Mapa: {rows}×{cols} místností. Všichni začínáte společně — pak se cesty rozejdou.*"
            ),
            color=0x8B0000,
        )
        ready_view = TutorialReadyView(players, self, channel.id)
        await channel.send(
            embed=tutorial_embed,
            view=ready_view,
            content=(
                "📖 Přečtěte si pravidla a klikněte **✅ Připraven/a**. "
                "Hra začne, jakmile jsou všichni připraveni (nebo za 90 s automaticky)."
            ),
        )
        await channel.send(f"🚪 **Door Labyrinth** — Vytvářejí se místnosti ({rows}×{cols})…")

        for room_id in room_ids:
            if room_id not in occupied:
                continue
            await self._ensure_room_thread(channel, game, room_id)
            await asyncio.sleep(0.5)

        skaut_uid = next(
            (uid for uid, p in player_data.items() if p["role"] == "skaut"),
            None
        )

        for m in players:
            uid = str(m.id)
            pdata = player_data[uid]
            role = pdata["role"]
            role_data = ROLE_INFO.get(role, {})

            if uid == murderer_uid_str:
                role_text = role_data.get("description", "💀 **JSI VRAH!**")
            elif role == "blázen":
                fake = random.choice([r for r in ROLE_INFO if ROLE_INFO[r]["team"] == "innocent" and r != "blázen"])
                player_data[uid]["fake_role"] = fake
                role_text = ROLE_INFO[fake]["description"]
            else:
                role_text = role_data.get("description", "Nevinný")

            dm_embed = discord.Embed(
                title="🚪 Door Labyrinth — Tvoje role",
                description=f"{role_text}\n\nHra začala v {channel.mention}!",
                color=0x8B0000 if uid == murderer_uid_str else 0x1E90FF,
            )
            dm_embed.add_field(
                name="Tvoje předměty",
                value=item_list_str(pdata["items"]) or "žádné",
                inline=False,
            )
            dm_embed.set_footer(text="Tuto zprávu vidíš jen ty.")

            if uid == murderer_uid_str and role == "manipulátor" and skaut_uid:
                skaut_name = player_data[skaut_uid]["name"]
                dm_embed.add_field(name="🎯 Skaut je:", value=f"**{skaut_name}**", inline=False)

            try:
                await m.send(embed=dm_embed)
            except discord.Forbidden:
                pass

        for m in players:
            uid = str(m.id)
            thread_id = game["map"][player_data[uid]["room"]]["thread_id"]
            if thread_id:
                thread = channel.guild.get_channel_or_thread(thread_id)
                if thread:
                    try:
                        await thread.add_user(m)
                    except Exception:
                        pass

        await ready_view.wait_ready()
        await channel.send("⚔️ **Všichni jsou připraveni — hra začíná!**")
        await self._start_round(channel.id)

    # ── Vlákno místnosti ─────────────────────────────────────────────────────

    async def _ensure_room_thread(self, channel: discord.TextChannel,
                                   game: dict, room_id: str) -> discord.Thread | None:
        room = game["map"][room_id]
        if room["thread_id"]:
            return channel.guild.get_channel_or_thread(room["thread_id"])
        room_data = game["map"][room_id]
        custom_name = room_data.get("custom_name")
        thread_name = f"🚪 {custom_name or ('Místnost ' + room_id)}"
        try:
            thread = await channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                invitable=False,
            )
            room["thread_id"] = thread.id
            return thread
        except Exception as e:
            print(f"[Labyrinth] Chyba při vytváření vlákna {room_id}: {e}")
            return None

    # ── Kolo ─────────────────────────────────────────────────────────────────

    async def _start_round(self, channel_id: int):
        game = self.active_games.get(channel_id)
        if not game:
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            return

        game["round"] += 1
        current_round = game["round"]

        # Auto-odhalení exitu po N kolech
        n_rooms_total = len(game["map"])
        auto_reveal_at = max(3, n_rooms_total // 3)
        if current_round == auto_reveal_at and not game.get("exit_announced"):
            exit_room_id = game["exit_room"]
            game["exit_announced"] = exit_room_id
            murderer_uid_auto = game.get("murderer_uid", "")
            for uid, pdata_auto in game["players"].items():
                if not pdata_auto["alive"] or uid == murderer_uid_auto:
                    continue
                tid = game["map"][pdata_auto["room"]].get("thread_id")
                if tid:
                    rt = channel.guild.get_channel_or_thread(tid)
                    if rt:
                        try:
                            await rt.send(
                                f"🧭 **Záhadná síla vede vaše kroky…** EXIT se nachází v místnosti **{exit_room_id}**."
                            )
                        except Exception:
                            pass

        # Reset per-round flagů
        for pdata in game["players"].values():
            pdata["searched_this_round"] = False
            pdata["scanned_this_round"] = False
            pdata["shot_this_round"] = False
            pdata["shoot_target"] = None
            pdata["door_assignment"] = None
            if pdata.get("pistol_cooldown", 0) > 0:
                pdata["pistol_cooldown"] -= 1

        # Amulet Druhé Naděje: oživení čekajících
        murderer_pdata = game["players"].get(game["murderer_uid"], {})
        murderer_room = murderer_pdata.get("room") if murderer_pdata.get("alive") else None
        still_pending = []
        for revival in game.get("pending_revivals", []):
            r_uid = revival["uid"]
            r_room_id = revival["room_id"]
            revival_round = revival.get("round", 0)
            force_revive = (current_round - revival_round) >= 3
            if murderer_room != r_room_id or force_revive:
                r_pdata = game["players"][r_uid]
                r_pdata["alive"] = True
                r_pdata["room"] = r_room_id
                game["map"][r_room_id]["players"].append(r_uid)
                game["map"][r_room_id]["bodies"] = [
                    b for b in game["map"][r_room_id]["bodies"] if b["uid"] != r_uid
                ]
                r_member = channel.guild.get_member(int(r_uid))
                if r_member:
                    r_tid = game["map"][r_room_id]["thread_id"]
                    if r_tid:
                        r_thread = channel.guild.get_channel_or_thread(r_tid)
                        if r_thread:
                            try:
                                await r_thread.add_user(r_member)
                                await r_thread.send(f"🔮 **{r_pdata['name']}** byl/a oživena Amuletem Druhé Naděje!")
                            except Exception:
                                pass
                    try:
                        await r_member.send(
                            f"🔮 Amulet tě oživil! Vrah opustil místnost **{r_room_id}**. Jsi zpět ve hře!"
                        )
                    except discord.Forbidden:
                        pass
            else:
                still_pending.append(revival)
        game["pending_revivals"] = still_pending

        alive = alive_players(game)
        game["pending_choices"] = len(alive)
        game["movement_triggered"] = False

        for uid in alive:
            pdata = game["players"][uid]
            if pdata.get("trapped"):
                pdata["door_assignment"] = pdata["room"]
                game["pending_choices"] = max(0, game["pending_choices"] - 1)

        self._door_views[channel_id] = {}
        occupied_rooms = set(game["players"][uid]["room"] for uid in alive)

        for room_id in occupied_rooms:
            room = game["map"][room_id]
            thread_id = room["thread_id"]
            if not thread_id:
                thread = await self._ensure_room_thread(channel, game, room_id)
                if not thread:
                    continue
            else:
                thread = channel.guild.get_channel_or_thread(thread_id)
                if not thread:
                    continue

            players_here = [
                game["players"][u]["name"]
                for u in room["players"]
                if game["players"][u]["alive"]
            ]
            bodies_here = []
            for b in room["bodies"]:
                body_loot = item_list_str(b.get("items", []))
                loot_str = f" — u těla: {body_loot}" if body_loot else ""
                bodies_here.append(
                    f"💀 Tělo hráče **{b['name']}** (leží tu {current_round - b['round']} kol){loot_str}"
                )

            room_name = room.get("custom_name") or room_id
            embed = discord.Embed(
                title=f"Kolo {current_round} — {room_name}",
                description=room["description"],
                color=0x4B0082,
            )
            embed.add_field(name="Hráči v místnosti",
                            value=", ".join(players_here) or "nikdo", inline=False)
            if bodies_here:
                embed.add_field(name="Těla", value="\n".join(bodies_here), inline=False)

            n_doors = len(room["connections"])
            dice_flavor = (
                f"Před vámi stojí {n_doors} {'dveře' if n_doors == 2 else 'dveří' if n_doors >= 5 else 'dveře'}. "
                "Arion hodí kostkami — číslo na každé kostce udává kapacitu průchodu."
            )
            exit_notice = ""
            if game.get("exit_opened"):
                exit_notice = "\n🚪 **EXIT JE OTEVŘEN! Vstup volný pro všechny!**"
            elif game.get("exit_announced"):
                exit_notice = "\n📍 **EXIT byl nalezen** — zkontroluj svůj panel akcí."
            embed.add_field(name="🎲 Pohyb", value=dice_flavor + exit_notice, inline=False)

            if room.get("chest"):
                chest = room["chest"]
                chest_status = (
                    "🔒 **Zamčená truhla** — prohledej místnost, možná najdeš klíč."
                    if chest["locked"] else "📦 **Truhla je otevřena.**"
                )
                embed.add_field(name="📦 Truhla", value=chest_status, inline=False)

            if room.get("ghost_arion") and not game.get("ghost_arion_used"):
                embed.add_field(name="🐱 Duch Temné Arion",
                                value="*Přízračná kočka zahalená temnou aurou se na tebe dívá. Něco nabízí…*",
                                inline=False)

            if room["is_exit"] and game.get("exit_announced"):
                gen_fuel = game.get("generator_fuel", 0)
                if game.get("generator_started"):
                    gen_field = "✅ **Generátor běží!** Zadej kód a unikni."
                else:
                    missing = 3 - gen_fuel
                    gen_field = f"⛽ **Generátor: {gen_fuel}/3** — chybí {missing} {'kanystr' if missing == 1 else 'kanystry' if missing <= 4 else 'kanystru'}"
                embed.add_field(name="🔌 Generátor", value=gen_field, inline=False)

            embed.add_field(name="🗺️ Mapa", value=render_map(game, room_id, hide_exit=True), inline=False)

            trapped_here = [
                game["players"][u]["name"]
                for u in room["players"]
                if game["players"][u]["alive"] and game["players"][u].get("trapped")
            ]
            if trapped_here:
                embed.add_field(name="🪤 Hráči v pasti",
                                value=f"{', '.join(trapped_here)} — nemohou odejít", inline=False)
            embed.set_footer(text="Zvol dveře | 🎒 Inventář → tlačítko níže")

            view = DoorChoiceView(self, game, room_id)
            self._door_views[channel_id][room_id] = view
            await thread.send(embed=embed, view=view)

            # Skaut intel
            murderer_role_here = game["players"][game["murderer_uid"]]["role"]
            manipulator_in_room = (
                murderer_role_here == "manipulátor"
                and game["players"][game["murderer_uid"]].get("alive")
                and game["players"][game["murderer_uid"]]["room"] == room_id
            )
            scouts_here = [
                u for u in room["players"]
                if game["players"][u]["alive"] and game["players"][u]["role"] == "skaut"
            ]
            for scout_uid in scouts_here:
                scout_member = channel.guild.get_member(int(scout_uid))
                if not scout_member:
                    continue
                if manipulator_in_room:
                    alive_uids = alive_players(game)
                    fake_names = [game["players"][u]["name"]
                                  for u in random.sample(alive_uids, min(2, len(alive_uids)))]
                    scout_name = game["players"][scout_uid]["name"]
                    try:
                        await scout_member.send(
                            f"👁️ **Skaut — Místnost {room_id}:**\n"
                            f"Minulé kolo tu bylo: **{', '.join(fake_names)}**"
                        )
                    except discord.Forbidden:
                        pass
                    m_member = channel.guild.get_member(int(game["murderer_uid"]))
                    if m_member:
                        try:
                            await m_member.send(
                                f"🎭 **Korupce úspěšná!** Skaut **{scout_name}** v místnosti {room_id} "
                                f"dostal falešné informace."
                            )
                        except discord.Forbidden:
                            pass
                else:
                    code_hints = []
                    for r_id, r_data in game["map"].items():
                        if r_data.get("code_number") is not None and not r_data.get("code_found"):
                            code_hints.append(room_direction(room_id, r_id))
                    hint_str = (
                        f"\n🔍 Hint: nenalezené kódy jsou směrem {', '.join(sorted(set(code_hints))[:2])}"
                        if code_hints else ""
                    )
                    vote_room_id = game.get("vote_room_id")
                    if vote_room_id and not game.get("vote_used") and vote_room_id != room_id:
                        hint_str += f"\n🔴 Hlasovací místnost je směrem **{room_direction(room_id, vote_room_id)}**"
                    chest_room_id = game.get("chest_room")
                    if chest_room_id and game["map"][chest_room_id].get("chest", {}).get("locked") and chest_room_id != room_id:
                        hint_str += f"\n📦 Truhla je směrem **{room_direction(room_id, chest_room_id)}**"
                    if not game.get("ghost_arion_used"):
                        ghost_room = next(
                            (r for r, d in game["map"].items() if d.get("ghost_arion")), None
                        )
                        if ghost_room and ghost_room != room_id:
                            hint_str += f"\n🐱 Duch Arion je někde směrem **{room_direction(room_id, ghost_room)}**"
                    if current_round == 1:
                        dark_count = sum(1 for r in game["map"].values() if r.get("dark"))
                        total_codes = game.get("total_codes", 6)
                        try:
                            await scout_member.send(
                                f"👁️ **Skaut — Kolo 1, Startovní intel:**\n"
                                f"Mapa má **{dark_count}** tmavých místností.\n"
                                f"Celkem čísel kódu k nalezení: **{total_codes}**{hint_str}"
                            )
                        except discord.Forbidden:
                            pass
                    else:
                        prev_names = [game["players"][u]["name"]
                                      for u in room["last_round_players"] if u in game["players"]]
                        try:
                            await scout_member.send(
                                f"👁️ **Skaut — Místnost {room_id}:**\n"
                                f"Minulé kolo tu bylo: **{', '.join(prev_names) or 'nikdo'}**{hint_str}"
                            )
                        except discord.Forbidden:
                            pass

        # Souhrn kola v hlavním kanálu
        found_codes = game.get("found_codes", [])
        total_codes = game.get("total_codes", 6)
        round_embed = discord.Embed(title=f"🚪 Kolo {current_round} — přehled", color=0x4B0082)
        round_embed.add_field(name="🟢 Živí hráči", value=str(len(alive)), inline=True)
        round_embed.add_field(name="🔢 Kód", value=f"{len(found_codes)}/{total_codes}", inline=True)
        gen_fuel = game.get("generator_fuel", 0)
        gen_status = "✅ Běží" if game.get("generator_started") else f"⛽ {gen_fuel}/3"
        round_embed.add_field(name="🔌 Generátor", value=gen_status, inline=True)
        await channel.send(embed=round_embed)

        # Spectator stats
        spec_id = game.get("spectator_thread_id")
        if spec_id:
            spec_thread = channel.guild.get_channel_or_thread(spec_id)
            if spec_thread:
                alive_names = [game["players"][u]["name"] for u in alive]
                dead_names = [p["name"] for p in game["players"].values()
                              if not p["alive"] and not p.get("escaped")]
                escaped_names = [p["name"] for p in game["players"].values() if p.get("escaped")]
                spec_embed = discord.Embed(title=f"📊 Kolo {current_round} — Přehled hry", color=0x555555)
                spec_embed.add_field(name=f"🟢 Živí ({len(alive_names)})",
                                     value=", ".join(alive_names) or "—", inline=False)
                if escaped_names:
                    spec_embed.add_field(name=f"🏃 Uprchlí ({len(escaped_names)})",
                                         value=", ".join(escaped_names), inline=False)
                if dead_names:
                    spec_embed.add_field(name=f"💀 Mrtví ({len(dead_names)})",
                                         value=", ".join(dead_names), inline=False)
                try:
                    await spec_thread.send(embed=spec_embed)
                except Exception:
                    pass

    # ── Pohyb ─────────────────────────────────────────────────────────────────

    async def _execute_movement(self, channel_id: int):
        game = self.active_games.get(channel_id)
        if not game:
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            return

        for room_id, room in game["map"].items():
            room["last_round_players"] = list(room["players"])

        alive = alive_players(game)
        movements: dict[str, tuple[str, str]] = {}

        for uid in alive:
            pdata = game["players"][uid]
            dest = pdata.get("door_assignment")
            if not dest or pdata.get("trapped"):
                dest = pdata["room"]
            movements[uid] = (pdata["room"], dest)

        for room in game["map"].values():
            room["players"] = []

        for uid, (from_room, to_room) in movements.items():
            game["players"][uid]["room"] = to_room
            game["map"][to_room]["players"].append(uid)

        for uid, (from_room, to_room) in movements.items():
            if from_room == to_room:
                continue
            member = channel.guild.get_member(int(uid))
            if not member:
                continue

            old_tid = game["map"][from_room]["thread_id"]
            if old_tid:
                old_thread = channel.guild.get_channel_or_thread(old_tid)
                if old_thread:
                    try:
                        await old_thread.remove_user(member)
                    except Exception:
                        pass

            room_data = game["map"][to_room]
            if not room_data["thread_id"]:
                new_thread = await self._ensure_room_thread(channel, game, to_room)
                await asyncio.sleep(0.3)
            else:
                new_thread = channel.guild.get_channel_or_thread(room_data["thread_id"])
            if new_thread:
                try:
                    await new_thread.add_user(member)
                except Exception:
                    pass

        for uid in alive_players(game):
            game["players"][uid]["trapped"] = False

        await self._process_arrivals(channel_id)

    # ── Příchody ─────────────────────────────────────────────────────────────

    async def _process_arrivals(self, channel_id: int):
        game = self.active_games.get(channel_id)
        if not game:
            return

        channel = self.bot.get_channel(channel_id)
        murderer_uid = game["murderer_uid"]
        murderer_pdata = game["players"].get(murderer_uid, {})

        # Pasti
        for room_id, trap_info in list(game.get("traps", {}).items()):
            room = game["map"].get(room_id)
            if not room:
                continue
            players_here = [u for u in room["players"] if game["players"][u]["alive"]]
            for uid in players_here:
                if uid == murderer_uid:
                    continue
                pdata = game["players"][uid]
                if not pdata.get("trapped"):
                    pdata["trapped"] = True
                    thread_id = room["thread_id"]
                    if thread_id:
                        rt = channel.guild.get_channel_or_thread(thread_id)
                        if rt:
                            try:
                                await rt.send(f"🪤 **{pdata['name']}** se chytil/a do pasti!")
                            except Exception:
                                pass
                    member = channel.guild.get_member(int(uid))
                    if member:
                        try:
                            await member.send(f"🪤 Chytil/a jsi se do pasti v místnosti **{room_id}**!")
                        except discord.Forbidden:
                            pass
            if murderer_pdata.get("alive") and murderer_pdata.get("room") == room_id:
                trapped_victims = [u for u in players_here
                                   if game["players"][u].get("trapped") and u != murderer_uid]
                if trapped_victims:
                    victim_uid = trapped_victims[0]
                    murderer_member = channel.guild.get_member(int(murderer_uid))
                    if murderer_member:
                        view = MurderView(self, game, murderer_uid, victim_uid)
                        victim_name = game["players"][victim_uid]["name"]
                        try:
                            await murderer_member.send(
                                f"🪤 **{victim_name}** je chycen/a v pasti v místnosti {room_id}!\n"
                                f"Máš 60 sekund na rozhodnutí.",
                                view=view,
                            )
                        except discord.Forbidden:
                            pass
            game["traps"].pop(room_id, None)
            room["trap"] = None

        # Příležitost k vraždě
        if murderer_pdata.get("alive"):
            m_room = murderer_pdata["room"]
            players_with_murderer = [
                u for u in game["map"][m_room]["players"]
                if game["players"][u]["alive"]
            ]
            if len(players_with_murderer) == 2:
                victim_uid = next(u for u in players_with_murderer if u != murderer_uid)
                murderer_member = channel.guild.get_member(int(murderer_uid))
                if murderer_member:
                    view = MurderView(self, game, murderer_uid, victim_uid)
                    victim_name = game["players"][victim_uid]["name"]
                    try:
                        await murderer_member.send(
                            f"🔪 Jsi sám/sama s **{victim_name}** v místnosti {m_room}!\n"
                            f"Máš 60 sekund na rozhodnutí.",
                            view=view,
                        )
                    except discord.Forbidden:
                        pass

        # Action views
        await asyncio.sleep(1)
        alive = alive_players(game)
        occupied_rooms = set(game["players"][uid]["room"] for uid in alive)

        round_event = asyncio.Event()
        game["round_done_event"] = round_event
        game["actions_done"] = set()

        for room_id in occupied_rooms:
            room = game["map"][room_id]
            thread_id = room["thread_id"]
            if not thread_id:
                continue
            thread = channel.guild.get_channel_or_thread(thread_id)
            if not thread:
                continue

            players_here = [
                game["players"][u]["name"]
                for u in room["players"]
                if game["players"][u]["alive"]
            ]
            action_view = RoomActionView(self, game, room_id)
            await thread.send(
                f"**Kolo {game['round']} — Fáze akcí** "
                f"({len(players_here)} {'hráč' if len(players_here) == 1 else 'hráčů'})\n"
                f"⏱️ Máte **60 sekund** na akce, nebo klikněte ✅ Zakončit tah.",
                view=action_view,
            )

        try:
            await asyncio.wait_for(round_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass

        if channel_id not in self.active_games:
            return

        if game.get("vote_in_progress") and game.get("vote_event"):
            try:
                await asyncio.wait_for(game["vote_event"].wait(), timeout=200)
            except asyncio.TimeoutError:
                game["vote_in_progress"] = False

        if channel_id not in self.active_games:
            return

        win = check_win(game)
        if win:
            await self._end_game(channel_id, win)
        else:
            await self._start_round(channel_id)

    # ── Svíčka ───────────────────────────────────────────────────────────────

    async def _light_candle_cb(self, game: dict, room_id: str,
                                uid: str, channel: discord.TextChannel | None):
        pdata = game["players"].get(uid)
        if not pdata or not pdata["alive"]:
            return False, "Nejsi aktivní hráč."
        room = game["map"][room_id]
        if not room.get("dark") or room.get("candle_lit"):
            return False, "V místnosti není tma nebo svíčka již hoří."
        if "svíčka" not in pdata["items"]:
            return False, "❌ Nemáš svíčku."
        if "zapalovač" not in pdata["items"]:
            return False, "❌ Nemáš zapalovač."
        pdata["items"].remove("svíčka")
        room["candle_lit"] = True
        if channel:
            thread_id = room["thread_id"]
            if thread_id:
                rt = channel.guild.get_channel_or_thread(thread_id)
                if rt:
                    try:
                        await rt.send(f"🕯️ **{pdata['name']}** zapálil/a svíčku! Místnost **{room_id}** je nyní osvětlena.")
                    except Exception:
                        pass
        return True, "✅ Svíčka zapálena! Místnost je nyní trvale osvětlena."

    # ── Hlasování ────────────────────────────────────────────────────────────

    async def _vote_trigger_cb(self, game: dict, room_id: str,
                                triggerer_uid: str, channel: discord.TextChannel | None):
        if game.get("vote_used"):
            return False, "Hlasování již proběhlo."
        if not channel:
            return False, "Interní chyba — kanál nenalezen."
        game["vote_used"] = True
        game["vote_in_progress"] = True
        game["vote_event"] = asyncio.Event()
        triggerer_name = game["players"][triggerer_uid]["name"]

        alive = alive_players(game)
        innocents_in_vote = [u for u in alive if u != game["murderer_uid"]]
        suspect_options = [
            discord.SelectOption(label=game["players"][u]["name"], value=u, emoji="👤")
            for u in alive
        ]
        if not suspect_options:
            game["vote_in_progress"] = False
            game["vote_event"].set()
            return False, "Žádní hráči k obvinění."

        await channel.send(
            f"🔴 **{triggerer_name}** stiskl/a červené tlačítko v místnosti {room_id}!\n"
            f"**Globální hlasování!** Nevinní mají **60 sekund** na poradní vlákno — pak proběhne tajné DM hlasování.\n"
            f"⏸️ *Pohyb v labyrintu je dočasně pozastaven do výsledku hlasování.*"
        )

        async def run_vote():
            def _end_vote():
                game["vote_in_progress"] = False
                if "vote_event" in game:
                    game["vote_event"].set()

            conf_thread = None
            try:
                conf_thread = await channel.create_thread(
                    name="🗳️ Poradní vlákno — Kdo je vrah?",
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                )
                for inn_uid in innocents_in_vote:
                    member = channel.guild.get_member(int(inn_uid))
                    if member:
                        try:
                            await conf_thread.add_user(member)
                        except Exception:
                            pass
                await conf_thread.send(
                    "🗳️ **Poradní vlákno** — máte **60 sekund** na diskuzi.\n"
                    "Vrah zde není přítomen. Po uplynutí času dostanete DM s hlasovacím lístkem."
                )
            except Exception as e:
                print(f"[Labyrinth] Konferenční vlákno: {e}")

            await asyncio.sleep(60)

            if conf_thread:
                try:
                    await conf_thread.send("⏱️ Diskuze skončila. Probíhá tajné hlasování v DM…")
                    await conf_thread.edit(archived=True)
                except Exception:
                    pass

            async def send_vote_dms(options: list, v_counts: dict, v_voted: set, v_lock, suffix: str):
                for u in innocents_in_vote:
                    member = channel.guild.get_member(int(u))
                    if not member:
                        continue
                    select = discord.ui.Select(
                        placeholder="Kdo je vrah?",
                        options=options[:25],
                        custom_id=f"vote_sel_{u}_{suffix}",
                    )

                    async def make_cb(voter_uid: str):
                        async def cb(si: discord.Interaction):
                            if str(si.user.id) != voter_uid:
                                await si.response.send_message("To není tvůj hlas.", ephemeral=True)
                                return
                            async with v_lock:
                                if voter_uid in v_voted:
                                    await si.response.send_message("Už jsi hlasoval/a.", ephemeral=True)
                                    return
                                v_voted.add(voter_uid)
                                v_counts[si.data["values"][0]] = v_counts.get(si.data["values"][0], 0) + 1
                            await si.response.send_message("✅ Tvůj hlas byl zaznamenán.", ephemeral=True)
                        return cb

                    select.callback = await make_cb(u)
                    v_view = discord.ui.View(timeout=60)
                    v_view.add_item(select)
                    header = (
                        "🗳️ **Druhé kolo hlasování** (remíza) — vyber z remízujících:"
                        if suffix == "r2" else "🗳️ **Hlasování!** Kdo je vrah?"
                    )
                    try:
                        await member.send(header, view=v_view)
                    except discord.Forbidden:
                        pass

            async def resolve(counts: dict, is_retry: bool = False):
                if not counts:
                    await channel.send("🔴 Hlasování skončilo bez výsledku. **Hra pokračuje!** 🔪")
                    _end_vote()
                    return

                max_v = max(counts.values())
                top = [u for u, c in counts.items() if c == max_v]

                if len(top) > 1 and not is_retry:
                    names_tied = ", ".join(game["players"][u]["name"] for u in top)
                    await channel.send(
                        f"🤝 **Remíza!** Nejvíce hlasů: **{names_tied}**.\n**Druhé kolo hlasování.**"
                    )
                    r2_counts: dict[str, int] = {}
                    r2_lock = asyncio.Lock()
                    r2_voted: set[str] = set()
                    tied_opts = [
                        discord.SelectOption(label=game["players"][u]["name"], value=u, emoji="👤")
                        for u in top
                    ]
                    await send_vote_dms(tied_opts, r2_counts, r2_voted, r2_lock, suffix="r2")
                    await asyncio.sleep(60)
                    await resolve(r2_counts, is_retry=True)
                    return

                if len(top) > 1:
                    await channel.send("🤝 Ani druhé kolo nepřineslo shodu. **Hra pokračuje!** 🔪")
                    _end_vote()
                    return

                accused_uid = top[0]
                accused_name = game["players"][accused_uid]["name"]
                correct = accused_uid == game["murderer_uid"]
                result_lines = [
                    f"**{game['players'][u]['name']}**: {c} hlasů"
                    for u, c in sorted(counts.items(), key=lambda x: x[1], reverse=True)
                ]
                embed = discord.Embed(
                    title="🗳️ Výsledky hlasování",
                    description="\n".join(result_lines),
                    color=0x27AE60 if correct else 0x8B0000,
                )
                embed.add_field(name="Obviněný", value=f"**{accused_name}**", inline=True)
                embed.add_field(
                    name="Výsledek",
                    value="✅ Správně! Vrah odhalen!" if correct else "❌ Špatně! Vrah unikl.",
                    inline=True,
                )
                await channel.send(embed=embed)
                _end_vote()
                if correct:
                    await self._end_game(channel.id, "innocents")
                else:
                    await channel.send("**Hra pokračuje!** Vrah je stále na svobodě. 🔪")

            vote_counts: dict[str, int] = {}
            vote_lock = asyncio.Lock()
            voted_uids: set[str] = set()
            await send_vote_dms(suspect_options, vote_counts, voted_uids, vote_lock, suffix="r1")
            await asyncio.sleep(60)
            await resolve(vote_counts)

        asyncio.create_task(run_vote())
        return True, "✅ Poradní vlákno se otevírá — za 60 sekund dostanete DM s hlasovacím lístkem."

    # ── Past ──────────────────────────────────────────────────────────────────

    async def _trap_place_cb(self, game: dict, room_id: str,
                              uid: str, channel: discord.TextChannel | None):
        if uid != game["murderer_uid"]:
            return False, "Pouze Pastičkář může klást pasti."
        if game["players"][uid]["role"] != "pastičkář":
            return False, "Pouze Pastičkář může klást pasti."
        room = game["map"][room_id]
        if room.get("trap"):
            return False, "V místnosti již past je."
        room["trap"] = {"placed_by": uid, "round": game["round"]}
        game["traps"][room_id] = room["trap"]
        return True, f"🪤 Past byla položena v místnosti **{room_id}**."

    # ── Kanystr ───────────────────────────────────────────────────────────────

    async def _handle_fuel_deposit(self, game: dict, room_id: str,
                                    uid: str, channel: discord.TextChannel | None):
        if not channel:
            return False, "Interní chyba — kanál nenalezen."
        pdata = game["players"].get(uid)
        if not pdata or not pdata["alive"]:
            return False, "Nejsi aktivní hráč."
        if uid == game.get("murderer_uid"):
            return False, "❌ Tuto akci nemůžeš provést."
        if game.get("generator_started"):
            return False, "Generátor už běží."
        if "kanystr" not in pdata["items"]:
            return False, "❌ Nemáš kanystr."
        room = game["map"][room_id]
        if not room.get("is_exit"):
            return False, "Generátor je pouze u výstupu."

        pdata["items"].remove("kanystr")
        game["generator_fuel"] = game.get("generator_fuel", 0) + 1
        fuel = game["generator_fuel"]

        thread_id = room.get("thread_id")
        rt = channel.guild.get_channel_or_thread(thread_id) if thread_id else None

        if fuel >= 3:
            game["generator_started"] = True
            total_codes = game.get("total_codes", 6)
            found = len(game.get("found_codes", []))
            if rt:
                try:
                    await rt.send(
                        f"🔌 **Generátor se nastartoval!** {pdata['name']} vložil/a poslední kanystr.\n"
                        f"🔢 Kód: {found}/{total_codes} čísel nalezeno."
                    )
                except Exception:
                    pass
            return True, "✅ Třetí kanystr vložen — **generátor startuje!**"

        if rt:
            try:
                await rt.send(f"⛽ **{pdata['name']}** vložil/a kanystr. Palivo: **{fuel}/3**")
            except Exception:
                pass
        return True, f"⛽ Kanystr vložen. Palivo generátoru: **{fuel}/3**. Potřeba ještě {3 - fuel}."

    # ── Osvobození z pasti ────────────────────────────────────────────────────

    async def _free_cb(self, game: dict, room_id: str,
                        liberator_uid: str, target_uid: str,
                        channel: discord.TextChannel | None):
        target = game["players"].get(target_uid)
        if not target or not target.get("trapped"):
            return False, "Tento hráč není v pasti."
        target["trapped"] = False
        lib_name = game["players"][liberator_uid]["name"]
        tgt_name = target["name"]
        if channel:
            thread_id = game["map"][room_id]["thread_id"]
            if thread_id:
                rt = channel.guild.get_channel_or_thread(thread_id)
                if rt:
                    try:
                        await rt.send(f"🔓 **{lib_name}** osvobodil/a **{tgt_name}** z pasti!")
                    except Exception:
                        pass
        return True, f"🔓 **{tgt_name}** byl/a osvobozen/a."

    # ── Masová vražda ─────────────────────────────────────────────────────────

    async def _handle_mass_murder(self, channel_id: int, murderer_uid: str,
                                   victim_uids: list[str], channel: discord.TextChannel | None):
        game = self.active_games.get(channel_id)
        if not game or not channel:
            return
        murderer_pdata = game["players"].get(murderer_uid)
        if not murderer_pdata or murderer_pdata.get("mass_kill_used"):
            return
        murderer_pdata["mass_kill_used"] = True

        killed_names = []
        for victim_uid in victim_uids[:2]:
            victim = game["players"].get(victim_uid)
            if not victim or not victim["alive"]:
                continue
            victim["alive"] = False
            room_id = victim["room"]
            body_items = victim["items"][:]
            victim["items"].clear()
            game["map"][room_id]["bodies"].append({
                "uid": victim_uid, "round": game["round"],
                "name": victim["name"], "items": body_items,
            })
            if victim_uid in game["map"][room_id]["players"]:
                game["map"][room_id]["players"].remove(victim_uid)
            killed_names.append(victim["name"])
            victim_member = channel.guild.get_member(int(victim_uid))
            await self._move_to_spectator(channel_id, victim_uid, victim_member, channel)

        if killed_names:
            m_room = murderer_pdata["room"]
            thread_id = game["map"][m_room]["thread_id"]
            if thread_id:
                rt = channel.guild.get_channel_or_thread(thread_id)
                if rt:
                    try:
                        msg = await rt.send(
                            f"💀💀 **Masová vražda!** **{', '.join(killed_names)}** byli zabiti jedním úderem!"
                        )
                        asyncio.create_task(delete_after(msg, 10.0))
                    except Exception:
                        pass

        win = check_win(game)
        if win:
            await self._end_game(channel_id, win)

    # ── Střelba ───────────────────────────────────────────────────────────────

    async def _handle_shoot(self, channel_id: int, shooter_uid: str,
                             target_uid: str, channel: discord.TextChannel | None):
        game = self.active_games.get(channel_id)
        if not game or not channel:
            return

        shooter = game["players"].get(shooter_uid)
        target = game["players"].get(target_uid)
        if not shooter or not target or not target["alive"]:
            return
        if shooter.get("pistol_cooldown", 0) > 0:
            return

        shooter["shot_this_round"] = True
        shooter["shoot_target"] = target_uid
        if "pistole" in shooter["items"]:
            shooter["items"].remove("pistole")

        target["alive"] = False
        room_id = target["room"]
        body_items_t = target["items"][:]
        target["items"].clear()
        game["map"][room_id]["bodies"].append({
            "uid": target_uid, "round": game["round"],
            "name": target["name"], "items": body_items_t,
        })
        if target_uid in game["map"][room_id]["players"]:
            game["map"][room_id]["players"].remove(target_uid)

        target_member = channel.guild.get_member(int(target_uid))

        room_thread_id = game["map"][room_id]["thread_id"]
        if room_thread_id:
            rt = channel.guild.get_channel_or_thread(room_thread_id)
            if rt:
                await rt.send(f"💥 **{shooter['name']}** vystřelil/a! **{target['name']}** byl/a zasažen/a a zemřel/a!")

        await self._move_to_spectator(channel_id, target_uid, target_member, channel)

        if target_uid == game["murderer_uid"]:
            if room_thread_id:
                rt = channel.guild.get_channel_or_thread(room_thread_id)
                if rt:
                    await rt.send("🎉 **Vrah byl zastřelen! Nevinní vyhráli!**")
            await self._end_game(channel_id, "innocents")
        else:
            win = check_win(game)
            if win:
                await self._end_game(channel_id, win)

    # ── Vražda ────────────────────────────────────────────────────────────────

    async def _handle_murder(self, channel_id: int, murderer_uid: str,
                              victim_uid: str, channel: discord.TextChannel | None):
        game = self.active_games.get(channel_id)
        if not game or not channel:
            return

        victim = game["players"].get(victim_uid)
        if not victim or not victim["alive"]:
            return

        murderer_pdata_check = game["players"].get(murderer_uid, {})
        has_machete = "mačeta" in murderer_pdata_check.get("items", [])

        defense_weapons = [w for w in ["nůž", "baseballka", "sekáček", "vrtačka"]
                           if w in victim.get("items", [])]
        if defense_weapons and not has_machete and random.random() < 0.5:
            used_weapon = defense_weapons[0]
            victim["items"].remove(used_weapon)
            murderer_pdata = game["players"][murderer_uid]
            murderer_pdata["alive"] = False
            m_room = murderer_pdata["room"]
            m_body_items = murderer_pdata["items"][:]
            murderer_pdata["items"].clear()
            game["map"][m_room]["bodies"].append({
                "uid": murderer_uid, "round": game["round"],
                "name": murderer_pdata["name"], "items": m_body_items,
            })
            if murderer_uid in game["map"][m_room]["players"]:
                game["map"][m_room]["players"].remove(murderer_uid)

            victim_member = channel.guild.get_member(int(victim_uid))
            murderer_member = channel.guild.get_member(int(murderer_uid))
            if victim_member:
                try:
                    await victim_member.send(
                        f"⚔️ Tvá **{ITEM_EMOJI.get(used_weapon, '🔪')} {used_weapon}** zasáhla! "
                        f"**{murderer_pdata['name']}** (vrah) zemřel/a! Nevinní vyhráli!"
                    )
                except discord.Forbidden:
                    pass

            rt_id = game["map"][m_room]["thread_id"]
            if rt_id:
                rt = channel.guild.get_channel_or_thread(rt_id)
                if rt:
                    await rt.send(
                        f"⚔️ **{victim['name']}** použil/a {ITEM_EMOJI.get(used_weapon, '🔪')} {used_weapon}! "
                        f"**{murderer_pdata['name']}** byl/a zabit/a — byl/a to Vrah!"
                    )
            await self._move_to_spectator(channel_id, murderer_uid, murderer_member, channel)
            await self._end_game(channel_id, "innocents")
            return

        victim["alive"] = False
        room_id = victim["room"]
        body_items_v = victim["items"][:]
        victim["items"].clear()
        game["map"][room_id]["bodies"].append({
            "uid": victim_uid, "round": game["round"],
            "name": victim["name"], "items": body_items_v,
        })
        if victim_uid in game["map"][room_id]["players"]:
            game["map"][room_id]["players"].remove(victim_uid)

        victim_member = channel.guild.get_member(int(victim_uid))
        rt_id = game["map"][room_id]["thread_id"]
        if rt_id:
            rt = channel.guild.get_channel_or_thread(rt_id)
            if rt:
                msg = await rt.send(
                    f"💀 **{victim['name']}** byl/a nalezen/a mrtvý/á. Tělo leží v místnosti {room_id}."
                )
                asyncio.create_task(delete_after(msg, 10.0))

        if "amulet" in victim.get("items", []):
            victim["items"].remove("amulet")
            game.setdefault("pending_revivals", []).append({
                "uid": victim_uid, "room_id": room_id,
                "name": victim["name"], "round": game["round"],
            })
            if victim_member:
                try:
                    await victim_member.send(
                        f"🔮 **Amulet Druhé Naděje** se aktivoval! "
                        f"Budeš oživen/a, jakmile vrah opustí místnost **{room_id}**."
                    )
                except discord.Forbidden:
                    pass
        else:
            await self._move_to_spectator(channel_id, victim_uid, victim_member, channel)

        doctors_alive = [
            u for u, p in game["players"].items()
            if p["alive"] and p["role"] == "doktor" and "lékárnička" in p["items"]
        ]
        for doc_uid in doctors_alive:
            doc_room_id = game["players"][doc_uid]["room"]
            doc_tid = game["map"][doc_room_id].get("thread_id")
            if doc_tid:
                doc_thread = channel.guild.get_channel_or_thread(doc_tid)
                if doc_thread:
                    try:
                        doc_member = channel.guild.get_member(int(doc_uid))
                        mention = doc_member.mention if doc_member else "Doktore"
                        await doc_thread.send(
                            f"💊 {mention} — **{victim['name']}** zemřel/a! Máš lékárničku — "
                            f"můžeš ho oživit v místnosti kde leží tělo."
                        )
                    except Exception:
                        pass

        win = check_win(game)
        if win:
            await self._end_game(channel_id, win)

    # ── Oživení ───────────────────────────────────────────────────────────────

    async def _handle_revive(self, channel_id: int, doctor_uid: str, target_uid: str,
                              room_id: str, channel: discord.TextChannel | None):
        game = self.active_games.get(channel_id)
        if not game or not channel:
            return

        doctor = game["players"].get(doctor_uid)
        target = game["players"].get(target_uid)
        if not doctor or not target or doctor.get("revived_this_game"):
            return

        room = game["map"][room_id]
        room["bodies"] = [b for b in room["bodies"] if b["uid"] != target_uid]
        target["alive"] = True
        target["room"] = room_id
        room["players"].append(target_uid)
        doctor["items"].remove("lékárnička")
        doctor["revived_this_game"] = True

        target_member = channel.guild.get_member(int(target_uid))
        if target_member:
            thread_id = room["thread_id"]
            if thread_id:
                thread = channel.guild.get_channel_or_thread(thread_id)
                if thread:
                    try:
                        await thread.add_user(target_member)
                    except Exception:
                        pass
            try:
                await target_member.send(
                    f"💊 **{doctor['name']}** tě oživil/a! Jsi zpět v místnosti **{room_id}**."
                )
            except discord.Forbidden:
                pass

        thread_id = room["thread_id"]
        if thread_id:
            rt = channel.guild.get_channel_or_thread(thread_id)
            if rt:
                await rt.send(f"💊 **{doctor['name']}** použil/a lékárničku a oživil/a **{target['name']}**!")

    # ── Útěk ─────────────────────────────────────────────────────────────────

    async def _handle_escape(self, channel_id: int, uid: str,
                              channel: discord.TextChannel | None):
        game = self.active_games.get(channel_id)
        if not game or not channel:
            return

        pdata = game["players"][uid]
        pdata["alive"] = False
        pdata["escaped"] = True

        room_id = pdata["room"]
        if uid in game["map"][room_id]["players"]:
            game["map"][room_id]["players"].remove(uid)

        member = channel.guild.get_member(int(uid))

        if not game.get("exit_opened"):
            game["exit_opened"] = True
            await channel.send(
                f"🚪 **{pdata['name']}** zadal/a správný kód!\n"
                f"**EXIT JE OTEVŘEN!** Ostatní nevinní se nyní mohou volně pokusit o útěk bez kódu!"
            )
        else:
            await channel.send(f"🏃 **{pdata['name']}** uprchl/a otevřenými dveřmi!")

        rt_id = game["map"][room_id]["thread_id"]
        if rt_id:
            rt = channel.guild.get_channel_or_thread(rt_id)
            if rt:
                await rt.send(f"🚪 **{pdata['name']}** prošel/la výstupem a unikl/a!")

        await self._move_to_spectator(channel_id, uid, member, channel, escaped=True)

        win = check_win(game)
        if win:
            await self._end_game(channel_id, win)

    # ── Přesun do diváků ─────────────────────────────────────────────────────

    async def _move_to_spectator(self, channel_id: int, uid: str,
                                  member: discord.Member | None,
                                  channel: discord.TextChannel,
                                  escaped: bool = False):
        game = self.active_games.get(channel_id)
        if not game or not member:
            return

        spec_id = game.get("spectator_thread_id")
        if spec_id:
            spec_thread = channel.guild.get_channel_or_thread(spec_id)
            if spec_thread:
                try:
                    await spec_thread.add_user(member)
                    status = "uprchl/a" if escaped else "byl/a eliminován/a"
                    await spec_thread.send(f"👁️ **{member.display_name}** {status}.")
                except Exception:
                    pass

        if not escaped:
            try:
                await member.send(
                    "💀 **Byl/a jsi vyřazen/a z labyrintu.**\n"
                    "Byl/a jsi přesunut/a do divácké tribuny — sleduj průběh hry, "
                    "ale nekomunikuj s aktivními hráči."
                )
            except discord.Forbidden:
                pass

        for room in game["map"].values():
            if uid in room["players"]:
                room["players"].remove(uid)
            tid = room["thread_id"]
            if tid:
                rt = channel.guild.get_channel_or_thread(tid)
                if rt:
                    try:
                        await rt.remove_user(member)
                    except Exception:
                        pass

    # ── Konec hry ────────────────────────────────────────────────────────────

    async def _end_game(self, channel_id: int, winner: str):
        game = self.active_games.pop(channel_id, None)
        if not game:
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            return

        if winner == "_cancelled":
            for room in game["map"].values():
                tid = room["thread_id"]
                if tid:
                    try:
                        rt = channel.guild.get_channel_or_thread(tid)
                        if rt:
                            await rt.edit(archived=True)
                    except Exception:
                        pass
            self._door_views.pop(channel_id, None)
            return

        murderer_uid = game["murderer_uid"]
        murderer_name = game["players"][murderer_uid]["name"]

        if winner == "innocents":
            title = "🏆 Nevinní vyhráli!"
            desc = "Podařilo se jim uniknout nebo odhalit vraha."
            color = 0x27AE60
            for uid, p in game["players"].items():
                if uid != murderer_uid and (p.get("escaped") or p.get("alive")):
                    record_win(uid)
        else:
            title = "💀 Vrah zvítězil!"
            desc = f"**{murderer_name}** eliminoval/a všechny nevinné. Nikdo neunikl."
            color = 0x8B0000
            record_win(murderer_uid)

        reveal_lines = []
        for uid, pdata in game["players"].items():
            if uid == murderer_uid:
                status_emoji, status_label = "🔪", "VRAH"
            elif pdata.get("escaped"):
                status_emoji, status_label = "🏃", "unikl/a"
            elif pdata.get("alive"):
                status_emoji, status_label = "👤", "přežil/a"
            else:
                status_emoji, status_label = "💀", "zabit/a"
            role_display = pdata["role"]
            if pdata["role"] == "blázen" and pdata.get("fake_role"):
                role_display = f"blázen *(myslel/a sis, že jsi {pdata['fake_role']})*"
            reveal_lines.append(f"{status_emoji} **{pdata['name']}** — {role_display} *({status_label})*")

        embed = discord.Embed(title=title, description=desc, color=color)
        embed.add_field(name="Vrah byl", value=f"💀 **{murderer_name}**", inline=True)
        embed.add_field(name="Kol odehráno", value=str(game["round"]), inline=True)
        embed.add_field(name="Odhalení rolí", value="\n".join(reveal_lines), inline=False)
        await channel.send(embed=embed)

        for room in game["map"].values():
            tid = room["thread_id"]
            if tid:
                try:
                    rt = channel.guild.get_channel_or_thread(tid)
                    if rt:
                        await rt.send("🔒 Hra skončila. Toto vlákno bude archivováno.")
                        await rt.edit(archived=True)
                except Exception:
                    pass

        spec_id = game.get("spectator_thread_id")
        if spec_id:
            try:
                st = channel.guild.get_channel_or_thread(spec_id)
                if st:
                    await st.edit(archived=True)
            except Exception:
                pass

        self._door_views.pop(channel_id, None)

    # ── Slash příkazy ─────────────────────────────────────────────────────────

    async def labyrinth_start(self, interaction: discord.Interaction):
        if interaction.channel.id in self.active_games:
            await interaction.response.send_message(
                "V tomto kanálu už hra běží!", ephemeral=True
            )
            return
        view = LabyrinthLobby(self, interaction.user)
        await interaction.response.send_message(embed=view._embed(), view=view)

    @app_commands.command(
        name="labyrinth_cancel",
        description="[Admin] Zruší běžící hru Door Labyrinth"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def labyrinth_cancel(self, interaction: discord.Interaction):
        game = self.active_games.get(interaction.channel.id)
        if not game:
            await interaction.response.send_message("Žádná hra neběží.", ephemeral=True)
            return
        await interaction.response.defer()
        await self._end_game(interaction.channel.id, "_cancelled")
        self.active_games.pop(interaction.channel.id, None)
        await interaction.followup.send("🚫 Hra byla zrušena adminem.")

    @labyrinth_cancel.error
    async def cancel_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Jen admin může zrušit hru.", ephemeral=True)

    @app_commands.command(
        name="labyrinth_leaderboard",
        description="Žebříček výher Door Labyrinth"
    )
    async def labyrinth_leaderboard(self, interaction: discord.Interaction):
        scores = load_scores()
        if not scores:
            await interaction.response.send_message("Žebříček je zatím prázdný.", ephemeral=True)
            return
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
        medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
        lines = []
        for i, (uid, wins) in enumerate(top):
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"<@{uid}>"
            lines.append(f"{medals[i]} **{name}** — {wins} výher")
        embed = discord.Embed(
            title="🚪 Door Labyrinth — Žebříček",
            description="\n".join(lines),
            color=0x8B0000,
        )
        embed.set_footer(text="Top 10 | počet výher")
        await interaction.response.send_message(embed=embed)
