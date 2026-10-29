import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402

from weather.geometry import boundary  # noqa: E402

from traffic import cma_tiles, weather_sim  # noqa: E402

f = weather_sim.frame(seed=42, slot='2026-09-18T10:36:00Z')

print('--- echo pixel lon/lat extents per tile ---')
for x, y, rows in f['cells']:
    hits = []
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            if v is not None and v >= cma_tiles.ECHO_FLOOR_DBZ:
                hits.append((c, r))
    if not hits:
        print('tile', x, y, 'no echo')
        continue
    cols = [c for c, _r in hits]
    rws = [r for _c, r in hits]
    lon0, lat0 = cma_tiles.cell_centre_lonlat(x, y, min(cols), max(rws), 3)
    lon1, lat1 = cma_tiles.cell_centre_lonlat(x, y, max(cols), min(rws), 3)
    print('tile (%d,%d) echo %d px  lon[%.3f..%.3f] lat[%.3f..%.3f]'
          % (x, y, len(hits), lon0, lon1, lat0, lat1))

print('--- tile (6,2) full extent ---')
print('tile lon[%.3f..%.3f] lat[%.3f..%.3f]'
      % (cma_tiles.cell_centre_lonlat(6, 2, 0, 0, 3)[0],
         cma_tiles.cell_centre_lonlat(6, 2, 255, 0, 3)[0],
         cma_tiles.cell_centre_lonlat(6, 2, 0, 255, 3)[1],
         cma_tiles.cell_centre_lonlat(6, 2, 0, 0, 3)[1]))

print('--- operating boundary ---')
b = boundary()
print('boundary type', type(b).__name__, 'empty', b.is_empty)
print('boundary bounds', tuple(round(v, 3) for v in b.bounds))
