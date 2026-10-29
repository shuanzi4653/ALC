"""Verify the radar raster->metre registration lands where the raw geometry says.

The band once shipped with a hand-written metre polygon that had never been
through `weather.geometry.project`; it sat ~4300 km north, clipped to an empty
field, and was *valid*, so nothing complained. Raster-to-polygon has the same
failure mode available: a quadrant mistake or a missing row flip lands the echo
in the right shape at the wrong place.

So this does not re-run the same arithmetic. It takes the derivation's polygon,
converts it back to lon/lat, and compares it against the lon/lat of the dBZ cells
that produced it -- computed independently from the decoded tile. Two independent
routes to the same answer, or one of them is wrong.
"""
import math
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'backend-python'))
from _repo import ROOT  # noqa: E402

from shapely.geometry import Point  # noqa: E402
from shapely.ops import transform as shapely_transform  # noqa: E402
from weather.geometry import unproject, boundary  # noqa: E402
from traffic import cma_tiles, radar_field  # noqa: E402


def to_lonlat(geometry):
    """`weather.geometry.unproject` takes one point tuple, not x and y."""
    return shapely_transform(lambda x, y, z=None: unproject((x, y)), geometry)


frame = cma_tiles.frame()
print('frame available', frame.get('available'), 'slot', frame.get('slot'))
if not frame.get('available'):
    raise SystemExit('no frame: ' + str(frame.get('error')))

# --- route 1: what the derivation produced, back in lon/lat ---
derived = radar_field.derive(frame, minute=0)
convective = derived['bands']['CONVECTIVE']['geometry']
stratiform = derived['bands']['STRATIFORM']['geometry']
print()
print('=== route 1: derived geometry unprojected to lon/lat ===')
for name, geom in (('STRATIFORM', stratiform), ('CONVECTIVE', convective),
                   ('STRONG', derived['bands']['STRONG']['geometry'])):
    if geom.is_empty:
        print('  %-11s empty' % name)
        continue
    latlon = to_lonlat(geom)
    minx, miny, maxx, maxy = latlon.bounds
    parts = radar_field._polygon_parts(latlon)
    print('  %-11s %7.1f km2  parts=%-3d box %.2fE-%.2fE  %.2fN-%.2fN'
          % (name, geom.area / 1e6, parts, minx, maxx, miny, maxy))

# --- route 2: where the raw dBZ cells actually are ---
print()
print('=== route 2: raw dBZ cells >= convective, located independently ===')
hits = []
for x, y, rows in frame['cells']:
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            if value is not None and value >= cma_tiles.CONVECTIVE_DBZ:
                hits.append((value, x, y, c, r))
print('  raw cells >= %.0f dBZ: %d' % (cma_tiles.CONVECTIVE_DBZ, len(hits)))
if hits:
    print('  strongest %.1f dBZ at tile (%d,%d) cell (%d,%d)'
          % (max(hits)[0], max(hits)[1], max(hits)[2], max(hits)[3], max(hits)[4]))
else:
    print('  (none this minute -- stratiform-only sky, nothing for routing to avoid)')

# --- the check that matters: every derived polygon centre must fall on echo ---
print()
print('=== cross-check: derived polygon interior vs the classified raster ===')
test = stratiform if not stratiform.is_empty else convective
if test.is_empty:
    print('  no derived geometry to check')
else:
    latlon = to_lonlat(test)
    inside = 0
    total = 0
    samples = []
    for polygon in getattr(latlon, 'geoms', [latlon]):
        if polygon.is_empty:
            continue
        for fraction in (0.25, 0.5, 0.75):
            total += 1
            # walk the boundary rather than the centroid: a centroid can sit in a
            # hole, and a hole is legitimately echo-free
            point = polygon.exterior.interpolate(fraction, normalized=True)
            lon, lat = point.x, point.y
            cell = cma_tiles.cell_centre_lonlat
            best = None
            for x, y, rows in frame['cells']:
                nw = cell(x, y, 0, 0, 3)
                se = cell(x, y, cma_tiles.TILE_SIZE - 1, cma_tiles.TILE_SIZE - 1, 3)
                if se[0] <= lon <= nw[0] and se[1] <= lat <= nw[1]:
                    # invert the mercator mapping to a fractional cell
                    scale = 2 ** 3
                    world_x = (lon + 180.0) / 360.0 * scale
                    world_y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * scale
                    column = (world_x - x) * cma_tiles.TILE_SIZE
                    row = (world_y - y) * cma_tiles.TILE_SIZE
                    ci, ri = int(column), int(row)
                    if 0 <= ri < cma_tiles.TILE_SIZE and 0 <= ci < cma_tiles.TILE_SIZE:
                        value = rows[ri][ci]
                        best = (value, radar_field.band_of(value))
                    break
            if best is not None:
                value, band = best
                if band is not None:
                    inside += 1
                samples.append((round(lon, 2), round(lat, 2), value, band))
    print('  sampled boundary points: %d, on-echo %d (%.0f%%)'
          % (total, inside, 100.0 * inside / total if total else 0.0))
    for row in samples[:8]:
        print('    %.2fE %.2fN  %s dBZ -> %s' % (row[0], row[1], row[2], row[3]))

# --- and the boundary must actually contain it ---
print()
print('=== containment: derived geometry inside the operating boundary ===')
mask = boundary()
for name, geom in (('STRATIFORM', stratiform), ('CONVECTIVE', convective)):
    if geom.is_empty:
        print('  %-11s empty' % name)
        continue
    outside = geom.difference(mask.buffer(1.0)).area
    print('  %-11s outside boundary: %.1f m2' % (name, outside))
