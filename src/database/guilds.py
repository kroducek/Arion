"""
GuildManager — databázový manažer pro správu guild v Aurionisu.

Paralela k PartyManager, ale guildy jsou STÁLÉ a EXKLUZIVNÍ:
    • hráč může být max v JEDNÉ guildě (na rozdíl od party, kde jsou 3),
    • 3 úrovně hodností: guildmaster → officer → member.

Cesta: src/database/guild.py
POZOR: přidej do src/utils/paths.py konstantu GUILDS (analogicky k PARTIES),
       např.:  GUILDS = os.path.join(DATA_DIR, "guilds.json")
"""
import time
from typing import List, Optional, Dict
from src.utils.paths import GUILDS
from src.utils.json_utils import load_json, save_json


class GuildManager:
    """Databázový manažer pro správu guild v Aurionisu."""

    # Výchozí kapacita nové guildy (vůdce může změnit přes set_capacity)
    DEFAULT_CAPACITY = 50

    # Platné režimy náboru
    RECRUITMENT_MODES = ("open", "apply", "closed")

    # Maximum pozvánek na officera za 24h (rate limiting)
    MAX_INVITES_PER_DAY = 3

    def __init__(self, filename: str = GUILDS):
        self.filename = filename
        self._ensure_file()

    # ============================================================
    # Interní práce se souborem
    # ============================================================

    def _ensure_file(self):
        # load_json + save_json vytvoří soubor automaticky při prvním zápisu
        pass

    def _load(self) -> Dict:
        return load_json(self.filename, default={})

    def _save(self, data: Dict):
        save_json(self.filename, data)

    # ============================================================
    # Exkluzivita členství (1 guilda na hráče)
    # ============================================================

    def get_user_guild(self, user_id: int) -> Optional[str]:
        """Vrátí název guildy, ve které hráč je — nebo None. (Exkluzivní: max 1.)"""
        data = self._load()
        for name, guild in data.items():
            if user_id in guild.get("members", []):
                return name
        return None

    def is_in_any_guild(self, user_id: int) -> bool:
        """True pokud hráč už je v nějaké guildě."""
        return self.get_user_guild(user_id) is not None

    def is_user_in_guild(self, name: str, user_id: int) -> bool:
        """Zkontroluje, zda je hráč členem konkrétní guildy."""
        guild = self.get_guild(name)
        if not guild:
            return False
        return user_id in guild.get("members", [])

    # ============================================================
    # Hodnosti (guildmaster > officer > member)
    # ============================================================

    def get_rank(self, name: str, user_id: int) -> Optional[str]:
        """
        Vrátí hodnost hráče v guildě:
        "guildmaster" | "officer" | "member" | None (není členem).
        """
        guild = self.get_guild(name)
        if not guild:
            return None
        if user_id not in guild.get("members", []):
            return None
        if guild.get("guildmaster") == user_id:
            return "guildmaster"
        if user_id in guild.get("officers", []):
            return "officer"
        return "member"

    def is_guildmaster(self, name: str, user_id: int) -> bool:
        """True pokud je hráč vůdcem guildy."""
        guild = self.get_guild(name)
        if not guild:
            return False
        return guild.get("guildmaster") == user_id

    def is_officer(self, name: str, user_id: int) -> bool:
        """True pokud je hráč POUZE důstojník (ne vůdce)."""
        guild = self.get_guild(name)
        if not guild:
            return False
        return user_id in guild.get("officers", [])

    def is_officer_or_above(self, name: str, user_id: int) -> bool:
        """True pokud je hráč důstojník NEBO vůdce. (Gating pro invite/kick.)"""
        return self.is_guildmaster(name, user_id) or self.is_officer(name, user_id)

    def promote_to_officer(self, name: str, user_id: int) -> bool:
        """Povýší člena na důstojníka. Vrátí False pokud není člen nebo už je officer/GM."""
        data = self._load()
        guild = data.get(name)
        if not guild:
            return False
        if user_id not in guild.get("members", []):
            return False
        if guild.get("guildmaster") == user_id:
            return False
        officers = guild.setdefault("officers", [])
        if user_id in officers:
            return False
        officers.append(user_id)
        self._save(data)
        return True

    def demote_to_member(self, name: str, user_id: int) -> bool:
        """Sesadí důstojníka zpět na člena. Vrátí False pokud není důstojník."""
        data = self._load()
        guild = data.get(name)
        if not guild:
            return False
        officers = guild.get("officers", [])
        if user_id not in officers:
            return False
        officers.remove(user_id)
        self._save(data)
        return True

    def set_guildmaster(self, name: str, user_id: int) -> bool:
        """
        Předá vedení guildy novému hráči (pro /guild_transfer).
        Nový vůdce musí být členem. Starý vůdce se stane důstojníkem.
        """
        data = self._load()
        guild = data.get(name)
        if not guild:
            return False
        if user_id not in guild.get("members", []):
            return False

        old_gm = guild.get("guildmaster")
        guild["guildmaster"] = user_id

        officers = guild.setdefault("officers", [])
        # Nový vůdce už nesmí být v seznamu důstojníků
        if user_id in officers:
            officers.remove(user_id)
        # Starý vůdce klesá na důstojníka (pokud existoval a není to tentýž)
        if old_gm is not None and old_gm != user_id and old_gm not in officers:
            officers.append(old_gm)

        self._save(data)
        return True

    # ============================================================
    # Guild CRUD
    # ============================================================

    def create_guild(
        self,
        name: str,
        leader_id: int,
        quest: str,
        tag: Optional[str] = None,
        description: Optional[str] = None,
        recruitment: str = "open",
    ) -> bool:
        """
        Vytvoří novou guildu. Zakladatel se stává vůdcem.
        Vrátí False pokud: název existuje NEBO hráč už je v nějaké guildě (exkluzivita).
        """
        name = name.strip().lower()
        data = self._load()

        if name in data:
            return False

        # Exkluzivita — hráč nesmí být v žádné jiné guildě
        if self.is_in_any_guild(leader_id):
            return False

        if recruitment not in self.RECRUITMENT_MODES:
            recruitment = "open"

        data[name] = {
            "guildmaster": leader_id,
            "officers": [],
            "members": [leader_id],
            "tag": (tag.strip().upper() if tag else None),
            "description": (description.strip() if description else None),
            "quest": quest,                 # motto / cíl guildy
            "recruitment": recruitment,     # open | apply | closed
            "capacity": self.DEFAULT_CAPACITY,
            "created_at": int(time.time()),
            "founder": leader_id,
            "color": None,
            "emoji": None,
            "thread_id": None,
            "applications": [],             # čekající žadatelé (user_id)
            "whitelist": [],                # přímo pozvaní — smí vstoupit i při closed
            "invites_today": {},            # rate limiting {user_id_str: [ts, ...]}
        }

        self._save(data)
        return True

    def delete_guild(self, name: str) -> bool:
        """Smaže guildu včetně všech dat. Vrátí False pokud neexistuje."""
        name = name.strip().lower()
        data = self._load()
        if name not in data:
            return False
        del data[name]
        self._save(data)
        return True

    def get_guild(self, name: str) -> Optional[Dict]:
        """Vrátí data guildy nebo None."""
        data = self._load()
        return data.get(name.strip().lower())

    def list_all_guilds(self) -> Dict:
        """Vrátí všechny guildy jako dict {name: data}."""
        return self._load()

    def rename_guild(self, old_name: str, new_name: str) -> bool:
        """Přejmenuje guildu. Vrátí False pokud old neexistuje nebo new je obsazeno."""
        old_name = old_name.strip().lower()
        new_name = new_name.strip().lower()
        data = self._load()
        if old_name not in data or new_name in data:
            return False
        data[new_name] = data.pop(old_name)
        self._save(data)
        return True

    # ============================================================
    # Členové
    # ============================================================

    def member_count(self, name: str) -> int:
        """Vrátí počet členů guildy."""
        guild = self.get_guild(name)
        if not guild:
            return 0
        return len(guild.get("members", []))

    def is_full(self, name: str) -> bool:
        """True pokud guilda dosáhla své kapacity."""
        guild = self.get_guild(name)
        if not guild:
            return False
        cap = guild.get("capacity", self.DEFAULT_CAPACITY)
        return len(guild.get("members", [])) >= cap

    def add_member(self, name: str, user_id: int) -> bool:
        """
        Přidá hráče do guildy.
        Vrátí False pokud: guilda neexistuje, hráč už je člen,
        hráč už je v JINÉ guildě (exkluzivita), nebo je guilda plná.
        """
        name = name.strip().lower()
        data = self._load()
        guild = data.get(name)

        if not guild:
            return False
        if user_id in guild.get("members", []):
            return False
        if self.is_in_any_guild(user_id):
            return False
        cap = guild.get("capacity", self.DEFAULT_CAPACITY)
        if len(guild.get("members", [])) >= cap:
            return False

        guild["members"].append(user_id)

        # Úklid po vstupu — splněná pozvánka i přihláška už nejsou potřeba
        if user_id in guild.get("whitelist", []):
            guild["whitelist"].remove(user_id)
        if user_id in guild.get("applications", []):
            guild["applications"].remove(user_id)

        self._save(data)
        return True

    def remove_member(self, name: str, user_id: int) -> bool:
        """
        Odebere hráče z guildy. Pokud byl důstojník, sundá ho i z officers.
        Vrátí False pokud guilda/hráč neexistuje NEBO je hráč vůdce
        (vůdce musí nejdřív předat vedení nebo guildu rozpustit).
        """
        name = name.strip().lower()
        data = self._load()
        guild = data.get(name)

        if not guild:
            return False
        if user_id not in guild.get("members", []):
            return False
        if guild.get("guildmaster") == user_id:
            return False  # vůdce nemůže jen tak odejít

        guild["members"].remove(user_id)
        if user_id in guild.get("officers", []):
            guild["officers"].remove(user_id)

        self._save(data)
        return True

    # ============================================================
    # Nábor a přihlášky
    # ============================================================

    def set_recruitment(self, name: str, mode: str) -> bool:
        """Nastaví režim náboru: open | apply | closed. Vrátí False pro neplatný režim."""
        if mode not in self.RECRUITMENT_MODES:
            return False
        data = self._load()
        if name in data:
            data[name]["recruitment"] = mode
            self._save(data)
            return True
        return False

    def get_recruitment(self, name: str) -> Optional[str]:
        """Vrátí aktuální režim náboru guildy."""
        guild = self.get_guild(name)
        if not guild:
            return None
        return guild.get("recruitment", "open")

    def add_application(self, name: str, user_id: int) -> bool:
        """Přidá přihlášku hráče do fronty (režim 'apply')."""
        data = self._load()
        guild = data.get(name)
        if not guild:
            return False
        apps = guild.setdefault("applications", [])
        if user_id in apps:
            return False
        apps.append(user_id)
        self._save(data)
        return True

    def remove_application(self, name: str, user_id: int) -> bool:
        """Odebere přihlášku z fronty (po schválení/zamítnutí)."""
        data = self._load()
        guild = data.get(name)
        if not guild:
            return False
        apps = guild.get("applications", [])
        if user_id not in apps:
            return False
        apps.remove(user_id)
        self._save(data)
        return True

    def list_applications(self, name: str) -> List[int]:
        """Vrátí seznam ID čekajících žadatelů."""
        guild = self.get_guild(name)
        if not guild:
            return []
        return list(guild.get("applications", []))

    def is_applicant(self, name: str, user_id: int) -> bool:
        """True pokud má hráč čekající přihlášku do guildy."""
        guild = self.get_guild(name)
        if not guild:
            return False
        return user_id in guild.get("applications", [])

    # ============================================================
    # Systém pozvánek (přímá pozvánka officera → whitelist)
    # ============================================================

    def add_to_whitelist(self, name: str, user_id: int) -> bool:
        """Povolí pozvanému hráči vstup (i když je guilda 'closed')."""
        data = self._load()
        guild = data.get(name)
        if not guild:
            return False
        wl = guild.setdefault("whitelist", [])
        if user_id not in wl:
            wl.append(user_id)
            self._save(data)
        return True

    def remove_from_whitelist(self, name: str, user_id: int) -> bool:
        """Odebere hráče z whitelistu (rollback při selhání DM doručení)."""
        data = self._load()
        guild = data.get(name)
        if not guild:
            return False
        wl = guild.get("whitelist", [])
        if user_id in wl:
            wl.remove(user_id)
            guild["whitelist"] = wl
            self._save(data)
        return True

    def is_on_whitelist(self, name: str, user_id: int) -> bool:
        """Zkontroluje, zda byl hráč přímo pozván."""
        guild = self.get_guild(name)
        if not guild:
            return False
        return user_id in guild.get("whitelist", [])

    def can_invite(self, name: str, user_id: int) -> bool:
        """
        Zkontroluje, zda officer nevyčerpal denní limit pozvánek.
        Automaticky čistí záznamy starší než 24h.
        """
        data = self._load()
        guild = data.get(name)
        if not guild:
            return False

        user_str = str(user_id)
        invites = guild.get("invites_today", {}).get(user_str, [])

        current_time = time.time()
        invites = [ts for ts in invites if current_time - ts < 86400]

        guild.setdefault("invites_today", {})[user_str] = invites
        self._save(data)

        return len(invites) < self.MAX_INVITES_PER_DAY

    def record_invite(self, name: str, user_id: int):
        """Zaznamená pozvánku pro rate limiting."""
        data = self._load()
        guild = data.get(name)
        if not guild:
            return

        user_str = str(user_id)
        invites = guild.setdefault("invites_today", {}).setdefault(user_str, [])
        invites.append(time.time())
        self._save(data)

    # ============================================================
    # Kosmetika a metadata
    # ============================================================

    def set_color(self, name: str, hex_color: str):
        """Nastaví hex barvu embedu guildy (bez '#', např. 'FF5500')."""
        data = self._load()
        if name in data:
            data[name]["color"] = hex_color
            self._save(data)

    def set_emoji(self, name: str, emoji: str):
        """Nastaví emoji emblém guildy."""
        data = self._load()
        if name in data:
            data[name]["emoji"] = emoji
            self._save(data)

    def set_quest(self, name: str, quest: str):
        """Nastaví motto / cíl guildy."""
        data = self._load()
        if name in data:
            data[name]["quest"] = quest
            self._save(data)

    def set_tag(self, name: str, tag: str):
        """Nastaví zkratku guildy (např. 'AUR' → zobrazí se jako [AUR])."""
        data = self._load()
        if name in data:
            data[name]["tag"] = tag.strip().upper() if tag else None
            self._save(data)

    def set_description(self, name: str, description: str):
        """Nastaví delší popis / lore guildy."""
        data = self._load()
        if name in data:
            data[name]["description"] = description.strip() if description else None
            self._save(data)

    def set_capacity(self, name: str, capacity: int):
        """Nastaví maximální počet členů guildy."""
        data = self._load()
        if name in data:
            data[name]["capacity"] = max(1, int(capacity))
            self._save(data)

    def set_thread_id(self, name: str, thread_id: int):
        """Uloží ID Discord threadu guildy."""
        data = self._load()
        if name in data:
            data[name]["thread_id"] = thread_id
            self._save(data)

    def remove_thread_id(self, name: str):
        """Vymaže thread_id (při smazání threadu)."""
        data = self._load()
        if name in data:
            data[name]["thread_id"] = None
            self._save(data)