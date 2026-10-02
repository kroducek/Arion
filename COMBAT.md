# Combat: řízené vyhodnocování útoků

Combat je tracker. DM určuje, co situace dovoluje, jaké hody jsou potřeba a zda útok zasáhl. Bot automaticky neporovnává výsledky a neurčuje vítěze.

## Běžný průběh

1. Hráč použije `/attack` ve vlastním tahu. Zobrazí se dočasná karta útoku. Akce a zvolená munice se rezervují. DM ovládá NPC přes `/combat attack_npc`; `force` dovoluje výjimku z tahu a počtu akcí.
2. Cíl stiskne **Reakce** a popíše záměr (úhyb, blok, bariéra…). Za NPC může popis zadat DM. Samotný popis žádný zdroj neodečítá.
3. DM stiskne **Vyžádat hod**: vybere `cíl`, `útok` nebo konkrétního účastníka, kostky, volitelně až dva atributy a poznámku. Může zadat různé požadavky pro obě strany.
4. Hráč stiskne **Hodit** nebo použije odpovídající `/roll`, např. `/roll hod:1d20 check:DEX`. Pokud odpovídá více požadavků, nejprve vybere jeden; až potom se hází. `/roll samostatne:true` je běžný hod mimo čekající útoky.
5. DM rozhodne **Zásah**, **Minutí** nebo **Upravit zásah**. Úprava je celkové poškození včetně útočné furioku, před DEF a obranným pohlcením. Furioku se k ručnímu číslu nepřičítá podruhé, ale její přidělení se při zásahu spotřebuje.
6. Výsledek se uloží a vypíše do konzole. Po dokončení výpisu se dočasná karta smaže. RP zprávy zůstávají v chatu.

Hod kostkou a atribut jsou nadále oddělené hodnoty. Dva atributy mají průměr zaokrouhlený nahoru, stejně jako původní `/roll check`. Perkové bonusy se počítají ke statu, nikoli automaticky k hodu. Na další pokus slouží DM tlačítko **Přehodit**; původní výsledek zůstává v historii.

## Náklady a návraty

- **Náklady obrany** potvrzuje DM: mana, spotřeba reakce a případně použití cooldownu konkrétního perku. Tlačítko neprovádí vlastní efekt magie/perku; ten zůstává řízený DM a jeho stávajícími příkazy.
- **Již zaplaceno** pouze zaznamená náklady, které odečetl jiný příkaz. Znovu je neodečítá a undo je nevrací.
- Mana zbraně a rezervovaná munice se spotřebují i při minutí. Útočná furioku se spotřebuje jen při zásahu. Potvrzená obrana zůstává zaplacená i při minutí.
- **Zrušit** vrátí rezervaci útočníka. DM volí, zda vrátit také potvrzené náklady obrany. Spotřebované akce a jednorázové buffy se vracejí jen v rámci stejného tahu, aby se neovlivnily akce dalšího tahu.
- `/combat undo` vrací poslední rozhodnutí včetně změn HP, statusů, furioku obou stran, many, munice a přímo potvrzených nákladů obrany. Hody zůstávají v logu; automaticky nevzniká nový útok.
- Reakce se obnovuje na začátku vlastního tahu, ne všem při změně kola.

## DM výjimky a obnova

- Chybějící reakce nebo vyžádaný hod brání běžnému potvrzení. DM může výslovně zvolit **Rozhodnout bez čekání**.
- Čekající útoky blokují předání tahu hráčem. DM může předání potvrdit i s otevřenými útoky.
- Před odebráním účastníka nebo ukončením boje je nutné jeho čekající útoky vyhodnotit či zrušit.
- `/combat pending` na ArionDM obnoví zvolenou smazanou kartu bez nového hodu a bez další spotřeby.
- `/combat autoapply` už nezapíná automatické zásahy; útoky čekají na rozhodnutí DM.
- DM tlačítka přijímají administrátora nebo roli `DM`. Správcovské slash příkazy nadále používají existující admin gate a zůstávají v ArionDM.

## Persistence a testování

Čekající útok, požadavky a výsledky hodů jsou v SQLite. Změny útoku, profilů a cooldownů se zapisují v jedné transakci. Dvojí potvrzení ani dvojí hod nemohou spotřebovat zdroje dvakrát. Každá akce je navázaná na postavu přítomnou v boji; přepnutí aktivní postavy nepřesměruje její náklady na jiný profil.

Každý bot aktualizuje pouze vlastní zprávy (kontrola změn každé 3 sekundy), takže `/roll` z jiného bota aktualizuje správnou kartu. Při nedostupnosti Discordu zůstává rozhodnutí v logu. Staré otevřené karty se při interakci převedou; historicky neukládané údaje o jejich bonusové akci/buffech nelze zpětně přesně rekonstruovat.

Automatické testy pokrývají souběžné potvrzení, rollback, zásah/minutí/zrušení/undo, zdroje obou stran, runy, restart, výběr hodu, oprávnění, přepínání postav a ochranu proti přepsání čerstvého zásahu druhým botem. Živé ověření na Discordu vyžaduje restart ArionDND a ArionDM a synchronizaci příkazů podle stávajícího nasazení.
