"""Measure whether the cloud field now looks like real weather.

Three claims need evidence rather than assertion:

1. **Irregularity.** The old outline was a buffered point (a circle) or a
   three-harmonic ring. The test is the coefficient of variation of the radius
   sampled around the outline, and the exterior-angle profile. A circle scores
   0.0 and a regular polygon scores a constant angle; real radar echoes are
   lumpy, so the CV must be clearly non-zero and the edge must have genuine
   variation rather than one smooth scallop.

2. **Size variety.** Cells must differ in size, not be scaled copies. Measured as
   the spread of equivalent radii across the field at one minute.

3. **Life cycle.** Over the 480-minute timeline cells must appear and disappear,
   and a single cell's area must follow the observed grow-then-decay curve.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
import math


from traffic.weather import NetworkWeather, MIN_VISIBLE_RADIUS_M  # noqa: E402


def radius_stats(polygon):
    """Mean/CV of the radius sampled around a polygon's own centroid."""
    centroid = polygon.centroid
    coords = list(polygon.exterior.coords)[:-1]
    radii = [math.hypot(x - centroid.x, y - centroid.y) for x, y in coords]
    mean = sum(radii) / len(radii)
    if mean <= 0:
        return 0.0, 0.0
    variance = sum((r - mean) ** 2 for r in radii) / len(radii)
    return mean, math.sqrt(variance) / mean


def exterior_turn_stats(polygon, tolerance_deg=45.0):
    """Worst and mean exterior turn of a polygon's outline, in degrees.

    Degenerate zero-length edges are skipped. Shapely closes a ring by repeating
    the first coordinate at the end, and a naive walk over consecutive triples
    then evaluates one triple whose leading edge has length 0 -- atan2 of a zero
    vector yields a right angle, so every polygon reported a spurious 90.0-degree
    "corner" with a 1 m edge. Measuring the turn requires more than 3 usable
    points and a non-degenerate edge on both sides.
    """
    coords = list(polygon.exterior.coords)
    # Drop the duplicated closing vertex, then any residual duplicate points.
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    cleaned = [coords[0]]
    for point in coords[1:]:
        if math.hypot(point[0] - cleaned[-1][0], point[1] - cleaned[-1][1]) > 1e-6:
            cleaned.append(point)
    coords = cleaned
    if len(coords) < 3:
        return 0.0, 0.0, 0
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
        turns.append(math.degrees(math.acos(cos)))
    over = sum(1 for t in turns if t > tolerance_deg)
    return max(turns), sum(turns) / len(turns), over


print('=' * 78)
print('1. 不规则度：单体轮廓相对正圆的偏离')
print('=' * 78)
weather = NetworkWeather(4242, 'moving')
shapes = weather.shapes(60)
print(f'{"单体":<28}{"等效半径 m":>12}{"半径CV":>10}{"最大外角":>10}{"平均外角":>10}{">45°":>6}')
print('-' * 78)
cvs = []
radii = []
worst_turn = 0.0
for cell, field, ban, caution in shapes:
    parts = [field] if field.geom_type == 'Polygon' else list(field.geoms)
    for part in parts:
        if part.geom_type != 'Polygon' or part.area < 1e6:
            continue
        mean_r, cv = radius_stats(part)
        region_r = math.sqrt(part.area / math.pi)
        radii.append(region_r)
        cvs.append(cv)
        max_turn, avg_turn, over = exterior_turn_stats(part)
        worst_turn = max(worst_turn, max_turn)
        if len(cvs) <= 12:
            print(f'{cell["id"][:27]:<28}{region_r:>12.0f}{cv:>10.3f}'
                  f'{max_turn:>10.1f}{avg_turn:>10.1f}{over:>6}')

print()
print(f'半径变异系数（椭圆度+粗糙度）: 均值 {sum(cvs)/len(cvs):.3f}  '
      f'范围 {min(cvs):.3f} .. {max(cvs):.3f}')
print(f'  （正圆=0.000；旧的三谐波环约 0.03-0.05）')
print(f'最大外角: {worst_turn:.1f}°  （>45° 视为锯齿/尖角）')

print()
print('=' * 78)
print('2. 大小差异：同一分钟场内单体的等效半径分布')
print('=' * 78)
print(f'单体数 {len(radii)}   最小 {min(radii):.0f} m   最大 {max(radii):.0f} m   '
      f'最大/最小 = {max(radii)/min(radii):.1f} 倍')
mean_r = sum(radii) / len(radii)
print(f'均值 {mean_r:.0f} m   标准差 {math.sqrt(sum((r-mean_r)**2 for r in radii)/len(radii)):.0f} m')

print()
print('=' * 78)
print('3. 生命周期：时间轴上的生消')
print('=' * 78)
counts = []
for minute in range(0, 481, 30):
    alive = sum(1 for cell in weather.cells if weather.is_alive(cell, minute))
    counts.append((minute, alive))
print('分钟 : ' + '  '.join(f'{m:>3}' for m, _ in counts))
print('存活 : ' + '  '.join(f'{c:>3}' for _, c in counts))
distinct = sorted({c for _, c in counts})
print(f'存活数变化范围 {min(distinct)} .. {max(distinct)}；出现过 {len(distinct)} 种取值')
print(f'（若所有单体同时存在，这里只会有一个取值）')

print()
print('单个单体的面积演变（取一个生命周期完整的单体）：')
candidates = [c for c in weather.cells
              if c.get('lifeMinutes') and c['birth'] >= 30
              and c['birth'] + c['lifeMinutes'] <= 460 and c['shape'] == 'RING']
if candidates:
    cell = candidates[0]
    print(f'  {cell["id"]}  出生 {cell["birth"]:.0f} 分  生命史 {cell["lifeMinutes"]:.0f} 分')
    print(f'  {"分钟":>6}{"相对年龄":>10}{"半径 m":>12}{"面积 km2":>12}')
    birth, life = cell['birth'], cell['lifeMinutes']
    for fraction in (0.05, 0.2, 0.4, 0.6, 0.8, 0.95):
        minute = birth + life * fraction
        radius = weather.radius_at(cell, minute)
        area = math.pi * radius ** 2 / 1e6
        print(f'  {minute:>6.0f}{fraction:>10.2f}{radius:>12.0f}{area:>12.0f}')
    peak = weather.radius_at(cell, birth + life * 0.42)
    birth_r = weather.radius_at(cell, birth + 0.5)
    print(f'  -> 峰值半径 {peak:.0f} m 是出生时 {birth_r:.0f} m 的 {peak/birth_r:.2f} 倍')
else:
    print('  （本次抽样没有完整生命周期的单体）')
