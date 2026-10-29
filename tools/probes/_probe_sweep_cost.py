"""Where does a finer radar sweep actually spend its time?

``_probe_sweep_resolution`` established that the incursions fall to zero at a
10-minute stride but the build grows from ~28 s to ~73 s. Before paying that, or
before inventing an approximation to avoid it, this splits the build into its
phases so the cost is attributed rather than guessed:

  * the radar sweep itself (``_radar_avoidance`` -> ``_virtual_radar_samples``)
  * the per-flight loop, which is where any window union is paid
  * the two union memos, counted so the number of distinct windows is visible

Run from the repository root:

    backend-python\\.venv\\Scripts\\python.exe tools\\probes\\_probe_sweep_cost.py
"""
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'backend-python'))

from traffic import service, weather_control  # noqa: E402

SEED = 42
STRIDES = (60, 20, 10)


def timed(stride):
    service.RADAR_SWEEP_STRIDE_MINUTES = stride
    service._virtual_radar_samples.cache_clear()
    service._virtual_radar_derived.cache_clear()

    original = service._radar_window_union
    counters = {'calls': 0, 'misses': 0, 'seconds': 0.0}

    def wrapped(*args, **kwargs):
        counters['calls'] += 1
        before = dict(service._RADAR_WINDOW_CACHE)
        start = time.perf_counter()
        result = original(*args, **kwargs)
        counters['seconds'] += time.perf_counter() - start
        if len(service._RADAR_WINDOW_CACHE) > len(before):
            counters['misses'] += 1
        return result

    service._radar_window_union = wrapped
    try:
        start = time.perf_counter()
        plan = service.simulate(seed=SEED, scenario='live',
                                weather_mode=weather_control.MODE_VIRTUAL)
        total = time.perf_counter() - start
    finally:
        service._radar_window_union = original

    return plan, total, counters, len(service._virtual_radar_samples())


def main():
    weather_control.set_mode(weather_control.MODE_VIRTUAL, seed=SEED, actor='probe')
    print(f'{"stride":>7} {"samples":>8} {"total s":>9} {"union s":>9} {"union %":>8} '
          f'{"calls":>9} {"distinct windows":>17}')
    print('-' * 72)
    for stride in STRIDES:
        plan, total, counters, samples = timed(stride)
        share = counters['seconds'] / total * 100 if total else 0
        print(f'{stride:>7} {samples:>8} {total:>9.1f} {counters["seconds"]:>9.1f} '
              f'{share:>7.1f}% {counters["calls"]:>9} {counters["misses"]:>17}')
    print()
    print('union seconds counts the memoised window unions only; the first call for a')
    print('given (bucket, bucket, tier) does the real work, later calls are dict hits.')


if __name__ == '__main__':
    main()
