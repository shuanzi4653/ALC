"""Map which zoom-3 radar tiles actually exist at the newest published slot.

The default grid was guessed and two of its four tiles 404'd. Rather than guess
again, scan the tile space around China at zoom 3 and print every coordinate
that returns a tile, with its echo fraction. What exists is a fact about the
product's coverage, and the operating area has to live inside it.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
import datetime as dt
import urllib.error
import urllib.request


from traffic import cma_tiles

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

slot = cma_tiles.latest_slot()
print(f'probing slot {slot:%Y-%m-%d %H:%M}Z')
print()

found = []
for zoom in (2, 3, 4):
    span = 2 ** zoom
    print(f'=== zoom {zoom} (grid {span}x{span}) ===')
    for y in range(span):
        row = []
        for x in range(span):
            url = cma_tiles.tile_url(slot, zoom, x, y)
            request = urllib.request.Request(url, headers={'User-Agent': 'ALC-scan/1.0'})
            try:
                with OPENER.open(request, timeout=12) as response:
                    body = response.read()
                rows = cma_tiles.decode_tile(body)
                stats = cma_tiles.sample_stats(rows)
                nw = cma_tiles.cell_centre_lonlat(x, y, 0, 0, zoom)
                se = cma_tiles.cell_centre_lonlat(x, y, 255, 255, zoom)
                found.append((zoom, x, y, stats, nw, se))
                row.append(f'({x},{y}) {stats["echoFraction"]:>6.2%}')
            except Exception as error:  # noqa: BLE001
                row.append(f'({x},{y})  --   ')
        print('   ' + '  '.join(row))
    print()

print('=== 存在的瓦片与其地理范围 ===')
for zoom, x, y, stats, nw, se in found:
    print(f'zoom {zoom} tile ({x},{y}): '
          f'NW {nw[0]:7.2f}E {nw[1]:6.2f}N   SE {se[0]:7.2f}E {se[1]:6.2f}N   '
          f'echo {stats["echoFraction"]:6.2%}  max {stats["maxDbz"]}')
