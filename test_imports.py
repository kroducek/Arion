#!/usr/bin/env python
"""Quick import test to verify syntax."""

try:
    from src.utils.logger import configure_logging, get_logger
    print("✅ logger.py OK")
except Exception as e:
    print(f"❌ logger.py FAIL: {e}")

try:
    from src.utils.audit import log_action, get_recent
    print("✅ audit.py OK")
except Exception as e:
    print(f"❌ audit.py FAIL: {e}")

try:
    from src.logic.economy import _load_economy, _save_economy
    print("✅ economy.py OK")
except Exception as e:
    print(f"❌ economy.py FAIL: {e}")

try:
    from src.core.dnd.achievements import load_achievements, save_achievements
    print("✅ achievements.py OK")
except Exception as e:
    print(f"❌ achievements.py FAIL: {e}")

try:
    from src.core.dnd.perks import load_perks, save_perks
    print("✅ perks.py OK")
except Exception as e:
    print(f"❌ perks.py FAIL: {e}")

try:
    from src.core.dnd.aurionis import Aurionis
    print("✅ aurionis.py OK")
except Exception as e:
    print(f"❌ aurionis.py FAIL: {e}")

try:
    from src.core.bot.story import load_library, save_to_library
    print("✅ story.py OK")
except Exception as e:
    print(f"❌ story.py FAIL: {e}")

print("\n✅ All imports completed!")
