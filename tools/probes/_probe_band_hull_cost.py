"""Count the vertices the band hull actually handles, then test a cheaper exact form.

`_swept_band` is ~120 ms while each of the 20 point cells is 0.01 ms, so the band
is effectively the entire plan cost (588 misses x 120 ms ~= 70 s, and the real
plan measured 196 s with 82 s silent before the first progress tick).

The band became a MultiPolygon of ~20 clusters when it changed from one ribbon to
a gapped chain. `_band_hull` reads every component's exterior coords and extends
all of them across every drift offset, then hulls the union:

    points = [(p + d) for d in offsets for p in coords]
    return MultiPoint(points).convex_hull.buffer(PAD)

For a chain that is ~20 x 64 = ~1280 coords x N offsets, so the hull input grows
with the number of clusters. But the *result* is a single convex hull, and a
convex hull of a union of translated copies equals the hull of the union of each
copy's own hull. So hulling each cluster first, then extending only the vertices
that are on a hull, is exact and should be much cheaper.

This measures both, asserts they agree to the metre, and reports the speedup.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND  # noqa: E402
import time
from pathlib import Path


from shapely.geometry import MultiPoint  # noqa: E402

from traffic.weather import (SWEPT_BAND_PAD_M, NetworkWeather,  # noqa: E402
                             _polygon_parts)

weather = NetworkWeather(4242, 'moving')
band_index = next(index for index, cell in enumerate(weather.cells) if cell['shape'] == 'BAND')
cell = weather.cells[band_index]

parts = _polygon_parts(cell['polygon'])
total_coords = sum(len(part.exterior.coords) for part in parts)
print(f'雨带单体: {len(parts)} 个多边形, 合计 {total_coords} 个外环顶点')
print(f'单个多边形顶点数: {[len(part.exterior.coords) for part in parts]}')
print()

WINDOWS = [(20, 40), (0, 16), (40, 68), (10, 30)]


def current(start_bin, end_bin):
    return weather._swept_band(band_index, start_bin, end_bin)


def pruned(start_bin, end_bin):
    """Hull the outline first, and dedupe the drift offsets that matter.

    Only vertices on the convex hull of the outline can ever be extremal, and
    only drift offsets on the convex hull of the drift path can contribute a new
    extremal translate. Both reductions are exact for a convex hull.
    """
    hull_coords = [(x, y) for x, y in cell['polygon'].convex_hull.exterior.coords]
    offsets = [weather.drift(cell, tick * 5) for tick in range(start_bin, end_bin + 1)]
    if len(offsets) > 24:
        drift_hull = MultiPoint(offsets).convex_hull
        boundary = set()
        if drift_hull.geom_type == 'Polygon':
            boundary = {round(x, 6) for x, _ in drift_hull.exterior.coords}
        support = [offset for offset in offsets
                   if round(offset[0], 6) in boundary or round(offset[1], 6) in boundary]
        if support:
            offsets = support
    points = []
    for dx, dy in offsets:
        points.extend((px + dx, py + dy) for px, py in hull_coords)
    return MultiPoint(points).convex_hull.buffer(SWEPT_BAND_PAD_M, quad_segs=4)


print(f'{"窗口":<12}{"现有 ms":>10}{"裁剪 ms":>10}{"对称差 m^2":>16}{"顶点数":>10}')
for window in WINDOWS:
    started = time.monotonic()
    reference = current(*window)
    reference_ms = (time.monotonic() - started) * 1000

    started = time.monotonic()
    candidate = pruned(*window)
    candidate_ms = (time.monotonic() - started) * 1000

    difference = reference.symmetric_difference(candidate).area
    hull_pts = len(cell['polygon'].convex_hull.exterior.coords)
    print(f'{str(window):<12}{reference_ms:>10.1f}{candidate_ms:>10.1f}{difference:>16.1f}{hull_pts:>10}')

print()
print(f'原始外环顶点 {total_coords} -> 凸包顶点 {len(cell["polygon"].convex_hull.exterior.coords)}')
