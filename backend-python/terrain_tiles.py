"""高程瓦片代理（真实地形）。

为什么需要这一层：三维地形要的是 **raster-dem** 瓦片，浏览器把它当纹理采样，
必须有 CORS 头；而公开的 terrarium 瓦片（AWS Open Data）**不带** CORS 头，
直接给 maplibre 用会被浏览器拦下，地图就只剩一块平地（实测如此）。

所以由服务端代取并落地缓存：
- 第一次取某块瓦片走网络（约 100 KB，几秒）；
- 之后直接读本地文件，离线演示也能出地形；
- 统一带 `Access-Control-Allow-Origin: *`，前端可以放心用。

瓦片编码是 terrarium（`elevation = R*256 + G + B/256 - 32768`），
与前端 `encoding: 'terrarium'` 对应，不能换成 mapbox 的 rgb 编码。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "terrain-cache"
CACHE.mkdir(parents=True, exist_ok=True)

UPSTREAM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
MAX_Z = 9

router = APIRouter()

PNG_MAGIC = b"\x89PNG"


def tile_path(z: int, x: int, y: int) -> Path:
    return CACHE / f"{z}_{x}_{y}.png"


def _headers() -> Dict[str, str]:
    return {
        "Cache-Control": "public, max-age=604800",
        "Access-Control-Allow-Origin": "*",
    }


@router.get("/terrain/{z}/{x}/{y}.png")
def terrain_tile(z: int, x: int, y: int):
    """取一块 terrarium 高程瓦片。取不到就是没有，不回假数据。"""
    if z < 0 or z > MAX_Z or x < 0 or y < 0 or x >= 2 ** z or y >= 2 ** z:
        raise HTTPException(404, "瓦片坐标越界")
    path = tile_path(z, x, y)
    if path.is_file() and path.stat().st_size > 100:
        return FileResponse(path, media_type="image/png", headers=_headers())
    url = UPSTREAM.format(z=z, x=x, y=y)
    try:
        with httpx.Client(timeout=25.0, follow_redirects=True) as client:
            resp = client.get(url)
        if resp.status_code == 200 and resp.content[:4] == PNG_MAGIC:
            path.write_bytes(resp.content)
            return FileResponse(path, media_type="image/png", headers=_headers())
    except Exception as exc:  # noqa: BLE001 - 网络抖动不该让地图崩
        log.debug("terrain tile %s/%s/%s 失败: %s", z, x, y, exc)
    raise HTTPException(404, "该瓦片取不到")


def prefetch(zooms: tuple[int, ...] = (3, 4, 5), bbox=(72.0, 2.0, 137.0, 55.0)) -> Dict[str, Any]:
    """把中国范围常用层级的高程瓦片抓到本地。

    演示前跑一次，之后切立体就是本地读盘，不受网络影响。
    """
    import math

    lon0, lat0, lon1, lat1 = bbox
    saved, failed = 0, 0
    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        for z in zooms:
            n = 2 ** z
            x0 = int((lon0 + 180) / 360 * n)
            x1 = int((lon1 + 180) / 360 * n)
            def merc(lat: float) -> float:
                rad = math.radians(max(-85.0, min(85.0, lat)))
                return math.log(math.tan(math.pi / 4 + rad / 2))

            y0 = int((math.pi - merc(lat1)) / (2 * math.pi) * n)
            y1 = int((math.pi - merc(lat0)) / (2 * math.pi) * n)
            for x in range(max(0, x0), min(n - 1, x1) + 1):
                for y in range(max(0, y0), min(n - 1, y1) + 1):
                    path = tile_path(z, x, y)
                    if path.is_file() and path.stat().st_size > 100:
                        saved += 1
                        continue
                    try:
                        resp = client.get(UPSTREAM.format(z=z, x=x, y=y))
                        if resp.status_code == 200 and resp.content[:4] == PNG_MAGIC:
                            path.write_bytes(resp.content)
                            saved += 1
                        else:
                            failed += 1
                    except Exception:  # noqa: BLE001
                        failed += 1
    return {"saved": saved, "failed": failed, "dir": str(CACHE)}
