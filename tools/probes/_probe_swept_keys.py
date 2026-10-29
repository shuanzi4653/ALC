"""Count how many distinct swept-window keys the planner actually asks for.

The window cache is lru_cached, yet the profile shows thousands of calls that
each cost real time. That combination means either the cache is thrashing or the
keys are nearly all distinct. This counts the keys and the bin spans before
deciding which fix applies.

Note on the entry point: the planner no longer calls `swept()`. It calls
`envelope(start, end)` with raw minutes, and `envelope` bins to 5-minute ticks
and delegates to the cached `_swept_window`. Spying on `swept` therefore saw
zero calls and `min(spans)` raised ValueError on the empty sequence. The spy
below wraps `envelope`, which is the call the planner really makes.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from collections import Counter
from pathlib import Path

import math

from traffic import service  # noqa: E402
from traffic.weather import NetworkWeather  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


service.network()

keys = Counter()
spans = Counter()

real = NetworkWeather.envelope


def spy(self, start, end):
    # Mirror `envelope`'s own binning so the keys describe cache behaviour.
    start_bin = math.floor(start / 5)
    end_bin = math.ceil(end / 5)
    keys[(start_bin, end_bin)] += 1
    spans[end_bin - start_bin] += 1
    return real(self, start, end)


NetworkWeather.envelope = spy
service.simulate(seed=42, scenario='moving')
NetworkWeather.envelope = real

print('distinct swept windows requested:', len(keys), flush=True)
print('total calls                     :', sum(keys.values()), flush=True)
print('window cache cap                : 2048', flush=True)
if not spans:
    print('(no calls observed -- the planner changed entry point again)', flush=True)
    sys.exit(0)
print('--- bin-span histogram (top 12) ---', flush=True)
for span, count in spans.most_common(12):
    print(f'  span {span:>4} bins  x{count}', flush=True)
print(f'--- span min/max: {min(spans)} / {max(spans)} ---', flush=True)
print('--- most requested windows ---', flush=True)
for key, count in keys.most_common(5):
    print(f'  {key}  x{count}', flush=True)
