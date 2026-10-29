"""Attribute plan time to named phases, so the budget verdict names a real cause.

The earlier attribution only proved the fixed-zone feature is not to blame. This
splits `service.simulate` into its actual stages and counts how often the
separation search is entered, so the report can say where the seconds are
instead of only where they are not.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import time
from collections import Counter
from pathlib import Path


from traffic import service  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


PHASES = Counter()
CALLS = Counter()

# --- wrap the phases individually: cumulative cProfile cannot separate two
# --- functions that call each other in a loop. service.py does
# --- `from .spatial import conflict, ..., trajectory`, so these are module-level
# --- globals *of service*: patching spatial.conflict would not be seen here.
real_trajectory = service.trajectory
real_conflict = service.conflict
real_crossings = service._crossings
real_keys = service._keys
real_lateral = service._lateral


def timed(name, fn):
    def inner(*args, **kwargs):
        start = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            PHASES[name] += time.perf_counter() - start
            CALLS[name] += 1
    return inner


service.trajectory = timed('trajectory', real_trajectory)
service.conflict = timed('conflict', real_conflict)
service._crossings = timed('crossings', real_crossings)
service._keys = timed('keys', real_keys)
service._lateral = timed('lateral', real_lateral)

service.network()
print('warm-up done', flush=True)

PHASES.clear()
CALLS.clear()
start = time.perf_counter()
plan = service.simulate(seed=42, scenario='moving')
total = time.perf_counter() - start

accepted = [f for f in plan['flights'] if f['status'] == 'SCHEDULED']
reasons = Counter(f['reason'] for f in plan['flights'] if f['status'] == 'CLOSED')

print(f'TOTAL {total:.2f} s  flights={len(plan["flights"])} accepted={len(accepted)}', flush=True)
print('--- phases (cumulative, nested so they overlap) ---', flush=True)
for name, seconds in PHASES.most_common():
    print(f'  {name:12s} {seconds:7.2f} s  x{CALLS[name]:>7}  '
          f'{seconds / CALLS[name] * 1e6:8.1f} us/call', flush=True)
print('--- closure reasons ---', flush=True)
for reason, count in reasons.most_common():
    print(f'  {reason:42s} {count}', flush=True)

# Isolated cost of one conflict() call at the observed sample density.
samples = [len(f['points']) for f in accepted]
print('--- trajectory sample density ---', flush=True)
print(f'  accepted flights {len(accepted)}, points min={min(samples)} '
      f'max={max(samples)} mean={sum(samples) / len(samples):.1f}', flush=True)
