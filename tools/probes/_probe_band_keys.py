"""The `distinct (ci,s,e) = 96` line is misleading. Count properly.

`set(band_calls)` where band_calls holds (type_name, ci, s, e) gave 1035 -- so the
1035 windows are genuinely distinct triples. The `96` came from the *bh* list,
which stores `id(self)` as element 0, so `set` over a 4-tuple with a constant id
collapses to the distinct (ci, s, e) -- meaning the hull really is asked for only
96 distinct argument sets, 1035 times. That would be ~11 hits per key, not 0.

So the 0 hits must come from the cache key including something that varies. The
only remaining candidate is that `self` is NOT a single object across the plan:
`simulate` builds one NetworkWeather, but `_swept_band` is also reached for the
risk-frame path. This lists the actual distinct cache keys by re-deriving them.
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

real_bh = weather.NetworkWeather._band_hull
seen = []


def spy_bh(self, cell_index, start_bin, end_bin):
    seen.append((id(self), cell_index, start_bin, end_bin))
    return real_bh(self, cell_index, start_bin, end_bin)


weather.NetworkWeather._band_hull = spy_bh
weather.NetworkWeather._swept_window.cache_clear()
# `_band_hull` is no longer lru_cache-wrapped -- the hull cache was folded into
# `_swept_window`, so there is nothing to clear and `real_bh.cache_clear()`
# raised AttributeError. The spy above still counts every call.

plan = service.simulate(seed=42, scenario='moving')

print(f'_band_hull calls {len(seen)}', flush=True)
keys = Counter(seen)
print(f'distinct full keys {len(keys)}', flush=True)
print(f'  -> repeats would be {len(seen) - len(keys)}', flush=True)
print('--- distinct self ids ---', flush=True)
print(Counter(k[0] for k in seen), flush=True)
print('--- distinct (ci,s,e) ---', flush=True)
print(len(set((k[1], k[2], k[3]) for k in seen)), flush=True)
print('--- top repeated full keys ---', flush=True)
for key, count in keys.most_common(6):
    print(f'  {key} x{count}', flush=True)
print('--- top repeated (ci,s,e) ---', flush=True)
trip = Counter((k[1], k[2], k[3]) for k in seen)
for key, count in trip.most_common(6):
    print(f'  {key} x{count}', flush=True)
print('--- span distribution of (s,e) ---', flush=True)
span = Counter(k[3] - k[2] for k in seen)
print(sorted(span.items())[:25], flush=True)
print('--- distinct starts ---', flush=True)
starts = Counter(k[2] for k in seen)
print(f'  {len(starts)} starts', flush=True)
print('--- distinct ends ---', flush=True)
ends = Counter(k[3] for k in seen)
print(f'  {len(ends)} ends', flush=True)
print('--- IMPORTANT: is (s,e) unique, i.e. does e determine s? ---', flush=True)
pairs = set((k[2], k[3]) for k in seen)
print(f'  distinct (s,e): {len(pairs)} vs calls {len(seen)}', flush=True)
