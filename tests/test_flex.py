import unittest

from src.logic import flex

ITEMS_DB = {
    "mec_svetla": {"name": "Meč světla"},
    "lektvar_hp": {"name": "Lektvar HP"},
    "luk_lesni":  {"name": "Lesní luk"},
    "batoh":      {"name": "Batoh", "storage": {"capacity": 10}},
}


def _profile(with_batoh: bool = True) -> dict:
    inventory = [
        {"type": "registered", "id": "mec_svetla"},
        {"type": "custom", "name": "Dopis od krále", "desc": "Zapečetěný."},
    ]
    if with_batoh:
        inventory.append({"type": "registered", "id": "batoh"})
    return {
        "inventory": inventory,
        "storages": {"batoh": [{"type": "registered", "id": "lektvar_hp"}]},
        "equipment": {"hand_r": "luk_lesni", "helmet": None},
    }


class FindOwnedTests(unittest.TestCase):
    def test_finds_registered_item_in_inventory(self):
        entry = flex._find_owned(_profile(), "mec_svetla", ITEMS_DB)
        self.assertEqual(entry["id"], "mec_svetla")

    def test_finds_item_in_owned_storage_and_equipment(self):
        self.assertIsNotNone(flex._find_owned(_profile(), "lektvar_hp", ITEMS_DB))
        self.assertIsNotNone(flex._find_owned(_profile(), "luk_lesni", ITEMS_DB))

    def test_orphaned_storage_contents_are_not_flexable(self):
        # Batoh už hráč nemá, ale jeho seznam zůstal v profilu.
        self.assertIsNone(flex._find_owned(_profile(with_batoh=False), "lektvar_hp", ITEMS_DB))

    def test_finds_custom_item_by_name_case_insensitive(self):
        entry = flex._find_owned(_profile(), "dopis od krále", ITEMS_DB)
        self.assertEqual(entry["name"], "Dopis od krále")

    def test_unowned_item_returns_none(self):
        self.assertIsNone(flex._find_owned(_profile(), "artefakt_boha", ITEMS_DB))


if __name__ == "__main__":
    unittest.main()
