"""Isolate which of field / ban / caution carries the sharp corner.

The suite reports a 141.8-degree exterior turn, while a probe over `field` alone
saw at most 54.4. The test walks all three tiers, so the corner must be in `ban`
or `caution`. Each is measured separately here, and the offending vertex is
printed so the cause is visible rather than guessed.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
import math


from traffic.weather import NetworkWeather, _polygon_parts  # noqa: E402


def turns_of(geometry):
    """Every exterior turn across every polygon component, with degenerate edges skipped."""
    found = []
    for polygon in _polygon_parts(geometry):
        coords = list(polygon.exterior.coords)
        if len(coords) > 1 and coords[0] == coords[-1]:
            coords = coords[:-1]
        cleaned = [coords[0]]
        for point in coords[1:]:
            if math.hypot(point[0] - cleaned[-1][0], point[1] - cleaned[-1][1]) > 1e-6:
                cleaned.append(point)
        coords = cleaned
        span = len(coords)
        if span < 3:
            continue
        for index in range(span):
            a, b, c = coords[index - 1], coords[index], coords[(index + 1) % span]
            v1 = (b[0] - a[0], b[1] - a[1])
            v2 = (c[0] - b[0], c[1] - b[1])
            n1 = math.hypot(*v1) or 1e-9
            n2 = math.hypot(*v2) or 1e-9
            cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
            found.append((math.degrees(math.acos(max(-1.0, min(1.0, cos)))),
                          b, min(n1, n2)))
    return found


world = NetworkWeather(42, 'moving')
shapes = world.shapes(60)

for label, pick in (('field', lambda row: row[1]), ('ban', lambda row: row[2]),
                    ('caution', lambda row: row[3])):
    worst = (0.0, None, 0.0)
    worst_cell = None
    for row in shapes:
        geometry = pick(row)
        for turn, point, edge in turns_of(geometry):
            if turn > worst[0]:
                worst = (turn, point, edge)
                worst_cell = row[0]['id']
    turn, point, edge = worst
    print(f'{label:<9} 最大外角 {turn:>7.2f}°   最短相邻边 {edge:>8.1f} m')
    if point and turn > 45:
        print(f'          单体 {worst_cell}   位置 ({point[0]:.0f}, {point[1]:.0f})')

print()
print('=== 对超过 45 度的角逐个统计 ===')
for label, pick in (('field', lambda row: row[1]), ('ban', lambda row: row[2]),
                    ('caution', lambda row: row[3])):
    offenders = []
    for row in shapes:
        for turn, point, edge in turns_of(pick(row)):
            if turn > 45.0:
                offenders.append((turn, row[0]['id'], edge))
    offenders.sort(reverse=True)
    print(f'{label}: {len(offenders)} 个')
    for turn, cell, edge in offenders[:5]:
        print(f'    {turn:>7.2f}°  {cell:<24} 最短边 {edge:>7.1f} m')
