"""Report the final state of the band-hull fix and the files it touched."""

import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import subprocess

PY = os.path.join(ROOT, 'backend-python', '.venv', 'Scripts', 'python.exe')


# 1. Confirm the fix is present and the dead code is gone.
SRC = r'backend-python\traffic\weather.py'
src = open(SRC, encoding='utf-8').read()
lines = src.splitlines()

# The 92.3% figure may survive only where it is explicitly retracted. Any
# occurrence must sit within a few lines of the word that flags it as wrong,
# otherwise it is still being stated as fact.
retractions = ('does not survive', 'must not be quoted', 'once claimed')
stale_ok = True
for number, line in enumerate(lines, 1):
    if '92.3' not in line:
        continue
    window = ' '.join(lines[max(0, number - 6):number + 6])
    if not any(flag in window for flag in retractions):
        stale_ok = False
        print(f'  line {number} states 92.3% without retraction: {line.strip()}')

checks = {
    '_outline_hull_coords defined': 'def _outline_hull_coords(' in src,
    '_band_hull uses it': "coords=_outline_hull_coords(cell['polygon'])" in src,
    'old 820-vertex loop gone': "for part in _polygon_parts(cell['polygon'])\n                for x,y in part.exterior.coords" not in src,
    '92.3% only appears retracted': stale_ok,
    'measured 59.8% recorded': '59.8%' in src,
}
for name, ok in checks.items():
    print(('OK  ' if ok else 'FAIL'), name)

# 2. Show the diff stat for the changed file.
env = {k.upper(): v for k, v in os.environ.items()}
diff = subprocess.run(['git', 'diff', '--stat', 'backend-python/traffic/weather.py'],
                      capture_output=True, env=env)
print()
print(diff.stdout.decode('utf-8', 'replace').strip() or '(no tracked diff)')

# 3. Confirm the new probes exist. Paths are relative to the repository root,
#    because the tools were reorganised into tools/<class>/ directories; the
#    scripts themselves kept their names so document citations still resolve.
print()
for name in ('tools/harness/_wait_ready.py', 'tools/probes/_probe_e2e_chain.py',
             'tools/runners/_run_tests_band.py', 'tools/maintenance/_append_log.py'):
    print(('present ' if os.path.isfile(name) else 'MISSING '), name)
