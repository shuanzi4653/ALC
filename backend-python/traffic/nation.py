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
from . import nation_ops

ROOT = Path(__file__).resolve().parents[2]

# 与 build_nation_network 相同的投影，用于把回波与航路放到同一平面做绕飞
AEQD = '+proj=aeqd +lat_0=35 +lon_0=105 +datum=WGS84 +units=m'
_TO_XY = None
_TO_LL = None


def _xy_transformer():
    global _TO_XY
    if _TO_XY is None:
        from pyproj import Transformer
        _TO_XY = Transformer.from_crs('EPSG:4326', AEQD, always_xy=True)
    return _TO_XY


def _ll_transformer():
    global _TO_LL
    if _TO_LL is None:
        from pyproj import Transformer
        _TO_LL = Transformer.from_crs(AEQD, 'EPSG:4326', always_xy=True)
    return _TO_LL
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
    # 纳入范围**以路网节点为准**：边境 50 km 内退出的城市在建网时已连同航线一起删除，
    # 这里再按节点名单过一遍，避免"城市还在、航线没了"的半拉子状态。
    allowed = {row['name'] for row in _network().get('nodes') or []}
    rows = [row for row in _cities_doc()['cities']
            if row.get('lon') is not None and (not allowed or row['name'] in allowed)]
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


def _city_weather() -> Dict[str, Dict[str, Any]]:
    """逐市气象（open-meteo 公开接口，免密钥）。取不到的城市就是没有，不补零。"""
    try:
        from weather import city_weather
        payload = city_weather.fetch([(row['name'], row['lat'], row['lon']) for row in _city_rows()])
        return payload.get('cities') or {}
    except Exception:  # noqa: BLE001 - 气象源不可用不能把页面打崩
        return {}


@lru_cache(maxsize=1)
def _corridor_rows() -> List[Dict[str, Any]]:
    return list(_network().get('corridors') or [])


@lru_cache(maxsize=1)
def _radar() -> Dict[str, Any]:
    try:
        from weather import radar_public
        return radar_public.fetch()
    except Exception as exc:  # noqa: BLE001
        return {'available': False, 'error': str(exc)[:80], 'bands': {}, 'counts': {}}


@lru_cache(maxsize=2)
def _china_mask():
    """国界并集（34 个省级单元），用来把回波裁到国内。跟建网工具用的是同一份区划。

    区划数据里有自相交的环（天津—河北那段著名的 `side location conflict`），
    直接 union 会抛拓扑异常，所以每个省先 make_valid 再并。
    """
    from shapely import make_valid
    from shapely.ops import unary_union
    shapes = []
    for geometry in _province_shapes().values():
        try:
            fixed = make_valid(geometry)
            if not fixed.is_empty:
                shapes.append(fixed)
        except Exception:  # noqa: BLE001
            continue
    return unary_union(shapes) if shapes else None


@lru_cache(maxsize=2)
def _radar_clipped(radar_ts: str) -> Dict[str, Any]:
    """回波只保留**国内**部分。

    为什么在数据层裁，而不是只在前端裁像素：一条发给前端的境外回波，
    既白占字节，也会被绕飞算法当成"要躲的东西"，等于在本国航路上按外国天气改航。
    裁完再算，逻辑和显示才对得上。
    """
    radar = _radar()
    mask = _china_mask()
    bands = (radar.get('bands') or {})
    if mask is None or not bands:
        return bands
    from shapely.geometry import Polygon
    out: Dict[str, List[List[List[float]]]] = {}
    for band, rings in bands.items():
        kept: List[List[List[float]]] = []
        for ring in rings or []:
            try:
                poly = Polygon(ring)
                if not poly.is_valid or poly.area <= 0:
                    continue
                piece = poly.intersection(mask)
                if piece.is_empty:
                    continue
                parts = getattr(piece, 'geoms', [piece])
                for part in parts:
                    if part.is_empty or part.area < 0.02:
                        continue
                    coords = [[round(x, 3), round(y, 3)] for x, y in part.exterior.coords]
                    if len(coords) >= 4:
                        kept.append(coords)
            except Exception:  # noqa: BLE001
                continue
        out[band] = kept[:45]
    return out


