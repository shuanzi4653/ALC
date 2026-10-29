
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
from weather.geometry import boundary
from shapely.ops import unary_union
from traffic.weather import NetworkWeather, _polygon_parts, _areal, _clip

world = NetworkWeather(42, 'moving')
cells = world.shapes(0)
band = [c for c, f, b, a in cells if c['shape'] == 'BAND'][0]
band_field = [f for c, f, b, a in cells if c['shape'] == 'BAND'][0]
parts_band = _polygon_parts(band_field)
print("band field parts:", len(parts_band))

fields = _polygon_parts(unary_union([f for _, f, _, _ in cells]))
print("union components:", len(fields))

# how many components does the band's field clip into?
hits = 0
for idx, field in enumerate(fields):
    clipped = _clip(band_field, field)
    ok = _areal(clipped)
    if ok:
        hits += 1
print("components the band is a member of:", hits)

# Is the band's field one connected geometry per component, or does the union merge
# the chain into fewer components?
print("band field geom type:", band_field.geom_type)
print("band centroids within 60km of a component?")
for idx, field in enumerate(fields[:6]):
    c = field.centroid
    print(f"  comp {idx}: type={field.geom_type} area={field.area:,.0f} centroid=({c.x:,.0f},{c.y:,.0f})")
