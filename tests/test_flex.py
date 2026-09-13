import unittest

from src.logic import flex


class FindOwnedTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "inventory": [
                {"type": "registered", "id": "mec_svetla"},
                {"type": "custom", "name": "Dopis od krále", "desc": "Zapečetěný."},
            ],
            "storages": {"batoh": [{"type": "registered", "id": "lektvar_hp"}]},
            "equipment": {"hand_r": "luk_lesni", "helmet": None},
        }

    def test_finds_registered_item_in_inventory(self):
        entry = flex._find_owned(self.profile, "mec_svetla")
        self.assertEqual(entry["id"], "mec_svetla")

    def test_finds_item_in_storage_and_equipment(self):
        self.assertIsNotNone(flex._find_owned(self.profile, "lektvar_hp"))
        self.assertIsNotNone(flex._find_owned(self.profile, "luk_lesni"))

    def test_finds_custom_item_by_name_case_insensitive(self):
        entry = flex._find_owned(self.profile, "dopis od krále")
        self.assertEqual(entry["name"], "Dopis od krále")

    def test_unowned_item_returns_none(self):
        self.assertIsNone(flex._find_owned(self.profile, "artefakt_boha"))


if __name__ == "__main__":
    unittest.main()
