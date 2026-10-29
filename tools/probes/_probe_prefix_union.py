"""Can the envelope be answered from a prefix union U(k) instead of a hull per window?

Per cell the swept set over ticks is `S(s,e) = union(cell(tick) for tick in s..e)`.
If `U(k) = union(cell(tick) for tick in 0..k)` is built once per k in 0..96, then

    S(s, e) = ... is NOT U(e) - U(s-1) for a union. Difference removes area that
    later ticks re-cover. The correct identity is containment: if every cell only
    ever grows or translates, U is not an interval decomposition.

So the prefix trick needs `S(s,e) = U(e) intersect complement(U(s-1))`, which is
only exact when the cell's swept area over disjoint tick ranges is disjoint --
never true here (cells orbit back over their own track).

This probe tests the identity that WOULD be safe: is S(s,e) monotone in e for
fixed s, and does S(s,e) == union of per-cell S_cell(s,e)? Monotonicity in e is
what allows a single growing accumulator per start, which is both exact and
avoids recomputing from scratch.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import time
from pathlib import Path


from traffic import weather  # noqa: E402
from shapely.geometry import MultiPoint  # noqa: E402

wx = weather.NetworkWeather(42, 'moving')
ring = [c for c in wx.cells if c['shape'] == 'RING'][0]
band_index = next(i for i, c in enumerate(wx.cells) if c['shape'] == 'BAND')

# 1. Monotonicity in e for a fixed start, per cell type.
def band_swept(cell, s, e):
    # The first argument is the cell's *index*; passing the dict reaches
    # `int(cell_index)` and raises TypeError.
    return wx._swept_band(cell, s, e)

print('--- monotone in e, fixed start (band) ---', flush=True)
s = 56
prev = None
bad = 0
for e in range(s, s + 30):
    cur = band_swept(band_index, s, e)
    if prev is not None:
        gap = prev.difference(cur).area
        if gap > 1.0:
            bad += 1
            print(f'  e={e}: dropped {gap:,.2f} m^2', flush=True)
    prev = cur
print(f'  non-monotone steps: {bad}', flush=True)

# 2. Does the band track buffer the ring cheaply? Time both.
print('--- ring cost per window ---', flush=True)
for window in [(56, 70), (0, 96)]:
    t0 = time.perf_counter()
    for _ in range(5):
        centres = [wx.centre_at(ring, tick * 5) for tick in range(window[0], window[1] + 1)]
        from shapely.geometry import LineString
        track = LineString(centres) if len(centres) > 1 else __import__('shapely').geometry.Point(centres[0])
        track.buffer(ring['sweptPad'], quad_segs=8)
    t_ring = (time.perf_counter() - t0) / 5
    t0 = time.perf_counter()
    for _ in range(5):
        band_swept(band_index, window[0], window[1])
    t_band = (time.perf_counter() - t0) / 5
    print(f'  {window}: ring {t_ring * 1000:.2f} ms, band {t_band * 1000:.2f} ms', flush=True)

# 3. Cost of the 20 rings vs the band for a window of each recurring span.
print('--- full window cost by span (this is what 13419 calls pay) ---', flush=True)
from collections import Counter
for window in [(56, 70), (0, 96), (25, 39)]:
    t0 = time.perf_counter()
    for _ in range(3):
        wx._swept_window.__wrapped__(wx, window[0], window[1])
    t = (time.perf_counter() - t0) / 3
    print(f'  window {window} span {window[1] - window[0]}: {t * 1000:.2f} ms', flush=True)

# 4. What if only the band is cached per (s,e) and the rings use a track cache
#    keyed by (s,e) -- how many ring-track builds does a plan need?
print('--- distinct (s,e) windows the planner asks for ---', flush=True)
real_env = weather.NetworkWeather.envelope
calls = []
def spy(self, start, end):
    calls.append((int(start // 5), int(-(-end // 5))))
    return real_env(self, start, end)
import traffic.service as service
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

service.network()
weather.NetworkWeather.envelope = spy
service.simulate(seed=42, scenario='moving')
weather.NetworkWeather.envelope = real_env
print(f'  calls {len(calls)}, distinct {len(set(calls))}', flush=True)

# 5. Could a per-start accumulator answer all spans? Count distinct starts.
starts = sorted(set(s for s, e in calls))
print(f'  distinct starts {len(starts)}: {starts[:12]}...', flush=True)
print(f'  max start {max(starts)}, max end {max(e for s, e in calls)}', flush=True)
