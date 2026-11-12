# -*- coding: utf-8 -*-
"""全国航线网（四级：全国 → 大区 → 省 → 市）。

口径（2026-11-10 用户拍板）
--------------------------
- **范围**：全国 30 个省级单元。**不含台湾、西藏、港澳**（这两地不通航，不纳入网络）。
- **节点**：区划目录里 330 个地级单元，**中心点距境外不足 50 km 的 11 城整体退出通航**
  （节点与航线一并删除，不留半条），实际纳入 **319 个**（`data/traffic/cities-cn.json`，坐标来自 Wikidata）。
- **航线**：`data/traffic/nation-network.json`（`tools/traffic/build_nation_network.py` 离线生成）：
    ① 省内 MST，市市相连；
    ② **没有机场的市另有一条专用接驳**到最近有机场城市（`AIRPORT_FEED`）——
       接驳是"多一条"，省内网照常跑，不是替代；
    ③ 跨省收窄：每省只连最近 1–2 个省，用两省最近城市对做通道（`CROSS`）。
- **定位**：飞行汽车解决**城市间**交通；跨省长距离仍靠飞机与火车 ——
  这套网络是**分担**，不是**取代**，所以跨省只留少量通道，不做全国全互联。
- **机场**：`data/traffic/airports-cn.json`（站点总表，与此刻是否发报无关）。
- **实况**：open-meteo 逐市实况（公开、免密钥）为主，wttr.in 补缺；**不用 METAR 报文**
  （报文只覆盖几十个站，且冷启动要多花 10 秒）。取不到的城市如实标"无实况"，不补零。
- **规模（当前数据）**：30 省 / 319 市 / 56 个有机场的城市 / 492 条航线
  （省内 201 + 机场接驳 261 + 跨省 30）。四个数都从载荷 `summary` 读，不在文档里写死当结论。

四级走同一入口 `payload(level, id)`，逐级按需切片 —— 前端每下钻一次重新请求，
返回上级时把数据清掉，内存里不留整棵树。
"""
from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import nation_zones
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
    # 纳入范围**以路网节点为准**：边界 50 km 内退出的城市在建网时已连同航线一起删除，
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


def _city_weather_payload() -> Dict[str, Any]:
    """逐市气象（多源：open-meteo 批量为主，wttr.in 补缺）。取不到的城市就是没有，不补零。

    返回**整份载荷**（含 fetchedAt 与 sources）；取证要引用"这份实况是什么时候取的"；
    只拿 cities 的调用走 `_city_weather()`。

    顺序有讲究：备源补数是**按顺序**补前 80 个，所以这里把省会、机场城市排前面 ——
    真要限流时，先保证"能起降的城市"有实况。
    """
    try:
        from weather import city_weather
        rows = sorted(_city_rows(), key=lambda row: (row.get('rank', 3), row['name']))
        return city_weather.fetch([(row['name'], row['lat'], row['lon']) for row in rows])
    except Exception:  # noqa: BLE001 - 气象源不可用不能把页面打崩
        return {}


def _city_weather() -> Dict[str, Dict[str, Any]]:
    return _city_weather_payload().get('cities') or {}


# 模型概率取不到的原因。留在这里供 modelCard.error 下发 ——
# 只返回空字典而不说为什么，界面就只能写"没取到"，说不清是限流还是模型坏了。
_MODEL_ERROR = ''


def _model_probs() -> Dict[str, float]:
    """全国模型（ml-v3）逐市低能见度概率。

    取不到就给空字典，**并把原因记到 `_MODEL_ERROR`**；调用方据此把 probSource
    标成 RULE 并把原因下发。这是"模型不可用要说出来"，不是静默降级。
    """
    global _MODEL_ERROR
    try:
        from ml import national_model
        from weather import city_hourly
        rows = [{'name': row['name'], 'lat': row['lat'], 'lon': row['lon']} for row in _city_rows()]
        payload = city_hourly.fetch(rows)
        got = national_model.probability_map(payload.get('cities') or {})
        _MODEL_ERROR = '' if got else '逐市小时数据为空（可能被限流）'
        return got
    except Exception as exc:  # noqa: BLE001 - 模型或数据源不可用不能把页面打崩
        _MODEL_ERROR = f'{type(exc).__name__}: {str(exc)[:80]}'
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


# 每帧的环数统计：{band: {kept, total}}。供载荷里的 truncated 字段与界面提示用。
_RADAR_STATS: Dict[str, Dict[str, Dict[str, int]]] = {}


def radar_stats(radar_ts: str) -> Dict[str, Any]:
    st = _RADAR_STATS.get(radar_ts) or {}
    total = sum(int(v.get('total') or 0) for v in st.values())
    kept = sum(int(v.get('kept') or 0) for v in st.values())
    return {'bands': st, 'totalRings': total, 'keptRings': kept,
            'truncated': any(int(v.get('total') or 0) > int(v.get('kept') or 0) for v in st.values()),
            'cap': 200}


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
    stats: Dict[str, Dict[str, int]] = {}
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
                    # 面积下限 0.02 平方度 ≈ 20×20 km：小雨团被整片丢掉，
                    # 于是"图上有回波、判定里没有"。降到 0.004（≈6×6 km）。
                    if part.is_empty or part.area < 0.004:
                        continue
                    coords = [[round(x, 3), round(y, 3)] for x, y in part.exterior.coords]
                    if len(coords) >= 4:
                        kept.append((part.area, coords))
            except Exception:  # noqa: BLE001
                continue
        # 按面积降序取前 200：极端天气也不会把整片主雨带截掉（原先是 [:45] 顺序截断）
        kept.sort(key=lambda item: item[0], reverse=True)
        out[band] = [coords for _area, coords in kept[:200]]
        stats[band] = {'kept': len(out[band]), 'total': len(kept)}
    # 截断必须能被界面读到：悄悄丢掉 30 片回波，等于让读者以为"就这么多"。
    _RADAR_STATS[radar_ts] = stats
    return out


@lru_cache(maxsize=2)
def _neighbor_union_m():
    """邻国并集（米制，AEQD）。用于"这条航路离境外多远"的真实几何判定。"""
    from shapely.geometry import shape
    from shapely.ops import transform as shp_transform, unary_union
    payload = json.loads((ROOT / 'data' / 'traffic' / 'neighbors-50m.json').read_text(encoding='utf-8'))
    parts = []
    for feature in payload.get('features') or []:
        try:
            parts.append(shape(feature['geometry']))
        except Exception:  # noqa: BLE001
            continue
    if not parts:
        return None
    return shp_transform(_xy_transformer().transform, unary_union(parts))


@lru_cache(maxsize=2)
def _corridor_border(network_stamp: str) -> Dict[str, Dict[str, Any]]:
    """逐航路的**真实**离境距离与"进入 10/30 km 带"的进度区间。

    之前越界监视是读 `borderBlocked` 标记算出来的，等于"我说它不越界它就不越界"。
    这里改成几何：把航路按约 8 km 加密，逐点算到邻国的距离，缓存一份。
    492 条大多离境几十到上千公里，先整体量一次，只有 <50 km 的才加密找区间。
    """
    from shapely.geometry import LineString, Point
    near = _neighbor_union_m()
    if near is None:
        return {}
    to_xy = _xy_transformer().transform
    table: Dict[str, Dict[str, Any]] = {}
    for row in _corridor_rows():
        path = row.get('path') or [row['fromLonLat'], row['toLonLat']]
        if len(path) < 2:
            continue
        line = LineString([to_xy(lon, lat) for lon, lat in path])
        whole = near.distance(line) / 1000.0
        item = {'minKm': round(whole, 1), 'band10': [], 'band30': []}
        if whole < 50.0:
            steps = max(12, min(60, int(line.length / 8000.0)))
            samples = []
            for index in range(steps + 1):
                point = line.interpolate(index / steps, normalized=True)
                samples.append((index / steps, near.distance(point) / 1000.0))
            item['minKm'] = round(min(value for _, value in samples), 1)
            for limit, key in ((10.0, 'band10'), (30.0, 'band30')):
                start = None
                for progress, distance in samples:
                    if distance < limit and start is None:
                        start = progress
                    elif distance >= limit and start is not None:
                        item[key].append([round(start, 3), round(progress, 3)])
                        start = None
                if start is not None:
                    item[key].append([round(start, 3), 1.0])
        table[row['id']] = item
    return table


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


