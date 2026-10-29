import hashlib
import heapq
import itertools
import json
import logging
import math
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from shapely.geometry import GeometryCollection, LineString, Point, mapping
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree
from shapely.validation import make_valid

from weather.geometry import BOUNDARY_VERSION, INVERSE, boundary, geojson, province_feature_collection
from weather import geometry
from . import airspace, cma_tiles, delivery, radar_field, weather_control, weather_sim, zones as fixed_zones
from .catalog import CATALOG_FILE, city_pads, cities, connections, delivery_nodes
from .obstacles import SOURCE_VERSION as OBSTACLE_SOURCE_VERSION, evaluate as evaluate_obstacles
from .resources import ResourceCalendar, crossing_zones
from .routing import penetration_limit, route
from .spatial import bbox_2d, bbox_apart, conflict, rounded_path, trajectory, within_profile
from .weather import (LiveWeatherEnvelope, PublicWeather, _polygon_parts,
                      extreme_thresholds, fog_rule_block, fog_tiers)
from .weather_sources import provider_status, weather_snapshot as weather_snapshot_entry
import workspace as workspace_ctx

VERSION = 'city-traffic-1.3'
PLAN_REVISION = 'traffic-plan-v1.3'

_PLAN_REV_SEQ = itertools.count(1)
PROFILE_FILE = Path(__file__).resolve().parents[1] / 'data' / 'traffic' / 'aircraft-profiles.json'
ZONE_FILE = Path(__file__).resolve().parents[1] / 'data' / 'traffic' / 'fixed-zones.json'
STORE = Path(__file__).resolve().parents[2] / '.run' / 'traffic'
KEEP_PER_GENERATION = 8
RECENT_PROTECT_SECONDS = 600
LOCK = threading.Lock()
POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='traffic')
JOBS_LIMIT = 2
JOBS = {}

_SIMULATE_LOCK = threading.Lock()
_SIM_DAY = datetime.now(timezone.utc).date()
SIMULATION_BASE_TIME = datetime(_SIM_DAY.year, _SIM_DAY.month, _SIM_DAY.day, 10, 0, tzinfo=timezone.utc)
weather_sim.set_drift_reference(SIMULATION_BASE_TIME)
TIMELINE_MINUTES = 480
DISPLAY_BUCKET_MINUTES = 2
RADAR_SWEEP_LAG_BUCKETS = 5
RADAR_SWEEP_STRIDE_MINUTES = DISPLAY_BUCKET_MINUTES * RADAR_SWEEP_LAG_BUCKETS
PROGRESS_START_PERCENT = 2
PROGRESS_SNAPSHOT_PERCENT = 10
PROGRESS_SWEEP_PERCENT = 32
PROGRESS_STAGES = (
    (0, '准备气象快照与空域目录'),
    (PROGRESS_START_PERCENT, '生成运行班次'),
    (PROGRESS_SNAPSHOT_PERCENT, '读取雷达回波并展开时轴'),
    (PROGRESS_SWEEP_PERCENT, '逐班次规划航路与间隔'),
)
RADAR_WAIT_PROBES = (0.0, 0.5, 1.0)
DETOUR_WINDOW_PADDING_MINUTES = 0.0

DELAY_SELECTION_STRATEGY = 'minimal'

WIND_BAND_M = 45_000
WIND_SAMPLE_SPACING_M = 55_000
WIND_MAX_VECTORS = 900
WIND_NEIGHBOURS = 4
WIND_EDGE_TOLERANCE_M = 40_000

WEATHER_CLOSURE_REASONS = frozenset({
    'WEATHER_BLOCKED', 'WEATHER_UNAVAILABLE', 'FINAL_WEATHER_OR_BOUNDARY_CHECK_FAILED',
})

def _fingerprint():
    files = sorted(Path(__file__).parent.glob('*.py')) + [CATALOG_FILE, PROFILE_FILE, ZONE_FILE]
    return hashlib.sha256(b''.join(path.read_bytes() for path in files) + BOUNDARY_VERSION.encode()).hexdigest()[:16]

FINGERPRINT = _fingerprint()

def _operations_fingerprint() -> str:
    try:
        import json as _json
        from pathlib import Path as _Path
        path = _Path(__file__).resolve().parents[2] / 'config' / 'rules-v1.json'
        operations = (_json.loads(path.read_text(encoding='utf-8')) or {}).get('operations') or {}
        payload = _json.dumps(operations, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()[:8]
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            'operations 指纹计算失败，回落 no-operations：'
            '此后改 config/rules-v1.json 的 operations 段**不会**让计划键失效。%s', exc)
        return 'no-operations'

OPERATIONS_FINGERPRINT = _operations_fingerprint()

@lru_cache(maxsize=1)
def profiles():
    value = json.loads(PROFILE_FILE.read_text(encoding='utf-8'))
    for mode in ('CAR', 'DELIVERY'):
        profile = value[mode]
        if profile['maxCruiseAglM'] < max(profile['cruiseLayersAglM']):
            raise ValueError(f'{mode} 高度层超过上限')
        if profile['minCruiseAglM'] > min(profile['cruiseLayersAglM']):
            raise ValueError(f'{mode} 高度层低于巡航下界')
        airspace.layers(profile)
    operations = value.get('operations') or {}
    if operations.get('riskCeilingAglM', 0) < max(value[mode]['maxCruiseAglM'] for mode in ('CAR', 'DELIVERY')):
        raise ValueError('风险区上限未覆盖机型高度上限')
    policy = (operations.get('staticAirspace') or {}).get('airportFootprintPolicy', fixed_zones.DEFAULT_POLICY)
    if policy not in (fixed_zones.APPROVAL_REQUIRED, fixed_zones.PROHIBITED):
        raise ValueError(f'机场净空区域执行口径非法：{policy}')
    return value

def airport_footprint_policy():
    return (operations().get('staticAirspace') or {}).get('airportFootprintPolicy', fixed_zones.DEFAULT_POLICY)

def operations():
    return profiles()['operations']

def _instant(minute):
    return (SIMULATION_BASE_TIME + timedelta(minutes=float(minute))).isoformat().replace('+00:00', 'Z')

def _line(points):
    return LineString([point[:2] for point in points])

@lru_cache(maxsize=1)
def network():
    lookup = {city['id']: city for city in cities()}
    pads = [pad for city in cities() for pad in city_pads(city)]
    settings = operations()['delivery']
    routes = []
    for corridor_index, (first_id, second_id) in enumerate(connections()):
        first, second = lookup[first_id], lookup[second_id]
        province = first['province'] if first['province'] == second['province'] else None
        first_pad, second_pad = city_pads(first)[0], city_pads(second)[0]
        path = route(first_pad['xy'], second_pad['xy'], boundary(province))
        routes.append({
            'id': f'CAR-{first_id}-{second_id}', 'mode': 'CAR', 'fromCity': first_id, 'toCity': second_id,
            'fromPad': first_pad['id'], 'toPad': second_pad['id'], 'name': f"{first['name']} ↔ {second['name']}",
            'province': province, 'interprovincial': province is None, 'path': path,
            'fromXY': list(first_pad['xy']), 'toXY': list(second_pad['xy']), 'referencePath': path,
            'corridorIndex': corridor_index,
        })

    for missing in [item for item in routes if not item['path']]:
        edges = {city['id']: [] for city in cities()}
        for item in routes:
            if item['path'] and item['province'] == missing['province']:
                length = LineString(item['path']).length
                edges[item['fromCity']].append((item['toCity'], length, item['path']))
                edges[item['toCity']].append((item['fromCity'], length, list(reversed(item['path']))))
        queue, visited = [(0, missing['fromCity'], [])], set()
        while queue:
            cost, node, legs = heapq.heappop(queue)
            if node in visited:
                continue
            visited.add(node)
            if node == missing['toCity']:
                missing['path'] = legs
                missing['referencePath'] = legs
                break
            for destination, length, leg in edges[node]:
                if destination not in visited:
                    heapq.heappush(queue, (cost + length, destination, legs + leg[bool(legs):]))
    for city in cities():
        hub = city_pads(city)[0]
        nodes = delivery_nodes(city, settings['nodesPerCity'])
        pads.extend(nodes)
        allowed = boundary(city['province']).intersection(Point(city['xy']).buffer(settings['serviceRadiusM']))
        for index, node in enumerate(nodes[:settings['corridorsPerCity']]):
            path = route(hub['xy'], node['xy'], allowed)
            routes.append({
                'id': f"DEL-{city['id']}-{index + 1:02}", 'mode': 'DELIVERY', 'fromCity': city['id'], 'toCity': city['id'],
                'fromPad': hub['id'], 'toPad': node['id'], 'deliveryNode': node['id'],
                'name': f"{city['name']} · {node['name']}", 'province': city['province'], 'interprovincial': False,
                'path': path, 'fromXY': list(hub['xy']), 'toXY': list(node['xy']), 'referencePath': path,
                'corridorIndex': index,
            })

    return {
        'cities': cities(), 'pads': pads, 'routes': routes,
        'boundary': geojson(boundary()), 'boundaryXY': mapping(boundary().simplify(150, preserve_topology=True)),
        'administrativeBoundaries': province_feature_collection(), 'source': 'SIMULATION', 'version': VERSION,
        'planRevision': PLAN_REVISION, 'baseTime': SIMULATION_BASE_TIME.isoformat().replace('+00:00', 'Z'),
        'timezone': 'Asia/Shanghai',
        'riskRules': _risk_rules(),
        'staticAirspace': static_airspace(),
        'deliveryConfig': settings,
        'weatherProviders': provider_status(),
        'assumptions': {
            'horizontalSeparationM': profiles()['separation']['horizontalM'],
            'verticalSeparationM': profiles()['separation']['verticalM'],
            'climbMps': 3, 'carSpeedKmh': profiles()['CAR']['speedKmh'],
            'deliverySpeedKmh': profiles()['DELIVERY']['speedKmh'], 'maxExtraMinutes': profiles()['separation']['maxExtraMinutes'],
            'groundWaitStepMinutes': profiles()['separation']['groundWaitStepMinutes'],
            'departureHorizonMinutes': 180, 'timelineMinutes': TIMELINE_MINUTES,
            'altitudeDatum': 'AGL 模拟相对高度；DEM 与建筑净空数据当前未覆盖本地全部航迹。',
            'cityCoordinates': '版本化城区代表中心；中心枢纽与配送节点为可追溯的模拟运行数据。',
            'obstacleSourceVersion': OBSTACLE_SOURCE_VERSION,
            'cruiseLayers': {mode: profiles()[mode]['cruiseLayersAglM'] for mode in ('CAR', 'DELIVERY')},
            'flightCeilingsAglM': {mode: profiles()[mode]['maxCruiseAglM'] for mode in ('CAR', 'DELIVERY')},
            'noAltitudeStacking': '冲突以已声明高度层、时隙或地面等待解决，不叠加高度。',
        },
    }

