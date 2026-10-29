"""Reconnaissance: runway bearings and clause-(六) facilities from OpenStreetMap.

OurAirports carries runway headings for only 7 of the 24 运输机场, and the
净空巡视检查区域 needs the real runway bearing. OSM maps the runways and the
navigation aids directly, so derive both from geometry rather than assuming.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ROOT = Path(ROOT)
import json
import urllib.parse
import urllib.request


import math  # noqa: E402
from shapely.geometry import LineString, Point, MultiPoint  # noqa: E402
from weather.geometry import boundary, project  # noqa: E402
from traffic.catalog import cities  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


UA = 'ALC-research/0.1 (low-altitude traffic simulation, contact: project owner)'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
OPENER.addheaders = [('User-Agent', UA)]
CACHE = ROOT / '.run' / 'zones_recon'
CACHE.mkdir(parents=True, exist_ok=True)
BBOX = '38.0,117.0,54.5,136.5'

RUNWAY_QUERY = f"""
[out:json][timeout:180];
way["aeroway"="runway"]({BBOX});
out geom tags;
"""

AID_QUERY = f"""
[out:json][timeout:180];
(
  nwr["man_made"="radar"]({BBOX});
  nwr["tower:type"="radar"]({BBOX});
  nwr["military"="radar"]({BBOX});
  nwr["aeroway"="navigationaid"]({BBOX});
);
out center tags;
"""

ENDPOINTS = ('https://overpass-api.de/api/interpreter',
             'https://overpass.kumi.systems/api/interpreter',
             'https://overpass.private.coffee/api/interpreter')


def overpass(name, query):
    path = CACHE / f'{name}.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))['elements']
    body = urllib.parse.urlencode({'data': query}).encode()
    last = None
    for endpoint in ENDPOINTS:
        for attempt in range(2):
            try:
                with OPENER.open(urllib.request.Request(endpoint, data=body), timeout=200) as response:
                    path.write_bytes(response.read())
                return json.loads(path.read_text(encoding='utf-8'))['elements']
            except Exception as exc:  # noqa: BLE001 - reconnaissance reports the raw reason
                last = f'{endpoint} attempt {attempt + 1}: {type(exc).__name__}: {exc}'
                print(f'  retry: {last}')
    raise RuntimeError(last)


def centre(element):
    if element.get('lat') is not None:
        return element['lat'], element['lon']
    if element.get('center'):
        return element['center']['lat'], element['center']['lon']
    geometry = element.get('geometry')
    if geometry:
        lat = sum(point['lat'] for point in geometry) / len(geometry)
        lon = sum(point['lon'] for point in geometry) / len(geometry)
        return lat, lon
    return None, None


# ---------------------------------------------------------------- runways
airports = json.loads((CACHE / 'candidates.json').read_text(encoding='utf-8'))['airports']
airports = [row for row in airports if row['scheduled'] == 'yes']
runways = []
for element in overpass('runways', RUNWAY_QUERY):
    if element.get('tags', {}).get('aeroway') != 'runway':
        continue
    geometry = element.get('geometry')
    if not geometry or len(geometry) < 2:
        continue
    line = LineString([(point['lon'], point['lat']) for point in geometry])
    mid = line.interpolate(0.5, normalized=True)
    runways.append({
        'osm': f"way/{element['id']}", 'name': element.get('tags', {}).get('name'),
        'ref': element.get('tags', {}).get('ref'),
        'lon': mid.x, 'lat': mid.y, 'lengthM': line.length * 111320 * math.cos(math.radians(mid.y)),
        'coords': [(point['lon'], point['lat']) for point in geometry],
    })

print(f'OSM runways in bbox: {len(runways)}')
print()
print('nearest OSM runway per 运输机场 (bearing derived from the real geometry):')
resolved = {}
for airport in sorted(airports, key=lambda row: row['ident']):
    target = Point(airport['lon'], airport['lat'])
    candidates = sorted(runways, key=lambda row: target.distance(Point(row['lon'], row['lat'])))
    if not candidates:
        continue
    nearest = candidates[0]
    distance_m = target.distance(Point(nearest['lon'], nearest['lat'])) * 111320 * math.cos(math.radians(airport['lat']))
    if distance_m > 8000:
        print(f"  {airport['icao'] or airport['ident']:<6} {airport['name'][:30]:<30} NO RUNWAY WITHIN 8 km "
              f"(nearest {distance_m / 1000:.1f} km)")
        continue
    end_a, end_b = nearest['coords'][0], nearest['coords'][-1]
    dx = (end_b[0] - end_a[0]) * math.cos(math.radians(end_a[1]))
    dy = end_b[1] - end_a[1]
    bearing = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    resolved[airport['icao'] or airport['ident']] = round(bearing, 1)
    print(f"  {airport['icao'] or airport['ident']:<6} {airport['name'][:30]:<30} "
          f"bearing={bearing:6.1f} len={nearest['lengthM']:6.0f}m off={distance_m:5.0f}m "
          f"ref={nearest['ref']} {nearest['osm']}")

print()
print('resolved:', json.dumps(resolved, ensure_ascii=False))
(CACHE / 'runway_bearings.json').write_text(json.dumps(resolved, indent=2), encoding='utf-8')

# ------------------------------------------------------- clause-(六) facilities
print()
print('clause (六) facilities from OSM:')
for element in overpass('aids', AID_QUERY):
    tags = element.get('tags') or {}
    lat, lon = centre(element)
    if lat is None:
        continue
    inside = boundary().covers(Point(project((lon, lat))))
    if not inside:
        continue
    nearest = min(cities(), key=lambda city: math.dist(city['xy'], project((lon, lat))))
    kinds = [f'{key}={tags[key]}' for key in ('man_made', 'tower:type', 'military', 'aeroway', 'operator', 'name:zh')
             if key in tags]
    print(f"  {element['type']}/{element['id']:<12} {(tags.get('name') or '(unnamed)')[:26]:<26} "
          f"{lat:.4f},{lon:.4f} {'|'.join(kinds)[:60]:<62} {nearest['name']}")
