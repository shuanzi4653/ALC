"""Count the points `_band_hull` feeds to `convex_hull`, per window.

Timing said the hull is ~478 ms cold and grows to ~820 ms while
`_band_cluster_outlines` costs 0.0002 ms -- so the cost is the final
`MultiPoint(...).convex_hull`, and the question is how many points it is asked
to hull. Guessing here would be exactly the mistake the file's own comments warn
about, so this counts them.

Run:  backend-python/.venv/Scripts/python.exe tools/probes/_probe_hull_points.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

from traffic import weather  # noqa: E402
from shapely.geometry import MultiPoint  # noqa: E402


def main():
    net = weather.NetworkWeather(seed=7, scenario='nominal')
    band_index = next(i for i, c in enumerate(net.cells) if c.get('shape') == 'BAND')
    cell = net.cells[band_index]

    print('%6s %6s %8s %9s %11s %11s %10s' %
          ('bins', 'ticks', 'offsets', 'clusters', 'coords', 'points', 'hull ms'))
    for start_bin in (0, 24, 48, 60, 72, 84):
        end_bin = start_bin + 14
        ticks = list(range(start_bin, end_bin + 1))
        offsets = [net.drift(cell, tick * 5) for tick in ticks]

        pruned = len(offsets)
        if len(offsets) > 24:
            drift_hull = MultiPoint(offsets).convex_hull
            boundary_points = set()
            if drift_hull.geom_type == 'Polygon':
                boundary_points = {round(x, 6) for x, _ in drift_hull.exterior.coords}
            support = [o for o in offsets
                       if round(o[0], 6) in boundary_points
                       or round(o[1], 6) in boundary_points]
            if support:
                pruned = len(support)

        cluster_coords = []
        live = 0
        for cluster in cell.get('clusters', ()):
            before = len(cluster_coords)
            for tick in ticks:
                outline, _core = weather._band_cluster_outlines(cluster, tick * 5)
                if outline is None:
                    continue
                cluster_coords.extend(weather._outline_hull_coords(outline))
            if len(cluster_coords) > before:
                live += 1

        points = pruned * len(cluster_coords)
        # Time just the hull on that many points, to show the point count is the cost.
        pts = [(0.0, 0.0)] * points
        began = time.perf_counter()
        MultiPoint(pts).convex_hull
        hull_ms = (time.perf_counter() - began) * 1000
        print('%6d %6d %8d %9d %11d %11d %10.1f'
              % (start_bin, len(ticks), pruned, live, len(cluster_coords), points, hull_ms))

    print()
    print('offsets kept by the prune vs the true drift hull:')
    for start_bin in (0, 48, 72):
        ticks = list(range(start_bin, start_bin + 15))
        offsets = [net.drift(cell, tick * 5) for tick in ticks]
        hull = MultiPoint(offsets).convex_hull
        true_vertices = len(hull.exterior.coords) if hull.geom_type == 'Polygon' else len(offsets)
        boundary_points = set()
        if hull.geom_type == 'Polygon':
            boundary_points = {round(x, 6) for x, _ in hull.exterior.coords}
        support = [o for o in offsets
                   if round(o[0], 6) in boundary_points
                   or round(o[1], 6) in boundary_points]
        print('  bins %3d: %2d offsets -> %2d kept, hull has %2d vertices'
              % (start_bin, len(offsets), len(support), true_vertices))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
