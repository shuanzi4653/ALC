"""Dump the actual vertex sequence around a sharp corner on `ban`.

The measurement says the worst `ban` corner has a 1.0 m adjacent edge, which is
the signature of a degenerate vertex rather than a real spike. Rather than guess
at the cause again, this prints the raw coordinates around the worst turn so the
structure is visible.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
import math


from traffic.weather import NetworkWeather  # noqa: E402

world = NetworkWeather(42, 'moving')
shapes = world.shapes(60)

ban = None
for cell, field, ban_geometry, caution in shapes:
    if cell['id'] == 'WX-1-09':
        ban = ban_geometry
        break
if ban is None:
    raise SystemExit('WX-1-09 not present at minute 60')

print(f'ban geom_type = {ban.geom_type}')
parts = [ban] if ban.geom_type == 'Polygon' else list(ban.geoms)
print(f'components = {len(parts)}')
for polygon in parts:
    coords = list(polygon.exterior.coords)
    print(f'  vertices (incl. closing) = {len(coords)}   area = {polygon.area / 1e6:.1f} km2')
    # Shortest edges
    edges = []
    for index in range(len(coords) - 1):
        a, b = coords[index], coords[index + 1]
        edges.append((math.hypot(b[0] - a[0], b[1] - a[1]), index))
    edges.sort()
    print(f'  最短 6 条边: ' + ', '.join(f'{length:.2f} m @v{i}' for length, i in edges[:6]))
    print(f'  边长度中位数 {sorted(e[0] for e in edges)[len(edges)//2]:.1f} m')

    # Print the neighbourhood of the shortest edge.
    shortest_length, shortest_index = edges[0]
    print()
    print(f'  最短边 (v{shortest_index}) 前后各 3 个顶点:')
    for offset in range(-3, 4):
        index = (shortest_index + offset) % (len(coords) - 1)
        x, y = coords[index]
        marker = ' <-- 起点' if offset == 0 else (' <-- 终点' if offset == 1 else '')
        print(f'    v{index:>4}  ({x:>12.2f}, {y:>12.2f}){marker}')

    # Count exact duplicate consecutive vertices.
    duplicates = 0
    for index in range(len(coords) - 1):
        if coords[index] == coords[index + 1]:
            duplicates += 1
    print(f'  完全重复的相邻顶点对: {duplicates}')

    # Very-close-but-not-equal pairs, which is what buffer(0) can leave behind.
    near = sum(1 for length, _ in edges if 0.0 < length < 5.0)
    print(f'  相邻距离在 0-5 m 之间的顶点对数: {near}')

    print()
    print('  顶点间距的分位:')
    ls = sorted(length for length, _ in edges)
    for quantile in (0.01, 0.05, 0.1, 0.25, 0.5, 0.75):
        index = min(len(ls) - 1, int(len(ls) * quantile))
        print(f'    {quantile * 100:>5.1f}%  {ls[index]:>10.2f} m')
