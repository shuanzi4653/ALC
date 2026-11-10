# -*- coding: utf-8 -*-
"""公开雷达回波（免密钥）：取拼图瓦片 → 按 dBZ 分级 → 转成经纬度多边形。

数据源
------
`https://api.rainviewer.com/public/weather-maps.json`（公开、免密钥）给出最近若干帧的
瓦片路径，瓦片是**墨卡托**的透明 PNG，只有回波、没有底图，因此像素可直接反算经纬度，
不需要额外配准。中国气象局（CMA）的 GIS 瓦片接口需要凭据，这里作为"有凭据时优先"的分支保留。

分级（与 `traffic/radar_field.py` 一致）
----------------------------------------
WEAK 15–35 dBZ / CONVECTIVE 35–45 / STRONG 45–60。颜色判断按反射率标准色：
绿=弱、黄=对流、橙红=强。没有 alpha 的像素不算回波。

产物
----
`frame = {available, ts, bands:{WEAK:[ring...], CONVECTIVE:[...], STRONG:[...]}, cells, coverage}`
ring 是 [[lon,lat], ...] 的闭合环，已抽稀（0.03°），可直接画 SVG 多边形。
"""
from __future__ import annotations

import concurrent.futures
import json
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

META_URL = 'https://api.rainviewer.com/public/weather-maps.json'
CACHE_DIR = Path(__file__).resolve().parents[2] / '.run' / 'radar'
TILE_ZOOM = 5                    # 5 级：单瓦片 1.25°，回波边缘才有细节
GRID_DEG = 0.14                  # 聚合网格：0.14° ≈ 15 km，接近回波胞的真实尺度
SIMPLIFY_DEG = 0.05              # 多边形抽稀，避免几百个点的锯齿
ALPHA_FLOOR = 40
TTL_SECONDS = 600.0
TIMEOUT_SECONDS = 20.0
USER_AGENT = 'ALC-tianchuang/1.0.1 (radar echo; contact: project maintainer)'
BBOX = (73.0, 15.5, 136.0, 54.5)  # 与全国视图一致
ROUND_PIXELS = 2.0                # 每 2 像素取一个点

_lock = threading.Lock()
_memory: Dict[str, Any] = {'value': None, 'expires': 0.0}


# ---------------------------------------------------------------- 瓦片与像素

def _lonlat_of(z: int, x: int, y: int, px: int, py: int, size: int = 256) -> Tuple[float, float]:
    n = 2 ** z
    lon = (x + px / size) / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * (y + py / size) / n)))
    return lon, math.degrees(lat_rad)


def _tile_range(z: int, bbox: Tuple[float, float, float, float]) -> List[Tuple[int, int]]:
    lon0, lat0, lon1, lat1 = bbox
    n = 2 ** z

    def xt(lon: float) -> int:
        return max(0, min(n - 1, int((lon + 180.0) / 360.0 * n)))

    def yt(lat: float) -> int:
        rad = math.radians(lat)
        return max(0, min(n - 1, int((1 - math.asinh(math.tan(rad)) / math.pi) / 2 * n)))

    xs = range(xt(lon0), xt(lon1) + 1)
    ys = range(yt(lat1), yt(lat0) + 1)
    return [(x, y) for x in xs for y in ys]


def _band_of(rgb: Tuple[int, int, int]) -> Optional[str]:
    r, g, b = rgb
    # 反射率标准配色：绿→黄→橙→红。白色（云顶/雪）不算回波主体，按弱回波处理。
    if r < 60 and g < 90 and b < 90:
        return None
    if r >= 200 and g >= 200 and b >= 200:
        return 'WEAK'
    if r >= 180:
        return 'STRONG'
    if r >= 140 and g >= 110:
        return 'CONVECTIVE'
    if g >= 110:
        return 'WEAK'
    if b >= 120 and r < 120:
        return None      # 蓝色是降水外的杂波，不计
    return None


