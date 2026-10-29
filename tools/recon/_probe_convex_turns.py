"""Locate every convex turn above 45 degrees and classify it.

Two categories matter:
  * the outline's own harmonic geometry -> a real rendering defect (must be 0)
  * a boundary cut (province edge / frame intersection) -> a real shape, report only
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import math
from pathlib import Path


from shapely.geometry import Polygon  # noqa: E402
from traffic import weather  # noqa: E402


def convex_turns(geometry):
    """(angle, vertex, ring_kind) for every negative-cross turn."""
    out = []
    if geometry.is_empty:
        return out
    parts = list(geometry.geoms) if geometry.geom_type.startswith('Multi') else [geometry]
    for part in parts:
        if part.geom_type != 'Polygon':
            continue
        for kind, ring in [('exterior', part.exterior)] + \
                [('interior', r) for r in part.interiors]:
            pts = list(ring.coords)
            n = len(pts) - 1
            for i in range(n):
                a, b, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
                v1 = (b[0] - a[0], b[1] - a[1])
                v2 = (c[0] - b[0], c[1] - b[1])
                n1 = math.hypot(*v1)
                n2 = math.hypot(*v2)
                if n1 < 1e-9 or n2 < 1e-9:
                    continue
                cross = v1[0] * v2[1] - v1[1] * v2[0]
                dot = v1[0] * v2[0] + v1[1] * v2[1]
                if cross < 0:
                    out.append((math.degrees(math.atan2(abs(cross), dot)), b, kind, n1, n2))
    return out


w = weather.NetworkWeather(42, 'moving')
print('=' * 78)
print('全部 >45° 凸角：定位与分类')
print('=' * 78)
hits = []
for minute in range(0, 480, 20):
    for cell, field, ban, caution in w.shapes(minute):
        for label, geom in (('Field', field), ('Ban', ban), ('Caution', caution)):
            for angle, vertex, ring_kind, n1, n2 in convex_turns(geom):
                if angle > 45:
                    hits.append((angle, minute, cell['id'], label, ring_kind, n1, n2, vertex))
hits.sort(reverse=True)
print(f'共 {len(hits)} 处 >45° 凸角（24 个分钟 x 全部层）')
for angle, minute, cid, label, ring_kind, n1, n2, vertex in hits[:15]:
    print(f'  {angle:>6.2f}°  minute={minute:>3}  {cid:<16} {label:<8} {ring_kind:<8} '
          f'边长 {n1:>8.1f} / {n2:>8.1f} m  顶点 ({vertex[0]:.0f},{vertex[1]:.0f})')

print()
print('=' * 78)
print('未裁剪几何判定：用原始 RING 单体（不含省界求交）重测')
print('=' * 78)
worst = 0.0
worst_info = None
count = 0
for minute in range(0, 480, 20):
    for cell, field, ban, caution in w.shapes(minute):
        if cell['shape'] == 'BAND':
            continue
        count += 1
        for label, geom in (('Field', field), ('Ban', ban), ('Caution', caution)):
            for angle, vertex, ring_kind, n1, n2 in convex_turns(geom):
                if angle > worst:
                    worst = angle
                    worst_info = (minute, cell['id'], label, ring_kind, n1, n2)
print(f'检查 {count} 个 RING 单体的层（分钟步长 20）')
print(f'最差凸角 {worst:.2f}°')
if worst_info:
    m, cid, label, kind, n1, n2 = worst_info
    print(f'  位于 minute={m} {cid} {label} {kind}，相邻边长 {n1:.1f} / {n2:.1f} m')

print()
print('=' * 78)
print('BAND 单体（含省界裁剪）的最差凸角')
print('=' * 78)
worst_band = 0.0
band_info = None
for minute in range(0, 480, 40):
    for cell, field, ban, caution in w.shapes(minute):
        if cell['shape'] != 'BAND':
            continue
        for label, geom in (('Field', field), ('Ban', ban), ('Caution', caution)):
            for angle, vertex, ring_kind, n1, n2 in convex_turns(geom):
                if angle > worst_band:
                    worst_band = angle
                    band_info = (minute, label, ring_kind, n1, n2, vertex)
print(f'最差凸角 {worst_band:.2f}°')
if band_info:
    m, label, kind, n1, n2, v = band_info
    print(f'  位于 minute={m} {label} {kind}，相邻边长 {n1:.1f} / {n2:.1f} m  '
          f'顶点 ({v[0]:.0f},{v[1]:.0f})')
    print('  注：边长 1-5 km 量级 = 真实省界直切；<10 m 才是碎边。')

print()
print('=' * 78)
print('全部 >45° 凸角的边长分布（判据：真实边界 vs 锯齿）')
print('=' * 78)
if hits:
    edges = sorted(max(h[5], h[6]) for h in hits)
    print(f'  n={len(edges)}  最小 {edges[0]:.1f} m  中位 {edges[len(edges)//2]:.1f} m  '
          f'最大 {edges[-1]:.1f} m')
    tiny = [e for e in edges if e < 10]
    print(f'  边长 <10 m（真碎边/锯齿）：{len(tiny)} 个')
    km = [e for e in edges if e >= 1000]
    print(f'  边长 >=1 km（省界直切）：{len(km)} 个')
