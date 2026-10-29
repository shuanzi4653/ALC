"""Measure the impact of published airport protection geometry on the plan.

Answers one question before anything is built: if the 净空巡视检查区域
(road centreline +/- 10 km, 20 km beyond each runway end) is treated as a hard
no-fly area, how many city hubs and reference routes does it actually touch?
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ROOT = Path(ROOT)
import csv
import io
import json


from shapely.geometry import LineString, Point  # noqa: E402
from shapely import affinity  # noqa: E402
from weather.geometry import boundary, project  # noqa: E402
from traffic.catalog import cities  # noqa: E402
import urllib.request  # noqa: E402

UA = 'ALC-research/0.1 (low-altitude traffic simulation, contact: project owner)'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
OPENER.addheaders = [('User-Agent', UA)]
CACHE = ROOT / '.run' / 'zones_recon'


def download(name, url):
    path = CACHE / name
    if not path.exists():
        with OPENER.open(url, timeout=180) as response:
            path.write_bytes(response.read())
    return path


def runways():
    path = download('runways.csv', 'https://davidmegginson.github.io/ourairports-data/runways.csv')
    result = {}
    for row in csv.DictReader(io.StringIO(path.read_text(encoding='utf-8', errors='replace'))):
        ident = row.get('airport_ident')
        try:
            length = float(row.get('length_ft') or 0)
        except ValueError:
            length = 0.0
        bearing = row.get('le_heading_degT') or row.get('he_heading_degT')
        try:
            bearing = float(bearing)
        except (TypeError, ValueError):
            bearing = None
        current = result.get(ident)
        if current is None or length > current[0]:
            result[ident] = (length, bearing, row.get('le_ident'), row.get('surface'))
    return result


def strip(centre_xy, bearing_deg, half_width=10000.0, beyond=20000.0, half_length=1200.0):
    """Rectangle: +/- half_width across, 20 km beyond each end of the runway box."""
    length = half_length * 2 + beyond * 2
    width = half_width * 2
    rectangle = Point(centre_xy).buffer(1).envelope
    from shapely.geometry import box
    rectangle = box(centre_xy[0] - length / 2, centre_xy[1] - width / 2,
                    centre_xy[0] + length / 2, centre_xy[1] + width / 2)
    return affinity.rotate(rectangle, -(bearing_deg - 90), origin=centre_xy)


data = json.loads((CACHE / 'candidates.json').read_text(encoding='utf-8'))
airports = [row for row in data['airports'] if row['scheduled'] == 'yes']
runway = runways()


def bearing_for(icao):
    record = runway.get(icao)
    if not record or record[1] is None:
        return None, record
    return record[1], record


print(f'candidate 运输机场: {len(airports)}, runways known: '
      f'{sum(1 for a in airports if bearing_for(a["icao"])[0] is not None)}')
print()
print('per airport: distance to hub, bearing, hub inside strip?')
inside_hubs, strips = [], {}
for airport in airports:
    bearing, record = bearing_for(airport['icao'])
    xy = project((airport['lon'], airport['lat']))
    if bearing is None:
        print(f"  {airport['icao']}: NO RUNWAY HEADING")
        continue
    geometry = strip(xy, bearing)
    strips[airport['icao']] = geometry
    hub = next(city for city in cities() if city['id'] == airport['nearestCityId'])
    hit = geometry.covers(Point(hub['xy']))
    if hit:
        inside_hubs.append((airport['icao'], airport['name'], hub['name']))
    print(f"  {airport['icao']} {airport['name'][:30]:<30} bearing={bearing:5.1f} "
          f"{record[2]}({record[3]}) hub={hub['name']}({airport['distanceToCityKm']}km) inside={hit}")

print()
print(f'机场巡视检查区域覆盖的城市枢纽: {len(inside_hubs)}')
for row in inside_hubs:
    print('   ', row)

# Reference routes: how many are crossed by a strip?
network_routes = []
import importlib  # noqa: E402

traffic_network = importlib.import_module('traffic.service').network()
for route in traffic_network['routes']:
    if route.get('path'):
        network_routes.append(route)
crossed = []
for route in network_routes:
    line = LineString(route['path'])
    hits = [icao for icao, geometry in strips.items() if line.intersects(geometry)]
    if hits:
        crossed.append((route['id'], route.get('name'), hits))
print()
print(f'参考航线总数 {len(network_routes)}, 被巡视检查区域穿越 {len(crossed)}')
for row in crossed[:40]:
    print('   ', row)
