# -*- coding: utf-8 -*-
"""NMC 拼图地理配准可行性验证（只读）。

步骤：
 1) 探测南海诸岛插图小窗的边框矩形（必须屏蔽，否则它会伪装成陆地）
 2) 建中国陆地掩膜
 3) 用 frontend/src/assets/china.json 在四种投影模型下拟合像素变换，报告 IoU 与残差
输出即判据：IoU 高 → 配准可行；IoU 低 → 这条路不通。
"""
from __future__ import annotations

import json
import math
import os
import sys

from PIL import Image, ImageDraw

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
    """插图小窗：在左半区找长的水平/竖直深色线，取包围盒。"""
    rows = []
    for y in range(int(H * 0.35), H - 60):
        run = 0
        best = 0
        for x in range(0, int(W * 0.45)):
            if max(px[x, y]) < 170:
                run += 1
                best = max(best, run)
            else:
                run = 0
        if best > W * 0.12:
            rows.append(y)
    cols = []
    for x in range(0, int(W * 0.45)):
        run = 0
        best = 0
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


def build_mask(px, W, H, ymax):
    m = bytearray(W * ymax)
    for y in range(ymax):
        base = y * W
        for x in range(W):
            c = px[x, y]
            if max(c) - min(c) > 14:
                continue
            if max(c) < 195 or max(c) > 254:
                continue
            if near(c, FLAT) or near(c, LINE):
                continue
            m[base + x] = 1
    return m


def rings(geo):
    """把 geometry 展平成环列表 [(lon,lat)...]。"""
    out = []
    t = geo.get('type')
    cs = geo.get('coordinates') or []
    if t == 'Polygon':
        polys = [cs]
    elif t == 'MultiPolygon':
        polys = cs
    else:
        return out
    for poly in polys:
        for ring in poly:
            if len(ring) >= 4:
                out.append(ring)
    return out


PROJ = {
    # name: f(lon, lat) -> (u, v)
    'equirect': lambda lon, lat: (lon, lat),
    'mercator': lambda lon, lat: (lon, math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))),
    'lambert25_47': None,   # 下面补
    'lambert30_60': None,
}


def _make_lambert(p1, p2):
    p1r, p2r = math.radians(p1), math.radians(p2)
    n = math.log(math.cos(p1r) / math.cos(p2r)) / math.log(
        math.tan(math.pi / 4 + p2r / 2) / math.tan(math.pi / 4 + p1r / 2))
    F = math.cos(p1r) * math.tan(math.pi / 4 + p1r / 2) ** n / n
    rho0 = F / math.tan(math.pi / 4 + p1r / 2) ** n

    def f(lon, lat):
        rho = F / math.tan(math.pi / 4 + math.radians(lat) / 2) ** n
        theta = n * math.radians(lon - 105.0)
        return (math.degrees(rho * math.sin(theta)), math.degrees(rho0 - rho * math.cos(theta)))
    return f


PROJ['lambert25_47'] = _make_lambert(25, 47)
PROJ['lambert30_60'] = _make_lambert(30, 60)


def rasterize(polys, params, W2, H2, model):
    """把经纬度环按 params 画到 (W2,H2) 小画布上。

    **params 是全分辨率像素单位**，而画布是 1/STEP 缩放的 ⇒ 画之前必须除 STEP。
    漏掉这一步会让多边形在画布里被放大 STEP 倍，只有一小块落进画布，于是
    优化器在一片错误的空间里"爬坡"，最终给出一个既不像中国、IoU 又不为 0 的解。
    """
    f = PROJ[model]
    img = Image.new('1', (W2, H2), 0)
    d = ImageDraw.Draw(img)
    s = 1.0 / STEP
    for ring in polys:
        pts = []
        for lon, lat in ring:
            u, v = f(lon, lat)
            pts.append(((params[0] + u * params[2]) * s, (params[1] - v * params[3]) * s))
        if len(pts) >= 3:
            d.polygon(pts, fill=1)
    return img


def iou(img, mask, W, H, exclude, ymax):
    """img 为 W2xH2（步长 STEP），mask 为 W*ymax 的 bytearray。"""
    W2, H2 = img.size
    pix = img.load()
    inter = uni = 0
    px_ = pix
    for j in range(H2):
        y = j * STEP
        if y >= ymax:
            break
        if exclude and exclude[1] <= y <= exclude[3]:
            continue
        row = y * W
        for i in range(W2):
            x = i * STEP
            if x >= W:
                break
            if exclude and exclude[0] <= x <= exclude[2]:
                continue
            a = px_[i, j]
            b = mask[row + x]
            if a and b:
                inter += 1
                uni += 1
            elif a or b:
                uni += 1
    return (inter / uni) if uni else 0.0, inter, uni


