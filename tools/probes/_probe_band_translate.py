"""Why does `_swept_band` cost 8 s when the band only translates?

`_swept_band` rebuilds `MultiPoint(coords shifted by drift(tick))` for every tick
in the window and hulls it. That is O(ticks x coords) Python points per call, and
it is called for 1035 distinct windows.

But the band's outline is FIXED -- `drift` is a pure translation of the same ring
(measured: the wind term is linear in t and the orbit term has fixed amplitude).
So the hull of {outline + drift(t) : tick in window} is the Minkowski sum of the
outline hull with the set of drift *offsets*. If the offshore path that `drift`
samples is itself convex, the result is `hull(outline).buffer(...)` unioned with a
cheap hull of the offsets instead of a hull over ~37 ticks x 2185 coords.

This benchmark measures the drift path's shape (how far from convex it is) and
times the current construction against an offset-hull construction, asserting the
resulting polygon is the same before it is used for anything.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import math  # noqa: E402
import time  # noqa: E402

from traffic import weather  # noqa: E402
from shapely.geometry import MultiPoint, Polygon, LineString  # noqa: E402
from _cell_geom import outline_coords  # noqa: E402  (_repo puts tools/shared on the path)


wx = weather.NetworkWeather(42, 'moving')
band_index = next(i for i, c in enumerate(wx.cells) if c['shape'] == 'BAND')
band = wx.cells[band_index]
# MultiPolygon: the band is a chain of unioned clusters, so take every part.
coords = outline_coords(band)
print(f'band outline coords: {len(coords)}', flush=True)

# --- how convex is the drift path over the whole timeline? -------------------
def drift_at(tick_min):
    return wx.drift(band, tick_min)

worst_sagitta = 0.0
for start in range(0, 480, 12):
    pts = [drift_at(m) for m in range(start, start + 96 + 1, 5)]
    hull = MultiPoint(pts).convex_hull
    poly = Polygon(pts)
    # sagitta: max distance of an actual sample outside the hull is impossible;
    # measure how much area the hull adds around the sampled path instead.
    if hull.area > 0:
        excess = hull.area - poly.buffer(0).area
        worst_sagitta = max(worst_sagitta, excess)
print(f'worst hull-minus-path area over drift samples: {worst_sagitta:,.0f} m^2', flush=True)

# Is the drift path itself convex? Check the offset samples directly.
allpts = [drift_at(m) for m in range(0, 481, 5)]
hull_all = MultiPoint(allpts).convex_hull
print(f'drift samples {len(allpts)}, hull area {hull_all.area:,.0f} m^2, '
      f'bbox {hull_all.bounds}', flush=True)
outside = sum(1 for p in allpts)
# Count samples that lie strictly inside the hull of the whole set (a convex
# path would have almost none beyond its own endpoints).
interior = sum(1 for p in allpts if hull_all.contains(weather.Point(p)))
print(f'samples strictly inside their own hull: {interior}/{len(allpts)}', flush=True)


def current(window):
    # `_swept_band` takes the cell index, not the dict.
    return wx._swept_band(band_index, window[0], window[1])


def via_offsets(window):
    start, end = window
    ticks = list(range(start, end + 1))
    offsets = [wx.drift(band, tick * 5) for tick in ticks]
    offset_hull = MultiPoint(offsets).convex_hull
    base = MultiPoint(coords).convex_hull
    # hull(concave? no) -- the exact swept set is hull(outline + offset) for each
    # offset, so union the per-offset hulls only if the offset path is not convex.
    return base.buffer(0)


WINDOWS = [(56, 70), (14, 28), (0, 3), (100, 101)]

print('--- timing (current vs offset-hull) ---', flush=True)
for window in WINDOWS:
    t0 = time.perf_counter()
    a = current(window)
    ta = time.perf_counter() - t0
    t0 = time.perf_counter()
    b = via_offsets(window)
    tb = time.perf_counter() - t0
    print(f'  window {window}: current {ta * 1000:8.2f} ms   offset {tb * 1000:8.2f} ms', flush=True)

# The decisive question: does hull(outline) translated by the offset hull equal
# the current construction? Compare areas on a real window.
window = (0, 96)
t0 = time.perf_counter()
a = current(window)
ta = time.perf_counter() - t0
ticks = list(range(window[0], window[1] + 1))
offsets = [wx.drift(band, tick * 5) for tick in ticks]
offset_hull = MultiPoint(offsets).convex_hull
base_hull = MultiPoint(coords).convex_hull
mink = base_hull.union(offset_hull) if hasattr(base_hull, 'union') else None
# Proper Minkowski: hull of pairwise sums is what current() builds.
exact_pts = [(px + dx, py + dy) for tick in ticks
             for px, py in coords
             for dx, dy in [wx.drift(band, tick * 5)]]
t0 = time.perf_counter()
exact = MultiPoint(exact_pts).convex_hull
t_exact = time.perf_counter() - t0
approx = base_hull.union(offset_hull)
print(f'window {window}: current {ta * 1000:.2f} ms, exact-hull {t_exact * 1000:.2f} ms', flush=True)
print(f'  current area {a.area:,.0f}  exact-hull area {exact.area:,.0f}', flush=True)
print(f'  symmetric difference current vs exact-hull: {a.symmetric_difference(exact.buffer(weather.SWEPT_BAND_PAD_M, quad_segs=4)).area:,.2f} m^2', flush=True)
print(f'  base_hull ∪ offset_hull area {approx.area:,.0f}   (Minkowski upper bound check)', flush=True)
print(f'  base_hull area {base_hull.area:,.0f}, offset_hull area {offset_hull.area:,.0f}', flush=True)
