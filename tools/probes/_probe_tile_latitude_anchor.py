"""Pin down the tile's latitude mapping using the radar network's own edge.

The missing fraction inside tile (6,3) reaches 100% well before the tile's
southern edge. That boundary is not arbitrary: it is the southern limit of the
radar network's data availability for this product. Reading the boundary's
latitude off the coordinate function and comparing it against the geography it
must correspond to is a check on the whole (zoom, tile, row) -> latitude chain,
independent of any assumption about where the weather should be.

The tile also reports how many columns are populated in its populated rows. If
the coordinate function were wrong about *longitude* the populated span would
not sit over land at the constant longitudes the function claims.

Outputs the raw row indices of the transitions, not just the derived latitudes,
so the arithmetic can be checked against a stated row number.
"""


import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
from traffic import cma_tiles

slot = cma_tiles.latest_slot()
print(f'slot {slot:%Y-%m-%d %H:%M}Z')
print()

x, y = 6, 3
rows = cma_tiles.decode_tile(cma_tiles.fetch_tile(slot, 3, x, y))
print(f'tile ({x},{y}): row 0 -> {cma_tiles.cell_centre_lonlat(x, y, 0, 0, 3)[1]:.2f}N, '
      f'row 255 -> {cma_tiles.cell_centre_lonlat(x, y, 0, 255, 3)[1]:.2f}N')
print()

print('row-by-row: populated count and north-edge latitude (every 8th row)')
last_populated = None
for index in range(0, 256, 8):
    row = rows[index]
    populated = sum(1 for value in row if value is not None)
    latitude = cma_tiles.cell_centre_lonlat(x, y, 0, index, 3)[1]
    if populated:
        last_populated = index
    print(f'  row {index:3d}  {latitude:6.2f}N  populated {populated:3d}/256')

print()
print('scanning every row for the southern-most populated row')
deepest = max((index for index in range(256)
               if any(value is not None for value in rows[index])), default=None)
print(f'southern-most populated row index = {deepest}')
if deepest is not None:
    print(f'  -> latitude {cma_tiles.cell_centre_lonlat(x, y, 0, deepest, 3)[1]:.2f}N')

print()
print('=== columns populated, by longitude, over the populated rows ===')
for index in range(0, 256, 16):
    row = rows[index]
    columns = [position for position, value in enumerate(row) if value is not None]
    if not columns:
        continue
    west = cma_tiles.cell_centre_lonlat(x, y, min(columns), index, 3)[0]
    east = cma_tiles.cell_centre_lonlat(x, y, max(columns), index, 3)[0]
    latitude = cma_tiles.cell_centre_lonlat(x, y, 0, index, 3)[1]
    print(f'  row {index:3d}  {latitude:6.2f}N  populated cols {min(columns):3d}-{max(columns):3d}  '
          f'-> lon {west:7.2f}E .. {east:7.2f}E  ({len(columns)} cols)')
