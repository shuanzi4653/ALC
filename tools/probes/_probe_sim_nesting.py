import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402

from traffic import radar_field, weather_sim  # noqa: E402

f = weather_sim.frame(seed=42, slot='2026-09-18T10:36:00Z')
d = radar_field.derive(f)
b = d['bands']

for name in ('STRATIFORM', 'CONVECTIVE', 'STRONG'):
    info = b[name]
    g = info['geometry']
    print('%-11s comp=%-3d area=%.4e m2  bounds=%s'
          % (name, info['components'], info['areaM2'],
             tuple(round(v, 1) for v in g.bounds)))

for lower, upper in (('STRATIFORM', 'CONVECTIVE'), ('CONVECTIVE', 'STRONG')):
    lg = b[lower]['geometry']
    ug = b[upper]['geometry']
    out = ug.difference(lg)
    print('%s outside %s: %.4e m2 (of %.4e, %.4f%% of upper)'
          % (upper, lower, out.area, ug.area,
             100.0 * out.area / ug.area if ug.area else 0.0))
    if out.area > 0:
        print('   leaked bounds', tuple(round(v, 1) for v in out.bounds))
