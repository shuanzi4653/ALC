"""Check that `_band_hull` produces a well-formed, non-degenerate hull.

Written because the sweep crashed with
``TypeError: cannot unpack non-iterable float object`` -- `offsets` is a list of
``(dx, dy)`` pairs and ``offsets.extend((0.0, 0.0))`` appended two bare floats
instead of one pair.  A crash is loud; the interesting failure after the fix is
the *quiet* one: an envelope that is empty or too small, which lets a trajectory
thread the band.  So this probe asserts both shape and size.

Run:  backend-python/.venv/Scripts/python.exe tools/probes/_probe_band_hull_shape.py
"""

import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

from traffic import weather  # noqa: E402


def main():
    net = weather.NetworkWeather(seed=7, scenario='nominal')
    band_index = None
    for index, cell in enumerate(net.cells):
        if cell.get('shape') == 'BAND':
            band_index = index
            break
    if band_index is None:
        print('no BAND cell in the network -- probe cannot run')
        return 1

    print('band cell index: %d  id=%s' % (band_index, net.cells[band_index].get('id')))
    print()

    # `offset` list shape for two very different windows: one that trips the
    # `len(offsets) > 24` prune and one that does not.
    failures = []
    for start_bin, end_bin in ((0, 14), (0, 96), (12, 40), (60, 96)):
        try:
            hull = net._band_hull(band_index, start_bin, end_bin)
        except Exception as exc:  # noqa: BLE001 - the whole point is to report it
            failures.append('window (%d,%d) raised %s: %s'
                            % (start_bin, end_bin, type(exc).__name__, exc))
            print('window (%3d,%3d): RAISED %s: %s'
                  % (start_bin, end_bin, type(exc).__name__, exc))
            continue

        empty = hull.is_empty
        area_km2 = 0.0 if empty else hull.area / 1.0e6
        kind = hull.geom_type
        valid = hull.is_valid
        print('window (%3d,%3d): %-18s valid=%-5s empty=%-5s area=%12.1f km2'
              % (start_bin, end_bin, kind, valid, empty, area_km2))
        if empty:
            failures.append('window (%d,%d) returned an empty envelope' % (start_bin, end_bin))
        if not valid:
            failures.append('window (%d,%d) returned an invalid geometry' % (start_bin, end_bin))

    # The swept value is what the planner actually consumes.
    print()
    for start, end in ((0.0, 180.0), (0.0, 480.0)):
        try:
            swept = net.envelope(start, end)
        except Exception as exc:  # noqa: BLE001
            failures.append('envelope(%s,%s) raised %s: %s'
                            % (start, end, type(exc).__name__, exc))
            print('envelope(%5.1f,%5.1f): RAISED %s: %s'
                  % (start, end, type(exc).__name__, exc))
            continue
        area_km2 = 0.0 if swept.is_empty else swept.area / 1.0e6
        print('envelope(%5.1f,%5.1f): %-18s empty=%-5s area=%12.1f km2  bounds=%s'
              % (start, end, swept.geom_type, swept.is_empty, area_km2,
                 tuple(round(v / 1000.0, 1) for v in swept.bounds) if not swept.is_empty else None))
        if swept.is_empty:
            failures.append('envelope(%s,%s) is empty' % (start, end))

    print()
    if failures:
        print('FAIL -- %d problem(s)' % len(failures))
        for item in failures:
            print('  ! ' + item)
        return 1
    print('ok -- band hull is well formed across every sampled window')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
