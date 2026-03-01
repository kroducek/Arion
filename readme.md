# ⚔️ Arion Bot - Přívodce Světem Aurionis

Magická kočka **Arion** je váš průvodce světem Aurionis. Poskytuje správu D&D kampaní, herní lore a správu družin s bohatými customizačními možnostmi.

## 🎯 Základní Funkce

### 👥 Správa Družin (`/party`)
Komplexní systém pro vytváření, správu a přizpůsobení adventurních skupin:

- **`/party create`** - Vytvoř novou družinu (veřejnou nebo soukromou)
- **`/party join`** - Připoj se k veřejné družině
- **`/party leave`** - Opusť aktuální družinu
- **`/party disband`** - Rozpusť svou družinu (pouze vůdce)
- **`/party invite`** - Pozvěj hráče do své družiny (DM invitace, pouze vůdce)
- **`/party kick`** - Vyhodď člena (pouze vůdce)
- **`/party info`** - Zobraz info o tvé družině
- **`/party list`** - Zobraz všechny dostupné družiny
- **`/party set`** - Otevři formulář pro nastavení identity (barva, emoji, cíl) - **Vůdce jen!**
- **`/party help`** - Zobraz nápovědu

### 🎨 Personalizace Družiny
Každá družina může mít:
- **Barvu** (Hex kód) - zobrazí se na levém okraji embeds
- **Emoji/Emblem** - automaticky se připíše před název private threadu
- **Cíl/Quest** - popis mise nebo cíle skupiny

### 🔒 Bezpečnost & Soukromí
- **Veřejné party** (`/party join` bez pozvánky)
- **Soukromé party** (přístup pouze pozvánkou)
- **Whitelistování** (vůdce kontroluje kdo se může připojit)
- **Rate-limiting** max 3 pozvánky za den

### 💬 Private Thread Rooms
Každá družina má svou privátní konverzační místnost (private thread) v kanálu `#campfire`:
- Automatické vytvoření při založení
- Automatické přidávání/odebírání členů
- Jméno s emoji prefixem pro snadnější identifikaci
- Automatické smazání při rozpuštění party

## 🛠️ Instalace & Spuštění

### Requirements
- Python 3.10+
- discord.py 2.0+
- python-dotenv

### Setup
1. **Klonuj/stáhni projekt**
   ```
   cd ArionBot
   ```

2. **Vytvoř virtuální prostředí (optional ale doporučeno)**
   ```
   python -m venv venv
   venv\Scripts\activate  # Windows
   ```

3. **Instaluj závislosti**
   ```
   pip install discord.py python-dotenv
   ```

4. **Vytvoř `.env` soubor** (v root adresáři)
   ```
   DISCORD_TOKEN=tvůj_token_zde
   GUILD_ID=tvé_guild_id
   ```

5. **Vytvoř/onfiguruj `config.json`** (v root adresáři)
   ```json
   {
     "prefix": "!",
     "embed_color": "FFD700",
     "wiki_url": "https://wiki.example.com",
     "campfire_channel": "campfire"
   }
   ```

6. **Spusť bota**
   ```
   python main.py
   ```

## 📁 Projekt Struktura

```
ArionBot/
├── main.py              # Hlavní bot entrypoint
├── config.json          # Konfigurační soubor
├── .env                 # Token a ID (neupublikuj!)
├── readme.md            # Tato dokumentace
├── data/
│   └── parties.json     # Databáze družin (JSON persistence)
└── src/
    ├── cogs/
    │   ├── party.py     # Správa družin, modaly, interactions
    │   └── aurionis.py  # Lore a info příkazy (WIP)
    ├── database/
    │   └── party.py     # PartyManager - logika perzistence
    └── utils/
        └── embeds.py    # Shared embed helpers s watermarkem
```

## 🏗️ Architektura

### Modularita
- **Cog-based design**: Každá funkce v samostatném cog (party.py, aurionis.py)
- **Database layer**: Centralizovaný PartyManager s JSON persistence
- **Utils**: Sdílené helpy (embeds, validace)

### Party Database (`data/parties.json`)
Každá party má:
```json
{
  "party_name": {
    "leader": 123456,
    "members": [123456, 789012],
    "quest": "Vyhledat tajný chrám",
    "is_private": false,
    "whitelist": [123456, 789012],
    "invites": {"123456": ["2025-02-20T10:00:00"]},
    "thread_id": 999888,
    "color": "FF00AA",
    "emoji": "🦋",
    "created_at": "2025-02-20T10:00:00"
  }
}
```

## 🎭 UI & UX

### Modal Forms
- **`/party set jmeno:<name>`** otevře fantasy-stylizovaný modal s poli:
  - Název Družiny (hint z autocomplete)
  - Cíl Výpravy
  - Hlavní Emblem (emoji)
  - Barva (Hex kód)

### Embeds
- Moderní, epic design s:
  - Party barvou (custom hex na borders)
  - Emoji prefix v titulcích
  - Watermark "✨ Aurionis ✨" v footeru
  - Jasná struktura s fields pro informace

### Interactions
- Button-based invite acceptance (Accept/Decline v DM)
- Autocomplete pro party names
- Ephemeral responses pro soukromé operace

## 🐛 Troubleshooting

### Bot se nepřipojuje
- Zkontroluj `.env` (control znaky, BOM encoding)
- Zkontroluj `DISCORD_TOKEN` a `GUILD_ID`

### `/party set` neotevře modal
- Zkontroluj že server má slash command sync
- Restart bot (`python main.py` znovu)
- Zkontroluj bot permissiony (Send Messages, Use Slash Commands)

### Private thread se nevytvoří
- Zkontroluj že kanál `#campfire` existuje
- Zkontroluj bot permissiony na Create Threads, Manage Threads

### DB chyby
- Jestli `data/parties.json` není přístupný, bot vytvoří nový
- Pro reset: smaž `data/parties.json` (data budou ztracena!)

## 🔮 Future Features (TODO)
- [ ] Aurionis lore cog (wiki integraci)
- [ ] Party level/XP systém
- [ ] Character sheets
- [ ] Treasure/loot tracking
- [ ] Campaign journals/logs

## 📝 Poznámky pro Vývojáře

### Kód Kvalita
- Všechny embeds mají watermark "✨ Aurionis ✨"
- Helper metody: `_validate_hex_color()`, `_update_thread_emoji()`, `_get_party_color()`
- Čisté, modulární kódy bez duplicitů
- Type hints kde je relevantní

### Databáze
- PartyManager zpracovává všechny operace
- Atomické transakce (read-modify-write)
- Tolerantní k chybám (empty/invalid JSON vrací {})

### Interakce
- Listeners pro cleanup když se thready/kanály smažou
- Ephemeral responses pro citlivé info
- Error embeds s jasnou diagnostikou

---

**⚔️ Tvůrce**: Mathé  
**🐱 Maskot**: Arion  
**🌟 Verze**: 1.0  
**📅 Poslední update**: Únor 2025