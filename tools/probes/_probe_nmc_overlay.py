# -*- coding: utf-8 -*-
"""把拟合出的中国轮廓叠画到 NMC 拼图上，供人眼判定配准是否成立。只读。"""
from __future__ import annotations

import json
import math
import os
import sys

from PIL import Image, ImageDraw

SRC = r"C:\Users\12921\Desktop\ALC\.run\_scratch\nmc"
CHINA = r"C:\Users\12921\Desktop\ALC\frontend\src\assets\china.json"

# 上一轮 equirect 的拟合结果（锚点 = (73.50, 53.56)）
PARAMS = {'x0': -47.50, 'y0': -112.00, 'kx': 12.5683, 'ky': 12.8329}
ANCHOR = (73.50, 53.56)


def newest():
    fs = [os.path.join(SRC, f) for f in os.listdir(SRC)
          if f.startswith("nmc_") and f.upper().endswith(".PNG")]
    fs.sort(key=os.path.getmtime)
    return fs[-1]


def rings(geo):
    out = []
    t = geo.get('type')
    cs = geo.get('coordinates') or []
    polys = [cs] if t == 'Polygon' else (cs if t == 'MultiPolygon' else [])
    for poly in polys:
        for ring in poly:
            if len(ring) >= 4:
                out.append(ring)
    return out


def main() -> int:
    im = Image.open(newest()).convert('RGB')
    d = ImageDraw.Draw(im)
    data = json.load(open(CHINA, encoding='utf-8'))
    for ft in data['features']:
        for ring in rings(ft['geometry']):
            pts = [(PARAMS['x0'] + (lon - ANCHOR[0]) * PARAMS['kx'],
                    PARAMS['y0'] - (lat - ANCHOR[1]) * PARAMS['ky'])
                   for lon, lat in ring]
            if len(pts) >= 3:
                d.line(pts + [pts[0]], fill=(255, 0, 0), width=1)
    out = os.path.join(SRC, 'overlay_equirect.png')
    im.save(out)
    print(f"-> {out}")

    # 再画一版只保留省级中心点，便于肉眼核对
    im2 = Image.open(newest()).convert('RGB')
    d2 = ImageDraw.Draw(im2)
    for ft in data['features']:
        c = ft['properties'].get('center')
        if not c:
            continue
        x = PARAMS['x0'] + (c[0] - ANCHOR[0]) * PARAMS['kx']
        y = PARAMS['y0'] - (c[1] - ANCHOR[1]) * PARAMS['ky']
        d2.ellipse([x - 4, y - 4, x + 4, y + 4], outline=(255, 0, 0), width=2)
    out2 = os.path.join(SRC, 'overlay_centers.png')
    im2.save(out2)
    print(f"-> {out2}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
