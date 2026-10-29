"""Pin down exactly which term of `cell_centre_lonlat` is wrong.

The function claims to return the lon/lat of a cell inside tile (x, y) at a given
zoom. The independent check is the one the docstrings themselves state: at zoom 3
one tile spans 360 / 2**3 = 45 degrees, so tile (6,2)'s box must be
90.09E-134.91E / 66.48N-41.05N.

This evaluates the function's own arithmetic term by term and compares against
that stated box, so the defect is named rather than inferred.
"""
import math
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'backend-python'))
from _repo import ROOT  # noqa: E402

from traffic import cma_tiles  # noqa: E402

SIZE = cma_tiles.TILE_SIZE
ZOOM = 3


def claimed(tile_x, tile_y, column, row):
    """The implementation as written."""
    return cma_tiles.cell_centre_lonlat(tile_x, tile_y, column, row, ZOOM)


def correct(tile_x, tile_y, column, row):
    """The standard slippy-map formula, spelled out in full.

    world coordinate in units of tiles:
        world_x = (tile_x + column / SIZE) / 2**zoom
        world_y = (tile_y + row    / SIZE) / 2**zoom
    longitude = world_x * 360 - 180
    latitude  = atan(sinh(pi - 2*pi*world_y))
    """
    scale = 2 ** ZOOM
    world_x = (tile_x + (column + 0.5) / SIZE) / scale
    world_y = (tile_y + (row + 0.5) / SIZE) / scale
    longitude = world_x * 360.0 - 180.0
    latitude = math.degrees(math.atan(math.sinh(math.pi - 2.0 * math.pi * world_y)))
    return longitude, latitude


print('claimed degree-per-cell:', cma_tiles.tile_degrees_per_cell(ZOOM))
print('correct degree-per-cell: %.4f' % (360.0 / (SIZE * 2 ** ZOOM)))
print()

for tile in ((6, 2), (6, 3)):
    print('=== tile %s ===' % (tile,))
    for label, (column, row) in (('NW corner cell', (0, 0)),
                                 ('centre cell', (128, 128)),
                                 ('SE corner cell', (255, 255))):
        got = claimed(*tile, column, row)
        want = correct(*tile, column, row)
        print('  %-16s claimed %8.3fE %7.3fN   correct %8.3fE %7.3fN   dlon %7.3f dlat %7.3f'
              % (label, got[0], got[1], want[0], want[1],
                 got[0] - want[0], got[1] - want[1]))
    nw = correct(*tile, 0, 0)
    se = correct(*tile, 255, 255)
    print('  correct box: %.2fE-%.2fE  %.2fN-%.2fN' % (nw[0], se[0], se[1], nw[1]))
    print()

print('=== what the implementation is actually computing ===')
print('the claimed code path, expanded:')
for tile in ((6, 2),):
    x, y = tile
    scale = 2 ** ZOOM
    for column, row in ((0, 0), (255, 255)):
        world_x = (x + (column + 0.5) / SIZE) / scale
        world_y = (y + (row + 0.5) / SIZE) / scale
        print('  raw world_x=%.6f world_y=%.6f' % (world_x, world_y))
        print('    x*360-180          = %.3fE' % (world_x * 360.0 - 180.0))
        print('    atan(sinh(pi-2pi*wy)) = %.3fN'
              % math.degrees(math.atan(math.sinh(math.pi - 2 * math.pi * world_y))))
        n = math.pi - 2.0 * math.pi * world_y
        print('    the variant with n un-negated: %.3fN'
              % math.degrees(math.atan(math.sinh(n))))
    break
