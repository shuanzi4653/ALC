"""Measure the binned-window cache inside a real plan, not in isolation.

The isolated check cleared the cache between runs, so `hits 0 misses 1035` said
nothing about a single plan. This reports cache_info() after ONE simulate() and
breaks the remaining time down, so the next change is aimed at a measured target
rather than the last hypothesis.
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
wx_probe = weather.NetworkWeather(42, 'moving')

# Count what a single plan asks the window cache for.
weather.NetworkWeather._swept_window.cache_clear()
plan = service.simulate(seed=42, scenario='moving')
info = weather.NetworkWeather._swept_window.cache_info()
# `_band_hull` carries no lru_cache any more (its cache folded into
# `_swept_window`), so there is no cache_info to read here.
print('--- one plan, window cache ---', flush=True)
print(f'  _swept_window  hits {info.hits}  misses {info.misses}  '
      f'currsize {info.currsize}  maxsize {info.maxsize}', flush=True)

# Where does the remaining time go now?
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


real = {
    'trajectory': service.trajectory,
    'conflict': service.conflict,
    'crossings': service._crossings,
    'keys': service._keys,
    'lateral': service._lateral,
}
for name, fn in real.items():
    setattr(service, name, timed(name, fn))

real_env = weather.NetworkWeather.envelope
real_sw = weather.NetworkWeather._swept_window
real_bh = weather.NetworkWeather._band_hull

service.envelope_t = timed('envelope', real_env)
weather.NetworkWeather.envelope = service.envelope_t
weather.NetworkWeather._swept_window = timed('swept_window', real_sw)
weather.NetworkWeather._band_hull = timed('band_hull', real_bh)

service.network()
PHASES.clear()
CALLS.clear()
t0 = time.perf_counter()
plan = service.simulate(seed=42, scenario='moving')
total = time.perf_counter() - t0
print(f'--- re-run: TOTAL {total:.2f} s ---', flush=True)
for name, seconds in PHASES.most_common():
    print(f'  {name:14s} {seconds:7.2f} s  x{CALLS[name]:>7}  '
          f'{seconds / CALLS[name] * 1e6:9.1f} us/call', flush=True)
print('--- cache after this run ---', flush=True)
# Read the cache through the *saved original*. Line 66 swapped the class
# attribute for a timing wrapper, so `_swept_window.cache_info()` on the class
# raised `AttributeError: 'function' object has no attribute 'cache_info'`.
i2 = real_sw.cache_info()
print(f'  _swept_window hits {i2.hits} misses {i2.misses} currsize {i2.currsize}', flush=True)
