# -*- coding: utf-8 -*-
"""定点抽样 + 扫描线，判定 NMC 拼图底图各色块的语义（陆/海/外域/纹理）。只读。"""
from __future__ import annotations

import os
import sys
from collections import Counter

from PIL import Image

SRC = r"C:\Users\12921\Desktop\ALC\.run\_scratch\nmc"


def newest():
    fs = [os.path.join(SRC, f) for f in os.listdir(SRC)
          if f.startswith("nmc_") and f.upper().endswith(".PNG")]
    fs.sort(key=os.path.getmtime)
    return fs[-1]


def main() -> int:
    im = Image.open(newest()).convert("RGB")
    W, H = im.size
    px = im.load()
    print(f"{os.path.basename(newest())} {W}x{H}")

    print("\n== A) 四角与边中抽样 ==")
    pts = [("左上", 6, 6), ("上中", W // 2, 6), ("右上", W - 7, 6),
           ("左中", 6, H // 2), ("正中", W // 2, H // 2), ("右中", W - 7, H // 2),
           ("左下", 6, H - 100), ("下中", W // 2, H - 100), ("右下", W - 7, H - 100)]
    for name, x, y in pts:
        c = px[x, y]
        print(f"  {name} ({x:>3},{y:>3}) #{c[0]:02x}{c[1]:02x}{c[2]:02x} rgb={c}")

    print("\n== B) 横扫描线 y=150 / y=350 / y=520（每 25px 一点） ==")
    for y in (150, 350, 520):
        row = []
        for x in range(5, W, 25):
            c = px[x, y]
            row.append(f"{x}:{c[0]:02x}{c[1]:02x}{c[2]:02x}")
        print(f"  y={y}: " + " ".join(row))

    print("\n== C) 竖扫描线 x=100 / x=400 / x=700 ==")
    for x in (100, 400, 700):
        col = []
        for y in range(5, H - 110, 30):
            c = px[x, y]
            col.append(f"{y}:{c[0]:02x}{c[1]:02x}{c[2]:02x}")
        print(f"  x={x}: " + " ".join(col))

    print("\n== D) 全图低频色（合并非常接近的） top-25 ==")
    cnt = Counter()
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            c = px[x, y]
            k = (c[0] // 8 * 8, c[1] // 8 * 8, c[2] // 8 * 8)
            cnt[k] += 1
    tot = sum(cnt.values())
    for c, n in cnt.most_common(25):
        print(f"  #{c[0]:02x}{c[1]:02x}{c[2]:02x}  {n:>6}  {n / tot * 100:6.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
