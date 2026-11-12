# -*- coding: utf-8 -*-
"""全国视图（L1）聚合层。

设计纪律
--------
1. **只传聚合**：全国层只给"每省多少条走廊 / 什么状态"，明细由前端按需拉
   `/traffic/v2/corridors`。这是为了避免把 53 走廊 × 1614 班的会话载荷搬到全国屏。
2. **不改任何既有数字**：本模块只读 `service.network()` 与城市目录，不参与
   规划、不参与裁决，因此 2848 / 8 班 / 320 min / 94% 全部不受影响。
3. **三态诚实**：有走廊且有站的省 = operational；只有站 = observing；
   两者都没有 = pending。没有数据就写 pending，不用 0 冒充。
4. **大区按民航局七大区**：华北 / 东北 / 华东 / 中南 / 西南 / 西北 / 新疆。
   港澳台单列 `other`，不计入七大区统计。
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from weather import metar_history, national_metar

from . import service as traffic

ASSET_PATH = Path(__file__).resolve().parents[2] / 'frontend' / 'src' / 'assets' / 'china.json'
CORRIDOR_PATH = Path(__file__).resolve().parents[2] / 'data' / 'traffic' / 'national-corridors.json'

REGION_ORDER: Tuple[str, ...] = (
    'north', 'northeast', 'east', 'central', 'southwest', 'northwest', 'xinjiang',
)
REGION_NAMES: Dict[str, str] = {
    'north': '华北', 'northeast': '东北', 'east': '华东', 'central': '中南',
    'southwest': '西南', 'northwest': '西北', 'xinjiang': '新疆',
    'other': '港澳台及其他',
}
REGION_OF: Dict[int, str] = {
    110000: 'north', 120000: 'north', 130000: 'north', 140000: 'north', 150000: 'north',
    210000: 'northeast', 220000: 'northeast', 230000: 'northeast',
    310000: 'east', 320000: 'east', 330000: 'east', 340000: 'east',
    350000: 'east', 360000: 'east', 370000: 'east',
    410000: 'central', 420000: 'central', 430000: 'central',
    440000: 'central', 450000: 'central', 460000: 'central',
    500000: 'southwest', 510000: 'southwest', 520000: 'southwest',
    530000: 'southwest', 540000: 'southwest',
    610000: 'northwest', 620000: 'northwest', 630000: 'northwest', 640000: 'northwest',
    650000: 'xinjiang',
    710000: 'other', 810000: 'other', 820000: 'other',
}

STATE_OPERATIONAL = 'operational'
STATE_OBSERVING = 'observing'
STATE_TRUNK_ONLY = 'trunk'
STATE_PENDING = 'pending'


@lru_cache(maxsize=1)
def provinces() -> Tuple[Dict[str, Any], ...]:
    """省级单元，来自前端同款底图，保证两边 adcode 一致。

    底图共 35 个要素，其中 `100000_JD` 是**南海诸岛示意要素**（无 adcode、无名称），
    不是行政单元，这里显式排除 —— 所以省级单元实为 **34**（大陆 31 + 港澳台 3）。
    """
    with ASSET_PATH.open('r', encoding='utf-8') as handle:
        payload = json.load(handle)
    rows: List[Dict[str, Any]] = []
    for feature in payload.get('features') or []:
        props = feature.get('properties') or {}
        adcode = props.get('adcode')
        if not isinstance(adcode, int):
            continue
        centre = props.get('center') or props.get('centroid')
        rows.append({
            'adcode': adcode,
            'name': props.get('name') or '',
            'region': REGION_OF.get(adcode, 'other'),
            'center': [round(float(centre[0]), 4), round(float(centre[1]), 4)] if centre else None,
        })
    rows.sort(key=lambda item: item['adcode'])
    return tuple(rows)


def _distance_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def station_provinces() -> Counter:
    """把 METAR 站挂到省：取最近的省会/城市代表点（东三省那 4 站的旧口径）。"""
    cities = traffic.cities()
    counter: Counter = Counter()
    for code, info in metar_history.STATION_INFO.items():
        point = (float(info['lon']), float(info['lat']))
        best: Optional[Tuple[float, str]] = None
        for city in cities:
            distance = _distance_km(point, (float(city['coordinate'][0]), float(city['coordinate'][1])))
            if best is None or distance < best[0]:
                best = (distance, city['province'])
        if best is not None and best[0] <= 150.0:
            counter[best[1]] += 1
    return counter


# ------------------------------------------------------------------ 全国覆盖层
# 两条数据来源必须分开写清楚，不能混：
#   站 = 真实 METAR（aviationweather.gov，一次 bbox 拉全国，按省界多边形归属）
#   干线 = 模拟派生（data/traffic/national-corridors.json，MST + 就近补边）

@lru_cache(maxsize=1)
def _province_shapes() -> Dict[int, Any]:
    """省界多边形（经纬度），用于把报文站归属到省。底图与前端同一份。"""
    from shapely.geometry import shape
    with ASSET_PATH.open('r', encoding='utf-8') as handle:
        payload = json.load(handle)
    shapes: Dict[int, Any] = {}
    for feature in payload.get('features') or []:
        props = feature.get('properties') or {}
        adcode = props.get('adcode')
        geometry = feature.get('geometry')
        if not isinstance(adcode, int) or not geometry:
            continue
        try:
            shapes[adcode] = shape(geometry)
        except Exception:  # noqa: BLE001 - 单个要素几何坏了不该拖垮全国层
            continue
    return shapes


@lru_cache(maxsize=1)
def _polygon_index():
    """(adcode, prepared geometry) 列表，供逐站命中测试。"""
    from shapely.prepared import prep
    return [(adcode, prep(geometry)) for adcode, geometry in _province_shapes().items()]


@lru_cache(maxsize=1)
def national_corridors() -> Tuple[Dict[str, Any], ...]:
    if not CORRIDOR_PATH.is_file():
        return ()
    payload = json.loads(CORRIDOR_PATH.read_text(encoding='utf-8'))
    return tuple(payload.get('corridors') or ())


def _station_rows() -> Tuple[Dict[int, List[Dict[str, Any]]], Dict[str, Any]]:
    """把全国报文站按省界归属；返回 {adcode: [站...]} 与数据源状态。"""
    payload = national_metar.fetch()
    stations = payload.get('stations') or {}
    by_province: Dict[int, List[Dict[str, Any]]] = {}
    if not payload.get('available'):
        return by_province, {'available': False, 'source': 'METAR (aviationweather.gov)',
                             'error': payload.get('error'), 'count': 0}
    from shapely.geometry import Point
    for row in stations.values():
        point = Point(row['lon'], row['lat'])
        for adcode, prepared in _polygon_index():
            if prepared.contains(point):
                by_province.setdefault(adcode, []).append(row)
                break
    return by_province, {'available': True, 'source': payload.get('source'),
                         'fetchedAt': payload.get('fetchedAt'), 'count': len(stations)}


def _corridor_counts() -> Tuple[Counter, Counter, int]:
    """按省统计走廊数，**城际（CAR）与配送（DELIVERY）分开**。

    全国屏的"风险走廊"口径只算城际走廊；配送走廊是城内的，混进来会让总数
    被误读成"全国这么多条风险走廊"。

    第三个返回值是**跨省走廊数**：这类走廊的 `province` 为 None，不属于任何一个省，
    所以单独计数，不能悄悄丢进某个省，也不能从总数里消失。
    """
    car: Counter = Counter()
    delivery: Counter = Counter()
    interprovincial = 0
    for route in traffic.network().get('routes') or []:
        province = route.get('province')
        if route.get('mode') == 'DELIVERY':
            if province:
                delivery[province] += 1
            continue
        if province:
            car[province] += 1
        else:
            interprovincial += 1
    return car, delivery, interprovincial


def national() -> Dict[str, Any]:
    """全国层聚合。体积目标 < 30 KB（约 35 条省级记录 + 干线/站点点位）。"""
    car_counts, delivery_counts, interprovincial = _corridor_counts()
    station_counts = station_provinces()
    city_counts: Counter = Counter(city['province'] for city in traffic.cities())
    stations_by_province, station_meta = _station_rows()
    corridors = national_corridors()

    # 省级干线按端点归属：一条干线同时计入两端省份
    trunk_counts: Counter = Counter()
    for row in corridors:
        trunk_counts[row['from']] += 1
        trunk_counts[row['to']] += 1

    rows: List[Dict[str, Any]] = []
    region_stats: Dict[str, Dict[str, Any]] = {
        key: {'id': key, 'name': REGION_NAMES[key], 'provinceCount': 0,
              'operational': 0, 'observing': 0, 'trunk': 0, 'pending': 0, 'corridors': 0,
              'deliveryCorridors': 0, 'cities': 0, 'stations': 0}
        for key in REGION_ORDER
    }
    summary = {'operational': 0, 'observing': 0, 'trunk': 0, 'trunkTotal': 0, 'pending': 0,
               'endpointCorridors': 0, 'localTotal': 0,
               'deliveryCorridors': 0, 'cities': 0, 'stations': 0}
    station_points: List[Dict[str, Any]] = []
    # 条数口径：干线 = 文件里的行数；本地网 = 东三省实际跑出来的城际走廊（含跨省）
    summary['trunkTotal'] = len(corridors)
    summary['localTotal'] = sum(car_counts.values()) + interprovincial

    for province in provinces():
        name = province['name']
        adcode = province['adcode']
        trunk = int(trunk_counts.get(adcode, 0))
        local = int(car_counts.get(name, 0))
        corridors_total = trunk + local
        delivery = int(delivery_counts.get(name, 0))
        live = stations_by_province.get(adcode) or []
        stations = len(live) + int(station_counts.get(name, 0)) if live else int(station_counts.get(name, 0))
        # 站数按真实报文站算；东三省那 4 站也在这批里，别再叠加两次
        stations = len(live)
        cities = int(city_counts.get(name, 0))
        if corridors_total > 0 and stations > 0:
            state = STATE_OPERATIONAL
        elif stations > 0:
            state = STATE_OBSERVING
        elif corridors_total > 0:
            # 有干线但本站没有报文：不能算"运行态"，也不能说"待接入"——单列一态。
            state = STATE_TRUNK_ONLY
        else:
            state = STATE_PENDING
        rows.append({
            'adcode': adcode,
            'name': name,
            'region': province['region'],
            'state': state,
            'corridors': corridors_total,
            'trunkCorridors': trunk,
            'localCorridors': local,
            'deliveryCorridors': delivery,
            'cities': cities,
            'stations': stations,
            'center': province['center'],
        })
        for row in live:
            station_points.append({
                'code': row['station'], 'name': province['name'],
                'lon': row['lon'], 'lat': row['lat'], 'ts': row['ts'],
                'visM': row['visM'], 'tempC': row['tempC'],
                'visLower': bool(row.get('visLower')),
                'low': bool(isinstance(row['visM'], (int, float)) and row['visM'] < 3000),
            })
        summary[state] += 1
        summary['endpointCorridors'] += corridors_total
        summary['deliveryCorridors'] += delivery
        summary['cities'] += cities
        summary['stations'] += stations
        region = region_stats.get(province['region'])
        if region is not None:
            region['provinceCount'] += 1
            region[state] += 1
            region['corridors'] += corridors_total
            region['deliveryCorridors'] += delivery
            region['cities'] += cities
            region['stations'] += stations

    return {
        'status': 'OK',
        'layer': 'L1-national',
        'generatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'regions': [region_stats[key] for key in REGION_ORDER],
        'provinces': rows,
        'corridors': list(corridors),
        'stationPoints': station_points,
        'coverage': {
            'stations': station_meta,
            'trunk': {'source': 'SIM', 'count': len(corridors),
                      'note': '省级干线（省会代表点 MST + 就近补边），只用于全国屏聚合与示意，'
                              '不参与运行计划与裁决'},
            # 本层不写死省名与条数：RUN 走廊来自运行计划，计划变了两句话就会漂。
            'local': {'source': 'RUN', 'provinces': len([p for p in car_counts if p]),
                      'corridors': sum(car_counts.values()),
                      'interprovincial': interprovincial,
                      'note': (f'运行计划实际跑出的城际走廊 {sum(car_counts.values())} 条'
                               f'（分布在 {len([p for p in car_counts if p])} 个省级单元）'
                               f'，另有跨省 {interprovincial} 条；与省级干线分开计数，不合并')},
        },
        'summary': {
            'provinces': len(rows),
            'regions': len(REGION_ORDER),
            'operational': summary['operational'],
            'observing': summary['observing'],
            'trunkOnly': summary['trunk'],
            'pending': summary['pending'],
            'corridors': summary['trunkTotal'] + summary['localTotal'],
            'endpointCorridors': summary['endpointCorridors'],
            'trunkCorridors': summary['trunkTotal'],
            'localCorridors': summary['localTotal'],
            'interprovincialCorridors': interprovincial,
            'deliveryCorridors': summary['deliveryCorridors'],
            'cities': summary['cities'],
            'stations': summary['stations'],
            'stationChannels': station_meta.get('count', 0),
        },
        'notes': [
            '底图 35 个要素中 1 个为南海诸岛示意（无 adcode），省级单元实为 34。',
            '站是真实 METAR（aviationweather.gov 一次拉全国，按省界多边形归属）；拿不到就是 0，不补零。',
            '干线是模拟派生（省会代表点 MST + 就近补边），标注 source=SIM，不参与规划与裁决。',
            '四态：operational=有走廊且有站；observing=只有站；trunk=有干线但本站无报文；pending=都没有。',
            '全国层只传聚合与点位，明细仍按省懒加载；本接口不改变任何既有运行数字。',
        ],
    }