def _radar_polygons(bands: Dict[str, Any]):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    shapes = []
    for band in ('CONVECTIVE', 'STRONG'):
        for ring in (bands or {}).get(band) or []:
            try:
                poly = Polygon(ring)
                if poly.is_valid and poly.area > 0:
                    shapes.append(poly)
            except Exception:  # noqa: BLE001
                continue
    return unary_union(shapes) if shapes else None


def _detour_for(path: List[List[float]], avoid) -> Optional[Dict[str, Any]]:
    """走廊穿回波时**小绕一下**：把中点沿法线挪开，能避开就返回新路径。"""
    from shapely.geometry import LineString, Point
    to_xy, to_ll = _xy_transformer(), _ll_transformer()
    if avoid is None or len(path) < 2:
        return None
    pts = [to_xy.transform(lon, lat) for lon, lat in path]
    line = LineString(pts)
    if not line.intersects(avoid):
        return None
    hit = line.intersection(avoid)
    hit_m = max(3000.0, min(90000.0, hit.length))
    best = None
    for depth_m in (hit_m * 0.45 + 6000.0, hit_m * 0.75 + 8000.0, hit_m * 1.1 + 12000.0):
      for sign in (1, -1):
          a, b = pts[0], pts[-1]
          dx, dy = b[0] - a[0], b[1] - a[1]
          length = (dx * dx + dy * dy) ** 0.5 or 1.0
          nx, ny = -dy / length * sign, dx / length * sign
          shifted = LineString([a, (a[0] + dx / 2 + nx * depth_m, a[1] + dy / 2 + ny * depth_m), b])
          if shifted.intersects(avoid):
              continue
          cost = shifted.length - line.length
          if cost < 0 or cost > line.length * 0.4:
              continue
          if best is None or cost < best[0]:
              best = (cost, shifted)
    if best is None:
        return None
    _, shifted = best
    coords = [list(to_ll.transform(x, y)) for x, y in shifted.coords]
    return {'path': [[round(lon, 4), round(lat, 4)] for lon, lat in coords],
            'shiftKm': round(best[0] / 1000.0, 1),
            # 原航路落在回波里的长度（公里）：反事实要拿它算"不绕飞会暴露多久"
            'hitKm': round(hit.length / 1000.0, 1)}


@lru_cache(maxsize=2)
def _detour_table(radar_ts: str) -> Dict[str, Dict[str, Any]]:
    """按雷达帧缓存绕飞结果：一帧 10 分钟，不用每个请求重算 514 条。"""
    from shapely.ops import transform as shp_transform
    radar = _radar()
    avoid = _radar_polygons(_radar_clipped(radar.get('ts') or 'none'))
    if avoid is None:
        return {}
    # 回波多边形是经纬度，航路要投影到米制平面才能判交、才能算法线侧移
    avoid = shp_transform(_xy_transformer().transform, avoid)
    table: Dict[str, Dict[str, Any]] = {}
    for row in _corridor_rows():
        path = row.get('path') or [row['fromLonLat'], row['toLonLat']]
        got = _detour_for(path, avoid)
        if got:
            table[row['id']] = got
    return table


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
    weather = _city_weather()
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
            'weatherCities': sum(1 for item in cities if weather.get(item['name'])),
            'lowVisCities': sum(1 for item in cities if (weather.get(item['name']) or {}).get('low')),
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
            'bulge': row.get('bulge', 0.0),
            'borderDetour': bool(row.get('borderDetour')),
            'borderBlocked': bool(row.get('borderBlocked')),
            'lengthKm': row['lengthKm'], 'geometry': row['geometry'],
            'fromLonLat': row['fromLonLat'], 'toLonLat': row['toLonLat'],
        }
        path = row.get('path') or []
        if len(path) > 2:                 # 两点直飞不重复传 path，前端用两端点
            item['path'] = path
        out.append(item)
    return out


