import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from traffic import service, weather  # noqa: E402
from _cell_geom import describe  # noqa: E402

# `service.network()` returns the *network payload* (a dict of routes/hubs).
# The weather cells live on the NetworkWeather object; calling `.cells` on the
# dict raised `AttributeError: 'dict' object has no attribute 'cells'`.
wx = weather.NetworkWeather(42, 'moving')
print('cells total:', len(wx.cells))
for c in wx.cells:
    poly = c.get('polygon')
    if poly is None:
        detail = 'no polygon'
    else:
        detail = describe(c)
    print(f"  {c['id']:<22} {c['shape']:<5} {detail}")
