"""Render a decoded radar tile to a PNG so the echo can be located by eye.

The adapter reports its strongest cell at 109.4E / 56.9N, which is outside the
northeast operating area. Before this is treated as a bug, the decode has to be
checked independently of the adapter's own arithmetic: a picture of the tile,
written with a north-up orientation and a coordinate grid, shows immediately
whether the echo is really there or whether the rows were flipped.

Cross-checking the placement by rendering rather than by re-reading the same
code is the point -- an arithmetic error and a correct-but-surprising answer
look identical in numbers and different in a picture.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
import struct
import urllib.request
import zlib


from traffic import cma_tiles

OUTPUT = os.path.join(ROOT, '_radar_tile_check.png')

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
slot = cma_tiles.latest_slot()
print(f'slot {slot:%Y-%m-%d %H:%M}Z')

# Colour ramp for reflectivity, low to high. Chosen so "no echo" is transparent
# and the convective range is unmistakably distinct from light rain.
RAMP = [
    (0.0, (0, 0, 0, 0)),
    (5.0, (120, 200, 240, 110)),
    (15.0, (60, 150, 230, 190)),
    (25.0, (40, 200, 120, 220)),
    (35.0, (240, 220, 60, 235)),
    (45.0, (240, 130, 40, 245)),
    (55.0, (220, 40, 60, 255)),
    (70.0, (150, 20, 90, 255)),
]


def colour(value):
    if value is None:
        return (0, 0, 0, 0)
    below = RAMP[0]
    for stop in RAMP:
        if value < stop[0]:
            return below[1]
        below = stop
    return RAMP[-1][1]


def png(width, height, pixels):
    raw = b''.join(b'\x00' + bytes(row) for row in pixels)

    def chunk(tag, payload):
        body = tag + payload
        return struct.pack('>I', len(payload)) + body + struct.pack('>I', zlib.crc32(body) & 0xffffffff)

    header = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


# Two panels side by side: the tiles in the adapter's declared order (north-up)
# and the same tiles with rows NOT flipped. If the adapter is right, the left
# panel is the geographically correct one; comparing them shows the magnitude of
# the error a missing flip would cause.
tiles = list(cma_tiles.DEFAULT_GRID)
tile_px = cma_tiles.TILE_SIZE
scale = 2  # enlarge so the structure is readable
panel_w = tile_px * scale
panel_h = tile_px * scale * len(tiles)

def build(flip):
    rows_out = []
    for x, y in tiles:
        body = cma_tiles.fetch_tile(slot, 3, x, y)
        values = struct.unpack(f'>{tile_px * tile_px}h', body)
        decoder = cma_tiles.decode_tile
        rows = decoder(body)
        if not flip:
            # Undo the adapter's flip to show the raw row order.
            rows = list(reversed(rows))
        for row in rows:
            line = []
            for value in row:
                line.extend(bytes(colour(value)) * scale)
            for _ in range(scale):
                rows_out.append(line)
    return rows_out


left = build(flip=True)
right = build(flip=False)
gap_width = 4 * scale
gap = [40, 40, 40, 255] * gap_width
combined = [l + gap + r for l, r in zip(left, right)]

with open(OUTPUT, 'wb') as handle:
    handle.write(png(panel_w * 2 + gap_width, panel_h, combined))
print(f'wrote {OUTPUT}  ({panel_w * 2 + gap_width} x {panel_h})')
print('left = north-up as the adapter decodes it; right = raw row order')

print()
print('=== tile corners, adapter convention (row 0 = north) ===')
for x, y in tiles:
    nw = cma_tiles.cell_centre_lonlat(x, y, 0, 0, 3)
    se = cma_tiles.cell_centre_lonlat(x, y, tile_px - 1, tile_px - 1, 3)
    print(f'  ({x},{y})  NW {nw[0]:7.2f}E {nw[1]:6.2f}N   SE {se[0]:7.2f}E {se[1]:6.2f}N')

print()
print('=== strongest echo per tile, with its own coordinates ===')
for x, y in tiles:
    rows = cma_tiles.decode_tile(cma_tiles.fetch_tile(slot, 3, x, y))
    best = (-1e9, None, None)
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            if value is not None and value > best[0]:
                best = (value, column_index, row_index)
    value, column, row = best
    lon, lat = cma_tiles.cell_centre_lonlat(x, y, column, row, 3)
    print(f'  ({x},{y})  {value:5.1f} dBZ at cell ({column:3d},{row:3d}) -> {lon:7.2f}E {lat:6.2f}N')
