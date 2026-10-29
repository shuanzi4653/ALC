# -*- coding: utf-8 -*-
"""提取 NMC 拼图的「中国陆地掩膜」并打印 ASCII 形状，验证配准可行性。只读。"""
from __future__ import annotations

import os
import sys

from PIL import Image

SRC = r"C:\Users\12921\Desktop\ALC\.run\_scratch\nmc"
SEA = (179, 230, 255)
FLAT = (229, 229, 229)   # 中国以外陆地/边衬
LINE = (204, 204, 204)   # 界线


def newest():
    fs = [os.path.join(SRC, f) for f in os.listdir(SRC)
          if f.startswith("nmc_") and f.upper().endswith(".PNG")]
    fs.sort(key=os.path.getmtime)
    return fs[-1]


def near(c, t, tol):
    return abs(c[0] - t[0]) <= tol and abs(c[1] - t[1]) <= tol and abs(c[2] - t[2]) <= tol


def build_mask(px, W, H, ymax):
    """中国陆地：低饱和 + 高亮 + 不是平灰 #e5e5e5 + 不是界线灰 #cccccc。"""
    m = [[0] * W for _ in range(ymax)]
    for y in range(ymax):
        for x in range(W):
            c = px[x, y]
            sat = max(c) - min(c)
            if sat > 14:
                continue
            if max(c) < 195 or max(c) > 254:
                continue
            if near(c, FLAT, 5) or near(c, LINE, 5):
                continue
            m[y][x] = 1
    return m


def main() -> int:
    im = Image.open(newest()).convert("RGB")
    W, H = im.size
    px = im.load()
    ymax = H - 46          # 图例带上沿大致位置
    m = build_mask(px, W, H, ymax)
    tot = sum(sum(r) for r in m)
    print(f"{os.path.basename(newest())} {W}x{H}  中国陆地掩膜像元={tot} ({tot/(W*ymax)*100:.1f}%)")

    CW, CH = 110, 54
    print("\n  掩膜 ASCII（# = 判为中国陆地）")
    print("   " + "".join(str((i // 10) % 10) for i in range(CW)))
    print("   " + "".join(str(i % 10) for i in range(CW)))
    for cy in range(CH):
        y0 = int(cy * ymax / CH)
        y1 = max(y0 + 1, int((cy + 1) * ymax / CH))
        line = []
        for cx in range(CW):
            x0 = int(cx * W / CW)
            x1 = max(x0 + 1, int((cx + 1) * W / CW))
            s = 0
            n = 0
            for y in range(y0, y1):
                for x in range(x0, x1):
                    s += m[y][x]
                    n += 1
            line.append('#' if s / n > 0.5 else ('+' if s / n > 0.2 else ' '))
        print(f"{cy:>2} " + "".join(line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
