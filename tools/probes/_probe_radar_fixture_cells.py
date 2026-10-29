"""Find raster coordinates whose cells land inside the operating boundary.

The unit fixtures need cells that survive the clip, and guessing raster rows and
columns puts them over Russia. This inverts the mapping instead: walk the
network's own projected bounding box, project sample points, and report which
tile/row/column each one corresponds to.

Printing this list is the point -- the numbers go straight into the test fixtures
so a fixture coordinate is a measured fact rather than a guess that happens to
pass.
"""
import math
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'backend-python'))
from _repo import ROOT  # noqa: E402

from weather.geometry import boundary, unproject  # noqa: E402
from traffic import cma_tiles  # noqa: E402

ZOOM = 3
SIZE = cma_tiles.TILE_SIZE
mask = boundary()
print('boundary bounds km', tuple(round(v / 1000) for v in mask.bounds))
print()


def raster_of(lon, lat):
    """Invert the slippy-map formula: lon/lat -> (tile_x, tile_y, column, row)."""
    scale = 2 ** ZOOM
    world_x = (lon + 180.0) / 360.0 * scale
    world_y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * scale
    tile_x = int(math.floor(world_x))
    tile_y = int(math.floor(world_y))
    column = int((world_x - tile_x) * SIZE)
    row = int((world_y - tile_y) * SIZE)
    return tile_x, tile_y, column, row


# Sample the network's interior on a grid in projected metres, keep the points
# that are comfortably inside the boundary, and report their raster coordinates.
minx, miny, maxx, maxy = mask.bounds
found = {}
step = 40000
for x in range(int(minx), int(maxx) + 1, step):
    for y in range(int(miny), int(maxy) + 1, step):
        from shapely.geometry import Point
        if not mask.buffer(-20000).covers(Point(x, y)):
            continue  # keep a margin so a cell's quad is fully inside
        lon, lat = unproject((x, y))
        tile = raster_of(lon, lat)
        found.setdefault(tile[:2], []).append((tile[2], tile[3], round(lon, 2), round(lat, 2)))

for tile in sorted(found):
    rows = found[tile]
    print('tile %s: %d interior sample cells' % (tile, len(rows)))
    for column, row, lon, lat in rows[:6]:
        print('   column=%-4d row=%-4d  %.2fE %.2fN' % (column, row, lon, lat))
    print()

# A compact triple that is adjacent, so a test can build a 1x1, 2x2 or line.
print('=== a contiguous block, for fixtures ===')
if (6, 2) in found:
    rows = sorted(found[(6, 2)])
    # take a run of four adjacent columns in the same row
    best = None
    for index in range(len(rows) - 3):
        window = rows[index:index + 4]
        if all(window[i][0] + 1 == window[i + 1][0] and window[i][1] == window[i + 1][1]
               for i in range(3)):
            best = window
            break
    if best:
        for column, row, lon, lat in best:
            print('   column=%-4d row=%-4d  %.2fE %.2fN' % (column, row, lon, lat))
    else:
        print('   no four-in-a-row found at this step; loosen the step')
