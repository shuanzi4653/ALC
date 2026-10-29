# -*- coding: utf-8 -*-
"""拆解 NMC 全国雷达拼图 PNG：图例色标 / 插图小窗 / 底图配色。

只读。不改任何业务文件。
输出用于回答两个问题：
  Q1 配色→dBZ 能不能**从图里读出来**（而不是猜）？
  Q2 底图（省界/标注/南海诸岛插图）会不会污染回波像元？
"""
from __future__ import annotations

import io
import os
import sys
from collections import Counter

from PIL import Image

SRC = r"C:\Users\12921\Desktop\ALC\.run\_scratch\nmc"


def newest():
    files = [os.path.join(SRC, f) for f in os.listdir(SRC) if f.upper().endswith(".PNG")]
    files.sort(key=os.path.getmtime)
    return files[-1]


def main() -> int:
    path = newest()
    im = Image.open(path).convert("RGB")
    W, H = im.size
    px = im.load()
    print(f"file={os.path.basename(path)} size={W}x{H}")

    # ---- 1) 找图例色带：在图像下半部分，逐行统计"高饱和"像元数 ----
    def sat(c):
        r, g, b = c
        return max(c) - min(c)

    print("\n== 1) 图像下半部逐行的饱和像元数（找色标带） ==")
    rows = []
    for y in range(H // 2, H):
        n = sum(1 for x in range(0, W, 2) if sat(px[x, y]) > 60)
        rows.append((y, n))
    peak = max(rows, key=lambda t: t[1])
    print(f"  峰值行 y={peak[0]} 饱和数={peak[1]}")
    band = [y for y, n in rows if n > peak[1] * 0.5]
    y0, y1 = min(band), max(band)
    print(f"  色标带 y ∈ [{y0}, {y1}]  厚度 {y1 - y0 + 1}")
    for y, n in rows:
        if y0 - 4 <= y <= y1 + 4:
            print(f"    y={y:<4} sat={n}")

    # ---- 2) 在色标带里逐列取色 → 精确调色板 ----
    print("\n== 2) 色标带逐列取色（列中位色） ==")
    mid = (y0 + y1) // 2
    cols = []
    for x in range(W):
        col = [px[x, y] for y in range(y0, y1 + 1)]
        c = Counter(col).most_common(1)[0][0]
        cols.append(c)
    # 找出连续同色段
    segs = []
    start = 0
    for x in range(1, W + 1):
        if x == W or cols[x] != cols[start]:
            if x - start >= 2:
                segs.append((start, x - 1, cols[start], x - start))
            start = x
    sat_segs = [s for s in segs if sat(s[2]) > 60 or (s[2] != (255, 255, 255) and s[3] >= 6)]
    print(f"  连续同色段共 {len(segs)}；疑似色标段 {len(sat_segs)}")
    for a, b, c, w in sat_segs:
        print(f"    x[{a:>4},{b:>4}] w={w:<4} #{c[0]:02x}{c[1]:02x}{c[2]:02x} rgb={c}")

    # ---- 3) 全图配色分类 ----
    print("\n== 3) 全图配色分类（按饱和度/亮度） ==")
    cnt = Counter()
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            c = px[x, y]
            s = sat(c)
            mx = max(c)
            if s <= 12:
                k = "灰/黑/白(低饱和)" if mx < 90 else ("白/极浅" if mx > 240 else "灰阶")
            else:
                # 色相粗分
                r, g, b = c
                if g >= r and g >= b:
                    k = "绿系" if not (r > 150 and g > 150 and b < 120) else "黄绿"
                elif r >= g and r >= b:
                    k = "红/品系"
                else:
                    k = "蓝/青系"
            cnt[k] += 1
    total = sum(cnt.values())
    for k, n in cnt.most_common():
        print(f"    {k:<18} {n:>7}  {n / total * 100:6.2f}%")

    # ---- 4) 插图小窗探测：找竖直/水平长直线（边框） ----
    print("\n== 4) 插图小窗（南海诸岛）边框探测 ==")
    dark_rows = []
    for y in range(0, H):
        n = sum(1 for x in range(0, W // 2) if max(px[x, y]) < 150)
        dark_rows.append((y, n))
    cand = [t for t in dark_rows if t[1] > W * 0.12]
    print(f"  左半区深色横线候选行数={len(cand)}  前 12: {cand[:12]}")
    dark_cols = []
    for x in range(0, W // 2):
        n = sum(1 for y in range(H // 3, H) if max(px[x, y]) < 150)
        dark_cols.append((x, n))
    candc = [t for t in dark_cols if t[1] > H * 0.10]
    print(f"  左半区深色竖线候选列数={len(candc)}  前 12: {candc[:12]}")

    # ---- 5) 地图绘图区（去掉图例/白边） ----
    print("\n== 5) 绘图区估计 ==")
    print(f"  由 1) 知色标带 y≥{y0} ⇒ 绘图区 y < {y0 - 6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
