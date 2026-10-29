"""Follow the 41 crossing corridors all the way to the flight records.

Exactly which reason code do the flights on those corridors end up with? If they
are all CLOSED before the avoidance step (boundary, turn radius, horizon), the
weather query was never reached and 'detours=0' is a statement about ordering,
not about weather. If they are ACCEPTED with reason=CLEAR, the envelope genuinely
did not fire and that would be a defect.
"""
from collections import Counter

from shapely.geometry import LineString

from traffic import service
from traffic import zones as fixed_zones
from traffic.weather import PublicWeather

snapshot = service.weather_snapshot_entry(service.cities())
envelope = PublicWeather(snapshot, service.cities()).envelope(0, 480)
static = fixed_zones.envelope(service.airport_footprint_policy())
catalog = service.network()

crossing_route_ids = set()
for item in catalog['routes']:
    if item['path'] and (LineString(item['path']).intersects(envelope)
                         or LineString(item['path']).intersects(static)):
        crossing_route_ids.add(item['id'])
print(f"routes touching weather-envelope or static airspace: {len(crossing_route_ids)}")
print(f"  sample: {sorted(crossing_route_ids)[:8]}")

run = service.simulate(42, 'live')
reasons = Counter()
for flight in run['flights']:
    if flight.get('routeId') in crossing_route_ids:
        reasons[(flight['status'], flight['reason'])] += 1

print()
print("status/reason for flights on crossing routes:")
for (status, reason), count in sorted(reasons.items(), key=lambda kv: -kv[1]):
    print(f"  {status:<10} {reason:<28} {count}")

# What does reason=WEATHER_DETOUR look like globally, and what are the reasons
# that actually closed flights?
closed = Counter(f['reason'] for f in run['flights'] if f['status'] == 'CLOSED')
print()
print("all closure reasons in the live run:")
for reason, count in closed.most_common():
    print(f"  {reason:<28} {count}")
