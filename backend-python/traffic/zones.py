import json
from functools import lru_cache
from pathlib import Path

import numpy
from shapely import affinity, intersects_xy
from shapely.geometry import GeometryCollection, Point, box, mapping
from shapely.ops import unary_union
from shapely.strtree import STRtree

from weather.geometry import boundary, geojson, project

CATALOG_FILE = Path(__file__).resolve().parents[1] / 'data' / 'traffic' / 'fixed-zones.json'

PROHIBITED = 'PROHIBITED'
APPROVAL_REQUIRED = 'APPROVAL_REQUIRED'
REGISTERED = 'REGISTERED_REVIEW_REQUIRED'
ENFORCEMENT_LEVELS = (PROHIBITED, APPROVAL_REQUIRED, REGISTERED)

GEOMETRY_KINDS = ('CIRCLE', 'RUNWAY_RECT')

CIRCLE_QUADRANT_SEGMENTS = 8

DEFAULT_POLICY = APPROVAL_REQUIRED

DEFAULT_REPORT_LIMIT = 6

@lru_cache(maxsize=4)
def catalog():
    value = json.loads(CATALOG_FILE.read_text(encoding='utf-8'))
    clauses = {clause['key']: clause for clause in value['clauses']}
    for site in value['sites']:
        if site['clause'] not in clauses:
            raise ValueError(f"固定管制区 {site['id']} 引用了未知类别 {site['clause']}")
        if site['enforcement'] not in ENFORCEMENT_LEVELS:
            raise ValueError(f"固定管制区 {site['id']} 的 enforcement 非法：{site['enforcement']}")
        geometry = site.get('geometry')
        if geometry is None:
            if not site.get('geometryStatus') or 'NOT_PUBLICLY_PUBLISHED' not in site['geometryStatus'] \
                    and 'REQUIRES_LOCAL_PUBLICATION' not in site['geometryStatus']:
                raise ValueError(f"固定管制区 {site['id']} 缺少几何时未声明原因")
            if not (site.get('referencePoint') or {}).get('coordinate'):
                raise ValueError(f"固定管制区 {site['id']} 缺少公开参考点")
            continue
        if geometry['kind'] not in GEOMETRY_KINDS:
            raise ValueError(f"固定管制区 {site['id']} 使用了未公开的几何种类 {geometry['kind']}")
        if not site.get('citation'):
            raise ValueError(f"固定管制区 {site['id']} 缺少法定依据")
    return value

def clauses():
    return catalog()['clauses']

def sites(policy=DEFAULT_POLICY):
    result = []
    for site in catalog()['sites']:
        record = dict(site)
        if policy == PROHIBITED and record.get('strictEnforcement') == PROHIBITED:
            record['enforcement'] = PROHIBITED
            record['enforcementNote'] = '按严格口径将机场巡视检查区域视为一律禁止进入。'
        result.append(record)
    return result

def _circle(centre, radius):
    return Point(centre).buffer(radius, quad_segs=CIRCLE_QUADRANT_SEGMENTS)

def _runway_rectangle(centre, bearing, runway_length_m, half_width, beyond_end):
    length = runway_length_m + beyond_end * 2
    width = half_width * 2
    geometry = box(centre[0] - length / 2, centre[1] - width / 2, centre[0] + length / 2, centre[1] + width / 2)
    return affinity.rotate(geometry, 90 - bearing, origin=centre)

@lru_cache(maxsize=4)
def _geometries(policy=DEFAULT_POLICY):
    result = {}
    for site in sites(policy):
        geometry = site.get('geometry')
        if not geometry:
            continue
        centre = project(tuple(geometry['centre']))
        if geometry['kind'] == 'CIRCLE':
            result[site['id']] = _circle(centre, float(geometry['radiusM']))
        else:
            result[site['id']] = _runway_rectangle(
                centre, float(geometry['bearingDeg']), float(geometry['runwayLengthM']),
                float(geometry['halfWidthM']), float(geometry['beyondEndM']))
    return result

