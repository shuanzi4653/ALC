"""Locate the single 55-degree turn in the northeast band's field outline.

The smoothness guard now fails on exactly one vertex: 55.03 degrees, on the
band's ``field``. Everything else is well under 45. Two explanations are
possible and they demand opposite responses:

* the outline generator still produces a cusp somewhere, which is a real
  defect and must be fixed in the generator; or
* the band polygon is a union of cluster outlines, and where two clusters
  overlap the union introduces a genuine concave corner -- a notch between two
  merged cloud masses, which is what real merged echoes look like. That is
  geometry, not roughness, and the guard's flat "every vertex under 45" rule is
  simply the wrong instrument for a union.

This probe prints the neighbourhood of the worst vertex, the edge lengths on
both sides, and whether the turn is convex or concave. A concave notch with
kilometre-scale legs is a merger; a convex cusp with sub-100 m legs is a flaw.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
import math


from traffic.weather import NetworkWeather

TOLERANCE = 45.0


def turns_with_neighbourhood(polygon):
    coords = list(polygon.exterior.coords)
    # Drop the duplicated closing vertex: keeping it makes the last real edge
    # zero-length and the turn at that point meaningless.
    if len(coords) >= 2 and coords[0] == coords[-1]:
        coords = coords[:-1]
    total = len(coords)
    rows = []
    for index in range(total):
        a, b, c = coords[index - 1], coords[index], coords[(index + 1) % total]
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        n1 = math.hypot(*v1) or 1.0
        n2 = math.hypot(*v2) or 1.0
        cosine = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
        angle = math.degrees(math.acos(cosine))
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        rows.append((angle, index, b, min(n1, n2), cross))
    rows.sort(reverse=True, key=lambda row: row[0])
    return rows


world = NetworkWeather(42, 'moving')
shapes = world.shapes(60)

worst_overall = []
for cell, field, ban, caution in shapes:
    for label, geometry in (('field', field), ('ban', ban), ('caution', caution)):
        geoms = [geometry] if geometry.geom_type == 'Polygon' else list(geometry.geoms)
        for position, polygon in enumerate(geoms):
            if polygon.geom_type != 'Polygon':
                continue
            if len(polygon.exterior.coords) < 5:
                continue
            for angle, index, point, short_edge, cross in turns_with_neighbourhood(polygon)[:3]:
                worst_overall.append((angle, cell['id'], label, position, point,
                                      short_edge, cross, len(polygon.exterior.coords) - 1))

worst_overall.sort(reverse=True, key=lambda row: row[0])
print('=== 前 12 个最尖的转角 ===')
for angle, cell, label, position, point, short_edge, cross, vertices in worst_overall[:12]:
    kind = '凸（向外）' if cross < 0 else '凹（向内缺口）'
    print(f'{angle:7.2f}°  {cell:<22} {label:<8} 部件{position} 顶点数{vertices:>4}  '
          f'最短边 {short_edge:8.1f} m  {kind}  位置 ({point[0]:.0f}, {point[1]:.0f})')

print()
print('=== 判定 ===')
convex_over = [row for row in worst_overall if row[0] > TOLERANCE and row[6] < 0]
concave_over = [row for row in worst_overall if row[0] > TOLERANCE and row[6] >= 0]
print(f'超过 {TOLERANCE}° 的凸角：{len(convex_over)} 个（凸角=尖刺，属真缺陷）')
for row in convex_over[:6]:
    print(f'   {row[0]:7.2f}°  {row[1]} {row[2]}  最短边 {row[5]:.1f} m')
print(f'超过 {TOLERANCE}° 的凹角：{len(concave_over)} 个（凹角=合并缺口，属形状）')
for row in concave_over[:6]:
    print(f'   {row[0]:7.2f}°  {row[1]} {row[2]}  最短边 {row[5]:.1f} m')
