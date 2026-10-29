"""Why is detours=0 when 41 raw corridors cross the envelope?

`_lateral` offsets every corridor sideways (220 m for CAR, 90 m for drones) before
the avoidance query is asked. The raw catalogue path is not the line the planner
tests. This probe repeats the planner's own offset and asks the same question, so
'detours=0' is either explained by the offset absorbing the crossing, or exposed
as a genuine bug.
"""
from shapely.geometry import LineString

from traffic import service
from traffic import zones as fixed_zones
from traffic.weather import PublicWeather

snapshot = service.weather_snapshot_entry(service.cities())
world = PublicWeather(snapshot, service.cities())
envelope = world.envelope(0, 480)
static = fixed_zones.envelope(service.airport_footprint_policy())
catalog = service.network()

raw_hits = offset_hits = 0
total = 0
for item in catalog['routes']:
    if not item['path']:
        continue
    total += 1
    if LineString(item['path']).intersects(envelope):
        raw_hits += 1
    allowed = service._allowed_for_route(item, catalog)
    width = 220 if item['mode'] == 'CAR' else 90
    lateral = service._lateral(item['path'], width, allowed)
    line = LineString(lateral)
    if line.intersects(envelope) or line.intersects(static):
        offset_hits += 1

print(f"raw corridors crossing the weather envelope   : {raw_hits} / {total}")
print(f"after the planner's _lateral offset, crossing : {offset_hits} / {total}")
print()
print("Interpretation:")
print("  - a crossing that survives the offset forces route(); those become WEATHER_DETOUR")
print("  - the offset is applied to BOTH sides of a 220 m corridor, so an envelope")
print("    that only clips the corridor edge is absorbed and no detour is recorded")
