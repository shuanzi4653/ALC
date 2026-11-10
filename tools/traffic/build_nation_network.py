# -*- coding: utf-8 -*-
"""构建全国城市航线网（每市一个节点 + 机场接驳 + 收窄的跨省通道）。

规则（2026-11-10 用户口径）
--------------------------
1. **节点**：全国 30 个省级单元的全部地级单元（`data/traffic/cities-cn.json`，坐标来自 Wikidata）。
   **不含台湾、西藏、港澳** —— 不通航，不纳入。
2. **省内**：本省节点跑 Prim MST，保证「市市相连」。
3. **机场接驳**：没有机场的市**必须**有一条直连最近有机场城市的航线（`AIRPORT_FEED`），
   同时它照常在省内网里跑 —— 接驳是"多一条"，不是"替代"。
4. **跨省**：每省只连最近的 1–2 个省，用两省最近的城市对做通道（`CROSS`）。
5. 每条边用 `routing.route()`（A*，允许域 = 全国纳入省的并集）生成航路；
   直线可飞就如实标 `DIRECT`，绕不开就标 `STRAIGHT_FALLBACK`，不假装算出来了。

产物：`data/traffic/nation-network.json`（提交入库，运行期只读，不再现算 A*）。

    .venv/Scripts/python.exe tools/traffic/build_nation_network.py
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

from pyproj import Transformer  # noqa: E402
from shapely import make_valid  # noqa: E402
from shapely.geometry import LineString, shape  # noqa: E402
from shapely.ops import transform as shapely_transform, unary_union  # noqa: E402

from traffic.routing import route  # noqa: E402

CITY_FILE = ROOT / 'data' / 'traffic' / 'cities-cn.json'
AIRPORT_FILE = ROOT / 'data' / 'traffic' / 'airports-cn.json'
OUT = ROOT / 'data' / 'traffic' / 'nation-network.json'

# 全国用 AEQD：中心 35°N / 105°E。单点等距方位投影，边缘有畸变，但只用于"路径形状 + 是否越界"，
# 里程一律用 haversine 算真实公里数。
PROJ = '+proj=aeqd +lat_0=35 +lon_0=105 +datum=WGS84 +units=m'
FORWARD = Transformer.from_crs('EPSG:4326', PROJ, always_xy=True)
INVERSE = Transformer.from_crs(PROJ, 'EPSG:4326', always_xy=True)

CROSS_MAX = 2
SIMPLIFY_M = 6000.0
MAX_POINTS = 24


def project(lon, lat):
    return FORWARD.transform(lon, lat)


def unproject(point):
    return list(INVERSE.transform(point[0], point[1]))


def haversine(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def province_geometries(names: Iterable[str]):
    asset = ROOT / 'frontend' / 'src' / 'assets' / 'china.json'
    payload = json.loads(asset.read_text(encoding='utf-8'))
    wanted = set(names)
    parts = []
    for feature in payload.get('features') or []:
        name = (feature.get('properties') or {}).get('name')
        if name in wanted:
            parts.append(make_valid(shape(feature['geometry'])))
    merged = unary_union(parts)
    return shapely_transform(FORWARD.transform, merged)


def load_cities() -> List[Dict[str, Any]]:
    return [row for row in json.loads(CITY_FILE.read_text(encoding='utf-8'))['cities']
            if row.get('lon') is not None]


def mark_airports(cities: List[Dict[str, Any]]) -> int:
    payload = json.loads(AIRPORT_FILE.read_text(encoding='utf-8'))
    icao_by_city: Dict[str, str] = {}
    for station in payload.get('stationRows') or []:
        if station.get('city'):
            icao_by_city.setdefault(station['city'], station['icao'])
    count = 0
    for city in cities:
        icao = icao_by_city.get(city['name'])
        city['hasAirport'] = icao is not None
        city['station'] = icao
        if icao:
            count += 1
    return count


def _prim(points: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    if len(points) < 2:
        return []
    pairs = []
    for i, a in enumerate(points):
        for b in points[i + 1:]:
            pairs.append((haversine((a['lon'], a['lat']), (b['lon'], b['lat'])), a['name'], b['name']))
    pairs.sort()
    chosen: List[Tuple[str, str]] = []
    connected = {points[0]['name']}
    while len(connected) < len(points):
        best = next(((d, a, b) for d, a, b in pairs if (a in connected) != (b in connected)), None)
        if best is None:
            break
        chosen.append((best[1], best[2]))
        connected.update((best[1], best[2]))
    return chosen


def _province_mst(by_province: Dict[str, List[Dict[str, Any]]]) -> List[Tuple[str, str, float]]:
    """省级最小生成树：点 = 省，边权 = 两省最近城市对的距离。返回 (省A, 省B, 距离)。"""
    names = sorted(by_province)
    best: Dict[Tuple[str, str], Tuple[float, str, str]] = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            distance, ca, cb = min(((haversine((x['lon'], x['lat']), (y['lon'], y['lat'])), x, y)
                                    for x in by_province[a] for y in by_province[b]),
                                   key=lambda item: item[0])
            best[(a, b)] = (distance, ca['name'], cb['name'])
    chosen = []
    connected = {names[0]}
    while len(connected) < len(names):
        candidate = None
        for (a, b), (distance, _, _) in best.items():
            if (a in connected) == (b in connected):
                continue
            if candidate is None or distance < candidate[0]:
                candidate = (distance, a, b)
        if candidate is None:
            break
        distance, a, b = candidate
        connected.update((a, b))
        chosen.append((a, b, distance))
    return chosen


def plan_edges(cities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    index = {city['name']: city for city in cities}
    by_province: Dict[str, List[Dict[str, Any]]] = {}
    for city in cities:
        by_province.setdefault(city['province'], []).append(city)

    edges: Dict[frozenset, Dict[str, Any]] = {}

    def add(a: str, b: str, *, feed: bool = False, cross: bool = False) -> None:
        if a == b:
            return
        key = frozenset((a, b))
        edge = edges.get(key)
        if edge is None:
            edge = {'a': a, 'b': b, 'feed': False, 'cross': False}
            edges[key] = edge
        # 标记叠加：同一条线既可能是接驳、也可能是跨省，不互相覆盖（否则"无机场市必须有接驳"会被抹掉）
        edge['feed'] = edge['feed'] or feed
        edge['cross'] = edge['cross'] or cross

    # ① 省内 MST：市市相连
    for province, rows in by_province.items():
        for a, b in _prim(rows):
            add(a, b)

    # ② 无机场市 → 最近机场城市（叠加一条，不替代省内网）
    airports = [city for city in cities if city['hasAirport']]
    for city in cities:
        if city['hasAirport'] or not airports:
            continue
        nearest = min(airports, key=lambda item: haversine((city['lon'], city['lat']), (item['lon'], item['lat'])))
        add(city['name'], nearest['name'], feed=True)

    # ③ 跨省：省级 MST（保证连通且总长度最短）+ 每省再补一条最近邻（够用即止）
    for province_a, province_b, _distance in _province_mst(by_province):
        pair = best_pair(by_province, province_a, province_b)
        add(pair[0], pair[1], cross=True)
    for province in sorted(by_province):
        nearest = None
        for other in sorted(by_province):
            if other == province:
                continue
            distance, a, b = best_pair(by_province, province, other, with_distance=True)
            if nearest is None or distance < nearest[0]:
                nearest = (distance, a, b)
        if nearest is not None:
            add(nearest[1], nearest[2], cross=True)

    # ④ 收口：任何"一条跨省通道都没有"的省，补一条到最近邻省的通道（连通性优先）
    have_cross = set()
    for edge in edges.values():
        if edge['cross']:
            have_cross.update((index[edge['a']]['province'], index[edge['b']]['province']))
    for province in sorted(by_province):
        if province in have_cross:
            continue
        nearest = None
        for other in sorted(by_province):
            if other == province:
                continue
            distance, a, b = best_pair(by_province, province, other, with_distance=True)
            if nearest is None or distance < nearest[0]:
                nearest = (distance, a, b)
        if nearest is not None:
            add(nearest[1], nearest[2], cross=True)

    rows = []
    for edge in edges.values():
        a, b = index[edge['a']], index[edge['b']]
        # 跨省通道优先标记：同一条线若既是接驳又是跨省，按"跨省通道"显示，
        # `feed` 标志仍为 true，判据与界面都读标志，不靠 kind 猜。
        kind = 'CROSS' if edge['cross'] else ('AIRPORT_FEED' if edge['feed'] else 'INTRA')
        rows.append({'from': edge['a'], 'to': edge['b'], 'kind': kind,
                     'feed': edge['feed'], 'cross': edge['cross'],
                     'fromProvince': a['province'], 'toProvince': b['province'],
                     'lengthKm': round(haversine((a['lon'], a['lat']), (b['lon'], b['lat'])), 1)})
    rows.sort(key=lambda row: (row['kind'], row['from'], row['to']))
    return rows


def best_pair(by_province, a: str, b: str, with_distance: bool = False):
    distance, ca, cb = min(((haversine((x['lon'], x['lat']), (y['lon'], y['lat'])), x, y)
                            for x in by_province[a] for y in by_province[b]),
                           key=lambda item: item[0])
    return (distance, ca['name'], cb['name']) if with_distance else (ca['name'], cb['name'])


def build_geometry(edge: Dict[str, Any], cities: Dict[str, Dict[str, Any]], allowed) -> Dict[str, Any]:
    a, b = cities[edge['from']], cities[edge['to']]
    start, end = project(a['lon'], a['lat']), project(b['lon'], b['lat'])
    distance = math.dist(start, end)
    step = max(2000.0, min(15000.0, distance / 80.0))
    checks = 80000 if distance > 600000 else 25000
    path = route(start, end, allowed, None, step_m=step, max_checks=checks)
    if path and len(path) >= 2:
        line = LineString(path).simplify(SIMPLIFY_M, preserve_topology=False)
        coords = list(line.coords)
        if len(coords) > MAX_POINTS:
            stride = math.ceil(len(coords) / MAX_POINTS)
            coords = coords[::stride] + [coords[-1]]
        lonlat = [[round(x, 4), round(y, 4)] for x, y in (unproject((px, py)) for px, py in coords)]
        return {'path': lonlat, 'geometry': 'DIRECT' if len(coords) == 2 else 'ASTAR'}
    return {'path': [[a['lon'], a['lat']], [b['lon'], b['lat']]], 'geometry': 'STRAIGHT_FALLBACK'}


def main() -> int:
    started = time.time()
    cities = load_cities()
    airports = mark_airports(cities)
    provinces = sorted({city['province'] for city in cities})
    print(f'节点 {len(cities)} / {len(provinces)} 省，有机场 {airports}，无机场 {len(cities) - airports}', flush=True)
    edges = plan_edges(cities)
    kinds: Dict[str, int] = {}
    for edge in edges:
        kinds[edge['kind']] = kinds.get(edge['kind'], 0) + 1
    print(f'边 {len(edges)}：{kinds}', flush=True)

    allowed = province_geometries(provinces)
    index = {city['name']: city for city in cities}
    corridors = []
    for order, edge in enumerate(edges, start=1):
        geo = build_geometry(edge, index, allowed)
        corridors.append({
            'id': f'NC-{order:04d}',
            'fromName': edge['from'], 'toName': edge['to'],
            'fromProvince': edge['fromProvince'], 'toProvince': edge['toProvince'],
            'kind': edge['kind'], 'feed': edge['feed'], 'cross': edge['cross'],
            'lengthKm': edge['lengthKm'],
            'fromLonLat': [index[edge['from']]['lon'], index[edge['from']]['lat']],
            'toLonLat': [index[edge['to']]['lon'], index[edge['to']]['lat']],
            'path': geo['path'], 'geometry': geo['geometry'], 'source': 'SIM',
        })
        if order % 100 == 0:
            print(f'  航路 {order}/{len(edges)} · {time.time() - started:.0f}s', flush=True)

    fallback = sum(1 for row in corridors if row['geometry'] == 'STRAIGHT_FALLBACK')
    payload = {
        'source': 'SIM（AEQD 35N/105E + A*；省界来自 frontend/src/assets/china.json）',
        'rule': '省内 MST（市市相连）+ 无机场市机场接驳（叠加，不替代）+ 省级 MST 跨省通道（每省 1–2 条最近邻）',
        'excluded': ['台湾省', '西藏自治区', '香港特别行政区', '澳门特别行政区'],
        'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'counts': {'cities': len(cities), 'provinces': len(provinces), 'airports': airports,
                   'corridors': len(corridors), 'fallback': fallback, 'byKind': kinds},
        'nodes': [{key: city.get(key) for key in
                   ('name', 'province', 'region', 'adcode', 'lon', 'lat', 'hasAirport', 'station',
                    'nodeName', 'coordSource')} for city in cities],
        'corridors': corridors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'写入 {OUT}（{OUT.stat().st_size/1024:.0f} KB），用时 {time.time() - started:.0f}s，直线兜底 {fallback}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
