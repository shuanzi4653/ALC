"""Confirm the spike sits at the stretched long-axis end, and test a phase offset.

WX-1-03 has 72 vertices and the bad turn is at index 36 = vertices//2, i.e. exactly
theta = pi, which is the +x end of the ellipse before rotation -- the stretched
long-axis endpoint. Any even vertex count puts samples exactly there.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import math
from pathlib import Path


from shapely.geometry import Polygon  # noqa: E402
from traffic import weather as W  # noqa: E402


def max_convex(poly):
    pts = list(poly.exterior.coords)
    n = len(pts) - 1
    worst, idx = 0.0, None
    for i in range(n):
        a, b, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 < 1e-9 or n2 < 1e-9:
            continue
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        dot = v1[0] * v2[0] + v1[1] * v2[1]
        if cross < 0:
            ang = math.degrees(math.atan2(abs(cross), dot))
            if ang > worst:
                worst, idx = ang, i
    return worst, idx


def outline_with_phase(cx, cy, radius, cfg, phase0, harmonics=None):
    """Verbatim copy of _irregular_outline with an added sampling phase offset."""
    harmonics = harmonics if harmonics is not None else cfg['harmonics']
    stretch = cfg['stretch']
    axis = cfg['axis']
    cos_axis, sin_axis = math.cos(axis), math.sin(axis)
    normaliser = sum(a for _, a, _ in harmonics)
    roughness = W.OUTLINE_ROUGHNESS_LOW_ORDER if len(harmonics) < 4 else W.OUTLINE_ROUGHNESS
    highest = max(o for o, _, _ in harmonics)
    slope = sum(a * o for o, a, _ in harmonics)
    stretch_factor = (stretch + 1 / stretch) / 2
    budget = math.ceil(roughness * slope * stretch_factor * math.tau
                       / max(normaliser, 1e-9) / W.OUTLINE_MAX_TURN_RAD)
    vertices = int(max(24, 24 * highest // 2, budget))
    vertices = min(vertices, W.OUTLINE_VERTICES)
    pts = []
    for index in range(vertices):
        theta = index * math.tau / vertices + phase0
        wave = sum(a * math.sin(o * theta + p) for o, a, p in harmonics)
        scale = 1 + roughness * wave / max(normaliser, 1e-9)
        px = radius * scale * stretch * math.cos(theta)
        py = radius * scale * (1 / stretch) * math.sin(theta)
        pts.append((cx + px * cos_axis - py * sin_axis, cy + px * sin_axis + py * cos_axis))
    return Polygon(pts).buffer(0)


w = W.NetworkWeather(42, 'moving')
print('=' * 78)
print('基线：所有单体的最大凸角（现网代码，phase0 = 0）')
print('=' * 78)
bad = []
for cell in w.cells:
    if cell['shape'] != 'RING' or 'outline' not in cell:
        continue
    poly = W._irregular_outline(0, 0, cell['radius'], cell['outline'])
    worst, idx = max_convex(poly)
    n = len(poly.exterior.coords) - 1
    if worst > 43:
        bad.append((worst, idx, n, cell['id'], cell['outline']['stretch']))
bad.sort(reverse=True)
for worst, idx, n, cid, s in bad:
    print(f'  {cid:<14} 转角 {worst:>6.2f}°  顶点 {n:>4}  触发点 {idx:>4}  '
          f'({idx}/{n} = {idx/n:.2f})  stretch {s:.3f}')

print()
print('=' * 78)
print('加采样相位偏移后（phase0 = 半个顶点步长）')
print('=' * 78)
for shift_frac in (0.0, 0.25, 0.5, 0.75):
    worst_all = 0.0
    worst_id = None
    over = 0
    for cell in w.cells:
        if cell['shape'] != 'RING' or 'outline' not in cell:
            continue
        cfg = cell['outline']
        highest = max(o for o, _, _ in cfg['harmonics'])
        slope = sum(a * o for o, a, _ in cfg['harmonics'])
        norm = sum(a for _, a, _ in cfg['harmonics'])
        rough = W.OUTLINE_ROUGHNESS_LOW_ORDER if len(cfg['harmonics']) < 4 else W.OUTLINE_ROUGHNESS
        sf = (cfg['stretch'] + 1 / cfg['stretch']) / 2
        budget = math.ceil(rough * slope * sf * math.tau / norm / W.OUTLINE_MAX_TURN_RAD)
        v = min(int(max(24, 24 * highest // 2, budget)), W.OUTLINE_VERTICES)
        poly = outline_with_phase(0, 0, cell['radius'], cfg, shift_frac * math.tau / v)
        worst, _ = max_convex(poly)
        if worst > worst_all:
            worst_all, worst_id = worst, cell['id']
        if worst > 45:
            over += 1
    print(f'  phase0 = {shift_frac:>4.2f} x 步长:  最大凸角 {worst_all:>6.2f}°  '
          f'({worst_id})  超 45° 的单体 {over} 个')
