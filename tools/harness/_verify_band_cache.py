"""The band-hull cache must be a pure speed-up: identical geometry, identical plan.

Two things have to hold, or the change has to be reverted again:
  1. `_swept_band` returns the same geometry as the pre-change per-vertex hull for
     every window the planner actually asks for;
  2. the plan is bit-identical, checked by hashing (id, status, reason) over all
     flights, and by accepted/closed counts.

(2) is the real guard. The outward grid-snapping experiment passed (1) on area
yet still re-planned the network; only the flight-level hash catches that.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import hashlib
import json
from pathlib import Path


import time  # noqa: E402

from traffic import service, weather  # noqa: E402
from shapely.geometry import MultiPoint  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


wx = weather.NetworkWeather(42, 'moving')
band_index = next(i for i, c in enumerate(wx.cells) if c['shape'] == 'BAND')
band = wx.cells[band_index]
coords = list(band['polygon'].exterior.coords)


def reference(start_bin, end_bin):
    """The construction that was in place before this change, verbatim."""
    points = []
    for tick in range(start_bin, end_bin + 1):
        dx, dy = wx.drift(band, tick * 5)
        points.extend((px + dx, py + dy) for px, py in coords)
    return MultiPoint(points).convex_hull.buffer(weather.SWEPT_BAND_PAD_M, quad_segs=4)


print('--- geometry equality across real windows ---', flush=True)
WINDOWS = [(0, 1), (0, 3), (14, 28), (56, 70), (0, 96), (0, 97), (95, 97), (25, 39), (12, 107)]
worst = 0.0
for window in WINDOWS:
    got = wx._swept_band(band_index, window[0], window[1])
    want = reference(window[0], window[1])
    diff = got.symmetric_difference(want).area
    worst = max(worst, diff)
    print(f'  {str(window):<10} symdiff {diff:>12,.4f} m^2', flush=True)
print(f'  WORST {worst:,.4f} m^2', flush=True)
assert worst < 1.0, f'band hull changed geometry by {worst:,.2f} m^2'

# What does the support-point pruning buy? Time each window.
print('--- cost per window (support-point pruning) ---', flush=True)
for window in [(56, 70), (0, 96)]:
    t0 = time.perf_counter()
    wx._swept_band(band_index, window[0], window[1])
    cold = time.perf_counter() - t0
    t0 = time.perf_counter()
    wx._swept_band(band_index, window[0], window[1])
    again = time.perf_counter() - t0
    print(f'  {window}: first {cold * 1000:7.2f} ms, second {again * 1000:7.2f} ms', flush=True)

print('--- plan identity ---', flush=True)
service.network()
digests = {}
for seed in (42, 98765):
    t0 = time.perf_counter()
    plan = service.simulate(seed=seed, scenario='moving')
    elapsed = time.perf_counter() - t0
    accepted = sum(1 for f in plan['flights'] if f['status'] == 'SCHEDULED')
    closed = sum(1 for f in plan['flights'] if f['status'] == 'CLOSED')
    digest = hashlib.sha256(json.dumps(
        [(f['id'], f['status'], f.get('reason')) for f in plan['flights']],
        sort_keys=True).encode()).hexdigest()[:16]
    print(f'  seed {seed}: {elapsed:.2f} s  flights {len(plan["flights"])} '
          f'accepted {accepted} closed {closed}  digest {digest}', flush=True)
    digests[seed] = (accepted, closed, digest)

print(json.dumps({str(k): v for k, v in digests.items()}, indent=2), flush=True)