def _risk_rules():
    settings = operations()['crossingZone']
    return {
        'ceilingAglM': operations()['riskCeilingAglM'],
        'floorAglM': 0,
        'horizontalSeparationM': profiles()['separation']['horizontalM'],
        'verticalSeparationM': profiles()['separation']['verticalM'],
        'crossingZoneCapacity': settings['capacity'],
        'crossingZoneWindowMinutes': settings['windowMinutes'],
        'crossingZoneCellM': settings['cellM'],
        'labels': {'BAN': '派生飞行风险区（禁止进入）', 'CAUTION': '派生飞行风险区（谨慎进入）'},
        'layerName': '派生飞行风险区',
        'derivation': '由气象场按本系统阈值派生，非官方空域管制范围。',
        'note': '系统派生的飞行限制，不等同于官方空域管制命令。',
    }

def _published(geometry_value):
    if geometry_value is None or geometry_value.is_empty:
        return None
    lonlat = transform(INVERSE.transform, geometry_value)
    if not lonlat.is_valid:
        lonlat = make_valid(lonlat)
    parts = _polygon_parts(lonlat)
    if not parts:
        return None
    polygonal = parts[0] if len(parts) == 1 else unary_union(parts)
    if polygonal.is_empty:
        return None
    return mapping(polygonal)

def radar_regions(minute=0):
    relay = None
    if weather_control.is_virtual():
        slot = SIMULATION_BASE_TIME + timedelta(minutes=float(minute))
        derived = _virtual_radar_derived(weather_control.seed(), slot)
        virtual = True
    else:
        frame_result = weather_control.radar_frame()
        relay = frame_result.get('relay')
        derived = radar_field.derive(frame_result, minute=minute)
        virtual = False
    summary = radar_field.summary(derived=derived, virtual=virtual)
    if not derived.get('available'):
        return {'available': False, 'regions': [], 'watch': None, 'summary': summary,
                'mode': weather_control.mode(), 'error': derived.get('error'),
                'relay': relay}
    field, core, caution, watch = radar_field.shield(derived)
    rules = _risk_rules()
    if virtual:
        source_id = 'SYNTHETIC_RADAR_CREF'
        source_note = '本区域几何由程序生成的模拟回波推导，不是观测结果的实况判读。'
    else:
        source_id = 'CMA_DATA_NET_RADAR_CREF'
        source_note = '本区域几何由 CMA 组网组合反射率瓦片实测推导。'
    watch_record = None
    if not watch.is_empty:
        published_watch = _published(watch)
        if published_watch is not None:
            watch_record = {
                'id': 'RADAR-CMA-CREF-WATCH', 'kind': 'RADAR_WATCH',
                'source': source_id,
                'slot': (derived.get('provenance') or {}).get('slot'),
                'band': 'STRATIFORM',
                'areaKm2': round(watch.area / 1e6, 1),
                'note': '15-35 dBZ 层状降水，可飞越，仅作可见性说明，不构成限制。',
                'field': published_watch,
            }
    published_field = _published(field)
    if published_field is None:
        return {'available': True, 'regions': [], 'watch': watch_record,
                'summary': summary, 'mode': weather_control.mode(), 'error': None}
    record = {
        'id': 'RADAR-CMA-CREF',
        'kind': 'RADAR',
        'cityId': None,
        'source': source_id,
        'sources': [source_id],
        'sourceNote': source_note,
        'synthetic': virtual,
        'slot': (derived.get('provenance') or {}).get('slot'),
        'slotAgeMinutes': (derived.get('provenance') or {}).get('slotAgeMinutes'),
        'bands': {name: {'components': row.get('components'),
                         'areaKm2': round((row.get('areaM2') or 0.0) / 1e6, 1)}
                  for name, row in (derived.get('bands') or {}).items()},
        'floorAglM': rules['floorAglM'],
        'ceilingAglM': rules['ceilingAglM'],
        'field': published_field,
        'ban': _published(core) or {'type': 'Polygon', 'coordinates': []},
        'caution': _published(caution) or {'type': 'Polygon', 'coordinates': []},
    }
    return {'available': True, 'regions': [record], 'watch': watch_record,
            'summary': summary, 'mode': weather_control.mode(), 'error': None}

def low_visibility_regions(minute=0):
    city_rows = cities()
    snapshot = weather_snapshot_entry(city_rows)
    if not snapshot.get('available'):
        return {'available': False, 'regions': [],
                'reason': 'WEATHER_UNAVAILABLE',
                'error': '气象快照不可用，本帧不发布能见度派生几何。',
                **fog_rule_block()}
    area = boundary()
    regions = []
    for cell, caution, ban in fog_tiers(snapshot, city_rows):
        def clip(geometry):
            if geometry is None or geometry.is_empty:
                return None
            clipped = geometry.intersection(area)
            parts = _polygon_parts(clipped)
            if not parts:
                return None
            polygonal = parts[0] if len(parts) == 1 else unary_union(parts)
            return None if polygonal.is_empty else mapping(polygonal)
        regions.append({**cell, 'ban': clip(ban), 'caution': clip(caution)})
    return {'available': True, 'regions': regions,
            'reason': None if regions else 'NO_LOW_VISIBILITY_READING',
            'detail': (None if regions else
                       '能见度已逐城读取并逐档判定：本帧没有站点低于偏低档阈值。'),
            **fog_rule_block()}

def _tally(counters, key):
    if counters is not None:
        counters[key] = counters.get(key, 0) + 1

@lru_cache(maxsize=16)
def _virtual_radar_derived(seed, slot):
    frame_result = weather_sim.frame(seed=seed, slot=slot)
    derived = radar_field.derive({**frame_result, 'mode': weather_control.MODE_VIRTUAL}, minute=0)
    derived['syntheticEcho'] = bool((frame_result.get('provenance') or {}).get('synthetic'))
    return derived

@lru_cache(maxsize=1)
def _virtual_radar_samples():
    return _virtual_radar_sweep()

def _virtual_radar_sweep(progress=None, seed=None, diagnostics=None):
    if seed is None:
        seed = weather_control.seed()
    steps = range(0, TIMELINE_MINUTES + 1, RADAR_SWEEP_STRIDE_MINUTES)
    total = len(steps)
    samples = []
    for done, offset in enumerate(steps, start=1):
        if progress is not None:
            progress(done / total)
        slot = SIMULATION_BASE_TIME + timedelta(minutes=offset)
        derived = _virtual_radar_derived(seed, slot)
        if not derived.get('available'):
            _tally(diagnostics, 'unavailable')
            continue
        if not derived.get('syntheticEcho'):
            _tally(diagnostics, 'notSynthetic')
            continue
        field, core, _caution, _watch = radar_field.shield(derived)
        if field.is_empty:
            _tally(diagnostics, 'empty')
            continue
        samples.append((offset, field, core))
    return tuple(samples)

def progress_stage(percent):
    stage = PROGRESS_STAGES[0][1]
    for threshold, label in PROGRESS_STAGES:
        if percent >= threshold:
            stage = label
    return stage

def _radar_window_union(radar_obstacle, start, end, probe=None, tier='field'):
    if not isinstance(radar_obstacle, tuple):
        return radar_obstacle
    column = 1 if tier == 'field' else 2
    span_lo, span_hi = _window_sample_span(start, end)
    key = (span_lo, span_hi, tier)
    cached = _RADAR_WINDOW_CACHE.get(key)
    if cached is None:
        window = [sample[column] for sample in radar_obstacle
                  if span_lo - RADAR_SWEEP_STRIDE_MINUTES <= sample[0] <= span_hi]
        cached = tuple((geom.bounds, geom) for geom in window if not geom.is_empty)
        _RADAR_WINDOW_CACHE[key] = cached
    if not cached:
        return GeometryCollection()
    if probe is None:
        if len(cached) == 1:
            return cached[0][1]
        return unary_union([geom for _bounds, geom in cached])
    p_minx, p_miny, p_maxx, p_maxy = probe.bounds
    hits = [geom for (b_minx, b_miny, b_maxx, b_maxy), geom in cached
            if (p_minx <= b_maxx and p_maxx >= b_minx
                and p_miny <= b_maxy and p_maxy >= b_miny)
            and probe.intersects(geom)]
    if not hits:
        return GeometryCollection()
    return hits[0] if len(hits) == 1 else unary_union(hits)

_RADAR_WINDOW_CACHE = {}
_RADAR_ERODED_CACHE = {}

