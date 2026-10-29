"""Can the band hull be built from fewer sample ticks without changing it?

All 1035 band-hull calls are distinct -- there is no reuse to cache, so the only
way to cut its 3.5 s is to make each hull cheaper. The hull is taken over
`64 outline vertices x (span+1) tick offsets`. The outline is fixed, so the hull
is `hull({outline + d_t})`, and the extremal points come from the outline vertices
on the convex hull of the *drift set*: for each drift offset that lies on the
drift hull, one translate of the outline contributes.

So a hull over sampled ticks is exact iff the sampled drift offsets include every
vertex of the true drift path's hull. The drift path is smooth (wind + two slow
harmonics), so it should be very well approximated by far fewer samples -- but
"well approximated" is not "exact", and a smaller hull lets trajectories through.

This measures, per window, the true hull area against hulls built from strided
tick subsets, and reports the missing area. Only a stride with zero missing area
on every window is usable.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import time
from pathlib import Path


from traffic import weather  # noqa: E402
from shapely.geometry import MultiPoint  # noqa: E402
from _cell_geom import outline_coords  # noqa: E402  (_repo puts tools/shared on the path)


wx = weather.NetworkWeather(42, 'moving')
bi = next(i for i, c in enumerate(wx.cells) if c['shape'] == 'BAND')
band = wx.cells[bi]
# The band is a chain of ~20 unioned clusters, so its footprint is a
# MultiPolygon; `.exterior` only exists on a single Polygon.
coords = outline_coords(band)

WINDOWS = [(0, 18), (0, 36), (1, 14), (0, 96), (12, 107), (95, 97), (56, 70)]


def hull_strided(start_bin, end_bin, stride):
    points = []
    ticks = list(range(start_bin, end_bin + 1, stride))
    if ticks[-1] != end_bin:
        ticks.append(end_bin)
    for tick in ticks:
        dx, dy = wx.drift(band, tick * 5)
        points.extend((px + dx, py + dy) for px, py in coords)
    return MultiPoint(points).convex_hull.buffer(weather.SWEPT_BAND_PAD_M, quad_segs=4)


print('--- missing area vs full hull, by stride ---', flush=True)
for stride in (1, 2, 3, 4, 5, 8):
    worst = 0.0
    worst_win = None
    for w in WINDOWS:
        full = hull_strided(w[0], w[1], 1)
        cheap = hull_strided(w[0], w[1], stride)
        missing = full.difference(cheap).area
        if missing > worst:
            worst = missing
            worst_win = w
    print(f'  stride {stride}: worst missing {worst:>16,.2f} m^2  (window {worst_win})', flush=True)

print('--- timing at various strides (window 0..96) ---', flush=True)
for stride in (1, 2, 4, 8):
    t0 = time.perf_counter()
    for _ in range(5):
        hull_strided(0, 96, stride)
    t = (time.perf_counter() - t0) / 5
    print(f'  stride {stride}: {t * 1000:7.2f} ms', flush=True)

print('--- how many drift samples are hull vertices? (window 0..96) ---', flush=True)
for w in [(0, 96), (0, 18), (56, 70)]:
    offsets = [wx.drift(band, t * 5) for t in range(w[0], w[1] + 1)]
    h = MultiPoint(offsets).convex_hull
    hv = len(h.exterior.coords) - 1
    print(f'  window {w}: {len(offsets)} samples, {hv} on the drift hull', flush=True)
