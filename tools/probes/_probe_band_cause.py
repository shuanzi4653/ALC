"""Isolate the cause of the extra closures.

The chain covers LESS ground than the old ribbon (33,626 vs 58,916 km^2 clipped) and
yet closed MORE flights (2621 vs 2036). So the cause is not area. Two candidates:

  A. the satellites parked inside the gaps; and
  B. the sampling geometry -- the old ribbon followed the centreline smoothly while
     the chain is 26 discs whose *combined* footprint may still straddle a corridor
     the ribbon left open at some latitudes.

Measure each separately by building the field three ways and reporting the same
east-west severance metric for all of them, plus the closure count.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import time
from collections import Counter
from pathlib import Path


from shapely.geometry import LineString, MultiPolygon, Point
from shapely.ops import unary_union

from weather.geometry import boundary, project
from traffic import weather as W
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def centres(include_satellites):
    path = [project(p) for p in W.BAND_CENTRELINE_LONLAT]
    line = LineString(path)
    length = line.length
    count = max(2, int(length // W.BAND_CLUSTER_SPACING_M))
    rows = []
    for i in range(count + 1):
        pt = line.interpolate(min(i * W.BAND_CLUSTER_SPACING_M, length))
        rows.append((pt.x, pt.y, W.BAND_CLUSTER_RADII_M[i % len(W.BAND_CLUSTER_RADII_M)]))
    discs = []
    for x, y, r in rows:
        discs.append(Point(x, y).buffer(r, quad_segs=8))
        if include_satellites and r >= 21000:
            off = r * 1.28
            sat = [(x + off, y - off*0.35), (x - off*0.9, y + off*0.5)][len(discs) % 2]
            discs.append(Point(sat).buffer(r * 0.34, quad_segs=8))
    field = unary_union(discs)
    parts = W._polygon_parts(field)
    return MultiPolygon(parts) if len(parts) > 1 else parts[0]


def severance(geom, steps=41):
    """Worst share of a west-east straight line that falls inside the field."""
    worst, clear = 0.0, 0
    minx, miny, maxx, maxy = geom.bounds
    for s in range(steps):
        y = miny + (maxy - miny) * s / (steps - 1)
        line = LineString([(minx - 300000, y), (maxx + 300000, y)])
        frac = line.intersection(geom).length / line.length
        worst = max(worst, frac)
        if frac == 0:
            clear += 1
    return worst, clear


def main():
    b = boundary()
    ribbon = LineString([project(p) for p in W.BAND_CENTRELINE_LONLAT]).buffer(26000, quad_segs=8)

    variants = [
        ('old ribbon 26 km', ribbon),
        ('chain, no satellites', centres(False)),
        ('chain, with satellites', centres(True)),
    ]
    print(f'{"variant":<26}{"clipped km2":>13}{"comps":>7}{"worst sev":>11}{"clear/y":>9}')
    print('-' * 66)
    for label, geom in variants:
        clipped = geom.intersection(b)
        worst, clear = severance(geom)
        print(f'{label:<26}{clipped.area/1e6:>13,.0f}{len(W._polygon_parts(clipped)):>7}'
              f'{worst:>10.1%}{clear:>9}')

    print()
    print('gap analysis: for each adjacent pair of cluster centres, the free distance')
    print('between outlines (negative would mean the chain is a wall there):')
    for include in (False, True):
        c = centres(include)
        parts = sorted(W._polygon_parts(c), key=lambda p: p.centroid.x)
        gaps = []
        for a, bb in zip(parts, parts[1:]):
            gaps.append(a.distance(bb))
        tag = 'with satellites' if include else 'no satellites'
        print(f'  {tag:<16} min {min(gaps):7.0f} m   median {sorted(gaps)[len(gaps)//2]:7.0f} m   '
              f'components {len(parts)}')
        print(f'                   gaps <=1 km: {sum(1 for g in gaps if g <= 1000)}   '
              f'<=5 km: {sum(1 for g in gaps if g <= 5000)}')


if __name__ == '__main__':
    main()
