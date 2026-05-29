import unittest
import os
import json
import threading
from src.utils.json_utils import load_json, save_json

TEST_FILE = "test_data.json"

class TestJsonUtils(unittest.TestCase):
    def tearDown(self):
        if os.path.exists(TEST_FILE):
            os.remove(TEST_FILE)
            
    def test_load_nonexistent(self):
        data = load_json(TEST_FILE, default={"foo": "bar"})
        self.assertEqual(data, {"foo": "bar"})
        
    def test_save_and_load(self):
        save_json(TEST_FILE, {"test": 123})
        self.assertTrue(os.path.exists(TEST_FILE))
        data = load_json(TEST_FILE)
        self.assertEqual(data, {"test": 123})
        
    def test_invalid_json(self):
        with open(TEST_FILE, "w", encoding="utf-8") as f:
            f.write("{invalid json]")
        data = load_json(TEST_FILE, default=[])
        self.assertEqual(data, [])

    def test_thread_safety(self):
        # We simulate how Cogs use json_utils (with a dedicated lock for the operation)
        save_json(TEST_FILE, {"count": 0})
        app_lock = threading.Lock()
        
        def worker():
            for _ in range(50):
                with app_lock:
                    d = load_json(TEST_FILE)
                    d["count"] += 1
                    save_json(TEST_FILE, d)
                
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
            
        final_data = load_json(TEST_FILE)
        self.assertEqual(final_data["count"], 500)

if __name__ == "__main__":
    unittest.main()