# —— 虚拟气象（演示包）——
# 用户要的"全国恶劣天气"场景：不是给前端加一层滤镜，而是**真的造出回波几何**，
# 让绕飞、停飞、事件、禁飞区框全部按这套几何重算一遍。
# 固定种子（按 10 分钟一档 + 余弦扰动），同一帧重跑结果一致，方便复核与截图对比。
_VIRTUAL_CACHE: Dict[Any, Any] = {}

# 六个大区各给一个中心点与半径（经度±、纬度±），覆盖东部沿海与长江中游两条主廊道。
# 半径比第一版收 18%：原来整片罩得太满，凡是压线的走廊都"绕不开"，于是虚拟模式下
# 只剩停飞、一架绕飞都没有 —— 真实强对流过程里总有一部分航路是能小绕过去的。
_VIRTUAL_CELLS = (
    ('华东', 119.2, 31.6, 2.54, 1.80),
    ('中南-长江中游', 113.4, 29.6, 2.30, 1.64),
    ('中南-华南沿海', 112.6, 22.8, 1.97, 1.39),
    ('华北', 116.6, 37.8, 2.13, 1.56),
    ('东北', 125.4, 45.2, 1.80, 1.31),
    ('西南', 105.6, 29.2, 1.64, 1.23),
)


def _ellipse_ring(lon: float, lat: float, rx: float, ry: float, phase: float,
                  n: int = 40) -> List[List[float]]:
    """椭圆环 + 两谐波扰动：形状像回波胞，不像标准椭圆。

    顶点数 40 与真实回波同量级（真实环经闭运算 + Chaikin 后约 60–120 点），
    前端不需要为虚拟数据走另一套渲染。
    """
    ring = []
    for i in range(n):
        t = 2 * math.pi * i / n
        wobble = 1 + 0.16 * math.sin(3 * t + phase) + 0.09 * math.cos(5 * t - phase)
        x = lon + rx * wobble * math.cos(t)
        y = lat + ry * wobble * math.sin(t)
        ring.append([round(x, 3), round(y, 3)])
    ring.append(ring[0])
    return ring


# 每个对流系统里挂几个对流单体。真实回波是"层状罩里长着几个对流胞、胞里有强核"，
# 以前每个系统只画三个同心椭圆 —— 那是靶心，不是回波。三档各自一片，画出来还互不嵌套。
_VIRTUAL_CELLS_PER_SYSTEM = 6


def _virtual_bands(bucket: int) -> Dict[str, List[List[List[float]]]]:
    """按 10 分钟一档生成合成回波：**有结构的对流系统群**。

    一个系统 = 1 个层状罩（WEAK）+ N 个对流单体（CONVECTIVE）+ 单体内的强核（STRONG）。
    这样三档天然是"罩 ⊃ 单体 ⊃ 强核"的嵌套结构，前端按绿→黄→红叠色就是真实回波的样子；
    以前每档各画一个同心椭圆，三档面积差不多，看着像三个靶心叠在一起。

    片数：6 系统 × (2 罩 + 6 单体 + 6 强核) = 84 片，与实测同量级（实测 45/68/86）。
    单体位置用固定相位算出来，同一 bucket 重跑结果一致 —— 演示回放才能复现。
    """
    strong: List[List[List[float]]] = []
    convective: List[List[List[float]]] = []
    weak: List[List[List[float]]] = []
    for index, (_region, lon, lat, rx, ry) in enumerate(_VIRTUAL_CELLS):
        phase = (bucket * 0.37 + index * 1.13) % (2 * 3.14159)
        # 中心随时间缓慢漂移：演示"回波在动"，但不会漂出国境
        drift_lon = 0.55 * math.cos(phase)
        drift_lat = 0.32 * math.sin(phase * 0.8)
        cx, cy = lon + drift_lon, lat + drift_lat
        # 层状罩：整个系统的大边界
        weak.append(_ellipse_ring(cx, cy, rx, ry, phase + 1.7))
        # 罩外再带一片薄的层状云（真实回波边缘总有衰减带，不是一刀切）
        weak.append(_ellipse_ring(cx + rx * 0.55, cy - ry * 0.35, rx * 0.62, ry * 0.55, phase + 2.6))
        for k in range(_VIRTUAL_CELLS_PER_SYSTEM):
            ang = 2 * math.pi * k / _VIRTUAL_CELLS_PER_SYSTEM + phase * 0.6
            # 单体沿系统内部一圈排布，半径取系统的 0.45，避免顶到罩边
            ox = math.cos(ang) * rx * 0.45
            oy = math.sin(ang) * ry * 0.45
            cell_r = 0.46 + 0.16 * math.sin(phase + k * 1.9)
            convective.append(_ellipse_ring(cx + ox, cy + oy, rx * cell_r, ry * cell_r,
                                            phase + k * 0.8))
            # 强核偏在单体的一侧（真实强回波不在胞心，在入流侧）
            strong.append(_ellipse_ring(cx + ox * 1.14, cy + oy * 1.14,
                                        rx * cell_r * 0.42, ry * cell_r * 0.42,
                                        phase + k * 1.4))
    return {'STRONG': strong, 'CONVECTIVE': convective, 'WEAK': weak}


def _virtual_radar(bucket: int) -> Dict[str, Any]:
    bands = _VIRTUAL_CACHE.get(('bands', bucket))
    if bands is None:
        bands = _virtual_bands(bucket)
        _VIRTUAL_CACHE[('bands', bucket)] = bands
    # stats 与真实帧同构（_radar_clipped 之后由 radar_stats 产出）：前端与"口径与来源"页
    # 读的是同一组字段，虚拟模式不该让它们变成 None —— 那会让"回波 199 片"在切到虚拟后消失。
    counts = {k: len(v) for k, v in bands.items()}
    stats = {
        'bands': {k: {'kept': n, 'total': n} for k, n in counts.items()},
        'totalRings': sum(counts.values()),
        'keptRings': sum(counts.values()),
        'truncated': False,
        'cap': None,
    }
    return {
        'available': True,
        'ts': f'VIRTUAL-{bucket * 600}',      # 600 秒一档，形如时间戳，前端按字符串比较即可
        'source': 'VIRTUAL（演示包：合成回波，非实况）',
        'virtual': True,
        'bands': bands,
        'counts': counts,
        'stats': stats,
        # 覆盖率没有"真实国土面积"分母可言，给 None 比给个假数诚实
        'coverage': None,
    }


# 虚拟雾：东部平原与长江中游两片。中心点取自 _VIRTUAL_CELLS 里靠东的三个系统附近，
# 画出来是"连成片的雾"，而不是"每个城市一个小圆"。
_VIRTUAL_FOG_FIELDS = (
    ('华北平原-黄淮', 116.2, 36.2, 3.4, 1.9, 700),
    ('长江中下游', 117.4, 30.4, 3.8, 1.7, 900),
    ('四川盆地', 105.4, 30.2, 2.1, 1.3, 1600),
)


