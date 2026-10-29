# -*- coding: utf-8 -*-
"""NMC 拼图地理配准 v3：全分辨率、无容差 IoU。只读。

v2 的教训：给掩膜做 1 格膨胀后，五个投影模型全落在 Dice 0.91~0.92 —— **容差
把分辨力吃掉了**，于是"哪个投影对"这个问题在数值上无法回答。v3 去掉一切容差，
在 1:1 分辨率上算 IoU，并额外报告三个可解释残差：
  · 投影多边形 bbox  vs  掩膜 bbox
  · 海洋被多边形覆盖的比例（配准错了这一项会很大）
  · 若干地标城市的像素位置，供叠图核对
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

SRC = r"C:\Users\12921\Desktop\ALC\.run\_scratch\nmc"
CHINA = r"C:\Users\12921\Desktop\ALC\frontend\src\assets\china.json"
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


def _lambert(p1, p2, lonc=105.0):
    p1r, p2r = math.radians(p1), math.radians(p2)
    n = math.log(math.cos(p1r) / math.cos(p2r)) / math.log(
        math.tan(math.pi / 4 + p2r / 2) / math.tan(math.pi / 4 + p1r / 2))
    F = math.cos(p1r) * math.tan(math.pi / 4 + p1r / 2) ** n / n
    rho0 = F / math.tan(math.pi / 4 + p1r / 2) ** n

    def f(lon, lat):
        rho = F / math.tan(math.pi / 4 + math.radians(lat) / 2) ** n
        th = n * math.radians(lon - lonc)
        return (rho * math.sin(th), rho0 - rho * math.cos(th))
    return f


PROJ = {
    'equirect': lambda lon, lat: (lon, lat),
    'mercator': lambda lon, lat: (lon, math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))),
    'lambert25_47': _lambert(25, 47),
    'lambert30_60': _lambert(30, 60),
    'lambert38_50': _lambert(38, 50),
    'lambert15_35': _lambert(15, 35),
    'lambert47_25': _lambert(47, 25),
}

CITIES = [('北京', 116.4, 39.9), ('乌鲁木齐', 87.6, 43.8), ('广州', 113.3, 23.1),
          ('哈尔滨', 126.6, 45.8), ('拉萨', 91.1, 29.7), ('三亚', 109.5, 18.25),
          ('上海', 121.5, 31.2), ('成都', 104.1, 30.7)]


def main() -> int:
    path = newest()
    im = Image.open(path).convert('RGB')
    W, H = im.size
    ymax = H - 46
    px = im.load()
    print(f"{os.path.basename(path)} {W}x{H}")

    box = detect_inset(px, W, H)
    pad = 4
    ex = (max(0, box[0] - pad), max(0, box[1] - pad),
          min(W, box[2] + pad + 1), min(ymax, box[3] + pad + 1)) if box else (0, 380, 250, ymax)
    print(f"插图小窗={box}  屏蔽区={ex}")

    arr = np.asarray(im).astype(np.int16)
    sat = arr.max(axis=2) - arr.min(axis=2)
    mx = arr.max(axis=2)
    sea_m = (np.abs(arr[:, :, 0] - SEA[0]) <= 6) & (np.abs(arr[:, :, 1] - SEA[1]) <= 6) & (np.abs(arr[:, :, 2] - SEA[2]) <= 6)
    flat = (np.abs(arr[:, :, 0] - FLAT[0]) <= 5) & (np.abs(arr[:, :, 1] - FLAT[1]) <= 5) & (np.abs(arr[:, :, 2] - FLAT[2]) <= 5)
    line = (np.abs(arr[:, :, 0] - LINE[0]) <= 5) & (np.abs(arr[:, :, 1] - LINE[1]) <= 5) & (np.abs(arr[:, :, 2] - LINE[2]) <= 5)
    land_m = (sat <= 14) & (mx >= 195) & (mx <= 254) & (~flat) & (~line) & (~sea_m)
    land_m[ymax:, :] = False
    # 有效区（既不是海、也不是被屏蔽的插图）
    valid = np.ones((ymax, W), dtype=bool)
    valid[ex[1]:ex[3], ex[0]:ex[2]] = False
    land_m[ymax:, :] = False
    land_v = land_m[:ymax, :] & valid
    sea_v = sea_m[:ymax, :] & valid
    print(f"陆地掩膜(有效区)={land_v.sum()}  海洋(有效区)={sea_v.sum()}")

    data = json.load(open(CHINA, encoding='utf-8'))
    polys = []
    for ft in data['features']:
        polys.extend(rings(ft['geometry']))
    ls = [p for r in polys for p in r]
    lo0, lo1 = min(p[0] for p in ls), max(p[0] for p in ls)
    la0, la1 = min(p[1] for p in ls), max(p[1] for p in ls)
    print(f"参照环数={len(polys)} 经度[{lo0:.2f},{lo1:.2f}] 纬度[{la0:.2f},{la1:.2f}]")

    # 稳健 bbox
    colsum = land_v.sum(axis=0)
    rowsum = land_v.sum(axis=1)
    xs = np.where(colsum >= 12)[0]
    ys = np.where(rowsum >= 12)[0]
    mx0, mx1, my0, my1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    print(f"掩膜稳健 bbox x[{mx0},{mx1}] y[{my0},{my1}]")

    results = {}
    for model in PROJ:
        f = PROJ[model]
        uvs = [f(lon, lat) for lon, lat in ls]
        us = [a for a, _ in uvs]
        vs = [b for _, b in uvs]
        u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
        du, dv = max(1e-9, u1 - u0), max(1e-9, v1 - v0)
        nr = [[((f(lon, lat)[0] - u0) / du, (f(lon, lat)[1] - v0) / dv) for lon, lat in r] for r in polys]

        def raster(p):
            img = Image.new('1', (W, ymax), 0)
            d = ImageDraw.Draw(img)
            for rr in nr:
                pts = [(p[0] + a * p[2], p[1] + (1 - b) * p[3]) for a, b in rr]
                if len(pts) >= 3:
                    d.polygon(pts, fill=1)
            return np.array(img, dtype=bool)   # np.asarray 返回只读视图，后面要就地屏蔽

        def score(p):
            m = raster(p)
            m[ex[1]:ex[3], ex[0]:ex[2]] = False   # 屏蔽区不计分
            inter = int((m & land_v).sum())
            union = int((m | land_v).sum())
            iou = inter / union if union else 0.0
            seahit = int((m & sea_v).sum()) / max(1, int(m.sum()))
            return iou, seahit

        p = [mx0, my0, mx1 - mx0, my1 - my0]
        best, best_sea = score(p)
        for span in (60, 24, 9, 3, 1.2, 0.5):
            improved = True
            while improved:
                improved = False
                for i in range(4):
                    for k in (-2, -1, 1, 2):
                        cand = list(p)
                        cand[i] = p[i] + k * span
                        if i >= 2 and cand[i] < 30:
                            continue
                        s, sh = score(cand)
                        if (s, -sh) > (best, -best_sea):
                            best, best_sea, p = s, sh, cand
                            improved = True
        results[model] = (best, best_sea, p)
        print(f"\n== {model} ==  IoU={best:.4f}  多边形落在海上的比例={best_sea*100:.2f}%")
        print(f"   参数 X0={p[0]:.1f} Y0={p[1]:.1f} W={p[2]:.1f} H={p[3]:.1f}")

        def to_xy(lon, lat):
            a = (f(lon, lat)[0] - u0) / du
            b = (f(lon, lat)[1] - v0) / dv
            return p[0] + a * p[2], p[1] + (1 - b) * p[3]
        print("   地标像素位置: " + "  ".join(
            f"{n}({to_xy(lo, la)[0]:.0f},{to_xy(lo, la)[1]:.0f})" for n, lo, la in CITIES))

    print("\n== 结论（全分辨率无容差 IoU） ==")
    for m, (s, sh, _) in sorted(results.items(), key=lambda t: -t[1][0]):
        v = "可行" if s >= 0.85 else ("可用" if s >= 0.78 else ("勉强" if s >= 0.65 else "不可行"))
        print(f"  {m:<16} IoU={s:.4f}  海上={sh*100:5.2f}%  {v}")

    # 把最好的模型叠图出来
    mname = max(results, key=lambda k: results[k][0])
    p = results[mname][2]
    f = PROJ[mname]
    uvs = [f(lon, lat) for lon, lat in ls]
    us = [a for a, _ in uvs]
    vs = [b for _, b in uvs]
    u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
    ov = Image.open(path).convert('RGB')
    d = ImageDraw.Draw(ov)
    for r in polys:
        pts = [(p[0] + ((f(lon, lat)[0] - u0) / (u1 - u0)) * p[2],
                p[1] + (1 - (f(lon, lat)[1] - v0) / (v1 - v0)) * p[3]) for lon, lat in r]
        if len(pts) >= 3:
            d.line(pts + [pts[0]], fill=(220, 0, 0), width=1)
    for n, lo, la in CITIES:
        x = p[0] + ((f(lo, la)[0] - u0) / (u1 - u0)) * p[2]
        y = p[1] + (1 - (f(lo, la)[1] - v0) / (v1 - v0)) * p[3]
        d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(0, 0, 255), width=2)
    out = os.path.join(SRC, f'overlay_best_{mname}.png')
    ov.save(out)
    print(f"\n最优模型={mname}  叠图 -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
