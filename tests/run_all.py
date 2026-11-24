"""Run every offline test suite against the mod in this repository.

    python tests/run_all.py

Each suite loads the mod with a simulated game (stub SDK modules), so no game is needed. Windows
only: the mod's audio engine opens winmm devices.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SUITES = ["test_mod.py", "test_menu9.py"] + [f"test_round{i}.py" for i in range(3, 26)]

failed = []
for name in SUITES:
    proc = subprocess.run([sys.executable, os.path.join(HERE, name), ROOT], capture_output=True, text=True, timeout=600)
    last = (proc.stdout.strip().splitlines() or [""])[-1]
    ok = proc.returncode == 0 and "OK" in last
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {last if ok else (proc.stderr.strip().splitlines() or [''])[-1]}")
    if not ok:
        failed.append(name)
# Suites learn status-menu tab names into the mod folder; don't leave that behind.
leftover = os.path.join(ROOT, "bl2_access", "tab_names.json")
if os.path.exists(leftover):
    os.remove(leftover)
import shutil
shutil.rmtree(os.path.join(ROOT, "bl2_access", "maps"), ignore_errors=True)   # learned paths from the suites
print(f"\n{len(SUITES) - len(failed)} of {len(SUITES)} suites passed")
sys.exit(1 if failed else 0)