def _virtual_vis_override(cities: List[Dict[str, Any]],
                          weather: Dict[str, Dict[str, Any]],
                          bucket: int) -> Dict[str, Dict[str, Any]]:
    """虚拟气象的**唯一**开关点：返回一份 weather 副本，只改 ``visM``。

    这是"虚拟气象到底影响了什么"的答案：**只有能见度被替换**，其余要素
    （气温、风、湿度）原样不动。而能见度是雾与低能见判定的唯一输入，所以

      · ``_fog()`` 会因为 visM 变小而自然画出雾区 —— 雾是"算出来的"，不是新画一层；
      · ``nation_ops.flight_objects()`` 会因此产生 WEATHER_HOLD 与绕飞 —— 判据同一条路径。

    显示侧仍用**真实** weather 的 visM（见 ``_payload_locked`` 里的 ``display_weather``），
    所以页面上的"能见度 2.4 km"永远是真数，而"因雾停飞"是按虚拟雾算的。
    这条边界必须两边都守住，否则要么虚数当实况、要么虚拟气象什么也没发生。
    """
    out = {name: dict(row) for name, row in weather.items()}
    phase = (bucket * 0.29) % (2 * math.pi)
    for index, (_name, lon, lat, rx, ry, base_vis) in enumerate(_VIRTUAL_FOG_FIELDS):
        # 雾场本身也在缓慢移动/消长：不然拖时间轴时雾一动不动，一眼看出是贴图
        cx = lon + 0.4 * math.cos(phase + index)
        cy = lat + 0.25 * math.sin(phase * 0.7 + index)
        for city in cities:
            name = city['name']
            row = out.get(name)
            if row is None:
                continue
            dx = (city['lon'] - cx) / rx
            dy = (city['lat'] - cy) / ry
            d = math.hypot(dx, dy)
            if d > 1.35:
                continue
            # 中心 600 m 上下（雾），外圈 1500–2800 m（轻雾/霾）—— 用 base_vis 与距离线性插值
            if d <= 0.55:
                vis = base_vis * (0.75 + 0.35 * math.sin(phase + index))
            else:
                vis = base_vis + (3000 - base_vis) * min(1.0, (d - 0.55) / 0.8)
            row['visM'] = int(max(300, min(row.get('visM') or 99999, vis)))
            # `low` 是 visM<3000 的派生布尔，全库有三处直接读它（页头低能见计数、
            # 城市红圈、逐市情报状态）。只改 visM 不改 low，就会出现
            # "雾区 104 城、页头仍写 11 城"这种自相矛盾。
            row['low'] = row['visM'] < 3000
            row['virtualVis'] = True
    return out


def _virtual_detour_table(bucket: int) -> Dict[str, Dict[str, Any]]:
    """按合成回波重算绕飞：与真实回波同一套判定（_detour_for），不是另写一套。"""
    cached = _VIRTUAL_CACHE.get(('table', bucket))
    if cached is not None:
        return cached
    from shapely.ops import transform as shp_transform
    avoid = _radar_polygons(_virtual_bands(bucket))
    table: Dict[str, Dict[str, Any]] = {}
    blocked: set = set()
    if avoid is not None:
        avoid_xy = shp_transform(_xy_transformer().transform, avoid)
        for row in _corridor_rows():
            path = row.get('path') or [row['fromLonLat'], row['toLonLat']]
            got = _detour_for(path, avoid_xy)
            if got:
                table[row['id']] = got
            elif _path_hits(path, avoid_xy):   # 必须用投影后的 avoid：_path_hits 比的是米制平面
                # 压线但小绕脱不开：这条航路此刻不成立，交给上层的"停飞"处理
                blocked.add(row['id'])
    _VIRTUAL_CACHE[('table', bucket)] = (table, blocked)
    return table, blocked


def _path_hits(path: List[List[float]], avoid) -> bool:
    """航路是否落在回波多边形里（米制平面判交，与 _detour_for 同一套投影）。"""
    from shapely.geometry import LineString
    if avoid is None or len(path) < 2:
        return False
    to_xy = _xy_transformer()
    line = LineString([to_xy.transform(lon, lat) for lon, lat in path])
    return bool(line.intersects(avoid))


def _virtual_bucket(minute: int) -> int:
    return int(max(0, min(1440, minute)) // 10)


def _fog(cities: List[Dict[str, Any]], weather: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """低能见度区（雾区）：**由逐市能见度派生**的面，不是真实的雾场观测。

    做法：能见度 <1500 m 的城市画 35 km 缓冲、1500–3000 m 画 55 km 缓冲，同档合并成片。
    这是"已知这几个城市看不见，周围多大一片大概也看不见"的保守估计 ——
    半径是按城市间距取的，不是气象上的雾团尺度，所以界面上必须标 DERIVED，
    也不能拿它当"官方雾区预警"讲。
    """
    from shapely.geometry import Point
    from shapely.ops import unary_union
    radius = {'BAN': 0.32, 'LOW': 0.50}          # 度；约 35 km / 55 km
    groups: Dict[str, List[Point]] = {'BAN': [], 'LOW': []}
    rows: List[Dict[str, Any]] = []
    for city in cities:
        live = weather.get(city['name']) or {}
        vis = live.get('visM')
        if vis is None:
            continue
        if vis < 1500:
            level = 'BAN'
        elif vis < 3000:
            level = 'LOW'
        else:
            continue
        groups[level].append(Point(city['lon'], city['lat']))
        rows.append({'name': city['name'], 'province': city['province'],
                     'lon': city['lon'], 'lat': city['lat'], 'visM': vis, 'level': level})
    bands: Dict[str, List[List[List[float]]]] = {}
    for level, points in groups.items():
        if not points:
            bands[level] = []
            continue
        merged = unary_union([point.buffer(radius[level], quad_segs=6) for point in points])
        merged = merged.simplify(0.02)
        parts = getattr(merged, 'geoms', [merged])
        rings = []
        for part in parts:
            if part.is_empty or part.area < 0.02:
                continue
            rings.append([[round(x, 3), round(y, 3)] for x, y in part.exterior.coords])
        bands[level] = rings[:24]
        # 城市点本身也要画：面是估的，点是实测的，两者不能混
    all_points = [(row['lon'], row['lat']) for row in rows]
    bbox = None
    if all_points:
        bbox = [round(min(p[0] for p in all_points) - 0.6, 3), round(min(p[1] for p in all_points) - 0.4, 3),
                round(max(p[0] for p in all_points) + 0.6, 3), round(max(p[1] for p in all_points) + 0.4, 3)]
    return {
        'available': bool(rows),
        'counts': {'BAN': sum(1 for row in rows if row['level'] == 'BAN'),
                   'LOW': sum(1 for row in rows if row['level'] == 'LOW'),
                   'cities': len(rows)},
        'bands': bands,
        'cities': rows,
        'bbox': bbox,
        'radiusKm': {'BAN': 35, 'LOW': 55},
        'source': 'open-meteo current 逐市能见度（公开、免密钥）',
        'note': '面由城市能见度按半径外扩合并得到（DERIVED），不是雾场观测；半径是工程估值，不是气象雾团尺度。',
    }


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
    """全国层的"实况点"就是**逐市实况本身**。

    早先这里拉的是 METAR（`national()` 与 `model_stations.fetch()` 两次 HTTP，冷启动
    合计 12 秒，且只覆盖几十个站），而全国层本来就有 319 城逐市实况 —— 重复拉一份又慢
    又不全，是把旧运行网的取数逻辑惯性带过来了。

    现在全国层一律用逐市实况，不再调 METAR：METAR 只在离线交叉校验里用。
    冷启动从 12 秒压到 2.5 秒（实测）。
    """
    weather = _city_weather()
    points: List[Dict[str, Any]] = []
    for row in _city_rows():
        item = weather.get(row['name'])
        if not item:
            continue
        points.append({
            'name': row['name'], 'province': row['province'],
            'lon': row['lon'], 'lat': row['lat'],
            'visM': item.get('visM'), 'tempC': item.get('tempC'),
            'windMps': item.get('windMps'),
            # PUBLIC = 公开源逐市实况（open-meteo / wttr），不是 METAR 报文
            'source': 'PUBLIC',
        })
    return points


def _province_rows(virtual: bool = False, minute: int = 0) -> List[Dict[str, Any]]:
    stations = _live_stations()
    live: Dict[str, int] = {}
    model: Dict[str, int] = {}
    for point in stations:
        bucket = model if point.get('source') == 'MODEL' else live
        bucket[point['name']] = bucket.get(point['name'], 0) + 1
    by_province = _cities_by_province()
    stats = _corridor_stats()
    # 省级"低能见城市"是**判据口径**：虚拟气象下必须与雾区同源，否则会出现
    # "雾区 104 城、省级汇总 11 城"。逐市能见度读数本身也走同一份（见 intel 说明）。
    weather = (_virtual_vis_override(_city_rows(), _city_weather(), _virtual_bucket(minute))
               if virtual else _city_weather())
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
        # 全国层用逐市实况，不再是 METAR 报文；标签保留但语义已改，界面上写"逐市实况点"
        'stationsMetar': sum(1 for row in stations if row.get('source') == 'PUBLIC'),
        'stationsModel': sum(1 for row in stations if row.get('source') == 'MODEL'),
        'operational': sum(1 for row in provinces if row['state'] == 'operational'),
        'pending': sum(1 for row in provinces if row['state'] == 'pending'),
        # 边界退出通航：城市与航线一并删除，这里把被删的城市名与距离摊开，
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
            'stations': '公开源逐市实况（open-meteo / wttr），全国 319 市逐点；不使用 METAR 报文，报文仅作离线交叉校验',
        },
        'positioning': '飞行汽车解决城市间交通；跨省长距离仍靠飞机与火车，本网络是分担不是取代。',
    }


