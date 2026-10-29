"""Decide whether the band envelope should be bridged, on evidence.

The per-cluster version is *geometrically* better (no bridging of the corridors)
but *slower*: it measures 92 s per plan against 66 s for the single-hull version.
Those two facts are about different things, so this probe separates them:

  * how much envelope is "bridging" -- area the single hull claims that the
    per-cluster union does not, i.e. airspace between segments;
  * whether any *trajectory* actually uses that airspace, which is the only
    reason bridging would matter to an operator.

The second question is the decisive one. If no planned trajectory crosses the
bridged region then the bridging is a cosmetic difference in the envelope
(which the envelope's caller consumes only as a keep-out), and the cheaper
version is the right trade. If trajectories *do* cross it, then the bridged
envelope is refusing airspace the band leaves open, and the cost is worth
paying -- or the routing needs to change instead.

Run:  backend-python/.venv/Scripts/python.exe tools/probes/_probe_band_bridging.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

from traffic import weather  # noqa: E402
from shapely.geometry import MultiPoint  # noqa: E402
from shapely.ops import unary_union  # noqa: E402


def bridged_hull(net, cell, start_bin, end_bin):
    """The single-hull construction: pool all clusters, one hull."""
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


def per_cluster_hull(net, cell, start_bin, end_bin):
    """The per-cluster construction: a union of per-cluster hulls."""
    ticks = list(range(start_bin, end_bin + 1))
    offsets = [net.drift(cell, tick * 5) for tick in ticks]
    cb = weather._hull_ring_coords(MultiPoint(offsets).convex_hull)
    if not cb:
        return None
    pieces = []
    for cluster in cell.get('clusters', ()):
        coords = []
        for tick in ticks:
            coords.extend(weather._band_cluster_hull_coords(cluster, tick * 5))
        if not coords:
            continue
        ca = weather._hull_ring_coords(MultiPoint(coords).convex_hull)
        if not ca:
            continue
        points = [(ax + bx, ay + by) for ax, ay in ca for bx, by in cb]
        pieces.append(MultiPoint(points).convex_hull)
    if not pieces:
        return None
    return unary_union(pieces).buffer(weather.SWEPT_BAND_PAD_M, quad_segs=4)


def main():
    net = weather.NetworkWeather(seed=7, scenario='nominal')
    band_index = next(i for i, c in enumerate(net.cells) if c.get('shape') == 'BAND')
    cell = net.cells[band_index]

    print('%6s %12s %12s %10s %10s %10s'
          % ('bins', 'bridged km2', 'perclust km2', 'bridge km2', 't bridged', 't perclu'))
    total_bridged = total_per = total_bridge_area = 0.0
    windows = 0
    for start_bin in (0, 12, 24, 36, 48, 60, 72, 84):
        end_bin = start_bin + 14
        began = time.perf_counter()
        a = bridged_hull(net, cell, start_bin, end_bin)
        ta = time.perf_counter() - began
        began = time.perf_counter()
        b = per_cluster_hull(net, cell, start_bin, end_bin)
        tb = time.perf_counter() - began
        if a is None or b is None:
            continue
        bridge = a.difference(b)
        bridge_km2 = bridge.area / 1.0e6 if not bridge.is_empty else 0.0
        total_bridged += a.area / 1.0e6
        total_per += b.area / 1.0e6
        total_bridge_area += bridge_km2
        windows += 1
        print('%6d %12.1f %12.1f %10.1f %9.1fms %9.1fms'
              % (start_bin, a.area / 1.0e6, b.area / 1.0e6, bridge_km2,
                 ta * 1000, tb * 1000))

    if not windows:
        print('no windows produced geometry')
        return 1

    print()
    print('bridged total:     %10.1f km2' % total_bridged)
    print('per-cluster total: %10.1f km2' % total_per)
    print('bridging (diff):   %10.1f km2  (%.1f%% of the bridged envelope)'
          % (total_bridge_area, total_bridge_area / total_bridged * 100 if total_bridged else 0))

    # Does any planned trajectory cross the bridging region? That is the question
    # that decides whether the difference matters operationally.
    from traffic import service
    plan = service.simulate(seed=7, scenario='nominal')
    # `simulate` returns a *dict*, not an object -- reading `.flights` off it via
    # getattr silently yields None and skips this whole test, which is exactly
    # what an earlier version of this probe did.
    if not isinstance(plan, dict):
        print()
        print('simulate() did not return a dict (%s); skipping the trajectory test'
              % type(plan).__name__)
        return 0
    flights = list(plan.get('flights') or [])
    if not flights:
        print()
        print('simulate() returned no flights; skipping the trajectory test')
        return 0

    print()
    print('checking %d planned trajectories against the bridging region...' % len(flights))
    # A flight point is `[x, y, altM, minute]` in the SAME projected metres the
    # envelope lives in (verified: point[0] is on the order of -2e5, and the
    # envelope bounds are hundreds of km), so containment is a direct test with no
    # reprojection. Each window is tested against points whose own minute falls
    # inside that window -- comparing a t=30 bridging region against a t=200
    # waypoint would manufacture hits that do not exist.
    from shapely.geometry import Point

    hits = 0
    checked = 0
    hit_flights = []
    for start_bin in (0, 24, 48, 72):
        end_bin = start_bin + 14
        a = bridged_hull(net, cell, start_bin, end_bin)
        b = per_cluster_hull(net, cell, start_bin, end_bin)
        if a is None or b is None:
            continue
        bridge = a.difference(b)
        if bridge.is_empty or bridge.area <= 0.0:
            continue
        lo_minute = start_bin * 5
        hi_minute = end_bin * 5
        for flight in flights:
            for point in (flight.get('points') or []):
                if len(point) < 4:
                    continue
                minute = point[3]
                if not (lo_minute <= minute <= hi_minute):
                    continue
                checked += 1
                if bridge.contains(Point(point[0], point[1])):
                    hits += 1
                    hit_flights.append(flight.get('id'))
                    break

    print('points tested inside windowed bridging regions: %d' % checked)
    print('trajectory points landing inside bridged area:  %d' % hits)
    if hit_flights:
        print('example flights: %s' % ', '.join(sorted(set(hit_flights))[:8]))
    print()
    if hits:
        print('VERDICT: bridging rejects real airspace -- keep the per-cluster envelope')
        return 0
    print('VERDICT: bridging rejects no trajectory -- the cheaper single hull '
          'is an acceptable trade, and the difference is envelope-only')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
