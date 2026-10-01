import copy
import discord
from src.logic import furioku as energy
from discord.ext import commands
from discord import app_commands
from typing import Optional
import random
import datetime
import logging

logger = logging.getLogger("Spirits")

from src.utils.paths import PROFILES as DATA_FILE
from src.utils.json_utils import load_json, save_json
from src.database.characters import pkey
from src.utils.admin_gate import mark_admin

# ══════════════════════════════════════════════════════════════════════════════
# KONFIGURACE
# ══════════════════════════════════════════════════════════════════════════════

DM_ROLE_NAME = "DM"
FU_EMO       = "<:furioku:1490160933081972866>"
SPIRIT_EMO   = "👻"

ELEMENTS: dict[str, dict] = {
    "voda":      {"emoji": "💧", "color": 0x2980b9, "furioku_type": "Vodní furioka"},
    "zeme":      {"emoji": "🪨", "color": 0x8B6914, "furioku_type": "Zemní furioka"},
    "ohen":      {"emoji": "🔥", "color": 0xe74c3c, "furioku_type": "Ohnivá furioka"},
    "vzduch":    {"emoji": "🌬️", "color": 0x99d6ea, "furioku_type": "Vzdušná furioka"},
    "svetlo":    {"emoji": "✨", "color": 0xf9e547, "furioku_type": "Světelná furioka"},
    "temnota":   {"emoji": "🌑", "color": 0x2c2c3e, "furioku_type": "Temná furioka"},
    "rovnovaha": {"emoji": "⚖️", "color": 0x1d9e75, "furioku_type": "Vyvážená furioka"},
    "prazdnota": {"emoji": "🌀", "color": 0x8e44ad, "furioku_type": "Prázdná furioka"},
    "chaos":     {"emoji": "💥", "color": 0xe67e22, "furioku_type": "Chaotická furioka"},
}

def rank_xp_threshold(rank: int) -> int:
    return int(100 * (rank ** 1.6))

BREED_CHANCE: dict[int, float] = {0: 0.80, 1: 0.55, 2: 0.30, 3: 0.10}
BREED_ELEMENT_BONUS   = 0.15
BREED_ELEMENT_PENALTY = 0.10

def rank_label(rank: int) -> str:
    labels = {
        1: "Běžný",
        2: "Neobvyklý", 3: "Neobvyklý",
        4: "Vzácný",    5: "Vzácný",
        6: "Epický",    7: "Epický",
        8: "Legendární",9: "Legendární",
        10: "Mytický",
    }
    if rank >= 11:
        return f"Mimo chápání (R{rank})"
    return f"{labels.get(rank, 'Neznámý')} (R{rank})"

def rank_color(rank: int) -> int:
    if rank <= 3:  return 0x888780
    if rank <= 5:  return 0x1d9e75
    if rank <= 7:  return 0x534ab7
    if rank <= 9:  return 0xf1c40f
    return 0xe74c3c

# ══════════════════════════════════════════════════════════════════════════════
# DATOVÁ VRSTVA
# ══════════════════════════════════════════════════════════════════════════════

def _load() -> dict:
    data = load_json(DATA_FILE)
    for profile in data.values():
        energy.normalize(profile)
    return data

def _save(data: dict) -> None:
    save_json(DATA_FILE, data)