def robust_bbox(mask, W, ymax, exclude, min_run=12):
    """稳健 bbox：只认在整行/整列里有足够多掩膜像元的位置，滤掉孤立噪点。"""
    colsum = [0] * W
    rowsum = [0] * ymax
    for y in range(ymax):
        base = y * W
        for x in range(W):
            if mask[base + x]:
                if exclude and exclude[0] <= x <= exclude[2] and exclude[1] <= y <= exclude[3]:
                    continue
                colsum[x] += 1
                rowsum[y] += 1
    xs = [x for x in range(W) if colsum[x] >= min_run]
    ys = [y for y in range(ymax) if rowsum[y] >= min_run]
    return min(xs), max(xs), min(ys), max(ys)


def main() -> int:
    path = newest()
    im = Image.open(path).convert('RGB')
    W, H = im.size
    px = im.load()
    ymax = H - 46
    print(f"{os.path.basename(path)} {W}x{H}")

    box = detect_inset(px, W, H)
    print(f"\n== 1) 插图小窗边框探测 ==")
    if box is None:
        print("  未探到；按保守矩形屏蔽 x<250 且 y>380")
        exclude = (0, 380, 250, ymax)
    else:
        pad = 4
        exclude = (max(0, box[0] - pad), max(0, box[1] - pad),
                   min(W - 1, box[2] + pad), min(ymax, box[3] + pad))
        print(f"  边框 box={box} -> 屏蔽区 {exclude}")
    print(f"  屏蔽区尺寸 {exclude[2]-exclude[0]}x{exclude[3]-exclude[1]} px")

    mask = build_mask(px, W, H, ymax)
    print(f"\n== 2) 中国陆地掩膜 ==")
    print(f"  像元={sum(mask)}  占 {sum(mask)/(W*ymax)*100:.1f}%")

    data = json.load(open(CHINA, encoding='utf-8'))
    polys = []
    for ft in data['features']:
        polys.extend(rings(ft['geometry']))
    print(f"\n== 3) 参照矢量 ==\n  china.json 环数={len(polys)}")

    lons = [p[0] for r in polys for p in r]
    lats = [p[1] for r in polys for p in r]
    lo0, lo1 = min(lons), max(lons)
    la0, la1 = min(lats), max(lats)
    print(f"  经度 [{lo0:.2f},{lo1:.2f}]  纬度 [{la0:.2f},{la1:.2f}]")

    W2, H2 = W // STEP, H // STEP
    # 参考点：以 (lo0, la1) 为锚，u/v 相对该点度量
    f = PROJ['equirect']

    def anchorize(ring, model):
        ff = PROJ[model]
        u0, v0 = ff(lo0, la1)
        return [(lambda t: (t[0] - u0, t[1] - v0))(ff(lon, lat)) for lon, lat in ring]

    results = {}
    for model in PROJ:
        arings = [anchorize(r, model) for r in polys]
        mx0, mx1, my0, my1 = robust_bbox(mask, W, ymax, exclude)
        print(f"\n== 4) 模型 {model} ==")
        print(f"  掩膜稳健 bbox x[{mx0},{mx1}] y[{my0},{my1}]")

        # u/v 跨度
        us = [p[0] for r in arings for p in r]
        vs = [p[1] for r in arings for p in r]
        u0m, u1m = min(us), max(us)
        v0m, v1m = min(vs), max(vs)
        # 初值由 bbox 对齐（注意 v 向上为正、y 向下为正）
        kx = (mx1 - mx0) / max(1e-9, u1m - u0m)
        ky = (my1 - my0) / max(1e-9, v1m - v0m)
        x0 = mx0 - u0m * kx
        y0 = my0 + v1m * ky
        params = [x0, y0, kx, ky]

        def score(p):
            img = rasterize(arings, p, W2, H2, model)
            return iou(img, mask, W, H, exclude, ymax)[0]

        best = score(params)
        # 坐标下降
        for rnd in range(4):
            span = [60, 60, 2.0, 2.0] if rnd == 0 else [24, 24, 0.7, 0.7] if rnd == 1 else [9, 9, 0.25, 0.25] if rnd == 2 else [3, 3, 0.09, 0.09]
            for i in range(4):
                for k in range(-6, 7):
                    cand = list(params)
                    cand[i] = params[i] + k * span[i] / 6
                    if i >= 2 and cand[i] <= 0.5:
                        continue
                    s = score(cand)
                    if s > best:
                        best = s
                        params = cand
        img = rasterize(arings, params, W2, H2, model)
        s, inter, uni = iou(img, mask, W, H, exclude, ymax)
        results[model] = (s, params)
        print(f"  最优 IoU={s:.4f}  inter={inter}  union={uni}")
        print(f"  参数 x0={params[0]:.2f} y0={params[1]:.2f} kx={params[2]:.4f} ky={params[3]:.4f}")

    print("\n== 5) 结论 ==")
    for model, (s, _) in sorted(results.items(), key=lambda t: -t[1][0]):
        verdict = "可行" if s >= 0.70 else ("勉强" if s >= 0.55 else "不可行")
        print(f"  {model:<16} IoU={s:.4f}  {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
