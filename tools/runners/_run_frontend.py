"""Run the frontend node:test suite and the vite production build.

Bash is unusable for this here (no `cd`, no glob expansion, and relative vite
paths break), so both invocations are driven from Python with an explicit cwd.
Usage: python _run_frontend.py [test|build|both]
"""
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT # noqa: E402
from _node import NODE  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ROOT = Path(ROOT)
FRONTEND = ROOT / 'frontend'
# Which node actually ran belongs in the log: a stale pin used to fail with
# `FileNotFoundError: [WinError 2]`, which reads like a broken build.
print('== node runtime:', NODE, '==', flush=True)
VITE = FRONTEND / 'node_modules' / 'vite' / 'bin' / 'vite.js'

mode = sys.argv[1] if len(sys.argv) > 1 else 'both'
env = {k.upper(): v for k, v in os.environ.items()}
env['NO_PROXY'] = '127.0.0.1,localhost'
env['CI'] = '1'

codes = {}

if mode in ('test', 'both'):
    # No file arguments: node --test discovers the suite itself. Passing
    # `tests/*.test.mjs` would fail because bash here does not expand globs.
    print('== node --test ==', flush=True)
    codes['test'] = subprocess.run([str(NODE), '--test'], cwd=str(FRONTEND), env=env).returncode

if mode in ('build', 'both'):
    print('== vite build ==', flush=True)
    codes['build'] = subprocess.run([str(NODE), str(VITE), 'build'], cwd=str(FRONTEND), env=env).returncode

for name, code in codes.items():
    print(f'{name}: RC {code}', flush=True)
sys.exit(1 if any(codes.values()) else 0)
