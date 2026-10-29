"""Compare the old continuous ribbon against the new cluster chain.

The surprise worth explaining: replacing a continuous wall with a chain of clusters
made MORE flights close, not fewer. That can only happen if the chain covers more
ground than the ribbon did, so measure it rather than guess.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from shapely.geometry import LineString
from weather.geometry import boundary, project
from traffic import weather as W
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def old_ribbon(half_width):
    line = LineString([project(p) for p in W.BAND_CENTRELINE_LONLAT])
    return line.buffer(half_width, quad_segs=8)


def main():
    # Returns (field, core, anchor) since the band gained a caution core.
    field = W._band_clusters()[0]
    b = boundary()

    print(f'centreline length (projected): {LineString([project(p) for p in W.BAND_CENTRELINE_LONLAT]).length/1000:,.0f} km')
    print()
    print(f'{"variant":<34}{"area km2":>12}{"clipped km2":>13}{"components":>12}{"pct of NE":>12}')
    print('-' * 83)

    ne_area = b.area / 1e6

    def row(label, geom):
        clipped = geom.intersection(b)
        parts = W._polygon_parts(clipped)
        print(f'{label:<34}{geom.area/1e6:>12,.0f}{clipped.area/1e6:>13,.0f}'
              f'{len(parts):>12}{100*clipped.area/1e6/ne_area:>11.1f}%')

    for hw in (20000, 26000, 32000):
        row(f'old ribbon half-width {hw//1000} km', old_ribbon(hw))
    row('new cluster chain', field)
    print()
    print(f'net box: {b.area/1e6:,.0f} km^2')
    print()
    # How much of the *east-west* reach is severed at each latitude.
    print('max east-west severance per straight line (share of the line inside the field):')
    for label, geom in (('old ribbon 26 km', old_ribbon(26000)), ('cluster chain', field)):
        worst = 0.0
        for step in range(25):
            minx, miny, maxx, maxy = geom.bounds
            y = miny + (maxy - miny) * step / 24
            line = LineString([(minx - 300000, y), (maxx + 300000, y)])
            worst = max(worst, line.intersection(geom).length / line.length)
        print(f'  {label:<22} worst {worst:6.1%}')


if __name__ == '__main__':
    main()
