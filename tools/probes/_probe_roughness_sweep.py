"""Find which harmonic configuration produces the 46.7-degree convex cusp.

The cusp survives both a higher vertex count and a gentler simplify tolerance,
so it is not a sampling or simplification artefact -- it is in the shape itself.
With only two harmonics (order 2 and 3) the radius is

    r(theta) = R * (1 + kappa * (a2*sin(2t+p2) + a3*sin(3t+p3)) / (a2+a3))

and the curvature of such a curve can genuinely reach a sharp point when the
second-derivative term of the two orders cancels the radius term. This script
sweeps the roughness `kappa` and reports, for the same seed-42 cell, the worst
convex turn. The goal is the largest kappa that still keeps every convex turn
under the guard's 45-degree limit, so the outline stays visibly irregular.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
import math


from shapely.geometry import Polygon

import traffic.weather as weather


def convex_turns(polygon):
    coords = list(polygon.exterior.coords)
    if len(coords) >= 2 and coords[0] == coords[-1]:
        coords = coords[:-1]
    total = len(coords)
    worst = 0.0
    for index in range(total):
        a, b, c = coords[index - 1], coords[index], coords[(index + 1) % total]
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        n1 = math.hypot(*v1) or 1.0
        n2 = math.hypot(*v2) or 1.0
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        if cross >= 0:
            continue  # concave, not a spike
        cosine = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
        worst = max(worst, math.degrees(math.acos(cosine)))
    return worst


world = weather.NetworkWeather(42, 'moving')
cell = next(c for c in world.cells if c['id'] == 'WX-1-09')
cfg = cell['outline']
print("WX-1-09 harmonics:", [(o, round(a, 3), round(p, 2)) for o, a, p in cfg['harmonics']])
print("full outline has", len(cfg['harmonics']), "harmonics; core uses first 2")
print()

original = weather.OUTLINE_ROUGHNESS
print(f"{'kappa':>7} {'2阶核心最尖凸角':>16} {'全阶轮廓最尖凸角':>18} {'2阶半径CV':>10} {'2阶顶点':>8}")
for kappa in (0.42, 0.36, 0.30, 0.26, 0.22, 0.18, 0.14, 0.10):
    weather.OUTLINE_ROUGHNESS = kappa

    low = weather._irregular_outline(0.0, 0.0, float(cell['radius']), cfg,
                                     harmonics=cfg['harmonics'][:2])
    full = weather._irregular_outline(0.0, 0.0, float(cell['radius']), cfg)

    # Radial spread of the core outline: a disc would be 0.0.
    centre = low.centroid
    radii = [math.hypot(x - centre.x, y - centre.y)
             for x, y in list(low.exterior.coords)[:-1]]
    mean = sum(radii) / len(radii)
    variance = sum((r - mean) ** 2 for r in radii) / len(radii)
    cv = (variance ** 0.5) / mean if mean else 0.0

    print(f"{kappa:7.2f} {convex_turns(low):15.2f}° {convex_turns(full):17.2f}° "
          f"{cv:10.3f} {len(low.exterior.coords) - 1:8d}")

weather.OUTLINE_ROUGHNESS = original
print()
print("目标：2阶核心的凸角 < 45°，同时 CV 尽可能接近 0.19（即保持明显不规则）")
