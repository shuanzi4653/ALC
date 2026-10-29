"""Time each per-flight step to find where the plan actually spends its time.

Measured end to end: 196.5 s for 7760 flights, with the first progress tick only
at 82.6 s. The pre-loop setup is 0.24 s and `_flight()` is ~0 s, so the cost is
inside the loop body. This runs the real loop over a slice of flights and
accumulates time per step, so the dominant cost is named rather than guessed.

Called with: python _probe_flight_steps.py [n_flights]
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND  # noqa: E402
import collections
import random
import time
from pathlib import Path


from shapely.geometry import LineString, Point  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

from traffic import service  # noqa: E402
from traffic.weather import NetworkWeather  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 300
SEED = 4242

catalog = service.network()
rng = random.Random(SEED)
weather = NetworkWeather(SEED, 'moving')
geometries = [LineString(item['path']) for item in catalog['routes'] if item['path']]
route_ids = [item['id'] for item in catalog['routes'] if item['path']]
route_modes = [item['mode'] for item in catalog['routes'] if item['path']]
tree = STRtree(geometries)
static_policy = service.airport_footprint_policy()
static_obstacle = service.fixed_zones.envelope(static_policy)

pending = []
for item in catalog['routes']:
    interval = 60 if item['mode'] == 'CAR' else 30
    for departure in range(0, service.TIMELINE_MINUTES, interval):
        for direction in (0, 1):
            wave_offset = (int(item['id'].rsplit('-', 1)[-1]) - 1) * 3 if item['mode'] == 'DELIVERY' else 0
            pending.append((departure + direction * 8 + wave_offset + rng.randint(0, 2), item['id'], direction, item))
pending.sort(key=lambda item: item[:3])

calendar = service.ResourceCalendar({pad['id']: pad.get('capacity', 1) for pad in catalog['pads']})
zone_settings = service.operations()['crossingZone']
wait_step = max(1, int(service.profiles()['separation']['groundWaitStepMinutes']))
max_extra = service.profiles()['separation']['maxExtraMinutes']
max_minutes = service.operations()['maxFlightMinutes']
profile_by_mode = service.profiles()

accepted, buckets, path_cache = [], {}, {}
totals = collections.Counter()
counts = collections.Counter()
cursor = 0.0


def timed(label, func):
    """Run func, add its wall time to the bucket for label, return its result."""
    started = time.monotonic()
    result = func()
    totals[label] += time.monotonic() - started
    counts[label] += 1
    return result


loop_started = time.monotonic()
for index, (scheduled, route_id, direction, route_item) in enumerate(pending[:LIMIT]):
    flight = service._flight(rng, route_item, direction, scheduled)
    if not route_item['path']:
        continue
    mode = route_item['mode']
    profile = profile_by_mode[mode]
    allowed = service._allowed_for_route(route_item, catalog)
    if static_obstacle.covers(Point(route_item['fromXY'])) or static_obstacle.covers(Point(route_item['toXY'])):
        continue
    lateral = list(reversed(route_item['path'])) if direction else route_item['path']
    lateral = timed('_lateral', lambda: service._lateral(lateral, 220 if mode == 'CAR' else 90, allowed))
    base = timed('rounded_path(base)', lambda: service.rounded_path(lateral, profile['minTurnRadiusM']))
    if not base or not allowed.covers(LineString(base)):
        continue
    layer_options = service.airspace.preferences(profile, direction, route_item['corridorIndex'])
    nominal = timed('trajectory(nominal)', lambda: service.trajectory(
        base, scheduled, profile['speedKmh'], layer_options[0],
        max_altitude=profile['maxCruiseAglM'], climb_mps=profile['maxClimbMps']))
    if not nominal:
        continue
    base_duration = nominal[-1][3] - scheduled
    if scheduled + base_duration > service.TIMELINE_MINUTES:
        continue
    obstacle = timed('weather.envelope', lambda: weather.envelope(
        scheduled, scheduled + base_duration + max_extra))
    lateral_line = LineString(lateral)
    path, detour = lateral, False
    hit = timed('intersects', lambda: lateral_line.intersects(obstacle) or lateral_line.intersects(static_obstacle))
    if hit:
        avoidance = obstacle if static_obstacle.is_empty else timed(
            'union(static)', lambda: obstacle.union(static_obstacle))
        cache_key = (route_id, direction, int(scheduled // 5))
        if cache_key not in path_cache:
            path_cache[cache_key] = timed('route(detour)', lambda: service.route(
                lateral[0], lateral[-1], allowed, avoidance))
        path = path_cache[cache_key]
        detour = True
    if not path:
        continue
    path = timed('rounded_path(detour)', lambda: service.rounded_path(path, profile['minTurnRadiusM']))
    if not path or not allowed.covers(LineString(path)):
        continue
    crossings = timed('_crossings', lambda: service._crossings(
        path, route_id, mode, geometries, tree, route_ids, route_modes))
    chosen = None
    for delay in range(0, max_extra + 1, wait_step):
        for layer in layer_options:
            points = timed('trajectory(attempt)', lambda: service.trajectory(
                path, scheduled + delay, profile['speedKmh'], layer, crossings=crossings,
                max_altitude=profile['maxCruiseAglM'], climb_mps=profile['maxClimbMps']))
            if not points or not service.within_profile(points, profile):
                continue
            if points[-1][3] > service.TIMELINE_MINUTES:
                continue
            if points[-1][3] - scheduled - base_duration > max_extra + 1e-8:
                continue
            if points[-1][3] - points[0][3] > max_minutes[mode]:
                continue
            pad_entries = ((flight['fromPad'], points[0][3]), (flight['toPad'], points[-1][3]))
            if not timed('calendar.window', lambda: calendar.window_available(pad_entries, profile['padSeparationMinutes'])):
                continue
            zones = timed('crossing_zones', lambda: service.crossing_zones(
                path, crossings, points, zone_settings['cellM']))
            for zone in zones:
                calendar.register(zone['zoneId'], zone_settings['capacity'])
            zone_entries = tuple((zone['zoneId'], zone['minute']) for zone in zones if zone['minute'] is not None)
            if not calendar.window_available(zone_entries, zone_settings['windowMinutes']):
                continue
            keys = timed('_keys', lambda: service._keys(points))
            possible = set().union(*(buckets.get(key, set()) for key in keys))
            collisions = timed('conflict', lambda: [
                accepted[item] for item in possible if service.conflict(points, accepted[item]['points'])])
            if collisions:
                continue
            chosen = (points, delay, keys, layer, zones, pad_entries, zone_entries)
            break
        if chosen:
            break
    if chosen:
        accepted.append({'id': flight['id'], 'points': chosen[0]})
        for key in chosen[2]:
            buckets.setdefault(key, set()).add(len(accepted) - 1)

elapsed = time.monotonic() - loop_started
print(f'处理 {min(LIMIT, len(pending))} 班耗时 {elapsed:.2f}s  '
      f'-> 外推 {len(pending)} 班约 {elapsed / min(LIMIT, len(pending)) * len(pending):.0f}s')
print()
print(f'{"步骤":<26}{"总秒数":>10}{"次数":>8}{"每次ms":>10}')
for label, seconds in totals.most_common():
    per = seconds / max(counts[label], 1) * 1000
    print(f'{label:<26}{seconds:>10.3f}{counts[label]:>8}{per:>10.3f}')
print(f'{"(循环总计)":<26}{elapsed:>10.3f}')