def _is_dm(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    return any(r.name == DM_ROLE_NAME for r in interaction.user.roles)

def _default_spirit(name: str, rank: int, fury: int,
                    element: str, description: str = "") -> dict:
    return {
        "name":         name,
        "rank":         rank,
        "fury":         fury,
        "element":      element,
        "description":  description,
        "xp":           0,
        "xp_threshold": rank_xp_threshold(rank),
        "total_xp":     0,
        "created_at":   datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }

# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def get_equipped_spirit(profile: dict) -> dict | None:
    spirits = energy.equipped(profile)
    return spirits[0] if spirits else None


def breeding_preview(profile, idx_a, idx_b):
    energy.normalize(profile)
    a, b = profile['spirits'][idx_a], profile['spirits'][idx_b]
    survivor, consumed = (a, b) if a['rank'] >= b['rank'] else (b, a)
    chance = BREED_CHANCE.get(abs(a['rank'] - b['rank']), 0.0)
    chance = min(1.0, chance + BREED_ELEMENT_BONUS) if a['element'] == b['element'] else max(0.0, chance - BREED_ELEMENT_PENALTY)
    gain = int(survivor['fury_max'] * .05)
    return dict(survivor=survivor, consumed=consumed, chance=chance,
                success=(survivor['rank'] + 1, survivor['fury_cur'] + consumed['fury_cur'], survivor['fury_max'] + consumed['fury_max']),
                failure=(survivor['rank'], survivor['fury_cur'] + gain, survivor['fury_max'] + gain))


def breeding_preview_embed(preview):
    survivor, consumed = preview['survivor'], preview['consumed']
    embed = discord.Embed(title="⚗️ Potvrdit šlechtění?", color=0xf39c12,
        description=f"**Přežije:** {survivor['name']}\n**Bude pohlcen:** {consumed['name']}\n"
                    "⚠️ Pohlcený duch zanikne při úspěchu i neúspěchu. Akce je nevratná.")
    for label, chance, key in [('Úspěch', preview['chance'], 'success'), ('Neúspěch', 1 - preview['chance'], 'failure')]:
        rank, current, maximum = preview[key]
        embed.add_field(name=f"{label} · {chance:.0%}", inline=False,
            value=f"Rank **{survivor['rank']} → {rank}**\nMaximum furioku **{survivor['fury_max']} → {maximum}**\n"
                  f"Aktuální energie **{survivor['fury_cur']} → {current}** (výsledek {current}/{maximum})")
    embed.set_footer(text="Přeživšímu zůstane jméno, popis, element, XP i nasazení. Při shodném ranku přežije první vybraný duch.")
    return embed


def breed_spirits(profile: dict, idx_a: int, idx_b: int) -> dict:
    spirits = profile.get("spirits", [])
    if not (0 <= idx_a < len(spirits) and 0 <= idx_b < len(spirits)):
        raise ValueError("Neplatné indexy duchů.")
    if idx_a == idx_b:
        raise ValueError("Nelze kombinovat ducha se sebou samým.")

    preview = breeding_preview(profile, idx_a, idx_b)
    stronger, weaker = preview['survivor'], preview['consumed']
    chance = preview['chance']
    success = random.random() < chance
    consumed = weaker['id']
    stronger['rank'], stronger['fury_cur'], stronger['fury_max'] = preview['success' if success else 'failure']
    stronger['fury'] = stronger['fury_max']
    stronger['xp_threshold'] = rank_xp_threshold(stronger['rank'])
    spirits[:] = [s for s in spirits if s['id'] != consumed]
    energy.normalize(profile)
    return dict(success=success, chance=chance, new_spirit=stronger if success else None,
                survivor=stronger, consumed_name=weaker['name'])

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _elem_emoji(element: str) -> str:
    return ELEMENTS.get(element.split("/")[0], {}).get("emoji", "❓")

def _spirit_line(s: dict, equipped: bool = False) -> str:
    emoji  = _elem_emoji(s.get("element", ""))
    eq     = "  ⭐ *hlavní duch*" if equipped else ""
    thresh = s.get("xp_threshold", rank_xp_threshold(s["rank"]))
    return (
        f"{SPIRIT_EMO} **{s['name']}** {emoji}  ·  {rank_label(s['rank'])}  ·  "
        f"{s.get('fury_cur', s['fury'])}/{s.get('fury_max', s['fury'])} {FU_EMO} {'💤' if s.get('fury_cur', s['fury']) == 0 else ''}  ·  XP: {s.get('xp', 0)}/{thresh}{eq}"
    )

def _spirit_embed(s: dict, title: str = None) -> discord.Embed:
    elem   = s.get("element", "?")
    emoji  = _elem_emoji(elem)
    color  = ELEMENTS.get(elem.split("/")[0], {}).get("color", rank_color(s["rank"]))
    embed  = discord.Embed(title=title or f"{SPIRIT_EMO} {s['name']}", color=color)
    embed.add_field(name="Rank",    value=rank_label(s["rank"]),       inline=True)
    embed.add_field(name="Element", value=f"{emoji} {elem}",           inline=True)
    embed.add_field(name="Furioka", value=f"{s.get('fury_cur', s['fury'])}/{s.get('fury_max', s['fury'])} {FU_EMO} {'💤' if s.get('fury_cur', s['fury']) == 0 else ''}",     inline=True)
    thresh = s.get("xp_threshold", rank_xp_threshold(s["rank"]))
    embed.add_field(
        name="Progres",
        value=f"XP: **{s.get('xp', 0)}** / {thresh}  ·  Celkem: {s.get('total_xp', 0)}",
        inline=False,
    )
    if s.get("description"):
        embed.add_field(name="Popis", value=f"*{s['description']}*", inline=False)
    embed.set_footer(text=f"Získán: {s.get('created_at', '?')[:10]}")
    return embed

# ══════════════════════════════════════════════════════════════════════════════
# CONFIRM VIEW
# ══════════════════════════════════════════════════════════════════════════════

class BreedConfirmView(discord.ui.View):
    def __init__(self, uid: str, idx_a: int, idx_b: int,
                 a_name: str, b_name: str, chance: float, expected=None):
        super().__init__(timeout=30)
        self.uid     = uid
        self.idx_a   = idx_a
        self.idx_b   = idx_b
        self.a_name  = a_name
        self.b_name  = b_name
        self.expected = copy.deepcopy(expected)
        self.chance  = chance
        self.done    = False

    async def on_timeout(self):
        if not self.done:
            for item in self.children:
                item.disabled = True

    @discord.ui.button(label="Potvrdit šlechtění", style=discord.ButtonStyle.danger, emoji="⚗️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ověř vlastnictví
        if pkey(interaction.user.id) != self.uid:
            await interaction.response.send_message("❌ Toto není tvoje šlechtění.", ephemeral=True)
            return

        if self.done:
            return await interaction.response.send_message("Toto šlechtění už bylo vyhodnoceno.", ephemeral=True)
        self.done = True
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        # Znovu načti čerstvá data (mohla se změnit)
        data    = _load()
        profile = data.get(self.uid)
        if not profile:
            await interaction.followup.send("❌ Profil nenalezen.", ephemeral=True)
            return

        spirits = profile.get("spirits", [])
        # Přeověř indexy — jména musí souhlasit
        if (self.idx_a >= len(spirits) or self.idx_b >= len(spirits)
                or spirits[self.idx_a]["name"].lower() != self.a_name.lower()
                or spirits[self.idx_b]["name"].lower() != self.b_name.lower()):
            await interaction.followup.send(
                "❌ Duchové se změnili od potvrzení. Zkus znovu.", ephemeral=True
            )
            return

        if self.expected is not None and self.expected != [spirits[self.idx_a], spirits[self.idx_b]]:
            return await interaction.followup.send("❌ Hodnoty duchů se změnily. Otevři nový náhled šlechtění.", ephemeral=True)

        try:
            result = breed_spirits(profile, self.idx_a, self.idx_b)
        except ValueError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
            return

        _save(data)
        chance_pct = int(result["chance"] * 100)

        if result["success"]:
            ns    = result["new_spirit"]
            emoji = _elem_emoji(ns["element"])
            embed = discord.Embed(
                title="✨ Šlechtění úspěšné!",
                description=(
                    f"**{self.a_name}** a **{self.b_name}** se sloučili!\n"
                    f"**{ns['name']}** přežil a zesílil; jeho identita a XP zůstávají."
                ),
                color=rank_color(ns["rank"]),
            )
            embed.add_field(name="Rank",    value=rank_label(ns["rank"]),    inline=True)
            embed.add_field(name="Element", value=f"{emoji} {ns['element']}", inline=True)
            embed.add_field(name="Furioka", value=f"{ns['fury']} {FU_EMO}",  inline=True)
            embed.set_footer(text=f"Šance byla {chance_pct}%")
        else:
            sv    = result["survivor"]
            embed = discord.Embed(
                title="💀 Šlechtění selhalo",
                description=(
                    f"**{result['consumed_name']}** byl pohlcen!\n"
                    f"**{sv['name']}** přežil a mírně zesílil ({sv['fury']} {FU_EMO})."
                ),
                color=0x888780,
            )
            embed.set_footer(text=f"Šance byla {chance_pct}%")

        await interaction.followup.send(embed=embed)

    @discord.ui.button(label="Zrušit", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if pkey(interaction.user.id) != self.uid:
            await interaction.response.send_message("❌ Toto není tvoje šlechtění.", ephemeral=True)
            return
        self.done = True
        self.stop()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="*Šlechtění zrušeno. Oba duchové přežili.*", embed=None, view=self
        )

# ══════════════════════════════════════════════════════════════════════════════
# FURIOKU: ÚTOK / OBRANA  (správa přes /staty → tlačítko Furioku)
# ══════════════════════════════════════════════════════════════════════════════
#
# Uloženo v profilu:
# Energy allocation and spirit selection are shared with combat.

PERK_JEDNOTA = "furioku_jednota"
PERK_OBRANA  = "furioku_obrana"
PERK_UTOK    = "furioku_utok"


def _furioka(profile: dict) -> dict:
    energy.normalize(profile)
    return profile['furioka']

def _owned_perks(user_id: int) -> list[str]:
    """Perky aktivní postavy — načteno z perks cogu, s bezpečným fallbackem."""
    try:
        from src.core.dnd.perks import owned_perks
        return owned_perks(user_id)
    except Exception:
        return []


def furioku_pool(profile: dict, user_id: int) -> int:
    return energy.pool(profile, _owned_perks(user_id))


def furioka_bonuses(profile: dict, user_id: int) -> tuple[int, int]:
    return energy.bonuses(profile, _owned_perks(user_id))


def furioka_absorb(profile: dict, user_id: int, incoming_dmg: int) -> tuple[int, int]:
    return energy.absorb(profile, incoming_dmg, _owned_perks(user_id))


def _furioka_embed(profile: dict, user_id: int, page: int = 0) -> discord.Embed:
    f      = _furioka(profile)
    perks  = _owned_perks(user_id)
    spirits = profile['spirits'][page * 24:(page + 1) * 24]
    pool   = furioku_pool(profile, user_id)
    fury_cur = profile.get("fury_cur", 0)

    has_jednota = PERK_JEDNOTA in perks
    has_obrana  = PERK_OBRANA  in perks
    has_utok    = PERK_UTOK    in perks

    atk, dfn = furioka_bonuses(profile, user_id)
    volne    = max(0, pool - atk - dfn)

    current, maximum = energy.totals(profile, perks)
    src = f"Furioku: **{current}/{maximum}** · Vlastní: **{fury_cur}/{profile.get('fury_max', 0)}** · Dostupné: **{pool}**"

    embed = discord.Embed(
        title=f"{FU_EMO}  Správa furioku",
        description=(f"{src}\n-# Volně k nasazení: **{volne}**\n"
                     f"-# Rozděl furioku do útoku a obrany. Se **Jednotou** můžeš "
                     f"sloučit ducha a využít i jeho furioku."),
        color=0x8e44ad,
    )
    embed.add_field(
        name="⚔️ Útok",
        value=(f"{FU_EMO} **{f['atk_amount']}**  →  **+{atk}** k dmg\n-# *1d… zbraň + {atk} furioku*"
               if has_utok else "🔒 *chybí perk Furioku: Útok*"),
        inline=True,
    )
    embed.add_field(
        name="🛡️ Obrana",
        value=(f"{FU_EMO} **{f['def_amount']}**  →  pohltí **{dfn}** dmg\n-# *zásah spotřebuje furioku*"
               if has_obrana else "🔒 *chybí perk Furioku: Obrana*"),
        inline=True,
    )

    lines = [f"{'🔗' if s['id'] in f['spirit_ids'] and has_jednota else '👻'} **{s['name']}** · {s['fury_cur']}/{s['fury_max']} {'💤' if s['fury_cur'] == 0 else ''} {'⭐ hlavní' if s['id'] == profile.get('main_spirit_id') else ''}" for s in spirits]
    embed.add_field(name="Duchové", value=("\n".join(lines)[:1000] or "Nasadit ducha: `/duch equip`."), inline=False)
    embed.add_field(name="Jednota", value="Hlavní duch dostává XP a ukazuje se v profilu. Jednotu vyber nezávisle v nabídce dole; sama XP nedává. Pořadí čerpání i sestavy nastavíš tlačítkem Sestavy a čerpání.", inline=False)

    if profile.get('main_spirit_choice_pending'):
        embed.add_field(name="Vyber hlavního ducha", value="Dříve jsi měl více nasazených duchů. Vyber jednoho v panelu; do té doby duchové XP nezískávají. Jednota zůstává zachovaná.", inline=False)
    names = {s['id']: s['name'] for s in profile['spirits']}
    names['self'] = 'vlastní'
    active = {s['id'] for s in energy.linked(profile, perks)} | {'self'}
    order = list(dict.fromkeys(f.get('source_order', []) + ['self'] + f['spirit_ids']))
    embed.add_field(name="Čerpání", value=' → '.join(names[i] for i in order if i in active)[:1000], inline=False)
    fu_perks = [p for p in perks if p.startswith("furioku_")]
    if fu_perks:
        try:
            from src.core.dnd.perks import load_perks
            all_p = load_perks()
            names = [all_p.get(pid, {}).get("name", pid) for pid in fu_perks]
        except Exception:
            names = fu_perks
        embed.add_field(name="🌀 Tvé furioku perky",
                        value=", ".join(f"`{n}`" for n in names), inline=False)

    embed.set_footer(text="⭐ Aurionis")
    return embed


class EnergyModal(discord.ui.Modal):
    def __init__(self, panel, action):
        super().__init__(title={'amount': 'Přesné přidělení energie', 'order': 'Pořadí čerpání', 'save': 'Uložit sestavu', 'load': 'Načíst sestavu', 'delete': 'Smazat sestavu'}[action])
        self.panel, self.action = panel, action
        _, p = panel._get()
        if action == 'amount':
            self.first = discord.ui.TextInput(label='Útok', default=str(p['furioka']['atk_amount']), max_length=12)
            self.second = discord.ui.TextInput(label='Obrana', default=str(p['furioka']['def_amount']), max_length=12)
            self.add_item(self.first)
            self.add_item(self.second)
        else:
            names = {s['id']: s['name'] for s in p['spirits']}
            names['self'] = 'já'
            order = list(dict.fromkeys(p['furioka'].get('source_order', []) + ['self'] + p['furioka']['spirit_ids']))
            self.first = discord.ui.TextInput(label='Jeden zdroj na řádek; vlastní energie = já' if action == 'order' else 'Název sestavy',
                style=discord.TextStyle.paragraph if action == 'order' else discord.TextStyle.short,
                default='\n'.join(names[i] for i in order if i in names)[:4000] if action == 'order' else None,
                max_length=4000 if action == 'order' else 60)
            self.add_item(self.first)

    async def on_submit(self, interaction):
        if not await self.panel._guard(interaction):
            return
        data, p = self.panel._get()
        perks = _owned_perks(self.panel.user_id)
        note = 'Nastavení uloženo.'
        try:
            if self.action == 'amount':
                energy.allocate(p, perks, int(self.first.value), int(self.second.value))
            elif self.action == 'order':
                energy.set_source_order(p, self.first.value.splitlines())
            elif self.action == 'save':
                energy.save_preset(p, self.first.value)
            elif self.action == 'load':
                note = energy.load_preset(p, self.first.value, perks)
            else:
                if p.get('furioku_presets', {}).pop(self.first.value.strip(), None) is None:
                    raise ValueError('Tato sestava neexistuje.')
        except ValueError as exc:
            return await interaction.response.send_message(f'❌ {exc}', ephemeral=True)
        _save(data)
        self.panel._build_selects()
        await interaction.response.edit_message(content=note, embed=_furioka_embed(p, self.panel.user_id, self.panel.page), view=self.panel)


class EnergySettings(discord.ui.View):
    def __init__(self, panel):
        super().__init__(timeout=300)
        for label, action in [('Pořadí čerpání', 'order'), ('Uložit sestavu', 'save'), ('Načíst sestavu', 'load'), ('Smazat sestavu', 'delete')]:
            button = discord.ui.Button(label=label)
            async def callback(interaction, action=action):
                if await panel._guard(interaction):
                    await interaction.response.send_modal(EnergyModal(panel, action))
            button.callback = callback
            self.add_item(button)


class FurioukaView(discord.ui.View):
    """Rozdělení furioku: +/- do útoku (dmg) a obrany (štít), sloučení ducha."""

    STEP = 5

    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.profile_key = pkey(user_id)
        self.page = 0
        self._build_selects()

    def _build_selects(self):
        for child in list(self.children):
            if isinstance(child, discord.ui.Select):
                self.remove_item(child)
        _, profile = self._get()
        spirits = profile.get('spirits', []) if profile else []
        pages = max(1, (len(spirits) + 23) // 24)
        self.page %= pages
        group = spirits[self.page * 24:(self.page + 1) * 24]
        for mode, row, title in [('main', 3, 'Hlavní duch · XP a profil'), ('unity', 4, 'Jednota · zapojit / odpojit ducha')]:
            options = [discord.SelectOption(label='Bez hlavního ducha' if mode == 'main' else 'Odpojit všechny', value='none')]
            for spirit in group:
                chosen = spirit['id'] == profile.get('main_spirit_id') if mode == 'main' else spirit['id'] in profile['furioka']['spirit_ids']
                label = f"{'✓ ' if chosen else ''}{spirit['name']}"
                options.append(discord.SelectOption(label=label[:100], value=spirit['id'],
                    description=f"{spirit['fury_cur']}/{spirit['fury_max']}" + (' · 💤' if spirit['fury_cur'] == 0 else '')))
            select = discord.ui.Select(placeholder=f"{title} ({self.page + 1}/{pages})", options=options, row=row)
            async def callback(interaction, select=select, mode=mode):
                if not await self._guard(interaction):
                    return
                data, profile = self._get()
                value = select.values[0]
                if value != 'none' and value not in {s['id'] for s in profile['spirits']}:
                    return await interaction.response.send_message('Duch už není ve tvé sbírce. Otevři panel znovu.', ephemeral=True)
                if mode == 'main':
                    energy.choose_main(profile, None if value == 'none' else value)
                else:
                    if PERK_JEDNOTA not in _owned_perks(self.user_id):
                        return await interaction.response.send_message('❌ Chybí perk Furioku: Jednota.', ephemeral=True)
                    ids = profile['furioka']['spirit_ids']
                    if value == 'none':
                        ids.clear()
                    elif value in ids:
                        ids.remove(value)
                    else:
                        ids.append(value)
                await self._refresh(interaction, data, profile)
            select.callback = callback
            self.add_item(select)

    @discord.ui.button(label="Další duchové", emoji="➡️", row=2)
    async def next_spirits(self, interaction, button):
        if not await self._guard(interaction):
            return
        self.page += 1
        data, profile = self._get()
        await self._refresh(interaction, data, profile)

    def _get(self):
        data = _load()
        return data, data.get(self.profile_key)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id or pkey(self.user_id) != self.profile_key:
            await interaction.response.send_message("❌ Toto není tvůj panel.", ephemeral=True)
            return False
        return True

    async def _refresh(self, interaction, data, profile):
        _save(data)
        self._build_selects()
        await interaction.response.edit_message(
            embed=_furioka_embed(profile, self.user_id, self.page), view=self)

    def _adjust(self, profile: dict, role: str, delta: int) -> str | None:
        perks = _owned_perks(self.user_id)
        need  = PERK_UTOK if role == "atk" else PERK_OBRANA
        if need not in perks:
            return f"Chybí ti perk **{'Furioku: Útok' if role=='atk' else 'Furioku: Obrana'}**."
        f   = _furioka(profile)
        key = f"{role}_amount"
        new = f[key] + delta
        if new < 0:
            return None
        other = f["def_amount"] if role == "atk" else f["atk_amount"]
        if delta > 0 and new + other > furioku_pool(profile, self.user_id):
            return "Nemáš tolik furioku v zásobě."
        f[key] = new
        return None

    @discord.ui.button(label="Přesně", row=0)
    async def exact_amount(self, interaction, button):
        if await self._guard(interaction):
            await interaction.response.send_modal(EnergyModal(self, 'amount'))

    async def _all(self, interaction, attack):
        if not await self._guard(interaction):
            return
        data, p = self._get()
        perks = _owned_perks(self.user_id)
        amount = energy.pool(p, perks)
        try:
            energy.allocate(p, perks, amount if attack else 0, 0 if attack else amount)
        except ValueError as exc:
            return await interaction.response.send_message(f'❌ {exc}', ephemeral=True)
        await self._refresh(interaction, data, p)

    @discord.ui.button(label="Vše do útoku", row=0)
    async def all_attack(self, interaction, button):
        await self._all(interaction, True)

    @discord.ui.button(label="Vše do obrany", row=1)
    async def all_defense(self, interaction, button):
        await self._all(interaction, False)

    @discord.ui.button(label="Sestavy a čerpání", row=2)
    async def settings(self, interaction, button):
        if not await self._guard(interaction):
            return
        _, p = self._get()
        names = ', '.join(p.get('furioku_presets', {})) or 'zatím žádné'
        await interaction.response.send_message('Uložené sestavy: ' + names[:1700] + '\nUložení stejného názvu přepíše sestavu. V pořadí uveď zdroje po řádcích (vlastní = já). Neuvedené zdroje se doplní na konec.', view=EnergySettings(self), ephemeral=True)

    # ── útok ──
    @discord.ui.button(label="＋5", emoji="⚔️", style=discord.ButtonStyle.danger, row=0)
    async def atk_plus(self, interaction, _b):
        if not await self._guard(interaction): return
        data, profile = self._get()
        err = self._adjust(profile, "atk", self.STEP)
        if err: return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        await self._refresh(interaction, data, profile)

    @discord.ui.button(label="－5", emoji="⚔️", style=discord.ButtonStyle.secondary, row=0)
    async def atk_minus(self, interaction, _b):
        if not await self._guard(interaction): return
        data, profile = self._get()
        self._adjust(profile, "atk", -self.STEP)
        await self._refresh(interaction, data, profile)

    # ── obrana ──
    @discord.ui.button(label="＋5", emoji="🛡️", style=discord.ButtonStyle.success, row=1)
    async def def_plus(self, interaction, _b):
        if not await self._guard(interaction): return
        data, profile = self._get()
        err = self._adjust(profile, "def", self.STEP)
        if err: return await interaction.response.send_message(f"❌ {err}", ephemeral=True)
        await self._refresh(interaction, data, profile)

    @discord.ui.button(label="－5", emoji="🛡️", style=discord.ButtonStyle.secondary, row=1)
    async def def_minus(self, interaction, _b):
        if not await self._guard(interaction): return
        data, profile = self._get()
        self._adjust(profile, "def", -self.STEP)
        await self._refresh(interaction, data, profile)

    # ── sloučit ducha ──
    @discord.ui.button(label="Sjednotit / odpojit všechny", emoji="👻", style=discord.ButtonStyle.primary, row=2)
    async def toggle_spirit(self, interaction, _b):
        if not await self._guard(interaction): return
        data, profile = self._get()
        perks = _owned_perks(self.user_id)
        if PERK_JEDNOTA not in perks:
            return await interaction.response.send_message(
                "❌ Sloučit ducha vyžaduje perk **Furioku: Jednota**.", ephemeral=True)
        if not profile['spirits']:
            return await interaction.response.send_message(
                "❌ Nemáš žádného ducha.", ephemeral=True)
        f = _furioka(profile)
        ids = [s["id"] for s in profile["spirits"]]
        f["spirit_ids"] = [] if f["spirit_ids"] == ids else ids
        f["use_spirit"] = bool(f["spirit_ids"])
        await self._refresh(interaction, data, profile)

    @discord.ui.button(label="Sundat vše", emoji="🔄", style=discord.ButtonStyle.secondary, row=2)
    async def clear(self, interaction, _b):
        if not await self._guard(interaction): return
        data, profile = self._get()
        f = _furioka(profile)
        f.update(atk_amount=0, def_amount=0)
        await self._refresh(interaction, data, profile)


async def open_furioka(interaction: discord.Interaction, user_id: int):
    """Otevře hráčský panel /furioku."""
    data = _load()
    profile = data.get(pkey(user_id))
    if not profile:
        await interaction.response.send_message(
            "Nemáš profil — projdi nejdřív tutoriálem.", ephemeral=True)
        return
    energy.normalize(profile)
    _save(data)
    if not profile.get("furioku_unlocked"):
        return await interaction.response.send_message("?????????", ephemeral=True)
    await interaction.response.send_message(
        embed=_furioka_embed(profile, user_id),
        view=FurioukaView(user_id), ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class Spirits(commands.Cog):
    # Jedna skupina /duch se v limitu 100 globálních příkazů počítá jako 1 slot,
    # ne jako 9. Subpříkazy (až 25) se do limitu nezapočítávají.
    duch = app_commands.Group(name="duch", description="Strážní duchové — správa, šlechtění a info.")

    bond = app_commands.Group(name="bond", description="[DM] RP sblížení hráče s duchem.", parent=duch)

    async def _bond_action(self, interaction, action, **kwargs):
        if not _is_dm(interaction):
            return await interaction.response.send_message("❌ Jen DM.", ephemeral=True)
        from src.logic.spirit_bond import change_bond
        try:
            result = change_bond(interaction.channel_id, action, interaction_id=interaction.id, **kwargs)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        name = discord.utils.escape_markdown(discord.utils.escape_mentions(result['spirit_name'])).replace('\n', ' ').replace('\r', ' ')
        if action == 'start':
            message = f"-# <@{result['user_id']}> se sbližuje s duchem {name}."
        elif action == 'fail':
            message = f"-# Bonding s duchem {name} selhal."
        elif result['successes'] == 3:
            message = f"-# Success · 3/3 — {name} evolvoval. Furioku {result['old_maximum']} → {result['new_maximum']}."
        else:
            message = f"-# Success · {result['successes']}/3 — {name}."
        await interaction.response.send_message(message, allowed_mentions=discord.AllowedMentions(
            users=[discord.Object(id=result['user_id'])] if action == 'start' else False, roles=False, everyone=False))

    @bond.command(name="start", description="[DM] Zahájí RP bonding s konkrétním duchem hráče.")
    @app_commands.describe(member="Hráč (aktivní postava)", duch="Jméno vlastněného ducha")
    @mark_admin
    async def bond_start(self, interaction: discord.Interaction, member: discord.Member, duch: str):
        await self._bond_action(interaction, 'start', profile_key=pkey(member.id), user_id=member.id, spirit_name=duch)

    @bond_start.autocomplete('duch')
    async def bond_spirit_names(self, interaction: discord.Interaction, current: str):
        member = getattr(interaction.namespace, 'member', None)
        if member is None:
            return []
        p = _load().get(pkey(member.id), {})
        return [app_commands.Choice(name=s['name'][:100], value=s['name']) for s in p.get('spirits', [])
                if current.casefold() in s['name'].casefold()][:25]

    @bond.command(name="success", description="[DM] Úspěch bondingu; třetí úspěch vyvolá evoluci.")
    @app_commands.describe(nove_maximum="Pouze třetí úspěch: nové maximum furioku (výchozí ×2)")
    @mark_admin
    async def bond_success(self, interaction: discord.Interaction, nove_maximum: app_commands.Range[int, 0] | None = None):
        await self._bond_action(interaction, 'success', new_maximum=nove_maximum)

    @bond.command(name="fail", description="[DM] Zruší bonding v tomto kanálu a jeho postup.")
    @mark_admin
    async def bond_fail(self, interaction: discord.Interaction):
        await self._bond_action(interaction, 'fail')

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="furioku", description="Správa vlastní energie, duchů a Jednoty.")
    @app_commands.describe(duch="Volitelně přepni Jednotu konkrétního vlastněného ducha.")
    async def furioku(self, interaction: discord.Interaction, duch: str | None = None):
        data = _load()
        profile = data.get(pkey(interaction.user.id), {})
        energy.normalize(profile)
        if not profile.get('furioku_unlocked'):
            return await interaction.response.send_message("?????????", ephemeral=True)
        if duch:
            if PERK_JEDNOTA not in _owned_perks(interaction.user.id):
                return await interaction.response.send_message("❌ Chybí perk Furioku: Jednota.", ephemeral=True)
            spirit = next((s for s in profile['spirits'] if s['name'].lower() == duch.lower()), None)
            if spirit is None:
                return await interaction.response.send_message("❌ Tento duch není ve tvé sbírce.", ephemeral=True)
            ids = profile['furioka']['spirit_ids']
            if spirit['id'] in ids:
                ids.remove(spirit['id'])
            else:
                ids.append(spirit['id'])
        _save(data)
        await open_furioka(interaction, interaction.user.id)

    # ── /duch pridat ──────────────────────────────────────────────────────────

    @duch.command(name="pridat", description="[DM] Přidá hráči nového strážného ducha.")
    @app_commands.describe(
        member="Hráč", name="Jméno ducha",
        rank="Počáteční rank (1 = slabý, 10+ = mytický)",
        fury="Kolik furioku duch přináší",
        element="Element ducha",
        description="Krátký popis (volitelné)",
    )
    @app_commands.choices(element=[
        app_commands.Choice(name=f"{v['emoji']} {k.capitalize()}", value=k)
        for k, v in ELEMENTS.items()
    ])
    @mark_admin
    async def duch_pridat(
        self, interaction: discord.Interaction,
        member: discord.Member, name: str, rank: int, fury: int,
        element: app_commands.Choice[str], description: str = "",
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        if fury < 0 or rank < 1:
            await interaction.followup.send("❌ Neplatné hodnoty.")
            return

        data    = _load()
        uid     = pkey(member.id)
        profile = data.setdefault(uid, {})
        spirits = profile.setdefault("spirits", [])

        if any(s["name"].lower() == name.lower() for s in spirits):
            await interaction.followup.send(f"❌ **{member.display_name}** už má ducha **{name}**.")
            return

        spirit = _default_spirit(name, rank, fury, element.value, description)
        spirits.append(spirit)
        energy.normalize(profile)
        _save(data)

        embed = _spirit_embed(spirit, title=f"✅ Duch přidán — {name}")
        embed.description = f"Přidán hráči **{member.display_name}**. Hlavního ducha a Jednotu vybereš přes `/furioku`."
        await interaction.followup.send(embed=embed)

    # ── /duch xp ──────────────────────────────────────────────────────────────

    @duch.command(name="xp", description="[DM] Přidej duchovi XP.")
    @app_commands.describe(member="Hráč", amount="Množství XP")
    @mark_admin
    async def duch_xp(
        self, interaction: discord.Interaction,
        member: discord.Member, amount: int,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        if amount <= 0:
            await interaction.followup.send("❌ Množství musí být kladné.")
            return

        data    = _load()
        uid     = pkey(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return

        results = energy.grant_xp(profile, amount)
        if not results:
            return await interaction.followup.send("❌ Hráč nemá vybraného hlavního ducha.")
        _save(data)
        lines = [f"👻 **{r['spirit_name']}**: +{amount} XP · rank {r['old_rank']} → {r['new_rank']}" for r in results]
        levelup = energy.rank_up_text(results)
        if levelup:
            await interaction.followup.send(embed=discord.Embed(title="⬆️ Hlavní duch postoupil!", description=levelup[:4000], color=0xf1c40f), ephemeral=False)
        else:
            await interaction.followup.send("\n".join(lines)[:1900])

    @duch.command(name="slechtit", description="Pokus o šlechtění dvou duchů — silnější může pohltit slabšího!")
    @app_commands.describe(jmeno_a="První duch; při shodném ranku přežije tento", jmeno_b="Jméno druhého ducha")
    async def duch_slechtit(
        self, interaction: discord.Interaction,
        jmeno_a: str, jmeno_b: str,
    ):
        await interaction.response.defer(ephemeral=False)
        data    = _load()
        uid     = pkey(interaction.user.id)
        profile = data.get(uid)

        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return

        spirits = profile.get("spirits", [])
        if len(spirits) < 2:
            await interaction.followup.send("❌ Potřebuješ alespoň 2 duchy pro šlechtění.")
            return

        idx_a = next((i for i, s in enumerate(spirits) if s["name"].lower() == jmeno_a.lower()), None)
        idx_b = next((i for i, s in enumerate(spirits) if s["name"].lower() == jmeno_b.lower()), None)

        if idx_a is None:
            await interaction.followup.send(f"❌ Nemáš ducha jménem **{jmeno_a}**.")
            return
        if idx_b is None:
            await interaction.followup.send(f"❌ Nemáš ducha jménem **{jmeno_b}**.")
            return
        if idx_a == idx_b:
            await interaction.followup.send("❌ Nelze kombinovat ducha se sebou samým.")
            return

        a, b = spirits[idx_a], spirits[idx_b]
        preview = breeding_preview(profile, idx_a, idx_b)
        confirm_embed = breeding_preview_embed(preview)
        view = BreedConfirmView(uid, idx_a, idx_b, a['name'], b['name'], preview['chance'], expected=[a, b])
        await interaction.followup.send(embed=confirm_embed, view=view)

    # ── /duch equip ───────────────────────────────────────────────────────────

    async def _ac_spirit_name(self, interaction: discord.Interaction, current: str):
        """Nabídne jména duchů cílové postavy (vlastní, u DM případně cizí)."""
        try:
            # cílový hráč: pokud DM zadal member v jiné option, respektuj ho
            target_id = interaction.user.id
            for opt in (interaction.data.get("options") or []):
                for sub in (opt.get("options") or [opt]):
                    if sub.get("name") == "member" and sub.get("value"):
                        target_id = int(sub["value"])
            data    = _load()
            profile = data.get(pkey(target_id)) or {}
            cur     = (current or "").lower()
            return [
                app_commands.Choice(name=f"{s['name']} ({s.get('fury', 0)} 🔥)", value=s["name"])
                for s in profile.get("spirits", [])
                if cur in s["name"].lower()
            ][:25]
        except Exception:
            logger.exception("[spirits] autocomplete jména selhal")
            return []

    @furioku.autocomplete("duch")
    async def furioku_duch_autocomplete(self, interaction: discord.Interaction, current: str):
        profile = _load().get(pkey(interaction.user.id), {})
        return [app_commands.Choice(name=s['name'][:100], value=s['name'])
                for s in profile.get('spirits', []) if current.lower() in s['name'].lower()][:25]

    @duch.command(name="equip", description="Vyber jednoho hlavního ducha pro XP a profil (DM může i jiným).")
    @app_commands.describe(name="Jméno ducha", member="[DM] Hráč (prázdné = ty)")
    @app_commands.autocomplete(name=_ac_spirit_name)
    async def duch_equip(
        self, interaction: discord.Interaction,
        name: str, member: discord.Member = None,
    ):
        await interaction.response.defer(ephemeral=True)
        # Pro sebe smí kdokoli; cizímu hráči jen DM.
        if member is not None and member.id != interaction.user.id:
            if not _is_dm(interaction):
                await interaction.followup.send("❌ Nasadit ducha jinému hráči může jen DM.")
                return
        target = member or interaction.user

        data    = _load()
        uid     = pkey(target.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{target.display_name}** nemá profil.")
            return

        spirits = profile.get("spirits", [])
        idx     = next((i for i, s in enumerate(spirits) if s["name"].lower() == name.lower()), None)
        if idx is None:
            names = ", ".join(s["name"] for s in spirits) or "žádní"
            who   = "Nemáš" if target.id == interaction.user.id else f"**{target.display_name}** nemá"
            await interaction.followup.send(f"❌ {who} ducha **{name}**.\nDostupní: {names}")
            return

        energy.normalize(profile)
        spirit = spirits[idx]
        energy.choose_main(profile, spirit['id'])
        _save(data)
        old_str = ""
        who = "Sis" if target.id == interaction.user.id else f"**{target.display_name}**"
        await interaction.followup.send(
            f"✅ {who} nasadil **{spirit['name']}** "
            f"({rank_label(spirit['rank'])}, {spirit['fury']} {FU_EMO}).{old_str}"
        )

    # ── /duch unequip ─────────────────────────────────────────────────────────

    @duch.command(name="unequip", description="Sundej si strážného ducha (DM může i jiným).")
    @app_commands.describe(member="[DM] Hráč (prázdné = ty)")
    @app_commands.autocomplete(name=_ac_spirit_name)
    async def duch_unequip(
        self, interaction: discord.Interaction,
        name: str, member: discord.Member = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if member is not None and member.id != interaction.user.id:
            if not _is_dm(interaction):
                await interaction.followup.send("❌ Sundat ducha jinému hráči může jen DM.")
                return
        target = member or interaction.user

        data    = _load()
        uid     = pkey(target.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{target.display_name}** nemá profil.")
            return

        spirit = next((s for s in energy.equipped(profile) if s['name'].lower() == name.lower()), None)
        if spirit is None:
            return await interaction.followup.send("❌ Tento duch není hlavní.")
        energy.choose_main(profile, None)
        energy.normalize(profile)
        _save(data)
        await interaction.followup.send(f"✅ Duch **{spirit['name']}** sundán. Zůstává v kolekci.")

    # ── /duch upravit ─────────────────────────────────────────────────────────

    @duch.command(name="upravit", description="[DM] Uprav hodnoty existujícího ducha.")
    @app_commands.describe(
        member="Hráč", name="Jméno ducha",
        nove_fury="Nová hodnota furioku",
        novy_rank="Nový rank (resetuje XP)",
        novy_popis="Nový popis",
        nove_jmeno="Přejmenovat ducha",
    )
    @mark_admin
    async def duch_upravit(
        self, interaction: discord.Interaction,
        member: discord.Member, name: str,
        nove_fury: Optional[int] = None,
        novy_rank: Optional[int] = None,
        novy_popis: Optional[str] = None,
        nove_jmeno: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return

        data    = _load()
        uid     = pkey(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return

        spirits = profile.get("spirits", [])
        spirit  = next((s for s in spirits if s["name"].lower() == name.lower()), None)
        if spirit is None:
            names = ", ".join(s["name"] for s in spirits) or "žádní"
            await interaction.followup.send(f"❌ Hráč nemá ducha **{name}**.\nDostupní: {names}")
            return

        changes = []
        if nove_fury is not None and nove_fury >= 0:
            energy.normalize(profile)
            spirit["fury_cur"] = min(nove_fury, spirit["fury_cur"])
            spirit["fury_max"] = nove_fury
            spirit["fury"] = nove_fury
            changes.append(f"furioka → **{nove_fury}**")
        if novy_rank is not None and novy_rank >= 1:
            spirit["rank"]          = novy_rank
            spirit["xp_threshold"]  = rank_xp_threshold(novy_rank)
            spirit["xp"]            = 0
            changes.append(f"rank → **{rank_label(novy_rank)}**")
        if novy_popis is not None:
            spirit["description"] = novy_popis
            changes.append("popis aktualizován")
        if nove_jmeno is not None:
            if any(s["name"].lower() == nove_jmeno.lower() for s in spirits if s is not spirit):
                await interaction.followup.send(f"❌ Hráč už má ducha jménem **{nove_jmeno}**.")
                return
            old_name = spirit["name"]
            spirit["name"] = nove_jmeno
            changes.append(f"přejmenován: **{old_name}** → **{nove_jmeno}**")

        if not changes:
            await interaction.followup.send("ℹ️ Nezadal/a jsi žádnou změnu.")
            return

        _save(data)
        await interaction.followup.send(
            f"✅ Duch **{spirit['name']}** hráče **{member.display_name}** upraven:\n"
            + "\n".join(f"• {c}" for c in changes)
        )

    # ── /duch odebrat ─────────────────────────────────────────────────────────

    @duch.command(name="odebrat", description="[DM] Trvale odebere ducha z kolekce hráče.")
    @app_commands.describe(member="Hráč", name="Jméno ducha")
    @mark_admin
    async def duch_odebrat(
        self, interaction: discord.Interaction,
        member: discord.Member, name: str,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return

        data    = _load()
        uid     = pkey(member.id)
        profile = data.get(uid)
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return

        spirits = profile.get("spirits", [])
        idx     = next((i for i, s in enumerate(spirits) if s["name"].lower() == name.lower()), None)
        if idx is None:
            names = ", ".join(s["name"] for s in spirits) or "žádní"
            await interaction.followup.send(f"❌ Hráč nemá ducha **{name}**.\nDostupní: {names}")
            return

        energy.normalize(profile)
        spirits.pop(idx)
        energy.normalize(profile)
        _save(data)
        await interaction.followup.send(f"✅ Duch **{name}** trvale odebrán hráči **{member.display_name}**.")

    # ── /duch seznam ──────────────────────────────────────────────────────────

    @duch.command(name="seznam", description="Zobraz seznam strážných duchů hráče.")
    @app_commands.describe(member="Hráč (výchozí: ty)")
    async def duch_seznam(
        self, interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target  = member or interaction.user
        data    = _load()
        uid     = pkey(target.id)
        profile = data.get(uid)

        if not profile:
            await interaction.followup.send(f"❌ **{target.display_name}** nemá profil.", ephemeral=True)
            return

        spirits      = profile.get("spirits", [])
        energy.normalize(profile)
        equipped_ids = profile["equipped_spirit_ids"]

        if not spirits:
            await interaction.followup.send(f"*{target.display_name} nemá žádného strážného ducha.*", ephemeral=True)
            return

        lines = []
        for i, s in enumerate(spirits):
            line = _spirit_line(s, equipped=(s["id"] in equipped_ids))
            if s.get("description"):
                line += f"\n-# *{s['description']}*"
            lines.append(line)

        embed = discord.Embed(
            title=f"{SPIRIT_EMO} Strážní duchové — {target.display_name}",
            description="\n\n".join(lines),
            color=0x9b59b6,
        )
        embed.set_footer(text=f"Celkem duchů: {len(spirits)}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /duch info ────────────────────────────────────────────────────────────

    @duch.command(name="info", description="Zobraz detailní info o konkrétním duchovi.")
    @app_commands.describe(name="Jméno ducha", member="Hráč (výchozí: ty)")
    async def duch_info(
        self, interaction: discord.Interaction,
        name: str, member: Optional[discord.Member] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        target  = member or interaction.user
        data    = _load()
        uid     = pkey(target.id)
        profile = data.get(uid)

        if not profile:
            await interaction.followup.send(f"❌ **{target.display_name}** nemá profil.")
            return

        spirits      = profile.get("spirits", [])
        energy.normalize(profile)
        equipped_ids = profile["equipped_spirit_ids"]
        idx          = next((i for i, s in enumerate(spirits) if s["name"].lower() == name.lower()), None)
        if idx is None:
            await interaction.followup.send(f"❌ Duch **{name}** nenalezen.")
            return

        spirit   = spirits[idx]
        equipped = (spirit["id"] in equipped_ids)
        title    = f"{SPIRIT_EMO} {spirit['name']}" + (" ⭐ hlavní duch" if equipped else "")
        embed    = _spirit_embed(spirit, title=title)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Spirits(bot))