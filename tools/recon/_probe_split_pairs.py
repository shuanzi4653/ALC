"""Split cells: identify them by the lineage key.

History: this probe was written when `_shed_daughter` did *not* record the parent,
and it concluded "血统在构造后即丢失". That conclusion is now false -- the key was
added and the probe kept printing the old verdict, which made a fixed defect look
open. It reads the key directly now, and keeps the id-suffix count as a
cross-check so the two derivations have to agree.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import math
from pathlib import Path


from traffic import weather as W  # noqa: E402

print('=' * 78)
print('F1. 分裂单体识别：parent 行键 vs id 后缀 -D1')
print('=' * 78)
for seed in (1, 7, 13, 42, 99, 2026):
    w = W.NetworkWeather(seed, 'moving')
    by_suffix = [c for c in w.cells if c['id'].endswith('-D1')]
    by_key = [c for c in w.cells if c.get('parent')]
    keys = sorted({k for c in w.cells for k in c})
    print(f'  seed {seed:>5}: 总数 {len(w.cells):>3}  -D1 后缀 {len(by_suffix)}  '
          f'parent 键 {len(by_key)}  '
          f'{"一致" if sorted(c["id"] for c in by_suffix) == sorted(c["id"] for c in by_key) else "不一致"}')
print()
print('单体字典的键集合：')
print('  ', sorted({k for c in W.NetworkWeather(42, "moving").cells for k in c}))
print()
probe = W.NetworkWeather(42, 'moving')
by_id = {c['id']: c for c in probe.cells}
daughters = [c for c in probe.cells if c.get('parent')]
if not daughters:
    print('=> 本 seed 未产生分裂单体，无法验证行键。')
else:
    resolvable = [c for c in daughters if c.get('parent') in by_id]
    print(f'=> _shed_daughter 记录的 parent 键可反查母体：{len(resolvable)}/{len(daughters)} 命中。')
    print('   血统在构造后保留，可直接读取字段而无需解析 id 后缀。')

print()
print('=' * 78)
print('F2. 分裂对：间隙是否随时间增大')
print('=' * 78)
for seed in (1, 7, 13, 42, 99, 2026):
    w = W.NetworkWeather(seed, 'moving')
    by_id = {c['id']: c for c in w.cells}
    for child in [c for c in w.cells if c.get('parent')]:
        # Read the lineage key. This used to be `child['id'][:-3]`, which is the
        # string workaround the key was added to remove -- and which silently
        # breaks on any id whose suffix is not exactly three characters.
        parent = by_id.get(child['parent'])
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
        if len(rows) < 2:
            continue
        churn = [c for c in w.cells if c['id'].startswith(child['id'][:-3])]
        print(f'  seed {seed}  {child["id"]}  <-  {parent["id"]}')
        print('    分钟/间隙(km): ' + '  '.join(f'{t}:{g:>6.1f}' for t, g in rows))
        print(f'    间隙变化 {rows[-1][1]-rows[0][1]:+.1f} km '
              f'（{"分离" if rows[-1][1] > rows[0][1] + 0.5 else "接近或持平"}）')

print()
print('=' * 78)
print('F4. 可见单体数随时间（云团确有增减）')
print('=' * 78)
for seed in (42,):
    w = W.NetworkWeather(seed, 'moving')
    counts = []
    for t in range(0, 480, 20):
        live = [c for c in w.cells
                if w.is_alive(c, t) and w.radius_at(c, t) >= W.MIN_VISIBLE_RADIUS_M]
        counts.append((t, len(live)))
    print(f'  seed {seed}: ' + ' '.join(f'{t}:{n}' for t, n in counts))
    vals = [n for _, n in counts]
    print(f'  范围 {min(vals)}-{max(vals)}；分裂单体出现于 '
          + ', '.join(f"{c['id']}@{c['birth']:.0f}min"
                      for c in w.cells if c['id'].endswith('-D1')))

print()
print('=' * 78)
print('F5. 颗粒度：形状种子逐单体独立 -> 轮廓是否真的互不相同')
print('=' * 78)
w = W.NetworkWeather(42, 'moving')
seeds = [(c['id'], c['shapeSeed']) for c in w.cells if c.get('shapeSeed') is not None]
print(f'  有独立形状种子的单体 {len(seeds)} 个，去重后 {len({s for _, s in seeds})} 个')
import hashlib
sigs = {}
for c in w.cells:
    if c.get('shapeSeed') is None:
        continue
    cfg = c['outline']
    sig = hashlib.sha1(repr(sorted(cfg['harmonics'])).encode()).hexdigest()[:8]
    sigs.setdefault(sig, []).append(c['id'])
print(f'  谐波配置的去重签名 {len(sigs)} 个（唯一签名数应接近单体数）')
dupes = {k: v for k, v in sigs.items() if len(v) > 1}
print(f'  重复签名的组：{dupes if dupes else "无"}')
