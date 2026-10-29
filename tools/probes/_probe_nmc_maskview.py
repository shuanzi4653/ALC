# -*- coding: utf-8 -*-
"""把掩膜画到原图上（青=中国陆地掩膜，品红=海洋掩膜），看它到底抓到了什么。只读。"""
from __future__ import annotations

import os
import sys

from PIL import Image

SRC = r"C:\Users\12921\Desktop\ALC\.run\_scratch\nmc"
SEA = (179, 230, 255)
FLAT = (229, 229, 229)
LINE = (204, 204, 204)


def newest():
    fs = [os.path.join(SRC, f) for f in os.listdir(SRC)
          if f.startswith("nmc_") and f.upper().endswith(".PNG")]
    fs.sort(key=os.path.getmtime)
    return fs[-1]


def near(c, t, tol=5):
    return abs(c[0] - t[0]) <= tol and abs(c[1] - t[1]) <= tol and abs(c[2] - t[2]) <= tol


def main() -> int:
    im = Image.open(newest()).convert('RGB')
    W, H = im.size
    px = im.load()
    ymax = H - 46
    ov = im.copy()
    o = ov.load()
    land = sea = 0
    for y in range(ymax):
        for x in range(W):
            c = px[x, y]
            sat = max(c) - min(c)
            if near(c, SEA, 6):
                o[x, y] = (255, 0, 255)
                sea += 1
                continue
            if sat > 14 or max(c) < 195 or max(c) > 254 or near(c, FLAT) or near(c, LINE):
                continue
            o[x, y] = (0, 200, 200)
            land += 1
    print(f"land={land} sea={sea}")
    out = os.path.join(SRC, 'mask_overlay.png')
    ov.save(out)
    print(f"-> {out}")

    # 统计掩膜的列/行分布，找出污染带
    print("\n== 掩膜列分布（每 25 列一格的计数） ==")
    for x0 in range(0, W, 25):
        n = sum(1 for y in range(ymax) for x in range(x0, min(W, x0 + 25))
                if o[x, y] == (0, 200, 200))
        print(f"  x[{x0:>3},{x0+24:>3}] {n:>6} {'#' * min(60, n // 60)}")
    print("\n== 掩膜行分布（每 20 行一格） ==")
    for y0 in range(0, ymax, 20):
        n = sum(1 for y in range(y0, min(ymax, y0 + 20)) for x in range(W)
                if o[x, y] == (0, 200, 200))
        print(f"  y[{y0:>3},{y0+19:>3}] {n:>6} {'#' * min(60, n // 60)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
