"""Reconnaissance: build a candidate list of publicly locatable固定设施 in 东北三省.

Sources, both public and queryable:
  * OurAirports (public domain, https://ourairports-data/) for 民用运输机场.
  * OpenStreetMap via the Overpass API for 核设施 / 水库 / 港口 / 纪念地 / 天文台 / 雷达站.

Output is a review table only; nothing here is written into the application.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, ARTIFACTS  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ARTIFACTS = Path(ARTIFACTS)
import csv
import io
import json
import urllib.parse
import urllib.request


from shapely.geometry import Point  # noqa: E402
from weather.geometry import boundary, project  # noqa: E402
from traffic.catalog import cities  # noqa: E402


UA = 'ALC-research/0.1 (low-altitude traffic simulation, contact: project owner)'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
OPENER.addheaders = [('User-Agent', UA)]
OUT = Path(ARTIFACTS) / '.run' / 'zones_recon'
OUT.mkdir(parents=True, exist_ok=True)

# 东北三省 bbox, deliberately a little wider than the boundary itself.
BBOX = (38.0, 117.0, 54.5, 136.5)


def fetch(url, data=None, timeout=180):
    request = urllib.request.Request(url, data=data)
    with OPENER.open(request, timeout=timeout) as response:
        return response.read()


def airports():
    cache = OUT / 'airports.csv'
    if not cache.exists():
        cache.write_bytes(fetch('https://davidmegginson.github.io/ourairports-data/airports.csv'))
    rows = []
    text = cache.read_text(encoding='utf-8', errors='replace')
    for row in csv.DictReader(io.StringIO(text)):
        if row.get('iso_country') != 'CN':
            continue
        if row.get('type') not in ('large_airport', 'medium_airport'):
            continue
        try:
            lat, lon = float(row['latitude_deg']), float(row['longitude_deg'])
        except (TypeError, ValueError):
            continue
        if not (BBOX[0] <= lat <= BBOX[2] and BBOX[1] <= lon <= BBOX[3]):
            continue
        xy = project((lon, lat))
        if not boundary().covers(Point(xy)):
            continue
        nearest = min(cities(), key=lambda city: ((city['xy'][0] - xy[0]) ** 2 + (city['xy'][1] - xy[1]) ** 2))
        distance = ((nearest['xy'][0] - xy[0]) ** 2 + (nearest['xy'][1] - xy[1]) ** 2) ** 0.5
        rows.append({
            'ident': row['ident'], 'icao': row['icao_code'], 'iata': row['iata_code'],
            'name': row['name'], 'municipality': row['municipality'],
            'lat': lat, 'lon': lon, 'elevationFt': row['elevation_ft'],
            'scheduled': row['scheduled_service'],
            'nearestCity': nearest['name'], 'nearestCityId': nearest['id'],
            'distanceToCityKm': round(distance / 1000, 1),
        })
    rows.sort(key=lambda row: (row['nearestCityId'], row['name']))
    return rows


OVERPASS_QUERY = """
[out:json][timeout:240];
(
  nwr["plant:source"="nuclear"]({bbox});
  nwr["generator:source"="nuclear"]({bbox});
  nwr[name~"核电"]({bbox});
  nwr["water"="reservoir"]({bbox});
  nwr["landuse"="reservoir"]({bbox});
  nwr["waterway"="dam"]({bbox});
  nwr["harbour"]({bbox});
  nwr["amenity"="observatory"]({bbox});
  nwr["man_made"="observatory"]({bbox});
  nwr["man_made"="radar"]({bbox});
  nwr["tower:type"="radar"]({bbox});
  nwr["man_made"="tower"]["name"~"雷达"]({bbox});
  nwr["tourism"="museum"]["name"~"纪念馆|陈列馆|博物馆"]({bbox});
  nwr["historic"="memorial"]["name"~"纪念馆|九·一八|九一八"]({bbox});
);
out center tags;
"""


def facilities():
    # Overpass wants a form-encoded body; a JSON body is rejected with HTTP 400.
    body = urllib.parse.urlencode(
        {'data': OVERPASS_QUERY.format(bbox=f'{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}')}).encode()
    raw = fetch('https://overpass-api.de/api/interpreter', data=body)
    (OUT / 'overpass.json').write_bytes(raw)
    elements = json.loads(raw.decode('utf-8'))['elements']
    rows = []
    for element in elements:
        tags = element.get('tags') or {}
        lat = element.get('lat') or (element.get('center') or {}).get('lat')
        lon = element.get('lon') or (element.get('center') or {}).get('lon')
        if lat is None or lon is None:
            continue
        xy = project((lon, lat))
        inside = boundary().covers(Point(xy))
        nearest = min(cities(), key=lambda city: ((city['xy'][0] - xy[0]) ** 2 + (city['xy'][1] - xy[1]) ** 2))
        distance = ((nearest['xy'][0] - xy[0]) ** 2 + (nearest['xy'][1] - xy[1]) ** 2) ** 0.5
        rows.append({
            'osm': f"{element['type']}/{element['id']}", 'name': tags.get('name'),
            'lat': round(lat, 5), 'lon': round(lon, 5), 'latlng': f'{lat:.6f},{lon:.6f}',
            'latlngShort': f'{lat:.4f},{lon:.4f}',
            'insideBoundary': inside, 'nearestCity': nearest['name'],
            'distanceToCityKm': round(distance / 1000, 1), 'tags': tags,
        })
    rows.sort(key=lambda row: (row['name'] or '', row['osm']))
    return rows


if __name__ == '__main__':
    data = {'airports': airports(), 'facilities': facilities()}
    (OUT / 'candidates.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"airports: {len(data['airports'])}")
    for row in data['airports']:
        print(f"  {row['icao'] or '-':<5} {row['iata'] or '-':<4} {row['name'][:34]:<34} "
              f"{row['lat']:.4f},{row['lon']:.4f} {row['nearestCity']} {row['distanceToCityKm']}km sched={row['scheduled']}")
    print(f"facilities: {len(data['facilities'])}")
    for row in data['facilities']:
        print(f"  {row['osm']:<16} {(row['name'] or '?')[:30]:<30} {row['latlngShort']} "
              f"{row['nearestCity']} {row['distanceToCityKm']}km in={row['insideBoundary']}")
