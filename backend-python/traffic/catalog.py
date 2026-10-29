import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

from shapely.geometry import Point

from weather.geometry import boundary, project

CATALOG_FILE = Path(__file__).resolve().parents[1] / 'data' / 'traffic' / 'city-centers.json'
PROVINCES = ('辽宁省', '吉林省', '黑龙江省')

@lru_cache(maxsize=1)
def _catalog():
    value = json.loads(CATALOG_FILE.read_text(encoding='utf-8'))
    rows = value.get('cities', [])
    if len(rows) != 36 or len({row.get('id') for row in rows}) != 36:
        raise ValueError('城市目录必须包含 36 个唯一城市')
    return value

ROWS = {
    province: [(row['name'], *row['coordinate']) for row in _catalog()['cities'] if row['province'] == province]
    for province in PROVINCES
}

@lru_cache(maxsize=1)
def cities():
    result = []
    for row in _catalog()['cities']:
        coordinate = list(row['coordinate'])
        xy = list(project(coordinate))
        valid = boundary(row['province']).covers(Point(xy))
        result.append({
            **row,
            'coordinate': coordinate,
            'xy': xy,
            'coordinateValid': valid,
            'coordinateStatus': 'VALID' if valid else 'OUTSIDE_PROVINCE_REVIEW_REQUIRED',
        })
    return result

def city_pads(city):
    if not city['coordinateValid']:
        return []
    return [{
        'id': f"CITY-{city['id']}", 'cityId': city['id'], 'kind': 'CITY_HUB',
        'name': f"{city['name']}中心枢纽", 'xy': list(city['xy']),
        'coordinate': list(city['coordinate']), 'groundElevationMSL': None,
        'capacity': 4, 'status': 'SIMULATED_REFERENCE', 'offsetFromCenterM': 0.0,
    }]

def delivery_nodes(city, count=10):
    if not city['coordinateValid']:
        return []
    allowed = boundary(city['province']).intersection(Point(city['xy']).buffer(6000))
    seed = int(hashlib.sha256(city['id'].encode()).hexdigest()[:8], 16)
    result = []
    for index in range(count):
        angle = (seed % 360 + index * 137.507764) * math.pi / 180
        radius = 1800 + ((seed >> (index % 16)) % 3500)
        point = [city['xy'][0] + math.cos(angle) * radius, city['xy'][1] + math.sin(angle) * radius]
        if not allowed.covers(Point(point)):
            continue
        role = 'MERCHANT' if index % 3 == 0 else 'RECEIVER'
        result.append({
            'id': f"DEL-{city['id']}-{index + 1:02}", 'cityId': city['id'], 'kind': role,
            'name': f"{city['name']}{'商家' if role == 'MERCHANT' else '收货'}节点{index + 1}",
            'xy': point, 'capacity': 1, 'status': 'SIMULATED_SERVICE_NODE',
        })
    return result

@lru_cache(maxsize=1)
def connections():
    result = set()
    valid_cities = [city for city in cities() if city['coordinateValid']]
    for province in PROVINCES:
        group = [city for city in valid_cities if city['province'] == province]
        pairs = sorted((math.dist(a['xy'], b['xy']), a['id'], b['id'])
                       for i, a in enumerate(group) for b in group[i + 1:])
        components = {city['id']: {city['id']} for city in group}
        for _, a, b in pairs:
            if b not in components[a]:
                merged = components[a] | components[b]
                result.add(tuple(sorted((a, b))))
                for key in merged:
                    components[key] = merged
        for city in group:
            nearest = [(distance, a, b) for distance, a, b in pairs if city['id'] in (a, b)][:2]
            result.update(tuple(sorted((a, b))) for _, a, b in nearest)
    result.update((('1-01', '2-01'), ('2-01', '3-01')))
    return sorted(result)
