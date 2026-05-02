import subprocess
import sys
import threading

def run(script):
    proc = subprocess.Popen(
        [sys.executable, "-u", script],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    proc.wait()
    sys.exit(proc.returncode or 1)

t = threading.Thread(target=run, args=("main_dnd.py",), daemon=True)
t.start()
run("main_bot.py")
