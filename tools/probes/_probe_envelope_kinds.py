"""Split the envelope miss cost by cell kind: point cells vs the band.

The cache hits 59.8% in ordered use, so misses dominate: ~194-588 misses at a
measured 77-110 ms each. That is the whole plan budget. But the 21 cells are not
alike. A point cell sweeps by buffering a short centre track; the band sweeps by
hulling 64 outline vertices across every drift offset, which is a different order
of work. If one kind dominates, that is what has to change.

This times a single miss for each kind on the same window, so the fix can be
aimed rather than guessed.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND  # noqa: E402
import time
from pathlib import Path


from traffic.weather import NetworkWeather  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


weather = NetworkWeather(4242, 'moving')
kinds = {}
for index, cell in enumerate(weather.cells):
    kinds.setdefault(cell['shape'], []).append(index)
print('单体构成:', {shape: len(rows) for shape, rows in kinds.items()})
print()

WINDOW = (20, 40)  # a 21-tick window, typical of what the planner asks for

for shape, indices in kinds.items():
    index = indices[0]
    cell = weather.cells[index]
    started = time.monotonic()
    try:
        shapes = []
        if cell['shape'] == 'BAND':
            weather._swept_band(index, *WINDOW)
        else:
            centres = [weather.centre_at(cell, tick * 5) for tick in range(WINDOW[0], WINDOW[1] + 1)]
            for probe in centres:
                pass
        elapsed = time.monotonic() - started
        print(f'{shape:<8} 单体#{index} 单次 {elapsed * 1000:8.2f}ms')
    except Exception as error:  # noqa: BLE001
        print(f'{shape:<8} 单体#{index} 失败 {type(error).__name__}: {error}')

print()
print('=== 整窗 miss（全部 21 个体，含 unary_union） ===')
for attempt in range(3):
    fresh = NetworkWeather(4242, 'moving')
    started = time.monotonic()
    fresh._swept_window(*WINDOW)
    print(f'  第 {attempt + 1} 次整窗 miss: {(time.monotonic() - started) * 1000:.1f}ms')

print()
print('=== 仅雨带 vs 仅点单体 ===')
fresh = NetworkWeather(4242, 'moving')


def timed(label, func):
    started = time.monotonic()
    func()
    print(f'  {label}: {(time.monotonic() - started) * 1000:.1f}ms')


band_index = next(index for index, cell in enumerate(fresh.cells) if cell['shape'] == 'BAND')
timed('仅雨带 _swept_band', lambda: fresh._swept_band(band_index, *WINDOW))
