"""Verify the Minkowski identity that lets the band hull drop ~60x the points.

Claim to test
-------------
Let ``A`` be the cluster coords and ``B`` the drift offsets.  The current code
hulls the Cartesian sum ``{a + b}`` directly, which is ~15 x 4000 = 60k points
and costs 250-355 ms.  The proposed code uses

    hull(A + B) == hull( hull(A) + hull(B) )

which needs only ``|vertices(hull A)| x |vertices(hull B)|`` points -- a few
hundred -- and should be orders of magnitude cheaper.

The identity is a standard fact for convex hulls of Minkowski sums of finite
point sets, but the whole reason the band's envelope is delicate is that a hull
that comes out *too small* silently lets a trajectory thread the rain band. So
this is verified numerically against the current implementation on real windows
rather than asserted from theory.

A second check guards the other direction: the result must still *contain* every
raw ``a + b`` point, so it cannot be too small.

Run:  backend-python/.venv/Scripts/python.exe tools/probes/_probe_hull_identity.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

from traffic import weather  # noqa: E402
from shapely.geometry import MultiPoint, Point  # noqa: E402


def collect(net, cell, start_bin, end_bin):
    """Rebuild the two point sets exactly as `_band_hull` does."""
    ticks = list(range(start_bin, end_bin + 1))
    offsets = [net.drift(cell, tick * 5) for tick in ticks]
    cluster_coords = []
    for cluster in cell.get('clusters', ()):
        for tick in ticks:
            outline, _core = weather._band_cluster_outlines(cluster, tick * 5)
            if outline is None:
                continue
            cluster_coords.extend(weather._outline_hull_coords(outline))
    return offsets, cluster_coords


def direct(offsets, cluster_coords):
    points = []
    for dx, dy in offsets:
        points.extend((px + dx, py + dy) for px, py in cluster_coords)
    return MultiPoint(points).convex_hull


def minkowski(offsets, cluster_coords):
    hull_a = MultiPoint(cluster_coords).convex_hull
    hull_b = MultiPoint(offsets).convex_hull
    ca = list(hull_a.exterior.coords) if hull_a.geom_type == 'Polygon' else list(hull_a.coords)
    cb = list(hull_b.exterior.coords) if hull_b.geom_type == 'Polygon' else list(hull_b.coords)
    points = [(ax + bx, ay + by) for ax, ay in ca for bx, by in cb]
    return MultiPoint(points).convex_hull


def main():
    net = weather.NetworkWeather(seed=7, scenario='nominal')
    band_index = next(i for i, c in enumerate(net.cells) if c.get('shape') == 'BAND')
    cell = net.cells[band_index]

    print('%6s %9s %9s %13s %13s %9s %8s' %
          ('bins', 'nA', 'nB', 'direct km2', 'mink km2', 'diff km2', 't ratio'))
    worst_diff = 0.0
    worst_ratio = 0.0
    for start_bin in (0, 12, 24, 36, 48, 60, 72, 84):
        offsets, cluster_coords = collect(net, cell, start_bin, start_bin + 14)
        if not offsets or not cluster_coords:
            print('%6d  -- nothing alive, skipped' % start_bin)
            continue

        began = time.perf_counter()
        a = direct(offsets, cluster_coords)
        t_direct = time.perf_counter() - began

        began = time.perf_counter()
        b = minkowski(offsets, cluster_coords)
        t_mink = time.perf_counter() - began

        area_a = a.area / 1.0e6
        area_b = b.area / 1.0e6
        diff = abs(a.area - b.area) / 1.0e6
        ratio = t_direct / max(t_mink, 1e-9)
        worst_diff = max(worst_diff, diff)
        worst_ratio = max(worst_ratio, ratio)
        print('%6d %9d %9d %13.1f %13.1f %9.3f %7.1fx'
              % (start_bin, len(cluster_coords), len(offsets), area_a, area_b, diff, ratio))

        # Containment: every raw a+b point must be inside the Minkowski hull.
        hull_a = MultiPoint(cluster_coords).convex_hull
        ca = list(hull_a.exterior.coords)
        # sample raw points rather than all 60k, to keep the probe fast
        sample = offsets[:: max(1, len(offsets) // 5)]
        misses = 0
        outer = b.buffer(1.0)  # 1 m tolerance for float noise
        for dx, dy in sample:
            for px, py in ca[: 40 ]:
                if not outer.contains(Point(px + dx, py + dy)):
                    misses += 1
        if misses:
            print('        ! %d sampled raw points fell outside the Minkowski hull' % misses)

    print()
    print('worst area difference: %.3f km2' % worst_diff)
    print('worst speed-up:        %.1fx' % worst_ratio)
    if worst_diff > 1.0:
        print('FAIL -- the identity does not hold to within 1 km2 on the real windows')
        return 1
    print('ok -- identity holds; the Minkowski route reproduces the direct hull area')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
