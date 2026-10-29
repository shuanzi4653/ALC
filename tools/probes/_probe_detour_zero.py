"""Is detours=0 a real 'nothing to detour around' or a broken avoidance query?

A zero is only meaningful once you know who computed it. This measures the
envelope geometry against the straight-line corridors directly, so 'no detour'
can be distinguished from 'the envelope was never consulted'.
"""
from shapely.geometry import LineString

from traffic import service
from traffic.weather import PublicWeather

snapshot = service.weather_snapshot_entry(service.cities())
world = PublicWeather(snapshot, service.cities())
envelope = world.envelope(0, 480)
print(f"envelope area over the whole plan = {envelope.area/1e6:.1f} km2")
print(f"envelope is_empty = {envelope.is_empty}")

catalog = service.network()
hits = 0
for item in catalog['routes']:
    if not item['path']:
        continue
    line = LineString(item['path'])
    if line.intersects(envelope):
        hits += 1
        print(f"  corridor {item['id']} intersects the envelope")

print(f"corridors crossing the live envelope: {hits} / {sum(1 for i in catalog['routes'] if i['path'])}")

# Also check the fixed airspace union, which is the other half of the same query.
from traffic import zones as fixed_zones
policy = service.airport_footprint_policy()
static = fixed_zones.envelope(policy)
print(f"static airspace envelope area = {static.area/1e6:.1f} km2, is_empty={static.is_empty}")

if hits == 0:
    print("VERDICT: detours=0 is legitimate -- the live envelope does not reach any corridor")
else:
    print("VERDICT: corridors DO cross the envelope, so detours=0 would be suspicious")
