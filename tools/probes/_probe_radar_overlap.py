"""Measure how much of the strong echo is genuinely inside the operating boundary.

The derivation reported CONVECTIVE/STRONG empty while 187 cells read >= 35 dBZ.
The suspicion is that those cells are real but outside the network, and the clip
is doing its job. That is testable rather than arguable: classify the raster,
project every cell individually, and count how many land inside the boundary --
then compare against what the component pass produced.

If the counts agree, the clip is correct and nothing is broken.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'backend-python'))
from _repo import ROOT  # noqa: E402

from weather.geometry import boundary, project  # noqa: E402
from traffic import cma_tiles, radar_field  # noqa: E402

frame = cma_tiles.frame(force=True)
if not frame.get('available'):
    raise SystemExit('no frame: ' + str(frame.get('error')))
zoom = frame['provenance']['zoom']
mask = boundary()
print('slot', frame['slot'], 'boundary bounds km',
      tuple(round(v / 1000) for v in mask.bounds))
print()

# --- classify every cell individually and ask the boundary about each one ---
per_band = {}
inside_band = {}
for x, y, rows in frame['cells']:
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            band = radar_field.band_of(value)
            if band is None:
                continue
            per_band[band] = per_band.get(band, 0) + 1
            quad = radar_field.cell_quad(x, y, column_index, row_index, zoom)
            polygon = radar_field._quad_metres(quad)
            if polygon.intersects(mask):
                inside_band[band] = inside_band.get(band, 0) + 1

print('=== cells by band, and how many touch the operating boundary ===')
for band in radar_field.BAND_ORDER:
    print('  %-11s total %6d   touching boundary %6d' %
          (band, per_band.get(band, 0), inside_band.get(band, 0)))
print()

# --- and what the full derivation produced, for comparison ---
derived = radar_field.derive(frame)
print('=== what derive() produced, and the raw overlap area ===')
for band in radar_field.BAND_ORDER:
    row = derived['bands'][band]
    print('  %-11s components %3d   area %8.1f km2   cells %6d'
          % (band, row['components'], row['areaM2'] / 1e6, row['cells']))

# --- the direct test: union every in-boundary CONVECTIVE cell and measure it ---
print()
print('=== independent union of in-boundary CONVECTIVE cells ===')
from shapely.ops import unary_union  # noqa: E402
quads = []
for x, y, rows in frame['cells']:
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            if radar_field.band_of(value) != 'CONVECTIVE':
                continue
            polygon = radar_field._quad_metres(
                radar_field.cell_quad(x, y, column_index, row_index, zoom))
            if polygon.intersects(mask):
                quads.append(polygon)
if not quads:
    print('  no in-boundary CONVECTIVE cells at all')
else:
    merged = unary_union(quads).intersection(mask)
    print('  %d quads -> %.1f km2 inside the boundary' % (len(quads), merged.area / 1e6))
    print('  parts:', radar_field._polygon_parts(merged))
    print('  floor is %d cell(s) of membership, not an area'
          % radar_field.MIN_COMPONENT_CELLS)
    print('  -> %d cells, so it %s survive'
          % (len(quads), 'should' if len(quads) >= radar_field.MIN_COMPONENT_CELLS
             else 'should not'))

# --- the same for STRATIFORM, which did survive ---
print()
print('=== independent union of in-boundary STRATIFORM cells ===')
quads = []
for x, y, rows in frame['cells']:
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            if radar_field.band_of(value) != 'STRATIFORM':
                continue
            polygon = radar_field._quad_metres(
                radar_field.cell_quad(x, y, column_index, row_index, zoom))
            if polygon.intersects(mask):
                quads.append(polygon)
merged = unary_union(quads).intersection(mask) if quads else None
if merged is None:
    print('  none')
else:
    print('  %d quads -> %.1f km2 inside the boundary, parts %d'
          % (len(quads), merged.area / 1e6, radar_field._polygon_parts(merged)))