def _cells_from_tile(image, z: int, x: int, y: int) -> List[Tuple[float, float, str]]:
    """把一张瓦片里"有回波"的像素聚成 GRID_DEG 网格，返回 [(lon, lat, band)]。"""
    width, height = image.size
    step = max(1, int(ROUND_PIXELS))
    buckets: Dict[Tuple[int, int], Tuple[int, int, int]] = {}
    pixels = image.load()
    for py in range(0, height, step):
        for px in range(0, width, step):
            r, g, b, a = pixels[px, py]
            if a < ALPHA_FLOOR:
                continue
            band = _band_of((r, g, b))
            if band is None:
                continue
            lon, lat = _lonlat_of(z, x, y, px, py, width)
            key = (int(lon // GRID_DEG), int(lat // GRID_DEG))
            current = buckets.get(key)
            rank = {'WEAK': 1, 'CONVECTIVE': 2, 'STRONG': 3}
            if current is None or rank[band] > rank[current[2]]:
                buckets[key] = (key[0], key[1], band)
    return [(cx * GRID_DEG, cy * GRID_DEG, band) for cx, cy, band in buckets.values()]





# ---------------------------------------------------------------- 多边形

def _rings_of(cells: List[Tuple[float, float]]) -> List[List[List[float]]]:
    import shapely
    from shapely.geometry import box

    if not cells:
        return []
    boxes = [box(lon, lat, lon + GRID_DEG, lat + GRID_DEG) for lon, lat in cells]
    merged = shapely.union_all(boxes)
    merged = merged.simplify(SIMPLIFY_DEG, preserve_topology=True)
    parts = getattr(merged, 'geoms', [merged])
    rings: List[List[List[float]]] = []
    for part in parts:
        if part.is_empty or part.area <= 0:
            continue
        if part.area < 0.08:          # 丢掉单个格子的碎点，图上才不是满屏芝麻
            continue
        coords = [[round(x, 3), round(y, 3)] for x, y in part.exterior.coords]
        if len(coords) >= 4:
            rings.append(coords)
    rings.sort(key=lambda ring: -abs(_ring_area(ring)))
    return rings[:45]


def _ring_area(ring: List[List[float]]) -> float:
    total = 0.0
    for index in range(len(ring) - 1):
        x1, y1 = ring[index]
        x2, y2 = ring[index + 1]
        total += x1 * y2 - x2 * y1
    return total / 2.0


# ---------------------------------------------------------------- 帧

def _meta() -> Dict[str, Any]:
    response = httpx.get(META_URL, timeout=TIMEOUT_SECONDS, headers={'User-Agent': USER_AGENT})
    response.raise_for_status()
    return response.json()


def _latest_frame(meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    radar = (meta or {}).get('radar') or {}
    past = radar.get('past') or []
    if not past:
        return None
    frame = past[-1]
    return {'time': frame['time'], 'path': frame['path'], 'host': meta.get('host', 'https://tilecache.rainviewer.com')}


def fetch(force: bool = False) -> Dict[str, Any]:
    now = time.monotonic()
    with _lock:
        if not force and _memory['value'] and now < _memory['expires']:
            return _memory['value']

    started = time.time()
    try:
        frame = _latest_frame(_meta())
        if frame is None:
            raise RuntimeError('没有可用雷达帧')
    except Exception as exc:  # noqa: BLE001
        return _empty(f'取帧失败：{str(exc)[:90]}')

    stamp = datetime.fromtimestamp(frame['time'], tz=timezone.utc).strftime('%Y%m%d%H%M')
    cache_file = CACHE_DIR / f'{stamp}-z{TILE_ZOOM}.json'
    if cache_file.exists() and not force:
        try:
            cached = json.loads(cache_file.read_text(encoding='utf-8'))
            with _lock:
                _memory.update({'value': cached, 'expires': now + TTL_SECONDS})
            return cached
        except Exception:  # noqa: BLE001 - 缓存坏了就重算
            pass

    try:
        from PIL import Image
        import io as _io
    except Exception as exc:  # noqa: BLE001
        return _empty(f'缺少图像库：{str(exc)[:60]}')

    tiles = _tile_range(TILE_ZOOM, BBOX)
    cells: Dict[str, List[Tuple[float, float]]] = {'WEAK': [], 'CONVECTIVE': [], 'STRONG': []}
    fetched = 0

    def grab(pair: Tuple[int, int]):
        x, y = pair
        url = f"{frame['host']}{frame['path']}/256/{TILE_ZOOM}/{x}/{y}/4/1_1.png"
        try:
            response = httpx.get(url, timeout=TIMEOUT_SECONDS, headers={'User-Agent': USER_AGENT})
            if response.status_code != 200 or not response.content:
                return None
            image = Image.open(_io.BytesIO(response.content)).convert('RGBA')
            return _cells_from_tile(image, TILE_ZOOM, x, y)
        except Exception:  # noqa: BLE001 - 单瓦片失败跳过
            return None

    # 12 张瓦片串行要 8–11 s，并发取能压到 2 s 内
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for rows in pool.map(grab, tiles):
            if rows is None:
                continue
            fetched += 1
            for lon, lat, band in rows:
                cells[band].append((lon, lat))

    bands = {band: _rings_of(rows) for band, rows in cells.items()}
    total_cells = sum(len(rows) for rows in cells.values())
    value = {
        'available': True,
        'source': '公开雷达拼图（RainViewer 公共接口，免密钥；瓦片为墨卡托，像素直接反算经纬度）',
        'ts': datetime.fromtimestamp(frame['time'], tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'zoom': TILE_ZOOM,
        'gridDeg': GRID_DEG,
        'tiles': {'asked': len(tiles), 'fetched': fetched},
        'cells': total_cells,
        'bands': bands,
        'counts': {band: len(rings) for band, rings in bands.items()},
        'coverage': round(100.0 * total_cells * (GRID_DEG ** 2) / _bbox_area(BBOX), 2),
        'elapsedMs': int((time.time() - started) * 1000),
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        cache_file.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    except Exception:  # noqa: BLE001
        pass
    with _lock:
        _memory.update({'value': value, 'expires': now + TTL_SECONDS})
    return value


def _bbox_area(bbox: Tuple[float, float, float, float]) -> float:
    lon0, lat0, lon1, lat1 = bbox
    return max(1e-6, (lon1 - lon0) * (lat1 - lat0))


def _empty(reason: str) -> Dict[str, Any]:
    return {'available': False, 'error': reason, 'ts': None,
            'bands': {'WEAK': [], 'CONVECTIVE': [], 'STRONG': []},
            'counts': {'WEAK': 0, 'CONVECTIVE': 0, 'STRONG': 0}, 'cells': 0, 'coverage': 0.0}
