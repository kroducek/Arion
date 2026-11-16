"""Lokální kontrola výběru scén bez Discord tokenu a volání OpenAI."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.core.ai import archives, service
from src.database import db


class ArchiveSearchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        original_path = db.db_path()
        self.addCleanup(db.reset_for_tests, original_path)
        db.reset_for_tests(str(Path(temp.name) / "arion.db"))
        archives.setup()
        archives.register(10, 20, "Vall")
        self.channel = SimpleNamespace(id=20, guild=SimpleNamespace(id=10))

    def fill(self, texts):
        archives.insert_batch([(20, i, "Vypravěč", text, archives.normalize(text))
                               for i, text in enumerate(texts, 1)])

    def scene(self, question, phrase=""):
        return archives.select_scene(self.channel, question, phrase, ["Vall"], 10000)

    def test_latest_scene_precedes_marked_ooc(self):
        self.fill(["Vall otevřel dveře.", "Za nimi čekala stráž."] + ["// Příště v pátek."] * 600)
        self.assertTrue(archives.alias_match("Vall", "Co se Vallovi přihodilo?"))
        self.assertEqual(len(self.scene("Stručně řekni, co posledního Vall zažil.")), 2)

    def test_profile_does_not_require_the_subject_to_own_an_archive(self):
        terms = archives.lookup_terms("Co víš o Karlovi?", "", [["Vall"]])
        self.assertEqual(terms, ["karl"])
        question = "Kdo je Karl?"
        self.fill(["Vall svěřil Karlovi mapu."])
        archives.insert_batch([(20, 50, "Karl", "Mám ji.", "mam ji.")])
        rows = archives.select_scene(self.channel, question, "", [], 10000, subject=terms)
        self.assertEqual([r["autor"] for r in rows], ["Vypravěč", "Karl"])
        self.assertEqual(archives.lookup_terms("Kdo je Vall?", "", [["Vall", "Vlk"]]), ["vall", "vlk"])
        self.assertEqual(archives.lookup_terms("Kdo je Vall?", "pečeť", [["Vall"]]), ["pecet"])

    def test_early_encounter_context_edit_and_deletion(self):
        self.fill(["U brány stojí rytíř.", "Karl se představí.", "Vall mu nabízí nocleh."] +
                  ["Další scéna."] * 550 + ["Karl se vrací."])
        found = self.scene("Kdy Vall poprvé potkal Karla?")
        self.assertEqual(found[0]["text"], "U brány stojí rytíř.")
        self.assertEqual(found[1]["zdroj"], "https://discord.com/channels/10/20/2")
        archives.insert_batch([(20, 2, "DM", "ŘP je Řád poutníků.", "rp je rad poutniku.")], replace=True)
        self.assertTrue(self.scene("Co znamená zkratka ŘP?"))
        archives.erase(20, [2])
        archives.insert_batch([(20, 2, "DM", "stará ŘP", "stara rp")])
        self.assertFalse(self.scene("Co znamená zkratka ŘP?"))

    def test_canon_visibility_and_source_links(self):
        db.save_doc("arion_canon:10", {"1": dict(channel=20, public=False, druh="výrok", text="Vall se vrátí.")})
        def canon(guild, channel, private):
            return service.lore_context(guild, include_dm_only=private, channel_id=channel, question="Vall")
        self.assertFalse(canon(10, 20, False))
        self.assertFalse(canon(11, 20, True))
        self.assertFalse(canon(10, 21, True))
        self.assertEqual(canon(10, 20, True)[0]["druh"], "výrok")
        self.assertEqual(service.extract_sources("Vall odchází.\nZDROJE: 2,99", ["a", "b"]),
                         ("Vall odchází.", ["b"]))
        self.assertTrue(archives.capabilities_question("Co všechno dokážeš?"))