def _flights_payload_locked(level: str = 'nation', ident: Optional[str] = None,
                    minute: int = 0, virtual: bool = False) -> Dict[str, Any]:
    """只回航班与统计：时间轴每拖一次都要刷新，不能把整份网络重算一遍。"""
    minute = max(0, min(1440, int(minute or 0)))
    provinces = [row['name'] for row in _province_rows()]
    blocked_ids: set = set()
    if virtual:
        radar = _virtual_radar(_virtual_bucket(minute))
        table, blocked_ids = _virtual_detour_table(_virtual_bucket(minute))
    else:
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
    # 与 _payload_locked 同一套输入：时间轴拖动时，班次裁决的口径不能和整页载荷不一致。
    # 否则会出现"首页说因雾停飞 14 架、拖一格时间轴变回 0 架"这种自相矛盾。
    display_weather = _city_weather()
    judge_weather = (_virtual_vis_override(_city_rows(), display_weather, _virtual_bucket(minute))
                     if virtual else display_weather)
    flights = nation_ops.flight_objects(corridors, minute, table, judge_weather, _model_probs(),
                                        blocked_ids=blocked_ids)
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


def _payload_locked(level: str = 'nation', ident: Optional[str] = None,
            minute: int = 0, virtual: bool = False) -> Dict[str, Any]:
    minute = max(0, min(1440, int(minute or 0)))
    provinces = _province_rows(virtual, minute)
    stations = _live_stations()
    base = _base(level, ident)
    names = [row['name'] for row in provinces]
    # 虚拟气象：换的是**几何来源**，不是结果 —— 绕飞与停飞仍由同一套 _detour_for 判定，
    # 所以"开演示包"与"真实天气"跑的是同一条代码路径，只是输入不同。
    blocked_ids: set = set()
    if virtual:
        radar = _virtual_radar(_virtual_bucket(minute))
        table, blocked_ids = _virtual_detour_table(_virtual_bucket(minute))
    else:
        radar = _radar()
        table = _detour_table(radar.get('ts') or 'none') if radar.get('available') else {}

    def attach(body: Dict[str, Any], corridors: List[Dict[str, Any]],
               cities: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        for row in corridors:
            got = table.get(row['id'])
            if got:
                row['detour'] = got          # 前端用它画绕飞后的实际航迹
        weather_doc = _city_weather_payload()
        weather = weather_doc.get('cities') or {}
        model_probs = _model_probs()
        scoped_cities = cities if cities is not None else _city_rows()
        # 虚拟气象的唯一落点：**换一份能见度**，其余要素不动（见 _virtual_vis_override）。
        # judge_weather 给判定用，display_weather 给界面用 —— 两者必须分开：
        # 合起来就会出现"气温 3℃ 但能见度 600 m"这种半真半假的读数。
        bucket = _virtual_bucket(minute)
        judge_weather = _virtual_vis_override(scoped_cities, weather, bucket) if virtual else weather
        display_weather = weather
        # 逐市情报：**能见度用判定口径**（它本身就是雾的量化，虚拟雾变了它就该变），
        # 气温/风速仍取自 display_weather 的实况。每行带 virtualVis，前端加"（虚拟）"。
        intel_weather = judge_weather if virtual else display_weather
        if virtual:
            # 节点上的 weather 只服务"红圈 + 点开看这座城"：能见度与 low 跟着虚拟雾走，
            # 气温风速原样（它们是实况）。不换这一步，页头会写"低能见 11 城"而雾区盖了 104 城，
            # 地图上也不会出现红圈 —— 虚拟气象只在表格里生效、图上毫无变化。
            for node in body.get('nodes') or []:
                jw = judge_weather.get(node['name']) or {}
                if node.get('weather') and jw.get('visM') is not None:
                    node['weather'] = {**node['weather'], 'visM': jw['visM'],
                                       'low': bool(jw.get('low')), 'virtual': True}
            if body.get('summary') is not None:
                body['summary']['lowVisCities'] = sum(
                    1 for row in scoped_cities if (judge_weather.get(row['name']) or {}).get('low'))
        flights = nation_ops.flight_objects(corridors, minute, table, judge_weather, model_probs,
                                            blocked_ids=blocked_ids)
        hit = sum(1 for row in corridors if row.get('detour'))
        delayed = sum(1 for row in flights if row['status'] == 'DELAYED')
        blocked = sum(1 for row in corridors if row.get('borderBlocked'))
        border_hit = sum(1 for row in corridors if row.get('borderDetour'))
        airport_by_city: Dict[str, Dict[str, Any]] = {}
        for station in _airports().get('stationRows') or []:
            if station.get('city'):
                airport_by_city.setdefault(station['city'], station)
        for node in body.get('nodes') or []:
            if model_probs and node['name'] in model_probs:
                node['pLowVis'] = model_probs[node['name']]
        return {**body,
                'minute': minute,
                'radar': ({
                    # 虚拟气象：直接用合成几何，**不能**再去读 _radar_clipped（那会读回真实帧）
                    'available': True,
                    'ts': radar.get('ts'),
                    'source': radar.get('source'),
                    'counts': {band: len(rings) for band, rings in radar.get('bands', {}).items()},
                    'bands': radar.get('bands', {}),
                    'coverage': None,
                    'tiles': None,
                    'virtual': True,
                    'stats': radar.get('stats'),
                } if radar.get('virtual') else {
                    'available': bool(radar.get('available')),
                    'ts': radar.get('ts'),
                    'source': radar.get('source'),
                    'counts': {band: len(rings) for band, rings
                               in _radar_clipped(radar.get('ts') or 'none').items()},
                    'bands': _radar_clipped(radar.get('ts') or 'none'),
                    'coverage': radar.get('coverage'),
                    # 瓦片直链：前端按墨卡托贴图，边界比矢量多边形更像真实回波
                    'tiles': radar.get('tiles_url'),
                    'virtual': False,
                    'stats': radar_stats(radar.get('ts') or 'none'),
                }),
                'clearanceNote': '许可要素由本班次已写定的计划字段组装，不重新计算；标“待批”的班次不进入在飞序列。',
                'flights': flights,
                'upcoming': nation_ops.upcoming(corridors, minute)[:90],
                'alerts': nation_ops.alerts(corridors, flights, judge_weather, scoped_cities),
                # intel 是"读数 + 判定"两张皮：visM/tempC/wind 取实况（数字必须是真的），
                # low/status 取判定口径（否则虚拟雾区里的城市会写着"可放行"而飞机已停飞）。
                # 每行带 virtualVis 标记，前端据此在数字后面加"虚拟"。
                'intel': nation_ops.intel(scoped_cities, intel_weather, airport_by_city),
                # 雾由能见度派生：喂 judge_weather 就自动跟着虚拟雾走，不需要另画一层
                'fog': {**_fog(scoped_cities, judge_weather),
                        **({'virtual': True,
                            'note': '虚拟气象：雾区为合成场（按虚拟能见度派生），非实况。'}
                           if virtual else {})},
                # 虚拟气象的影响面写着讲清楚：换的是回波与雾，气温/风/能见度读数仍是实况。
                # 前端在开启虚拟时把这几行显示出来，避免"虚拟"被读成"整页都是假数据"。
                'weatherMode': {
                    'virtual': bool(virtual),
                    'label': '虚拟气象（演示包）' if virtual else '实测气象',
                    'replaced': ['radar', 'fog'] if virtual else [],
                    'untouched': ['tempC', 'windMps', 'humidity', 'pressure'] if virtual else [],
                    'note': ('回波为合成对流系统、雾区按虚拟能见度派生；'
                             '气温、风等要素仍为公开源实况。裁决用能见度已按虚拟雾区调整。'
                             if virtual else '全部要素取自公开源实况。'),
                },
                # 机场净空（DERIVED）：规则化几何 + 穿越统计。
                # 与法定管制区（OFFICIAL，另库）分开，永不合并计数。
                # 只挂计数摘要；几何与穿越明细走 /traffic/v2/nation/zones 按需取。
                # 287 个环放进主载荷会多出 250 KB，而首页并不用它们。
                'zones': nation_zones.summary(),
                # 实况元信息：哪个源给了多少城、是不是旧数据、是不是还在补。
                # 界面上"逐市气象 0/0"必须能解释成"补数中"而不是"没有"。
                'weatherMeta': {
                    'fetchedAt': weather_doc.get('fetchedAt'),
                    'sources': weather_doc.get('sources') or {},
                    'stale': bool(weather_doc.get('stale')),
                    # 旧数据必须带年龄：3 天前的快照和 2 分钟前的过期缓存，
                    # 对"能不能飞"含义完全不同，一个布尔说不清。
                    'staleAgeSeconds': weather_doc.get('staleAgeSeconds'),
                    'expiredSnapshot': bool(weather_doc.get('expiredSnapshot')),
                    'refreshing': bool(weather_doc.get('refreshing')),
                    'cities': len(weather),
                    'errors': (weather_doc.get('errors') or [])[:3],
                },
                'modelCard': _model_card(model_probs),
                'counterfactual': nation_ops.counterfactual(flights),
                'border': {**nation_ops.border_monitor(
                                corridors, flights,
                                _corridor_border(_network().get('generatedAt') or 'v1')),
                           'excludeKm': _network().get('borderExcludeKm'),
                           'excludedCities': _network().get('borderExcluded') or []},
                'traffic': {'corridors': len(corridors), 'airborne': len(flights),
                            'delayed': delayed, 'radarHitCorridors': hit,
                            'blocked': blocked, 'borderDetourCorridors': border_hit,
                            'hold': sum(1 for row in flights if row['decision'] == 'HOLD'),
                            'lowVisCities': sum(1 for row in scoped_cities
                                                if (judge_weather.get(row['name']) or {}).get('low')),
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
                    'note': '纳入范围内没有这个城市（外围缓冲带内的城市已整体退出通航）'}
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


def _evidence_locked(flight_id: str, minute: int = 60) -> Dict[str, Any]:
    """全国班次的取证链：**每一行都带来源**，没有来源的行不许写。

    设计上刻意不依赖"班次属于哪个层级"：班次 id 里已经带走廊号（`NC-0310#-1`），
    直接按走廊重算这一班，O(1)，不必为了一次点击重建整棵树。

    大模型是否可用由**调用方**（main）决定并回填 `llm` 字段 —— 没配置就必须
    如实说"只有规则链"，不能拿规则结论冒充模型判定。
    """
    raw = (flight_id or '').strip()
    corridor_id = raw.split('#')[0]
    destination = None
    for row in _corridor_rows():
        if row['id'] == corridor_id:
            destination = row
            break
    if destination is None:
        return {'status': 'NOT_FOUND', 'flightId': raw,
                'note': f'没有这条航线：{corridor_id}'}
    minute = max(0, min(1440, int(minute or 0)))
    radar = _radar()
    table = _detour_table(radar.get('ts') or 'none') if radar.get('available') else {}
    weather_body = _city_weather_payload()
    weather = weather_body.get('cities') or {}
    weather_ts = weather_body.get('fetchedAt')
    scoped = _slice_corridors({destination['fromProvince'], destination['toProvince']})
    corridor = next((item for item in scoped if item['id'] == corridor_id), None)
    if corridor is None:
        return {'status': 'NOT_FOUND', 'flightId': raw, 'note': '航线不在当前路网里'}
    if table.get(corridor_id):
        corridor['detour'] = table[corridor_id]
    flights = nation_ops.flight_objects([corridor], minute, table, weather)
    flight = next((item for item in flights if item['id'] == raw), None)
    if flight is None:
        return {'status': 'NOT_AIRBORNE', 'flightId': raw, 'minute': minute,
                'note': '该班次在此刻不在飞（可能已到达或尚未起飞）；时间轴上换一分钟再取证。'}

    a = weather.get(flight['fromName']) or {}
    b = weather.get(flight['toName']) or {}
    detour = corridor.get('detour') or {}

    def vis(value):
        return '无实况' if value is None else (f'{value/1000:.1f} km' if value < 10000 else f'≥{value/1000:.0f} km')

    # 回波必须分三态，不能都写成"无回波"：
    #   雷达没取到   → ABSENT：不可用，绕飞结论不成立
    #   取到且压线   → DERIVED：穿了多少 km
    #   取到但没压线 → DERIVED：这是本系统算出来的结论，不是没数据
    # 前两种混成一个输出，就等于让证据链把"没拿到"说成"算过了、没有"。
    radar_ok = bool(radar.get('available'))
    if not radar_ok:
        band_text, band_source = '回波数据不可用（本帧未取到）', 'ABSENT'
        band_action, band_action_source = '未做绕飞判断', 'ABSENT'
        band_source_text, band_source_badge = '回波源未返回，本班次的绕飞与暴露结论不成立', 'ABSENT'
    elif detour:
        band_text, band_source = f"原航路穿回波 {detour.get('hitKm')} km", 'DERIVED'
        band_action, band_action_source = f"外偏 {detour.get('shiftKm')} km 绕飞", 'DERIVED'
        band_source_text, band_source_badge = '公开雷达拼图（RainViewer），已裁到国内', 'PUBLIC'
    else:
        band_text, band_source = '本帧无回波压线', 'DERIVED'
        band_action, band_action_source = '保持原航路', 'DERIVED'
        band_source_text, band_source_badge = '公开雷达拼图（RainViewer），已裁到国内', 'PUBLIC'

    steps = [
        {'n': 1, 'title': '班次与航路', 'rows': [
            {'label': '班次', 'value': f"{flight['callsign']}（{flight['id']}）", 'source': 'SIM'},
            {'label': '起讫', 'value': f"{flight['fromName']} → {flight['toName']}", 'source': 'SIM'},
            {'label': '航线', 'value': f"{corridor_id} · {corridor.get('kindLabel')} · {corridor.get('lengthKm')} km", 'source': 'SIM'},
            {'label': '计划', 'value': f"{flight['planAt']} 起飞 / {flight['arriveAt']} 到达", 'source': 'SIM'},
        ]},
        {'n': 2, 'title': '端点实况', 'rows': [
            {'label': f"{flight['fromName']} 能见度", 'value': vis(a.get('visM')), 'source': 'PUBLIC', 'ts': weather_ts},
            {'label': f"{flight['toName']} 能见度", 'value': vis(b.get('visM')), 'source': 'PUBLIC', 'ts': weather_ts},
            {'label': '端点风速', 'value': f"{a.get('windMps', '—')} / {b.get('windMps', '—')} m/s", 'source': 'PUBLIC', 'ts': weather_ts},
        ]},
        {'n': 3, 'title': '航路回波', 'rows': [
            {'label': '回波段', 'value': band_text, 'source': band_source, 'ts': radar.get('ts')},
            {'label': '处理', 'value': band_action, 'source': band_action_source},
            {'label': '回波源', 'value': band_source_text, 'source': band_source_badge,
             'ts': radar.get('ts') if radar_ok else None},
        ]},
        {'n': 4, 'title': '风险与裁决', 'rows': [
            {'label': '风险概率', 'value': f"{flight['riskP']:.2f}（{flight['riskLevelLabel']}）", 'source': 'DERIVED'},
            {'label': '裁决', 'value': flight['decisionLabel'], 'source': 'DERIVED'},
            *[{'label': f'依据 {index + 1}', 'value': text, 'source': 'DERIVED'}
              for index, text in enumerate(flight.get('drivers') or [])],
        ]},
        {'n': 5, 'title': '反事实与边界', 'rows': [
            {'label': '不绕飞暴露', 'value': f"{flight['exposure']['directMin']} 分钟", 'source': 'DERIVED'},
            {'label': '绕飞后暴露', 'value': f"{flight['exposure']['detourMin']} 分钟", 'source': 'DERIVED'},
            {'label': '边界', 'value': ('航线已按边界带改线' if corridor.get('borderDetour')
                                      else ('该航线受限停飞' if corridor.get('borderBlocked') else '未触发')),
             'source': 'OFFICIAL'},
        ]},
    ]
    # —— 判据：把"凭什么这样裁决"拆成逐条可核对的阈值判断 ——
    # 之前证据链只给一句"风险 0.05（低）"，读者没法核。这里每条都写：实测多少、阈值多少、过没过。
    # 值域 0–1 的 ratio 一并给出，前端据此画条，不用自己再算一遍（两处算就会两处不一致）。
    criteria = []
    vis_floor = nation_ops.VIS_BANDS[-1][0]      # 5.0 km：最后一道可见度门槛
    # 注意：本函数里 `vis` 是**格式化函数**（把米数变成"≥58 km"），不是数值。
    # 数值要在这里单独取，别把函数当数用 —— 会直接 TypeError。
    vis_list = [v.get('visM') for v in (a, b) if v.get('visM') is not None]
    vis_val = min(vis_list) if vis_list else None
    wind_list = [v.get('windMps') for v in (a, b) if v.get('windMps') is not None]
    wind_val = max(wind_list) if wind_list else None
    if vis_val is not None:
        criteria.append({
            'key': 'vis', 'label': '端点能见度（取两端较差）',
            'display': vis(vis_val),
            'actual': round(vis_val / 1000.0, 1), 'threshold': round(vis_floor / 1000.0, 1),
            'unit': 'km', 'higherBetter': True,
            'ratio': round(min(1.0, vis_val / vis_floor), 3),
            'pass': vis_val >= vis_floor, 'source': 'PUBLIC',
        })
    else:
        criteria.append({'key': 'vis', 'label': '端点能见度（取两端较差）',
                         'display': '无实况', 'actual': None, 'threshold': 5.0, 'unit': 'km',
                         'higherBetter': True, 'ratio': 0.0, 'pass': False,
                         'source': 'ABSENT', 'note': '两端都没有实况，按"未通过"处理'})
    if wind_val is not None:
        criteria.append({
            'key': 'wind', 'label': '端点风速（取两端较大）',
            'display': f'{wind_val:.1f} m/s', 'actual': round(wind_val, 1),
            'threshold': nation_ops.WIND_HIGH, 'unit': 'm/s', 'higherBetter': False,
            'ratio': round(min(1.0, wind_val / nation_ops.WIND_HIGH), 3),
            'pass': wind_val < nation_ops.WIND_HIGH, 'source': 'PUBLIC',
        })
    if radar_ok:
        hit = float(detour.get('hitKm') or 0.0)
        criteria.append({
            'key': 'echo', 'label': '航路穿强回波',
            'display': (f"穿 {hit:g} km" if detour else '无压线'),
            'actual': hit, 'threshold': 0.0, 'unit': 'km', 'higherBetter': False,
            'ratio': 1.0 if detour else 0.0,
            'pass': not detour, 'source': 'DERIVED',
        })
    else:
        criteria.append({'key': 'echo', 'label': '航路穿强回波', 'display': '回波不可用',
                         'actual': None, 'threshold': 0.0, 'unit': 'km', 'higherBetter': False,
                         'ratio': 0.0, 'pass': True, 'source': 'ABSENT',
                         'note': '本帧没取到回波，这一条不参与裁决'})
    criteria.append({
        'key': 'risk', 'label': '运行风险概率',
        'display': f"{flight['riskP']:.2f}（{flight['riskLevelLabel']}）",
        'actual': round(flight['riskP'], 3), 'threshold': nation_ops.RISK_HOLD,
        'unit': '', 'higherBetter': False,
        'ratio': round(min(1.0, flight['riskP'] / nation_ops.RISK_HOLD), 3),
        'pass': flight['riskP'] < nation_ops.RISK_HOLD, 'source': 'DERIVED',
    })
    if flight.get('pModel') is not None:
        criteria.append({
            'key': 'pmodel', 'label': '模型低能见概率（ml-v3）',
            'display': f"{flight['pModel']:.0%}", 'actual': round(flight['pModel'], 3),
            'threshold': nation_ops.MODEL_HOLD, 'unit': '', 'higherBetter': False,
            'ratio': round(min(1.0, flight['pModel'] / nation_ops.MODEL_HOLD), 3),
            'pass': flight['pModel'] < nation_ops.MODEL_HOLD, 'source': 'DERIVED',
        })

    # —— 期望损失：直飞 / 绕飞 / 延期三个方案的代价对比 ——
    # 三项加权，系数直接印在界面上，读者可以自己复算。
    #  风险损失 = 该方案下的飞行风险概率 × 1.0
    #  时间成本 = 延误分钟 ÷ 60 × 0.6
    #  能耗成本 = 航程增量 km × 0.02
    W_RISK, W_HOUR, W_KM = 1.0, 0.6, 0.02
    speed = float(flight.get('speedKmh') or 200.0)
    detour_km = float(flight.get('detourKm') or 0.0)
    # 压线时"直飞"不是可选项：穿强回波是**硬约束**，不参与代价比较。
    # 若还把它算进"最省"里，界面会推荐一条规则明令禁止的航路 —— 表里与裁决自相矛盾。
    direct_option = {
        'key': 'direct', 'label': '直飞（原航路）',
        'riskP': round(flight['riskP'], 3), 'delayMin': 0, 'extraKm': 0.0,
        'available': not detour,
        'note': ('保持当前航路' if not detour else '航路压强回波，直飞不成立（硬约束优先于代价比较）'),
    }
    # 绕飞：去掉回波那一项加成（_risk 里回波固定 +0.18），航程增 detourKm
    echo_surcharge = 0.18 if detour else 0.0
    detour_risk = round(max(0.05, flight['riskP'] - echo_surcharge), 3)
    detour_option = {
        'key': 'detour', 'label': '绕飞（外偏避让）',
        'riskP': detour_risk,
        'delayMin': round(detour_km / max(60.0, speed) * 60.0, 1),
        'extraKm': round(detour_km, 1),
        'available': bool(detour),
        'note': (f"原航路穿回波，外偏 {detour.get('shiftKm')} km" if detour
                 else '本帧无可用绕飞方案（航路未压线或周围无安全间隙）'),
    }
    # 延期：不承担飞行风险（风险项记 0），代价按 60 分钟计 —— 不假设天气会好转
    hold_option = {
        'key': 'hold', 'label': '延期（等窗口）',
        'riskP': 0.0, 'delayMin': 60, 'extraKm': 0.0,
        'available': True, 'note': '不飞则不承担飞行风险；按推迟 60 分钟计，不假设天气好转',
    }
    options = []
    for opt in (direct_option, detour_option, hold_option):
        cost = opt['riskP'] * W_RISK + opt['delayMin'] / 60.0 * W_HOUR + opt['extraKm'] * W_KM
        options.append({**opt, 'cost': round(cost, 3)})
    usable = [o for o in options if o['available']]
    best = min(usable, key=lambda o: o['cost'])['key'] if usable else None
    for opt in options:
        opt['recommended'] = opt['key'] == best
        opt['delta'] = round(opt['cost'] - (min(o['cost'] for o in usable) if usable else 0), 3)
    expected_loss = {'weights': {'risk': W_RISK, 'perHour': W_HOUR, 'perKm': W_KM},
                     'options': options, 'best': best,
                     'formula': '代价 = 风险概率×1.0 + 延误分钟÷60×0.6 + 航程增量km×0.02'}

    conclusion = f"{flight['decisionLabel']}：风险 {flight['riskP']:.2f}"
    if detour:
        conclusion += f"；原航路穿回波 {detour.get('hitKm')} km，已外偏 {detour.get('shiftKm')} km"
    else:
        conclusion += '；端点实况与航路回波均未触发改航条件'
    return {
        'status': 'OK', 'flightId': raw, 'minute': minute,
        'generatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'flight': {key: flight[key] for key in
                   ('id', 'callsign', 'fromName', 'toName', 'departAt', 'arriveAt',
                    'riskP', 'riskLevel', 'riskLevelLabel', 'decision', 'decisionLabel', 'altM')},
        'steps': steps,
        'criteria': criteria,
        'expectedLoss': expected_loss,
        'observed': {
            'fromName': flight['fromName'], 'toName': flight['toName'],
            'fromVis': vis(a.get('visM')), 'toVis': vis(b.get('visM')),
            'fromWind': a.get('windMps'), 'toWind': b.get('windMps'),
            'echo': band_text, 'echoTs': radar.get('ts'), 'weatherTs': weather_ts,
            'radarOk': radar_ok, 'hasDetour': bool(detour),
            'detourKm': round(detour_km, 1), 'speedKmh': speed,
            'exposureDirect': flight['exposure']['directMin'],
            'exposureDetour': flight['exposure']['detourMin'],
        },
        'conclusion': conclusion,
        'discipline': '本链为「规则派生」：实况来自公开源、回波来自公开拼图、概率由本系统阈值算出，'
                      '不是训练模型输出，也不是官方管制结论。',
    }


def journal(minute: int = 60, lookback: int = 40, level: str = 'nation',
            ident: str = '') -> Dict[str, Any]:
    """运行日志：从**当前这一刻的快照**里派生出的运行事件。

    为什么不存历史表：本系统的班次是解析式生成的（给定分钟，位置与裁决都是确定的），
    没有"历史"可存，也不需要存 —— 每一分钟都能重算出来。所以这里的做法是
    **在时间窗内扫一遍**，把进出场、绕飞、延期、停飞挑出来，带上发生的时刻。

    产出行的字段与旧会话日志（`/traffic/journal`）对齐，前端两本账共用一个表格 ——
    账本可以有两本，列不能有两套（否则同一个"绕飞"在两页里长得不一样）。
    """
    minute = max(0, min(1440, int(minute or 0)))
    lookback = max(5, min(180, int(lookback or 40)))
    start = max(0, minute - lookback)

    body = payload(level=level, ident=ident, minute=minute) if ident else payload(level=level, minute=minute)
    flights = body.get('flights') or []
    corridors = body.get('corridors') or []
    weather_meta = body.get('weatherMeta') or {}
    summary = body.get('summary') or {}
    radar = body.get('radar') or {}

    rows: List[Dict[str, Any]] = []

    def clock(m: float) -> str:
        # 与前端同口径：08:00 起算，跨零点加 +Nd
        raw = 8 * 60 + float(m or 0)
        day = int(raw // 1440)
        t = int(raw % 1440)
        text = f'{t // 60:02d}:{t % 60:02d}'
        return f'{text} +{day}d' if day > 0 else text

    for f in flights:
        name = f"{f.get('fromName')} → {f.get('toName')}"
        fid = f.get('id')
        dep = f.get('departMinute')
        arr = f.get('arriveMinute')
        decision = f.get('decision')
        # 起飞：发生在窗口内
        if dep is not None and start <= dep <= minute:
            rows.append({'minute': round(dep, 1), 'at': clock(dep), 'kind': 'SYSTEM',
                         'kindLabel': '运行事件', 'actionLabel': '起飞',
                         'name': name, 'flightId': fid,
                         'corridor': f.get('corridor'), 'decision': f.get('decision'),
                         'decisionLabel': f.get('decisionLabel'),
                         'detail': f"{f.get('callsign')} 于 {f.get('actualAt') or f.get('departAt')} 起飞，"
                                   f"高度 {f.get('altM')} m，许可 {f.get('clearance', {}).get('statusLabel') or '—'}"})
        # 到达：发生在窗口内
        if arr is not None and start <= arr <= minute:
            rows.append({'minute': round(arr, 1), 'at': clock(arr), 'kind': 'SYSTEM',
                         'kindLabel': '运行事件', 'actionLabel': '到达',
                         'name': name, 'flightId': fid,
                         'corridor': f.get('corridor'), 'decision': f.get('decision'),
                         'decisionLabel': f.get('decisionLabel'),
                         'detail': f"{f.get('callsign')} 到达，全程 {f.get('durationMin')} 分钟"})
        # 绕飞 / 延期 / 停飞：这是"当前状态"，时刻记在当前分钟
        if decision == 'DETOUR':
            rows.append({'minute': minute, 'at': clock(minute), 'kind': 'SYSTEM',
                         'kindLabel': '运行事件', 'actionLabel': '绕飞',
                         'name': name, 'flightId': fid,
                         'corridor': f.get('corridor'), 'decision': f.get('decision'),
                         'decisionLabel': f.get('decisionLabel'),
                         'detail': f"风险 {f.get('riskP')}；外偏后航程增加 {f.get('detourKm')} km"})
        if decision == 'HOLD':
            # 关键：延期可能来自"规则风险"也可能来自"模型低能见概率"。
            # 只写"风险 0.05（高）"会读不通 —— 0.05 是低分，档位是高的，因为档位看的是模型概率。
            pm = f.get('pModel')
            why = (f"模型低能见概率 {pm:.0%}" if (f.get('probSource') == 'MODEL' and pm is not None)
                   else f"规则风险 {f.get('riskP')}")
            rows.append({'minute': minute, 'at': clock(minute), 'kind': 'SYSTEM',
                         'kindLabel': '运行事件', 'actionLabel': '延期',
                         'name': name, 'flightId': fid,
                         'corridor': f.get('corridor'), 'decision': f.get('decision'),
                         'decisionLabel': f.get('decisionLabel'),
                         'detail': f"{why}（{f.get('riskLevelLabel')}档）；规则分 {f.get('riskP')}；"
                                   f"计划 {f.get('planAt')}，实际未放行"})
    for c in corridors:
        if c.get('borderBlocked'):
            rows.append({'minute': minute, 'at': clock(minute), 'kind': 'SYSTEM',
                         'kindLabel': '运行事件', 'actionLabel': '停飞',
                         'name': f"{c.get('fromName')} → {c.get('toName')}", 'flightId': None,
                         'detail': f"{c.get('id')} 受限停飞；航线 {c.get('lengthKm')} km"})

    # 数据源：把"这一屏的实况是什么时候的"也记一条，否则日志里只有结论没有来源
    if weather_meta.get('fetchedAt'):
        sources = weather_meta.get('sources') or {}
        src_text = '、'.join(f'{k} {v}' for k, v in sources.items()) or '—'
        rows.append({'minute': minute, 'at': clock(minute), 'kind': 'SOURCE',
                     'kindLabel': '数据源', 'actionLabel': '气象实况',
                     'name': f"{weather_meta.get('cities') or summary.get('weatherCities') or 0} 城",
                     'flightId': None,
                     'detail': (f"来源 {src_text}；抓取于 {weather_meta.get('fetchedAt')}"
                                + ('；已过期快照' if weather_meta.get('expiredSnapshot') else '')
                                + ('；数据偏旧' if weather_meta.get('stale') else ''))})
    rows.append({'minute': minute, 'at': clock(minute), 'kind': 'SOURCE',
                 'kindLabel': '数据源', 'actionLabel': '雷达回波',
                 'name': '全国拼图' if radar.get('available') else '不可用',
                 'flightId': None,
                 'detail': (f"帧时刻 {radar.get('ts')}；三档轮廓已按面积排序取前 200 片"
                            if radar.get('available') else '本帧未取到回波，绕飞与暴露结论不成立')})

    rows.sort(key=lambda r: (-float(r['minute']), str(r['actionLabel'])))
    counts = {'SYSTEM': 0, 'SOURCE': 0, 'MANUAL': 0, 'EXPORT': 0}
    for r in rows:
        counts[r['kind']] = counts.get(r['kind'], 0) + 1
    return {
        'status': 'OK',
        'minute': minute,
        'window': [start, minute],
        'level': level,
        'ident': ident,
        'rows': rows[:400],
        'counts': counts,
        'note': ('这些行由当前分钟的快照**重算**得出：班次是解析式生成的，没有历史表，'
                 '也不需要历史表。窗口内的起飞与到达是"发生过"，绕飞/延期/停飞是"此刻仍如此"。'),
    }


def _model_card(model_probs: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """模型卡：ml-v2（沈阳/长春/哈尔滨三站，不能外推）+ ml-v3（全国，在这 319 城上训练的）。"""
    card = nation_ops.model_card()
    try:
        from ml import national_model
        national = national_model.card()
    except Exception:  # noqa: BLE001
        national = {'available': False}
    card['nationalModel'] = national
    if national.get('available'):
        card['national']['applicable'] = True
        card['national']['coverage'] = (f"全国 {national.get('provenance', {}).get('cities')} 城 · "
                                        f"训练样本 {national.get('provenance', {}).get('samples')} 条")
        card['national']['note'] = national.get('provenance', {}).get('caveat')
        # probSource 必须反映"这一帧到底有没有拿到概率"，不能写死 MODEL。
        # 写死的话，冷启动或限流时界面会说"用模型算的"，而实际一个概率都没有 ——
        # DERIVED 这个标签就失去了区分模型与规则的能力。
        if model_probs:
            card['fallback'] = {'probSource': 'MODEL',
                                'note': '端点两城的模型概率按独立事件合并，再与规则分各自把关'}
        else:
            card['fallback'] = {
                'probSource': 'RULE',
                'note': ('全国模型概率本帧未取到，已退回规则分（不含模型分量）'
                         + (f'：{_MODEL_ERROR}' if _MODEL_ERROR else '')),
                'error': _MODEL_ERROR or '未取到',
            }
    cards = sorted((model_probs or {}).values(), reverse=True)
    card['liveCoverage'] = {
        'cities': len(model_probs or {}),
        'maxP': cards[0] if cards else None,
        'medianP': cards[len(cards) // 2] if cards else None,
    }
    return card


def _pulse_locked() -> Dict[str, Any]:
    """状态心跳：只回"有没有东西变了"，不回整份数据。

    推送的意义不是把 500 KB 反复塞给前端，而是让屏幕**不用轮询也知道**雷达换帧了、
    实况更新了、模型换版了。前端收到变化再按需拉取。
    """
    radar = _radar()
    weather = _city_weather_payload()
    version = None
    try:
        from ml import national_model
        card = national_model.card()
        version = card.get('version') if card.get('available') else None
    except Exception:  # noqa: BLE001
        version = None
    return {
        'at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'radarTs': radar.get('ts'),
        'radarBands': sum(len(v or []) for v in (_radar_clipped(radar.get('ts') or 'none') or {}).values()),
        'weatherAt': weather.get('fetchedAt'),
        'modelVersion': version,
        'cities': len(_city_rows()),
    }


# shapely / GEOS 不是线程安全的：网关预热的线程和第一个真实请求撞在一起时，
# 两边同时进 make_valid / buffer，会直接把进程打成段错误（实测 exit 139）。
# 所以对外入口串行化 —— 命中 lru_cache 时这一步只是拿一次锁，代价可以忽略。
_NATION_LOCK = threading.RLock()


def payload(level: str = 'nation', ident: Optional[str] = None, minute: int = 60,
            virtual: bool = False):
    with _NATION_LOCK:
        return _payload_locked(level, ident, minute, virtual)


def flights_payload(level: str = 'nation', ident: Optional[str] = None, minute: int = 60,
                    virtual: bool = False):
    with _NATION_LOCK:
        return _flights_payload_locked(level, ident, minute, virtual)


def pulse() -> Dict[str, Any]:
    """心跳同样要串行：它内部要算雷达环数（shapely），和主请求并发就会崩进程。"""
    with _NATION_LOCK:
        return _pulse_locked()


def evidence(flight_id: str, minute: int = 60) -> Dict[str, Any]:
    with _NATION_LOCK:
        return _evidence_locked(flight_id, minute)
