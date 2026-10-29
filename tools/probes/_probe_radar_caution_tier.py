"""When a STRONG echo is present, what happens to the caution tier?

`shield()` sets `outer = field if field else strong`, `core = strong.buffer(...)`,
then returns `outer.difference(core)`. If the frame's only echo is STRONG, then
`field` (CONVECTIVE) is empty, so `outer = strong`, and subtracting a grown copy
of `strong` from `strong` leaves nothing -- the caution tier is empty *by
construction*, not by accident.

That is worth measuring rather than reasoning about: it decides whether a
STRONG-only convective cell can be drawn as a two-tier hazard at all, and the
payload test just asserted the opposite.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shapely.geometry import GeometryCollection  # noqa: E402
from traffic import cma_tiles, radar_field  # noqa: E402

ZOOM = 3
INSIDE_CELLS = ((254, 169), (251, 169), (249, 168), (254, 172))
KINDS = {50.0: 'STRONG-only (>=45)', 40.0: 'CONVECTIVE-only (35-45)', 20.0: 'STRATIFORM-only (15-35)'}


def frame(entries):
    rows = [[None] * cma_tiles.TILE_SIZE for _ in range(cma_tiles.TILE_SIZE)]
    for row, column, value in entries:
        rows[row][column] = value
    return {'available': True, 'error': None, 'slot': 'x', 'slotAgeMinutes': 1.0,
            'provenance': {'provider': 'CMA_DATA_NET', 'zoom': ZOOM}, 'cells': [(6, 2, rows)]}


def area(g):
    return 0.0 if g is None or g.is_empty else g.area / 1e6


for value, label in KINDS.items():
    entries = [(INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], value),
               (INSIDE_CELLS[3][0], INSIDE_CELLS[3][1], value)]
    derived = radar_field.derive(frame(entries))
    field, core, caution, watch = radar_field.shield(derived)
    print(f'{label}')
    print(f'   bands   field={area(field):.1f}km2 core={area(core):.1f}km2 '
          f'caution={area(caution):.1f}km2 watch={area(watch):.1f}km2')
    print(f'   empty?  field={field.is_empty} core={core.is_empty} '
          f'caution={caution.is_empty} watch={watch.is_empty}')

# Mixed: a CONVECTIVE ring around a STRONG core is the case the two-tier render
# was designed for. Build it as two separate cells so both bands exist.
mixed = [(INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 50.0),
         (INSIDE_CELLS[0][0], INSIDE_CELLS[0][1] + 1, 50.0),
         (INSIDE_CELLS[0][0], INSIDE_CELLS[0][1] + 2, 40.0),
         (INSIDE_CELLS[0][0] + 1, INSIDE_CELLS[0][1], 40.0),
         (INSIDE_CELLS[0][0] + 1, INSIDE_CELLS[0][1] + 1, 40.0),
         (INSIDE_CELLS[0][0] + 1, INSIDE_CELLS[0][1] + 2, 40.0)]
derived = radar_field.derive(frame(mixed))
field, core, caution, watch = radar_field.shield(derived)
print('mixed CONVECTIVE ring + STRONG core')
print(f'   bands   field={area(field):.1f}km2 core={area(core):.1f}km2 '
      f'caution={area(caution):.1f}km2 watch={area(watch):.1f}km2')
print(f'   empty?  field={field.is_empty} core={core.is_empty} '
      f'caution={caution.is_empty} watch={watch.is_empty}')
