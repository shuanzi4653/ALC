"""Verify that a wider swept window strictly contains a narrower one.

The optimisation under consideration is to stop recomputing `swept()` for every
flight's own (departure-derived) window and instead compute one window wide
enough to cover every flight on a route. That is only sound if the envelope is
monotone in the window: if `swept(a, b)` for a wider [a,b] always covers
`swept(c, d)` for a narrower [c,d] inside it.

This checks the property on the real cells rather than assuming it. If it fails,
the wide-window substitution would under-cover and the planner could clear a
flight through weather it should have avoided.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from itertools import combinations
from pathlib import Path


from traffic.weather import NetworkWeather  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


weather = NetworkWeather(42, 'moving')


def clear_cache():
    """Empty the swept-window cache.

    `swept` is a thin wrapper; the lru_cache lives on `_swept_window`. Calling
    `weather.swept.cache_clear()` raised
    `AttributeError: 'function' object has no attribute 'cache_clear'` because a
    bound method is not decorated.
    """
    weather._swept_window.cache_clear()


# Bins span the whole timeline at the model's 5-minute sampling step.
windows = [(0, 2), (10, 24), (56, 70)]          # narrow, from the real histogram
wide = (0, 96)                                   # covers the full 480-minute timeline
# Clear the cache so each is genuinely computed, not served by another window.
clear_cache()

results = []
for narrow in windows:
    clear_cache()
    inner = weather.swept(*narrow)
    outer = weather.swept(*wide)
    leftover = inner.difference(outer).area
    # `covers` is exact and reports False when an edge merely coincides; the area
    # of what actually falls outside is the quantity that matters for safety.
    covered = leftover < 1.0
    results.append((narrow, covered, leftover))
    print(f'window {narrow}  covered_by {wide}: {outer.covers(inner)} '
          f'(area-based: {covered})  leftover_area={leftover:.6f} m2  '
          f'inner_area={inner.area:.1f} m2', flush=True)

# Also check containment between two real windows of different width.
clear_cache()
a = weather.swept(10, 24)
clear_cache()
b = weather.swept(10, 40)
print(f'\n(10,40) covers (10,24): {b.covers(a)}  leftover={a.difference(b).area:.6f} m2', flush=True)

ok = all(row[1] for row in results) and a.difference(b).area < 1.0
print('\nMONOTONE (within 1 m2 tolerance)' if ok else '\nNOT MONOTONE', flush=True)
