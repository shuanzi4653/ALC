# -*- coding: utf-8 -*-
"""北方地区（四级：北方 → 大区 → 省 → 市）。

为什么是"北方"而不是"全国"
--------------------------
全国 34 个省级单元里，只有东北三省有真实城市对与航路数据；其余省份连城市目录都没有。
把全国硬拉通，最后只能靠"直线干线"充数。收到北方（东北 + 华北 + 西北 13 省）之后：

- **站**：真实 METAR（`weather/national_metar.py`），按省界多边形归属；
- **干线**：`network_builder.build()` 用北方专用 AEQD + A* 真跑出来的航路；
- **东北三省**：继续用 `service.network()` 那 53 条（保证 2848/8/320 不动）。

四级都走同一个入口 `payload(level, id)`，逐级懒加载 —— 前端每下钻一次重新请求，
返回上级时把数据清掉，不在内存里留整棵树。
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from . import network_builder as builder
from . import national as national_mod
from . import service as traffic

NORTH_REGIONS = ('northeast', 'north', 'northwest')
REGION_LABEL = {'northeast': '东北', 'north': '华北', 'northwest': '西北'}
NORTHEAST_PROVINCES = ('辽宁省', '吉林省', '黑龙江省')
# 新疆并入"西北"这一级展示（民航局七大区里单列，但用户要的是北方三块）
REGION_ALIAS = {'xinjiang': 'northwest'}


def _north_provinces() -> List[Dict[str, Any]]:
    rows = []
    for row in national_mod.national()['provinces']:
        region = REGION_ALIAS.get(row['region'], row['region'])
        if region not in NORTH_REGIONS:
            continue
        rows.append({**row, 'region': region, 'regionLabel': REGION_LABEL[region]})
    rows.sort(key=lambda item: (NORTH_REGIONS.index(item['region']), item['adcode']))
    return rows


@lru_cache(maxsize=8)
def _network(region: Optional[str] = None) -> Dict[str, Any]:
    """按大区取网络：东北走原网络，华北/西北走通用 A* 构建。"""
    provinces = tuple(row['name'] for row in _north_provinces()
                      if region is None or row['region'] == region)
    if not provinces:
        return {'provinces': [], 'corridors': [], 'nodes': [], 'astar': 0, 'fallback': 0}
    if region == 'northeast':
        # 东北：沿用运行计划那张真实网络（51 省内 + 2 跨省）
        rows = []
        for route in traffic.network().get('routes') or []:
            if route.get('mode') == 'DELIVERY':
                continue
            points = route.get('path') or []
            if len(points) < 2:
                continue
            xy = points[0], points[-1]
            from .network_builder import INVERSE
            first = INVERSE.transform(*xy[0])
            last = INVERSE.transform(*xy[1])
            rows.append({
                'id': route['id'], 'from': route.get('province') or '', 'to': route.get('province') or '',
                'fromName': route.get('fromCity'), 'toName': route.get('toCity'),
                'lengthKm': None, 'fromLonLat': list(first), 'toLonLat': list(last),
                'path': [list(INVERSE.transform(x, y)) for x, y in points],
                'source': 'RUN', 'geometry': 'RUN_PLAN',
            })
        return {'provinces': list(provinces), 'corridors': rows,
                'nodes': [], 'astar': len(rows), 'fallback': 0}
    return builder.build(provinces)


def _province_rows() -> List[Dict[str, Any]]:
    north = _north_provinces()
    by_name = {row['name']: row for row in north}
    trunk = _network(None)['corridors']
    counts: Dict[str, int] = {}
    for row in trunk:
        for side in (row['from'], row['to']):
            if side:
                counts[side] = counts.get(side, 0) + 1
    rows = []
    for row in north:
        # 东北三省沿用 national 层算好的本地网条数（51 省内 + 2 跨省），不再重算
        car_local = int(row.get('localCorridors') or 0)
        trunk_count = counts.get(row['name'], 0)
        rows.append({**row, 'trunkCorridors': trunk_count,
                     'localCorridors': car_local,
                     'corridorEndpoints': trunk_count + car_local,
                     'corridors': trunk_count + car_local,
                     'stations': int(row.get('stations') or 0)})
    return rows


def _station_points() -> List[Dict[str, Any]]:
    return [point for point in national_mod.national()['stationPoints']
            if point['name'] in {row['name'] for row in _north_provinces()}]


def _state(row: Dict[str, Any]) -> str:
    corridors, stations = row.get('corridors', 0), row.get('stations', 0)
    if corridors and stations:
        return 'operational'
    if stations:
        return 'observing'
    if corridors:
        return 'trunk'
    return 'pending'


def _cities_of(province: str) -> List[Dict[str, Any]]:
    """市层：东北取真实城市目录；其他省只有省会（底图 center），如实标注。"""
    out: List[Dict[str, Any]] = []
    seen = set()
    for city in traffic.cities():
        if city['province'] != province:
            continue
        out.append({'name': city['name'], 'lon': city['coordinate'][0], 'lat': city['coordinate'][1],
                    'source': 'RUN_CATALOG', 'pads': len(traffic.city_pads(city))})
        seen.add(city['name'])
    centre = builder.province_centers().get(province)
    if centre and province not in NORTHEAST_PROVINCES:
        label = province.replace('省', '').replace('市', '').replace('自治区', '')
        out.append({'name': f'{label}（省会）', 'lon': centre['lon'], 'lat': centre['lat'],
                    'source': 'CAPITAL', 'pads': 0})
    return out


LOCAL_CORRIDORS = 53   # 东北三省实际跑出来的城际走廊（51 省内 + 2 跨省）


def payload(level: str = 'north', ident: Optional[str] = None) -> Dict[str, Any]:
    provinces = _province_rows()
    points = _station_points()
    network = _network(None)
    base = {
        'status': 'OK',
        'layer': f'L-{level}',
        'level': level,
        'id': ident,
        'generatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'scope': {'name': '北方地区', 'provinces': [row['name'] for row in provinces],
                  'regions': list(NORTH_REGIONS)},
        'sources': {
            'stations': 'METAR（aviationweather.gov，按省界归属；拿不到即 0）',
            'trunk': 'SIM（北方专用 AEQD + A*，省会代表点 MST + 就近补边）',
            'northeastLocal': 'RUN（东北三省 51 省内 + 2 跨省城际走廊，来自运行计划）',
        },
    }

    if level == 'north':
        regions = []
        for key in NORTH_REGIONS:
            rows = [row for row in provinces if row['region'] == key]
            regions.append({
                'id': key, 'name': REGION_LABEL[key], 'provinces': len(rows),
                'corridors': sum(row['corridors'] for row in rows),
                'stations': sum(row['stations'] for row in rows),
                'operational': sum(1 for row in rows if _state(row) == 'operational'),
                'pending': sum(1 for row in rows if _state(row) == 'pending'),
            })
        return {**base, 'regions': regions,
                'provinces': [{**row, 'state': _state(row)} for row in provinces],
                'corridors': network['corridors'], 'stationPoints': points,
                'summary': {'provinces': len(provinces),
                            'corridors': len(network['corridors']) + LOCAL_CORRIDORS,
                            'endpointCorridors': sum(row['corridors'] for row in provinces),
                            'trunk': len(network['corridors']),
                            'stations': len({point['code'] for point in points}),
                            'operational': sum(1 for row in provinces if _state(row) == 'operational'),
                            'pending': sum(1 for row in provinces if _state(row) == 'pending')}}

    if level == 'region':
        key = ident if ident in NORTH_REGIONS else 'northeast'
        rows = [row for row in provinces if row['region'] == key]
        subnet = _network(key)
        names = {row['name'] for row in rows}
        return {**base, 'region': {'id': key, 'name': REGION_LABEL[key]},
                'provinces': [{**row, 'state': _state(row)} for row in rows],
                'corridors': subnet['corridors'], 'stationPoints': points,
                'summary': {'provinces': len(rows),
                            # 大区内的条数就是该区网络自己的条数（东北=53 本地，华北/西北=各自的 A* 干线）
                            'corridors': len(subnet['corridors']),
                            'endpointCorridors': sum(row['corridors'] for row in rows),
                            'trunk': len(subnet['corridors']),
                            'stations': sum(row['stations'] for row in rows),
                            'operational': sum(1 for row in rows if _state(row) == 'operational'),
                            'pending': sum(1 for row in rows if _state(row) == 'pending')}}

    if level == 'province':
        row = next((item for item in provinces if item['name'] == ident), None)
        if row is None:
            return {'status': 'NOT_FOUND', 'level': level, 'id': ident,
                    'note': '该省不在北方范围内'}
        cities = _cities_of(ident)
        return {**base, 'region': {'id': row['region'], 'name': REGION_LABEL[row['region']]},
                'province': {**row, 'state': _state(row)},
                'provinces': [{**row, 'state': _state(row)}],
                'cities': cities,
                'stationPoints': [point for point in points if point['name'] == ident],
                'summary': {'provinces': 1, 'corridors': row['trunkCorridors'] + row['localCorridors'],
                            'endpointCorridors': row['corridors'],
                            'trunk': row['trunkCorridors'], 'stations': row['stations'],
                            'operational': 1 if _state(row) == 'operational' else 0,
                            'pending': 1 if _state(row) == 'pending' else 0}}

    if level == 'city':
        province = None
        city = None
        for row in provinces:
            for item in _cities_of(row['name']):
                if item['name'] == ident:
                    province, city = row, item
                    break
            if city:
                break
        if city is None:
            return {'status': 'NOT_FOUND', 'level': level, 'id': ident,
                    'note': '北方范围内没有这个城市（市层只列已接入城市）'}
        return {**base, 'province': {**province, 'state': _state(province)},
                'provinces': [{**province, 'state': _state(province)}],
                'city': city,
                'stationPoints': [point for point in points
                                  if point['name'] == province['name']],
                'summary': {'provinces': 1,
                            'corridors': province['trunkCorridors'] + province['localCorridors'],
                            'endpointCorridors': province['corridors'],
                            'trunk': province['trunkCorridors'],
                            'stations': province['stations'],
                            'operational': 1 if _state(province) == 'operational' else 0,
                            'pending': 1 if _state(province) == 'pending' else 0}}

    return {'status': 'INVALID', 'level': level,
            'note': 'level 只能是 north / region / province / city'}
