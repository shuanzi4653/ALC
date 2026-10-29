"""Why does `_band_hull` report 0 hits when `_swept_window` gets 92%?

`_swept_window` is cached on (self, start_bin, end_bin) and a single plan reuses
one NetworkWeather instance, so `self` is stable and the binned keys repeat.
`_band_hull` is cached on (self, cell_index, start_bin, end_bin) with the SAME
arguments for the same windows -- yet it reports 0 hits.

The difference is that `_swept_window`'s cached call is the *only* caller of the
hull, so the hull is entered once per distinct window anyway. But if that is so,
`_band_hull.misses` should equal `_swept_window.misses` (1035) and its hits too.

This checks the two hypotheses: (a) `cell_index` is being passed as something
unhashable/equal-but-distinct, (b) the hull is reached by a path that bypasses the
cache (e.g. `_swept_band` called directly from elsewhere).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from collections import Counter
from pathlib import Path


from traffic import service, weather  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


service.network()

real_swept_band = weather.NetworkWeather._swept_band
band_calls = []


def spy_band(self, cell_index, start_bin, end_bin):
    band_calls.append((type(cell_index).__name__, cell_index, start_bin, end_bin))
    return real_swept_band(self, cell_index, start_bin, end_bin)


weather.NetworkWeather._swept_band = spy_band

real_bh = weather.NetworkWeather._band_hull
bh_calls = []


def spy_bh(self, cell_index, start_bin, end_bin):
    bh_calls.append((id(self), type(cell_index).__name__, cell_index, start_bin, end_bin))
    return real_bh(self, cell_index, start_bin, end_bin)


weather.NetworkWeather._band_hull = spy_bh

weather.NetworkWeather._swept_window.cache_clear()
# `_band_hull` is no longer lru_cache-wrapped (the hull cache folded into
# `_swept_window`), so `real_bh.cache_clear()` raised AttributeError. The spy
# still counts every call, which is all this probe needs.

plan = service.simulate(seed=42, scenario='moving')

print(f'_swept_band calls {len(band_calls)}', flush=True)
print(f'_band_hull  calls {len(bh_calls)}', flush=True)
print('--- _swept_band arg types ---', flush=True)
print(Counter((t, ) for t, _, _, _ in band_calls), flush=True)
print('--- distinct _swept_band args ---', flush=True)
print(len(set(band_calls)), flush=True)
print('--- distinct _band_hull args ---', flush=True)
print(len(set(bh_calls)), flush=True)
print('--- distinct self objects in _band_hull ---', flush=True)
print(Counter(c[0] for c in bh_calls), flush=True)
print('--- distinct cell_index values ---', flush=True)
print(Counter(c[2] for c in bh_calls), flush=True)
print('--- band_hull cache ---', flush=True)
print('(no cache: _band_hull is uncached now; the call count above is the measure)', flush=True)
print('--- swept_window cache ---', flush=True)
print(weather.NetworkWeather._swept_window.cache_info(), flush=True)

# Is _swept_band ever called outside _swept_window?
print('--- _swept_band callers distinct windows vs swept_window distinct ---', flush=True)
print(f'  _swept_band distinct (ci,s,e): {len(set(band_calls))}', flush=True)
sw = [(c[1], c[2], c[3]) for c in bh_calls]
print(f'  _band_hull distinct (ci,s,e): {len(set(sw))}', flush=True)