def _window_sample_span(start, end):
    if not RADAR_SWEEP_STRIDE_MINUTES:
        return int(start) // 5 * 5, max(int(end) // 5 * 5, int(start) // 5 * 5)
    lo = int(start) // 5 * 5
    hi = -(-int(end) // RADAR_SWEEP_STRIDE_MINUTES) * RADAR_SWEEP_STRIDE_MINUTES
    return lo, max(hi, lo)

def _radar_penetration_limit(radar_obstacle, start, end, penetration_m):
    if not isinstance(radar_obstacle, tuple):
        return radar_obstacle
    span_lo, span_hi = _window_sample_span(start, end)
    key = (span_lo, span_hi, penetration_m)
    cached = _RADAR_ERODED_CACHE.get(key)
    if cached is None:
        cached = penetration_limit(
            _radar_window_union(radar_obstacle, span_lo, span_hi), penetration_m)
        if cached is None:
            cached = GeometryCollection()
        _RADAR_ERODED_CACHE[key] = cached
    return cached

ROUTE_BASIS = ('CLEAR', 'STATIC_AIRSPACE', 'POINT_WEATHER', 'LOW_VISIBILITY',
               'RADAR_CORE', 'RADAR_FIELD', 'BOUNDARY')
WEATHER_BASIS = ('POINT_WEATHER', 'RADAR_CORE', 'RADAR_FIELD', 'LOW_VISIBILITY')

def _radar_first_sample_minute(radar_obstacle, probe, start, end, tier):
    column = 1 if tier == 'field' else 2
    bucket_start = int(start) // 5 * 5
    bucket_end = max(int(end) // 5 * 5, bucket_start)
    p_minx, p_miny, p_maxx, p_maxy = probe.bounds
    for sample in radar_obstacle:
        if sample[0] > bucket_end or sample[0] < bucket_start - RADAR_SWEEP_STRIDE_MINUTES:
            continue
        geometry = sample[column]
        if geometry.is_empty:
            continue
        b_minx, b_miny, b_maxx, b_maxy = geometry.bounds
        if (p_minx > b_maxx or p_maxx < b_minx
                or p_miny > b_maxy or p_maxy < b_miny):
            continue
        if probe.intersects(geometry):
            return sample[0]
    return None

def _route_basis(lateral_line, static_obstacle, envelope, radar_obstacle, allowed,
                 start, end, fog_ban=None, fog_caution=None):
    coords = list(lateral_line.coords)
    direct = LineString([coords[0], coords[-1]])
    if not static_obstacle.is_empty and direct.intersects(static_obstacle):
        return 'STATIC_AIRSPACE', None
    if not envelope.is_empty and direct.intersects(envelope):
        return 'POINT_WEATHER', None
    if fog_ban is not None and not fog_ban.is_empty and direct.intersects(fog_ban):
        return 'LOW_VISIBILITY', None
    if fog_caution is not None and not fog_caution.is_empty and direct.intersects(fog_caution):
        return 'LOW_VISIBILITY', None
    if not isinstance(radar_obstacle, tuple):
        if (radar_obstacle is not None and not radar_obstacle.is_empty
                and direct.intersects(radar_obstacle)):
            return 'RADAR_CORE', None
    else:
        if not _radar_window_union(radar_obstacle, start, end, probe=direct,
                                   tier='core').is_empty:
            return 'RADAR_CORE', _radar_first_sample_minute(
                radar_obstacle, direct, start, end, 'core')
        if not _radar_window_union(radar_obstacle, start, end,
                                   probe=direct).is_empty:
            return 'RADAR_FIELD', _radar_first_sample_minute(
                radar_obstacle, direct, start, end, 'field')
    if not allowed.covers(direct):
        return 'BOUNDARY', None
    return 'CLEAR', None

CLEARANCE_VALIDITY_MINUTES = 15
CLEARANCE_LIMIT_TEXT = '东北三省低空协同运行边界'

def _clearance_record(flight, *, direction_route, clearance_status, weather_note,
                      validity_minutes=CLEARANCE_VALIDITY_MINUTES):
    release = flight.get('plannedReleaseAt')
    ctot = flight.get('departureMinute')
    window = None
    if ctot is not None:
        window = {
            'from': _instant(ctot),
            'until': _instant(ctot + validity_minutes),
            'validityMinutes': validity_minutes,
        }
    return {
        'callsign': flight.get('id'),
        'limit': CLEARANCE_LIMIT_TEXT,
        'route': direction_route,
        'assignedLevelAglM': flight.get('assignedLayerAglM'),
        'requestedDepartureAt': flight.get('requestedDepartureAt'),
        'releasedAt': release,
        'ctot': window,
        'weatherBasis': weather_note,
        'status': clearance_status,
    }

def _minutes_text(minutes, about=False):
    value = float(minutes)
    if value < 0.5:
        return '不足 1 分钟'
    return ('约 %d 分钟' if about else '%d 分钟') % round(value)

def _weather_basis_note(scenario, weather_mode, delay_minutes, detour_minutes):
    channel = '虚拟气象通道（程序生成回波，用于演示）' if weather_mode == 'virtual' else '实测气象通道（公开观测）'
    if scenario == 'clear':
        return f'{channel}；本场景声明无不利气象，按已声明高度层与时隙放行'
    if scenario == 'unknown':
        return f'{channel}；气象源不可用，本班次不予放行'
    parts = [channel]
    if detour_minutes and detour_minutes > 0.01:
        parts.append(f'按回波避让改航，航程增加{_minutes_text(detour_minutes, about=True)}')
    if delay_minutes:
        parts.append(f'原时隙被占或走廊未清，时隙重排 +{_minutes_text(delay_minutes)}')
    if len(parts) == 1:
        parts.append('原时隙走廊已清，按申请时刻放行')
    return '；'.join(parts)

def radar_status():
    return {
        **radar_field.summary(
            derived={'available': False, 'error': '未取帧：状态查询不触发网络请求'}),
        'mode': weather_control.mode(),
        'controller': weather_control.status(),
    }

@lru_cache(maxsize=4)
def static_airspace(policy=None):
    policy = policy or airport_footprint_policy()
    return {
        'rules': fixed_zones.rules(policy),
        'status': fixed_zones.status(policy),
        'audit': fixed_zones.audit(policy),
        'zones': fixed_zones.frame(policy, display_ceiling_agl_m=operations()['riskCeilingAglM']),
    }

def _keys(points):
    keys = set()
    for first, second in zip(points, points[1:]):
        for x in range(math.floor((min(first[0], second[0]) - 250) / 15000), math.floor((max(first[0], second[0]) + 250) / 15000) + 1):
            for y in range(math.floor((min(first[1], second[1]) - 250) / 15000), math.floor((max(first[1], second[1]) + 250) / 15000) + 1):
                for moment in range(math.floor(first[3] / 10), math.floor(second[3] / 10) + 1):
                    keys.add((x, y, moment))
    return keys

def _lateral(path, width, allowed):
    if len(path) < 2:
        return path
    points = [path[0]]
    for first, second in zip(path, path[1:]):
        length = math.dist(first, second)
        if length < 1:
            continue
        dx, dy = (second[0] - first[0]) / length, (second[1] - first[1]) / length
        for fraction in (.12, .88):
            points.append([first[0] + (second[0] - first[0]) * fraction + dy * width,
                           first[1] + (second[1] - first[1]) * fraction - dx * width])
    points.append(path[-1])
    return points if allowed.covers(LineString(points)) else path

def _crossings(path, route_id, mode, lines, tree, route_ids, route_modes):
    line, distances = LineString(path), []
    for index in tree.query(line, predicate='intersects'):
        if route_ids[index] == route_id or (mode == 'CAR' and route_modes[index] == 'CAR'):
            continue
        intersection = line.intersection(lines[index])
        points = [intersection] if intersection.geom_type == 'Point' else list(intersection.geoms) if intersection.geom_type == 'MultiPoint' else []
        for point in points:
            distance = line.project(point)
            if 300 < distance < line.length - 300:
                distances.append(distance)
    return sorted(set(distances))

def _allowed_for_route(route_item, catalog):
    allowed = boundary(route_item['province'])
    if route_item['mode'] == 'DELIVERY':
        city = next(city for city in catalog['cities'] if city['id'] == route_item['fromCity'])
        return allowed.intersection(Point(city['xy']).buffer(operations()['delivery']['serviceRadiusM']))
    return allowed

def _flight(seed_rng, route_item, direction, scheduled):
    from_city = route_item['fromCity'] if not direction else route_item['toCity']
    to_city = route_item['toCity'] if not direction else route_item['fromCity']
    from_pad = route_item['fromPad'] if not direction else route_item['toPad']
    to_pad = route_item['toPad'] if not direction else route_item['fromPad']
    return {
        'id': f"{route_item['id']}-{direction}-{scheduled}", 'routeId': route_item['id'], 'mode': route_item['mode'],
        'direction': direction, 'scheduledMinute': scheduled, 'requestedDepartureMinute': scheduled,
        'requestedDepartureAt': _instant(scheduled), 'plannedReleaseAt': None, 'actualReleaseAt': None,
        'plannedTakeoffAt': None, 'actualTakeoffAt': None, 'estimatedArrivalAt': None, 'actualArrivalAt': None,
        'name': route_item['name'], 'fromCity': from_city, 'toCity': to_city, 'fromPad': from_pad, 'toPad': to_pad,
        'status': 'CLOSED', 'reason': 'NO_GEOMETRIC_PATH', 'points': [], 'delayMinutes': 0, 'detourMinutes': 0,
        'groundWaitMinutes': 0, 'separationAction': 'NONE', 'conflictWith': [], 'planRevision': PLAN_REVISION,
        'assignedLayerAglM': None, 'layerStrategy': None, 'cruiseLayersUsedAglM': [], 'crossingZones': [],
        'payload': seed_rng.randint(1, 4) if route_item['mode'] == 'CAR' else seed_rng.randint(1, 3),
        'orderStatus': '待分配' if route_item['mode'] == 'DELIVERY' else None,
        'clearanceStatus': 'NOT_EVALUATED',
        'staticAirspace': {'zones': 0, 'prohibited': 0, 'approvalRequired': 0, 'clauses': [], 'crossings': []},
    }

def _plan_trajectory(seed=42, scenario='live', progress=lambda _: None, live_snapshot=None,
                     weather_mode=None):
    catalog, rng = network(), random.Random(seed)
    progress(PROGRESS_START_PERCENT)
    weather_mode = weather_mode or weather_control.mode()
    if scenario == 'live':
        weather_snapshot = live_snapshot or weather_snapshot_entry(catalog['cities'])
        weather = PublicWeather(weather_snapshot, catalog['cities'])
    elif scenario == 'clear':
        weather_snapshot = None
        weather = LiveWeatherEnvelope(None, catalog['cities'])
    else:
        weather_snapshot = None
        weather = LiveWeatherEnvelope(None, catalog['cities'])
    geometries = [LineString(item['path']) for item in catalog['routes'] if item['path']]
    route_ids = [item['id'] for item in catalog['routes'] if item['path']]
    route_modes = [item['mode'] for item in catalog['routes'] if item['path']]
    tree = STRtree(geometries)
    static_policy = airport_footprint_policy()
    static_obstacle = fixed_zones.envelope(static_policy)
    progress(PROGRESS_SNAPSHOT_PERCENT)
    def sweep_progress(fraction):
        span = PROGRESS_SWEEP_PERCENT - PROGRESS_SNAPSHOT_PERCENT
        progress(PROGRESS_SNAPSHOT_PERCENT + round(fraction * span))

    radar_obstacle, radar_avoidance_info = _radar_avoidance(scenario, weather_mode,
                                                            sweep_progress)
    fog_ban, fog_caution_discs, fog_avoidance_info = _low_visibility_avoidance(
        scenario, weather_snapshot, catalog['cities'])
    fog_caution_layer = (unary_union([disc['geometry'] for disc in fog_caution_discs])
                         if fog_caution_discs else GeometryCollection())
    _RADAR_WINDOW_CACHE.clear()
    _RADAR_ERODED_CACHE.clear()
    pending = []
    for item in catalog['routes']:
        interval = 60 if item['mode'] == 'CAR' else 30
        for departure in range(0, TIMELINE_MINUTES, interval):
            for direction in (0, 1):
                wave_offset = (int(item['id'].rsplit('-', 1)[-1]) - 1) * 3 if item['mode'] == 'DELIVERY' else 0
                pending.append((departure + direction * 8 + wave_offset + rng.randint(0, 2), item['id'], direction, item))
    pending.sort(key=lambda item: item[:3])
    accepted, flights, buckets, path_cache = [], [], {}, {}
    accepted_boxes = []
    calendar = ResourceCalendar({pad['id']: pad.get('capacity', 1) for pad in catalog['pads']})
    zone_settings = operations()['crossingZone']
    wait_step = max(1, int(profiles()['separation']['groundWaitStepMinutes']))
    max_extra = profiles()['separation']['maxExtraMinutes']
    max_minutes = operations()['maxFlightMinutes']
    layer_usage = {}
    progress(PROGRESS_SWEEP_PERCENT)
    loop_span = 100 - PROGRESS_SWEEP_PERCENT
    for index, (scheduled, route_id, direction, route_item) in enumerate(pending):
        flight = _flight(rng, route_item, direction, scheduled)
        flights.append(flight)
        progress(PROGRESS_SWEEP_PERCENT + round((index + 1) / len(pending) * loop_span))
        if scenario == 'unknown' or (scenario == 'live' and not weather_snapshot.get('available')
                                     and radar_avoidance_info.get('included') is not True):
            flight['reason'] = 'WEATHER_UNAVAILABLE'
            continue
        if not route_item['path']:
            continue
        mode = route_item['mode']
        profile = profiles()[mode]
        allowed = _allowed_for_route(route_item, catalog)
        if static_obstacle.covers(Point(route_item['fromXY'])) or static_obstacle.covers(Point(route_item['toXY'])):
            flight['reason'] = 'STATIC_AIRSPACE_BLOCKED'
            continue
        lateral = list(reversed(route_item['path'])) if direction else route_item['path']
        lateral = _lateral(lateral, 220 if mode == 'CAR' else 90, allowed)
        base = rounded_path(lateral, profile['minTurnRadiusM'])
        if not base or not allowed.covers(LineString(base)):
            flight['reason'] = 'TURN_RADIUS_OR_BOUNDARY_LIMIT'
            continue
        layer_options = airspace.preferences(profile, direction, route_item['corridorIndex'])
        nominal = trajectory(base, scheduled, profile['speedKmh'], layer_options[0],
                             max_altitude=profile['maxCruiseAglM'], climb_mps=profile['maxClimbMps'])
        if not nominal:
            flight['reason'] = 'ALTITUDE_PROFILE_LIMIT'
            continue
        base_duration = nominal[-1][3] - scheduled
        base_line = _line(base)
        base_km = base_line.length / 1000
        path, detour = None, False
        lateral_line = LineString(lateral)
        fog_caution = fog_caution_layer
        exempted, exempt_cities = _exempt_fog_caution(
            fog_caution_discs, route_item['fromXY'], route_item['toXY'])
        if exempted is not None:
            fog_caution = exempted
        if exempt_cities:
            fog_avoidance_info['padExemptFlights'] += 1
            fog_avoidance_info['padExemptCities'] = sorted(
                set(fog_avoidance_info['padExemptCities']) | set(exempt_cities))
        penetration_m = profiles()['separation']['horizontalM']
        wait_offsets = sorted({int(round(fraction * max_extra)) for fraction in RADAR_WAIT_PROBES})
        for offset in wait_offsets:
            begin = scheduled + offset
            pass
            span = (begin, begin + base_duration + DETOUR_WINDOW_PADDING_MINUTES)
            envelope = weather.envelope(*span)
            core_window = _radar_window_union(radar_obstacle, *span, probe=lateral_line, tier='core')
            needs_avoidance = (lateral_line.intersects(static_obstacle)
                               or lateral_line.intersects(envelope)
                               or not core_window.is_empty
                               or lateral_line.intersects(fog_ban)
                               or lateral_line.intersects(fog_caution))
            if not needs_avoidance:
                needs_avoidance = not _radar_window_union(
                    radar_obstacle, *span, probe=lateral_line).is_empty
            if not needs_avoidance:
                candidate = lateral
            else:
                hard = static_obstacle
                for extra in (envelope, fog_ban, core_window):
                    if not extra.is_empty:
                        hard = hard.union(extra)
                if isinstance(radar_obstacle, tuple):
                    soft_set = _radar_window_union(radar_obstacle, *span, tier='field')
                    core_set = _radar_window_union(radar_obstacle, *span, tier='core')
                    if not core_set.is_empty:
                        hard = hard.union(core_set)
                else:
                    soft_set = GeometryCollection()
                if not fog_caution.is_empty:
                    soft_set = (fog_caution if soft_set.is_empty
                                else soft_set.union(fog_caution))
                cache_key = (route_id, direction, int(begin // 5))
                if cache_key not in path_cache:
                    path_cache[cache_key] = route(lateral[0], lateral[-1], allowed, hard,
                                                  soft_obstacles=soft_set, penetration_m=penetration_m)
                candidate = path_cache[cache_key]
            if candidate:
                path = candidate
                detour = needs_avoidance or offset > 0
                break
        if not path:
            flight['reason'] = ('STATIC_AIRSPACE_BLOCKED'
                                if lateral_line.intersects(static_obstacle) else 'WEATHER_BLOCKED')
            continue
        path = rounded_path(path, profile['minTurnRadiusM'])
        if not path or not allowed.covers(LineString(path)):
            flight['reason'] = 'TURN_RADIUS_OR_BOUNDARY_LIMIT'
            continue
        crossings = _crossings(path, route_id, mode, geometries, tree, route_ids, route_modes)
        def weather_clear_at(line, begin, end):
            if line.intersects(weather.envelope(begin, end)):
                return False
            if not fog_ban.is_empty and line.intersects(fog_ban):
                return False
            if not fog_caution.is_empty and line.intersects(
                    penetration_limit(fog_caution, penetration_m)):
                return False
            if not isinstance(radar_obstacle, tuple):
                return not line.intersects(radar_obstacle)
            window = (begin, end)
            if not _radar_window_union(radar_obstacle, *window, probe=line, tier='core').is_empty:
                return False
            if _radar_window_union(radar_obstacle, *window, probe=line).is_empty:
                return True
            return not line.intersects(
                _radar_penetration_limit(radar_obstacle, *window, penetration_m))

        chosen, encountered = None, set()
        first_rejection = None
        best = None
        stop_search = False
        minimal_selection = DELAY_SELECTION_STRATEGY == 'minimal'
        for delay in range(0, max_extra + 1, wait_step):
            if best is not None and delay >= best[0]:
                break
            for layer_index, layer in enumerate(layer_options):
                points = trajectory(path, scheduled + delay, profile['speedKmh'], layer, crossings=crossings,
                                    max_altitude=profile['maxCruiseAglM'], climb_mps=profile['maxClimbMps'])
                if not points or not within_profile(points, profile):
                    first_rejection = first_rejection or 'ALTITUDE_PROFILE_LIMIT'
                    continue
                if not weather_clear_at(_line(points), points[0][3], points[-1][3]):
                    first_rejection = first_rejection or 'WEATHER_BLOCKED'
                    continue
                pad_entries = ((flight['fromPad'], points[0][3]), (flight['toPad'], points[-1][3]))
                if not calendar.window_available(pad_entries, profile['padSeparationMinutes']):
                    first_rejection = first_rejection or 'SEPARATION_RESOURCE_OR_TIME_LIMIT'
                    continue
                zones = crossing_zones(path, crossings, points, zone_settings['cellM'])
                for zone in zones:
                    calendar.register(zone['zoneId'], zone_settings['capacity'])
                zone_entries = tuple((zone['zoneId'], zone['minute']) for zone in zones if zone['minute'] is not None)
                if not calendar.window_available(zone_entries, zone_settings['windowMinutes']):
                    first_rejection = first_rejection or 'SEPARATION_RESOURCE_OR_TIME_LIMIT'
                    continue
                keys = _keys(points)
                possible = set().union(*(buckets.get(key, set()) for key in keys))
                candidate_box = bbox_2d(points)
                collisions = [accepted[item] for item in possible
                              if not bbox_apart(candidate_box, accepted_boxes[item])
                              and conflict(points, accepted[item]['points'],
                                           box_a=candidate_box, box_b=accepted_boxes[item])]
                if collisions:
                    encountered.update(item['id'] for item in collisions)
                    first_rejection = first_rejection or 'SEPARATION_RESOURCE_OR_TIME_LIMIT'
                    continue
                detour_extra = max(0.0, (_line(points).length - base_line.length) / 1000
                                   / profile['speedKmh'] * 60)
                total_extra = delay + detour_extra
                candidate = (total_extra, delay, layer_index, points, keys, layer, zones,
                             pad_entries, zone_entries)
                if best is None or candidate < best:
                    best = candidate
                if not minimal_selection:
                    stop_search = True
                    break
                if total_extra <= 1e-9:
                    stop_search = True
                    break
            if stop_search:
                break
        if best is not None:
            chosen = (best[3], best[1], best[4], best[5], best[6], best[7], best[8])
        if not chosen:
            flight['reason'] = first_rejection or 'SEPARATION_RESOURCE_OR_TIME_LIMIT'
            flight['conflictWith'] = sorted(encountered)[:8]
            continue
        points, delay, keys, layer, zones, pad_entries, zone_entries = chosen
        final_line = _line(points)
        if (not allowed.covers(final_line)
                or final_line.intersects(static_obstacle)
                or not weather_clear_at(final_line, points[0][3], points[-1][3])):
            flight['reason'] = 'FINAL_WEATHER_OR_BOUNDARY_CHECK_FAILED'
            continue
        static_summary, static_records = fixed_zones.crossings(points, static_policy)
        clearance = evaluate_obstacles(points, route_id)
        strategy = airspace.PRIMARY if layer == layer_options[0] else airspace.ALTERNATE
        layer_usage[f'{mode}:{layer:g}'] = layer_usage.get(f'{mode}:{layer:g}', 0) + 1
        if delay and strategy == airspace.ALTERNATE:
            action = 'GROUND_HOLD_AND_LAYER'
        elif delay:
            action = 'SLOT_AND_LAYER'
        elif strategy == airspace.ALTERNATE:
            action = 'ALTERNATE_LAYER'
        else:
            action = 'LAYERED_CORRIDOR'
        route_basis, route_basis_from = _route_basis(
            lateral_line, static_obstacle,
            weather.envelope(points[0][3], points[-1][3]),
            radar_obstacle, allowed, points[0][3], points[-1][3],
            fog_ban=fog_ban, fog_caution=fog_caution)
        weather_caused = route_basis in WEATHER_BASIS
        flight.update(
            status='SCHEDULED',
            reason='WEATHER_DETOUR' if weather_caused else 'CLEAR',
            points=points,
            departureMinute=points[0][3], arrivalMinute=points[-1][3], plannedReleaseAt=_instant(points[0][3]),
            plannedTakeoffAt=_instant(points[0][3]), estimatedArrivalAt=_instant(points[-1][3]),
            delayMinutes=delay, groundWaitMinutes=delay,
            detourMinutes=round(max(0.0,
                                    (final_line.length / 1000 - base_km) / profile['speedKmh'] * 60), 2),
            distanceKm=round(final_line.length / 1000, 2),
            separationAction=action, layerStrategy=strategy, assignedLayerAglM=layer,
            cruiseLayersUsedAglM=airspace.validate(points, profile)['cruiseLayersUsedAglM'],
            crossingDistancesM=[round(distance, 2) for distance in crossings], crossingZones=zones,
            conflictWith=sorted(encountered)[:8],
            staticAirspace={**static_summary, 'crossings': static_records},
            maxAltitudeM=max(point[2] for point in points), clearanceStatus=clearance['status'], clearance=clearance,
            routeBasis=route_basis, routeBasisFromMinute=route_basis_from,
            orderStatus='待起飞' if mode == 'DELIVERY' else None,
        )
        flight['atcClearance'] = _clearance_record(
            flight,
            direction_route=f"{flight['fromPad']} — {flight['toPad']}",
            clearance_status=clearance['status'],
            weather_note=_weather_basis_note(scenario, weather_mode, delay, flight['detourMinutes']),
        )
        accepted_index = len(accepted)
        accepted.append(flight)
        accepted_boxes.append(bbox_2d(points))
        calendar.reserve_all(tuple(pad_entries) + zone_entries)
        for key in keys:
            buckets.setdefault(key, set()).add(accepted_index)

    delivery_summary = delivery.attach(flights, operations()['delivery'], TIMELINE_MINUTES)
    _arrivals = [row.get('arrivalMinute') for row in flights
                 if isinstance(row.get('arrivalMinute'), (int, float))]
    timeline_minutes = max(TIMELINE_MINUTES,
                           int(math.ceil(max(_arrivals))) + 10) if _arrivals else TIMELINE_MINUTES
    return {
        'source': 'SIMULATION', 'version': VERSION, 'fingerprint': FINGERPRINT,
        'planRevision': str(next(_PLAN_REV_SEQ)), 'planVersion': PLAN_REVISION,
        'weatherMode': weather_mode,
        'baseTime': SIMULATION_BASE_TIME.isoformat().replace('+00:00', 'Z'), 'timezone': 'Asia/Shanghai',
        'seed': seed, 'scenario': scenario, 'status': 'READY', 'progress': 100, 'flights': flights,
        'timelineMinutes': timeline_minutes,
        'weatherSnapshot': weather_snapshot if scenario == 'live' else {
            'provider': 'NONE', 'dataType': 'NO_WEATHER_CLAIMED',
            'weatherSnapshotId': None,
            'qualityFlags': ['NO_WEATHER_SOURCE_FOR_THIS_SCENARIO'],
        },
        'radarAvoidance': radar_avoidance_info,
        'lowVisibilityAvoidance': fog_avoidance_info,
        'stats': {
            'cities': len(catalog['cities']), 'routes': len(catalog['routes']),
            'carRoutes': sum(item['mode'] == 'CAR' for item in catalog['routes']),
            'deliveryRoutes': sum(item['mode'] == 'DELIVERY' for item in catalog['routes']),
            'interprovincialRoutes': sum(item['interprovincial'] for item in catalog['routes']),
            'flights': len(flights), 'accepted': len(accepted), 'closed': len(flights) - len(accepted),
            'statusCounts': {'scheduled': sum(1 for f in flights if f.get('status') == 'SCHEDULED'),
                             'closed': len(flights) - len(accepted)},
            'detours': sum(1 for item in accepted if (item.get('detourMinutes') or 0) > 0.01),
            'closedByReason': _reason_tally(flights),
            'closedByClosureReason': _reason_tally(flights, closed_only=True),
            'closedByWeather': sum(item['reason'] in WEATHER_CLOSURE_REASONS
                                   for item in flights if item['status'] != 'SCHEDULED'),
            'resolved': sum(bool(item['conflictWith']) for item in accepted),
            'orders': sum(item['mode'] == 'DELIVERY' for item in flights),
            'groundHolds': sum(item['groundWaitMinutes'] > 0 for item in accepted),
            'alternateLayers': sum(item['layerStrategy'] == airspace.ALTERNATE for item in accepted),
            'noAltitudeStacking': True,
            'staticAirspace': {
                'policy': static_policy,
                'zoneCount': fixed_zones.status(static_policy)['withGeometry'],
                'closedByStaticAirspace': sum(item['reason'] == 'STATIC_AIRSPACE_BLOCKED' for item in flights),
                'flightsRequiringApproval': sum(item['staticAirspace']['approvalRequired'] > 0 for item in accepted),
                'prohibitedConflicts': sum(item['staticAirspace']['prohibited'] for item in accepted),
                'crossingRecords': sum(item['staticAirspace']['zones'] for item in accepted),
                'clauses': sorted({clause for item in accepted for clause in item['staticAirspace']['clauses']}),
            },
        },
        'layerUsage': dict(sorted(layer_usage.items())),
        'hubs': hub_snapshot(calendar, catalog),
        'deliveryPlan': delivery_summary,
    }

def simulate(seed=42, scenario='live', progress=lambda _: None, live_snapshot=None,
             weather_mode=None):
    with _SIMULATE_LOCK:
        return _plan_trajectory(seed, scenario, progress, live_snapshot, weather_mode)

def hub_snapshot(calendar, catalog):
    utilization = calendar.utilization()
    pads = {resource: detail for resource, detail in utilization.items() if not resource.startswith('XZ:')}
    zones = {resource: detail for resource, detail in utilization.items() if resource.startswith('XZ:')}
    return {
        'pads': pads,
        'busiestPads': [{'resource': key, **value} for key, value in sorted(pads.items(), key=lambda item: (-item[1]['reservations'], item[0]))[:12]],
        'crossingZones': {
            'count': len(zones),
            'capacityPerZone': operations()['crossingZone']['capacity'],
            'windowMinutes': operations()['crossingZone']['windowMinutes'],
            'reservations': sum(value['reservations'] for value in zones.values()),
            'busiest': [{'resource': key, **value} for key, value in sorted(zones.items(), key=lambda item: (-item[1]['reservations'], item[0]))[:8]],
        },
        'padCount': len(catalog['pads']),
        'note': '起降资源为模拟容量与时隙占用，不是真实机场容量。',
    }

def identity(seed, scenario, weather_snapshot_id=None, weather_mode=None, workspace=None,
             radar=None):
    if weather_mode is None:
        weather_mode = weather_control.mode()
    suffix = f':{workspace}' if workspace else ''
    radar_suffix = f':{radar}' if radar else ''
    return hashlib.sha256(f'{VERSION}:{FINGERPRINT}:{PLAN_REVISION}:{OPERATIONS_FINGERPRINT}:'
                          f'{seed}:{scenario}:'
                          f'{weather_snapshot_id or ""}:{weather_mode}{suffix}{radar_suffix}'
                          .encode()).hexdigest()[:24]

SNAPSHOT_META_FIELDS = ('provider', 'dataType', 'weatherSnapshotId', 'retrievedAt', 'validAt', 'validUntil',
                        'modelRunAt', 'resolution', 'coverage', 'qualityFlags', 'cache', 'errorCode')

PLAN_SHARE = os.environ.get('ALC_PLAN_SHARE', '1') not in ('0', 'false', 'False', '')
_SHARE_OF: Dict[str, str] = {}

def _config_digest() -> str:
    try:
        payload = json.dumps([profiles(), operations()], sort_keys=True, ensure_ascii=False)
    except Exception:  # noqa: BLE001 - 配置读不出来就不共享，退回逐份建场
        return 'no-config'
    return hashlib.sha1(payload.encode('utf-8')).hexdigest()[:12]

def _share_index_path() -> Path:
    return STORE / '_share.json'

def _share_lookup(share: str) -> Optional[str]:
    """索引里该 share key 对应哪个计划文件（不校验内容，调用方自己校验）。"""
    try:
        data = json.loads(_share_index_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    row = data.get(share)
    if not isinstance(row, dict):
        return None
    key = row.get('key')
    return key if isinstance(key, str) and (STORE / f'{key}.json').exists() else None

def _share_record(share: str, key: str) -> None:
    try:
        path = _share_index_path()
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except ValueError:
                data = {}
        data[share] = {'key': key, 'at': round(time.time(), 3)}
        if len(data) > 24:
            for old in sorted(data, key=lambda k: data[k].get('at', 0))[:len(data) - 24]:
                data.pop(old, None)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(data), encoding='utf-8')
        temp.replace(path)
    except OSError:
        pass

def snapshot_meta(snapshot):
    if not snapshot:
        return None
    return {key: snapshot.get(key) for key in SNAPSHOT_META_FIELDS}

def coverage(value):
    cities_total = value['stats']['cities']
    cities_valid = sum(1 for city in cities() if city['coordinateValid'])
    return {
        'baseMap': 'OpenFreeMap / OpenStreetMap 在线矢量底图，需要联网。',
        'administrativeBoundary': BOUNDARY_VERSION,
        'cityDirectory': f'{cities_valid}/{cities_total} 个城区代表中心通过本省边界校验。',
        'cityCoordinatesOutsideProvince': [city['id'] for city in cities() if not city['coordinateValid']],
        'routeInteriorWeather': '仅城际端点和采样城市有天气值，航路内部未全程采样。',
        'terrain': {'status': 'UNAVAILABLE', 'note': '本地没有覆盖全部航迹的 DEM。'},
        'buildings': {'status': 'UNAVAILABLE', 'note': '本地没有覆盖全部航迹的建筑高度目录。'},
        'obstacleSourceVersion': OBSTACLE_SOURCE_VERSION,
        'traffic': '模拟生成；配送节点与订单为合成数据。',
        'granularity': '天气网格与供应商分辨率一致，不支持街区级雷暴定位。',
    }

def _ready(seed, scenario):
    value = session(seed, scenario)
    if value.get('status') != 'READY':
        raise ValueError('运行计划尚未就绪')
    return value

def plan_meta(seed, scenario):
    value = _ready(seed, scenario)
    return {
        'status': 'READY', 'sessionId': value['sessionId'], 'version': value['version'],
        'planRevision': value['planRevision'],
        'planVersion': value.get('planVersion') or PLAN_REVISION,
        'fingerprint': value['fingerprint'],
        'baseTime': value['baseTime'], 'timezone': value['timezone'], 'seed': value['seed'],
        'scenario': value['scenario'], 'stats': value['stats'], 'layerUsage': value['layerUsage'],
        'weatherSnapshot': snapshot_meta(value.get('weatherSnapshot')), 'coverage': coverage(value),
        'riskRules': _risk_rules(),
    }

def hubs(seed, scenario):
    value = _ready(seed, scenario)
    return {**value['hubs'], 'sessionId': value['sessionId'], 'planRevision': value['planRevision']}

def delivery_plan(seed, scenario):
    value = _ready(seed, scenario)
    flights = value['flights']
    orders = [f for f in flights if f['mode'] == 'DELIVERY']
    vehicles = {}
    for flight in orders:
        key = flight.get('vehicleId')
        if not key:
            continue
        arrival = flight.get('arrivalMinute')
        status = flight.get('vehicleStatus') or ('停用' if flight['status'] == 'CLOSED' else '装载')
        current = vehicles.get(key)
        if current is None:
            vehicles[key] = {
                'vehicleId': key, 'cityId': flight['fromCity'], 'homePad': flight['fromPad'],
                'assignedFlights': 1, 'lastArrivalMinute': arrival,
                'energyPercentRemainingAtHandover': flight.get('energyPercentRemainingAtHandover'),
                'status': status,
            }
            continue
        current['assignedFlights'] += 1
        if arrival is not None and (current['lastArrivalMinute'] is None or arrival > current['lastArrivalMinute']):
            current['lastArrivalMinute'] = arrival
            current['energyPercentRemainingAtHandover'] = flight.get('energyPercentRemainingAtHandover')
            current['status'] = status
    return {
        'sessionId': value['sessionId'], 'planRevision': value['planRevision'],
        'summary': value['deliveryPlan'],
        'orders': [{key: flight.get(key) for key in
                    ('id', 'orderId', 'orderStatus', 'orderOutcome', 'orderOutcomeReason', 'fromCity', 'fromPad',
                     'toPad', 'vehicleId', 'scheduledMinute', 'departureMinute', 'arrivalMinute', 'delayMinutes',
                     'distanceKm', 'payload', 'energyPercentRemainingAtHandover', 'energyReservePercent')}
                   for flight in orders],
        'vehicles': [vehicles[key] for key in sorted(vehicles)],
    }

def _cached_fingerprint(path):
    try:
        with open(path, 'rb') as handle:
            head = handle.read(8192).decode('utf-8', 'replace')
    except OSError:
        return None
    match = re.search(r'"fingerprint"\s*:\s*"([^"]*)"', head)
    return match.group(1) if match else None

def _prune_stale_store():
    if STORE.exists():
        for path in STORE.glob('*.tmp'):
            try:
                path.unlink()
            except OSError:
                pass
    if not STORE.exists():
        return
    kept = dropped = 0
    live: list[Path] = []
    for path in STORE.glob('*.json'):
        if _cached_fingerprint(path) == FINGERPRINT:
            kept += 1
            live.append(path)
            continue
        try:
            path.unlink()
            dropped += 1
        except OSError:
            pass

    excess = 0
    if len(live) > KEEP_PER_GENERATION:
        now = time.time()
        try:
            ranked = sorted(live, key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            ranked = live
        for path in ranked[KEEP_PER_GENERATION:]:
            try:
                if getattr(path.stat(), 'st_mtime', 0) > now - RECENT_PROTECT_SECONDS:
                    continue
                path.unlink()
                excess += 1
                kept -= 1
            except OSError:
                pass

    if dropped or excess:
        logging.getLogger(__name__).info(
            'Traffic store pruned: dropped %d stale generation + %d over-capacity '
            'cache file(s), kept %d for %s',
            dropped, excess, kept, FINGERPRINT)

def _build_entry(key, seed, scenario, live_snapshot=None, weather_mode=None, workspace=None,
                 retain=True):
    with workspace_ctx.bind(workspace):
        return _build(key, seed, scenario, live_snapshot, weather_mode, retain)

class _PrewarmAbandoned(BaseException):
    pass

def _user_build_waiting(me):
    """是否有**用户发起**的构建在排队或运行（不含自己，也不含其它预建）。"""
    with LOCK:
        return any(entry.get('status') == 'BUILDING' and not entry.get('prewarm')
                   for other, entry in JOBS.items() if other != me)

def _release_free_memory(label: str = '') -> None:
    import gc
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL('libc.so.6').malloc_trim(0)
    except Exception:  # noqa: BLE001  —— 非 Linux / 非 glibc，跳过
        pass

def _build(key, seed, scenario, live_snapshot=None, weather_mode=None, retain=True):
    try:
        def progress(value):
            if not retain and _user_build_waiting(key):
                raise _PrewarmAbandoned
            with LOCK:
                JOBS[key]['progress'] = value
                JOBS[key]['stage'] = progress_stage(value)
        result = simulate(seed, scenario, progress, live_snapshot, weather_mode)
        result['sessionId'] = key
        _share = _SHARE_OF.pop(key, None)
        if _share:
            _share_record(_share, key)
        STORE.mkdir(parents=True, exist_ok=True)
        temporary = STORE / f'{key}.tmp'
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        temporary.replace(STORE / f'{key}.json')
        with LOCK:
            if retain:
                JOBS[key] = result
            else:
                JOBS.pop(key, None)
        _prune_stale_store()
        if retain:
            _prewarm_sibling(seed, scenario, live_snapshot, weather_mode)
    except _PrewarmAbandoned:
        with LOCK:
            JOBS.pop(key, None)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Traffic simulation failed')
        with LOCK:
            if retain:
                JOBS[key] = {'status': 'ERROR', 'sessionId': key, 'message': '运行计划计算失败，请查看本地 Python 日志'}
            else:
                JOBS.pop(key, None)
    finally:
        _release_free_memory()

def _prewarm_sibling(seed, scenario, live_snapshot, weather_mode):
    other = (weather_control.MODE_VIRTUAL if weather_mode == weather_control.MODE_MEASURED
             else weather_control.MODE_MEASURED)
    snapshot_id = live_snapshot.get('weatherSnapshotId') if live_snapshot else None
    workspace = workspace_ctx.current()
    sibling = identity(seed, scenario, snapshot_id, other, workspace,
                       radar=weather_control.frame_identity(other, workspace))
    with LOCK:
        if sibling in JOBS:
            return
        if any(value.get('status') == 'BUILDING' for value in JOBS.values()):
            return
        JOBS[sibling] = {'status': 'BUILDING', 'progress': 0, 'stage': progress_stage(0),
                         'sessionId': sibling, 'prewarm': True, 'startedAt': time.time()}
    POOL.submit(_build_entry, sibling, seed, scenario, live_snapshot, other, workspace, False)

def session(seed, scenario, workspace=None):
    ws = workspace if workspace is not None else workspace_ctx.current()
    live_snapshot = weather_snapshot_entry(cities()) if scenario == 'live' else None
    snapshot_id = live_snapshot.get('weatherSnapshotId') if live_snapshot else None
    weather_mode = weather_control.mode(ws)
    radar_id = weather_control.frame_identity(weather_mode, ws)
    key = identity(seed, scenario, snapshot_id, weather_mode, ws, radar=radar_id)
    share = '%s:%s' % (identity(seed, scenario, snapshot_id, weather_mode, None, radar=radar_id),
                       _config_digest())
    with LOCK:
        if key in JOBS:
            return JOBS[key]
        if sum(value['status'] == 'BUILDING' and not value.get('prewarm')
               for value in JOBS.values()) >= 2:
            return {'status': 'BUSY', 'message': '已有模拟计划正在计算，请稍后重试'}
        if len(JOBS) >= JOBS_LIMIT:
            old = next((old_key for old_key, value in JOBS.items() if value['status'] != 'BUILDING'), None)
            if old:
                del JOBS[old]
        saved = STORE / f'{key}.json'
        if saved.exists():
            try:
                result = json.loads(saved.read_text(encoding='utf-8'))
                if (result.get('fingerprint') == FINGERPRINT
                        and result.get('planVersion', result.get('planRevision')) == PLAN_REVISION
                        and result.get('weatherMode', weather_mode) == weather_mode):
                    JOBS[key] = result
                    if PLAN_SHARE:
                        _share_record(share, key)
                    return result
            except (ValueError, OSError):
                pass
        if PLAN_SHARE and share != key:
            donor = _share_lookup(share)
            if donor and donor != key:
                try:
                    result = json.loads((STORE / f'{donor}.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    result = None
                if (isinstance(result, dict)
                        and result.get('fingerprint') == FINGERPRINT
                        and result.get('planVersion', result.get('planRevision')) == PLAN_REVISION
                        and result.get('weatherMode', weather_mode) == weather_mode
                        and result.get('scenario') == scenario
                        and result.get('seed') == seed):
                    result['sessionId'] = key
                    result['sharedFrom'] = donor
                    JOBS[key] = result
                    _share_record(share, donor)
                    return result
        JOBS[key] = {'status': 'BUILDING', 'progress': 0, 'stage': progress_stage(0),
                     'sessionId': key, 'startedAt': time.time()}
        _SHARE_OF[key] = share
        POOL.submit(_build_entry, key, seed, scenario, live_snapshot, weather_mode, ws)
        return JOBS[key]

def forget_other_channels(mode, workspace=None):
    ws = workspace if workspace is not None else workspace_ctx.current()
    dropped = 0
    with LOCK:
        for key, entry in list(JOBS.items()):
            if entry.get('status') == 'BUILDING':
                continue
            if entry.get('weatherMode') == mode:
                continue
            if entry.get('workspace') not in (None, ws):
                continue
            del JOBS[key]
            dropped += 1
    return dropped

def _case_weather_frame(case_id, minute, city_id=None):
    from traffic import cases as traffic_cases
    try:
        from weather.metar_history import STATION_INFO as _STATION_INFO
    except Exception:  # noqa: BLE001
        _STATION_INFO = {}

    doc = traffic_cases.load(case_id) or {}
    frames = doc.get('frames') or []
    if not frames:
        return {
            'available': False, 'case': case_id,
            'lowVisibility': {'included': False, 'reason': 'CASE_NOT_FOUND',
                              'detail': '案例帧不可用，本帧不产出任何气象几何。'},
            'radar': {'available': False, 'reason': 'CASE_NOT_FOUND'},
            'stationVisibility': [],
        }
    index = 0
    if minute is not None:
        index = max(0, min(len(frames) - 1, int(round(float(minute) / 60.0))))
    frame = frames[index]
    stations = []
    for code, value in frame.items():
        if code == 't' or not isinstance(value, dict):
            continue
        vis = value.get('visM')
        if vis is None:
            continue
        limits = {'ban': 1000.0, 'warn': 5000.0}
        level = 'BAN' if vis <= limits['ban'] else ('CAUTION' if vis <= limits['warn'] else 'CLEAR')
        info = _STATION_INFO.get(code) or {}
        stations.append({
            'station': code,
            'visM': vis, 'visLevel': level,
            'gustMs': value.get('gustMs'),
            'cloudBaseM': value.get('cloudBaseM'),
            'lat': info.get('lat'), 'lon': info.get('lon'),
            'observedAt': frame.get('t'),
        })
    return {
        'available': True,
        'case': case_id,
        'validAt': frame.get('t'),
        'weatherMode': 'measured',
        'frameIndex': index,
        'frameCount': len(frames),
        'lowVisibility': {
            'included': False,
            'reason': 'CASE_OBSERVATION_ONLY',
            'detail': ('本案例只有 %d 个机场站的实测能见度，没有城市格点场，'
                       '因此不产出雾区面 —— 图上按站点画的是**影响范围示意**，'
                       '不是实测雾区边界。' % len(stations)),
            'stations': len(stations),
            'cities': 0,
        },
        'radar': {
            'available': False,
            'reason': 'CASE_NO_RADAR_TILES',
            'detail': '案例不含雷达瓦片，本帧不加入回波避让几何（不拿实时回波冒充历史）。',
        },
        'wind': {'available': bool(stations),
                 'note': '示例：风向风速取自同帧机场站实测。'},
        'stationVisibility': stations,
        'qualityFlags': ['HISTORICAL_REPLAY', 'STATION_OBSERVATION_ONLY_NO_GRID'],
    }

def weather_frame(seed, scenario, minute, city_id=None, case_id=None):
    if case_id:
        return _case_weather_frame(case_id, minute, city_id)

    city = next((item for item in cities() if item['id'] == city_id), None)
    if city_id and not city:
        raise ValueError('Unknown city')
    rules = _risk_rules()
    weather_mode = weather_control.mode()
    if scenario != 'live':
        unavailable = scenario == 'unknown'
        return {
            'available': not unavailable, 'provider': 'NONE',
            'dataType': 'NO_WEATHER_CLAIMED', 'seed': seed, 'scenario': scenario,
            'minute': minute, 'cityId': city_id, 'validAt': _instant(minute),
            'source': 'NONE',             'cells': [], 'winds': [], 'riskRules': rules,
            'extremeThresholds': extreme_thresholds(),
            'radar': radar_regions(minute), 'weatherMode': weather_mode,
            'lowVisibility': {'available': False, 'regions': [],
                              'reason': 'SCENARIO_DOES_NOT_DECLARE_WEATHER',
                              'error': None, **fog_rule_block()},
            'qualityFlags': ['WEATHER_SOURCE_UNAVAILABLE' if unavailable
                             else 'NO_ADVERSE_WEATHER_CLAIMED'],
            'observations': [],
            'coverage': {'requestedCities': 0, 'returnedCities': 0,
                         'routeCoverage': 'NOT_REQUESTED'},
        }
    snapshot = weather_snapshot_entry(cities())
    world = PublicWeather(snapshot, cities())
    winds = _wind_grid(snapshot, city_id)
    return {
        **snapshot, 'source': snapshot.get('provider') or 'UNKNOWN',
        'scenario': scenario, 'minute': minute, 'cityId': city_id,
        'cells': _with_risk_envelope(world.frame(minute), rules), 'winds': winds, 'riskRules': rules,
        'extremeThresholds': extreme_thresholds(),
        'radar': radar_regions(minute), 'lowVisibility': low_visibility_regions(minute),
        'weatherMode': weather_mode,
    }

def _radar_rule_block():
    return {
        'tiers': 'CONVECTIVE_AND_STRONG',
        'bandFloorDbz': cma_tiles.ECHO_FLOOR_DBZ,
        'convectiveDbz': cma_tiles.CONVECTIVE_DBZ,
        'strongDbz': cma_tiles.STRONG_DBZ,
        'coreInsetM': radar_field.CORE_INSET_M,
        'penetrationM': profiles()['separation']['horizontalM'],
    }

def _radar_avoidance(scenario, weather_mode=None, progress=None):
    if weather_mode is None:
        weather_mode = weather_control.mode()
    if scenario != 'live':
        return GeometryCollection(), {'included': False,
                                      'reason': 'SCENARIO_DOES_NOT_DECLARE_WEATHER',
                                      **_radar_rule_block()}
    if weather_mode == weather_control.MODE_VIRTUAL:
        tally = {}
        samples = _virtual_radar_sweep(progress, diagnostics=tally)
        info = {'included': bool(samples), 'mode': weather_mode,
                'slot': SIMULATION_BASE_TIME.isoformat().replace('+00:00', 'Z'),
                'slotTo': (SIMULATION_BASE_TIME + timedelta(minutes=TIMELINE_MINUTES)
                           ).isoformat().replace('+00:00', 'Z'),
                'sweepSlots': len(samples), 'sweepStrideMinutes': RADAR_SWEEP_STRIDE_MINUTES,
                'sweepEmptySlots': tally.get('empty', 0),
                'note': '模拟回波随推演时间轴平移；避让按各班次飞行窗口内的当刻回波取并集'
                        '（35 dBZ 以上；层状降水仅展示，不构成限制）。',
                **_radar_rule_block()}
        if tally.get('notSynthetic'):
            return GeometryCollection(), {
                **info, 'included': False, 'reason': 'VIRTUAL_FRAME_NOT_SYNTHETIC',
                'detail': f'虚拟通道的扫掠里有 {tally["notSynthetic"]} 个时次拿到的帧不带合成标记，'
                          '取帧没有走生成器；本计划不使用雷达避让。'}
        if tally.get('unavailable'):
            return GeometryCollection(), {
                **info, 'included': False, 'reason': 'VIRTUAL_FRAME_UNAVAILABLE',
                'detail': f'虚拟通道的扫掠里有 {tally["unavailable"]} 个时次取不到帧 —— 回波是生成的，'
                          '本不应发生；本计划不使用雷达避让。'}
        if not samples:
            info['included'] = False
            info['reason'] = 'NO_CONVECTIVE_ECHO'
            info['detail'] = '生成的回波已逐时次读取并逐档判定：本推演窗口内未达 35 dBZ 阈值。'
        return samples, info
    frame_result = weather_control.radar_frame()
    if frame_result.get('mode') != weather_mode:
        return GeometryCollection(), {
            'included': False, 'mode': weather_mode,
            'reason': 'CHANNEL_CHANGED_DURING_BUILD',
            'detail': f'计划按 {weather_mode} 生成，构建期间通道变为 '
                      f'{frame_result.get("mode")}，本计划不使用雷达避让。',
            **_radar_rule_block()}
    derived = radar_field.derive(frame_result, minute=0)
    if not derived.get('available'):
        return GeometryCollection(), {'included': False, 'mode': frame_result.get('mode'),
                                      'reason': 'RADAR_UNAVAILABLE', 'detail': derived.get('error'),
                                      **_radar_rule_block()}
    field, core, caution, watch = radar_field.shield(derived)
    provenance = derived.get('provenance') or {}
    info = {'included': not field.is_empty, 'mode': weather_mode,
            'slot': provenance.get('slot'), 'slotAgeMinutes': provenance.get('slotAgeMinutes'),
            'areaKm2': round(field.area / 1e6, 1),
            'coreAreaKm2': round(core.area / 1e6, 1),
            'cautionAreaKm2': round(caution.area / 1e6, 1),
            'watchAreaKm2': round(watch.area / 1e6, 1),
            'note': '单时刻实测观测驱动全窗口避让（35 dBZ 以上；层状降水仅展示，不构成限制）。',
            **_radar_rule_block()}
    if field.is_empty:
        info['reason'] = 'NO_CONVECTIVE_ECHO'
        info['detail'] = ('回波帧已取到并逐级判定：本帧没有 ≥35 dBZ 回波，'
                          '所有航路按直线走廊放行；15–35 dBZ 层状降水不构成限制。')
    return field, info

def _low_visibility_avoidance(scenario, snapshot, city_rows):
    if scenario != 'live':
        return (GeometryCollection(), [], {
            'included': False, 'reason': 'SCENARIO_DOES_NOT_DECLARE_WEATHER',
            'cities': 0, 'padExemptFlights': 0, **fog_rule_block()})
    if not (snapshot or {}).get('available'):
        return (GeometryCollection(), [], {
            'included': False, 'reason': 'WEATHER_UNAVAILABLE',
            'detail': '气象快照不可用，本计划不加入能见度避让几何。',
            'cities': 0, 'padExemptFlights': 0, **fog_rule_block()})
    rows = fog_tiers(snapshot, city_rows)
    if not rows:
        return (GeometryCollection(), [], {
            'included': False, 'reason': 'NO_LOW_VISIBILITY_READING',
            'detail': ('能见度已逐城读取并逐档判定：本帧没有站点低于偏低档阈值，'
                       '所有航路不加入能见度避让几何。'),
            'cities': 0, 'padExemptFlights': 0, **fog_rule_block()})
    bans = [ban for _cell, _caution, ban in rows if not ban.is_empty]
    discs = [{'cityId': cell['cityId'], 'cityName': cell['cityName'],
              'tier': cell['tier'], 'visibilityM': cell['visibilityM'],
              'geometry': caution}
             for cell, caution, _ban in rows if not caution.is_empty]
    ban_geom = unary_union(bans) if bans else GeometryCollection()
    info = {
        'included': bool(bans) or bool(discs),
        'cities': len(rows),
        'banCities': sum(1 for cell, _c, _b in rows if cell['tier'] == 'BAN'),
        'cautionCities': sum(1 for cell, _c, _b in rows if cell['tier'] == 'CAUTION'),
        'banAreaKm2': round(ban_geom.area / 1e6, 1),
        'cautionAreaKm2': round(sum(disc['geometry'].area for disc in discs) / 1e6, 1),
        'readings': [{'cityId': cell['cityId'], 'cityName': cell['cityName'],
                      'tier': cell['tier'],
                      'visibilityM': cell['visibilityM']}
                     for cell, _c, _b in rows],
        'padExemptFlights': 0,
        'padExemptCities': [],
        **fog_rule_block(),
    }
    return (ban_geom, discs, info)

def _exempt_fog_caution(caution_discs, from_xy, to_xy):
    if not caution_discs:
        return None, []
    a, b = Point(from_xy), Point(to_xy)
    exempt = [index for index, disc in enumerate(caution_discs)
              if disc['geometry'].covers(a) or disc['geometry'].covers(b)]
    if not exempt:
        return None, []
    rest = [disc['geometry'] for index, disc in enumerate(caution_discs)
            if index not in exempt]
    cities_exempt = sorted({caution_discs[index]['cityId'] for index in exempt})
    return (unary_union(rest) if rest else GeometryCollection()), cities_exempt

def _reason_tally(flights, closed_only=False):
    tally = {}
    for item in flights:
        if closed_only and item.get('status') == 'SCHEDULED':
            continue
        reason = item.get('reason')
        if not reason:
            continue
        tally[reason] = tally.get(reason, 0) + 1
    return dict(sorted(tally.items(), key=lambda pair: (-pair[1], pair[0])))

def _wind_grid(snapshot, city_id=None):
    observations = []
    for observation in snapshot.get('observations', []):
        source_city = next((item for item in cities() if item['id'] == observation['cityId']), None)
        if not source_city:
            continue
        if city_id and source_city['id'] != city_id:
            continue
        speed = observation.get('windSpeed10mMps')
        direction = observation.get('windDirection10mDeg')
        if speed is None or direction is None:
            continue
        radians = math.radians(direction)
        observations.append({
            'xy': list(source_city['xy']),
            'u': -speed * math.sin(radians), 'v': -speed * math.cos(radians),
            'cityId': source_city['id'],
        })
    if not observations:
        return []
    provider = snapshot.get('provider') or 'UNKNOWN'
    if city_id:
        only = observations[0]
        return [{**only, 'xy': [only['xy'][0] + 600, only['xy'][1] + 600],
                 'source': provider, 'interpolated': False}]
    area = boundary()
    samples = _wind_samples(area)
    if not samples:
        return [{**item, 'source': provider, 'interpolated': False} for item in observations]
    grid = []
    for x, y in samples:
        near = sorted(observations, key=lambda item: (item['xy'][0] - x) ** 2 + (item['xy'][1] - y) ** 2)[:WIND_NEIGHBOURS]
        total = 0.0
        u = v = 0.0
        for item in near:
            d2 = (item['xy'][0] - x) ** 2 + (item['xy'][1] - y) ** 2
            w = 1.0 / max(d2, 1.0)
            u += item['u'] * w
            v += item['v'] * w
            total += w
        if total <= 0:
            continue
        grid.append({'xy': [x, y], 'u': u / total, 'v': v / total,
                     'cityId': near[0]['cityId'], 'source': provider,
                     'interpolated': True})
    return grid

def _wind_samples(area):
    if area is None or area.is_empty:
        return []
    box = area.bounds
    lon_w, lat_s = geometry.unproject((box[0], box[1]))
    lon_e, lat_n = geometry.unproject((box[2], box[3]))
    if not all(math.isfinite(v) for v in (lon_w, lat_s, lon_e, lat_n)):
        return []
    span_lat = lat_n - lat_s
    if span_lat <= 0:
        return []
    bands = max(2, int(math.ceil(span_lat / _degrees_for_metres(WIND_BAND_M))) + 1)
    samples = []
    for band in range(bands):
        lat = lat_s + span_lat * band / (bands - 1)
        high = geometry.project((lon_e, lat))
        low = geometry.project((lon_w, lat))
        parallel = LineString([(low[0], low[1]), (high[0], high[1])])
        spans = _parallel_spans(area.intersection(parallel))
        for lo_lon, hi_lon in spans:
            width_m = abs(hi_lon - lo_lon) * 111_320.0 * math.cos(math.radians(lat))
            columns = max(1, int(math.ceil(width_m / WIND_SAMPLE_SPACING_M)) + 1)
            for col in range(columns):
                lon = lo_lon if columns == 1 else lo_lon + (hi_lon - lo_lon) * col / (columns - 1)
                x, y = geometry.project((lon, lat))
                if not area.covers(Point(x, y)):
                    continue
                samples.append((x, y))
                if len(samples) >= WIND_MAX_VECTORS:
                    return samples
    return samples

def _degrees_for_metres(metres):
    return metres / 111_320.0

def _parallel_spans(geom):
    spans = []
    parts = []
    if geom is None or geom.is_empty:
        return spans
    if geom.geom_type == 'LineString':
        parts = [geom]
    elif geom.geom_type == 'MultiLineString':
        parts = list(geom.geoms)
    for part in parts:
        if len(part.coords) < 2:
            continue
        lons = [geometry.unproject((cx, cy))[0] for cx, cy in part.coords]
        lo, hi = min(lons), max(lons)
        if hi > lo:
            spans.append((lo, hi))
    return spans

def _with_risk_envelope(cells, rules):
    return [{**cell, 'floorAglM': rules['floorAglM'], 'ceilingAglM': rules['ceilingAglM']} for cell in cells]
