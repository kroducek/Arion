# Furioku a duchové

Hráčská správa je `/furioku` v ArionDND. Nová postava vidí pouze `?????????`;
první duch nebo kladný Vliv systém trvale odemkne. Administrace zůstává v ArionDM.

- Maximum hráče: 5 × součet Vlivů + trvalý bonus `/dmfury`.
- `/duch equip name:...` vybírá právě jednoho hlavního ducha pro XP a profil.
- `/duch unequip name:...` sundává hlavního ducha, aniž by měnil Jednotu.
- `/furioku duch:...` přepíná zapojení libovolného vlastněného ducha do Jednoty.
  Tlačítko v panelu zapojí/odpojí všechny. Spotřeba jde nejprve z hráče,
  poté z duchů v pořadí zapojení. Sundání ducha energii nedoplní.
- Útok a Obrana vyžadují příslušný perk; Jednota vyžaduje perk Jednota.
- Přidělení rezervuje energii. Obrana spotřebuje jen pohlcené poškození.
  Útok přidá přidělenou energii k potvrzenému zásahu a vyprázdní útočnou rezervaci.
  Minutí energii nespotřebuje. Při zmenšení zásoby má útočná rezervace přednost.
- Hráči bez přidělené obrany nemají automatický furiokový štít. NPC si ponechávají
  nastavený štít. Statusové poškození ignoruje DEF, nikoli přidělenou auru.
- Combat průběžně čte energii profilu a zapisuje spotřebu hráče i duchů.
  Undo vrací také energii a rezervace. Boj si pamatuje konkrétní postavu.
- Rest obnovuje stejným procentem vlastní energii i energii všech vlastněných
  duchů, včetně nenasazených (1: 0 %, 2–10: 25 %, 11–19: 50 %, 20: 100 %).
- Kladné XP odměny přes společnou funkci `add_xp` (včetně `/admin-xp`) dostane
  v plné výši hlavní duch, i když je vyčerpaný nebo není v Jednotě. Odebrání hráčových XP
  zpětně nesnižuje duchovy ranky. `/duch xp` odmění hlavního ducha.
- Postup ducha je automatický: práh floor(100 × rank^1.6), maximum energie
  +25 % za rank (nejméně +1). Jedna odměna může přinést více ranků.
- Šlechtění zachovává silnějšího ducha: identitu, jméno, popis, element, XP
  a nasazení. Při stejném ranku přežije první vybraný duch.
  Úspěch: rank +1, přičtení maxima a zbývající energie pohlceného ducha.
  Neúspěch: +5 % vlastního maxima, zaokrouhleno dolů. Slabší vždy zaniká.
  Dosavadní pravděpodobnosti šlechtění zůstávají zachované.

## Kompatibilita dat

Migrace je postupná při načtení/použití profilu. Staré `fury` ducha se převede
na `fury_max` a `fury_cur` se stejnou hodnotou. `fury` zůstává kompatibilním
zobrazením maxima; při spotřebě se nemění. Starý `equipped_spirit_idx` se převede
na seznam stabilních ID. Další výběr a Jednota používají tato ID, takže odstranění
nebo přejmenování ducha neposune nasazení na jiného. Existující tresty XP prahu
za neúspěšné náhodné postupy se při dalším udělení XP nepoužívají.

Po nasazení restartovat ArionDND a ArionDM, aby proběhla synchronizace slash
příkazů. Samostatná minihra `/duel` v ArionBOT není součástí tohoto reworku.

## Hlavní duch a Jednota (druhá část)

Panel `/furioku` má nezávislé nabídky pro hlavního ducha a Jednotu. Nabídky
stránkují po 24 duchách, hromadné zapojení není omezeno na zobrazenou stránku.
Jednota nevyžaduje equip a sama nezískává XP. Profil i obrázková karta zobrazují
součet aktuální energie a maxim hráče a pouze skutečně sjednocených duchů
(s vlastněným perkem Jednota). Hlavní duch je samostatně uveden v profilu.
💤 označuje nulovou energii; nesundává ducha, neodpojuje Jednotu, neblokuje XP.
Maximum vyčerpaného sjednoceného ducha zůstává započtené do společného baru.

