# -*- coding: utf-8 -*-
"""把最优拟合结果在几个地标处放大裁切，供人眼判定配准误差量级。只读。"""
from __future__ import annotations

import os
import sys

from PIL import Image

SRC = r"C:\Users\12921\Desktop\ALC\.run\_scratch\nmc"


def main() -> int:
    src = os.path.join(SRC, 'overlay_best_lambert25_47.png')
    im = Image.open(src).convert('RGB')
    W, H = im.size
    jobs = [
        ('lm_hainan_taiwan', (400, 520, 700, 700), 2),
        ('lm_northeast', (600, 60, 825, 260), 2),
        ('lm_xinjiang', (30, 130, 330, 330), 2),
        ('lm_bohai_shandong', (480, 250, 720, 450), 2),
    ]
    for name, box, sc in jobs:
        c = im.crop(box)
        c = c.resize((c.width * sc, c.height * sc), Image.LANCZOS)
        p = os.path.join(SRC, f'{name}.png')
        c.save(p)
        print(f'{name}: {box} -> {p} {c.width}x{c.height}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
