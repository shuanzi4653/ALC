"""Re-measure the user's requirement straight from the current code.

The user's specification was explicit: the rain band must not be continuous,
because an unbroken band severs the east-west network; it should be "一些大云团
带一些小云团" with "间隙可以过去的" (gaps wide enough to pass through).

This script answers exactly that, from the live `weather.py` rather than from
recorded numbers, and states the gap in metres next to a flight-crossable
threshold so the answer is falsifiable rather than a claim of intent.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND  # noqa: E402
from pathlib import Path


from shapely.geometry import shape  # noqa: E402

from traffic.weather import (BAND_CLUSTER_GAP_M, BAND_CLUSTER_RADII_M,  # noqa: E402
                             BAND_CLUSTER_SPACING_M, NetworkWeather,
                             _polygon_parts)

print('构造参数')
print('  半径循环 (m)      :', BAND_CLUSTER_RADII_M)
print('  簇间距   (m)      :', BAND_CLUSTER_SPACING_M)
print('  目标间隙 (m)      :', BAND_CLUSTER_GAP_M)
print('  半径循环最大相邻和:', BAND_CLUSTER_RADII_M[0] + BAND_CLUSTER_RADII_M[4],
      '-> 间隙', BAND_CLUSTER_SPACING_M - (BAND_CLUSTER_RADII_M[0] + BAND_CLUSTER_RADII_M[4]))

world = NetworkWeather(42, 'moving')
print()
print('各时刻实测')
print('  分钟 | 云团数 | 最小间隙(m) | <1km间隙 | 面积(km2)')
for minute in (0, 30, 60, 120, 240):
    bands = [(cell, geometry) for cell, geometry, _, _ in world.shapes(minute)
             if cell['shape'] == 'BAND']
    for _, geometry in bands:
        parts = _polygon_parts(geometry)
        gaps = []
        for index, part in enumerate(parts):
            nearest = min((part.distance(other) for offset, other in enumerate(parts)
                           if offset != index), default=float('nan'))
            gaps.append(nearest)
        # The band is clipped by the province boundary when drawn, so measure the
        # drawn form too: that is what a route actually has to pass through.
        drawn = [shape(region['field']) for region in world.frame(minute)
                 if 'BAND' in ' '.join(region.get('sources', []))]
        print(f'  {minute:>4} | {len(parts):>6} | {min(gaps):>11.0f} | '
              f'{sum(1 for g in gaps if g < 1000):>8} | {geometry.area / 1e6:>9.0f}'
              f'{"  (裁剪后区域 " + str(len(drawn)) + " 块)" if drawn else ""}')
