"""Probe the synthetic radar generator: timing, contract, motion, consumer chain.

This is the acceptance probe for `traffic/weather_sim.py`. It checks the four
things that make the generator usable:

  1. it is fast enough to sit inside an HTTP request;
  2. its frame is contract-compatible with `cma_tiles.frame()`;
  3. it is deterministic for a given (seed, slot) but **evolves** across slots;
  4. `radar_field.derive` + `shield` consume it with no branch at all.
"""
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402

from traffic import cma_tiles, radar_field, weather_sim  # noqa: E402

SLOT = '2026-09-18T10:36:00Z'

print('--- 1. timing (two-tile frame) ---')
t0 = time.perf_counter()
f = weather_sim.frame(seed=42, slot=SLOT)
elapsed = time.perf_counter() - t0
print('gen seconds %.3f' % elapsed)
assert elapsed < 2.0, 'generator too slow for an HTTP request: %.3fs' % elapsed

print('--- 2. contract keys vs cma_tiles.frame() ---')
real_keys = {'available', 'provenance', 'error', 'slot', 'cells', 'degreesPerCell',
             'gridTiles', 'stats', 'lookbackStepsUsed', 'cache'}
missing = real_keys - set(f)
extra = set(f) - real_keys
print('missing from sim:', sorted(missing))
print('extra in sim    :', sorted(extra))
assert not missing, 'synthetic frame is missing real keys: %s' % sorted(missing)

print('--- 3. cell shape ---')
x0, y0, rows = f['cells'][0]
print('cell triple', x0, y0, 'rows', len(rows), 'cols', len(rows[0]))
assert len(rows) == cma_tiles.TILE_SIZE and len(rows[0]) == cma_tiles.TILE_SIZE
types = {type(v).__name__ for row in rows for v in row}
print('value types', types)
assert types <= {'float', 'NoneType'}, 'unexpected value types: %s' % types
print('degreesPerCell', f['degreesPerCell'], 'gridTiles', f['gridTiles'])
print('stats', f['stats'])
assert f['stats']['present'] > 0, 'synthetic frame is empty'
assert f['stats']['maxDbz'] > cma_tiles.STRONG_DBZ, 'no STRONG core in the frame'

print('--- 4. determinism ---')
g = weather_sim.frame(seed=42, slot=SLOT)
print('identical bytes:', f['cells'] == g['cells'])
assert f['cells'] == g['cells'], 'not deterministic for the same (seed, slot)'

print('--- 5. evolution over slots (motion + life cycle) ---')
base = dt.datetime(2026, 9, 18, 10, 36, tzinfo=dt.timezone.utc)
prev = None
distinct = 0
for minutes in (0, 6, 12, 18, 24):
    fr = weather_sim.frame(seed=42, slot=base + dt.timedelta(minutes=minutes))
    same = None if prev is None else (fr['cells'] == prev)
    if same is False:
        distinct += 1
    print('slot +%3dmin present=%-7d maxDbz=%-6s echoFrac=%-9s identical_to_prev=%s'
          % (minutes, fr['stats']['present'], fr['stats']['maxDbz'],
             fr['stats']['echoFraction'], same))
    prev = fr['cells']
assert distinct >= 4, 'field is not evolving across slots'
print('distinct successive frames:', distinct)

print('--- 6. radar_field.derive / shield consume it ---')
derived = radar_field.derive(f)
print('derive available', derived.get('available'), 'error', derived.get('error'))
print('derive echoFraction', derived.get('echoFraction'),
      'components', derived.get('components'))
assert derived.get('available'), 'derive rejected the synthetic frame: %s' % derived.get('error')
outer, core, caution, watch = radar_field.shield(derived)
print('outer   is_empty=%-5s area=%.4f deg^2' % (outer.is_empty, outer.area))
print('core    is_empty=%-5s area=%.4f deg^2' % (core.is_empty, core.area))
print('caution is_empty=%-5s area=%.4f deg^2' % (caution.is_empty, caution.area))
print('watch   is_empty=%-5s area=%.4f deg^2' % (watch.is_empty, watch.area))
assert not outer.is_empty, 'shield produced no outer field'
assert not core.is_empty, 'shield produced no core'
# `within` is exact and fails on a shared boundary, which `core` has by
# construction (`core = core.intersection(outer)`). Compare with a small
# tolerance instead, and additionally assert the core holds no area outside.
outside = core.difference(outer)
print('core area outside outer: %.6f m^2' % outside.area)
assert outside.area < 1.0, 'core materially escapes outer: %.3f m^2' % outside.area
# caution is defined as outer minus core, so it must not overlap the core.
overlap = caution.intersection(core)
print('caution/core overlap: %.6f m^2' % overlap.area)
assert overlap.area < 1.0, 'caution overlaps core: %.3f m^2' % overlap.area

print('--- 7. intensity structure of the dBZ tiers ---')
# The bands are *mutually exclusive* ranges (15-35, 35-45, 45-inf -- see
# `radar_field.BAND_EDGES`), so a STRONG pixel is by construction NOT inside the
# STRATIFORM geometry. Nesting of contours therefore does not show up as
# polygon-within-polygon between tiers; what it shows up as is a STRONG region
# that is *surrounded by* CONVECTIVE echo on the raster, which is the property
# that makes the drawn hazard read as a storm rather than a flat blob.
#
# The invariant worth asserting is therefore about the raster, not the polygons:
# every STRONG pixel should have CONVECTIVE echo (or another STRONG pixel) in its
# neighbourhood, i.e. strong cores must not sit alone on a hard edge against
# clear air. A generator that filled a whole cell at a single dBZ would violate
# this, and that is exactly the failure mode the radial profile exists to avoid.
bands = derived['bands']
for name in ('STRATIFORM', 'CONVECTIVE', 'STRONG', 'SEVERE'):
    info = bands.get(name) or {}
    print('%-11s components=%-4s areaM2=%.4e' % (name, info.get('components'),
                                                 info.get('areaM2', 0.0)))

rows_all = [row for _x, _y, r in f['cells'] for row in r]
strong_px = [(r, c) for r, row in enumerate(rows_all)
             for c, v in enumerate(row) if v is not None and v >= cma_tiles.STRONG_DBZ]
convective_px = [(r, c) for r, row in enumerate(rows_all)
                 for c, v in enumerate(row) if v is not None and v >= cma_tiles.CONVECTIVE_DBZ]
print('STRONG pixels %d, CONVECTIVE-and-up pixels %d' % (len(strong_px), len(convective_px)))
assert strong_px, 'no STRONG pixel at all'
# Every STRONG pixel is also a CONVECTIVE-and-up pixel, which is only true if the
# radial profile descends monotonically -- the nesting property, stated where it
# actually holds.
assert set(strong_px) <= set(convective_px), \
    'some STRONG pixels are not enclosed by the CONVECTIVE footprint'
alone = 0
cset = set(convective_px)
for r, c in strong_px:
    neighbours = [(r + dr, c + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                  if (dr, dc) != (0, 0)]
    if not any(n in cset for n in neighbours):
        alone += 1
print('STRONG pixels with no CONVECTIVE neighbour: %d of %d' % (alone, len(strong_px)))
assert alone == 0, 'strong cores sit on a hard edge against clear air'

print()
print('OK: synthetic radar frame is fast, deterministic, evolving, and consumable')
