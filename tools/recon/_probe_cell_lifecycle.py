"""Check the split-cell model across seeds, and the life cycle curve itself."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import math
from pathlib import Path


from traffic import weather  # noqa: E402

print('=' * 78)
print('F1. 分裂单体：跨 seed 统计')
print('=' * 78)
seeds = [1, 7, 13, 42, 99, 2026]
total_parents = 0
for seed in seeds:
    w = weather.NetworkWeather(seed, 'moving')
    kids = [c for c in w.cells if c.get('parent')]
    total_parents += len(kids)
    print(f'  seed {seed:>5}: 单体总数 {len(w.cells):>3}  分裂产生 {len(kids)} 个'
          + ('  ' + ', '.join(f"{c['id']}(母线{c['parent']})" for c in kids) if kids else ''))
print(f'  合计 {total_parents} 个分裂单体（CELL_SPLIT_SHARE=0.12 x 20 单体 x 6 seed ≈ 14 期望值）')

print()
print('=' * 78)
print('F2. 分裂间隙随时间的变化（找一组真实的分裂）')
print('=' * 78)
found = False
for seed in seeds:
    w = weather.NetworkWeather(seed, 'moving')
    for child in [c for c in w.cells if c.get('parent')]:
        parent = next((c for c in w.cells if c['id'] == child['parent']), None)
        if parent is None:
            continue
        rows = []
        for t in range(0, 480, 20):
            if not (w.is_alive(child, t) and w.is_alive(parent, t)):
                continue
            cx, cy = w.centre_at(child, t)
            px, py = w.centre_at(parent, t)
            gap = (math.dist((cx, cy), (px, py))
                   - w.radius_at(child, t) - w.radius_at(parent, t))
            rows.append((t, gap / 1000))
        if len(rows) < 3:
            continue
        found = True
        span = rows[-1][1] - rows[0][1]
        print(f"  seed {seed}  {child['id']}  ←  {parent['id']}")
        print('    分钟/间隙(km): ' + '  '.join(f'{t}:{g:.0f}' for t, g in rows))
        print(f'    间隙变化 {span:+.1f} km  '
              f'（{"分离中" if span > 0.5 else "未分离或接近中"}）')
        break
    if found:
        break

print()
print('=' * 78)
print('F3. 生命周期曲线形状（radius_at 归一化）')
print('=' * 78)
w = weather.NetworkWeather(42, 'moving')
cell = next(c for c in w.cells if c['shape'] == 'RING' and c.get('lifeMinutes'))
life = cell['lifeMinutes']
birth = cell['birth']
print(f"  {cell['id']}  出生 {birth:.1f} min  寿命 {life:.1f} min  "
      f"名义半径 {cell['radius']/1000:.2f} km")
print(f"  {weather.CELL_PEAK_AGE_FRACTION=}  {weather.CELL_MIN_SIZE_FRACTION=}")
pts = []
for k in range(0, 21):
    t = birth + life * k / 20
    pts.append((k / 20, w.radius_at(cell, t) / cell['radius']))
print('  progress/radius比: ' + '  '.join(f'{p:.2f}:{r:.2f}' for p, r in pts[::2]))
peak_at = max(pts, key=lambda x: x[1])
print(f'  峰值出现在 progress={peak_at[0]:.2f}，峰值比 {peak_at[1]:.3f}')
print(f'  生前 (t=birth-10) 半径 {w.radius_at(cell, birth-10):.1f} m')
print(f'  死后 (t=birth+life+10) 半径 {w.radius_at(cell, birth+life+10):.1f} m')

print()
print('=' * 78)
print('F4. 时轴上的可见单体数（云团应当有增有减）')
print('=' * 78)
w = weather.NetworkWeather(42, 'moving')
counts = []
for t in range(0, 480, 10):
    live = [c for c in w.cells if w.is_alive(c, t) and w.radius_at(c, t) >= weather.MIN_VISIBLE_RADIUS_M]
    counts.append((t, len(live)))
print('  分钟:数量  ' + ' '.join(f'{t}:{n}' for t, n in counts))
vals = [n for _, n in counts]
print(f'  范围 {min(vals)}–{max(vals)}，首个非零点 t={next(t for t, n in counts if n)}')