def _node(row: Dict[str, Any], weather: Dict[str, Dict[str, Any]],
          external: bool = False) -> Dict[str, Any]:
    raw = weather.get(row['name'])
    # 节点上只带"屏上要用的四个数"，源与时间戳放 summary，别在 330 个节点里重复 330 遍
    slim = None
    if raw:
        slim = {'tempC': None if raw.get('tempC') is None else round(raw['tempC'], 1),
                'windMps': raw.get('windMps'),
                'visM': None if raw.get('visM') is None else int(round(raw['visM'] / 100.0) * 100),
                'low': bool(raw.get('low'))}
    return {'name': row['name'], 'province': row['province'],
            'lon': row['lon'], 'lat': row['lat'],
            'hasAirport': row['hasAirport'], 'airport': row.get('airport'),
            'capital': row.get('capital', False), 'rank': row.get('rank', 3),
            'external': external,
            'weather': slim}


def _slice_nodes(provinces: set, city: Optional[str] = None) -> List[Dict[str, Any]]:
    weather = _city_weather()
    out = []
    for row in _city_rows():
        if row['province'] not in provinces:
            continue
        if city is not None and row['name'] != city:
            continue
        out.append(_node(row, weather))
    return out


def _external_nodes(corridors: List[Dict[str, Any]], scoped: set) -> List[Dict[str, Any]]:
    """跨省航线的**另一端**也要画出来 —— 否则屏上只有一条线伸出去，看不出"从哪飞到哪"。"""
    wanted = set()
    for row in corridors:
        if row['fromProvince'] not in scoped:
            wanted.add(row['fromName'])
        if row['toProvince'] not in scoped:
            wanted.add(row['toName'])
    if not wanted:
        return []
    weather = _city_weather()
    out = []
    for row in _city_rows():
        if row['name'] in wanted:
            out.append(_node(row, weather, external=True))
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
    local = [row for row in nodes if not row.get('external')]
    return {
        'provinces': len(provinces),
        'cities': len(local),
        'externals': len(nodes) - len(local),
        'airports': sum(1 for row in local if row['hasAirport']),
        'feedCities': sum(1 for row in local if not row['hasAirport']),
        'corridors': len(corridors),
        'byKind': by_kind,
        'weatherSource': 'open-meteo current（公开、免密钥，逐市）',
        'weatherCities': sum(1 for row in nodes if row.get('weather')),
        'lowVisCities': sum(1 for row in nodes if (row.get('weather') or {}).get('low')),
        'stations': len(stations),
        'stationsMetar': sum(1 for row in stations if row.get('source') != 'MODEL'),
        'stationsModel': sum(1 for row in stations if row.get('source') == 'MODEL'),
        'operational': sum(1 for row in provinces if row['state'] == 'operational'),
        'pending': sum(1 for row in provinces if row['state'] == 'pending'),
        # 边境退出通航：城市与航线一并删除，这里把被删的城市名与距离摊开，
        # 材料里要能一条条对上，不能只说"已处理"。
        'borderExcludeKm': _network().get('borderExcludeKm'),
        'borderExcludedCities': [row['name'] for row in _network().get('borderExcluded') or []],
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


def flights_payload(level: str = 'nation', ident: Optional[str] = None,
                    minute: int = 0) -> Dict[str, Any]:
    """只回航班与统计：时间轴每拖一次都要刷新，不能把整份网络重算一遍。"""
    minute = max(0, min(1440, int(minute or 0)))
    provinces = [row['name'] for row in _province_rows()]
    radar = _radar()
    table = _detour_table(radar.get('ts') or 'none') if radar.get('available') else {}
    if level == 'region':
        scoped = {row['name'] for row in _province_rows() if row['region'] == (ident or 'north')}
        corridors = _slice_corridors(scoped)
    elif level == 'province':
        corridors = _slice_corridors({ident or ''})
    elif level == 'city':
        corridors = _slice_corridors({''}, city=ident or '')
        if not corridors:
            city = next((item for item in _city_rows() if item['name'] == ident), None)
            if city:
                corridors = _slice_corridors({city['province']}, city=ident)
    else:
        corridors = _slice_corridors(set(provinces))
    flights = nation_ops.flight_objects(corridors, minute, table, _city_weather())
    by_province: Dict[str, Dict[str, int]] = {}
    by_city: Dict[str, Dict[str, int]] = {}
    for flight in flights:
        for table_, key in ((by_province, flight['fromProvince']), (by_city, flight['fromName'])):
            bucket = table_.setdefault(key, {'airborne': 0, 'delayed': 0, 'hold': 0})
            bucket['airborne'] += 1
            if flight['status'] == 'DELAYED':
                bucket['delayed'] += 1
            if flight['decision'] == 'HOLD':
                bucket['hold'] += 1
    return {
        'status': 'OK', 'level': level, 'id': ident, 'minute': minute,
        'radarTs': radar.get('ts'),
        'flights': flights,
        'byProvince': by_province,
        'byCity': by_city,
        'traffic': {'corridors': len(corridors), 'airborne': len(flights),
                    'delayed': sum(1 for row in flights if row['status'] == 'DELAYED'),
                    'hold': sum(1 for row in flights if row['decision'] == 'HOLD'),
                    'blocked': sum(1 for row in corridors if row.get('borderBlocked')),
                    'radarHitCorridors': sum(1 for row in corridors if table.get(row['id']))},
    }


def payload(level: str = 'nation', ident: Optional[str] = None,
            minute: int = 0) -> Dict[str, Any]:
    provinces = _province_rows()
    stations = _live_stations()
    base = _base(level, ident)
    names = [row['name'] for row in provinces]
    radar = _radar()
    table = _detour_table(radar.get('ts') or 'none') if radar.get('available') else {}
    minute = max(0, min(1440, int(minute or 0)))

    def attach(body: Dict[str, Any], corridors: List[Dict[str, Any]],
               cities: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        for row in corridors:
            got = table.get(row['id'])
            if got:
                row['detour'] = got          # 前端用它画绕飞后的实际航迹
        weather = _city_weather()
        flights = nation_ops.flight_objects(corridors, minute, table, weather)
        hit = sum(1 for row in corridors if row.get('detour'))
        delayed = sum(1 for row in flights if row['status'] == 'DELAYED')
        blocked = sum(1 for row in corridors if row.get('borderBlocked'))
        border_hit = sum(1 for row in corridors if row.get('borderDetour'))
        scoped_cities = cities if cities is not None else _city_rows()
        airport_by_city: Dict[str, Dict[str, Any]] = {}
        for station in _airports().get('stationRows') or []:
            if station.get('city'):
                airport_by_city.setdefault(station['city'], station)
        return {**body,
                'minute': minute,
                'radar': {'available': bool(radar.get('available')),
                          'ts': radar.get('ts'),
                          'source': radar.get('source'),
                          'counts': {band: len(rings) for band, rings
                                     in _radar_clipped(radar.get('ts') or 'none').items()},
                          'bands': _radar_clipped(radar.get('ts') or 'none'),
                          'coverage': radar.get('coverage'),
                          # 瓦片直链：前端按墨卡托贴图，边界比矢量多边形更像真实回波
                          'tiles': radar.get('tiles_url')},
                'clearanceNote': '许可要素由本班次已写定的计划字段组装，不重新计算；标“待批”的班次不进入在飞序列。',
                'flights': flights,
                'upcoming': nation_ops.upcoming(corridors, minute)[:90],
                'alerts': nation_ops.alerts(corridors, flights, weather, scoped_cities),
                'intel': nation_ops.intel(scoped_cities, weather, airport_by_city),
                'border': {**nation_ops.border_monitor(corridors, flights),
                           'excludeKm': _network().get('borderExcludeKm'),
                           'excludedCities': _network().get('borderExcluded') or []},
                'traffic': {'corridors': len(corridors), 'airborne': len(flights),
                            'delayed': delayed, 'radarHitCorridors': hit,
                            'blocked': blocked, 'borderDetourCorridors': border_hit,
                            'hold': sum(1 for row in flights if row['decision'] == 'HOLD'),
                            'lowVisCities': sum(1 for row in scoped_cities
                                                if (weather.get(row['name']) or {}).get('low')),
                            'detourShiftKm': round(sum(r['shiftKm'] for r in table.values()), 1)}}

    if level in ('nation', 'north'):
        corridors = _slice_corridors(set(names))
        nodes = _slice_nodes(set(names))
        scoped_cities = _city_rows()
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
        body = attach({**base, 'level': 'nation', 'regions': regions, 'provinces': provinces,
                       'nodes': nodes, 'corridors': corridors, 'stationPoints': stations,
                       'view': {'bbox': _scope_bbox(names)},
                       'summary': _summary(provinces, corridors, nodes, stations)}, corridors, scoped_cities)
        blocks = nation_ops.province_blocks(provinces, corridors, body['flights'])
        by_province = {row['name']: row for row in blocks}
        region_rows = []
        for key in REGION_ORDER:
            members = [row for row in provinces if row['region'] == key]
            if not members:
                continue
            names = {row['name'] for row in members}
            # 每个大区自己那一份航线：跨区通道会同时出现在两个区里，这是"本区涉及"，
            # 不是重复计数 —— 全国合计那一行仍然回原始列表数。
            scoped = [row for row in corridors
                      if row['fromProvince'] in names or row['toProvince'] in names]
            sub = [by_province[row['name']] for row in members if row['name'] in by_province]
            region_rows.append({'id': key, 'name': REGION_LABEL[key],
                                'total': _totals(sub, body['flights'], scoped),
                                'provinces': sub})
        body['rollup'] = {
            'level': 'nation',
            'total': _totals(blocks, body['flights'], corridors),
            'regions': region_rows,
        }
        return body

    if level == 'region':
        key = ident if ident in REGION_ORDER else REGION_ORDER[0]
        rows = [row for row in provinces if row['region'] == key]
        scoped = {row['name'] for row in rows}
        corridors = _slice_corridors(scoped)
        nodes = _slice_nodes(scoped)
        scoped_cities = [row for row in _city_rows() if row['province'] in scoped]
        scoped_stations = [point for point in stations if point['name'] in scoped]
        body = attach({**base, 'region': {'id': key, 'name': REGION_LABEL[key]},
                       'regions': [], 'provinces': rows, 'nodes': nodes,
                       'corridors': corridors, 'stationPoints': scoped_stations,
                       'view': {'bbox': _scope_bbox(list(scoped))},
                       'summary': _summary(rows, corridors, nodes, scoped_stations)}, corridors, scoped_cities)
        blocks = nation_ops.province_blocks(rows, corridors, body['flights'])
        body['rollup'] = {'level': 'region', 'total': _totals(blocks, body['flights'], corridors),
                          'provinces': blocks}
        return body

    if level == 'province':
        row = next((item for item in provinces if item['name'] == ident), None)
        if row is None:
            return {'status': 'NOT_FOUND', 'level': level, 'id': ident,
                    'note': '该省不在本次纳入范围（台湾、西藏、港澳不纳入）' if ident in EXCLUDED
                            else '没有这个省级单元'}
        cities = _cities_by_province().get(ident) or []
        corridors = _slice_corridors({ident})
        nodes = _slice_nodes({ident}) + _external_nodes(corridors, {ident})
        city_blocks = nation_ops.city_blocks(ident, cities, corridors, [])
        for item in city_blocks:
            item['feedTarget'] = None
        # 接驳目标：无机场城市那条 AIRPORT_FEED 的另一端
        for item in city_blocks:
            for link in corridors:
                if link.get('feed') and item['name'] in (link['fromName'], link['toName']):
                    item['feedTarget'] = (link['toName'] if link['fromName'] == item['name']
                                          else link['fromName'])
                    break
        scoped_cities = cities
        scoped_stations = [point for point in stations if point['name'] == ident]
        body = attach({**base, 'region': {'id': row['region'], 'name': REGION_LABEL[row['region']]},
                       'regions': [], 'provinces': [row], 'province': row,
                       'cities': city_blocks, 'nodes': nodes, 'corridors': corridors,
                       'stationPoints': scoped_stations,
                       'view': {'bbox': _points_bbox([(n['lon'], n['lat']) for n in nodes])},
                       'summary': _summary([row], corridors, nodes, scoped_stations)}, corridors, scoped_cities)
        blocks = nation_ops.city_blocks(ident, cities, corridors, body['flights'])
        for item, source in zip(blocks, city_blocks):
            item['feedTarget'] = source.get('feedTarget')
        body['rollup'] = {'level': 'province',
                          'total': _totals(nation_ops.province_blocks([row], corridors, body['flights']),
                                           body['flights'], corridors),
                          'cities': blocks}
        return body

    if level == 'city':
        city = next((item for item in _city_rows() if item['name'] == ident), None)
        if city is None:
            return {'status': 'NOT_FOUND', 'level': level, 'id': ident,
                    'note': '纳入范围内没有这个城市（边境 50 km 内的城市已整体退出通航）'}
        row = next((item for item in provinces if item['name'] == city['province']), None)
        corridors = _slice_corridors({city['province']}, city=ident)
        feed = [item for item in corridors if item.get('feed')]
        neighbours = sorted({item['toName'] if item['fromName'] == ident else item['fromName']
                             for item in corridors})
        neighbour_set = {ident} | set(neighbours)
        node_rows = [row for row in _city_rows() if row['name'] in neighbour_set]
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
        body = attach({**base, 'regions': [], 'provinces': [row] if row else [], 'province': row,
                       # 市层只画"自己 + 直接相邻"的节点，视野也收到这几个点上：
                       # 否则整省会挤成一团，3 条航线看不出连到谁。
                       'city': detail,
                       'nodes': [_node(row, _city_weather(),
                                       external=row['province'] != city['province']) for row in node_rows],
                       'corridors': corridors,
                       'stationPoints': [point for point in stations if point['name'] == city['province']],
                       'view': {'bbox': _points_bbox([(row['lon'], row['lat']) for row in node_rows])},
                       'summary': _summary([row] if row else [], corridors, [city], [])},
                      corridors, [city])
        one = nation_ops.city_blocks(city['province'], [city], corridors, body['flights'])
        body['rollup'] = {'level': 'city',
                          'total': _totals(nation_ops.province_blocks([row] if row else [], corridors,
                                                                      body['flights']),
                                           body['flights'], corridors),
                          'cities': one}
        body['city'] = {**detail, 'airborne': one[0]['airborne'] if one else 0,
                        'delayed': one[0]['delayed'] if one else 0}
        return body

    return {'status': 'INVALID', 'level': level,
            'note': 'level 只能是 nation / region / province / city'}


def _totals(blocks: List[Dict[str, Any]], flights: List[Dict[str, Any]],
            corridors: List[Dict[str, Any]]) -> Dict[str, Any]:
    """一个块自己的合计。

    **航线数不能把各省的块加起来**：一条跨省航线会同时出现在两个省里，
    累加就把 492 条算成 582 条（实测差 90）。所以航线/停飞/绕飞三项一律回原始列表数，
    只有"城市/在飞/异常"这类按归属唯一计的才相加。
    """
    return {
        'provinces': len({b.get('name') for b in blocks if b.get('region') is not None}) if blocks else 0,
        'cities': sum(int(b.get('cities') or 0) for b in blocks),
        'airports': sum(int(b.get('airports') or 0) for b in blocks),
        'corridors': len(corridors),
        'blocked': sum(1 for row in corridors if row.get('borderBlocked')),
        'detour': sum(1 for row in corridors if row.get('detour')),
        'airborne': sum(int(b.get('airborne') or 0) for b in blocks),
        'delayed': sum(int(b.get('delayed') or 0) for b in blocks),
        'hold': sum(int(b.get('hold') or 0) for b in blocks),
        'lowVisCities': sum(int(b.get('lowVisCities') or 0) for b in blocks),
    }
