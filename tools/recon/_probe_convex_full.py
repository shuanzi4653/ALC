"""Full-timeline convex-turn audit at 5-minute stride, all cells, all tiers.

This supersedes the 18-combination sample in the V1.6 evidence pack, which
missed four violations by sampling too coarsely.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import math
import statistics
from pathlib import Path


from shapely.geometry import Polygon  # noqa: E402
from traffic import weather  # noqa: E402

LIMIT_DEG = 45.0


def convex_turns(geometry):
    out = []
    if geometry.is_empty:
        return out
    parts = list(geometry.geoms) if geometry.geom_type.startswith('Multi') else [geometry]
    for part in parts:
        if part.geom_type != 'Polygon':
            continue
        rings = [('exterior', part.exterior)] + [('interior', r) for r in part.interiors]
        for kind, ring in rings:
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
                    out.append((math.degrees(math.atan2(abs(cross), dot)), b, kind, min(n1, n2)))
    return out


for seed in (42, 7):
    w = weather.NetworkWeather(seed, 'moving')
    worst = 0.0
    worst_info = None
    violations = []
    ring_count = 0
    band_count = 0
    total_geoms = 0
    all_angles = []
    min_edge = None
    for minute in range(0, 480, 5):
        for cell, field, ban, caution in w.shapes(minute):
            is_band = cell['shape'] == 'BAND'
            for label, geom in (('Field', field), ('Ban', ban), ('Caution', caution)):
                if geom.is_empty:
                    continue
                total_geoms += 1
                for angle, vertex, ring_kind, edge in convex_turns(geom):
                    all_angles.append(angle)
                    if edge < 10 and (min_edge is None or edge < min_edge):
                        min_edge = edge
                    if angle > LIMIT_DEG:
                        violations.append((angle, minute, cell['id'], label, ring_kind, edge, is_band))
                    if angle > worst:
                        worst = angle
                        worst_info = (minute, cell['id'], label, ring_kind, edge, is_band)
    print('=' * 78)
    print(f'seed {seed}：全时轴 5 分钟步长审计')
    print('=' * 78)
    print(f'  抽样几何 {total_geoms} 个，凸角总数 {len(all_angles)}')
    print(f'  最差凸角 {worst:.2f}°  '
          f'（minute={worst_info[0]} {worst_info[1]} {worst_info[2]} '
          f'{"BAND" if worst_info[5] else "RING"}，最短相邻边 {worst_info[4]:.1f} m）')
    print(f'  超 {LIMIT_DEG:.0f}° 的凸角 {len(violations)} 处')
    if violations:
        band_v = [v for v in violations if v[6]]
        ring_v = [v for v in violations if not v[6]]
        print(f'    其中 BAND（含省界裁剪）{len(band_v)} 处，RING（未裁剪本体）{len(ring_v)} 处')
        for angle, minute, cid, label, kind, edge, is_band in sorted(violations, reverse=True)[:8]:
            print(f'      {angle:>6.2f}°  min={minute:>3}  {cid:<16}{label:<8}'
                  f'{"BAND" if is_band else "RING":<6} 最短边 {edge:>8.1f} m')
    if all_angles:
        print(f'  凸角分布：中位 {statistics.median(all_angles):.2f}°  '
              f'P95 {sorted(all_angles)[int(len(all_angles)*0.95)]:.2f}°  '
              f'最大 {max(all_angles):.2f}°')
    print(f'  最短边（凡 <10 m 者）：{min_edge if min_edge is not None else "无 <10 m 的边"}')
    print()
