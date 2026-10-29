"""Why does the plan close flights instead of routing around the hazard?

Measured 2026-09-30 on the default live/measured build: 2519 WEATHER_BLOCKED,
0 WEATHER_DETOUR. This probe separates the candidate causes:

  A. the obstacle set contains the flight's own start/end point, so `route()`
     returns None before it ever searches (it refuses a pad inside a hazard);
  B. the caution ring is in the obstacle set at all (caution = "enter with
     care", not "do not enter");
  C. the detour space is genuinely too narrow.

For every closed flight it reports which of weather-envelope / radar-field /
static-airspace covers its start point, and what the closure would be if only
the *ban* tier were an obstacle.
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND  # noqa: E402

from shapely.geometry import GeometryCollection, LineString, Point  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from traffic import service, weather, weather_control, zones as fixed_zones  # noqa: E402

SEED, SCENARIO = 42, 'live'

catalog = service.network()
snapshot = service.weather_snapshot_entry(catalog['cities'])
world = weather.PublicWeather(snapshot, catalog['cities'])

frame = service.weather_frame(SEED, SCENARIO, 60)
cells = frame.get('cells') or []
from shapely.geometry import shape

ban_parts = [shape(c['ban']) for c in cells if c.get('ban', {}).get('coordinates')]
caution_parts = [shape(c['caution']) for c in cells if c.get('caution', {}).get('coordinates')]
only_ban = unary_union(ban_parts) if ban_parts else GeometryCollection()
ban_and_caution = unary_union(ban_parts + caution_parts) if (ban_parts or caution_parts) else GeometryCollection()
print('cells', len(cells), 'with ban', len(ban_parts), 'with caution', len(caution_parts))
print('only_ban km2', round(only_ban.area / 1e6, 1), '| ban+caution km2', round(ban_and_caution.area / 1e6, 1))

radar_geom, radar_info = service._radar_avoidance(SCENARIO)
print('radar obstacle:', radar_info)
if isinstance(radar_geom, tuple):
    radar_union = unary_union([g for _, g in radar_geom]) if radar_geom else GeometryCollection()
else:
    radar_union = radar_geom
print('radar obstacle km2', round(radar_union.area / 1e6, 1))

static_policy = service.airport_footprint_policy()
static = fixed_zones.envelope(static_policy)

plan = service.simulate(seed=SEED, scenario=SCENARIO)
flights = plan['flights']
closed = [f for f in flights if f['status'] != 'SCHEDULED' and f['reason'] == 'WEATHER_BLOCKED']
print('closed WEATHER_BLOCKED:', len(closed))

by = Counter()
for f in closed:
    route_item = next(r for r in catalog['routes'] if r['id'] == f['routeId'])
    start = Point(route_item['path'][0] if not f['direction'] else route_item['path'][-1])
    end = Point(route_item['path'][-1] if not f['direction'] else route_item['path'][0])
    tags = []
    if ban_and_caution.covers(start) or ban_and_caution.covers(end):
        tags.append('start/end-in-ban+cau')
    if only_ban.covers(start) or only_ban.covers(end):
        tags.append('start/end-in-ban-only')
    if radar_union.covers(start) or radar_union.covers(end):
        tags.append('start/end-in-radar')
    if static.covers(start) or static.covers(end):
        tags.append('start/end-in-static')
    # does the straight corridor touch each tier?
    line = LineString([tuple(start.coords[0]), tuple(end.coords[0])])
    if line.intersects(ban_and_caution):
        tags.append('corridor-hits-ban+cau')
    if line.intersects(radar_union):
        tags.append('corridor-hits-radar')
    by[' | '.join(tags) or 'no-obstacle-hit'] += 1

print()
for key, n in by.most_common():
    print(f'{n:6d}  {key}')

# Directly ask routing: with only the ban tier as obstacle, can the worst route pass?
print()
samples = closed[:5]
for f in samples:
    route_item = next(r for r in catalog['routes'] if r['id'] == f['routeId'])
    allowed = service._allowed_for_route(route_item, catalog)
    start = tuple(route_item['path'][0] if not f['direction'] else route_item['path'][-1])
    end = tuple(route_item['path'][-1] if not f['direction'] else route_item['path'][0])
    r_ban = service.route(start, end, allowed, only_ban)
    r_all = service.route(start, end, allowed, ban_and_caution)
    print(f"{f['id']}: route(only_ban)={'OK' if r_ban else 'None'} route(ban+caution)={'OK' if r_all else 'None'}")