def envelope(policy=DEFAULT_POLICY):
    shapes = [geometry for site_id, geometry in _geometries(policy).items()
              if _by_id(policy)[site_id]['enforcement'] == PROHIBITED]
    return unary_union(shapes) if shapes else GeometryCollection()

@lru_cache(maxsize=4)
def _by_id(policy=DEFAULT_POLICY):
    return {site['id']: site for site in sites(policy)}

@lru_cache(maxsize=4)
def _index(policy=DEFAULT_POLICY):
    geometries = _geometries(policy)
    ids = sorted(geometries)
    return ids, STRtree([geometries[site_id] for site_id in ids])

def _overlapping(footprint, policy):
    ids, tree = _index(policy)
    geometries = _geometries(policy)
    return [(ids[int(index)], geometries[ids[int(index)]]) for index in tree.query(footprint)]

def _vertical_band(site):
    floor = float(site.get('floorAglM') or 0)
    ceiling = site.get('ceilingAglM')
    return floor, (None if ceiling is None else float(ceiling))

def crossings(points, policy=DEFAULT_POLICY, limit=DEFAULT_REPORT_LIMIT):
    empty = {'zones': 0, 'prohibited': 0, 'approvalRequired': 0, 'clauses': []}
    if not points:
        return empty, []
    xs = numpy.array([point[0] for point in points])
    ys = numpy.array([point[1] for point in points])
    zs = numpy.array([point[2] for point in points])
    footprint = box(xs.min() - 1, ys.min() - 1, xs.max() + 1, ys.max() + 1)
    records = []
    for site_id, geometry in _overlapping(footprint, policy):
        site = _by_id(policy)[site_id]
        floor, ceiling = _vertical_band(site)
        band = zs >= floor
        if ceiling is not None:
            band &= zs <= ceiling
        if not band.any():
            continue
        hit = intersects_xy(geometry, xs, ys) & band
        if not hit.any():
            continue
        index = numpy.nonzero(hit)[0]
        records.append({
            'zoneId': site_id, 'name': site['name'], 'clause': site['clause'],
            'sector': site['sector'], 'enforcement': site['enforcement'],
            'entryMinute': round(float(points[index[0]][3]), 2),
            'exitMinute': round(float(points[index[-1]][3]), 2),
            'maxAglM': round(float(zs[index].max()), 1),
            'citation': site.get('citation'),
        })
    records.sort(key=lambda record: (-_priority(record['enforcement']), record['entryMinute'], record['zoneId']))
    summary = {
        'zones': len(records),
        'prohibited': sum(1 for record in records if record['enforcement'] == PROHIBITED),
        'approvalRequired': sum(1 for record in records if record['enforcement'] == APPROVAL_REQUIRED),
        'clauses': sorted({record['clause'] for record in records}),
    }
    return summary, records[:limit]

def _priority(enforcement):
    return {PROHIBITED: 2, APPROVAL_REQUIRED: 1}.get(enforcement, 0)

def point_zones(coordinate, policy=DEFAULT_POLICY):
    x, y = project(tuple(coordinate))
    target = Point(x, y)
    return [_by_id(policy)[site_id] for site_id, geometry in _overlapping(target, policy)
            if intersects_xy(geometry, x, y)]

def covering_layer(coordinate, agl_m=None, policy=DEFAULT_POLICY):
    return [site for site in point_zones(coordinate, policy)
            if agl_m is None or (_vertical_band(site)[0] <= agl_m
                                 and (_vertical_band(site)[1] is None or agl_m <= _vertical_band(site)[1]))]

def rules(policy=DEFAULT_POLICY):
    value = catalog()
    return {
        'catalogVersion': value['catalogVersion'],
        'dataRetrievedAt': value['dataRetrievedAt'],
        'airportFootprintPolicy': policy,
        'legalFramework': value['legalFramework'],
        'disclaimer': value['disclaimer'],
        'labels': {
            'STATIC_PROHIBITED': '固定管制区（未获批准不得进入）',
            'STATIC_APPROVAL_REQUIRED': '固定管制空域（须经批准）',
            'STATIC_REGISTERED': '已登记待补范围',
        },
        'enforcementNote': '固定管制区与气象派生风险区是两套东西：前者来自法规与公开数据，'
                           '不随时间变化；后者是本系统按气象阈值推导的飞行风险区，不是官方空域管制。',
    }

