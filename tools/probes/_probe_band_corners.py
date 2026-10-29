"""Find where the 90-degree corners in the band actually come from.

The shape probe reports a worst exterior turn of exactly 90.0 degrees on the
band. A mean turn of ~7-8 degrees alongside a single right angle is the
signature of a *union seam*, not of a rough outline: two smooth polygons meeting
at right angles produce exactly one corner each. This isolates the cause so the
fix targets the right thing.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
import math


from shapely.geometry import MultiPolygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from traffic import weather as W  # noqa: E402


def sharpest_turns(polygon, limit=8):
    """Sharpest exterior turns, ignoring the degenerate closing vertex.

    A raw walk over ``exterior.coords`` includes one triple whose leading edge
    has zero length (the ring repeats its first point), and atan2 of a zero
    vector yields a right angle. That produced a phantom 90.0-degree corner with
    a 1 m edge on every polygon, which looked like a geometry defect and was
    really a defect in this measurement.
    """
    coords = list(polygon.exterior.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    cleaned = [coords[0]]
    for point in coords[1:]:
        if math.hypot(point[0] - cleaned[-1][0], point[1] - cleaned[-1][1]) > 1e-6:
            cleaned.append(point)
    coords = cleaned
    turns = []
    span = len(coords)
    for index in range(span):
        a = coords[index - 1]
        b = coords[index]
        c = coords[(index + 1) % span]
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        n1 = math.hypot(*v1) or 1.0
        n2 = math.hypot(*v2) or 1.0
        cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
        turns.append((math.degrees(math.acos(cos)), b, min(n1, n2)))
    turns.sort(reverse=True, key=lambda row: row[0])
    return turns[:limit]


print('=== 逐个簇单独检查（不 union）===')
path = [W.project(p) for p in W.BAND_CENTRELINE_LONLAT]
from shapely.geometry import LineString  # noqa: E402
line = LineString(path)
length = line.length
count = max(2, int(length // W.BAND_CLUSTER_SPACING_M))
centres = []
for index in range(count + 1):
    point = line.interpolate(min(index * W.BAND_CLUSTER_SPACING_M, length))
    centres.append((point.x, point.y, W.BAND_CLUSTER_RADII_M[index % len(W.BAND_CLUSTER_RADII_M)]))

rng_holder = {}
import random  # noqa: E402
cluster_rng = random.Random(20240917)
outlines = []
for x, y, radius in centres:
    # Mirror `_band_field` exactly: the outline builder takes a *config dict*
    # from `cell_outline_params`, not the Random itself. Passing the Random
    # raised `TypeError: 'Random' object is not subscriptable` because the
    # builder indexes cfg['harmonics'].
    cfg = W.cell_outline_params(cluster_rng, lobes=6 if radius >= 18000 else 8)
    outline = W._irregular_outline(x, y, radius, cfg)
    outlines.append(outline)

for index, (outline, (x, y, r)) in enumerate(zip(outlines, centres)):
    turns = sharpest_turns(outline)
    worst = turns[0][0] if turns else 0.0
    print(f'  簇{index:>2} 半径 {r:>6} 顶点 {len(outline.exterior.coords):>4} 最大外角 {worst:>6.1f}°')

print()
print('=== 成对距离（判定是否接触）===')
print(f'{"对":>8}{"中心距 m":>12}{"半径和 m":>12}{"间隙 m":>12}{"接触":>6}')
touching = 0
for i in range(len(centres)):
    for j in range(i + 1, len(centres)):
        xi, yi, ri = centres[i]
        xj, yj, rj = centres[j]
        gap = math.hypot(xi - xj, yi - yj) - (ri + rj)
        # Distance between the actual outlines, not the nominal radii.
        real_gap = outlines[i].distance(outlines[j])
        flag = 'YES' if real_gap < 1.0 else ''
        if real_gap < 1.0:
            touching += 1
        if gap < 20000:
            print(f'{i:>4}-{j:<3}{math.hypot(xi-xj,yi-yj):>12.0f}{ri+rj:>12.0f}'
                  f'{real_gap:>12.0f}{flag:>6}')
print(f'实际接触的簇对: {touching}')

print()
print('=== union 后整体 ===')
field = unary_union(outlines)
parts = W._polygon_parts(field)
print(f'union 后多边形数 {len(parts)}（=簇数 {len(centres)} 则无合并；更少则说明有簇相接被合并）')
for part in parts:
    turns = sharpest_turns(part)
    worst = turns[0][0] if turns else 0.0
    if worst > 45:
        print(f'  尖角多边形: 面积 {part.area/1e6:>8.0f} km2  最大外角 {worst:>6.1f}°  顶点 {len(part.exterior.coords)}')
        for turn, point, edge in turns[:4]:
            print(f'      外角 {turn:>6.1f}°  位于 ({point[0]:.0f},{point[1]:.0f})  边长 {edge:.0f} m')
