# ArionBot & ArionDND

Dva Discord boti pro kampaň **Aurionis** (D&D / fantasy RPG server). Psáno v Pythonu pomocí discord.py.

---

## Boti

| Bot | Soubor | Token env | Popis |
|-----|--------|-----------|-------|
| **ArionBOT** | `main_bot.py` | `DISCORD_TOKEN_BOT` | Minihry, karty, ekonomika |
| **ArionDND** | `main_dnd.py` | `DISCORD_TOKEN_DND` | D&D systémy — postavy, questy, perky, boj |

---

## Spuštění

```bash
pip install -r requirements.txt
python main_bot.py   # ArionBOT
python main_dnd.py   # ArionDND
```

### Proměnné prostředí (`.env`)

```env
DISCORD_TOKEN_BOT=...
DISCORD_TOKEN_DND=...
PREFIX=!
WIKI_URL=https://tvowiki.cz/aurionis
EMBED_COLOR=FFD700
CAMPFIRE_CHANNEL=campfire
DATA_DIR=           # volitelné — vlastní cesta pro JSON soubory
```

---

## ArionDND — systémy

### Profil a statistiky
- `/profile [@hráč]` — HP, hlad, stats, zlato, perky, achievementy
- `/stats` — zobrazení a správa atributů (STR, DEX, CON, INT, WIS, CHA)
- `/roll <výraz>` — hod kostkou s automatickým zaznamenáním nat20/nat1 streaku

### Postavy a onboarding
- `/onboard` — registrace nové postavy
- `/memory` — NPC paměť (co NPC o hráčích ví)

### Questy
- `/quest add <název>` — vytvoření questu (modal s detaily)
- `/quest remove <název>` — smazání questu
- `/quest status <název> <status>` — změna stavu (aktivní / dokončený / neúspěšný)
- `/quest give <název> [@hráči...]` — přiřazení questu hráčům + DM notifikace
- `/audit-log` — posledních 20 admin akcí *(jen administrátoři)*

### Perk systém
- `/give-random-perk @hráč` — náhodný perk z obecného poolu + DM hráči
- `/perk give <id> @hráč` — přidělení konkrétního perku
- `/perk remove <id> @hráč` — odebrání perku
- `/perk reset @hráč` — smazání všech perků hráče
- `/perk use <id>` — aktivace perku (denní cooldown)
- `/perk detail <id>` — detail perku z databáze
- `/perk new` — nový perk (modal)
- `/perk edit <id>` — editace perku (modal s předvyplněním)
- `/perk delete <id>` — smazání perku z databáze
- `/perks show [@hráč]` — přehled perků hráče (Unikátní / S Cooldownem / Pasivní)
- `/perks give <id> @hráč` — alias pro rychlé přidělení
- `/perks list` — výpis celé perk databáze

**Skupiny perků:** Furioku · Magie · Pasivky · Temnota · Světlo · Unikátní

### Achievementy
- `/achievements [@hráč]` — přehled získaných achievementů
- `/achievement done <název> @hráč` — ruční udělení achievementu
- `/achievement remove <název> @hráč` — odebrání achievementu

**Auto-tracking:** nat20 streak ≥ 3, nat1 streak ≥ 3, celkový počet hodů ≥ 100 000, kumulativní ztráty v minihrách.

### Ekonomika a inventář
- `/economy` — správa zlata hráčů
- `/inventory` — předměty hráče
- `/shop` — obchod

### Boj a reputace
- `/combat` — bojový systém (iniciativa, kola)
- `/takedown` — statistiky knockdownů
- `/reputation` — reputační systém frakcí

### Party systém
- `/party` — správa skupin hráčů

### Ostatní
- `/diary` — deník postavy
- `/snajpycounter` — počítadlo speciálních akcí

---

## ArionBOT — minihry

| Příkaz | Popis |
|--------|-------|
| `/kostky` | Kostkové minihry |
| `/cards` | Karetní kolekce |
| `/guess` | Hádací hra |
| `/liar-dice` | Liar's dice |
| `/liar-slots` | Slotový liar |
| `/gallows` | Šibenice |
| `/tarot` | Tarotové karty |
| `/labyrinth` | Dungeon crawl |
| `/poll` | Hlasování |
| `/countdown` | Odpočet |
| `/news` | Zprávy serveru |
| `/story` | Story library |

---

## Struktura projektu

```
ArionBot/
├── main_bot.py          # ArionBOT entry point
├── main_dnd.py          # ArionDND entry point
├── src/
│   ├── core/
│   │   ├── bot/         # ArionBOT cogy (minihry, utility)
│   │   └── dnd/         # ArionDND cogy (questy, perky, achievementy...)
│   ├── logic/           # Sdílená herní logika (profil, roll, combat...)
│   ├── utils/           # Utility (paths, json_utils, audit, embeds...)
│   └── database/        # Seed migrace dat
└── data/                # JSON soubory (auto-generované)
```

### Klíčové datové soubory (`data/`)

| Soubor | Obsah |
|--------|-------|
| `profiles.json` | Postavy hráčů |
| `quests.json` | Quest databáze |
| `perks.json` | Perk databáze (seed migrace) |
| `player_perks.json` | Perky hráčů + cooldown tracking |
| `achievements.json` | Achievementy hráčů |
| `achievement_data.json` | Kumulativní data pro auto-tracking |
| `roll_stats.json` | Statistiky hodů kostkami |
| `audit_log.json` | Log admin akcí (max 500 záznamů) |
| `economy.json` | Ekonomika (zlato) |
| `items.json` | Item databáze |

---

## Technické detaily

- **Python 3.11+**, discord.py 2.x (`app_commands`)
- Persistence: JSON soubory (bez externích databází)
- Seed migrace: při startu botu se automaticky doplní chybějící záznamy v DB souborech
- Slash commandy synchronizovány při každém startu (`tree.sync()`)
