# -*- coding: utf-8 -*-
"""裁出 NMC 拼图的关键区域并放大，供人眼判读（只读）。"""
from __future__ import annotations

import os
import sys

from PIL import Image

SRC = r"C:\Users\12921\Desktop\ALC\.run\_scratch\nmc"


def newest():
    files = [os.path.join(SRC, f) for f in os.listdir(SRC) if f.upper().endswith(".PNG")]
    files.sort(key=os.path.getmtime)
    return files[-1]


def main() -> int:
    im = Image.open(newest()).convert("RGB")
    W, H = im.size
    jobs = [
        ("crop_legend_bottom", (0, H - 110, W, H), 2),
        ("crop_inset_bottomleft", (0, int(H * 0.45), int(W * 0.36), int(H * 0.95)), 2),
        ("crop_map_mid", (int(W * 0.35), int(H * 0.30), int(W * 0.85), int(H * 0.62)), 2),
    ]
    for name, box, scale in jobs:
        c = im.crop(box)
        c = c.resize((c.width * scale, c.height * scale), Image.NEAREST)
        p = os.path.join(SRC, f"{name}.png")
        c.save(p)
        print(f"{name}: box={box} -> {p} ({c.width}x{c.height})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
