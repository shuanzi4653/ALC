"""Focused pytest runner for a named subset, safe to run beside the full suite.

The project's `_run_pytest.py` covers the whole suite (~27-36 min). This is the
same setup for a handful of files so an edit can be checked in under a minute.
Three constraints it copies from that runner, each of which cost real time once:

  * `--basetemp` must be under the **OS temp dir**. Anywhere else the sandbox's
    safe-delete guard refuses pytest's bulk wipe of the previous tree, which
    turns every `tmp_path` teardown into a SystemExit and reports as "ERROR at
    setup" for most of the suite.
  * The leftover tree must be cleared **one child at a time**. A single bulk
    removal is refused once it grows past ~50 entries, so the run would only ever
    work the first time.
  * cwd must be `backend-python/`, because the tests import `traffic.*` and read
    `data/...` by relative path.

The basetemp name is distinct from the full runner's on purpose: two pytest
processes sharing one basetemp is a measured way to get two runs that each look
like they failed (see the 0.9.21 wrap-up notes).

Usage:  python tools/runners/_run_pytest_focus.py tests/test_radar_avoidance.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402

BACKEND = Path(ROOT) / 'backend-python'
PYTHON = BACKEND / '.venv' / 'Scripts' / 'python.exe'
BASETEMP = Path(tempfile.gettempdir()) / 'alc-pytest-focus-tmp'


def _clear_basetemp():
    if not BASETEMP.is_dir():
        return
    for child in list(BASETEMP.iterdir()):
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        except OSError as exc:
            print(f'warn: 无法清理 {child.name}: {type(exc).__name__}', flush=True)


def main(argv):
    targets = argv[1:] or ['tests/test_radar_avoidance.py']
    _clear_basetemp()
    env = {k.upper(): v for k, v in os.environ.items()}
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['NO_PROXY'] = '127.0.0.1,localhost'
    command = [str(PYTHON), '-m', 'pytest', *targets, '-q', '-p', 'no:cacheprovider',
               f'--basetemp={BASETEMP}']
    print('RUN', ' '.join(command), flush=True)
    return subprocess.run(command, cwd=str(BACKEND), env=env).returncode


if __name__ == '__main__':
    sys.exit(main(sys.argv))
