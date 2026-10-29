"""Measure the cluster chain: gaps, component count, and whether any east-west
corridor actually survives. Run with the project venv.

The whole point of the change is that the band must NOT be a wall. So this reports,
for each adjacent pair of clusters, the clear distance between their outlines, and
then tests the operational question directly: take the two ends of the chain and ask
whether a straight corridor between them crosses the field.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from traffic import weather as W
from weather.geometry import boundary, project
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    # `_band_clusters` now returns (field, core, anchor): the band gained a
    # first-class caution core when the risk layers were split. Unpacking two
    # raised `ValueError: too many values to unpack (expected 2)`.
    field, core, anchor = W._band_clusters()
    parts = W._polygon_parts(field)
    print(f'field type      : {field.geom_type}')
    print(f'component count : {len(parts)}')
    print(f'field area km^2 : {field.area/1e6:,.0f}')
    print(f'core  area km^2 : {core.area/1e6:,.0f}')
    print(f'anchor          : {anchor.x:.0f},{anchor.y:.0f}')
    print()

    # Gap between every adjacent component. Anything <= 0 is a merged wall.
    boxes = [(p.bounds, p.centroid) for p in parts]
    print('largest components (radius-ish):')
    for bounds, centroid in sorted(boxes, key=lambda b: -(b[0][2]-b[0][0]))[:10]:
        w = (bounds[2]-bounds[0])/1000
        h = (bounds[3]-bounds[1])/1000
        print(f'  ~{w:5.1f} x {h:5.1f} km  at {centroid.x:>9.0f},{centroid.y:>9.0f}')
    print()

    # Directly test the user's complaint: can you get across the chain?
    # Walk a set of straight west->east lines at several latitudes through the
    # band's own latitude span and record how much of each is inside the field.
    minx, miny, maxx, maxy = field.bounds
    print('west->east corridor test (fraction of each straight line inside the field):')
    crossings = 0
    for step in range(9):
        y = miny + (maxy-miny)*step/8
        line = LineString([(minx-200000, y), (maxx+200000, y)])
        inside = line.intersection(field).length
        frac = inside/line.length
        if inside == 0:
            verdict = 'CLEAR (no contact)'
        elif frac < 0.35:
            verdict = f'partial {frac:.0%}'
        else:
            verdict = f'BLOCKED {frac:.0%}'
        if inside == 0:
            crossings += 1
        print(f'  y={y:>9.0f}  inside={inside/1000:8.1f} km  {verdict}')
    print()
    print(f'latitude lines with zero contact: {crossings}/9')


if __name__ == '__main__':
    main()
