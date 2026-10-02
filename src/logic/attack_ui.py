"""Persistent attack card and explicit, player-triggered rolls."""
import asyncio
import copy
import logging
import discord
from discord import ui
from src.logic import attack_flow as flow
from src.database import db


def is_dm(interaction):
    user = interaction.user
    return bool(getattr(getattr(user, 'guild_permissions', None), 'administrator', False)
                or any(r.name == 'DM' for r in getattr(user, 'roles', [])))


async def notice(i, text):
    sender = i.followup.send if i.response.is_done() else i.response.send_message
    await sender(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


def attack_embed(a):
    unresolved = [r for r in a.get('requests', []) if r.get('result') is None and not r.get('superseded')]
    waiting = ', '.join(dict.fromkeys(r['actor'] for r in unresolved))
    stage = f'Čeká na hod: {waiting}' if waiting else ('Čeká na rozhodnutí DM' if a.get('reaction') else f"Čeká na reakci: {a['target']}")
    embed = discord.Embed(title='⚔️ Útok', color=0xC59145,
        description=f"{a['attacker']} → {a['target']}\n**{a.get('weapon_label', 'Zbraň')}** · základ **{a['damage']} dmg**\n{stage}"[:4096])
    embed.add_field(name='Poškození', value=a.get('roll_info', '—')[:700] or '—', inline=False)
    embed.add_field(name='Reakce', value=a.get('reaction') or 'Cíl popíše svůj záměr tlačítkem Reakce.', inline=False)
    rows = []
    for r in a.get('requests', [])[-12:]:
        result = r.get('result')
        value = f"**{result['total']}** · {result.get('stat_note', '')}" if result is not None else 'čeká'
        if r.get('superseded'):
            value += ' (nahrazený hod)'
        rows.append(f"{r['actor']} · {r['expr']} {','.join(r['attrs'])}: {value}" + (f" — {r['note']}" if r.get('note') else ''))
    if rows:
        embed.add_field(name='Hody · výsledek rozhodne DM', value='\n'.join(rows)[:1024], inline=False)
    res = a.get('resources', {})
    info = []
    if res.get('ammo_qty'):
        info.append(f"Rezervováno {res['ammo_qty']}× {res['ammo_id']}")
    if res.get('mana'):
        info.append(f"Útok spotřebuje {res['mana']} many při zásahu i minutí")
    if a.get('mana_note'):
        info.append(a['mana_note'])
    if info:
        embed.add_field(name='Zdroje útoku', value=' · '.join(info)[:1024], inline=False)
    costs = a.get('costs', [])
    if costs:
        cost = costs[0]
        embed.add_field(name='Potvrzené náklady obrany', value=f"{cost['mana']} many · reakce {'ano' if cost['reaction'] else 'ne'} · perk {cost['perk_id'] or '—'}" + (' · již zaplaceno' if cost['already_paid'] else ''), inline=False)
    embed.set_footer(text='Hodit můžeš tlačítkem nebo /roll. Zásah přidá přidělenou útočnou furioku; minutí ji zachová.')
    return embed


class AttackView(ui.View):
    def __init__(self, cog, channel_id=None, attacker='', attacker_uid=None, target='', damage=0,
                 weapon_id=None, mana_cost=0, ammo_note='', weapon_label='', roll_info='',
                 resources=None, extra_statuses=None, data=None):
        super().__init__(timeout=None)
        self.cog, self.channel_id = cog, channel_id
        self.persistent = not target and data is None
        self.message_id = None
        self.hydrate(data or dict(attacker=attacker, attacker_uid=attacker_uid, target=target,
            damage=damage, weapon_id=weapon_id, mana_cost=mana_cost, ammo_note=ammo_note,
            weapon_label=weapon_label, roll_info=roll_info, resources=resources or {},
            extra_statuses=extra_statuses or []))

    def hydrate(self, data):
        self.data = copy.deepcopy(data)
        for key in ('attacker', 'attacker_uid', 'target', 'damage', 'weapon_id', 'mana_cost',
                    'ammo_note', 'weapon_label', 'roll_info', 'resources'):
            setattr(self, key, data.get(key))
        self.extra_statuses = [tuple(s) for s in data.get('extra_statuses', [])]
        self.aid = data.get('id')
        self.message_id = data.get('message_id')

    def payload(self):
        return copy.deepcopy(self.data)

    def _forget_pending(self, state):
        state.get(flow.PENDING, {}).pop(self.aid or self.message_id, None)

    def _may_resolve(self, i):
        return is_dm(i)

    async def fresh(self, i):
        # A registered persistent view is shared; never hydrate it in a callback.
        state = db.load_doc(flow.COMBAT, {}).get(str(i.channel_id), {})
        mid = str(i.message.id) if i.message else self.message_id
        for aid, a in state.get(flow.PENDING, {}).items():
            if aid == self.aid or str(a.get('message_id', aid)) == mid:
                if not a.get('flow_version'):
                    a = flow.migrate_legacy(i.channel_id, aid)
                    flow.attach_message(i.channel_id, aid, int(mid), i.client.user.id)
                return AttackView(self.cog, i.channel_id, data=a)
        await notice(i, 'Tento útok už je vyhodnocený nebo zrušený.')
        return None

    async def refresh(self, i, a):
        self.hydrate(a)
        await i.response.edit_message(embed=attack_embed(a), view=self,
                                      allowed_mentions=discord.AllowedMentions.none())

    async def _replace_with_console(self, i, lines):
        if not i.response.is_done():
            await i.response.defer()
        # Send a durable complete result before deleting the working card.
        message = getattr(self, 'message', None) or i.message
        sent = await self.cog.send_console(i.channel, lines)
        if sent is False:
            await notice(i, 'Výsledek je uložený, ale konzoli se nepodařilo odeslat. Najdeš jej přes /combat log.')
            return
        if message:
            try:
                await message.delete()
            except discord.HTTPException:
                for child in self.children:
                    child.disabled = True
                await message.edit(view=self)

    async def decide(self, i, outcome, damage=None, bypass=False, refund=False):
        if not is_dm(i):
            return await notice(i, 'Výsledek určuje pouze DM.')
        try:
            result = flow.resolve(i.channel_id, self.aid, True, outcome, damage, bypass, refund)
        except ValueError as e:
            if 'Chybí reakce' in str(e) and not bypass:
                view = ui.View(timeout=180)
                button = ui.Button(label='Rozhodnout bez čekání', style=discord.ButtonStyle.danger)
                async def confirm(j):
                    await self.decide(j, outcome, damage, bypass=True)
                button.callback = confirm
                view.add_item(button)
                return await i.response.send_message(str(e), view=view, ephemeral=True)
            return await notice(i, str(e))
        from src.logic.combat import console
        await i.response.defer()
        self.message = None
        try:
            if self.message_id:
                self.message = await i.channel.fetch_message(int(self.message_id))
        except discord.HTTPException:
            pass
        # For a modal/ephemeral confirmation, do not delete that message in place of the card.
        if self.message is None:
            await self.cog.send_console(i.channel, [console(line) for line in result['lines']])
        else:
            await self._replace_with_console(i, [console(line) for line in result['lines']])
        self.cog.reload_state()
        state = self.cog.active_combats.get(i.channel_id)
        if state:
            if state.get('boss'):
                await self.cog._update_boss_bar(state, flashing=outcome == 'hit')
            await self.cog.check_wipeout(i.channel, state)

    async def resolve_hit(self, i, damage=None):
        await self.decide(i, 'hit', damage)

    @ui.button(label='Reakce', emoji='🛡️', custom_id='arion:combat:attack:reaction', row=0)
    async def reaction(self, i, button):
        view = await self.fresh(i)
        if view:
            from src.logic.combat import _actor_uid
            if not is_dm(i) and _actor_uid(view.target) != i.user.id:
                return await notice(i, 'Reakci popisuje cíl nebo DM.')
            await i.response.send_modal(ReactionModal(view))

    @ui.button(label='Hodit', emoji='🎲', custom_id='arion:combat:attack:roll', row=0)
    async def roll(self, i, button):
        view = await self.fresh(i)
        if view:
            choices = [x for x in flow.available_rolls(i.channel_id, i.user.id, is_dm(i)) if x[0] == view.aid]
            await choose_roll(i, choices)

    @ui.button(label='Vyžádat hod', custom_id='arion:combat:attack:request', row=0)
    async def request(self, i, button):
        if not is_dm(i):
            return await notice(i, 'Hod vyžaduje DM.')
        view = await self.fresh(i)
        if view:
            await i.response.send_modal(RequestModal(view))

    @ui.button(label='Náklady obrany', custom_id='arion:combat:attack:cost', row=0)
    async def cost(self, i, button):
        if not is_dm(i):
            return await notice(i, 'Náklady potvrzuje DM.')
        view = await self.fresh(i)
        if view:
            await i.response.send_modal(CostModal(view))

    @ui.button(label='Přehodit', custom_id='arion:combat:attack:reroll', row=0)
    async def reroll(self, i, button):
        if not is_dm(i):
            return await notice(i, 'Nový pokus povoluje DM.')
        view = await self.fresh(i)
        if view:
            choices = [(view.aid, r) for r in view.data.get('requests', []) if not r.get('superseded')]
            if not choices:
                return await notice(i, 'Zatím nejsou vyžádané žádné hody.')
            await i.response.send_message('Vyber hod, který má hráč zopakovat.', ephemeral=True,
                view=RollChoice(choices, i.user.id, reroll=True))

    @ui.button(label='Zásah', style=discord.ButtonStyle.success, custom_id='arion:combat:attack:hit', row=1)
    async def hit(self, i, button):
        view = await self.fresh(i)
        if view:
            await view.decide(i, 'hit')

    @ui.button(label='Minutí', custom_id='arion:combat:attack:miss', row=1)
    async def miss(self, i, button):
        view = await self.fresh(i)
        if view:
            await view.decide(i, 'miss')

    @ui.button(label='Upravit zásah', custom_id='arion:combat:attack:edit', row=1)
    async def edit(self, i, button):
        if not is_dm(i):
            return await notice(i, 'Poškození upravuje DM.')
        view = await self.fresh(i)
        if view:
            await i.response.send_modal(DamageModal(view))

    @ui.button(label='Zrušit', style=discord.ButtonStyle.danger, custom_id='arion:combat:attack:cancel', row=1)
    async def cancel(self, i, button):
        if not is_dm(i):
            return await notice(i, 'Útok ruší DM.')
        view = await self.fresh(i)
        if view:
            options = ui.View(timeout=180)
            for refund, label in [(False, 'Zrušit · obrana zůstane zaplacená'), (True, 'Zrušit · vrátit i náklady obrany')]:
                b = ui.Button(label=label)
                async def finish(j, refund=refund):
                    await view.decide(j, 'cancel', refund=refund)
                b.callback = finish
                options.add_item(b)
            await i.response.send_message('Akce a munice útočníka se vrátí. Co s potvrzenými náklady obrany?', view=options, ephemeral=True)


class ReactionModal(ui.Modal, title='Jak reaguješ na útok?'):
    text = ui.TextInput(label='Záměr', style=discord.TextStyle.paragraph, max_length=600,
                        placeholder='Pokusím se uhnout stranou / blokovat / vytvořit bariéru…')
    def __init__(self, view):
        super().__init__()
        self.view_ref = view
        self.text.default = view.data.get('reaction', '')
    async def on_submit(self, i):
        try:
            a = flow.update_reaction(i.channel_id, self.view_ref.aid, i.user.id, is_dm(i), str(self.text))
            await self.view_ref.refresh(i, a)
        except ValueError as e:
            await notice(i, str(e))


class RequestModal(ui.Modal, title='Vyžádat hod'):
    actor = ui.TextInput(label='Kdo: cíl / útok / jméno NPC / @hráč', default='cíl', max_length=100)
    dice = ui.TextInput(label='Kostky', default='1d20', max_length=80)
    attrs = ui.TextInput(label='Atributy (volitelné, např. DEX nebo STR,DEX)', required=False, max_length=30)
    note = ui.TextInput(label='Co hod posuzuje?', required=False, max_length=200)
    def __init__(self, view):
        super().__init__()
        self.view_ref = view
    async def on_submit(self, i):
        try:
            a = flow.request_roll(i.channel_id, self.view_ref.aid, is_dm(i), str(self.actor).strip(),
                str(self.dice), str(self.attrs).replace(' ', '').split(','), str(self.note))
            await self.view_ref.refresh(i, a)
        except ValueError as e:
            await notice(i, str(e))


class CostModal(ui.Modal, title='Potvrdit náklady obrany'):
    mana = ui.TextInput(label='Mana', default='0', max_length=6)
    reaction = ui.TextInput(label='Spotřebuje reakci? ano / ne', default='ano', max_length=3)
    perk = ui.TextInput(label='ID použitého perku (volitelné)', required=False, max_length=100)
    paid = ui.TextInput(label='Již zaplaceno jiným příkazem? ano / ne', default='ne', max_length=3)
    def __init__(self, view):
        super().__init__()
        self.view_ref = view
    async def on_submit(self, i):
        try:
            if str(self.reaction).lower() not in ('ano', 'ne') or str(self.paid).lower() not in ('ano', 'ne'):
                raise ValueError('Zadej ano nebo ne.')
            a = flow.confirm_cost(i.channel_id, self.view_ref.aid, is_dm(i), int(str(self.mana)),
                str(self.reaction).lower() == 'ano', str(self.perk).strip(), str(self.paid).lower() == 'ano')
            await self.view_ref.refresh(i, a)
        except ValueError as e:
            await notice(i, str(e))


class DamageModal(ui.Modal, title='Upravit a potvrdit zásah'):
    damage = ui.TextInput(label='Celkový dmg včetně furioku, před DEF/štítem', max_length=7)
    def __init__(self, view):
        super().__init__()
        self.view_ref = view
    async def on_submit(self, i):
        try:
            value = int(str(self.damage))
        except ValueError:
            return await notice(i, 'Zadej nezáporné celé číslo.')
        await self.view_ref.decide(i, 'hit', value)


async def perform_roll(i, aid, r):
    try:
        a, rolled = flow.submit_roll(i.channel_id, aid, r['id'], i.user.id, is_dm(i))
    except ValueError as e:
        return await notice(i, str(e))
    result = rolled['result']
    perk_note = '\n'.join(f"✨ {p['name']} +{p['bonus']} — {p['desc']}" for p in result.get('perks', []))[:600]
    await notice(i, f"🎲 {rolled['actor']} · {rolled['expr']} → **{result['total']}**\n{result['detail']}\n{result['stat_note']}\n{perk_note}\nHod je zapsaný na kartě útoku.")
    if i.guild and rolled.get('profile_key'):
        from src.core.dnd.roll_stats import record_roll
        from src.core.dnd.achievements import check_roll_achievements
        try:
            stats = record_roll(i.guild.id, i.user.id, nat20=result['nat20'], nat1=result['nat1'],
                hit24=result['total'] == 24, is_check=bool(rolled['attrs']), is_d20=result['is_d20'])
            await check_roll_achievements(i.guild.id, i.user, i.channel, stats)
        except Exception:
            logging.exception('Attack roll achievement failed')


class RollChoice(ui.View):
    def __init__(self, choices, user_id, reroll=False, page=0):
        super().__init__(timeout=180)
        select = ui.Select(placeholder='Vyber požadovaný hod', options=[
            discord.SelectOption(label=f"{r['actor']} · {r['expr']} {','.join(r['attrs'])}"[:100],
                description=(r.get('note') or 'Hod vyžádaný DM')[:100], value=str(n))
            for n, (aid, r) in enumerate(choices[page*25:(page+1)*25], start=page*25)])
        async def choose(i):
            if i.user.id != user_id:
                return await notice(i, 'Tento výběr není pro tebe.')
            aid, r = choices[int(select.values[0])]
            if reroll:
                try:
                    flow.request_roll(i.channel_id, aid, is_dm(i), r['actor'], r['expr'], r['attrs'], r.get('note', ''), reroll=r['id'])
                    await notice(i, 'Nový pokus je připravený. Původní hod zůstává v historii.')
                except ValueError as e:
                    await notice(i, str(e))
            else:
                await perform_roll(i, aid, r)
        select.callback = choose
        self.add_item(select)
        for next_page, label in [(page-1, 'Předchozí'), (page+1, 'Další')]:
            if 0 <= next_page < (len(choices)+24)//25:
                b = ui.Button(label=label)
                async def navigate(i, next_page=next_page):
                    if i.user.id != user_id:
                        return await notice(i, 'Tento výběr není pro tebe.')
                    await i.response.edit_message(view=RollChoice(choices, user_id, reroll, next_page))
                b.callback = navigate
                self.add_item(b)


async def choose_roll(i, choices):
    if not choices:
        return await notice(i, 'DM pro tebe zatím nevyžádal žádný další hod.')
    if len(choices) == 1:
        return await perform_roll(i, *choices[0])
    await i.response.send_message('Vyber, ke kterému požadavku hod patří.', ephemeral=True,
                                  view=RollChoice(choices, i.user.id))


async def route_roll(i, expr, attrs):
    choices = flow.available_rolls(i.channel_id, i.user.id, is_dm(i), expr, attrs)
    if not choices:
        return False
    await choose_roll(i, choices)
    return True


async def refresh_cards(cog):
    """Each bot edits only its own messages; /roll may run on a different bot."""
    try:
        await cog.bot.wait_until_ready()
    except RuntimeError:
        # Offline command-tree checks intentionally do not log in to Discord.
        return
    seen = {}
    while not cog.bot.is_closed():
        try:
            states = db.load_doc(flow.COMBAT, {})
            live = set()
            for channel_id, state in states.items():
                for aid, a in state.get(flow.PENDING, {}).items():
                    mid = a.get('message_id')
                    if not mid or str(a.get('bot_id')) != str(cog.bot.user.id):
                        continue
                    live.add(mid)
                    signature = repr(a)
                    if seen.get(mid) == signature:
                        continue
                    channel = cog.bot.get_channel(int(channel_id))
                    if channel is None:
                        continue
                    try:
                        message = await channel.fetch_message(int(mid))
                        await message.edit(embed=attack_embed(a), view=AttackView(cog, int(channel_id), data=a),
                                           allowed_mentions=discord.AllowedMentions.none())
                        seen[mid] = signature
                    except (discord.NotFound, discord.Forbidden):
                        seen[mid] = signature
            seen = {mid: signature for mid, signature in seen.items() if mid in live}
        except Exception:
            logging.exception('Attack card refresh failed')
        await asyncio.sleep(3)
