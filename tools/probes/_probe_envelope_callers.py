"""Where do 13,419 envelope calls come from, and why is each window asked once?

`hits 0 misses 1035` in the cache verification killed the caching hypothesis: the
cache is cold for every window, so the 13,419 calls are not repeats of 1035
windows -- they are mostly *distinct* start/end pairs that happen to collapse to
1035 (start,end) keys only because many flights share a scheduled minute.

Two call sites exist in service.py:
  line 365  obstacle = weather.envelope(scheduled, scheduled + base_duration + max_extra)
  line 433  final_line.intersects(weather.envelope(points[0][3], points[-1][3]))

Line 365 is per flight candidate, so its window depends only on `scheduled`
(one of 96 departure waves) and `base_duration` (which varies per mode). That
means far fewer distinct windows than candidates -- yet the cache sees one call
each. This probe logs the raw (start, end) floats and the caller to resolve it.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from collections import Counter
from pathlib import Path


import inspect  # noqa: E402

from traffic import service, weather  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


service.network()

real_env = weather.NetworkWeather.envelope
records = []


def spy(self, start, end):
    frame = inspect.currentframe().f_back
    records.append((start, end, frame.f_lineno))
    return real_env(self, start, end)


weather.NetworkWeather.envelope = spy
plan = service.simulate(seed=42, scenario='moving')
weather.NetworkWeather.envelope = real_env

print(f'calls {len(records)}', flush=True)
by_line = Counter(line for _, _, line in records)
print('--- calls by caller line in service.py ---', flush=True)
for line, count in by_line.most_common():
    print(f'  line {line}: {count}', flush=True)

print('--- raw float windows: how many distinct, before int rounding ---', flush=True)
raw = Counter((s, e) for s, e, _ in records)
print(f'  distinct raw (start,end): {len(raw)}', flush=True)
rounded = Counter((int(s // 5), int(-(-e // 5))) for s, e, _ in records)
print(f'  distinct rounded (s_bin,e_bin): {len(rounded)}', flush=True)

print('--- per-caller rounding ---', flush=True)
for line in by_line:
    subset = [(s, e) for s, e, ln in records if ln == line]
    r = len(set((int(s // 5), int(-(-e // 5))) for s, e in subset))
    print(f'  line {line}: {len(subset)} calls -> {r} distinct rounded windows', flush=True)

print('--- top raw windows ---', flush=True)
for (s, e), count in raw.most_common(8):
    print(f'  ({s}, {e}) x{count}  -> bins ({int(s // 5)}, {int(-(-e // 5))})', flush=True)

# Does line 365's window depend only on scheduled + base_duration?
print('--- line 365 structure ---', flush=True)
subset = [(s, e) for s, e, ln in records if ln == 365]
if subset:
    starts = Counter(s for s, e in subset)
    dur = Counter(round(e - s, 3) for s, e in subset)
    print(f'  distinct starts {len(starts)}, distinct durations {len(dur)}', flush=True)
    print(f'  distinct durations: {sorted(dur)[:15]}', flush=True)
    print(f'  distinct starts: {sorted(starts)[:15]}', flush=True)
    product = len(starts) * len(dur)
    print(f'  start x duration product {product} vs actual {len(set(subset))}', flush=True)
