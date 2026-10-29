"""Attribute the plan's compute time to the functions that actually cost it.

`weather.envelope` is the known hotspot (it was 94.7% of the old 12.6 s plan).
After the band rewrite `_band_hull` samples every live cluster's outline across
the whole window, which is more work per cache miss than the old
"one outline, translated" hull -- so the cost may have moved. This profile says
where it is now, by window, so an optimisation can be aimed rather than guessed.

Run:  backend-python/.venv/Scripts/python.exe tools/probes/_probe_band_cost.py
"""

import cProfile
import io
import pstats
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

from traffic import weather  # noqa: E402

SEED = 7
SCENARIO = 'nominal'


def build():
    return weather.NetworkWeather(seed=SEED, scenario=SCENARIO)


def cost_of_hull():
    net = build()
    band_index = next(i for i, c in enumerate(net.cells) if c.get('shape') == 'BAND')
    # Clear the window cache so each measurement is a cold hull.
    start = time.perf_counter()
    misses = 0
    for start_bin in range(0, 97, 5):
        net._swept_window.cache_clear() if hasattr(net._swept_window, 'cache_clear') else None
        net._band_hull(band_index, start_bin, start_bin + 14)
        misses += 1
    span = time.perf_counter() - start
    print('cold _band_hull x%d (span 14): %.1f ms total, %.2f ms each'
          % (misses, span * 1000, span * 1000 / max(misses, 1)))

    net2 = build()
    start = time.perf_counter()
    net2._band_hull(band_index, 0, 96)
    print('single wide _band_hull (span 96): %.1f ms' % ((time.perf_counter() - start) * 1000))


def cost_of_envelope_warm():
    net = build()
    # Mimic what `simulate` asks for: many overlapping windows, so the cache hits.
    windows = [(2 * i, 2 * i + 27) for i in range(240)]
    start = time.perf_counter()
    for s, e in windows:
        net.envelope(float(s), float(e))
    span = time.perf_counter() - start
    info = net._swept_window.cache_info() if hasattr(net._swept_window, 'cache_info') else None
    print('envelope x%d: %.1f ms total, %.2f ms each' % (len(windows), span * 1000, span * 1000 / len(windows)))
    if info:
        print('  cache: %s' % (info,))


def profile_plan():
    from traffic import service
    profiler = cProfile.Profile()
    profiler.enable()
    service.simulate(seed=SEED, scenario=SCENARIO)
    profiler.disable()
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream).sort_stats('cumulative')
    stats.print_stats(22)
    text = stream.getvalue()
    # print only the rows that carry the interesting names
    for line in text.splitlines():
        print(line)


def main():
    print('=== cold hull cost ===')
    cost_of_hull()
    print()
    print('=== warm envelope cost ===')
    cost_of_envelope_warm()
    print()
    print('=== plan profile (cumulative, top 22) ===')
    profile_plan()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
