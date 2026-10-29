"""Re-measure the REAL stored outline config, not a re-drawn one.

The earlier check re-drew parameters from Random(shapeSeed), which does not
reproduce the constructor's consumption order. Use cell['outline'] as stored.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import math
from pathlib import Path


from traffic import weather as W  # noqa: E402


def max_convex(poly):
    pts = list(poly.exterior.coords)
    n = len(pts) - 1
    worst = 0.0
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
            worst = max(worst, math.degrees(math.atan2(abs(cross), dot)))
    return worst


print('=' * 78)
print('真实存储 cfg 的最大凸角（跳过裁剪，直接生成轮廓）')
print('=' * 78)
print(f'{ "单体":<16}{"谐波":>4}{"最高阶":>7}{"顶点":>6}{"rough":>7}{"最大凸角":>10}  曲率预算')
print('-' * 78)
rows = []
for seed in (42, 7, 13, 1, 99, 2026):
    w = W.NetworkWeather(seed, 'moving')
    for cell in w.cells:
        if cell['shape'] != 'RING' or 'outline' not in cell:
            continue
        cfg = cell['outline']
        poly = W._irregular_outline(0, 0, cell['radius'], cfg)
        worst = max_convex(poly)
        harm = len(cfg['harmonics'])
        high = max(o for o, _, _ in cfg['harmonics'])
        v = max(24, min(W.OUTLINE_VERTICES, 24 * high // 2))
        rough = W.OUTLINE_ROUGHNESS_LOW_ORDER if harm < 4 else W.OUTLINE_ROUGHNESS
        norm = sum(a for _, a, _ in cfg['harmonics'])
        slope = sum(a * o for o, a, _ in cfg['harmonics']) / norm
        budget = math.degrees(rough * slope * 2 * math.pi / v)
        rows.append((worst, seed, cell['id'], harm, high, v, rough, budget))
rows.sort(reverse=True)
for worst, seed, cid, harm, high, v, rough, budget in rows[:14]:
    flag = '  X' if worst > 45 else ''
    print(f'  {cid:<16}{harm:>4}{high:>7}{v:>6}{rough:>7.2f}{worst:>10.2f}{flag}  '
          f'{budget:>6.2f}°')
print('-' * 78)
worsts = [r[0] for r in rows]
print(f'全部 {len(rows)} 个单体的最大凸角：中位 {sorted(worsts)[len(worsts)//2]:.2f}°  '
      f'最大 {max(worsts):.2f}°  超 45° 的 {sum(1 for x in worsts if x > 45)} 个')
print()
print('曲率预算 vs 实测凹凸角的相关性检查（预算高的单体，凸角是否真的更大）：')
print('  注意：预算是上界估计，只有顶点恰好落在斜率极值处才达到。')
hi = [r for r in rows if r[7] > 7.0]
print(f'  预算 >7° 的单体 {len(hi)} 个，其最大凸角均值 '
      f'{sum(r[0] for r in hi)/len(hi):.2f}°' if hi else '  无')
lo = [r for r in rows if r[7] <= 7.0]
print(f'  预算 <=7° 的单体 {len(lo)} 个，其最大凸角均值 '
      f'{sum(r[0] for r in lo)/len(lo):.2f}°' if lo else '  无')

print()
print('=' * 78)
print('决定性检查：把该单体轮廓逐顶点偏转角打印，看是否单点跳变')
print('=' * 78)
w = W.NetworkWeather(42, 'moving')
cell = next(c for c in w.cells if c['id'] == 'WX-1-03')
poly = W._irregular_outline(0, 0, cell['radius'], cell['outline'])
pts = list(poly.exterior.coords)
n = len(pts) - 1
print(f'  {cell["id"]}  顶点 {n}  stretch={cell["outline"]["stretch"]:.3f}')
for i in range(n):
    a, b, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
    v1 = (b[0] - a[0], b[1] - a[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    cross = v1[0] * v2[1] - v1[1] * v2[0]
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    ang = math.degrees(math.atan2(abs(cross), dot))
    if ang > 30:
        sign = '凸(尖刺)' if cross < 0 else '凹'
        print(f'    顶点 {i:>3}: 转角 {ang:>6.2f}° {sign}  '
              f'边长 {n1:>7.1f} / {n2:>7.1f} m  '
              f'半径 {math.hypot(b[0], b[1])/1000:.2f} km')
