# -*- coding: utf-8 -*-
"""通用航线网络构建（任意省集合 → 城市节点 + A* 干线）。

为什么要这一层
--------------
原来的 53 条城际走廊是写死在东北三省目录里的（`data/traffic/*.json` + `service.network()`），
扩到华北/西北就得再抄一遍。这里把"给定一组省 → 生成可跑的网络"抽出来：

    nodes(provinces) → 两两配对 → routing.route(..., boundary(省集合)) → 干线

- 节点来自**真实坐标**：省会（底图 `center`）+ 该省已接入的 METAR 站所在城市；
- 省界来自 `weather.geometry.boundary()`，与运行计划同源；
- 东北三省**不经过这里**：那 53 条仍走 `service.network()`，保证 2848/8/320 一个数都不动。

投影：沿用项目单点 AEQD（`weather.geometry.project`）。北方范围比全国小一个量级，
边缘畸变仍在可用范围内；返回值里带 `projection` 说明，别当成等距图用。
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform, unary_union

from .routing import route

# 北方专用 AEQD：中心 41°N/110°E。**不复用** weather.geometry 的那套（中心在 126°E，
# 是给东北三省用的）——把它套到新疆会有上千公里的方位畸变。
PROJ_STRING = '+proj=aeqd +lat_0=41 +lon_0=110 +datum=WGS84 +units=m'
FORWARD = Transformer.from_crs('EPSG:4326', PROJ_STRING, always_xy=True)
INVERSE = Transformer.from_crs(PROJ_STRING, 'EPSG:4326', always_xy=True)


def project(lon, lat):
    return FORWARD.transform(lon, lat)


def unproject(point):
    return list(INVERSE.transform(point[0], point[1]))


@lru_cache(maxsize=1)
def _province_geometries() -> Dict[str, Any]:
    payload = json.loads(ASSET_PATH.read_text(encoding='utf-8'))
    out: Dict[str, Any] = {}
    for feature in payload.get('features') or []:
        props = feature.get('properties') or {}
        name, geometry = props.get('name'), feature.get('geometry')
        if not name or not geometry:
            continue
        out[name] = make_valid(shape(geometry))
    return out


@lru_cache(maxsize=4)
def north_boundary(names: Tuple[str, ...]):
    geometries = _province_geometries()
    parts = [geometries[name] for name in names if name in geometries]
    if not parts:
        raise ValueError('Unknown region')
    merged = unary_union(parts)
    return shapely_transform(FORWARD.transform, merged)

ASSET_PATH = Path(__file__).resolve().parents[2] / 'frontend' / 'src' / 'assets' / 'china.json'

NORTH_REGIONS = ('northeast', 'north', 'northwest', 'xinjiang')
NORTHEAST = ('辽宁省', '吉林省', '黑龙江省')


def _haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


@lru_cache(maxsize=1)
def province_centers() -> Dict[str, Dict[str, Any]]:
    payload = json.loads(ASSET_PATH.read_text(encoding='utf-8'))
    out: Dict[str, Dict[str, Any]] = {}
    for feature in payload.get('features') or []:
        props = feature.get('properties') or {}
        name = props.get('name')
        centre = props.get('center') or props.get('centroid')
        if not name or not centre:
            continue
        out[name] = {'name': name, 'lon': round(float(centre[0]), 4),
                     'lat': round(float(centre[1]), 4)}
    return out


def regions_of(names: Iterable[str]) -> List[str]:
    from . import national as national_mod
    table = {row['name']: row['region'] for row in national_mod.provinces()}
    return sorted({table.get(name, 'other') for name in names})


def nodes(provinces: Iterable[str]) -> List[Dict[str, Any]]:
    """省集合 → 城市节点（省会 + 已接入报文站所在城市），按坐标去重。"""
    wanted = set(provinces)
    centers = province_centers()
    out: List[Dict[str, Any]] = []
    seen = set()
    for name in sorted(wanted):
        centre = centers.get(name)
        if centre is None:
            continue
        key = (round(centre['lon'], 2), round(centre['lat'], 2))
        if key not in seen:
            seen.add(key)
            out.append({'name': name, 'province': name, 'lon': centre['lon'],
                        'lat': centre['lat'], 'source': 'CAPITAL'})
    return out


def _allowed(provinces: Iterable[str]):
    names = tuple(sorted(provinces))
    return north_boundary(names) if names else None


def link(points: List[Dict[str, Any]], *, per_node: int = 2,
         max_km: float = 2200.0) -> List[Dict[str, Any]]:
    """MST + 就近补边，每条边跑一次 A*（失败则退化为直线并标注）。"""
    if len(points) < 2:
        return []
    provinces = sorted({point['province'] for point in points})
    allowed = _allowed(provinces)
    index = {point['name']: point for point in points}
    pairs: List[Tuple[float, str, str]] = []
    for i, first in enumerate(points):
        for second in points[i + 1:]:
            distance = _haversine_km((first['lon'], first['lat']), (second['lon'], second['lat']))
            if distance <= max_km:
                pairs.append((distance, first['name'], second['name']))
    pairs.sort()

    # Prim MST
    chosen: List[Tuple[float, str, str]] = []
    connected = {points[0]['name']}
    while len(connected) < len(points):
        best = None
        for distance, a, b in pairs:
            if (a in connected) == (b in connected):
                continue
            if best is None or distance < best[0]:
                best = (distance, a, b)
        if best is None:
            break
        chosen.append(best)
        connected.update((best[1], best[2]))
    have = {frozenset((a, b)) for _, a, b in chosen}
    for point in points:
        near = sorted((d, a, b) for d, a, b in pairs
                      if point['name'] in (a, b))[:per_node]
        for distance, a, b in near:
            key = frozenset((a, b))
            if key in have:
                continue
            have.add(key)
            chosen.append((distance, a, b))

    rows: List[Dict[str, Any]] = []
    for order, (distance, a, b) in enumerate(sorted(chosen), start=1):
        first, second = index[a], index[b]
        start_xy = project(first['lon'], first['lat'])
        end_xy = project(second['lon'], second['lat'])
        path = route(start_xy, end_xy, allowed) if allowed is not None else None
        if path and len(path) >= 2:
            lonlat = [list(unproject((x, y))) for x, y in path]
            geometry_source = 'ASTAR'
        else:
            lonlat = [[first['lon'], first['lat']], [second['lon'], second['lat']]]
            geometry_source = 'STRAIGHT_FALLBACK'
        rows.append({
            'id': f'TRK-{order:03d}',
            'from': first['province'], 'to': second['province'],
            'fromName': first['name'], 'toName': second['name'],
            'lengthKm': round(distance, 1),
            'fromLonLat': [first['lon'], first['lat']],
            'toLonLat': [second['lon'], second['lat']],
            'path': lonlat,
            'source': 'SIM',
            'geometry': geometry_source,
        })
    return rows


@lru_cache(maxsize=4)
def build(provinces: Tuple[str, ...]) -> Dict[str, Any]:
    """给定省集合构建网络。东北三省请继续用 `service.network()`，不要走这里。"""
    keys = tuple(sorted(provinces))
    points = nodes(keys)
    rows = link(points)
    return {
        'provinces': list(keys),
        'regions': regions_of(keys),
        'nodes': points,
        'corridors': rows,
        'astar': sum(1 for row in rows if row['geometry'] == 'ASTAR'),
        'fallback': sum(1 for row in rows if row['geometry'] != 'ASTAR'),
        'projection': 'AEQD（单点等距方位投影，非等距图；北方范围内可用）',
    }
