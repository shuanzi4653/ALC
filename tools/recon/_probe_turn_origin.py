"""Is the 46.88 degree turn a province-boundary cut, or the outline itself?

Compare three geometries for the same cell at the same minute:
  A) _irregular_outline(...)  -> raw harmonic shape
  B) shapes(t)['field']       -> after clipping to the legal boundary
The turn must be located in the difference between A and B if it is a cut.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import math
from pathlib import Path


from shapely.geometry import Polygon  # noqa: E402
from weather.geometry import boundary  # noqa: E402
from traffic import weather as W  # noqa: E402


def turns(geometry, threshold=45.0):
    out = []
    if geometry.is_empty:
        return out
    parts = list(geometry.geoms) if geometry.geom_type.startswith('Multi') else [geometry]
    for part in parts:
        if part.geom_type != 'Polygon':
            continue
        rings = [('exterior', part.exterior)] + [('interior', r) for r in part.interiors]
        for kind, ring in rings:
            pts = list(ring.coords)
            n = len(pts) - 1
            for i in range(n):
                a, b, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
                v1 = (b[0] - a[0], b[1] - a[1])
                v2 = (c[0] - b[0], c[1] - b[1])
                n1, n2 = math.hypot(*v1), math.hypot(*v2)
                if n1 < 1e-9 or n2 < 1e-9:
                    continue
                cross = v1[0] * v2[1] - v1[1] * v2[0]
                dot = v1[0] * v2[0] + v1[1] * v2[1]
                if cross < 0:
                    ang = math.degrees(math.atan2(abs(cross), dot))
                    if ang > threshold:
                        out.append((ang, b, kind, min(n1, n2)))
    return out


w = W.NetworkWeather(42, 'moving')
bound = boundary()
for minute in (255, 280):
    print('=' * 78)
    print(f'minute = {minute}')
    print('=' * 78)
    for cell, field, ban, caution in w.shapes(minute):
        if cell['id'] != 'WX-1-03':
            continue
        x, y = w.centre_at(cell, minute)
        raw = W._irregular_outline(x, y, w.radius_at(cell, minute), cell['outline'])
        print(f"  {cell['id']}  centre=({x:.0f},{y:.0f})  radius_at={w.radius_at(cell, minute)/1000:.2f} km")
        print(f'  A 原始谐波轮廓（未裁剪）: 顶点 {len(raw.exterior.coords)-1}  '
              f'>45° 凸角 {len(turns(raw))} 处  '
              f'最大 {max((t[0] for t in turns(raw)), default=0):.2f}°')
        shrunk = boundary().buffer(-1).contains(raw)
        print(f'     完全落在法定边界内? {shrunk}')
        print(f'  B shapes() 的 Field（已裁剪）: 顶点 {len(field.exterior.coords)-1 if field.geom_type=="Polygon" else sum(len(p.exterior.coords)-1 for p in field.geoms)}  '
              f'>45° 凸角 {len(turns(field))} 处')
        for ang, v, kind, edge in turns(field):
            print(f'     {ang:.2f}° {kind} 最短边 {edge:.1f} m 顶点 ({v[0]:.0f},{v[1]:.0f})')
        # Where does the boundary intersect the raw outline?
        inter = raw.boundary.intersection(bound.boundary)
        print(f'  轮廓与省界的交点：{inter.geom_type} '
              + (f'n={len(inter.geoms)}' if inter.geom_type == 'MultiPoint' else ''))
        if inter.geom_type == 'MultiPoint':
            for p in list(inter.geoms)[:6]:
                print(f'     ({p.x:.0f},{p.y:.0f})')
        elif inter.geom_type == 'Point':
            print(f'     ({inter.x:.0f},{inter.y:.0f})')
        print()
