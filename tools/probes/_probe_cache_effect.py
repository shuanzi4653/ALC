"""Is the 1035-call cost repeated keys (cache too small) or all-distinct keys?

A larger LRU only helps if the same window is asked for more than once within a
plan. `_profile_own.py` showed `_swept_window` entered 1035 times and (per the
earlier key probe) 1035 distinct windows existed, which would mean zero hits.

That needs one more check before concluding, because cache_info() also counts
calls that were *misses on lookup* -- the hash is over the raw arguments, and
`envelope()` passes `math.floor(start/5)` (an int) while some callers may pass a
float, so two "same" windows could miss each other. This measures the real hit
rate and, if it is zero, confirms the calls are genuinely distinct windows.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from collections import Counter
from pathlib import Path


from traffic import service  # noqa: E402
from traffic import weather  # noqa: E402

service.network()

# Reset the cache and record every argument pair actually requested.
weather.NetworkWeather._swept_window.cache_clear()

seen = Counter()
real = weather.NetworkWeather._swept_window.__wrapped__


def spy(self, start_bin, end_bin):
    seen[(type(start_bin).__name__, start_bin, type(end_bin).__name__, end_bin)] += 1
    return real(self, start_bin, end_bin)


weather.NetworkWeather._swept_window = spy

import time  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

start = time.perf_counter()
plan = service.simulate(seed=42, scenario='moving')
total = time.perf_counter() - start

print(f'TOTAL {total:.2f} s', flush=True)
print(f'  swept calls          {sum(seen.values())}', flush=True)
print(f'  distinct arg tuples  {len(seen)}', flush=True)

# Collapse the type tag: are the same numeric windows re-requested?
numeric = Counter()
for (t1, a, t2, b), count in seen.items():
    numeric[(a, b)] += count
print(f'  distinct numeric     {len(numeric)}', flush=True)
print(f'  repeats (numeric)    {sum(seen.values()) - len(numeric)}', flush=True)

print('--- argument types seen ---', flush=True)
types = Counter((t1, t2) for (t1, a, t2, b) in seen)
for pair, count in types.most_common():
    print(f'  {pair}  {count}', flush=True)

print('--- top repeated windows ---', flush=True)
for (a, b), count in numeric.most_common(8):
    print(f'  ({a:>5},{b:>5})  x{count}', flush=True)

span = Counter(b - a for (a, b) in numeric)
print('--- distinct spans ---', flush=True)
print('  ' + ', '.join(f'{s}:{c}' for s, c in sorted(span.items())[:20]), flush=True)
