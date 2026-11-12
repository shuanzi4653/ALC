# -*- coding: utf-8 -*-
"""国界几何的唯一解析点（矢量并集 + 墨卡托栅格掩膜）。

以前 `china.json` 被四处各读一遍、各解析一遍：
  · `traffic/nation.py::_province_shapes`（省界矢量）
  · `traffic/nation.py::_china_mask`（并集，裁回波环）
  · `weather/radar_public.py::_china_raster_mask`（栅格掩膜，裁贴图）
  · `traffic/national.py` / `weather/national_metar.py`（只要坐标范围）

四份解析意味着四种"国界"，而且后端一旦离开源码树打包（容器里只放 `backend-python/`），
`frontend/src/assets/china.json` 就找不到 —— 那时 `except` 把异常吞掉、掩膜静默跳过，
境内回波照画到境外去，界面上看不出来。所以这里做两件事：

1. **路径回退链**：`backend-python/data/china.json` → `frontend/src/assets/china.json`。
   前者是给"后端独立打包"准备的落点（把文件复制过去即可），后者是当前仓库的既有位置。
2. **找不到就大声报错**：`load()` 抛 `ChinaGeoMissing`，调用方据此把 `maskApplied`
   写进载荷 —— 静默降级比报错危险得多。
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_BACKEND = Path(__file__).resolve().parents[1]
CANDIDATES = (
    _BACKEND / 'data' / 'china.json',                      # 后端独立打包时的落点
    _BACKEND.parent / 'frontend' / 'src' / 'assets' / 'china.json',  # 仓库现状
)


class ChinaGeoMissing(RuntimeError):
    """`china.json` 一个候选路径都不存在。"""


def resolve_path() -> Path:
    for path in CANDIDATES:
        if path.exists():
            return path
    raise ChinaGeoMissing('china.json 不存在，尝试过：' + '、'.join(str(p) for p in CANDIDATES))


@lru_cache(maxsize=1)
def load() -> Dict[str, Any]:
    """原始 GeoJSON（缓存，进程内只解析一次）。"""
    return json.loads(resolve_path().read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def shapes() -> Dict[str, Any]:
    """省名 -> shapely 几何。**包含**全部带 name 的要素（与 `nation._province_shapes` 同语义）。

    九段线（`adchar == 'JD'`）也在这张表里，因为省界绘制与并集口径一直包含它；
    栅格掩膜那边会单独跳过（拼图范围不覆盖南海诸岛，跳不跳都一样，见 `raster_mask`）。
    """
    from shapely.geometry import shape

    out: Dict[str, Any] = {}
    for feature in load().get('features') or []:
        name = (feature.get('properties') or {}).get('name')
        if name and feature.get('geometry'):
            out[name] = shape(feature['geometry'])
    return out


@lru_cache(maxsize=1)
def union_mask():
    """国界并集，用来把回波环裁到国内。

    区划数据里有自相交的环（天津—河北那段著名的 `side location conflict`），
    直接 union 会抛拓扑异常，所以每个省先 `make_valid` 再并。
    """
    from shapely import make_valid
    from shapely.ops import unary_union

    parts = []
    for geometry in shapes().values():
        try:
            fixed = make_valid(geometry)
            if not fixed.is_empty:
                parts.append(fixed)
        except Exception:  # noqa: BLE001 - 单省坏了不该拖垮整张掩膜
            continue
    return unary_union(parts) if parts else None


@lru_cache(maxsize=1)
def _mask_template(zoom: int, x0: int, y0: int, x1: int, y1: int):
    """栅格化国界（Pillow 'L' 图），键是整块拼图范围。"""
    from PIL import Image, ImageDraw

    n = 2 ** zoom
    width = (x1 - x0 + 1) * 256
    height = (y1 - y0 + 1) * 256

    def to_px(lon: float, lat: float) -> Tuple[float, float]:
        px = ((lon + 180.0) / 360.0 * n - x0) * 256.0
        rad = math.radians(max(-85.0, min(85.0, lat)))
        py = ((1.0 - math.asinh(math.tan(rad)) / math.pi) / 2.0 * n - y0) * 256.0
        return (px, py)

    image = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(image)
    for feature in load().get('features') or []:
        props = feature.get('properties') or {}
        if not props.get('name') or props.get('adchar') == 'JD':
            # 九段线跳过是安全的：南海诸岛本来就在海南省的多边形里，
            # 且 z6 拼图最南只到约 11°N，那块几何根本不在栅格里。
            continue
        geometry = feature.get('geometry') or {}
        polys = ([geometry['coordinates']] if geometry.get('type') == 'Polygon'
                 else (geometry.get('coordinates') or []))
        for poly in polys:
            if poly and len(poly[0]) >= 3:
                draw.polygon([to_px(pt[0], pt[1]) for pt in poly[0]], fill=255)
    return image


def raster_mask(zoom: int, x0: int, y0: int, x1: int, y1: int) -> Optional[Any]:
    """墨卡托拼图栅格上的国界掩膜（bool ndarray），失败返回 None。

    `outline/width` 已去掉：实测"逐省独立填充"与"一次画全 + 3px 描边"
    在 8,499,968 个栅格上差异为 **0** —— 省界严格共边，没有缝要补，描边只是白花 49 ms。
    """
    try:
        import numpy as np

        return np.asarray(_mask_template(int(zoom), int(x0), int(y0), int(x1), int(y1)),
                          dtype=np.uint8) > 0
    except Exception:  # noqa: BLE001
        return None
