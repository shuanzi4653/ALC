"""Root cause of the four (seed 42) convex turns above 45 degrees.

Hypothesis: `roughness` switches on `len(harmonics) < 4`, but the vertex count
is chosen from the *highest* harmonic order. A cell with 5 lobes has 5 harmonics
(orders 2..6) so it takes the high roughness 0.42, while its highest order 6
yields only 24*6//2 = 72 vertices. The curvature budget is what actually binds.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import math
from pathlib import Path


from shapely.geometry import Polygon  # noqa: E402
from traffic import weather as W  # noqa: E402

w = W.NetworkWeather(42, 'moving')
target = next(c for c in w.cells if c['id'] == 'WX-1-03')
cfg = target['outline']

print('=' * 78)
print('WX-1-03 的轮廓参数')
print('=' * 78)
print(f"  harmonics ({len(cfg['harmonics'])} 条):")
for order, amp, phase in cfg['harmonics']:
    print(f'    order={order}  amplitude={amp:.4f}  phase={phase:.4f}')
print(f"  stretch={cfg['stretch']:.4f}  axis={math.degrees(cfg['axis']):.1f}°")

normaliser = sum(a for _, a, _ in cfg['harmonics'])
highest = max(o for o, _, _ in cfg['harmonics'])
vertices = max(24, min(W.OUTLINE_VERTICES, 24 * highest // 2))
roughness = W.OUTLINE_ROUGHNESS_LOW_ORDER if len(cfg['harmonics']) < 4 else W.OUTLINE_ROUGHNESS
print()
print(f"  谐波条数 {len(cfg['harmonics'])} -> roughness={roughness}  "
      f"(阈值 <4 用 {W.OUTLINE_ROUGHNESS_LOW_ORDER}, 否则 {W.OUTLINE_ROUGHNESS})")
print(f"  最高阶 {highest} -> Nyquist 顶点数 {24*highest//2}，取 max(24, min({W.OUTLINE_VERTICES}, ...)) = {vertices}")
print(f"  归一化因子 {normaliser:.4f}")

print()
print('=' * 78)
print('曲率预算：相邻顶点的角增量（解析）')
print('=' * 78)
print('  相邻顶点的 theta 差 = 2π/vertices = %.4f rad = %.2f°'
      % (2 * math.pi / vertices, 360 / vertices))
for label, r in (('实际用值', roughness), ('低阶值', W.OUTLINE_ROUGHNESS_LOW_ORDER)):
    print(f'  roughness={r} ({label}):')
    worst_est = 0.0
    for order, amp, phase in cfg['harmonics']:
        # d/dtheta of amplitude*sin(order*theta+phase) = amplitude*order*cos(...)
        contrib = r * amp * order / normaliser
        worst_est += contrib
        print(f'    order={order} amp={amp:.4f}: 一阶导峰值贡献 {contrib:.4f} rad/rad'
              f' = {math.degrees(contrib):.2f}° 每弧度')
    print(f'    合计最陡斜率 {worst_est:.4f} -> 每顶点偏转可达 '
          f'{math.degrees(worst_est * 2 * math.pi / vertices):.2f}°')

print()
print('=' * 78)
print('实测：直接生成该轮廓，量最大凸角')
print('=' * 78)
for lobes in range(2, 10):
    params = W.cell_outline_params(__import__('random').Random(target['shapeSeed']), lobes=lobes)
    poly = W._irregular_outline(0, 0, target['radius'], params)
    pts = list(poly.exterior.coords)
    n = len(pts) - 1
    worst, worst_i = 0.0, None
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
                worst, worst_i = ang, i
    rough = W.OUTLINE_ROUGHNESS_LOW_ORDER if len(params['harmonics']) < 4 else W.OUTLINE_ROUGHNESS
    v = max(24, min(W.OUTLINE_VERTICES, 24 * max(o for o, _, _ in params['harmonics']) // 2))
    flag = ' X 超限' if worst > 45 else ''
    print(f'  lobes={lobes}: 谐波 {len(params["harmonics"])}  roughness={rough}  顶点 {v}'
          f'  -> 最大凸角 {worst:>6.2f}°{flag}')

print()
print('=' * 78)
print('验证修法：把 roughness 判据从「谐波条数」改成「曲率预算」')
print('=' * 78)
print('  预算 = roughness * sum(amp*order)/sum(amp) * 2π/vertices，需 < 约 0.79 rad (45°)')
for lobes in range(2, 10):
    params = W.cell_outline_params(__import__('random').Random(target['shapeSeed']), lobes=lobes)
    norm = sum(a for _, a, _ in params['harmonics'])
    high = max(o for o, _, _ in params['harmonics'])
    v = max(24, min(W.OUTLINE_VERTICES, 24 * high // 2))
    slope = sum(a * o for o, a, _ in params['harmonics']) / norm
    for r in (W.OUTLINE_ROUGHNESS, W.OUTLINE_ROUGHNESS_LOW_ORDER):
        budget = r * slope * 2 * math.pi / v
        print(f'    lobes={lobes} roughness={r}: 预算 {budget:.4f} rad '
              f'= {math.degrees(budget):.2f}°  {"OK" if budget < 0.786 else "超限"}')
    print()
