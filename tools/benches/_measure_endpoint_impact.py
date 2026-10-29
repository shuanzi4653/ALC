"""Impact of the airport 净空巡视检查区域 on routes that cannot be re-routed.

A route that merely crosses a rectangle can detour around it. A route whose
endpoint (city hub or delivery node) is inside one cannot, so that flight has to
close. This decides whether the published rectangle is usable as a hard no-fly
area without gutting the network.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ROOT = Path(ROOT)
import json
import math


from shapely import affinity  # noqa: E402
from shapely.geometry import Point, box  # noqa: E402
from weather.geometry import project  # noqa: E402
from traffic.catalog import cities  # noqa: E402
from traffic import service  # noqa: E402

CACHE = ROOT / '.run' / 'zones_recon'
airports = [row for row in json.loads((CACHE / 'candidates.json').read_text(encoding='utf-8'))['airports']
            if row['scheduled'] == 'yes']
bearings = json.loads((CACHE / 'runway_bearings.json').read_text(encoding='utf-8'))
runways = {}
import csv as _csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import io

for row in _csv.DictReader(io.StringIO((CACHE / 'runways.csv').read_text(encoding='utf-8', errors='replace'))):
    ident = row.get('airport_ident')
    try:
        length = float(row.get('length_ft') or 0)
    except ValueError:
        length = 0.0
    if ident not in runways or length > runways[ident]:
        runways[ident] = length

HALF_WIDTH = float(sys.argv[1]) if len(sys.argv) > 1 else 10000.0
BEYOND = float(sys.argv[2]) if len(sys.argv) > 2 else 20000.0
print(f'footprint: 跑道两侧各 {HALF_WIDTH / 1000:g} km / 端外 {BEYOND / 1000:g} km')


def rect(lon, lat, bearing, half_length):
    centre = project((lon, lat))
    length = half_length * 2 + BEYOND * 2
    width = HALF_WIDTH * 2
    geometry = box(centre[0] - length / 2, centre[1] - width / 2, centre[0] + length / 2, centre[1] + width / 2)
    return affinity.rotate(geometry, -(bearing - 90), origin=centre)


zones = {}
for airport in airports:
    key = airport['icao']
    bearing = bearings.get(key)
    if bearing is None:
        continue
    half = runways.get(key, 2500.0) * 0.3048 / 2
    zones[key] = (airport, rect(airport['lon'], airport['lat'], bearing, half))

network = service.network()
hub_inside, node_inside = [], []
for city in cities():
    for key, (airport, geometry) in zones.items():
        if geometry.covers(Point(city['xy'])):
            hub_inside.append((city['name'], key, airport['name']))
for pad in network['pads']:
    for key, (airport, geometry) in zones.items():
        if pad.get('xy') and geometry.covers(Point(pad['xy'])):
            node_inside.append((pad['id'], key))

print(f'zones: {len(zones)}')
print(f'城市枢纽落入机场巡视检查区域: {len(hub_inside)}')
for row in hub_inside:
    print('   ', row)
print(f'交付节点落入: {len(node_inside)}')

blocked, detour = [], []
for route in network['routes']:
    hits = [key for key, (_, geometry) in zones.items() if geometry.intersects(
        __import__('shapely.geometry', fromlist=['LineString']).LineString(route['path']))] if route['path'] else []
    if not hits:
        continue
    first, last = route['path'][0], route['path'][-1]
    endpoints_inside = any(zones[key][1].covers(Point(first)) or zones[key][1].covers(Point(last)) for key in hits)
    (blocked if endpoints_inside else detour).append((route['id'], route['name'], hits))

print()
print(f'参考航线 {len(network["routes"])}')
print(f'  端点落在区域内（无法绕行）: {len(blocked)}')
for row in blocked:
    print('     ', row)
print(f'  仅被穿越（可绕行）: {len(detour)}')
interval_car, interval_del = 60, 30
flights_blocked = sum(2 * (480 // (interval_car if route_id.startswith('CAR') else interval_del))
                      for route_id, _, _ in blocked)
print()
print(f'按时间轴推算将被关闭的班次约: {flights_blocked}')
