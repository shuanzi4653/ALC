"""Locate the tile's true orientation using the missing-data pattern.

The two candidate row orders are mirror images of each other (verified by
rendering), so the decide question is which end is north. The tile itself
carries the answer, because the national radar mosaic has a strongly asymmetric
coverage pattern across this tile: it spans 90-135E and 0-66N, which includes
the South China Sea and the tropical belt at the bottom and sparsely-radared
Siberia at the top. If the data is being read the right way up, the fraction of
missing cells should NOT be symmetric between the top and bottom halves.

A cleaner signal is the echo's latitude. Convection in September over this
longitude band is a mid-latitude phenomenon; if the echo sits at 57N that is
late-season Siberia, and if it sits at 51N that is Mongolia -- both possible, so
latitude alone cannot decide it. The missing-data gradient can: the mosaic's
radar network thins out sharply toward the pole and toward the open ocean.

This prints the row-by-row missing fraction and the echo-weighted latitude under
both readings, so the choice rests on the data's own structure.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
import struct


from traffic import cma_tiles

slot = cma_tiles.latest_slot()
print(f'slot {slot:%Y-%m-%d %H:%M}Z')
print()

for x, y in cma_tiles.DEFAULT_GRID:
    body = cma_tiles.fetch_tile(slot, 3, x, y)
    rows_north_up = cma_tiles.decode_tile(body)
    rows_raw = list(reversed(rows_north_up))

    nw = cma_tiles.cell_centre_lonlat(x, y, 0, 0, 3)
    se = cma_tiles.cell_centre_lonlat(x, y, 255, 255, 3)
    print(f'=== tile ({x},{y})  NW {nw[0]:.2f}E {nw[1]:.2f}N   SE {se[0]:.2f}E {se[1]:.2f}N ===')

    def profile(rows, label):
        bands = []
        for band in range(8):
            start = band * 32
            chunk = [value for row in rows[start:start + 32] for value in row]
            missing = sum(1 for value in chunk if value is None)
            echo = sum(1 for value in chunk if value is not None and value >= 15.0)
            latitude = cma_tiles.cell_centre_lonlat(x, y, 0, start + 16, 3)[1]
            bands.append((latitude, missing / len(chunk), echo / len(chunk)))
        print(f'  -- {label} --')
        for latitude, miss, echo in bands:
            print(f'     {latitude:6.2f}N  missing {miss:6.2%}  echo {echo:6.3%}')

    profile(rows_north_up, 'north-up (adapter convention)')
    profile(rows_raw, 'raw row order (mirrored)')
    print()

print('判据：全国雷达拼图的缺测率在低纬海区与高纬稀疏区都偏高；')
print('若某一读法让「缺测率高的带」集中在一端而回波带与之分离，则该读法自洽。')
