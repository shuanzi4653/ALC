# -*- coding: utf-8 -*-
"""NMC 拼图地理配准验证 v2：归一化参数化 + 容差匹配，四模型可比。只读。

失败史（本文件 v1 的两个坑，都记下来以免重犯）：
 1) 小画布上用全分辨率坐标 → 多边形被放大 STEP 倍，优化器在错误空间爬坡。
 2) 步长按 equirect 的量纲调好，Lambert 输出的量纲完全不同 → 后两者恒 0。
    ⇒ 所有模型先把投影输出归一化到 [0,1]，再拟合像素位置与尺寸。
"""
from __future__ import annotations

import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

SRC = r"C:\Users\12921\Desktop\ALC\.run\_scratch\nmc"
CHINA = r"C:\Users\12921\Desktop\ALC\frontend\src\assets\china.json"
SEA = (179, 230, 255)
FLAT = (229, 229, 229)
LINE = (204, 204, 204)
STEP = 3


def newest():
    fs = [os.path.join(SRC, f) for f in os.listdir(SRC)
          if f.startswith("nmc_") and f.upper().endswith(".PNG")]
    fs.sort(key=os.path.getmtime)
    return fs[-1]


def near(c, t, tol=5):
    return abs(c[0] - t[0]) <= tol and abs(c[1] - t[1]) <= tol and abs(c[2] - t[2]) <= tol


def detect_inset(px, W, H):
    rows, cols = [], []
    for y in range(int(H * 0.35), H - 60):
        run = best = 0
        for x in range(0, int(W * 0.45)):
            if max(px[x, y]) < 170:
                run += 1
                best = max(best, run)
            else:
                run = 0
        if best > W * 0.12:
            rows.append(y)
    for x in range(0, int(W * 0.45)):
        run = best = 0
        for y in range(int(H * 0.35), H - 60):
            if max(px[x, y]) < 170:
                run += 1
                best = max(best, run)
            else:
                run = 0
        if best > H * 0.10:
            cols.append(x)
    if not rows or not cols:
        return None
    return (min(cols), min(rows), max(cols), max(rows))


def build_masks(px, W, H, ymax):
    land = bytearray(W * ymax)
    sea = bytearray(W * ymax)
    for y in range(ymax):
        base = y * W
        for x in range(W):
            c = px[x, y]
            if near(c, SEA, 6):
                sea[base + x] = 1
                continue
            if max(c) - min(c) > 14 or max(c) < 195 or max(c) > 254:
                continue
            if near(c, FLAT) or near(c, LINE):
                continue
            land[base + x] = 1
    return land, sea


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


def _lambert(p1, p2):
    p1r, p2r = math.radians(p1), math.radians(p2)
    n = math.log(math.cos(p1r) / math.cos(p2r)) / math.log(
        math.tan(math.pi / 4 + p2r / 2) / math.tan(math.pi / 4 + p1r / 2))
    F = math.cos(p1r) * math.tan(math.pi / 4 + p1r / 2) ** n / n
    rho0 = F / math.tan(math.pi / 4 + p1r / 2) ** n

    def f(lon, lat):
        rho = F / math.tan(math.pi / 4 + math.radians(lat) / 2) ** n
        th = n * math.radians(lon - 105.0)
        return (rho * math.sin(th), rho0 - rho * math.cos(th))
    return f


def _merc(lon, lat):
    return (lon, math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))))


PROJ = {
    'equirect': lambda lon, lat: (lon, lat),
    'mercator': _merc,
    'lambert25_47': _lambert(25, 47),
    'lambert30_60': _lambert(30, 60),
    'lambert38_50': _lambert(38, 50),
}


