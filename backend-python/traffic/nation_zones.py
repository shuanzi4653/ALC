"""全国机场净空（DERIVED）：规则化几何 + 穿越统计 + 指标。

为什么要单独一个模块，而不是改 `zones.py`：
`zones.py` 管的是**东北 69 个站点的法定管制区**（`fixed-zones.json`，每条带法定依据，
标 `OFFICIAL`）。那一套不能动，也不能和规则化出来的圈混在一起计数。

本模块只做 v3 §3 要求的那一层：把 287 个机场按公开等级与跑道方位**规则化**成
限制区 / 巡视区 / 净空区，全部标 `DERIVED`，界面上必须写"非官方公布"。

四层几何（v3 §3.2）：

| 层 | 几何 | 半径/尺寸 | 来源 |
|---|---|---|---|
| 限制区（运输） | 圆 | R = 8 km | DERIVED |
| 限制区（通用/支线） | 圆 | R = 5 km | DERIVED |
| 跑道净空区 | 两端延长梯形 | 长 10 km，半宽 1.5→3 km | DERIVED（**仅 10 站有跑道方位**） |
| 巡视区 | 圆 | R = 2 km | DERIVED |

纪律（硬）：`OFFICIAL` 与 `DERIVED` 永远分开计数、分开上色、分开展示。
"""

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / 'data' / 'traffic' / 'airports-cn-full.json'

PROJECTION = '+proj=aeqd +lat_0=35 +lon_0=105 +datum=WGS84 +units=m'
FWD = Transformer.from_crs('EPSG:4326', PROJECTION, always_xy=True)
INV = Transformer.from_crs(PROJECTION, 'EPSG:4326', always_xy=True)

# 半径按机场等级。数值取自 v3 §3.2，是**工程取值**，不是任何一部规章的原文。
LIMIT_RADIUS_M = {'TRANSPORT': 8000.0, 'REGIONAL': 5000.0}
PATROL_RADIUS_M = 2000.0
RUNWAY_BEYOND_M = 10000.0        # 跑道端向外延长
RUNWAY_HALF_WIDTH_START_M = 1500.0
RUNWAY_HALF_WIDTH_END_M = 3000.0
CIRCLE_POINTS = 28

# 陆地面积，只用来算"净空覆盖占比"这一个比率。
LAND_AREA_SQ_KM = 9_600_000.0


