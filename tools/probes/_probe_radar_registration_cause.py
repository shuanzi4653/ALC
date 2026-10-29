"""Isolate the registration error by reading back the exact cells the outline claims.

Two symptoms point at one cause:
  * 187 cells are >= 35 dBZ in the raw tile, but the derivation reports CONVECTIVE
    and STRONG empty;
  * boundary points of the drawn stratiform outline read back as no-echo.

Both are consistent with the quad being built at the wrong raster coordinates, so
this walks a single known strong cell end to end and prints every intermediate:
its dBZ, its declared lon/lat, its projected metres, and the raster coordinate
that lon/lat maps back to.
"""
import math
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'backend-python'))
from _repo import ROOT  # noqa: E402

from weather.geometry import project, unproject  # noqa: E402
from traffic import cma_tiles, radar_field  # noqa: E402

frame = cma_tiles.frame(force=True)
if not frame.get('available'):
    raise SystemExit('no frame: ' + str(frame.get('error')))
zoom = frame['provenance']['zoom']
print('slot', frame['slot'], 'zoom', zoom)
print()

# --- find the strongest cell and follow it through every step ---
best = None
for x, y, rows in frame['cells']:
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            if value is not None and (best is None or value > best[0]):
                best = (value, x, y, c, r)
value, x, y, column, row = best
print('=== the strongest cell ===')
print('  %.1f dBZ at tile (%d,%d) raster (column=%d, row=%d)' % (value, x, y, column, row))
print('  band_of says:', radar_field.band_of(value))

centre = cma_tiles.cell_centre_lonlat(x, y, column, row, zoom)
print('  cell_centre_lonlat -> %.4fE %.4fN' % centre)
print('  project()          -> %s' % (project(centre),))
print('  unproject(project) -> %.4fE %.4fN' % tuple(unproject(project(centre))))
print()

# --- now the quad the derivation would build for that same cell ---
print('=== the quad built for that cell ===')
quad = radar_field.cell_quad(x, y, column, row, zoom)
for point in quad:
    print('   lonlat %.4fE %.4fN' % point)
projected = [project(point) for point in quad]
print('  projected metres:')
for point in projected[:4]:
    print('   %.0fE %.0fN' % point)
corners_x = [p[0] for p in projected[:4]]
corners_y = [p[1] for p in projected[:4]]
print('  quad span: %.0f m x %.0f m' % (max(corners_x) - min(corners_x),
                                         max(corners_y) - min(corners_y)))
print()

# --- invert the tile maths independently to see whether row 0 is north ---
print('=== independent tile-maths check ===')
for label, (cc, rr) in (('north edge (row 0)', (128, 0)),
                        ('south edge (row 255)', (128, 255))):
    lon, lat = cma_tiles.cell_centre_lonlat(x, y, cc, rr, zoom)
    print('  %-22s %.4fE %.4fN' % (label, lon, lat))
print()

# --- what fraction of the tile is >= 35 dBZ, and where is it concentrated? ---
print('=== where the strong echo sits in raster coordinates ===')
rows_of_interest = []
for xx, yy, rows in frame['cells']:
    heavy = [(r, c) for r, rr in enumerate(rows) for c, v in enumerate(rr)
             if v is not None and v >= cma_tiles.CONVECTIVE_DBZ]
    if not heavy:
        continue
    r_min = min(v[0] for v in heavy)
    r_max = max(v[0] for v in heavy)
    c_min = min(v[1] for v in heavy)
    c_max = max(v[1] for v in heavy)
    print('  tile (%d,%d): %d cells >=35 dBZ, rows %d-%d, columns %d-%d'
          % (xx, yy, len(heavy), r_min, r_max, c_min, c_max))
    lon_min, lat_max = cma_tiles.cell_centre_lonlat(xx, yy, c_min, r_min, zoom)
    lon_max, lat_min = cma_tiles.cell_centre_lonlat(xx, yy, c_max, r_max, zoom)
    print('    -> lon/lat box %.2fE-%.2fE  %.2fN-%.2fN'
          % (lon_min, lon_max, lat_min, lat_max))
    # does that lon/lat box intersect the operating boundary?
    from weather.geometry import boundary
    from shapely.geometry import box as sbox
    probe = sbox(lon_min, lat_min, lon_max, lat_max)
    print('    boundary bounds:', tuple(round(v, 1) for v in boundary().bounds))
    print('    does the strong-echo lonlat box overlap the network area?',
          probe.intersects(boundary().bounds and sbox(*boundary().bounds)) if False else 'see projected test below')
    from shapely.geometry import Polygon
    projected_box = Polygon([project((lon_min, lat_min)), project((lon_max, lat_min)),
                             project((lon_max, lat_max)), project((lon_min, lat_max))])
    print('    does its *projected* box intersect the boundary?',
          projected_box.intersects(boundary()))
    print('    projected box bounds: %s' % (tuple(round(v / 1000) for v in projected_box.bounds),), 'km')
