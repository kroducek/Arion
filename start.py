import subprocess
import sys
import threading
import time
import signal

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

# Spustit ArionDND v daemon threadu
dnd_thread = threading.Thread(target=run, args=("main_dnd.py",), daemon=True)
dnd_thread.start()

# Dát mu čas na inicializaci
time.sleep(2)

# Spustit ArionBOT v main threadu (blokující)
try:
    run("main_bot.py")
except KeyboardInterrupt:
    print("[start.py] Terminating...")
    sys.exit(0)
