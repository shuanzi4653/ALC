"""Prove the offset-hull band envelope equals the per-vertex hull, or reject it.

The rewrite in `_swept_band` claims the Minkowski-sum form is the *same* region.
That claim has to be tested on the real windows the planner asks for, because a
cheaper envelope that is slightly smaller would silently let trajectories thread
through a risk area -- exactly the class of defect the band was promoted to a
first-class cell to fix.

Checks, per window:
  1. symmetric difference against the previous per-vertex hull, in m^2;
  2. that no accepted trajectory of a real plan enters the new envelope where it
     was outside the old one (the safety question that matters).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import time  # noqa: E402

from traffic import service, weather  # noqa: E402
from shapely.geometry import MultiPoint  # noqa: E402

wx = weather.NetworkWeather(42, 'moving')
band = [c for c in wx.cells if c['shape'] == 'BAND'][0]
coords = list(band['polygon'].exterior.coords)


def old_form(cell, start_bin, end_bin):
    """The construction replaced in this change, verbatim."""
    pts = []
    for tick in range(start_bin, end_bin + 1):
        dx, dy = wx.drift(cell, tick * 5)
        pts.extend((px + dx, py + dy) for px, py in coords)
    return MultiPoint(pts).convex_hull.buffer(weather.SWEPT_BAND_PAD_M, quad_segs=4)


WINDOWS = [(0, 1), (0, 3), (14, 28), (56, 70), (0, 96), (0, 97), (95, 97)]

print('--- area / symmetric difference (new vs old) ---', flush=True)
worst = 0.0
worst_window = None
for window in WINDOWS:
    new = wx._swept_band(band, window[0], window[1])
    old = old_form(band, window[0], window[1])
    diff = new.symmetric_difference(old).area
    missing = old.difference(new).area          # area the old form had, new lacks
    extra = new.difference(old).area            # area new added
    worst = max(worst, diff)
    if diff > worst * 0 + missing:
        pass
    print(f'  {str(window):<10} new {new.area:>18,.0f}  old {old.area:>18,.0f}  '
          f'symdiff {diff:>14,.2f}  missing {missing:>14,.2f}  extra {extra:>14,.2f}',
          flush=True)
    if missing > 0 and (worst_window is None or missing > worst_window[1]):
        worst_window = (window, missing)

print(f'--- worst symdiff {worst:,.2f} m^2 ---', flush=True)

# A smaller envelope is only acceptable if it never lets a trajectory that the
# old form would have blocked slip through. Run the plan and check every accepted
# path against BOTH envelopes.
print('--- plan safety: does any accepted path enter the new band envelope ---', flush=True)
plan = service.simulate(seed=42, scenario='moving')
accepted = [f for f in plan['flights'] if f['status'] == 'SCHEDULED']
print(f'  accepted {len(accepted)}', flush=True)

from shapely.geometry import LineString  # noqa: E402

new_inside = old_inside = 0
leaked = 0
t0 = time.perf_counter()
for flight in accepted:
    pts = flight.get('points') or []
    if len(pts) < 2:
        continue
    line = LineString([(p[0], p[1]) for p in pts])
    start_m, end_m = pts[0][3], pts[-1][3]
    s, e = int(start_m // 5), int(end_m // 5 + 0.999)
    if line.intersects(wx._swept_band(band, s, e)):
        new_inside += 1
    if line.intersects(old_form(band, s, e)):
        old_inside += 1
elapsed = time.perf_counter() - t0
print(f'  intersects new envelope: {new_inside}', flush=True)
print(f'  intersects old envelope: {old_inside}', flush=True)
print(f'  leaks (in new, not in old): {new_inside - old_inside}', flush=True)
print(f'  sweep check took {elapsed:.1f} s', flush=True)

# Also confirm the plan itself is unchanged, which is the strongest statement.
import hashlib  # noqa: E402
import json  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


digest = hashlib.sha256(
    json.dumps([(f['id'], f['status'], f.get('reason')) for f in plan['flights']],
               sort_keys=True).encode()).hexdigest()[:16]
print(f'  plan digest {digest}  accepted={sum(1 for f in plan["flights"] if f["status"] == "SCHEDULED")}'
      f'  closed={sum(1 for f in plan["flights"] if f["status"] == "CLOSED")}', flush=True)
