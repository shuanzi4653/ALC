"""Measure the envelope cache hit rate and per-call cost in a real plan run.

`weather.envelope` is 94.7% of the plan (7.717 s of 8.152 s over 300 flights,
25.7 ms per call). The mechanism is supposed to be cheap via the `lru_cache` on
`_swept_window`, keyed on 5-minute bins. If the hit rate is high and each *miss*
is expensive, the fix is to reduce the cost of a miss (or precompute); if the
hit rate is low, the fix is the keying. This measures which, rather than
assuming the cache is working because there is a comment claiming it does.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND  # noqa: E402
import math
import time
from pathlib import Path


from traffic.weather import NetworkWeather  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


SEED = 4242
weather = NetworkWeather(SEED, 'moving')

print(f'单体数 {len(weather.cells)}')
print('场景', weather.scenario)
print()

# Mirror how the planner calls it: bin first, so the cache key repeats.
misses = 0
hits = 0
miss_seconds = 0.0

for departure in range(0, 480, 5):
    for duration in (20, 40, 60):
        for extra in (0, 120):
            start_bin = math.floor(departure / 5)
            end_bin = math.ceil((departure + duration + extra) / 5)
            before = weather._swept_window.cache_info()
            started = time.monotonic()
            weather.envelope(departure, departure + duration + extra)
            elapsed = time.monotonic() - started
            after = weather._swept_window.cache_info()
            if after.misses > before.misses:
                misses += 1
                miss_seconds += elapsed
            else:
                hits += 1

info = weather._swept_window.cache_info()
total = misses + hits
print(f'调用 {total} 次：命中 {hits}（{hits / total * 100:.1f}%），未命中 {misses}')
print(f'未命中总耗时 {miss_seconds:.2f}s，平均每次 {miss_seconds / max(misses, 1) * 1000:.1f}ms')
print(f'lru_cache 统计 {info}')
print(f'单次 miss 成本相对总预算：7760 班 x 1 次调用')

# How many distinct windows does a real plan actually need?
needed = set()
for departure in range(0, 480, 1):
    needed.add((math.floor(departure / 5), math.ceil((departure + 60) / 5)))
print(f'若按分钟枚举，不同窗口数 {len(needed)}')
