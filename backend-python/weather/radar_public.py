# -*- coding: utf-8 -*-
"""公开雷达回波（免密钥）：取拼图瓦片 → 按 dBZ 分级 → 转成经纬度多边形。

数据源
------
`https://api.rainviewer.com/public/weather-maps.json`（公开、免密钥）给出最近若干帧的
瓦片路径，瓦片是**墨卡托**的透明 PNG，只有回波、没有底图，因此像素可直接反算经纬度，
不需要额外配准。中国气象局（CMA）的 GIS 瓦片接口需要凭据，这里作为"有凭据时优先"的分支保留。

分级（阈值唯一来源：`weather/dbz.py`）
----------------------------------------
WEAK ≥15 dBZ / CONVECTIVE ≥35 / STRONG ≥45（+60 用于图例刻度）。三档**累计**：
红核一定在黄里、黄一定在绿里。颜色与阈值**同一批**改，不许只改一头。

dBZ 从哪来（必须说清）
----------------------
瓦片是**已上色的 PNG**，不是基数据。这里的 dBZ 是用 RainViewer 官方色表
（`rainviewer_api_colors_table.csv`，Universal Blue 列，15–74 dBZ 每 1 dBZ 一色）
**逐色反查**出来的，方法标记为 `IMAGE_COLOUR_REVERSE_LOOKUP`，随载荷下发
（见 `provenance`）。它不是 0.5° 仰角的基本反射率，也不是实测 dBZ 场。

产物
----
`frame = {available, ts, bands:{WEAK:[ring...], ...}, cells, coverage,
          image, imageBbox, imageSize, imageScope, scale, thresholdsDbz,
          provenance, reverseLookup, maskApplied}`
ring 是 [[lon,lat], ...] 的闭合环，已抽稀（0.02°），可直接画 SVG 多边形；
`image` 是同一场 dBZ 的索引色 PNG（12 条图例对应 14 级色板里可达的那些档）。
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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import numpy as np

from . import china_geo
from .dbz import (
    BAND_EDGES,
    CONVECTIVE_DBZ,
    ECHO_FLOOR_DBZ,
    STRONG_DBZ,
    THRESHOLDS_DBZ,
)

META_URL = 'https://api.rainviewer.com/public/weather-maps.json'
ROOT_DIR = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT_DIR / '.run' / 'radar'
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
# 三档的累计阈值（V1.0.4）：WEAK=全部回波，CONVECTIVE=中强以上，STRONG=强回波。
# 语义从"每格归一个档"改成"每格过一个阈值"，三档因此**天然嵌套**，
# 前端按 绿→黄→红 叠色就是真实雷达的洋葱结构。
BAND_RANK = {'WEAK': 1, 'CONVECTIVE': 2, 'STRONG': 3}
TTL_SECONDS = 600.0
FAIL_TTL_SECONDS = 60.0          # 上游挂了别每 15 s 重试 130 张：串行锁会把三个接口一起拖住
TIMEOUT_SECONDS = 20.0           # 仅用于取帧清单（一个请求）
TILE_TIMEOUT_SECONDS = 6.0       # 单张瓦片：20 s × ceil(130/24) 波 = 最坏 120 s，前端 90 s 先崩
FETCH_DEADLINE_SECONDS = 45.0    # 全局止损：到点就用手上已有的拼，绝不把首屏拖过 90 s
MIN_TILE_RATIO = 0.9             # 少于九成瓦片就不发布这一帧（缺块的图会被缓存成"实况"）
# 16 线程不是"越快越好"的取舍：按陆地过滤后只需 60–80 张，16 线程 ≈ 4–5 波，
# 对免密钥公共服务也比 32 并发更克制。TILE_RETRIES 只在 429/503 上重试一次。
TILE_WORKERS = 16
TILE_RETRIES = 1
TILE_BACKOFF_SECONDS = 0.6
MAX_IMAGE_EDGE = 4096.0          # 出图长边上限（再大只是给浏览器添解码负担）
USER_AGENT = 'ALC-tianchuang/1.0.8 (radar echo; contact: project maintainer)'
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
    # 断点必须落在判据上：这两处原来是 34 / 46，于是 35 dBZ（绕飞线）与 45 dBZ（禁入线）
    # 都落在色块**中间**——图例画不出"这条边就是阈值"，而且 32–34 已经判对流却还是深绿。
    # 实测换这两个数字只动 4,624/10,866,688 = 0.04% 的像素，肉眼不可见。
    (35.0, (255, 255, 0, 255)),    # 35–38 dBZ: 纯亮黄（对流初生 / 中雨）
    (38.0, (244, 184, 0, 255)),    # 38–42 dBZ: 金黄
    (42.0, (255, 130, 0, 255)),    # 42–45 dBZ: 鲜橙（大雨 / 中等对流）
    (45.0, (255, 52, 0, 255)),     # 45–50 dBZ: 橙红（强降水 / 禁入线从这里开始）
    (50.0, (236, 0, 0, 255)),      # 50–55 dBZ: 鲜红（暴雨 / 强对流内核）
    (55.0, (188, 0, 0, 255)),      # 55–60 dBZ: 深红
    (60.0, (236, 0, 228, 255)),    # 60–65 dBZ: 亮品红（极端对流 / 冰雹核）
    (65.0, (168, 64, 220, 255)),   # 65–70 dBZ: 紫色
    (70.0, (255, 255, 255, 255)),  # 70+ dBZ: 亮白核
)

_lock = threading.Lock()
_memory: Dict[str, Any] = {'value': None, 'expires': 0.0}

# 反查命中/失配计数（每帧重置，随载荷下发）。这不是调试信息，是**唯一的**色表漂移观测点：
# 如果 RainViewer 换配色，全部像素会静默走进最近色回退、图上要么全 0 要么全强，
# 而界面上看不出区别 —— 有这两个数，至少能在载荷里发现"命中率掉到 0"。
_MISS_LOCK = threading.Lock()
_MISS_STATS = {'hit': 0, 'miss': 0, 'resolved': 0}


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


# ---------------------------------------------------------------- 官方色表反查
# 这一段替换了原来手调的分段线性拟合（`_pixel_dbz` / `_band_of` / `_tile_range`
# 三个函数已删）。为什么必须换：拿 RainViewer 官方色表逐色复算，拟合版在 15–50 dBZ 段
# 平均偏高 **+9.96 dBZ**、最大 **+13.80**——真 23 dBZ 算成 32（进"对流"）、真 28 算成 41
# （进"强回波"），门线整体前移 12–16 dBZ；同帧 STRONG 面积是真值的 **586 倍**，
# 一场 20–30 dBZ 的层状小雨被画成大片橙红强对流。反向也错：真实 51–54 / 55–61 / 65–74 dBZ
# 被整档丢弃，50 dBZ 反而被放大成 60（冰雹核消失且非单调）。
#
# 表来源：rainviewer_api_colors_table.csv，Universal Blue 列，15–74 dBZ 每 1 dBZ 一色。
# 注意 65–74 dBZ 是同一个白色，代表值取 70（与源图观感一致）；75 dBZ 以上是纯绿，
# 那是**溢出标记色**不是回波，不入表。
COLOUR_TO_DBZ: Dict[Tuple[int, int, int], float] = {
    (136, 221, 238): 15.0,
    (108, 209, 235): 16.0,
    ( 81, 197, 232): 17.0,
    ( 54, 186, 229): 18.0,
    ( 27, 174, 226): 19.0,
    (  0, 163, 224): 20.0,
    (  0, 154, 213): 21.0,
    (  0, 145, 202): 22.0,
    (  0, 136, 191): 23.0,
    (  0, 127, 180): 24.0,
    (  0, 119, 170): 25.0,
    (  0, 112, 163): 26.0,
    (  0, 105, 156): 27.0,
    (  0,  98, 149): 28.0,
    (  0,  91, 142): 29.0,
    (  0,  85, 136): 30.0,
    (  0,  81, 128): 31.0,
    (  0,  78, 120): 32.0,
    (  0,  74, 112): 33.0,
    (  0,  71, 104): 34.0,
    (255, 238,   0): 35.0,
    (255, 224,   0): 36.0,
    (255, 210,   0): 37.0,
    (255, 197,   0): 38.0,
    (255, 183,   0): 39.0,
    (255, 170,   0): 40.0,
    (255, 159,   0): 41.0,
    (255, 149,   0): 42.0,
    (255, 139,   0): 43.0,
    (255, 129,   0): 44.0,
    (255,  68,   0): 45.0,
    (242,  54,   0): 46.0,
    (230,  40,   0): 47.0,
    (217,  27,   0): 48.0,
    (205,  13,   0): 49.0,
    (193,   0,   0): 50.0,
    (168,   0,   0): 51.0,
    (143,   0,   0): 52.0,
    (118,   0,   0): 53.0,
    ( 93,   0,   0): 54.0,
    (255, 170, 255): 55.0,
    (255, 159, 255): 56.0,
    (255, 149, 255): 57.0,
    (255, 139, 255): 58.0,
    (255, 129, 255): 59.0,
    (255, 119, 255): 60.0,
    (255, 108, 255): 61.0,
    (255,  98, 255): 62.0,
    (255,  88, 255): 63.0,
    (255,  78, 255): 64.0,
    (255, 255, 255): 70.0,     # 65–74 同为白，取 70
}

# 反查能吐出的全部值（51 个：15..64 加 70）。图例色阶由它推导，不写死条数。
REACHABLE_DBZ: Tuple[float, ...] = tuple(sorted(set(COLOUR_TO_DBZ.values())))

# 最近色回退的容忍半径（RGB 欧氏距离）。超过它就判"无回波"：
# 那是抗锯齿/半透明的混合色，硬塞进最近档会凭空造出 1 像素的"强核"。
COLOUR_MAX_DIST = 40.0

_COLOUR_KEYS = np.array(sorted(COLOUR_TO_DBZ), dtype=np.int32)
_COLOUR_VALUES = np.array([COLOUR_TO_DBZ[tuple(int(v) for v in row)] for row in _COLOUR_KEYS],
                          dtype=np.float32)
_COLOUR_PACKED = (_COLOUR_KEYS[:, 0] << 16) | (_COLOUR_KEYS[:, 1] << 8) | _COLOUR_KEYS[:, 2]
_COLOUR_ORDER = np.argsort(_COLOUR_PACKED)
_COLOUR_SORTED = _COLOUR_PACKED[_COLOUR_ORDER]
_COLOUR_SORTED_DBZ = _COLOUR_VALUES[_COLOUR_ORDER]


def _nearest_dbz(r, g, b) -> np.ndarray:
    """查不到的颜色的最近色回退（分块，避免 8.5 M 像素 × 51 色一次性展开）。"""
    px = np.stack([r, g, b], axis=1).astype(np.int32)
    out = np.zeros(px.shape[0], dtype=np.float32)
    limit = COLOUR_MAX_DIST ** 2
    step = 200_000
    for start in range(0, px.shape[0], step):
        chunk = px[start:start + step]
        diff = chunk[:, None, :] - _COLOUR_KEYS[None, :, :]
        d2 = (diff * diff).sum(-1)
        idx = d2.argmin(1)
        best = d2[np.arange(chunk.shape[0]), idx]
        out[start:start + chunk.shape[0]] = np.where(best <= limit, _COLOUR_VALUES[idx], 0.0)
    return out


def _tile_dbz_array(image) -> np.ndarray:
    """单张 RGBA 瓦片 → dBZ 矩阵（float32）。

    先按精确 RGB 查表（PNG 无损，绝大多数像素一次命中），只对查不到的像素做最近色回退。
    """
    arr = np.asarray(image)
    if arr.ndim != 3 or arr.shape[2] < 4:
        return np.zeros(arr.shape[:2] or (1, 1), dtype=np.float32)
    r = arr[:, :, 0].astype(np.int32)
    g = arr[:, :, 1].astype(np.int32)
    b = arr[:, :, 2].astype(np.int32)
    valid = arr[:, :, 3] >= ALPHA_FLOOR
    out = np.zeros(r.shape, dtype=np.float32)

    packed = (r << 16) | (g << 8) | b
    pos = np.clip(np.searchsorted(_COLOUR_SORTED, packed), 0, _COLOUR_SORTED.size - 1)
    hit = valid & (_COLOUR_SORTED[pos] == packed)
    if hit.any():
        out[hit] = _COLOUR_SORTED_DBZ[pos[hit]]

    miss = valid & ~hit
    resolved = 0
    if miss.any():
        nearest = _nearest_dbz(r[miss], g[miss], b[miss])
        out[miss] = nearest
        resolved = int((nearest > 0).sum())
    with _MISS_LOCK:
        _MISS_STATS['hit'] += int(hit.sum())
        _MISS_STATS['miss'] += int(miss.sum())
        _MISS_STATS['resolved'] += resolved
    return out


def _tiles_over_land(tiles, mask, x0: int, y0: int):
    """只保留与陆地掩膜相交的瓦片。

    掩膜之外的回波最后会被整片抹成 0（`np.where(china_mask, ...)`），
    也就是说**拉了也是白拉**。全国 bbox 有 130 张瓦片，陆地只占 29.7%，
    按块筛一遍能省掉四成请求 —— 这既省时间，也是对免密钥公共服务的基本礼貌。

    遮罩缺失时返回全部瓦片：宁可多拉，也不能因为读不到底图就少画一块。
    """
    if mask is None:
        return list(tiles)
    kept = []
    for tx, ty in tiles:
        oy = (ty - y0) * 256
        ox = (tx - x0) * 256
        block = mask[oy:oy + 256, ox:ox + 256]
        if block.size and block.any():
            kept.append((tx, ty))
    return kept


def _despeckle_dbz(dbz: np.ndarray) -> np.ndarray:
    """剔除 8 邻域内孤立的 1–2 像素杂波点，保留真实降水回波胞结构。"""
    # 用 uint8 而不是 int32 累加：8.5 M 像素的 8 个切片原来峰值吃到 144.9 MB，
    # 换成 uint8 后只有 1/4；而且这一步现在排在**掩膜之后**，只算境内那 30%。
    mask = (dbz >= ECHO_FLOOR_DBZ).astype(np.uint8)
    if not mask.any():
        return dbz
    padded = np.pad(mask, 1, mode='constant')
    h, w = mask.shape
    nbrs = sum(
        padded[1 + dy:1 + dy + h, 1 + dx:1 + dx + w].astype(np.uint8)
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
        if not (dx == 0 and dy == 0)
    )
    cleaned = dbz.copy()
    # 原来是 `nbrs <= 1`：两点宽的回波带里每个点都只有 1 个邻居，会被**整条删掉**
    # （实测 (4,4)+(4,5) 双双清零）。孤立单点才是杂波，成对/成线的是真实细回波。
    cleaned[nbrs == 0] = 0.0
    return cleaned


_MASK_CACHE: Dict[Tuple[int, int, int, int, int], np.ndarray] = {}


def _china_raster_mask(z: int, x0: int, y0: int, x1: int, y1: int):
    """墨卡托拼图栅格上的国界掩膜。实现搬到 `weather/china_geo.py`（全仓一处解析）。

    缓存**只存成功结果**：`china_geo.raster_mask` 失败时返回 None，若把 None 也缓存住，
    就等于"一次读不到文件，进程生命周期内再也不裁国界" —— 那正是本 PR 在 `_radar()`
    上修掉的老坑，没道理在这里重犯。
    """
    key = (z, x0, y0, x1, y1)
    cached = _MASK_CACHE.get(key)
    if cached is not None:
        return cached
    mask = china_geo.raster_mask(z, x0, y0, x1, y1)
    if mask is not None:
        _MASK_CACHE[key] = mask
    return mask


def _encode_nexrad_png(crop_dbz: np.ndarray, upscale: float = 1.0):
    """dBZ 矩阵 -> 14 级 NEXRAD 索引色透明 PNG。

    返回 ``(data_uri, [w, h])``：出图尺寸随载荷下发（`imageSize`），
    前端据此判断这张图是下采样还是上采样，不必自己猜。

    两处与上一版不同，都是实测出来的：
      * **upscale 默认 1.0**。原来写 2.0，但被 `4096/max(w,h)` 截断成实际 1.498；
        升采样是纯插值、零信息，白付 49% 字节（PNG 32.2 -> 48.0 KB）。
      * **不做高斯模糊**。它是在量化域、放大之前做的：10-15 dBZ 那一档从 6,714 像素
        被抬到 16,417（+145%），图上凭空多一圈青晕（而矢量面从 15 dBZ 起，两者边界打架）；
        同时把 55/60/65 三档共 39 像素抹成 0 —— 冰雹核被吃掉。
    """
    from PIL import Image

    if crop_dbz.size == 0 or float(crop_dbz.max()) < ECHO_FLOOR_DBZ:
        return None, None
    h, w = crop_dbz.shape
    scale = min(float(upscale), MAX_IMAGE_EDGE / max(1, max(w, h)))
    w_out = max(1, int(round(w * scale)))
    h_out = max(1, int(round(h * scale)))
    if (w_out, h_out) != (w, h):
        # 只在真要放大时才重采样：量化到 0-255（0.294 dBZ 一步），双三次插值后折回 dBZ。
        norm = np.clip(crop_dbz * 3.4, 0.0, 255.0).astype(np.uint8)
        resized = Image.fromarray(norm, mode='L').resize((w_out, h_out), Image.BICUBIC)
        up_dbz = np.asarray(resized, dtype=np.float32) / 3.4
    else:
        up_dbz = crop_dbz

    idx = np.zeros(up_dbz.shape, dtype=np.uint8)
    for k, (threshold, _rgba) in enumerate(NEXRAD_LUT, start=1):
        idx[up_dbz >= threshold] = k
    if not idx.any():
        return None, None

    palette = [0, 0, 0]        # 索引 0 = 背景（透明）
    for _threshold, (cr, cg, cb, _ca) in NEXRAD_LUT:
        palette.extend((cr, cg, cb))
    palette.extend([0] * (768 - len(palette)))

    pim = Image.fromarray(idx, mode='P')
    pim.putpalette(palette)
    buf = _io.BytesIO()
    # transparency=0：只让索引 0 透明。LUT 里 14 个 alpha 全是 255，
    # 之前用 bytes([0,255,...]) 写出 15 字节 tRNS 是纯冗余（实测等价）。
    pim.save(buf, format='PNG', optimize=True, transparency=0)
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    return 'data:image/png;base64,' + b64, [w_out, h_out]


def nexrad_scale() -> List[Dict[str, Any]]:
    """图例色阶：只列**可达**档位，条数由数据推出来。

    可达 = 官方色表里真实存在的代表值（`REACHABLE_DBZ`，15..64 加 70，共 51 个）。
    某个断点区间里一个可达值都没有 -> 这一档永远不会出现在图上，不该进图例：

      * 10 dBZ 档：反查下限就是 15，[10,15) 里没有任何可达值 -> 滤掉
      * 65 dBZ 档：65-74 同色白，代表值取 70，[65,70) 为空 -> 滤掉

    所以 14 级编码色板对应 **12 条**图例。**不要**把色板砍成 12 —— 色板是编码，
    图例是刻度尺，两者由这条规则连接，不是拷贝关系。
    `until` 取下一个保留档的门限；60 的 until 因此是 70（60-64 全落同一格）。
    """
    lut = [(float(t), rgba) for t, rgba in NEXRAD_LUT]
    kept: List[Tuple[float, Tuple[int, int, int, int]]] = []
    for index, (floor, rgba) in enumerate(lut):
        ceiling = lut[index + 1][0] if index + 1 < len(lut) else float('inf')
        if any(floor <= value < ceiling for value in REACHABLE_DBZ):
            kept.append((floor, rgba))
    out: List[Dict[str, Any]] = []
    for index, (floor, rgba) in enumerate(kept):
        until = kept[index + 1][0] if index + 1 < len(kept) else None
        out.append({'dbz': floor, 'until': until,
                    'color': '#%02x%02x%02x' % rgba[:3]})
    return out


def virtual_nexrad_image(bucket: int, cells_spec: Tuple[Tuple[str, float, float, float, float], ...]):
    """虚拟恶劣天气的贴图 -> (data_uri, bbox, size)。与真实帧同一套编码与色板。"""
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

    data_uri, size = _encode_nexrad_png(dbz, upscale=1.0)
    if not data_uri:
        return None, None, None
    return data_uri, [lon0, lat0, lon1, lat1], size





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

    started = time.time()          # 只用于 elapsedMs（对外是"墙钟秒"）
    started_mono = time.monotonic()  # 用于 deadline：**必须与 grab() 里比较的时钟相同**
    try:
        frame = _latest_frame(_meta())
        if frame is None:
            raise RuntimeError('没有可用雷达帧')
    except Exception as exc:  # noqa: BLE001
        return _empty(f'取帧失败：{str(exc)[:90]}')

    stamp = datetime.fromtimestamp(frame['time'], tz=timezone.utc).strftime('%Y%m%d%H%M')
    # 缓存键带口径版本号：`-nexrad5` = 官方色表反查 + 无模糊 + 不放大。
    # 版本号必须跟着口径走：旧文件里存的是拟合出来的 dBZ，读回来就是错的数字。
    cache_file = CACHE_DIR / f'{stamp}-z{TILE_ZOOM}-g{GRID_DEG}-nexrad5.json'
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
    all_tiles = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    # 掩膜先算（它有缓存），用它筛掉整块在境外的瓦片
    china_mask = _china_raster_mask(TILE_ZOOM, x0, y0, x1, y1)
    tiles = _tiles_over_land(all_tiles, china_mask, x0, y0)
    skipped_tiles = len(all_tiles) - len(tiles)
    w_mosaic = (x1 - x0 + 1) * 256
    h_mosaic = (y1 - y0 + 1) * 256
    mosaic_dbz = np.zeros((h_mosaic, w_mosaic), dtype=np.float32)
    fetched = 0
    # 这里原来写的是 `started + ...`（epoch）却拿 monotonic 去比，两者差 3 个数量级，
    # 判据恒为 False —— 45 s 止损等于没写，实测过。
    deadline = started_mono + FETCH_DEADLINE_SECONDS
    # 1_0 = 关掉 snow 色标。`1_1` 会让降雪区走另一张色表（实测本帧 6.76% 的回波像素
    # 是雪色 (195,255,255) 系），单表反查对它们全部返回 0 —— 冬季 30+ dBZ 的降雪带会被低估。
    tile_url_tpl = f"{frame['host']}{frame['path']}/256/{{z}}/{{x}}/{{y}}/4/1_0.png"

    def grab(pair: Tuple[int, int]):
        if time.monotonic() > deadline:
            return None          # 全局止损：到点就不再发新请求，用手上已有的拼
        x, y = pair
        try:
            for attempt in range(TILE_RETRIES + 1):
                response = httpx.get(tile_url_tpl.format(z=TILE_ZOOM, x=x, y=y),
                                     timeout=TILE_TIMEOUT_SECONDS,
                                     headers={'User-Agent': USER_AGENT})
                if response.status_code in (429, 503) and attempt < TILE_RETRIES:
                    # 限流就退一步再来一次，别把 130 张一次性砸过去
                    time.sleep(TILE_BACKOFF_SECONDS * (attempt + 1))
                    continue
                break
            if response.status_code != 200 or not response.content:
                return None
            image = Image.open(_io.BytesIO(response.content)).convert('RGBA')
            return x, y, _tile_dbz_array(image)
        except Exception:  # noqa: BLE001 - 单瓦片失败跳过
            return None

    with _MISS_LOCK:
        _MISS_STATS.update({'hit': 0, 'miss': 0, 'resolved': 0})

    with concurrent.futures.ThreadPoolExecutor(max_workers=TILE_WORKERS) as pool:
        for item in pool.map(grab, tiles):
            if item is None:
                continue
            tx, ty, tile_dbz = item
            fetched += 1
            oy = (ty - y0) * 256
            ox = (tx - x0) * 256
            mosaic_dbz[oy:oy + 256, ox:ox + 256] = tile_dbz

    # 缺块闸门：少一个角就发布的图，会被缓存 10 分钟、被当成"那里没有回波"。
    # 假阴（说没雨，其实有）比报错危险得多 —— 绕飞判定会据此全放行。
    if fetched < len(tiles) * MIN_TILE_RATIO:
        return _empty(f'瓦片只取到 {fetched}/{len(tiles)}，本帧不发布（残缺帧会被当成实况）')

    # 先掩膜、再去噪：去噪只看 8 邻域，在境外那 70% 上算是白算，
    # 而且原来的 int32 累加在 8.5 M 像素上峰值吃到 144.9 MB。
    # （掩膜在取瓦片前就算过了，这里只做形状校验，不重复计算。）
    masked = china_mask is not None and china_mask.shape == mosaic_dbz.shape
    if masked:
        mosaic_dbz = np.where(china_mask, mosaic_dbz, 0.0)
    mosaic_dbz = _despeckle_dbz(mosaic_dbz)

    # 聚合到经纬网格（累积嵌套：STRONG ⊂ CONVECTIVE ⊂ WEAK，消除外环镂空）
    step = max(1, int(ROUND_PIXELS))
    sampled = mosaic_dbz[::step, ::step]
    sy_idx, sx_idx = np.where(sampled >= ECHO_FLOOR_DBZ)
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

    # 三档门限一律读 `weather/dbz.py`：以前这里硬编码 32/41，而色板断点是 34/46，
    # 于是"已经判对流、会让航线绕开"的那 7.1% 格子在图上还是深绿，
    # "已经判禁入"的那 4.6% 根本没变红。禁入区不红，等于把最该看见的东西藏了。
    cells: Dict[str, List[Tuple[float, float]]] = {
        'WEAK': [(cx * GRID_DEG, cy * GRID_DEG) for (cx, cy), v in grid_max.items()
                 if v >= ECHO_FLOOR_DBZ],
        'CONVECTIVE': [(cx * GRID_DEG, cy * GRID_DEG) for (cx, cy), v in grid_max.items()
                       if v >= CONVECTIVE_DBZ],
        'STRONG': [(cx * GRID_DEG, cy * GRID_DEG) for (cx, cy), v in grid_max.items()
                   if v >= STRONG_DBZ],
    }

    # 裁剪后的墨卡托反射率贴图（Data URI）+ 精确经纬框 + 出图尺寸
    image_uri: Optional[str] = None
    image_bbox: Optional[List[float]] = None
    image_size: Optional[List[int]] = None
    active_y, active_x = np.where(mosaic_dbz >= ECHO_FLOOR_DBZ)
    if active_y.size > 0:
        py0 = max(0, int(active_y.min()) - 4)
        py1 = min(h_mosaic, int(active_y.max()) + 5)
        px0 = max(0, int(active_x.min()) - 4)
        px1 = min(w_mosaic, int(active_x.max()) + 5)
        image_uri, image_size = _encode_nexrad_png(mosaic_dbz[py0:py1, px0:px1], upscale=1.0)
        if image_uri:
            crop_lon0, crop_lat1 = _lonlat_of(TILE_ZOOM, x0, y0, px0, py0, 256)
            crop_lon1, crop_lat0 = _lonlat_of(TILE_ZOOM, x0, y0, px1, py1, 256)
            image_bbox = [round(crop_lon0, 4), round(crop_lat0, 4),
                          round(crop_lon1, 4), round(crop_lat1, 4)]

    bands, total_cells = bands_from_cells(cells)

    # 覆盖率：分子分母都做 **cos(纬度) 面积权重**。
    # 以前两边都是"经纬度平方"，而纬度越高 1° 经度越短 —— 高纬回波会被系统性高估；
    # 分母又只用 bbox（陆地只占 29.7%），同一场天气的覆盖率会莫名掉到三分之一。
    pixel_deg = 360.0 / (2 ** TILE_ZOOM) / 256.0
    pixel_area = pixel_deg * pixel_deg
    rows = np.arange(h_mosaic, dtype=np.float64) + 0.5
    merc = np.pi * (1.0 - 2.0 * (y0 + rows / 256.0) / (2 ** TILE_ZOOM))
    row_weight = np.cos(np.arctan(np.sinh(merc)))
    echo_area = sum(math.cos(math.radians(cy * GRID_DEG)) for (_cx, cy) in grid_max) * (GRID_DEG ** 2)
    if masked:
        land_area = float((row_weight * china_mask.sum(axis=1)).sum()) * pixel_area
    else:
        land_area = float(row_weight.sum() * w_mosaic) * pixel_area

    value = {
        'available': True,
        'source': '公开雷达拼图（RainViewer 公共接口，免密钥；瓦片为墨卡托，像素直接反算经纬度）',
        'ts': datetime.fromtimestamp(frame['time'], tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'zoom': TILE_ZOOM,
        'gridDeg': GRID_DEG,
        'tiles': {'asked': len(tiles), 'fetched': fetched, 'skippedOffshore': skipped_tiles},
        'tiles_url': tile_url_tpl,
        'image': image_uri,
        'imageBbox': image_bbox,
        'imageSize': image_size,
        # 这张图只用于全国视图：省/市层要把 45.5 px/° 的栅格放大 6–8 倍，
        # 插值出来的颜色根本不在色阶里，那一层继续用矢量环。
        'imageScope': 'nation',
        'scale': nexrad_scale(),
        'thresholdsDbz': dict(THRESHOLDS_DBZ),
        'provenance': _provenance(frame),
        # 反查质量：hit=精确命中色表，miss=走进最近色回退，resolvedFromNearest=回退后仍判成回波。
        # missRatio 长期 >0.9 且 hitPixels=0 → 色表已变，图上的 dBZ 不再可信。
        'reverseLookup': _reverse_lookup_report(),
        'cells': total_cells,
        'bands': bands,
        'counts': {band: len(rings) for band, rings in bands.items()},
        'coverage': round(100.0 * echo_area / max(1e-6, land_area), 2),
        'coverageBasis': 'LAND' if masked else 'BBOX',
        'maskApplied': masked,
        'elapsedMs': int((time.time() - started) * 1000),
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        # 原子写：半截文件会让下一个进程 json.loads 失败（然后重算，白烧一次冷启动）
        tmp = cache_file.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        tmp.replace(cache_file)
        _prune_cache(keep=6)
    except Exception:  # noqa: BLE001
        pass
    with _lock:
        _memory.update({'value': value, 'expires': now + TTL_SECONDS})
    return value


def _reverse_lookup_report() -> Dict[str, Any]:
    with _MISS_LOCK:
        hit = int(_MISS_STATS['hit'])
        miss = int(_MISS_STATS['miss'])
        resolved = int(_MISS_STATS['resolved'])
    total = hit + miss
    ratio = round(miss / total, 4) if total else 0.0
    return {'hitPixels': hit, 'missPixels': miss, 'resolvedFromNearest': resolved,
            'missRatio': ratio,
            # 一个像素都没精确命中、却又有一堆像素待判 → 色表已经不是我们认识的那张
            'degraded': bool(total > 50000 and hit == 0)}


def _provenance(frame: Dict[str, Any]) -> Dict[str, Any]:
    """这帧 dBZ 是怎么来的 —— 逐字段写清，别让人把"反查"读成"实测"。

    `docs/radar-channels.md` §3.3 要求：颜色反算出来的场必须标
    `IMAGE_COLOUR_REVERSE_LOOKUP`，且不得与 `OBSERVED_DBZ_FIELD` 混用。
    """
    valid_at = datetime.fromtimestamp(frame['time'], tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {
        'provider': 'RAINVIEWER',
        'dataset': 'radar composite tiles, universal blue, z%d' % TILE_ZOOM,
        'method': 'IMAGE_COLOUR_REVERSE_LOOKUP',
        'colourTable': 'rainviewer_api_colors_table.csv#universal_blue',
        'qualityFlags': ['DERIVED_FROM_IMAGE_PRODUCT', 'NOT_CROSS_VALIDATED'],
        'validAt': valid_at,
        'retrievedAt': datetime.now(tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'projection': 'EPSG:3857',
        'pixelDegrees': round(360.0 / (2 ** TILE_ZOOM) / 256, 6),
    }


def _prune_cache(keep: int = 6) -> None:
    """只留最近 keep 帧：每帧约 230 KB、每天 144 帧 = 33 MB/天，不清就无限涨。"""
    try:
        files = sorted(CACHE_DIR.glob('*-nexrad5.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in files[keep:]:
            stale.unlink()
    except Exception:  # noqa: BLE001
        pass


def bands_from_cells(cells: Dict[str, List[Tuple[float, float]]]):
    """三档环 + 有效栅格数。**累计掩膜**，不是"每格只归一个档"（V1.0.4）。

    以前三档互斥，画出来是红、黄、绿三片并排相邻；真实雷达的强度分级是嵌套的
    （红核一定在黄里、黄一定在绿里）。互斥几何无论怎么调色都不像雷达 ——
    这是"看起来不像回波图"的根因，不是配色问题。

    现在 WEAK=全部回波、CONVECTIVE=中强以上、STRONG=强回波，
    前端按 绿→黄→红 叠色就得到真实回波的"洋葱"结构。
    返回 ``(bands, total_cells)``：total_cells 是去重后的有效栅格数，
    用于覆盖率的分子（以前是把三档相加，互斥时等价，累计后会重复计数）。
    """
    ranked: Dict[Tuple[float, float], int] = {}
    for band, rows in cells.items():
        rank = BAND_RANK[band]
        for cell in rows:
            if ranked.get(cell, 0) < rank:
                ranked[cell] = rank
    bands: Dict[str, List[Any]] = {}
    for band, need in BAND_RANK.items():
        rows = [cell for cell, rank in ranked.items() if rank >= need]
        bands[band] = _rings_of(_close_cells(rows)) if rows else []
    return bands, len(ranked)


def _bbox_area(bbox: Tuple[float, float, float, float]) -> float:
    lon0, lat0, lon1, lat1 = bbox
    return max(1e-6, (lon1 - lon0) * (lat1 - lat0))


def _empty(reason: str) -> Dict[str, Any]:
    out = {'available': False, 'error': reason, 'ts': None,
           'image': None, 'imageBbox': None, 'imageSize': None, 'imageScope': 'nation',
           'scale': nexrad_scale(), 'thresholdsDbz': dict(THRESHOLDS_DBZ),
           'reverseLookup': _reverse_lookup_report(),
           'bands': {'WEAK': [], 'CONVECTIVE': [], 'STRONG': []},
           'counts': {'WEAK': 0, 'CONVECTIVE': 0, 'STRONG': 0}, 'cells': 0,
           'coverage': 0.0, 'coverageBasis': 'BBOX', 'maskApplied': False}
    with _lock:
        _memory.update({'value': out, 'expires': time.monotonic() + FAIL_TTL_SECONDS})
    return out
