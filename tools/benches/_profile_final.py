"""Clean phase attribution on an idle machine, after the binned-key + pruning fix.

Reports the numbers the budget verdict needs: total plan time, where it goes, and
the envelope cache hit rate inside a single plan.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import time
from collections import Counter
from pathlib import Path


from traffic import service, weather  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


service.network()
# Warm the module-level plan cache so the timed run is the warm figure, matching
# how the budget is quoted elsewhere (cold first-call import is reported apart).
weather.NetworkWeather._swept_window.cache_clear()

PHASES = Counter()
CALLS = Counter()


def timed(name, fn):
    def inner(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            PHASES[name] += time.perf_counter() - t0
            CALLS[name] += 1
    return inner


for name in ('trajectory', 'conflict', '_crossings', '_keys', '_lateral'):
    setattr(service, name, timed(name, getattr(service, name)))

real_env = weather.NetworkWeather.envelope
real_band = weather.NetworkWeather._swept_band
weather.NetworkWeather.envelope = timed('envelope', real_env)
weather.NetworkWeather._swept_band = timed('swept_band', real_band)

service.network()
PHASES.clear()
CALLS.clear()
t0 = time.perf_counter()
plan = service.simulate(seed=42, scenario='moving')
total = time.perf_counter() - t0

info = weather.NetworkWeather._swept_window.cache_info()
accepted = sum(1 for f in plan['flights'] if f['status'] == 'SCHEDULED')
closed = sum(1 for f in plan['flights'] if f['status'] == 'CLOSED')
print(f'TOTAL {total:.2f} s  flights {len(plan["flights"])} accepted {accepted} closed {closed}', flush=True)
print('--- phases ---', flush=True)
for name, seconds in PHASES.most_common():
    print(f'  {name:12s} {seconds:7.2f} s  x{CALLS[name]:>7}  '
          f'{seconds / CALLS[name] * 1e6:9.1f} us/call', flush=True)
unaccounted = total - PHASES['envelope'] - PHASES['conflict'] - PHASES['trajectory'] \
    - PHASES['_crossings'] - PHASES['_keys'] - PHASES['_lateral']
print(f'  (non-overlapping top-level sum leaves {unaccounted:.2f} s outside)  -- envelope '
      f'contains swept_band', flush=True)
print(f'  swept_band  {PHASES["swept_band"]:7.2f} s  x{CALLS["swept_band"]}', flush=True)
print('--- window cache inside one plan ---', flush=True)
print(f'  hits {info.hits}  misses {info.misses}  hit rate '
      f'{info.hits / (info.hits + info.misses) * 100:.1f}%', flush=True)
