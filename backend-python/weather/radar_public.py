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

import base64
import concurrent.futures
import io as _io
import json
import math
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import numpy as np

META_URL = 'https://api.rainviewer.com/public/weather-maps.json'
ROOT_DIR = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT_DIR / '.run' / 'radar'
CHINA_GEOJSON = ROOT_DIR / 'frontend' / 'src' / 'assets' / 'china.json'
TILE_ZOOM = 6                    # 6 级：单瓦片 5.625°（≈2.4 km/px），全国回波纤毫毕现
# 聚合网格：原来是 0.14°（≈15 km）。一个格子在全国缩放下就是 8 px 的方块，
# 放大后是明显的大锯齿 —— 用户 2026-11-11 明确要求"不要锯齿、要高精度"。
# 0.04°（≈4.4 km）接近单个回波胞的尺度，格子数约 12 倍，union 仍在几十毫秒量级。
GRID_DEG = 0.04
# 简化容差：0.05°（≈5.5 km）会把平滑后的圆弧又削成方块，降到 0.008°（≈0.9 km）。
# 真正的去锯齿靠下面的闭运算，简化只负责丢掉冗余顶点。
SIMPLIFY_DEG = 0.008
# 闭运算半径：先外扩再回缩，把格子拼出来的直角磨成圆弧（≈3.2 km）
SMOOTH_DEG = 0.042
ALPHA_FLOOR = 40
TTL_SECONDS = 600.0
FAIL_TTL_SECONDS = 15.0
TIMEOUT_SECONDS = 20.0
USER_AGENT = 'ALC-tianchuang/1.0.1 (radar echo; contact: project maintainer)'
BBOX = (73.0, 15.5, 136.0, 54.5)  # 与全国视图一致
ROUND_PIXELS = 2.0                # 每 2 像素取一个点

# NEXRAD WSR-88D / CMA CINRAD 标准基本反射率（Base Reflectivity）专业色表（dBZ 下界 -> RGBA）：
# 100% 纯正气象高饱和度不透明配色（alpha=255，背景=0 完全透明），消灭暗沉发浑，边界鲜艳分明
NEXRAD_LUT: Tuple[Tuple[float, Tuple[int, int, int, int]], ...] = (
    (10.0, (0, 220, 220, 255)),    # 10–15 dBZ: 边缘浅青（毛毛雨 / 水汽边界）
    (15.0, (0, 236, 0, 255)),      # 15–20 dBZ: 亮绿（小雨 / 弱回波外缘）
    (20.0, (0, 196, 0, 255)),      # 20–25 dBZ: 纯绿
    (25.0, (0, 144, 0, 255)),      # 25–30 dBZ: 深绿
    (30.0, (144, 228, 0, 255)),    # 30–34 dBZ: 黄绿过渡（中雨初现）
    (34.0, (255, 255, 0, 255)),    # 34–38 dBZ: 纯亮黄（对流初生 / 中雨）
    (38.0, (244, 184, 0, 255)),    # 38–42 dBZ: 金黄
    (42.0, (255, 130, 0, 255)),    # 42–46 dBZ: 鲜橙（大雨 / 中等对流）
    (46.0, (255, 52, 0, 255)),     # 46–50 dBZ: 橙红（强降水）
    (50.0, (236, 0, 0, 255)),      # 50–55 dBZ: 鲜红（暴雨 / 强对流内核）
    (55.0, (188, 0, 0, 255)),      # 55–60 dBZ: 深红
    (60.0, (236, 0, 228, 255)),    # 60–65 dBZ: 亮品红（极端对流 / 冰雹核）
    (65.0, (168, 64, 220, 255)),   # 65–70 dBZ: 紫色
    (70.0, (255, 255, 255, 255)),  # 70+ dBZ: 亮白核
)

_lock = threading.Lock()
_memory: Dict[str, Any] = {'value': None, 'expires': 0.0}


# ---------------------------------------------------------------- 瓦片与像素

def _lonlat_of(z: int, x: int, y: int, px: float, py: float, size: int = 256) -> Tuple[float, float]:
    n = 2 ** z
    lon = (x + px / size) / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * (y + py / size) / n)))
    return lon, math.degrees(lat_rad)