def main() -> int:
    path = newest()
    im = Image.open(path).convert('RGB')
    W, H = im.size
    px = im.load()
    ymax = H - 46
    print(f"{os.path.basename(path)} {W}x{H}  STEP={STEP}")

    box = detect_inset(px, W, H)
    pad = 4
    exclude = (max(0, box[0] - pad), max(0, box[1] - pad),
               min(W - 1, box[2] + pad), min(ymax, box[3] + pad)) if box else (0, 380, 250, ymax)
    print(f"插图小窗 box={box}  屏蔽区={exclude}")

    land, sea = build_masks(px, W, H, ymax)
    if exclude:
        for y in range(exclude[1], min(exclude[3], ymax)):
            for x in range(exclude[0], exclude[2]):
                land[y * W + x] = 0
                sea[y * W + x] = 0
    print(f"中国陆地掩膜={sum(land)}  海洋掩膜={sum(sea)}")

    data = json.load(open(CHINA, encoding='utf-8'))
    polys = []
    for ft in data['features']:
        polys.extend(rings(ft['geometry']))
    ls = [p for r in polys for p in r]
    lo0, lo1 = min(p[0] for p in ls), max(p[0] for p in ls)
    la0, la1 = min(p[1] for p in ls), max(p[1] for p in ls)
    print(f"参照环数={len(polys)}  经度[{lo0:.2f},{lo1:.2f}] 纬度[{la0:.2f},{la1:.2f}]")

    # 掩膜稳健 bbox（阈值法）
    W2, H2 = W // STEP, H // STEP
    colsum = [0] * W
    rowsum = [0] * ymax
    for y in range(ymax):
        base = y * W
        for x in range(W):
            if land[base + x]:
                colsum[x] += 1
                rowsum[y] += 1
    xs = [x for x in range(W) if colsum[x] >= 12]
    ys = [y for y in range(ymax) if rowsum[y] >= 12]
    mx0, mx1, my0, my1 = min(xs), max(xs), min(ys), max(ys)
    print(f"掩膜稳健 bbox x[{mx0},{mx1}] y[{my0},{my1}]  ({mx1-mx0}x{my1-my0})")

    # 掩膜膨胀 r=1（格），做容差匹配
    mimg = Image.new('L', (W, ymax), 0)
    mimg.putdata(bytes(land))
    small = mimg.resize((W2, H2), Image.NEAREST)
    dil = small.filter(ImageFilter.MaxFilter(3))
    dil_px = dil.load()

    def make_norm(model):
        f = PROJ[model]
        uv = [f(lon, lat) for lon, lat in ls]
        us = [a for a, _ in uv]
        vs = [b for _, b in uv]
        u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
        du, dv = max(1e-9, u1 - u0), max(1e-9, v1 - v0)
        out = []
        for r in polys:
            rr = []
            for lon, lat in r:
                a, b = f(lon, lat)
                rr.append(((a - u0) / du, (b - v0) / dv))
            out.append(rr)
        return out

    def raster(nr, p):
        img = Image.new('1', (W2, H2), 0)
        d = ImageDraw.Draw(img)
        for rr in nr:
            pts = [((p[0] + a * p[2]) / STEP, (p[1] + (1 - b) * p[3]) / STEP) for a, b in rr]
            if len(pts) >= 3:
                d.polygon(pts, fill=1)
        return img

    def dice(img):
        p_ = img.load()
        inter = n1 = n2 = 0
        for j in range(H2):
            y = j * STEP
            if y >= ymax or (exclude and exclude[1] <= y <= exclude[3]):
                continue
            for i in range(W2):
                x = i * STEP
                if x >= W or (exclude and exclude[0] <= x <= exclude[2]):
                    continue
                a = p_[i, j]
                b = dil_px[i, j]
                if a:
                    n1 += 1
                if b:
                    n2 += 1
                if a and b:
                    inter += 1
        return (2 * inter / (n1 + n2)) if (n1 + n2) else 0.0

    results = {}
    for model in PROJ:
        nr = make_norm(model)
        p = [mx0, my0, mx1 - mx0, my1 - my0]
        best = dice(raster(nr, p))
        for rnd, sp in enumerate([(0.30, 60), (0.12, 30), (0.05, 12), (0.02, 5)]):
            frac, span = sp
            for i in range(4):
                for k in range(-6, 7):
                    cand = list(p)
                    cand[i] = p[i] + k * span / 6
                    if i >= 2 and cand[i] < 20:
                        continue
                    s = dice(raster(nr, cand))
                    if s > best:
                        best, p = s, cand
        results[model] = (best, p)
        print(f"\n== {model} ==  Dice(容差膨胀1格)={best:.4f}")
        print(f"   参数 X0={p[0]:.1f} Y0={p[1]:.1f} W={p[2]:.1f} H={p[3]:.1f}")
        # 反解：经纬度 → 像素
        f = PROJ[model]
        uvs = [f(lon, lat) for lon, lat in ls]
        us = [a for a, _ in uvs]
        vs = [b for _, b in uvs]
        u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
        def to_xy(lon, lat):
            a, b = f(lon, lat)
            un = (a - u0) / max(1e-9, u1 - u0)
            vn = (b - v0) / max(1e-9, v1 - v0)
            return p[0] + un * p[2], p[1] + (1 - vn) * p[3]
        for name, lon, lat in [('北京', 116.4, 39.9), ('乌鲁木齐', 87.6, 43.8),
                               ('广州', 113.3, 23.1), ('哈尔滨', 126.6, 45.8),
                               ('拉萨', 91.1, 29.7), ('三亚', 109.5, 18.25)]:
            x, y = to_xy(lon, lat)
            print(f"     {name:<6} -> ({x:6.1f},{y:6.1f})")
        print()

    print("\n== 结论 ==")
    for m, (s, _) in sorted(results.items(), key=lambda t: -t[1][0]):
        v = "可行" if s >= 0.90 else ("可用" if s >= 0.85 else ("勉强" if s >= 0.75 else "不可行"))
        print(f"  {m:<16} Dice={s:.4f}  {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
