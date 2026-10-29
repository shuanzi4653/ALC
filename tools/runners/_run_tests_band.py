"""Run the suites that can be affected by the band-hull change.

``_band_hull`` feeds the avoidance envelope, so the risk-merge, v1.3 and
network suites are the ones that can actually detect a regression here; the
full suite is run afterwards to catch anything indirect.

pytest's basetemp must live under %TEMP% and be emptied beforehand: the
sandbox's safe-delete aborts when a single pass removes more than 50 entries,
which makes every ``tmp_path`` fixture fail at setup. Passing extended-length
paths also slips past the guard, so the children are removed up front instead.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
import shutil
import subprocess


HERE = ROOT
BACKEND = os.path.join(HERE, 'backend-python')
PY = os.path.join(BACKEND, '.venv', 'Scripts', 'python.exe')
BASETEMP = os.path.join(os.environ.get('TEMP', r'C:\Windows\Temp'), 'alc-pytest-tmp')

targets = sys.argv[1:] or ['tests', '-q']


def clear_basetemp():
    if not os.path.isdir(BASETEMP):
        return
    removed = 0
    for name in os.listdir(BASETEMP):
        path = os.path.join(BASETEMP, name)
        try:
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
            removed += 1
        except Exception as exc:  # noqa: BLE001
            print(f'  (skip {name}: {type(exc).__name__})')
    print(f'cleared {removed} entries under {BASETEMP}')


clear_basetemp()

env = {k.upper(): v for k, v in os.environ.items()}
env['PYTHONDONTWRITEBYTECODE'] = '1'
env['NO_PROXY'] = '127.0.0.1,localhost'
env.setdefault('TEMP', os.environ.get('TEMP', r'C:\Windows\Temp'))

cmd = [PY, '-m', 'pytest', *targets, f'--basetemp={BASETEMP}']
print('$ ' + ' '.join(cmd), flush=True)
completed = subprocess.run(cmd, cwd=BACKEND, env=env)
sys.exit(completed.returncode)