@lru_cache(maxsize=1)
def _sites() -> List[Dict[str, Any]]:
    try:
        payload = json.loads(DATA_FILE.read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001 - 数据缺失时整层不可用，不阻断其它页面
        return []
    return payload.get('sites') or []


def available() -> bool:
    return bool(_sites())


def _circle(cx: float, cy: float, radius: float) -> Polygon:
    points = [
        (cx + radius * math.cos(2 * math.pi * i / CIRCLE_POINTS),
         cy + radius * math.sin(2 * math.pi * i / CIRCLE_POINTS))
        for i in range(CIRCLE_POINTS)
    ]
    return Polygon(points)


def _runway_polygon(cx: float, cy: float, heading_deg: float, length_m: float) -> Polygon:
    """跑道两端各向外延长 10 km 的梯形，半宽 1.5→3 km。

    航向是罗盘角（0=北、90=东），转到数学坐标要 `90-heading`。
    没有跑道方位的机场**不生成这一层** —— 用假方位画出来的喇叭口
    比没有更糟：它会让"绕开跑道端头"这句话失真。
    """
    angle = math.radians(90.0 - float(heading_deg))
    ux, uy = math.cos(angle), math.sin(angle)
    nx, ny = -uy, ux
    half = max(float(length_m), 1200.0) / 2.0
    near = -half - RUNWAY_BEYOND_M
    far = half + RUNWAY_BEYOND_M
    points = [
        (cx + ux * near + nx * RUNWAY_HALF_WIDTH_START_M, cy + uy * near + ny * RUNWAY_HALF_WIDTH_START_M),
        (cx + ux * near - nx * RUNWAY_HALF_WIDTH_START_M, cy + uy * near - ny * RUNWAY_HALF_WIDTH_START_M),
        (cx + ux * far - nx * RUNWAY_HALF_WIDTH_END_M, cy + uy * far - ny * RUNWAY_HALF_WIDTH_END_M),
        (cx + ux * far + nx * RUNWAY_HALF_WIDTH_END_M, cy + uy * far + ny * RUNWAY_HALF_WIDTH_END_M),
    ]
    return Polygon(points)


def _ring(polygon: Polygon, simplify: float = 0.02) -> List[List[float]]:
    simple = polygon.simplify(simplify, preserve_topology=True)
    coords = list(simple.exterior.coords)
    return [[round(lon, 4), round(lat, 4)] for lon, lat in (INV.transform(x, y) for x, y in coords)]


def _without_ring(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in row.items() if key != 'ring'}


@lru_cache(maxsize=1)
def _built() -> Dict[str, Any]:
    """建一次几何，缓存。287 个圆 + 10 个梯形，毫秒级。"""
    sites = _sites()
    limit_rows: List[Dict[str, Any]] = []
    patrol_rows: List[Dict[str, Any]] = []
    runway_rows: List[Dict[str, Any]] = []
    limit_shapes: List[Polygon] = []
    runway_shapes: List[Polygon] = []
    for site in sites:
        try:
            cx, cy = FWD.transform(site['lon'], site['lat'])
        except Exception:  # noqa: BLE001
            continue
        radius = LIMIT_RADIUS_M.get(site.get('kind') or '', 5000.0)
        circle = _circle(cx, cy, radius)
        limit_shapes.append(circle)
        limit_rows.append({
            'id': f"NZ-LIMIT-{site['ident']}", 'ident': site['ident'],
            'name': site.get('name') or site['ident'],
            'icao': site.get('icao'), 'iata': site.get('iata'),
            'level': 'LIMIT', 'kind': site.get('kind'),
            'radiusKm': round(radius / 1000.0, 1),
            # 规则化的默认等级：可申请穿越。演示时可整体切到 PROHIBITED。
            'enforcement': 'APPROVAL_REQUIRED',
            'source': 'DERIVED', 'ring': _ring(circle),
        })
        patrol = _circle(cx, cy, PATROL_RADIUS_M)
        patrol_rows.append({
            'id': f"NZ-PATROL-{site['ident']}", 'ident': site['ident'],
            'name': site.get('name') or site['ident'], 'level': 'PATROL',
            'radiusKm': round(PATROL_RADIUS_M / 1000.0, 1),
            'enforcement': 'APPROVAL_REQUIRED', 'source': 'DERIVED',
            'ring': _ring(patrol),
        })
        for index, runway in enumerate(site.get('runways') or []):
            shape = _runway_polygon(cx, cy, runway['heading'], runway['lengthM'])
            runway_shapes.append(shape)
            runway_rows.append({
                'id': f"NZ-RWY-{site['ident']}-{index}", 'ident': site['ident'],
                'name': site.get('name') or site['ident'], 'level': 'RUNWAY',
                'heading': runway['heading'], 'lengthM': runway['lengthM'],
                'beyondKm': round(RUNWAY_BEYOND_M / 1000.0, 1),
                'enforcement': 'APPROVAL_REQUIRED', 'source': 'DERIVED',
                'ring': _ring(shape),
            })
    return {
        'limit': limit_rows, 'patrol': patrol_rows, 'runway': runway_rows,
        'limitShapes': limit_shapes, 'runwayShapes': runway_shapes,
    }


def summary(policy: str = 'APPROVAL_REQUIRED') -> Dict[str, Any]:
    """只回计数与口径，**不回几何**。

    287 个 28 点环塞进主载荷会多出 250 KB —— 而首页根本不用它们，
    只有切到「净空图层」或「空域情报」时才需要。几何走独立接口按需取。
    """
    built = _built()
    sites = _sites()
    strict = str(policy).upper() == 'PROHIBITED'
    total_area_km2 = sum(math.pi * (LIMIT_RADIUS_M.get(s.get('kind') or '', 5000.0) / 1000.0) ** 2
                         for s in sites)
    return {
        'available': bool(sites),
        'source': 'DERIVED',
        'policy': 'PROHIBITED' if strict else 'APPROVAL_REQUIRED',
        'note': ('按公开跑道方位与机场等级规则化生成，非官方公布；'
                 '与东北 69 站点的法定管制区（OFFICIAL）分开计数，不合并。'),
        'counts': {
            'airports': len(sites),
            'withRunway': len({row['ident'] for row in built['runway']}),
            'limitZones': len(built['limit']),
            'patrolZones': len(built['patrol']),
            'runwayZones': len(built['runway']),
            'coverageSqKm': round(total_area_km2),
            'coverageRatio': round(total_area_km2 / LAND_AREA_SQ_KM, 6),
        },
    }


def payload(policy: str = 'APPROVAL_REQUIRED') -> Dict[str, Any]:
    """净空层载荷：环 + 计数 + 口径说明。

    `policy` 可整体切到 `PROHIBITED`（演示用），此时所有限制区标为"一律禁止进入"，
    计数与等级一起变 —— 切换本身就是一个可演示的动作。
    """
    built = _built()
    strict = str(policy).upper() == 'PROHIBITED'
    enforcement = 'PROHIBITED' if strict else 'APPROVAL_REQUIRED'

    def decorate(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for row in rows:
            item = dict(row)
            item['enforcement'] = enforcement
            out.append(item)
        return out

    limit = decorate(built['limit'])
    runway = decorate(built['runway'])
    sites = _sites()
    total_area_km2 = sum(math.pi * (LIMIT_RADIUS_M.get(s.get('kind') or '', 5000.0) / 1000.0) ** 2
                         for s in sites)
    return {
        'available': bool(sites),
        'source': 'DERIVED',
        'policy': enforcement,
        'note': ('按公开跑道方位与机场等级规则化生成，非官方公布；'
                 '与东北 69 站点的法定管制区（OFFICIAL）分开计数，不合并。'),
        'counts': {
            'airports': len(sites),
            'withRunway': len({row['ident'] for row in runway}),
            'limitZones': len(limit),
            'patrolZones': len(built['patrol']),
            'runwayZones': len(runway),
            'coverageSqKm': round(total_area_km2),
            'coverageRatio': round(total_area_km2 / LAND_AREA_SQ_KM, 6),
        },
        'bands': {'LIMIT': [row['ring'] for row in limit],
                  'RUNWAY': [row['ring'] for row in runway]},
        # rows 只给元数据，**不再重复带 ring** —— 几何已经在 bands 里，
        # 两边都发等于把 287 个环传两遍，载荷白涨一倍。
        'rows': [_without_ring(row) for row in limit[:400]],
        'runwayRows': [_without_ring(row) for row in runway[:80]],
    }


@lru_cache(maxsize=8)
def crossings(stamp: str, policy: str = 'APPROVAL_REQUIRED') -> Dict[str, Any]:
    """航线 × 净空区的穿越统计。

    `stamp` 只是缓存键（网络生成时间）；几何本身来自本模块。
    用 STRtree 索引 287 个限制区，492 条航线一次性查完，
    不逐对求交（那是 14 万次，慢且没必要）。
    """
    built = _built()
    shapes = built['limitShapes']
    if not shapes:
        return {'available': False, 'corridors': 0, 'hit': 0, 'rows': [], 'note': '净空数据未接入'}

    from . import nation as nation_mod

    sites_meta = [row for row in built['limit']]
    tree = STRtree(shapes)
    rows: List[Dict[str, Any]] = []
    hit_count = 0
    for corridor in nation_mod._corridor_rows():
        path = corridor.get('path') or [corridor['fromLonLat'], corridor['toLonLat']]
        if len(path) < 2:
            continue
        try:
            line = LineString([FWD.transform(lon, lat) for lon, lat in path])
        except Exception:  # noqa: BLE001
            continue
        indexes = tree.query(line)
        touched = []
        for index in indexes:
            shape = shapes[int(index)]
            if shape.intersects(line):
                meta = sites_meta[int(index)]
                touched.append({'ident': meta['ident'], 'name': meta['name'],
                                'radiusKm': meta['radiusKm']})
        if touched:
            hit_count += 1
            rows.append({
                'id': corridor['id'],
                'place': f"{corridor['fromName']} → {corridor['toName']}",
                'province': corridor['fromProvince'],
                'crossings': len(touched),
                'airports': [f"{t['name']}（{t['radiusKm']} km）" for t in touched[:4]],
                'policy': 'APPROVAL_REQUIRED' if str(policy).upper() != 'PROHIBITED' else 'PROHIBITED',
            })
    rows.sort(key=lambda row: -row['crossings'])
    return {
        'available': True,
        'policy': 'PROHIBITED' if str(policy).upper() == 'PROHIBITED' else 'APPROVAL_REQUIRED',
        'corridors': len(nation_mod._corridor_rows()),
        'hit': hit_count,
        'ratio': round(hit_count / max(1, len(nation_mod._corridor_rows())), 3),
        'rows': rows[:120],
        'note': ('按规则化限制区（DERIVED）与航路求交；'
                 '默认等级 APPROVAL_REQUIRED 表示"可申请穿越"，不是禁飞。'),
    }