def frame(policy=DEFAULT_POLICY, display_ceiling_agl_m=None):
    result = []
    for site in sites(policy):
        geometry = site.get('geometry')
        record = {
            'id': site['id'], 'name': site['name'], 'clause': site['clause'],
            'sector': site['sector'], 'sectorLabel': site['sectorLabel'],
            'enforcement': site['enforcement'], 'geometryStatus': site['geometryStatus'],
            'facilityType': site.get('facilityType'), 'authority': site.get('authority'),
            'citation': site.get('citation'), 'geometryRule': site.get('geometryRule'),
            'floorAglM': site.get('floorAglM'), 'ceilingAglM': site.get('ceilingAglM'),
            'note': site.get('note'),
        }
        if not geometry:
            record['referencePoint'] = site['referencePoint']
            result.append(record)
            continue
        projected = _geometries(policy)[site['id']].intersection(boundary())
        if projected.is_empty:
            continue
        floor = float(site.get('floorAglM') or 0)
        ceiling = site.get('ceilingAglM')
        drawn = display_ceiling_agl_m if ceiling is None else float(ceiling)
        record['geometry'] = geojson(projected)
        record['floorAglM'] = floor
        record['displayCeilingAglM'] = max(drawn or floor + 1, floor + 1)
        record['openEndedAbove'] = ceiling is None
        result.append(record)
    return result

def audit(policy=DEFAULT_POLICY):
    counts = {}
    for site in sites(policy):
        key = site['clause']
        bucket = counts.setdefault(key, {'sites': 0, 'withGeometry': 0, 'prohibited': 0,
                                         'approvalRequired': 0, 'registered': 0})
        bucket['sites'] += 1
        if site.get('geometry'):
            bucket['withGeometry'] += 1
        bucket[{'PROHIBITED': 'prohibited', 'APPROVAL_REQUIRED': 'approvalRequired',
                'REGISTERED_REVIEW_REQUIRED': 'registered'}[site['enforcement']]] += 1
    return {
        'catalogVersion': catalog()['catalogVersion'],
        'sites': len(catalog()['sites']),
        'withGeometry': sum(1 for site in catalog()['sites'] if site.get('geometry')),
        'clauses': [{'key': clause['key'], 'clause': clause['clause'], 'title': clause['title'],
                     'sector': clause['sector'], 'sectorLabel': clause['sectorLabel'],
                     'geometryStatus': clause['geometryStatus'], 'geometryRule': clause.get('geometryRule'),
                     'citation': clause.get('citation'), 'authority': clause.get('authority'),
                     'reviewAction': clause.get('reviewAction'),
                     **counts.get(clause['key'], {'sites': 0, 'withGeometry': 0, 'prohibited': 0,
                                                  'approvalRequired': 0, 'registered': 0})}
                    for clause in clauses()],
    }

def status(policy=DEFAULT_POLICY):
    value = catalog()
    shapes = _geometries(policy)
    return {
        'ready': True,
        'catalogVersion': value['catalogVersion'],
        'dataRetrievedAt': value['dataRetrievedAt'],
        'sites': len(value['sites']),
        'withGeometry': len(shapes),
        'prohibited': sum(1 for site in sites(policy) if site['enforcement'] == PROHIBITED),
        'approvalRequired': sum(1 for site in sites(policy) if site['enforcement'] == APPROVAL_REQUIRED),
        'registered': sum(1 for site in sites(policy) if site['enforcement'] == REGISTERED),
        'clauses': len(value['clauses']),
        'policy': policy,
        'note': '未取得公开定量范围的类别只登记、不生成几何。',
    }
