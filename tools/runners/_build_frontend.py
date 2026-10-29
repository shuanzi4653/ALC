"""Build the frontend and run its unit tests.

Vite needs an absolute cwd, and the sandbox shell cannot ``cd``, so this drives
it through subprocess. ``node --test`` alone does not compile ``.vue`` files, so
a MapLibre paint expression with a missing bracket would pass the tests and fail
only here -- the build is the real check for template changes.

Two things this file gets wrong easily, both measured the hard way:

1. **cwd must be ``frontend/``, not the repo root.** ``frontend/node_modules``
   holds vite and vue; the repo root has no ``node_modules`` at all. Resolving
   vite as ``ROOT/node_modules/vite/bin/vite.js`` fails with
   ``Cannot find module ...\\node_modules\\vite\\bin\\vite.js`` -- which reads
   like a missing dependency but is really a wrong-directory bug.

2. **Test discovery must never reach into ``backups/``.** Those directories hold
   archived copies of the frontend (``backups/*/frontend/tests/*.test.mjs``)
   with no ``node_modules`` beside them, so importing ``vue`` raises
   ``ERR_MODULE_NOT_FOUND``. Three archived copies contributed 8 failures to a
   16-file run and made an otherwise green suite look broken. ``node --test``
   run with cwd ``frontend/`` discovers only that directory, but the exclusion
   is asserted below as well so that a future change of cwd cannot silently
   reactivate the problem.

The discovered test count is compared against an expectation so that a
whole-directory drop-out (the failure mode that made the archives look like
failures in the first place) is loud rather than silent. Bump
``EXPECTED_MIN_TESTS`` when tests are genuinely added.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from _node import NODE  # noqa: E402
import glob
import subprocess


FRONTEND = os.path.join(ROOT, 'frontend')

# Archived copies of the frontend live under these; they must never be walked.
ARCHIVE_DIRS = ('backups', 'archive')

# Declared floor for the frontend suite (121 at time of writing). A drop means
# files stopped being discovered -- not that the code got better.
EXPECTED_MIN_TESTS = 121

env = {k.upper(): v for k, v in os.environ.items()}
env['NO_PROXY'] = '127.0.0.1,localhost'
env['CI'] = '1'


def _discovered_test_files():
    """Test files node --test will actually find, for the console record."""
    found = []
    for path in glob.glob(os.path.join(FRONTEND, 'tests', '*.test.mjs')):
        rel = os.path.relpath(path, ROOT).replace(os.sep, '/')
        if any(rel == d or rel.startswith(d + '/') for d in ARCHIVE_DIRS):
            continue
        found.append(path)
    return sorted(found)


test_files = _discovered_test_files()
print('=== discovered %d test file(s) under frontend/tests ===' % len(test_files), flush=True)
for path in test_files:
    print('    ' + os.path.relpath(path, ROOT), flush=True)
print('    (excluded by rule: %s)' % ', '.join(ARCHIVE_DIRS), flush=True)
print(flush=True)

print('=== node runtime: %s ===' % NODE, flush=True)
print(flush=True)

# One invocation per step. ``node --test`` with explicit file arguments keeps
# discovery pinned to frontend/tests regardless of any future cwd change; the
# ``--test-reporter=tap`` output is what gives the "# tests N" counter below.
steps = [
    ('unit tests (node --test)',
     [NODE, '--test', *test_files], FRONTEND),
    ('vite build',
     [NODE, os.path.join(FRONTEND, 'node_modules', 'vite', 'bin', 'vite.js'), 'build'], FRONTEND),
]

failed = []
for label, command, cwd in steps:
    print(f'=== {label} ({len(command)} args, cwd={os.path.basename(cwd)}) ===', flush=True)
    completed = subprocess.run(command, cwd=cwd, env=env,
                              capture_output=True, encoding='utf-8', errors='replace')
    out = (completed.stdout or '') + (completed.stderr or '')
    if label.startswith('unit tests'):
        # Keep the counters and the failure headings; drop the per-test spam.
        for line in out.splitlines():
            if line.startswith('# ') or line.startswith('not ok'):
                print(line, flush=True)
        counts = {}
        for line in out.splitlines():
            if line.startswith('# '):
                parts = line[2:].split(None, 1)
                if len(parts) == 2:
                    counts[parts[0]] = parts[1].strip()
        total = int(counts.get('tests', '0') or 0)
        passed = int(counts.get('pass', '0') or 0)
        if total < EXPECTED_MIN_TESTS:
            print(f'    !! only {total} tests discovered, expected >= {EXPECTED_MIN_TESTS} '
                  '-- files stopped being found', flush=True)
            completed = subprocess.CompletedProcess(command, 1)
        elif counts.get('fail', '0') not in ('0',):
            print(f'    !! {counts.get("fail")} failing', flush=True)
    else:
        print(out[-2000:] if len(out) > 2000 else out, flush=True)
    print(f'--- exit {completed.returncode}', flush=True)
    print(flush=True)
    if completed.returncode != 0:
        failed.append(label)

print('FAILED: ' + ', '.join(failed) if failed else 'all steps passed')
sys.exit(1 if failed else 0)
