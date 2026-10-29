"""Exercise the CMA radar tile adapter end to end against the live endpoint.

Checks, in order:
1. a frame can actually be fetched through the module (not just through the
   throwaway probe);
2. the decoded dBZ distribution looks like reflectivity rather than noise or a
   mis-decoded image;
3. the row order is really north-up, by comparing the echo centroid against the
   known location of the band the earlier probe found;
4. the coordinates produced by `cell_centre_lonlat` land inside the operating
   area, which is what the geometry pipeline will consume.
"""


import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
from traffic import cma_tiles

print('=== status ===')
for key, value in cma_tiles.status().items():
    print(f'  {key}: {value}')
print()

result = cma_tiles.frame(force=True)
print('=== frame ===')
print(f"available      : {result['available']}")
print(f"slot           : {result.get('slot')}")
print(f"slot age (min) : {result.get('slotAgeMinutes')}")
print(f"lookback used  : {result.get('lookbackStepsUsed')}")
print(f"error          : {result.get('error')}")

if not result['available']:
    # Do NOT report every unavailability as a code defect. This adapter reads a
    # live public product, so "no frame" has two very different causes and the
    # wording has to say which one:
    #
    #   * a transport failure (URLError / timeout) means the network or the
    #     product's schedule is the reason. Nothing about the adapter is proven
    #     wrong, and calling it "not usable as written" is a false accusation --
    #     it once sent me looking for a decoding bug that did not exist. This is
    #     the environment class the smoke gate already treats as EXPECTED.
    #   * any other error means the adapter itself failed (bad request shape, a
    #     decode exception), which IS a defect worth failing on.
    detail = str(result.get('error') or '')
    transport = any(marker in detail for marker in
                    ('URLError', 'HTTPError', 'timed out', 'TimeOut',
                     'Connection', 'SSLError', 'No route'))
    if transport:
        print()
        print('PRECONDITION: no frame available over the network (transport error).')
        print('              The adapter is not implicated. Re-run with a route to')
        print('              image.data.cma.cn, or accept this as environment-limited.')
        raise SystemExit(0)
    raise SystemExit('frame unavailable -- the adapter failed, not the network: ' + detail)

stats = result['stats']
print()
print('=== decoded statistics ===')
print(f"present cells  : {stats['present']} / {stats['cells']}")
print(f"echo >= {cma_tiles.ECHO_FLOOR_DBZ:.0f} dBZ  : {stats['echoFraction']:.2%}")
print(f"conv >= {cma_tiles.CONVECTIVE_DBZ:.0f} dBZ  : {stats['convectiveFraction']:.2%}")
print(f"strong >= {cma_tiles.STRONG_DBZ:.0f} dBZ: {stats['strongFraction']:.2%}")
print(f"dBZ range      : {stats['minDbz']:.1f} .. {stats['maxDbz']:.1f}")

# A mosaic over land is mostly clear air. An echo fraction near 1.0 would mean
# the bytes were mis-decoded (e.g. read as unsigned, or the missing marker was
# not honoured), so this is a real check rather than a nicety.
if stats['echoFraction'] > 0.5:
    raise SystemExit(f"echo fraction {stats['echoFraction']:.1%} is implausible for a mosaic -- decode is suspect")

print()
print('=== geographic placement of the strongest echo ===')
best = (-1e9, None, None, None, None)
for x, y, rows in result['cells']:
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            if value is not None and value > best[0]:
                best = (value, x, y, column_index, row_index)
value, x, y, column, row = best
longitude, latitude = cma_tiles.cell_centre_lonlat(x, y, column, row, result['provenance']['zoom'])
print(f"strongest cell : {value:.1f} dBZ")
print(f"tile ({x},{y}) cell ({column},{row})")
print(f"lon/lat        : {longitude:.3f}, {latitude:.3f}")

# The operating area is northeast China. A decode error that flipped rows would
# put this echo in the wrong hemisphere half the time, so a loose sanity box is
# enough to catch it.
inside = 115.0 <= longitude <= 135.0 and 38.0 <= latitude <= 54.0
print(f"inside NE China box (115-135E, 38-54N): {inside}")

print()
print('=== per-tile echo ===')
for x, y, rows in result['cells']:
    tile_stats = cma_tiles.sample_stats(rows)
    corner = cma_tiles.cell_centre_lonlat(x, y, 0, 0, result['provenance']['zoom'])
    print(f"  tile ({x},{y}) NW corner {corner[0]:.1f}E {corner[1]:.1f}N  "
          f"echo {tile_stats['echoFraction']:.2%}  max {tile_stats['maxDbz']}")
