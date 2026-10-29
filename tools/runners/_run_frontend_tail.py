"""Run the frontend suite + vite build and keep only the tail of the output.

The full node --test TAP stream is ~54 subtests of noise; the summary block and
any build error are the only parts worth reading, and the sandbox shell has no
`tail`. So the child's output is captured and the last N lines are printed.
Usage: python _run_frontend_tail.py [lines]
"""
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from _node import NODE  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ROOT = Path(ROOT)
FRONTEND = ROOT / 'frontend'
VITE = FRONTEND / 'node_modules' / 'vite' / 'bin' / 'vite.js'

lines = int(sys.argv[1]) if len(sys.argv) > 1 else 30
env = {k.upper(): v for k, v in os.environ.items()}
env['NO_PROXY'] = '127.0.0.1,localhost'
env['CI'] = '1'

codes = {}
for name, command in (('test', [str(NODE), '--test']), ('build', [str(NODE), str(VITE), 'build'])):
    result = subprocess.run(command, cwd=str(FRONTEND), env=env, capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    codes[name] = result.returncode
    output = (result.stdout or '') + (result.stderr or '')
    tail = output.strip().splitlines()[-lines:]
    print(f'== {name} (RC {result.returncode}) ==')
    print('\n'.join(tail))

sys.exit(1 if any(codes.values()) else 0)