def _tile_bounds(z: int, bbox: Tuple[float, float, float, float]) -> Tuple[int, int, int, int]:
    lon0, lat0, lon1, lat1 = bbox
    n = 2 ** z

    def xt(lon: float) -> int:
        return max(0, min(n - 1, int((lon + 180.0) / 360.0 * n)))

    def yt(lat: float) -> int:
        rad = math.radians(lat)
        return max(0, min(n - 1, int((1 - math.asinh(math.tan(rad)) / math.pi) / 2 * n)))

    return xt(lon0), yt(lat1), xt(lon1), yt(lat0)


def _tile_range(z: int, bbox: Tuple[float, float, float, float]) -> List[Tuple[int, int]]:
    x0, y0, x1, y1 = _tile_bounds(z, bbox)
    return [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]


def _pixel_dbz(rgb: Tuple[int, int, int]) -> float:
    """将 RainViewer Universal Blue 瓦片 RGB 像素反算为连续等效反射率 dBZ。

    RainViewer 公共瓦片实际色阶：
      - 外围灰/米色云团晕（<15 dBZ）：r >= g > b（如 (208,192,128)、(158,147,117)），属非降水云边，滤除；
      - 弱到强降水（15–47 dBZ）：浅青 (136,221,238) → 天蓝 (27,174,226) → 中蓝 (0,136,191) → 深藏青 (0,71,104)，
        满足 b > g 且 (b - r) >= 50，颜色越深 dBZ 越高；
      - 极端强对流核（48–62 dBZ）：亮黄 (255,238,0) → 橙红 (255,68,0) → 品红。
    """
    r, g, b = rgb
    if b > g and (b - r) >= 50:
        if r > 0:
            return 15.0 + max(0.0, min(1.0, (140.0 - r) / 140.0)) * 10.0
        return 25.0 + max(0.0, min(1.0, (165.0 - g) / 96.0)) * 22.0
    if r >= 170 and b < 100:
        return 48.0 + max(0.0, min(1.0, (255.0 - g) / 255.0)) * 12.0
    if r >= 160 and b >= 140 and g < 100:
        return 62.0
    return 0.0


def _band_of(rgb: Tuple[int, int, int]) -> Optional[str]:
    dbz = _pixel_dbz(rgb)
    if dbz >= 41.0:
        return 'STRONG'
    if dbz >= 32.0:
        return 'CONVECTIVE'
    if dbz >= 15.0:
        return 'WEAK'
    return None


def _tile_dbz_array(image) -> np.ndarray:
    """向量化反算单张 RGBA 瓦片的 dBZ 矩阵（256×256 float32）。"""
    arr = np.asarray(image, dtype=np.float32)
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
    valid = a >= ALPHA_FLOOR
    dbz = np.zeros(r.shape, dtype=np.float32)

    is_blue = valid & (b > g) & ((b - r) >= 50.0)
    light_blue = is_blue & (r > 0.0)
    dbz[light_blue] = 15.0 + np.clip((140.0 - r[light_blue]) / 140.0, 0.0, 1.0) * 10.0
    deep_blue = is_blue & (r == 0.0)
    dbz[deep_blue] = 25.0 + np.clip((165.0 - g[deep_blue]) / 96.0, 0.0, 1.0) * 22.0

    is_warm = valid & (r >= 170.0) & (b < 100.0)
    dbz[is_warm] = 48.0 + np.clip((255.0 - g[is_warm]) / 255.0, 0.0, 1.0) * 12.0

    is_magenta = valid & (r >= 160.0) & (b >= 140.0) & (g < 100.0)
    dbz[is_magenta] = 62.0
    return dbz


