"""Reconnaissance: clause-(六) facilities, one narrow Overpass query at a time.

The combined query (man_made=radar + military=radar + tower:type=radar +
aeroway=navigationaid over the whole northeast) kept timing out at the server,
so each tag gets its own small request and its own cache file.
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
import time
import urllib.parse
import urllib.request


from shapely.geometry import Point  # noqa: E402
from weather.geometry import boundary, project  # noqa: E402
from traffic.catalog import cities  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


UA = 'ALC-research/0.1 (low-altitude traffic simulation, contact: project owner)'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
OPENER.addheaders = [('User-Agent', UA)]
CACHE = ROOT / '.run' / 'zones_recon'
CACHE.mkdir(parents=True, exist_ok=True)
BBOX = '38.0,117.0,54.5,136.5'
ENDPOINTS = ('https://overpass-api.de/api/interpreter',
             'https://overpass.kumi.systems/api/interpreter',
             'https://overpass.private.coffee/api/interpreter')

QUERIES = {
    'navigationaid': f'[out:json][timeout:90];nwr["aeroway"="navigationaid"]({BBOX});out center tags;',
    'radar_manmade': f'[out:json][timeout:90];nwr["man_made"="radar"]({BBOX});out center tags;',
    'radar_tower': f'[out:json][timeout:90];nwr["tower:type"="radar"]({BBOX});out center tags;',
    'radar_military': f'[out:json][timeout:90];nwr["military"="radar"]({BBOX});out center tags;',
    'weather_station': f'[out:json][timeout:90];nwr["man_made"="monitoring_station"]["monitoring:weather"="yes"]({BBOX});out center tags;',
}


def fetch(name, query):
    path = CACHE / f'{name}.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))['elements']
    body = urllib.parse.urlencode({'data': query}).encode()
    for endpoint in ENDPOINTS:
        try:
            with OPENER.open(urllib.request.Request(endpoint, data=body), timeout=140) as response:
                path.write_bytes(response.read())
            return json.loads(path.read_text(encoding='utf-8'))['elements']
        except Exception as exc:  # noqa: BLE001
            print(f'  {name}: {endpoint.split("/")[2]} -> {type(exc).__name__}')
            time.sleep(2)
    return []


def centre(element):
    if element.get('lat') is not None:
        return element['lat'], element['lon']
    if element.get('center'):
        return element['center']['lat'], element['center']['lon']
    return None, None


for name, query in QUERIES.items():
    elements = fetch(name, query)
    inside = []
    for element in elements:
        lat, lon = centre(element)
        if lat is None:
            continue
        xy = project((lon, lat))
        if not boundary().covers(Point(xy)):
            continue
        nearest = min(cities(), key=lambda city: math.dist(city['xy'], xy))
        inside.append((element, lat, lon, nearest, math.dist(nearest['xy'], xy) / 1000))
    print(f'{name}: {len(elements)} in bbox, {len(inside)} inside 东北三省')
    for element, lat, lon, nearest, distance in inside:
        tags = element.get('tags') or {}
        keys = ('name', 'name:zh', 'operator', 'ref', 'aeroway', 'man_made', 'tower:type', 'military',
                'monitoring:weather')
        shown = '|'.join(f'{key}={tags[key]}' for key in keys if key in tags)
        print(f"   {element['type']}/{element['id']:<12} {lat:.4f},{lon:.4f} {nearest['name']}({distance:.1f}km) {shown[:90]}")
