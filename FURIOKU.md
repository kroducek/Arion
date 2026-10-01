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
