# -*- coding: utf-8 -*-
"""从 NMC 拼图里精确读出图例色标（色块 + dBZ 刻度），并统计地图区配色占用。

只读。
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

from PIL import Image

SRC = r"C:\Users\12921\Desktop\ALC\.run\_scratch\nmc"


def newest():
    files = [os.path.join(SRC, f) for f in os.listdir(SRC)
             if f.startswith("nmc_") and f.upper().endswith(".PNG")]
    files.sort(key=os.path.getmtime)
    return files[-1]


def sat(c):
    return max(c) - min(c)


def find_bar_row(px, W, H):
    """找色标带：一行里饱和像元的最长连续段要跨过 55% 以上宽度。"""
    best = None
    for y in range(int(H * 0.85), H):
        run = 0
        longest = 0
        start = None
        best_start = None
        for x in range(W):
            if sat(px[x, y]) > 50 and max(px[x, y]) > 90:
                if start is None:
                    start = x
                run += 1
                if run > longest:
                    longest = run
                    best_start = start
            else:
                run = 0
                start = None
        if best is None or longest > best[1]:
            best = (y, longest, best_start)
    return best


def main() -> int:
    path = newest()
    im = Image.open(path).convert("RGB")
    W, H = im.size
    px = im.load()
    print(f"file={os.path.basename(path)} size={W}x{H}")

    y, longest, x0 = find_bar_row(px, W, H)
    print(f"\n== 色标带 ==\n  row y={y}  最长连续饱和段={longest}px  起点 x={x0}  覆盖 {longest/W*100:.1f}% 宽")

    # 在该行及上下各 2 行里取众数色，切成色块
    ys = range(y - 3, y + 4)
    row = []
    for x in range(W):
        c = Counter(px[x, yy] for yy in ys).most_common(1)[0][0]
        row.append(c)

    swatches = []
    cur = row[x0]
    start = x0
    for x in range(x0 + 1, W + 1):
        c = row[x] if x < W else None
        if c != cur:
            width = x - start
            if width >= 4:
                swatches.append({'x0': start, 'x1': x - 1, 'w': width,
                                 'rgb': cur, 'hex': '#%02x%02x%02x' % cur})
            cur = c
            start = x
    print(f"\n== 色块（宽 ≥ 4px）共 {len(swatches)} ==")
    for i, s in enumerate(swatches):
        print(f"  [{i:>2}] x[{s['x0']:>4},{s['x1']:>4}] w={s['w']:<4} {s['hex']} rgb={s['rgb']}")

    dbz = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70]
    print(f"\n== 刻度 {len(dbz)} 个：{dbz} ==")
    print(f"  色块 {len(swatches)} 个 vs 刻度 {len(dbz)} 个 -> "
          f"{'一一对应，块 i = 下标 i 的刻度' if len(swatches) == len(dbz) else '不相等，需再判'}")

    # ---- 地图区统计：把绘图区（y < 色标带上沿 - 8）按"最近调色板色"分类 ----
    pal = [tuple(s['rgb']) for s in swatches]
    ymap = y - 20
    print(f"\n== 地图区（y < {ymap}）像素与调色板的匹配情况 ==")
    hit = Counter()
    near = Counter()
    total = 0
    unmapped = Counter()
    for yy in range(0, ymap, 2):
        for xx in range(0, W, 2):
            c = px[xx, yy]
            total += 1
            best, bd = None, 10 ** 9
            for i, p in enumerate(pal):
                d = (c[0] - p[0]) ** 2 + (c[1] - p[1]) ** 2 + (c[2] - p[2]) ** 2
                if d < bd:
                    bd, best = d, i
            if bd == 0:
                hit[best] += 1
            elif bd <= 900:          # 距离 ≤ 30：抗锯齿边缘
                near[best] += 1
            else:
                unmapped[c] += 1
    print(f"  采样总数={total}")
    print(f"  精确命中调色板={sum(hit.values())} ({sum(hit.values())/total*100:.2f}%)")
    print(f"  邻近(≤30)=.{sum(near.values())} ({sum(near.values())/total*100:.2f}%)")
    print(f"  完全不属于调色板={sum(unmapped.values())} ({sum(unmapped.values())/total*100:.2f}%)")
    print("  各档精确命中（色块序号 → 像元数）：")
    for i in sorted(hit):
        print(f"    [{i:>2}] {swatches[i]['hex']}  {hit[i]}")
    print("  不属于调色板的高频色 top-15：")
    for c, n in unmapped.most_common(15):
        print(f"    #{c[0]:02x}{c[1]:02x}{c[2]:02x} rgb={c}  {n}")

    out = os.path.join(SRC, "legend_palette.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({'imageSize': [W, H], 'barRow': y, 'tickDbz': dbz,
                   'swatches': [{'index': i, 'hex': s['hex'], 'rgb': list(s['rgb']),
                                 'x0': s['x0'], 'x1': s['x1']} for i, s in enumerate(swatches)]},
                  fh, ensure_ascii=False, indent=2)
    print(f"\n  调色板落盘 -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
