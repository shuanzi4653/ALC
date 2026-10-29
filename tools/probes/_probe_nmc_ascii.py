# -*- coding: utf-8 -*-
"""把 NMC 拼图降采样成 ASCII 结构图，看清陆地/海洋/回波/插图的分布。只读。"""
from __future__ import annotations

import os
import sys

from PIL import Image

SRC = r"C:\Users\12921\Desktop\ALC\.run\_scratch\nmc"


def newest():
    fs = [os.path.join(SRC, f) for f in os.listdir(SRC)
          if f.startswith("nmc_") and f.upper().endswith(".PNG")]
    fs.sort(key=os.path.getmtime)
    return fs[-1]


SEA = (179, 230, 255)


def cls(c):
    r, g, b = c
    mx, mn = max(c), min(c)
    sat = mx - mn
    # 海洋：以 #b3e6ff 为中心
    if abs(r - SEA[0]) < 12 and abs(g - SEA[1]) < 12 and abs(b - SEA[2]) < 12:
        return '~'
    if sat > 55 and mx > 120:
        # 有色 → 回波；再按色相粗分
        if b >= r and b >= g:
            return 'B'      # 蓝青（弱回波）
        if g >= r and g >= b:
            return 'G'      # 绿（层状）
        return 'R'          # 红/黄/品（强回波）
    if mx > 250:
        return '.'          # 近白
    if mx < 120:
        return 'X'          # 深色（线/标注）
    return '#'              # 灰（陆地/底图）


def main() -> int:
    im = Image.open(newest()).convert("RGB")
    W, H = im.size
    px = im.load()
    CW, CH = 110, 56
    print(f"{os.path.basename(newest())} {W}x{H}  -> ASCII {CW}x{CH}")
    print("   图例: ~海  #灰(陆)  .近白  X深色线  B蓝青回波  G绿回波  R强回波")
    print("   " + "".join(str((i // 10) % 10) for i in range(CW)))
    print("   " + "".join(str(i % 10) for i in range(CW)))
    for cy in range(CH):
        y0 = int(cy * H / CH)
        y1 = max(y0 + 1, int((cy + 1) * H / CH))
        line = []
        for cx in range(CW):
            x0 = int(cx * W / CW)
            x1 = max(x0 + 1, int((cx + 1) * W / CW))
            # 取块内"最有信息"的类别：回波 > 深色 > 海 > 灰
            votes = {}
            for y in range(y0, y1, max(1, (y1 - y0) // 4)):
                for x in range(x0, x1, max(1, (x1 - x0) // 4)):
                    k = cls(px[x, y])
                    votes[k] = votes.get(k, 0) + 1
            for pref in ('R', 'G', 'B', 'X', '~', '.', '#'):
                if votes.get(pref):
                    if pref in ('R', 'G', 'B') and votes[pref] < 1:
                        continue
                    line.append(pref)
                    break
            else:
                line.append('?')
        print(f"{cy:>2} " + "".join(line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
