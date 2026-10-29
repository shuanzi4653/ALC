"""Time the plan build end to end and report the cache state.

The behavioural gate failed with "still BUILDING after 292s" against a 420 s
whole-run cap. That is a *different* failure from the earlier crash and needs a
different answer: either the build regressed in cost, or the gate's budget is
sized for a plan that no longer exists. This probe tells the two apart by
measuring the real numbers rather than reasoning about them.

Run:  backend-python/.venv/Scripts/python.exe tools/probes/_probe_plan_cost.py
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

SEEDS = ((42, 'moving'), (99999, 'moving'), (0, 'nominal'))


def cache_state():
    """Is there a journal / cache file the plan build reuses?"""
    run_dir = ROOT / '.run' / 'traffic'
    if not run_dir.exists():
        return 'no .run/traffic directory'
    entries = []
    for name in sorted(os.listdir(str(run_dir))):
        path = run_dir / name
        try:
            size = path.stat().st_size
        except OSError:
            size = -1
        entries.append('%s (%d bytes)' % (name, size))
    return entries or 'empty'


def main():
    from traffic import service

    print('cache state before: %s' % (cache_state(),))
    print()

    for seed, scenario in SEEDS:
        # First call: whatever the cache holds.
        began = time.monotonic()
        state = service.session(seed, scenario)
        first = time.monotonic() - began
        print('seed=%-6d scenario=%-8s first call: %6.2fs  status=%s  progress=%s'
              % (seed, scenario, first, state.get('status'), state.get('progress')))

        # Poll to completion, bounded, so a pathological build reports rather than hangs.
        began = time.monotonic()
        deadline = began + 900.0
        steps = 0
        while True:
            state = service.session(seed, scenario)
            status = state.get('status')
            steps += 1
            if status in ('READY', 'ERROR'):
                break
            if time.monotonic() > deadline:
                print('  ! still %s after 900s (%d polls)' % (status, steps))
                break
            time.sleep(1.0)
        total = time.monotonic() - began
        flights = len(state.get('flights') or [])
        print('  -> %s after %6.2fs total (%d polls), flights=%d'
              % (state.get('status'), first + total, steps, flights))
        if state.get('status') == 'ERROR':
            print('     message: %s' % (state.get('message'),))
        print()

    print('cache state after: %s' % (cache_state(),))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
