"""Explain why a faster per-window hull made the whole plan slower.

Measured contradiction to resolve:

  * `_band_hull` per window: per-cluster 33.7-50.0 ms, bridged 45.1-52.4 ms
    -- the per-cluster construction is FASTER (or equal) on every window, and
  * whole plan: per-cluster 92 s, bridged 66 s
    -- the per-cluster construction is SLOWER by 26 s.

Those cannot both be the effect of the hull. Something outside `_band_hull`
changed cost when the envelope changed *shape*: the envelope is consumed by
routing and conflict checks, so a smaller, multi-part envelope changes how many
polygons those downstream routines must test. That is the hypothesis this probe
tests -- by counting the envelope's polygon parts and the routing work, rather
than guessing.

Run:  backend-python/.venv/Scripts/python.exe tools/probes/_probe_envelope_parts.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

from traffic import weather  # noqa: E402
from shapely.geometry import MultiPoint  # noqa: E402
from shapely.ops import unary_union  # noqa: E402


def part_count(geometry):
    if geometry is None or geometry.is_empty:
        return 0
    if geometry.geom_type in ('Polygon',):
        return 1
    return len(getattr(geometry, 'geoms', []))


def bridged_hull(net, cell, start_bin, end_bin):
    ticks = list(range(start_bin, end_bin + 1))
    offsets = [net.drift(cell, tick * 5) for tick in ticks]
    coords = []
    for cluster in cell.get('clusters', ()):
        for tick in ticks:
            coords.extend(weather._band_cluster_hull_coords(cluster, tick * 5))
    if not coords:
        return None
    cb = weather._hull_ring_coords(MultiPoint(offsets).convex_hull)
    ca = weather._hull_ring_coords(MultiPoint(coords).convex_hull)
    if not ca or not cb:
        return None
    points = [(ax + bx, ay + by) for ax, ay in ca for bx, by in cb]
    return MultiPoint(points).convex_hull.buffer(weather.SWEPT_BAND_PAD_M, quad_segs=4)


def main():
    net = weather.NetworkWeather(seed=7, scenario='nominal')
    band_index = next(i for i, c in enumerate(net.cells) if c.get('shape') == 'BAND')
    cell = net.cells[band_index]

    print('--- part count and vertex count of the window envelope ---')
    print('%6s %18s %18s' % ('bins', 'bridged parts/verts', 'perclust parts/verts'))
    for start_bin in (0, 24, 48, 72):
        end_bin = start_bin + 14
        a = bridged_hull(net, cell, start_bin, end_bin)
        b = net._band_hull(band_index, start_bin, end_bin)
        av = bv = 0
        if a is not None and not a.is_empty:
            av = len(a.exterior.coords) if a.geom_type == 'Polygon' else sum(
                len(g.exterior.coords) for g in a.geoms)
        if b is not None and not b.is_empty:
            bv = len(b.exterior.coords) if b.geom_type == 'Polygon' else sum(
                len(g.exterior.coords) for g in b.geoms)
        print('%6d %18s %18s'
              % (start_bin,
                 '%d parts / %d verts' % (part_count(a), av),
                 '%d parts / %d verts' % (part_count(b), bv)))

    # The envelope the planner actually sees is the union over ALL cells, not just
    # the band. A multi-part band makes that union multi-part too, and each part is
    # another polygon for the conflict test to walk.
    print()
    print('--- whole-network envelope, which is what routing consumes ---')
    print('%6s %10s %10s %14s' % ('bins', 'parts', 'verts', 'build ms'))
    for start_bin in (0, 24, 48, 72):
        end_bin = start_bin + 14
        net2 = weather.NetworkWeather(seed=7, scenario='nominal')
        # Make the window cache cold so this measures a real build.
        clear = getattr(net2._swept_window, 'cache_clear', None)
        if clear:
            clear()
        began = time.perf_counter()
        env = net2.envelope(start_bin * 5.0, end_bin * 5.0)
        span = time.perf_counter() - began
        verts = 0
        if env is not None and not env.is_empty:
            verts = (len(env.exterior.coords) if env.geom_type == 'Polygon'
                     else sum(len(g.exterior.coords) for g in env.geoms))
        print('%6d %10d %10d %13.1fms'
              % (start_bin, part_count(env), verts, span * 1000))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
