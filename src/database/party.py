import time
from typing import List, Optional, Dict
from src.utils.paths import PARTIES
from src.utils.json_utils import load_json, save_json


class PartyManager:
    """Databázový manažer pro správu družin v Aurionisu."""

    def __init__(self, filename: str = PARTIES):
        self.filename = filename
        
        self.MAX_PARTIES_PER_USER = 3
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
    # Multi-party kontroly
    # ============================================================

    def get_user_parties(self, user_id: int) -> List[str]:
        """Vrátí seznam názvů všech družin, ve kterých hráč je."""
        data = self._load()
        return [
            name for name, party in data.items()
            if user_id in party.get("members", [])
        ]

    def get_user_party(self, user_id: int) -> Optional[str]:
        """
        Legacy alias — vrátí první (nebo jedinou) party hráče.
        Preferuj get_user_parties() pro multi-party logiku.
        """
        parties = self.get_user_parties(user_id)
        return parties[0] if parties else None

    def get_user_party_count(self, user_id: int) -> int:
        """Vrátí počet družin hráče."""
        return len(self.get_user_parties(user_id))

    def is_user_in_party(self, name: str, user_id: int) -> bool:
        """Zkontroluje, zda je hráč členem dané družiny."""
        party = self.get_party(name)
        if not party:
            return False
        return user_id in party.get("members", [])

    def is_leader(self, name: str, user_id: int) -> bool:
        """Zkontroluje, zda je hráč vůdcem dané družiny."""
        party = self.get_party(name)
        if not party:
            return False
        return party.get("leader") == user_id

    # ============================================================
    # Party CRUD
    # ============================================================

    def create_party(self, name: str, leader_id: int, quest: str, is_private: bool = False) -> bool:
        """
        Vytvoří novou družinu.
        Vrátí False pokud název existuje nebo hráč dosáhl limitu 3 družin.
        """
        name = name.strip().lower()
        data = self._load()

        if name in data:
            return False

        if self.get_user_party_count(leader_id) >= self.MAX_PARTIES_PER_USER:
            return False

        data[name] = {
            "leader": leader_id,
            "quest": quest,           # Klíč 'quest' — konzistentní s cogem
            "members": [leader_id],
            "is_private": is_private,
            "created_at": int(time.time()),
            "color": None,
            "emoji": None,
            "thread_id": None,
            "whitelist": [],          # Hráči pozvaní do soukromé party
            "invites_today": {}       # Rate limiting pozvánek {user_id_str: [timestamp, ...]}
        }

        self._save(data)
        return True

    def delete_party(self, name: str) -> bool:
        """Smaže party včetně všech dat. Vrátí False pokud neexistuje."""
        name = name.strip().lower()
        data = self._load()
        if name not in data:
            return False
        del data[name]
        self._save(data)
        return True

    def get_party(self, name: str) -> Optional[Dict]:
        """Vrátí data party nebo None."""
        data = self._load()
        return data.get(name.strip().lower())

    def list_all_parties(self) -> Dict:
        """Vrátí všechny party jako dict {name: data}."""
        return self._load()

    def rename_party(self, old_name: str, new_name: str) -> bool:
        """Přejmenuje party. Vrátí False pokud old neexistuje nebo new je obsazeno."""
        old_name = old_name.strip().lower()
        new_name = new_name.strip().lower()
        data = self._load()
        if old_name not in data or new_name in data:
            return False
        data[new_name] = data.pop(old_name)
        self._save(data)
        return True

    # ============================================================
    # Členové a Vedení
    # ============================================================

    def add_member(self, name: str, user_id: int) -> bool:
        """
        Přidá hráče do party.
        Vrátí False pokud: party neexistuje, hráč už je členem,
        nebo hráč dosáhl limitu 3 družin.
        """
        name = name.strip().lower()
        data = self._load()
        party = data.get(name)

        if not party:
            return False
        if user_id in party.get("members", []):
            return False
        if self.get_user_party_count(user_id) >= self.MAX_PARTIES_PER_USER:
            return False

        party["members"].append(user_id)

        # Po připojení odstraníme z whitelistu (pozvánka splněna)
        if user_id in party.get("whitelist", []):
            party["whitelist"].remove(user_id)

        self._save(data)
        return True

    def remove_member(self, name: str, user_id: int) -> bool:
        """
        Odebere hráče z party.
        Vrátí False pokud party nebo hráč neexistuje.
        """
        name = name.strip().lower()
        data = self._load()
        party = data.get(name)

        if not party:
            return False
        if user_id not in party.get("members", []):
            return False

        party["members"].remove(user_id)
        self._save(data)
        return True

    def set_leader(self, name: str, user_id: int) -> bool:
        """
        Nastaví nového vůdce party (pro /party_promote).
        Hráč musí být členem party.
        """
        data = self._load()
        party = data.get(name)

        if not party:
            return False
        if user_id not in party.get("members", []):
            return False

        party["leader"] = user_id
        self._save(data)
        return True

    # ============================================================
    # Systém Pozvánek a Soukromí
    # ============================================================

    def add_to_whitelist(self, name: str, user_id: int) -> bool:
        """Povolí hráči vstup do soukromé party (po pozvánce)."""
        data = self._load()
        party = data.get(name)
        if not party:
            return False

        if "whitelist" not in party:
            party["whitelist"] = []

        if user_id not in party["whitelist"]:
            party["whitelist"].append(user_id)
            self._save(data)
        return True

    def remove_from_whitelist(self, name: str, user_id: int) -> bool:
        """
        Odstraní hráče z whitelistu (rollback při selhání DM doručení).
        """
        data = self._load()
        party = data.get(name)
        if not party:
            return False

        whitelist = party.get("whitelist", [])
        if user_id in whitelist:
            whitelist.remove(user_id)
            party["whitelist"] = whitelist
            self._save(data)
        return True

    def is_on_whitelist(self, name: str, user_id: int) -> bool:
        """Zkontroluje, zda je hráč na whitelistu soukromé party."""
        party = self.get_party(name)
        if not party:
            return False
        return user_id in party.get("whitelist", [])

    def can_invite(self, name: str, user_id: int) -> bool:
        """
        Zkontroluje, zda vůdce nevyčerpal denní limit 3 pozvánek.
        Automaticky čistí záznamy starší než 24h.
        """
        data = self._load()
        party = data.get(name)
        if not party:
            return False

        user_str = str(user_id)
        invites = party.get("invites_today", {}).get(user_str, [])

        # Vyčistit staré záznamy (starší než 86400s = 24h)
        current_time = time.time()
        invites = [ts for ts in invites if current_time - ts < 86400]

        # Uložíme vyčištěný seznam zpět
        if "invites_today" not in party:
            party["invites_today"] = {}
        party["invites_today"][user_str] = invites
        self._save(data)

        return len(invites) < 3

    def record_invite(self, name: str, user_id: int):
        """Zaznamená pozvánku pro rate limiting."""
        data = self._load()
        party = data.get(name)
        if not party:
            return

        user_str = str(user_id)
        if "invites_today" not in party:
            party["invites_today"] = {}
        if user_str not in party["invites_today"]:
            party["invites_today"][user_str] = []

        party["invites_today"][user_str].append(time.time())
        self._save(data)

    # ============================================================
    # Kosmetika a Metadata
    # ============================================================

    def set_color(self, name: str, hex_color: str):
        """Nastaví hex barvu embedu party (bez '#', např. 'FF5500')."""
        data = self._load()
        if name in data:
            data[name]["color"] = hex_color
            self._save(data)

    def set_emoji(self, name: str, emoji: str):
        """Nastaví emoji emblém party."""
        data = self._load()
        if name in data:
            data[name]["emoji"] = emoji
            self._save(data)

    def set_quest(self, name: str, quest: str):
        """Nastaví cíl/popis výpravy party."""
        data = self._load()
        if name in data:
            data[name]["quest"] = quest   # Klíč 'quest' — konzistentní s cogem
            self._save(data)

    def set_thread_id(self, name: str, thread_id: int):
        """Uloží ID Discord threadu party."""
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