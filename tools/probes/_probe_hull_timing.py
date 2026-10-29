"""Measure `_band_hull` and `envelope` cost without building a whole plan.

The earlier probe bundled a `cProfile` of `simulate()`, which runs the entire
plan and therefore takes many minutes -- far too slow to steer an optimisation
with. This one touches only the functions in question, at a scale small enough
to iterate on, and separates:

  * the *cold* cost of one hull (the thing to reduce), and
  * the per-window work as a function of the number of live clusters.

Run:  backend-python/.venv/Scripts/python.exe tools/probes/_probe_hull_timing.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

from traffic import weather  # noqa: E402


def build():
    return weather.NetworkWeather(seed=7, scenario='nominal')


def main():
    net = build()
    band_index = next(i for i, c in enumerate(net.cells) if c.get('shape') == 'BAND')
    band = net.cells[band_index]
    clusters = band.get('clusters') or []
    print('band cell:        %s' % band.get('id'))
    print('clusters defined: %d' % len(clusters))
    print()

    # How many clusters are alive across the run, per window? That count is the
    # multiplier on the inner loop, so it is the first thing to know.
    print('alive-cluster count per 15-bin window:')
    for start_bin in range(0, 82, 10):
        ticks = list(range(start_bin, start_bin + 15))
        live = []
        for cluster in clusters:
            any_live = False
            for tick in ticks:
                outline, _core = weather._band_cluster_outlines(cluster, tick * 5)
                if outline is not None:
                    any_live = True
                    break
            if any_live:
                live.append(cluster.get('id'))
        print('  bins %3d-%3d: %d live %s' % (start_bin, start_bin + 15, len(live), live[:3]))
    print()

    # Cold hull cost: clear the window cache between calls so nothing is reused.
    print('cold _band_hull cost (cache cleared each call):')
    total = 0.0
    runs = 0
    for start_bin in range(0, 82, 6):
        clear = getattr(net._swept_window, 'cache_clear', None)
        if clear:
            clear()
        began = time.perf_counter()
        try:
            hull = net._band_hull(band_index, start_bin, start_bin + 14)
        except Exception as exc:  # noqa: BLE001
            print('  bins %3d: RAISED %s: %s' % (start_bin, type(exc).__name__, exc))
            continue
        span = time.perf_counter() - began
        total += span
        runs += 1
        area = 0.0 if hull.is_empty else hull.area / 1.0e6
        print('  bins %3d-%3d: %7.1f ms  %-16s %10.1f km2'
              % (start_bin, start_bin + 14, span * 1000, hull.geom_type, area))
    if runs:
        print('  -> %.2f ms mean per cold hull over %d windows' % (total * 1000 / runs, runs))
    print()

    # How expensive is each ingredient?
    print('ingredient cost (per call, 200 reps in a loop):')

    def timeit(label, fn, reps=200):
        began = time.perf_counter()
        for _ in range(reps):
            fn()
        span = time.perf_counter() - began
        print('  %-34s %8.4f ms/call' % (label, span * 1000 / reps))

    cluster = clusters[0] if clusters else None
    if cluster:
        timeit('_band_cluster_outlines(cluster, 300)',
               lambda: weather._band_cluster_outlines(cluster, 300.0), reps=500)
        field, _core = weather._band_cluster_outlines(cluster, 300.0)
        if field is not None:
            timeit('_outline_hull_coords(field)',
                   lambda: weather._outline_hull_coords(field), reps=500)
    timeit('net.drift(cell, 300)', lambda: net.drift(band, 300.0), reps=500)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
