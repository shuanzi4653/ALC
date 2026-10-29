"""Split `_band_hull`'s remaining 121 s between its two Shapely calls.

After the outline memo, `_band_hull` is 121 s cumulative with only 0.8 s of its
own time, and `_outline_hull_coords` accounts for 12.5 s of that. The rest is
inside Shapely, which means one of:

  * ``MultiPoint(points).convex_hull``  -- on ~|hull A| x |hull B| points, and
  * ``.buffer(SWEPT_BAND_PAD_M, quad_segs=4)`` -- on the resulting polygon.

Which one dominates decides what to optimise, and they have opposite fixes, so
this times each stage separately on the real windows.

Run:  backend-python/.venv/Scripts/python.exe tools/probes/_probe_hull_split.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

from traffic import weather  # noqa: E402
from shapely.geometry import MultiPoint  # noqa: E402

REPS = 3


def main():
    net = weather.NetworkWeather(seed=7, scenario='nominal')
    band_index = next(i for i, c in enumerate(net.cells) if c.get('shape') == 'BAND')
    cell = net.cells[band_index]

    print('%6s %8s %8s %10s %10s %10s %10s' %
          ('bins', 'ncoords', 'npts', 'coords ms', 'hull ms', 'buffer ms', 'total ms'))
    totals = {'coords': 0.0, 'hull': 0.0, 'buffer': 0.0}
    windows = 0
    for start_bin in (0, 12, 24, 36, 48, 60, 72, 84):
        end_bin = start_bin + 14
        ticks = list(range(start_bin, end_bin + 1))
        offsets = [net.drift(cell, tick * 5) for tick in ticks]

        t_coords = t_hull = t_buffer = 0.0
        ncoords = 0
        npts = 0
        for _ in range(REPS):
            began = time.perf_counter()
            cluster_coords = []
            for cluster in cell.get('clusters', ()):
                for tick in ticks:
                    outline, _core = weather._band_cluster_outlines(cluster, tick * 5)
                    if outline is None:
                        continue
                    cluster_coords.extend(weather._outline_hull_coords(outline))
            t_coords += time.perf_counter() - began

            if not cluster_coords:
                break
            ca = weather._hull_ring_coords(MultiPoint(cluster_coords).convex_hull)
            cb = weather._hull_ring_coords(MultiPoint(offsets).convex_hull)
            points = [(ax + bx, ay + by) for ax, ay in ca for bx, by in cb]
            ncoords = len(cluster_coords)
            npts = len(points)

            began = time.perf_counter()
            hull = MultiPoint(points).convex_hull
            t_hull += time.perf_counter() - began

            began = time.perf_counter()
            hull.buffer(weather.SWEPT_BAND_PAD_M, quad_segs=4)
            t_buffer += time.perf_counter() - began

        if not ncoords:
            continue
        windows += 1
        totals['coords'] += t_coords
        totals['hull'] += t_hull
        totals['buffer'] += t_buffer
        print('%6d %8d %8d %10.1f %10.1f %10.1f %10.1f'
              % (start_bin, ncoords, npts,
                 t_coords / REPS * 1000, t_hull / REPS * 1000,
                 t_buffer / REPS * 1000,
                 (t_coords + t_hull + t_buffer) / REPS * 1000))

    if windows:
        print()
        grand = sum(totals.values())
        for name in ('coords', 'hull', 'buffer'):
            share = totals[name] / grand * 100 if grand else 0.0
            print('  %-8s %8.1f ms total  %5.1f%%' % (name, totals[name] * 1000, share))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
