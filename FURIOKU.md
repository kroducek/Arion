# Furioku a duchové

Hráčská správa je `/furioku` v ArionDND. Nová postava vidí pouze `?????????`;
první duch nebo kladný Vliv systém trvale odemkne. Administrace zůstává v ArionDM.

- Maximum hráče: 5 × součet Vlivů + trvalý bonus `/dmfury`.
- `/duch equip name:...` přidává dalšího ducha bez početního limitu.
- `/duch unequip name:...` sundává konkrétního ducha.
- `/furioku duch:...` přepíná zapojení nasazeného ducha do Jednoty.
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
  v plné výši každý nasazený duch. Odměna se nedělí. Odebrání hráčových XP
  zpětně nesnižuje duchovy ranky. `/duch xp` odmění všechny nasazené duchy.
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