Jediný dříve nasazený duch se stane hlavním automaticky. Pokud jich bylo více,
hráč si musí hlavního vybrat; panel ho upozorní. Do výběru duchové nezískávají XP.
Žádný duch ani XP se nesmažou a původní výběr Jednoty se zachová.

## Pohodlné ovládání a spotřeba

V `/furioku` lze zadat přesné částky, případně přesunout celou dostupnou zásobu
do útoku nebo obrany (druhá rezervace se vynuluje). Volba vyžaduje příslušný perk.
Tlačítko „Sestavy a čerpání“ otevře uložení, načtení a smazání pojmenované sestavy
a nastavení pořadí zdrojů. Do pořadí se zadávají jména po řádcích, vlastní energie
je `já`. Nezapojené zdroje se přeskočí; neuvedené se přidají nakonec (vlastní,
pak ostatní duchové v pořadí zapojení). Stejný zdroj nesmí být uveden dvakrát.

Sestava ukládá Jednotu, útočnou/obrannou rezervaci a pořadí čerpání, nikoli hlavního
ducha ani aktuální energii. Stejný název přepíše existující sestavu. Načtení nepřidává
energii, odstraní neexistující duchy, respektuje perky a omezí rezervace dostupnou
zásobou (útok má přednost). Názvy sestav jsou rozlišované přesně.

Potvrzené útoky, obranná absorpce a poškození statusy vypisují spotřebu podle zdrojů.
Duch je označen hláškou 💤 pouze při spotřebě jeho posledního bodu, nikoli při každém
dalším zásahu. Undo může obnovit energii; další skutečné vyčerpání se oznámí znovu.

## Oznámení postupu a náhled šlechtění

Postup hlavního ducha při `/admin-xp` se oznámí veřejně spolu s level-upem hráče,
nebo samostatně, pokud postoupil pouze duch. Ukazuje původní a nový rank i maximum
furioku. Questová odměna stejný údaj připojí do existujícího oznámení odměny.
Přímé `/duch xp` rovněž zobrazí postup ducha.

Potvrzení šlechtění ukazuje přeživšího a pohlceného ducha, šance a přesnou změnu
ranku, maxima i aktuální energie pro oba výsledky. Výslovně upozorňuje, že pohlcený
duch zanikne vždy. Pokud se duchové před potvrzením změní, akce vyžaduje nový náhled.

## RP bonding (ArionDM)

- `/duch bond start member:hráč duch:jméno` zahájí bonding pro aktivní postavu
  hráče a konkrétního vlastněného ducha. Odešle jediný řádek `-# @hráč se sbližuje
  s duchem Jméno.` Duch nemusí být hlavní ani sjednocený.
- `/duch bond success` přidá úspěch. Po třetím duch evolvuje a bonding skončí.
  Výchozí odměna je dvojnásobek jeho maxima v okamžiku dokončení.
- Při třetím úspěchu lze použít `nove_maximum` pro vlastní absolutní maximum
  (nejméně současné maximum). Aktuální energie vzroste o rozdíl maxim;
  například 40/100 přejde na 140/200. XP, rank, jméno a nasazení zůstávají.
- `/duch bond fail` smaže celý rozpracovaný postup bez odměny.

V kanálu je jeden bonding; stejný duch nemůže současně bondovat v jiném kanálu.
Stav je uložený v profilu, přežije restart a váže se na ID ducha a původní postavu.
Přejmenování ducha ho nepřeruší. Po odstranění ducha lze bonding zrušit přes fail.
Příkazy jsou dostupné pouze v ArionDM a vyžadují administrátora nebo roli DM.