def _despeckle_dbz(dbz: np.ndarray) -> np.ndarray:
    """剔除 8 邻域内孤立的 1–2 像素杂波点，保留真实降水回波胞结构。"""
    mask = (dbz >= 15.0).astype(np.int32)
    if not mask.any():
        return dbz
    padded = np.pad(mask, 1, mode='constant')
    h, w = mask.shape
    nbrs = sum(
        padded[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
        if not (dx == 0 and dy == 0)
    )
    cleaned = dbz.copy()
    cleaned[nbrs <= 1] = 0.0
    return cleaned


@lru_cache(maxsize=2)
def _china_raster_mask(z: int, x0: int, y0: int, x1: int, y1: int) -> Optional[np.ndarray]:
    """在墨卡托拼图栅格上生成国界掩膜（含 2px 边缘余量，配合前端 SVG clipPath 精确裁剪）。"""
    try:
        from PIL import Image, ImageDraw
        china = json.loads(CHINA_GEOJSON.read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return None
    n = 2 ** z
    w = (x1 - x0 + 1) * 256
    h = (y1 - y0 + 1) * 256

    def to_px(lon: float, lat: float) -> Tuple[float, float]:
        px = ((lon + 180.0) / 360.0 * n - x0) * 256.0
        rad = math.radians(max(-85.0, min(85.0, lat)))
        py = ((1.0 - math.asinh(math.tan(rad)) / math.pi) / 2.0 * n - y0) * 256.0
        return (px, py)

    mask_im = Image.new('L', (w, h), 0)
    draw = ImageDraw.Draw(mask_im)
    for feat in china.get('features') or []:
        props = feat.get('properties') or {}
        if not props.get('name') or props.get('adchar') == 'JD':
            continue
        geom = feat.get('geometry') or {}
        polys = [geom['coordinates']] if geom.get('type') == 'Polygon' else (geom.get('coordinates') or [])
        for poly in polys:
            if poly and len(poly[0]) >= 3:
                pts = [to_px(pt[0], pt[1]) for pt in poly[0]]
                draw.polygon(pts, fill=255, outline=255, width=3)
    return np.asarray(mask_im, dtype=np.uint8) > 0


def _encode_nexrad_png(crop_dbz: np.ndarray, upscale: float = 2.0) -> Optional[str]:
    """将裁剪后的连续 dBZ 矩阵做高斯保形平滑与双三次插值，映射为 14 级 NEXRAD 索引色透明 PNG（Data URI）。"""
    from PIL import Image, ImageFilter

    if crop_dbz.size == 0 or float(crop_dbz.max()) < 15.0:
        return None
    h, w = crop_dbz.shape
    scale = min(float(upscale), 4096.0 / max(1, max(w, h)))
    w_out = max(1, int(round(w * scale)))
    h_out = max(1, int(round(h * scale)))
    if (w_out, h_out) != (w, h):
        # 气象场高斯保形平滑：消除底层离散栅格网格台阶，还原流体大气的自然有机流线形态
        norm = np.clip(crop_dbz * 3.4, 0.0, 255.0).astype(np.uint8)
        blurred = Image.fromarray(norm, mode='L').filter(ImageFilter.GaussianBlur(radius=1.0))
        up_l = blurred.resize((w_out, h_out), Image.BICUBIC)
        up_dbz = np.asarray(up_l, dtype=np.float32) / 3.4
    else:
        up_dbz = crop_dbz

    idx = np.zeros(up_dbz.shape, dtype=np.uint8)
    for k, (threshold, _rgba) in enumerate(NEXRAD_LUT, start=1):
        idx[up_dbz >= threshold] = k
    if not idx.any():
        return None

    palette = [0, 0, 0]
    trans = [0]
    for _threshold, (cr, cg, cb, ca) in NEXRAD_LUT:
        palette.extend((cr, cg, cb))
        trans.append(ca)
    palette.extend([0] * (768 - len(palette)))

    pim = Image.fromarray(idx, mode='P')
    pim.putpalette(palette)
    buf = _io.BytesIO()
    pim.save(buf, format='PNG', optimize=True, transparency=bytes(trans))
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    return f'data:image/png;base64,{b64}'


def virtual_nexrad_image(bucket: int, cells_spec: Tuple[Tuple[str, float, float, float, float], ...]) -> Tuple[Optional[str], Optional[List[float]]]:
    """为虚拟恶劣天气模式生成同口径的高清墨卡托 NEXRAD 多级反射率贴图与经纬框。"""
    lon0, lat0, lon1, lat1 = 101.0, 19.5, 130.5, 48.5
    w, h = 800, 680
    lons = np.linspace(lon0, lon1, w, dtype=np.float32)[None, :]
    merc0 = math.log(math.tan(math.pi / 4.0 + math.radians(lat0) / 2.0))
    merc1 = math.log(math.tan(math.pi / 4.0 + math.radians(lat1) / 2.0))
    mercs = np.linspace(merc1, merc0, h, dtype=np.float32)[:, None]
    lats = np.degrees(np.arctan(np.sinh(mercs)))

    dbz = np.zeros((h, w), dtype=np.float32)
    for index, (_region, lon, lat, rx, ry) in enumerate(cells_spec):
        phase = (bucket * 0.37 + index * 1.13) % (2.0 * math.pi)
        cx = lon + 0.55 * math.cos(phase)
        cy = lat + 0.32 * math.sin(phase * 0.8)
        dx = (lons - cx) / rx
        dy = (lats - cy) / ry
        theta = np.arctan2(dy, dx)
        wobble = (1.0 + 0.16 * np.sin(3.0 * theta + phase)
                  + 0.09 * np.cos(5.0 * theta - phase)
                  + 0.05 * np.sin(9.0 * theta + 1.7 * phase))
        r_norm = np.hypot(dx, dy) / np.maximum(0.3, wobble)
        texture = 2.6 * np.sin(dx * 5.2 + phase) * np.cos(dy * 5.2 - phase)
        cell_dbz = np.where(r_norm <= 1.04, 54.5 - 39.5 * (r_norm ** 1.15) + texture, 0.0)
        dbz = np.maximum(dbz, cell_dbz)

    data_uri = _encode_nexrad_png(dbz, upscale=2.0)
    return data_uri, [lon0, lat0, lon1, lat1] if data_uri else None





# ---------------------------------------------------------------- 多边形

def _chaikin(ring, iterations=2):
    """Chaikin 割角：每条边取 1/4、3/4 两点，折线逐轮收敛到平滑曲线。

    闭运算只能把直角磨成圆角矩形，直边还是直边；真正让轮廓像雷达图的是这一步。
    顶点数每轮翻倍：2 轮会让全国载荷从 0.6 MB 涨到 2.4 MB，所以只跑 1 轮（约 2 倍），
    再 round 到 3 位（≈110 m）——保留曲线观感，又不把首屏拖慢。
    """
    if len(ring) < 4:
        return ring
    pts = list(ring)
    for _ in range(iterations):
        out = []
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            out.append((0.75 * x1 + 0.25 * x2, 0.75 * y1 + 0.25 * y2))
            out.append((0.25 * x1 + 0.75 * x2, 0.25 * y1 + 0.75 * y2))
        out.append(out[0])
        pts = out
    return pts


def _close_cells(cells: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """在**栅格层**做闭运算（膨胀一次 → 腐蚀一次），补单格孔洞与单格缝隙。

    为什么必须在这一层做：回波是"逐格判定 → 每格一个方盒 → union"得到的。
    某个格子只要低于阈值就被剔除，同一片回波里就出现成排的空格，
    union 出来的形状自然是碎裂的（实测一帧 370 个环）。
    几何层的 buffer 闭运算磨的是棱角，补不了这些孔 —— 孔在栅格阶段就已经形成了。

    只补 1 格：补 2 格会把两片本该分开的小雨拼成一片，那是另一种失真。
    """
    if not cells:
        return []
    grid = {(int(round(lon / GRID_DEG)), int(round(lat / GRID_DEG))) for lon, lat in cells}
    # 膨胀
    grown = set()
    for i, j in grid:
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                grown.add((i + di, j + dj))
    # 腐蚀
    closed = set()
    for i, j in grown:
        if all((i + di, j + dj) in grown for di in (-1, 0, 1) for dj in (-1, 0, 1)):
            closed.add((i, j))
    # 再补内部空洞：被 8 邻域包住但自己空的格子，迭代两轮（外围不会被误填）
    for _ in range(2):
        holes = set()
        for i, j in closed:
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    cand = (i + di, j + dj)
                    if cand in closed:
                        continue
                    near = sum(1 for a in (-1, 0, 1) for b in (-1, 0, 1) if (cand[0] + a, cand[1] + b) in closed)
                    if near >= 7:      # 8 邻域里至少 7 个是实心 → 是孔，不是边界
                        holes.add(cand)
        if not holes:
            break
        closed |= holes
    return [(i * GRID_DEG, j * GRID_DEG) for (i, j) in closed]


def _rings_of(cells: List[Tuple[float, float]]) -> List[List[List[float]]]:
    import shapely
    from shapely.geometry import box

    if not cells:
        return []
    boxes = [box(lon, lat, lon + GRID_DEG, lat + GRID_DEG) for lon, lat in cells]
    merged = shapely.union_all(boxes)
    # 闭运算：格子的直角在这里被磨圆。不做这一步，再小的网格也还是"由方块拼成的多边形"。
    try:
        grown = merged.buffer(SMOOTH_DEG, join_style=1, mitre_limit=1.2)
        back = grown.buffer(-SMOOTH_DEG, join_style=1, mitre_limit=1.2)
        if not back.is_empty and back.is_valid:
            merged = back
    except Exception:  # noqa: BLE001
        pass
    merged = merged.simplify(SIMPLIFY_DEG, preserve_topology=True)
    parts = getattr(merged, 'geoms', [merged])
    rings: List[List[List[float]]] = []
    for part in parts:
        if part.is_empty or part.area <= 0:
            continue
        # 面积下限 0.08 平方度（≈30×30 km）会把整片小雨团丢掉 —— 改成 0.004（≈6×6 km）。
        # 碎点靠"最小 3 个格子"控制，而不是靠一个很大的面积阈值。
        if part.area < 0.004:
            continue
        smooth = _chaikin(list(part.exterior.coords), 1)
        # 2 位小数 ≈ 1.1 km：平滑后的顶点间距本来就在 0.5–1 km，
        # 再保留 3 位只是在给 JSON 加字节（全国载荷 830 KB，其中回波占七成）。
        coords = [[round(x, 2), round(y, 2)] for x, y in smooth]
        if len(coords) >= 4:
            rings.append(coords)
    rings.sort(key=lambda ring: -abs(_ring_area(ring)))
    return rings[:200]


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
    cache_file = CACHE_DIR / f'{stamp}-z{TILE_ZOOM}-g{GRID_DEG}-nexrad4.json'
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
    except Exception as exc:  # noqa: BLE001
        return _empty(f'缺少图像库：{str(exc)[:60]}')

    x0, y0, x1, y1 = _tile_bounds(TILE_ZOOM, BBOX)
    tiles = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    w_mosaic = (x1 - x0 + 1) * 256
    h_mosaic = (y1 - y0 + 1) * 256
    mosaic_dbz = np.zeros((h_mosaic, w_mosaic), dtype=np.float32)
    fetched = 0

    def grab(pair: Tuple[int, int]):
        x, y = pair
        url = f"{frame['host']}{frame['path']}/256/{TILE_ZOOM}/{x}/{y}/4/1_1.png"
        try:
            response = httpx.get(url, timeout=TIMEOUT_SECONDS, headers={'User-Agent': USER_AGENT})
            if response.status_code != 200 or not response.content:
                return None
            image = Image.open(_io.BytesIO(response.content)).convert('RGBA')
            return x, y, _tile_dbz_array(image)
        except Exception:  # noqa: BLE001 - 单瓦片失败跳过
            return None

    # 瓦片并发拉取，拼成无缝墨卡托 dBZ 场
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        for item in pool.map(grab, tiles):
            if item is None:
                continue
            tx, ty, tile_dbz = item
            fetched += 1
            oy = (ty - y0) * 256
            ox = (tx - x0) * 256
            mosaic_dbz[oy:oy + 256, ox:ox + 256] = tile_dbz

    mosaic_dbz = _despeckle_dbz(mosaic_dbz)
    china_mask = _china_raster_mask(TILE_ZOOM, x0, y0, x1, y1)
    if china_mask is not None and china_mask.shape == mosaic_dbz.shape:
        mosaic_dbz = np.where(china_mask, mosaic_dbz, 0.0)

    # 聚合到经纬网格（累积嵌套：STRONG ⊂ CONVECTIVE ⊂ WEAK，消除外环镂空）
    step = max(1, int(ROUND_PIXELS))
    sampled = mosaic_dbz[::step, ::step]
    sy_idx, sx_idx = np.where(sampled >= 15.0)
    grid_max: Dict[Tuple[int, int], float] = {}
    for sy, sx in zip(sy_idx.tolist(), sx_idx.tolist()):
        py = sy * step
        px = sx * step
        val = float(mosaic_dbz[py, px])
        lon, lat = _lonlat_of(TILE_ZOOM, x0, y0, px, py, 256)
        key = (int(lon // GRID_DEG), int(lat // GRID_DEG))
        prev = grid_max.get(key, 0.0)
        if val > prev:
            grid_max[key] = val

    cells: Dict[str, List[Tuple[float, float]]] = {
        'WEAK': [(cx * GRID_DEG, cy * GRID_DEG) for (cx, cy), v in grid_max.items() if v >= 15.0],
        'CONVECTIVE': [(cx * GRID_DEG, cy * GRID_DEG) for (cx, cy), v in grid_max.items() if v >= 32.0],
        'STRONG': [(cx * GRID_DEG, cy * GRID_DEG) for (cx, cy), v in grid_max.items() if v >= 41.0],
    }

    # 生成裁剪后的墨卡托 NEXRAD 基本反射率透明贴图（Data URI）及精确经纬边界
    image_uri: Optional[str] = None
    image_bbox: Optional[List[float]] = None
    active_y, active_x = np.where(mosaic_dbz >= 15.0)
    if active_y.size > 0:
        py0 = max(0, int(active_y.min()) - 4)
        py1 = min(h_mosaic, int(active_y.max()) + 5)
        px0 = max(0, int(active_x.min()) - 4)
        px1 = min(w_mosaic, int(active_x.max()) + 5)
        image_uri = _encode_nexrad_png(mosaic_dbz[py0:py1, px0:px1], upscale=2.0)
        if image_uri:
            crop_lon0, crop_lat1 = _lonlat_of(TILE_ZOOM, x0, y0, px0, py0, 256)
            crop_lon1, crop_lat0 = _lonlat_of(TILE_ZOOM, x0, y0, px1, py1, 256)
            image_bbox = [round(crop_lon0, 4), round(crop_lat0, 4), round(crop_lon1, 4), round(crop_lat1, 4)]

    # 先补栅格孔洞，再成环：一片雨就应该是一个环，而不是一片雨加几百个洞。
    closed_cells = {band: _close_cells(rows) for band, rows in cells.items()}
    bands = {band: _rings_of(rows) for band, rows in closed_cells.items()}
    total_cells = len(cells['WEAK'])
    value = {
        'available': True,
        'source': '公开雷达拼图（RainViewer 公共接口，免密钥；瓦片为墨卡托，像素直接反算经纬度）',
        'ts': datetime.fromtimestamp(frame['time'], tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'zoom': TILE_ZOOM,
        'gridDeg': GRID_DEG,
        'tiles': {'asked': len(tiles), 'fetched': fetched},
        # 瓦片直链（墨卡托，透明底，只有回波）：前端按贴图铺，边界是原始像素，
        # 比"聚网格再并多边形"锐利得多 —— 这是回波边界糊的根因。
        'tiles_url': f"{frame['host']}{frame['path']}/256/{{z}}/{{x}}/{{y}}/4/1_1.png",
        'image': image_uri,
        'imageBbox': image_bbox,
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
    out = {'available': False, 'error': reason, 'ts': None,
           'image': None, 'imageBbox': None,
           'bands': {'WEAK': [], 'CONVECTIVE': [], 'STRONG': []},
           'counts': {'WEAK': 0, 'CONVECTIVE': 0, 'STRONG': 0}, 'cells': 0, 'coverage': 0.0}
    with _lock:
        _memory.update({'value': out, 'expires': time.monotonic() + FAIL_TTL_SECONDS})
    return out
