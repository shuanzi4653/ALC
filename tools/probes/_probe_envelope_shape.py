"""Is the 13,419-call envelope cost actually a prefix problem?

`_profile_own` shows `weather.envelope` entered 13,419 times but
`_swept_window` only 1,035, i.e. the same ~13 windows are asked for about 13
times each -- and the key probe shows the windows repeat that much exactly.

If the call sites are windows of the form (s, e) where e is tied to s, then the
distinct *starts* are far fewer than the distinct windows, and the union
`U(s, e) = union over ticks of cell(tick)` can be answered from prefix unions:

    envelope(s, e) = P(e) - P(s-1)      (and for cells, cell(tick) is a translate)

Both call sites in service.py build the window from the flight's own departure
and arrival, so the question is how many distinct starts there are and whether
the same start is re-asked with different ends.

This counts the real distribution to decide between "add caching" and "the cost
is irreducible per call".
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from collections import Counter
from pathlib import Path


from traffic import service, weather  # noqa: E402

service.network()

real_env = weather.NetworkWeather.envelope
calls = []


def spy(self, start, end):
    s = int(start // 5)
    e = int(-(-end // 5))
    calls.append((s, e))
    return real_env(self, start, end)


weather.NetworkWeather.envelope = spy
plan = service.simulate(seed=42, scenario='moving')
weather.NetworkWeather.envelope = real_env

print(f'calls {len(calls)}', flush=True)
starts = Counter(s for s, e in calls)
print(f'distinct starts  {len(starts)}', flush=True)
windows = Counter(calls)
print(f'distinct windows {len(windows)}', flush=True)
print(f'repeats {len(calls) - len(windows)}', flush=True)

print('--- span distribution (end - start) ---', flush=True)
span = Counter(e - s for s, e in calls)
for value, count in sorted(span.items()):
    print(f'  span {value:>4}: {count}', flush=True)

print('--- top windows ---', flush=True)
for (s, e), count in windows.most_common(10):
    print(f'  ({s:>4},{e:>4}) x{count}', flush=True)

print('--- top starts ---', flush=True)
for s, count in starts.most_common(10):
    print(f'  start {s:>4} x{count}', flush=True)

# How much of the cost is the BAND cell alone?
wx = weather.NetworkWeather(42, 'moving')
band_index = next(i for i, c in enumerate(wx.cells) if c['shape'] == 'BAND')
rings = [c for c in wx.cells if c['shape'] == 'RING']
print(f'--- cell mix: {len(wx.cells)} cells, {len(rings)} RING + 1 BAND ---', flush=True)

import time  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


top = windows.most_common(1)[0][0]
t0 = time.perf_counter()
for _ in range(10):
    # `_swept_band` takes the cell's *index*, not the dict. Passing the dict
    # reached `int(cell_index)` and raised
    # `TypeError: int() argument must be ... not 'dict'`.
    wx._swept_band(band_index, top[0], top[1])
t_band = (time.perf_counter() - t0) / 10
t0 = time.perf_counter()
for _ in range(10):
    wx._swept_window.__wrapped__(wx, top[0], top[1])
t_all = (time.perf_counter() - t0) / 10
print(f'  window {top}: band only {t_band * 1000:.2f} ms, whole window {t_all * 1000:.2f} ms', flush=True)
print(f'  band share {t_band / t_all * 100:.1f}%', flush=True)
print(f'  implied plan cost at {len(calls)} calls if all were {top}: '
      f'{t_all * len(calls):.1f} s', flush=True)
