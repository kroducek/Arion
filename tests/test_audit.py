import unittest
import os
import json
import threading
from unittest.mock import patch
from src.utils import audit

TEST_AUDIT_FILE = "test_audit_log.json"

class TestAudit(unittest.TestCase):
    def setUp(self):
        # Override the audit log path for testing
        self.patcher = patch('src.utils.audit.AUDIT_LOG', TEST_AUDIT_FILE)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(TEST_AUDIT_FILE):
            os.remove(TEST_AUDIT_FILE)
            
    def test_log_action(self):
        audit.log_action("test_action", "Admin", "User", "Detail")
        self.assertTrue(os.path.exists(TEST_AUDIT_FILE))
        
        with open(TEST_AUDIT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["action"], "test_action")
        self.assertEqual(data[0]["actor"], "Admin")
        self.assertEqual(data[0]["target"], "User")
        self.assertEqual(data[0]["detail"], "Detail")
        self.assertIn("ts", data[0])
        
    def test_get_recent(self):
        for i in range(10):
            audit.log_action("action", "actor", f"target{i}")
            
        recent = audit.get_recent(5)
        self.assertEqual(len(recent), 5)
        self.assertEqual(recent[-1]["target"], "target9")
        self.assertEqual(recent[0]["target"], "target5")
        
    def test_max_entries(self):
        with patch('src.utils.audit.MAX_ENTRIES', 10):
            for i in range(15):
                audit.log_action("action", "actor", f"target{i}")
                
            data = audit._load()
            self.assertEqual(len(data), 10)
            self.assertEqual(data[0]["target"], "target5")
            self.assertEqual(data[-1]["target"], "target14")
            
    def test_thread_safety(self):
        def worker(actor_id):
            for i in range(20):
                audit.log_action("threaded_action", f"Actor{actor_id}", f"Target{i}")
                
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
            
        data = audit._load()
        self.assertEqual(len(data), 100) # 5 threads * 20 actions

if __name__ == "__main__":
    unittest.main()
