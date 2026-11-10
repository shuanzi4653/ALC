import math
import sys
sys.path.insert(0, '.')
from shapely.geometry import LineString, Point
from traffic import service as service_mod
from traffic import zones

cat = service_mod.network()
geom = zones.envelope(zones.PROHIBITED)


def perp_offset(a, b, d):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1.0
    return (-dy / n * d, dx / n * d)


def score(pts, own):
    line = LineString(pts)
    return line.length, line.intersection(geom).difference(own).length / 1000.0


for rid in ('CAR-1-02-1-14', 'CAR-3-02-3-13'):
    item = [r for r in cat['routes'] if r['id'] == rid][0]
    p = [tuple(pt) for pt in item['path']]
    own = zones.covering_geometry_xy(*p[0]).union(zones.covering_geometry_xy(*p[-1]))
    base_len, base_zone = score(p, own)
    print(rid, 'base len', round(base_len / 1000, 1), 'inZone', round(base_zone, 1))
    best = (base_zone, None)
    for i in range(1, len(p) - 1):
        for d in (2000, 4000, 6000, 9000, 12000, 16000):
            for sign in (1, -1):
                ox, oy = perp_offset(p[i - 1], p[i + 1], d * sign)
                pts = list(p)
                pts[i] = (p[i][0] + ox, p[i][1] + oy)
                ln, zn = score(pts, own)
                if zn < best[0] - 0.05:
                    best = (zn, (i, d * sign, round(ln / 1000, 1)))
    print('   best single-vertex', best)
    # 双顶点组合：在最好单点基础上再动一点
    if best[1]:
        i0, d0, _ = best[1]
        for j in range(1, len(p) - 1):
            if j == i0:
                continue
            for d in (4000, 8000, 12000):
                for sign in (1, -1):
                    pts = list(p)
                    ox, oy = perp_offset(p[i0 - 1], p[i0 + 1], d0)
                    pts[i0] = (p[i0][0] + ox, p[i0][1] + oy)
                    ox2, oy2 = perp_offset(p[j - 1], p[j + 1], d * sign)
                    pts[j] = (p[j][0] + ox2, p[j][1] + oy2)
                    ln, zn = score(pts, own)
                    if zn < best[0] - 0.05:
                        best = (zn, (i0, d0, j, d * sign, round(ln / 1000, 1)))
        print('   best two-vertex', best)
