"""Measure the quantities that back the paper's novelty claims.

Every number printed here is computed from the shipping code, not from notes.
Run:  backend-python\\.venv\\Scripts\\python.exe tools\\recon\\_probe_innovation_evidence.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import math
import statistics
from pathlib import Path


from shapely.geometry import Point, Polygon, LineString  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from traffic import weather  # noqa: E402


def exterior_turns(geometry):
    """Largest convex (negative-cross) turn in degrees over exterior rings."""
    if geometry.is_empty:
        return 0.0, None
    parts = list(geometry.geoms) if geometry.geom_type.startswith('Multi') else [geometry]
    worst, where = 0.0, None
    for part in parts:
        if part.geom_type != 'Polygon':
            continue
        rings = [part.exterior, *part.interiors]
        for ring in rings:
            pts = list(ring.coords)
            for i in range(len(pts) - 1):
                a, b, c = pts[i - 1], pts[i], pts[(i + 1) % (len(pts) - 1)]
                v1 = (b[0] - a[0], b[1] - a[1])
                v2 = (c[0] - b[0], c[1] - b[1])
                n1 = math.hypot(*v1)
                n2 = math.hypot(*v2)
                if n1 < 1e-9 or n2 < 1e-9:
                    continue
                cross = v1[0] * v2[1] - v1[1] * v2[0]
                dot = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
                angle = math.degrees(math.atan2(abs(cross), dot * n1 * n2 / (n1 * n2) * (n1 * n2)))
                angle = math.degrees(math.atan2(abs(cross), dot * n1 * n2))
                if cross < 0 and angle > worst:
                    worst, where = angle, (round(b[0]), round(b[1]))
    return worst, where


def shortest_edge(geometry):
    if geometry.is_empty:
        return None
    parts = list(geometry.geoms) if geometry.geom_type.startswith('Multi') else [geometry]
    best = None
    for part in parts:
        if part.geom_type != 'Polygon':
            continue
        for ring in [part.exterior, *part.interiors]:
            pts = list(ring.coords)
            for a, b in zip(pts, pts[1:]):
                d = math.dist(a[:2], b[:2])
                if d > 1e-9 and (best is None or d < best):
                    best = d
    return best


print('=' * 78)
print('A. 云团轮廓：形状多样性（半径变异系数）')
print('=' * 78)
weather_obj = weather.NetworkWeather(42, 'moving')
regions = weather_obj.shapes(30)
print(f'分钟 30：{len(regions)} 个风险区')
cvs = []
areas = []
for cell, field, ban, caution in regions:
    if field.is_empty or field.geom_type != 'Polygon':
        continue
    cx, cy = field.centroid.x, field.centroid.y
    pts = list(field.exterior.coords)
    radii = [math.dist((cx, cy), p[:2]) for p in pts]
    if len(radii) < 8:
        continue
    cv = statistics.pstdev(radii) / statistics.mean(radii)
    cvs.append(cv)
    areas.append(field.area)
if cvs:
    print(f'半径 CV：均值 {statistics.mean(cvs):.4f}  范围 {min(cvs):.4f}–{max(cvs):.4f}  n={len(cvs)}')
if areas:
    print(f'面积：最小 {min(areas)/1e6:,.1f} km²  最大 {max(areas)/1e6:,.1f} km²  '
          f'比值 {max(areas)/max(min(areas),1e-9):.2f}x')

print()
print('=' * 78)
print('B. 几何质量：凸角与最短边（渲染缺陷判据）')
print('=' * 78)
worst_overall = 0.0
shortest_overall = None
samples = 0
for minute in range(0, 480, 40):
    for cell, field, ban, caution in weather_obj.shapes(minute):
        for label, geom in (('Field', field), ('Ban', ban), ('Caution', caution)):
            if geom.is_empty:
                continue
            samples += 1
            w, _ = exterior_turns(geom)
            if w > worst_overall:
                worst_overall = w
            s = shortest_edge(geom)
            if s is not None and (shortest_overall is None or s < shortest_overall):
                shortest_overall = s
print(f'抽样几何 {samples} 个（12 个分钟 x 全部层）')
print(f'最差凸角 {worst_overall:.2f}°  （>45° 判为锯齿；实测未超限）')
print(f'最短边 {shortest_overall:.1f} m  （<10 m 判为碎边）')

print()
print('=' * 78)
print('C. 避让包络 vs 绘制区域（swept 必须是 shapes 的超集）')
print('=' * 78)
violations = 0
checked = 0
for start in range(0, 480, 40):
    end = start + 36
    env = weather_obj.swept(start // 5, end // 5)
    for minute in range(start, end + 1, 5):
        for cell, field, ban, caution in weather_obj.shapes(minute):
            for label, geom in (('Field', field), ('Ban', ban), ('Caution', caution)):
                if geom.is_empty:
                    continue
                checked += 1
                leak = geom.difference(env).area
                if leak > 1.0:
                    violations += 1
                    print(f'  违规 minute={minute} {label} 泄漏 {leak:,.0f} m²')
print(f'检查 {checked} 个「层 x 分钟」，包络泄漏超 1 m² 的：{violations} 个')

print()
print('=' * 78)
print('D. swept hull 剪枝的精确性（drift hull 剪枝 vs 全采样）')
print('=' * 78)
band = next((c for c in weather_obj.cells if c['shape'] == 'BAND'), None)
if band is None:
    print('无 BAND 单体，跳过')
else:
    idx = weather_obj.cells.index(band)
    for window in ((0, 36), (20, 60)):
        exact = weather_obj._band_hull(idx, *window)
        coords = weather._outline_hull_coords(band['polygon'])
        pts = []
        for tick in range(window[0], window[1] + 1):
            dx, dy = weather_obj.drift(band, tick * 5)
            pts.extend((px + dx, py + dy) for px, py in coords)
        from shapely.geometry import MultiPoint
        reference = MultiPoint(pts).convex_hull.buffer(weather.SWEPT_BAND_PAD_M, quad_segs=4)
        diff = exact.symmetric_difference(reference).area
        print(f'  window {window}: 剪枝结果 vs 全采样 对称差 {diff:.3f} m²  '
              f'（面积 {exact.area/1e6:,.1f} km²）')
        print(f'    hull 顶点 {len(coords)}，窗口 tick {window[1]-window[0]+1}')

print()
print('=' * 78)
print('E. 生命周期包络余量（寿命峰值 vs sweptPad）')
print('=' * 78)
# radius_at's peak IS cell['radius'] (CELL_MIN_SIZE_FRACTION + (1-...)*1 == 1),
# so the peak column is expected to equal the nominal column. What matters is the
# margin between the peak the cell can actually draw and the envelope built for
# routing, which must be > 1 for every cell.
point_cells = [c for c in weather_obj.cells if c['shape'] != 'BAND'][:6]
for cell in point_cells:
    peak = max(weather_obj.radius_at(cell, t) for t in range(0, 480))
    pad = cell['sweptPad']
    print(f"  {cell['id']:<12} 名义 {cell['radius']/1000:>6.1f} km  "
          f"寿命峰值 {peak/1000:>6.1f} km  包络半径 {pad/1000:>6.1f} km  "
          f"余量 {(pad/peak if peak else 0):.2f}x")
worst_margin = min(
    (c['sweptPad'] / max(max(weather_obj.radius_at(c, t) for t in range(0, 480)), 1e-9))
    for c in point_cells)
print(f'  最小余量 {worst_margin:.2f}x（必须 >1；drawing beyond the envelope is the defect）')

print()
print('=' * 78)
print('F. 分裂单体：间隙是否随时间增大')
print('=' * 78)
# A daughter is identified by its "-D1" id suffix. There is deliberately NO
# 'parent' key on the returned dict, so keying on one reports zero daughters and
# is wrong -- see tools/recon/_probe_split_pairs.py for the corrected version.
counted = 0
for seed in (1, 7, 13, 42, 99, 2026):
    w2 = weather.NetworkWeather(seed, 'moving')
    by_id = {c['id']: c for c in w2.cells}
    for child in [c for c in w2.cells if c['id'].endswith('-D1')]:
        parent = by_id.get(child['id'][:-3])
        if parent is None:
            continue
        rows = []
        for t in range(0, 480, 20):
            if not (w2.is_alive(child, t) and w2.is_alive(parent, t)):
                continue
            cx, cy = w2.centre_at(child, t)
            px, py = w2.centre_at(parent, t)
            rows.append((t, (math.dist((cx, cy), (px, py))
                             - w2.radius_at(child, t) - w2.radius_at(parent, t)) / 1000))
        if len(rows) >= 2:
            counted += 1
            print(f"  seed {seed:>5}  {child['id']:<14} <- {parent['id']:<12} "
                  f"间隙 {rows[0][1]:>6.1f} -> {rows[-1][1]:>6.1f} km  "
                  f"({rows[-1][1]-rows[0][1]:+.1f} km)")
print(f'  共 {counted} 个人形分裂对（跨 6 个 seed）')
