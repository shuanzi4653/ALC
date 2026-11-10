# -*- coding: utf-8 -*-
"""全国航线网（四级：全国 → 大区 → 省 → 市）。

口径（2026-11-10 用户拍板）
--------------------------
- **范围**：全国 30 个省级单元。**不含台湾、西藏、港澳**（这两地不通航，不纳入网络）。
- **节点**：每个地级单元一个节点，共 331 个（`data/traffic/cities-cn.json`，坐标来自 Wikidata）。
- **航线**：`data/traffic/nation-network.json`（`tools/traffic/build_nation_network.py` 离线生成）：
    ① 省内 MST，市市相连；
    ② **没有机场的市另有一条专用接驳**到最近有机场城市（`AIRPORT_FEED`）——
       接驳是"多一条"，省内网照常跑，不是替代；
    ③ 跨省收窄：每省只连最近 1–2 个省，用两省最近城市对做通道（`CROSS`）。
- **定位**：飞行汽车解决**城市间**交通；跨省长距离仍靠飞机与火车 ——
  这套网络是**分担**，不是**取代**，所以跨省只留少量通道，不做全国全互联。
- **机场**：`data/traffic/airports-cn.json`（站点总表，与此刻是否发报无关）。
- **实况**：真实 METAR；某省一个报文站都没有时，用 open-meteo 模型实况兜底并标 `MODEL`。

四级走同一入口 `payload(level, id)`，逐级按需切片 —— 前端每下钻一次重新请求，
返回上级时把数据清掉，内存里不留整棵树。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import national as national_mod

ROOT = Path(__file__).resolve().parents[2]
CITY_FILE = ROOT / 'data' / 'traffic' / 'cities-cn.json'
NETWORK_FILE = ROOT / 'data' / 'traffic' / 'nation-network.json'
AIRPORT_FILE = ROOT / 'data' / 'traffic' / 'airports-cn.json'

REGION_ORDER = ('north', 'northeast', 'east', 'central', 'southwest', 'northwest')
REGION_LABEL = {'north': '华北', 'northeast': '东北', 'east': '华东',
                'central': '中南', 'southwest': '西南', 'northwest': '西北'}
KIND_LABEL = {'INTRA': '省内', 'AIRPORT_FEED': '机场接驳', 'CROSS': '跨省'}

# 省级行政中心（省会/首府/直辖市）。地图上给它们大一号的点 + 一圈浅色环，
# 用来在 331 个节点里一眼认出"省级中心"。
CAPITALS = {
    '北京市': '北京市', '天津市': '天津市', '河北省': '石家庄市', '山西省': '太原市',
    '内蒙古自治区': '呼和浩特市', '辽宁省': '沈阳市', '吉林省': '长春市', '黑龙江省': '哈尔滨市',
    '上海市': '上海市', '江苏省': '南京市', '浙江省': '杭州市', '安徽省': '合肥市',
    '福建省': '福州市', '江西省': '南昌市', '山东省': '济南市', '河南省': '郑州市',
    '湖北省': '武汉市', '湖南省': '长沙市', '广东省': '广州市', '广西壮族自治区': '南宁市',
    '海南省': '海口市', '重庆市': '重庆市', '四川省': '成都市', '贵州省': '贵阳市',
    '云南省': '昆明市', '陕西省': '西安市', '甘肃省': '兰州市', '青海省': '西宁市',
    '宁夏回族自治区': '银川市', '新疆维吾尔自治区': '乌鲁木齐市',
}
EXCLUDED = ('台湾省', '西藏自治区', '香港特别行政区', '澳门特别行政区')


@lru_cache(maxsize=1)
def _cities_doc() -> Dict[str, Any]:
    return json.loads(CITY_FILE.read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def _network() -> Dict[str, Any]:
    return json.loads(NETWORK_FILE.read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def _airports() -> Dict[str, Any]:
    return json.loads(AIRPORT_FILE.read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def _city_rows() -> List[Dict[str, Any]]:
    rows = [row for row in _cities_doc()['cities'] if row.get('lon') is not None]
    airport_by_city: Dict[str, str] = {}
    for station in _airports().get('stationRows') or []:
        if station.get('city'):
            airport_by_city.setdefault(station['city'], station['icao'])
    for row in rows:
        row['airport'] = airport_by_city.get(row['name'])
        row['hasAirport'] = row['airport'] is not None
        row['regionLabel'] = REGION_LABEL.get(row.get('region') or '', '')
        row['capital'] = CAPITALS.get(row['province']) == row['name']
        # 层级：1=省会/首府（大点+浅环）2=机场城市（中点）3=一般节点（小点）
        row['rank'] = 1 if row['capital'] else (2 if row['hasAirport'] else 3)
    return rows


@lru_cache(maxsize=1)
def _corridor_rows() -> List[Dict[str, Any]]:
    return list(_network().get('corridors') or [])


@lru_cache(maxsize=2)
def _province_shapes() -> Dict[str, Any]:
    from shapely.geometry import shape
    asset = ROOT / 'frontend' / 'src' / 'assets' / 'china.json'
    payload = json.loads(asset.read_text(encoding='utf-8'))
    out: Dict[str, Any] = {}
    for feature in payload.get('features') or []:
        name = (feature.get('properties') or {}).get('name')
        if name and feature.get('geometry'):
            out[name] = shape(feature['geometry'])
    return out


def _cities_by_province() -> Dict[str, List[Dict[str, Any]]]:
    table: Dict[str, List[Dict[str, Any]]] = {}
    for row in _city_rows():
        table.setdefault(row['province'], []).append(row)
    return table


def _corridor_stats() -> Dict[str, Dict[str, int]]:
    stats: Dict[str, Dict[str, int]] = {}
    for row in _corridor_rows():
        # 按**标志**统计，不按 kind 猜：同一条线可能既跨省又是接驳（kind 只决定显示名）
        if row.get('cross'):
            key = 'cross'
        elif row.get('feed'):
            key = 'feed'
        else:
            key = 'intra'
        for province in {row['fromProvince'], row['toProvince']}:
            bucket = stats.setdefault(province, {'intra': 0, 'feed': 0, 'cross': 0, 'total': 0})
            bucket[key] += 1
            bucket['total'] += 1
    return stats


def _live_stations() -> List[Dict[str, Any]]:
    """实况点 = 真实 METAR + （仅当该省无报文时）模型实况，逐点带 `source`。"""
    provinces = {row['province'] for row in _city_rows()}
    points: List[Dict[str, Any]] = []
    try:
        payload = national_mod.national()
        for point in payload.get('stationPoints') or []:
            if point.get('name') in provinces:
                points.append({**point, 'source': 'METAR'})
    except Exception:  # noqa: BLE001 - 网络不可用不能把页面打崩
        points = []
    covered = {point['name'] for point in points}
    try:
        from weather import model_stations
        for point in model_stations.fetch().get('points') or []:
            if point['name'] in provinces and point['name'] not in covered:
                points.append(point)
    except Exception:  # noqa: BLE001
        pass
    return points


def _province_rows() -> List[Dict[str, Any]]:
    stations = _live_stations()
    live: Dict[str, int] = {}
    model: Dict[str, int] = {}
    for point in stations:
        bucket = model if point.get('source') == 'MODEL' else live
        bucket[point['name']] = bucket.get(point['name'], 0) + 1
    by_province = _cities_by_province()
    stats = _corridor_stats()
    rows: List[Dict[str, Any]] = []
    for province, cities in by_province.items():
        bucket = stats.get(province) or {'intra': 0, 'feed': 0, 'cross': 0, 'total': 0}
        row = {
            'name': province,
            'adcode': cities[0].get('adcode', '')[:2],
            'region': cities[0].get('region'),
            'regionLabel': cities[0].get('regionLabel'),
            'cities': len(cities),
            'airports': sum(1 for item in cities if item['hasAirport']),
            'capitals': sum(1 for item in cities if item.get('capital')),
            'stations': live.get(province, 0),
            'modelStations': model.get(province, 0),
            'stationSource': 'METAR' if live.get(province) else ('MODEL' if model.get(province) else 'NONE'),
            'corridors': bucket['total'],
            'intraCorridors': bucket['intra'],
            'feedCorridors': bucket['feed'],
            'crossCorridors': bucket['cross'],
            'center': [round(sum(item['lon'] for item in cities) / len(cities), 3),
                       round(sum(item['lat'] for item in cities) / len(cities), 3)],
        }
        row['state'] = _state(row)
        rows.append(row)
    order = {name: index for index, name in enumerate(REGION_ORDER)}
    rows.sort(key=lambda item: (order.get(item['region'], 9), item['adcode']))
    return rows


def _state(row: Dict[str, Any]) -> str:
    observed = row['stations'] or row.get('modelStations') or 0
    if row['airports'] and observed and row['corridors']:
        return 'operational'
    if row['corridors']:
        return 'trunk'
    if observed:
        return 'observing'
    return 'pending'


# 全国视野用固定框：省界里含南海诸岛，按多边形算会被拉到北纬 3°，大陆被压成一条缝。
NATION_BBOX = [73.4, 16.2, 135.2, 53.8]


def _scope_bbox(provinces: List[str]) -> Optional[List[float]]:
    """视野框：全国用固定框；下钻时用**该范围城市节点**的外包框（不用省界多边形，
    否则海南会被南海诸岛撑开，新疆会被阿克赛钦撑开）。"""
    if len(provinces) >= 20:
        return list(NATION_BBOX)
    wanted = set(provinces)
    points = [(row['lon'], row['lat']) for row in _city_rows() if row['province'] in wanted]
    if not points:
        return None
    return [round(min(p[0] for p in points), 3), round(min(p[1] for p in points), 3),
            round(max(p[0] for p in points), 3), round(max(p[1] for p in points), 3)]


def _points_bbox(points: List[Tuple[float, float]]) -> Optional[List[float]]:
    if not points:
        return None
    return [round(min(p[0] for p in points), 3), round(min(p[1] for p in points), 3),
            round(max(p[0] for p in points), 3), round(max(p[1] for p in points), 3)]


def _slice_corridors(provinces: set, city: Optional[str] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in _corridor_rows():
        if city is not None:
            if city not in (row['fromName'], row['toName']):
                continue
        elif row['fromProvince'] not in provinces and row['toProvince'] not in provinces:
            continue
        item = {
            'id': row['id'], 'fromName': row['fromName'], 'toName': row['toName'],
            'fromProvince': row['fromProvince'], 'toProvince': row['toProvince'],
            'kind': row['kind'], 'kindLabel': KIND_LABEL.get(row['kind'], row['kind']),
            'feed': bool(row.get('feed')), 'cross': bool(row.get('cross')),
            'sea': bool(row.get('sea')),
            'lengthKm': row['lengthKm'], 'geometry': row['geometry'],
            'fromLonLat': row['fromLonLat'], 'toLonLat': row['toLonLat'],
        }
        path = row.get('path') or []
        if len(path) > 2:                 # 两点直飞不重复传 path，前端用两端点
            item['path'] = path
        out.append(item)
    return out


def _slice_nodes(provinces: set, city: Optional[str] = None) -> List[Dict[str, Any]]:
    out = []
    for row in _city_rows():
        if row['province'] not in provinces:
            continue
        if city is not None and row['name'] != city:
            continue
        out.append({'name': row['name'], 'province': row['province'],
                    'lon': row['lon'], 'lat': row['lat'],
                    'hasAirport': row['hasAirport'], 'airport': row.get('airport'),
                    'capital': row.get('capital', False), 'rank': row.get('rank', 3)})
    return out


def _summary(provinces: List[Dict[str, Any]], corridors: List[Dict[str, Any]],
             nodes: List[Dict[str, Any]], stations: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_kind = {'INTRA': 0, 'AIRPORT_FEED': 0, 'CROSS': 0}
    for row in corridors:
        if row.get('cross'):
            by_kind['CROSS'] += 1
        elif row.get('feed'):
            by_kind['AIRPORT_FEED'] += 1
        else:
            by_kind['INTRA'] += 1
    return {
        'provinces': len(provinces),
        'cities': len(nodes),
        'airports': sum(1 for row in nodes if row['hasAirport']),
        'feedCities': sum(1 for row in nodes if not row['hasAirport']),
        'corridors': len(corridors),
        'byKind': by_kind,
        'stations': len(stations),
        'stationsMetar': sum(1 for row in stations if row.get('source') != 'MODEL'),
        'stationsModel': sum(1 for row in stations if row.get('source') == 'MODEL'),
        'operational': sum(1 for row in provinces if row['state'] == 'operational'),
        'pending': sum(1 for row in provinces if row['state'] == 'pending'),
    }


def _base(level: str, ident: Optional[str]) -> Dict[str, Any]:
    return {
        'status': 'OK',
        'layer': f'L-{level}',
        'level': level,
        'id': ident,
        'generatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'scope': {'name': '全国', 'regions': list(REGION_ORDER), 'excluded': list(EXCLUDED)},
        'sources': {
            'cities': '民政部区划目录 + Wikidata P625（data/traffic/cities-cn.json）',
            'network': 'SIM：省内 MST + 无机场市机场接驳 + 每省最多 2 条跨省通道（A* 生成）',
            'airports': 'aviationweather.gov stationinfo 站点总表（与是否发报无关）',
            'stations': 'METAR 实时报文；无报文的省用 open-meteo 模型实况兜底并标 MODEL',
        },
        'positioning': '飞行汽车解决城市间交通；跨省长距离仍靠飞机与火车，本网络是分担不是取代。',
    }


def payload(level: str = 'nation', ident: Optional[str] = None) -> Dict[str, Any]:
    provinces = _province_rows()
    stations = _live_stations()
    base = _base(level, ident)
    names = [row['name'] for row in provinces]

    if level in ('nation', 'north'):
        corridors = _slice_corridors(set(names))
        nodes = _slice_nodes(set(names))
        regions = []
        for key in REGION_ORDER:
            rows = [row for row in provinces if row['region'] == key]
            if not rows:
                continue
            regions.append({
                'id': key, 'name': REGION_LABEL[key],
                'provinces': len(rows),
                'cities': sum(row['cities'] for row in rows),
                'airports': sum(row['airports'] for row in rows),
                'corridors': sum(row['corridors'] for row in rows),
                'stations': sum(row['stations'] + row.get('modelStations', 0) for row in rows),
                'operational': sum(1 for row in rows if row['state'] == 'operational'),
                'pending': sum(1 for row in rows if row['state'] == 'pending'),
            })
        return {**base, 'level': 'nation', 'regions': regions, 'provinces': provinces,
                'nodes': nodes, 'corridors': corridors, 'stationPoints': stations,
                'view': {'bbox': _scope_bbox(names)},
                'summary': _summary(provinces, corridors, nodes, stations)}

    if level == 'region':
        key = ident if ident in REGION_ORDER else REGION_ORDER[0]
        rows = [row for row in provinces if row['region'] == key]
        scoped = {row['name'] for row in rows}
        corridors = _slice_corridors(scoped)
        nodes = _slice_nodes(scoped)
        scoped_stations = [point for point in stations if point['name'] in scoped]
        return {**base, 'region': {'id': key, 'name': REGION_LABEL[key]},
                'regions': [], 'provinces': rows, 'nodes': nodes,
                'corridors': corridors, 'stationPoints': scoped_stations,
                'view': {'bbox': _scope_bbox(list(scoped))},
                'summary': _summary(rows, corridors, nodes, scoped_stations)}

    if level == 'province':
        row = next((item for item in provinces if item['name'] == ident), None)
        if row is None:
            return {'status': 'NOT_FOUND', 'level': level, 'id': ident,
                    'note': '该省不在本次纳入范围（台湾、西藏、港澳不纳入）' if ident in EXCLUDED
                            else '没有这个省级单元'}
        cities = _cities_by_province().get(ident) or []
        corridors = _slice_corridors({ident})
        nodes = _slice_nodes({ident})
        city_rows = []
        for city in cities:
            links = [item for item in _corridor_rows()
                     if city['name'] in (item['fromName'], item['toName'])]
            city_rows.append({
                'name': city['name'], 'lon': city['lon'], 'lat': city['lat'],
                'airport': city.get('airport'), 'hasAirport': city['hasAirport'],
                'links': len(links),
                'feedTarget': None if city['hasAirport'] else next(
                    (item['toName'] if item['fromName'] == city['name'] else item['fromName']
                     for item in links if item.get('feed')), None),
            })
        city_rows.sort(key=lambda item: (not item['hasAirport'], -item['links'], item['name']))
        scoped_stations = [point for point in stations if point['name'] == ident]
        return {**base, 'region': {'id': row['region'], 'name': REGION_LABEL[row['region']]},
                'regions': [], 'provinces': [row], 'province': row,
                'cities': city_rows, 'nodes': nodes, 'corridors': corridors,
                'stationPoints': scoped_stations,
                'view': {'bbox': _scope_bbox([ident])},
                'summary': _summary([row], corridors, nodes, scoped_stations)}

    if level == 'city':
        city = next((item for item in _city_rows() if item['name'] == ident), None)
        if city is None:
            return {'status': 'NOT_FOUND', 'level': level, 'id': ident,
                    'note': '纳入范围内没有这个城市'}
        row = next((item for item in provinces if item['name'] == city['province']), None)
        corridors = _slice_corridors({city['province']}, city=ident)
        feed = [item for item in corridors if item.get('feed')]
        neighbours = sorted({item['toName'] if item['fromName'] == ident else item['fromName']
                             for item in corridors})
        neighbour_set = {ident} | set(neighbours)
        node_rows = [row for row in _city_rows()
                     if row['province'] == city['province'] and row['name'] in neighbour_set]
        detail = {
            'name': city['name'], 'province': city['province'], 'region': city['region'],
            'lon': city['lon'], 'lat': city['lat'],
            'adcode': city.get('adcode'), 'nodeName': city.get('nodeName'),
            'hasAirport': city['hasAirport'], 'airport': city.get('airport'),
            'coordSource': city.get('coordSource'),
            'links': len(corridors),
            'feedTarget': (feed[0]['toName'] if feed and feed[0]['fromName'] == ident
                           else (feed[0]['fromName'] if feed else None)),
            'neighbours': neighbours,
        }
        return {**base, 'regions': [], 'provinces': [row] if row else [], 'province': row,
                # 市层只画"自己 + 直接相邻"的节点，视野也收到这几个点上：
                # 否则整省会挤成一团，3 条航线看不出连到谁。
                'city': detail,
                'nodes': [{'name': row['name'], 'province': row['province'], 'lon': row['lon'],
                           'lat': row['lat'], 'hasAirport': row['hasAirport'],
                           'airport': row.get('airport'), 'capital': row.get('capital', False),
                           'rank': row.get('rank', 3)} for row in node_rows],
                'corridors': corridors,
                'stationPoints': [point for point in stations if point['name'] == city['province']],
                'view': {'bbox': _points_bbox([(row['lon'], row['lat']) for row in node_rows])},
                'summary': _summary([row] if row else [], corridors, [city], [])}

    return {'status': 'INVALID', 'level': level,
            'note': 'level 只能是 nation / region / province / city'}
