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

from weather import metar_history

from . import service as traffic

ASSET_PATH = Path(__file__).resolve().parents[2] / 'frontend' / 'src' / 'assets' / 'china.json'

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
    """把 METAR 站挂到省：取最近的省会/城市代表点。

    只有 4 个站（沈阳/长春/哈尔滨/大连），用最近城市反查比再写一张常量表更不容易失同步。
    """
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


def _corridor_counts() -> Tuple[Counter, Counter, int]:
    """按省统计走廊数，**城际（CAR）与配送（DELIVERY）分开**。

    全国屏的"风险走廊"口径只算城际走廊（53 条那条网）；配送走廊是城内的，
    混进来会让 267 这种数字被误读成"全国 267 条风险走廊"。

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
    """全国层聚合。体积目标 < 30 KB（约 35 条省级记录）。"""
    car_counts, delivery_counts, interprovincial = _corridor_counts()
    station_counts = station_provinces()
    city_counts: Counter = Counter(city['province'] for city in traffic.cities())

    rows: List[Dict[str, Any]] = []
    region_stats: Dict[str, Dict[str, Any]] = {
        key: {'id': key, 'name': REGION_NAMES[key], 'provinceCount': 0,
              'operational': 0, 'observing': 0, 'pending': 0, 'corridors': 0,
              'deliveryCorridors': 0, 'cities': 0}
        for key in REGION_ORDER
    }
    summary = {'operational': 0, 'observing': 0, 'pending': 0, 'corridors': 0,
               'deliveryCorridors': 0, 'cities': 0}

    for province in provinces():
        name = province['name']
        corridors = int(car_counts.get(name, 0))
        delivery = int(delivery_counts.get(name, 0))
        stations = int(station_counts.get(name, 0))
        cities = int(city_counts.get(name, 0))
        if corridors > 0:
            state = STATE_OPERATIONAL
        elif stations > 0:
            state = STATE_OBSERVING
        else:
            state = STATE_PENDING
        rows.append({
            'adcode': province['adcode'],
            'name': name,
            'region': province['region'],
            'state': state,
            'corridors': corridors,
            'deliveryCorridors': delivery,
            'cities': cities,
            'stations': stations,
            'center': province['center'],
        })
        summary[state] += 1
        summary['corridors'] += corridors
        summary['deliveryCorridors'] += delivery
        summary['cities'] += cities
        region = region_stats.get(province['region'])
        if region is not None:
            region['provinceCount'] += 1
            region[state] += 1
            region['corridors'] += corridors
            region['deliveryCorridors'] += delivery
            region['cities'] += cities

    return {
        'status': 'OK',
        'layer': 'L1-national',
        'generatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'regions': [region_stats[key] for key in REGION_ORDER],
        'provinces': rows,
        'summary': {
            'provinces': len(rows),
            'regions': len(REGION_ORDER),
            'operational': summary['operational'],
            'observing': summary['observing'],
            'pending': summary['pending'],
            'corridors': summary['corridors'],
            'interprovincialCorridors': interprovincial,
            'deliveryCorridors': summary['deliveryCorridors'],
            'cities': summary['cities'],
            'stations': len(metar_history.STATION_INFO),
        },
        'notes': [
            '底图 35 个要素中 1 个为南海诸岛示意（无 adcode），省级单元实为 34。',
            '全国层只传聚合，明细按省懒加载（点省再拉 /traffic/v2/corridors）。',
            '三态：operational=有走廊且有站；observing=只有站；pending=待接入。',
            '大区按民航局七大区划分；港澳台单列，不计入七大区。',
            '本接口不参与规划与裁决，不改变任何既有运行数字。',
        ],
    }
