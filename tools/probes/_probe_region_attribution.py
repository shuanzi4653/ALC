"""Ground truth for the merged-region tier attribution fix.

The band became a chain of ~19 clusters, so a single BAND cell's ``ban`` is now a
MultiPolygon whose parts sit up to a megametre apart. ``_dissolve_regions`` groups
member cells by *field* component but collects each member's *entire* BAN, so every
region was handed every other region's cores. This probe measures:

  * region count vs cell count (the premise ``test_merging_reduces_...`` asserted)
  * ``ban.difference(field).area`` per region (must be ~0)
  * how far each ban part escapes its own region's field
  * that a mixed kind/source set (band + storms + live observations together)
    still lands every core inside its region -- the case the original test passed on
    precisely because storms do not overlap
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
import math


from traffic.weather import NetworkWeather, PublicWeather, _dissolve_regions, _polygon_parts

world = NetworkWeather(seed=42, scenario='moving')
bands = [c for c in world.cells if c['shape'] == 'BAND']
print("cells               :", len(world.cells))
print("band cells          :", len(bands))
print("band polygon parts  :", len(_polygon_parts(bands[0]['polygon'])))
print()

worst_escape = 0.0
worst_area = 0.0
for minute in (0, 30, 120, 300, 470):
    shapes = world.shapes(minute)
    regions = _dissolve_regions(shapes)
    total = 0.0
    esc = 0.0
    for members, field, ban, caution in regions:
        outside = ban.difference(field)
        total += outside.area if not outside.is_empty else 0.0
        for part in _polygon_parts(ban):
            d = part.distance(field)
            esc = max(esc, d)
        # the two tiers must be disjoint
        overlap = ban.intersection(caution).area
        assert overlap < 1.0, (minute, overlap)
    worst_area = max(worst_area, total)
    worst_escape = max(worst_escape, esc)
    print(f"minute {minute:>3}  cells {len(shapes):>2}  regions {len(regions):>2}  "
          f"ban-outside-field {total:>14,.0f} m^2  worst part distance {esc:>12,.0f} m")

print()
print("WORST ban-outside-field :", f"{worst_area:,.0f} m^2")
print("WORST part-to-field dist:", f"{worst_escape:,.0f} m")
print()

# --- the mixed case, which is what the original nested-tier test exercised ------
print("=== mixed set: band + storm cells + live observations ===")
storm = [(c, f, b, a) for c, f, b, a in world.shapes(60) if c['shape'] != 'BAND']
from traffic.weather_sources import weather_snapshot
from traffic.catalog import cities as _cities
_city_rows = _cities()
live = PublicWeather(weather_snapshot(_city_rows), _city_rows).shapes(60)
print("storm cells / live cells:", len(storm), len(live))


class Cells(dict):
    pass


mixed = storm + live
if mixed:
    regions = _dissolve_regions(mixed)
    print("mixed cells / regions   :", len(mixed), len(regions))
    bad = 0
    for members, field, ban, caution in regions:
        outside = ban.difference(field).area if not ban.difference(field).is_empty else 0.0
        if outside > 1.0:
            bad += 1
            print("  ESCAPE", outside, [m['id'] for m in members][:3])
    print("regions with escaping cores:", bad)
