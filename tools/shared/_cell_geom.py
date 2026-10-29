"""Read a weather cell's outline as a flat coordinate list, whatever its type.

Why this exists
---------------
Several probes wrote `list(cell['polygon'].exterior.coords)` and took a single
Polygon for granted. That was true when the rain band was one blob. It is now a
**chain** of irregular clusters unioned along a centreline
(`_band_field` builds `count+1` clusters and unions them), so `cell['polygon']`
is a MultiPolygon with ~20 disjoint parts and `.exterior` raises
`AttributeError: 'MultiPolygon' object has no attribute 'exterior'`.

Which coordinates the caller wants depends on the question:

* ``outline_coords`` -- every part's exterior, concatenated. Use this when the
  probe hulls or samples the structure, because omitting parts would sample only
  one cluster of a 20-cluster chain and understate the swept area.
* ``largest_ring`` -- the exterior of the single largest part. Use this when the
  probe needs *one* closed ring (e.g. to measure vertex spacing).

Neither silently degrades: a Polygon input returns its own exterior, so the same
call works for RING cells and for the band.
"""

import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from _repo import ROOT  # noqa: E402


def _rings(geom):
    """Yield each polygon part of `geom`, tolerating Polygon/MultiPolygon."""
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == 'Polygon':
        yield geom
    elif geom.geom_type == 'MultiPolygon':
        for part in geom.geoms:
            yield part
    elif geom.geom_type == 'GeometryCollection':
        for part in geom.geoms:
            yield from _rings(part)


def outline_coords(cell):
    """Flat [(x, y), ...] over every part of the cell's footprint."""
    coords = []
    for part in _rings(cell['polygon']):
        coords.extend(tuple(point) for point in part.exterior.coords)
    return coords


def largest_ring(cell):
    """The exterior of the largest part, as a closed coordinate ring."""
    parts = list(_rings(cell['polygon']))
    if not parts:
        return []
    biggest = max(parts, key=lambda part: part.area)
    return [tuple(point) for point in biggest.exterior.coords]


def describe(cell):
    """One-line summary of the cell's geometry, for probe logging."""
    geom = cell['polygon']
    parts = list(_rings(geom))
    return '%s parts=%d area=%.1f verts=%d' % (
        geom.geom_type, len(parts), geom.area,
        sum(len(p.exterior.coords) for p in parts))
