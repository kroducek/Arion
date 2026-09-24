import os
import subprocess
import sys
import threading
import time
from dotenv import load_dotenv

# Optional bot tokens must also be visible when launched from a local .env.
load_dotenv()

def run(script):
    """Spustí script a čeká na konec. Obsahuje error handling."""
    try:
        print(f"[start.py] Starting {script}...")
        proc = subprocess.Popen(
            [sys.executable, "-u", script],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        returncode = proc.wait()
        print(f"[start.py] {script} exited with code {returncode}")
        sys.exit(returncode or 1)
    except KeyboardInterrupt:
        print("[start.py] Interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"[start.py] Error running {script}: {e}")
        sys.exit(1)

def run_optional(script, env_var):
    """Spustí bota jen když má token — bez tokenu se tiše přeskočí."""
    if not os.getenv(env_var):
        print(f"[start.py] {script} přeskočen — {env_var} není nastavený.")
        return
    try:
        print(f"[start.py] Starting {script}...")
        proc = subprocess.Popen(
            [sys.executable, "-u", script],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        proc.wait()
        print(f"[start.py] {script} exited with code {proc.returncode}")
    except Exception as e:
        print(f"[start.py] Error running {script}: {e}")

# Spustit ArionDND v daemon threadu
dnd_thread = threading.Thread(target=run, args=("main_dnd.py",), daemon=True)
dnd_thread.start()

# Dát mu čas na inicializaci (migrace dat běží jen v ArionDND a ArionBOT)
time.sleep(2)

# ArionDM (admin příkazy) — volitelný, spustí se jen s DISCORD_TOKEN_DM
dm_thread = threading.Thread(target=run_optional, args=("main_dm.py", "DISCORD_TOKEN_DM"), daemon=True)
dm_thread.start()

# ArionCARDS — hráčské karty; admin příkazy zůstávají v ArionDM.
cards_thread = threading.Thread(target=run_optional, args=("main_cards.py", "DISCORD_TOKEN_CARDS"), daemon=True)
cards_thread.start()

# Spustit ArionBOT v main threadu (blokující)
try:
    run("main_bot.py")
except KeyboardInterrupt:
    print("[start.py] Terminating...")
    sys.exit(0)
