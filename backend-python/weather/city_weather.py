# -*- coding: utf-8 -*-
"""逐市气象（open-meteo 公开接口，免密钥）。

为什么要这一层
--------------
原来屏上只有"每省一个 METAR 站"，可这一层要回答的是**每个城市**现在什么天气。
METAR 站是机场的，一个省常常只有 1 个；城市有 330 个。open-meteo 的 `current`
是公开、免密钥、可批量（一次多坐标）的实况接口，正好补这个口径。

口径
----
- 逐市取：`temperature_2m / wind_speed_10m / visibility / weather_code / precipitation`；
- 一次请求批量 60 个坐标，330 城约 6 次；结果缓存 10 分钟；
- **拿不到就是没有**：某批失败只让那批城市没有气象，不插值、不补零；
- 与 METAR 的关系：METAR 仍是"机场实测"，这里是"城市模型实况"，两者分开标注，不互相替代。
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import httpx

# 落盘兜底：公开接口有免费额度（实测一小时打满就会连续 429）。
# 拿到就写盘，拿不到就用手上最近一份，并把时间戳一起带出去 ——
# "旧数据"和"没数据"是两件事，界面要能区分。
CACHE_FILE = Path(__file__).resolve().parent.parent.parent / 'data' / 'cache' / 'city-weather.json'

URL = 'https://api.open-meteo.com/v1/forecast'
FIELDS = 'temperature_2m,wind_speed_10m,visibility,weather_code,precipitation'
BATCH = 60
TTL_SECONDS = 1800.0
TIMEOUT_SECONDS = 25.0
USER_AGENT = 'ALC-tianchuang/1.0.1 (city weather; contact: project maintainer)'

_cache: Dict[str, Any] = {'expires': 0.0, 'value': None}
_lock = threading.Lock()


def _num(value: Any) -> Any:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _fetch_batch(rows: List[Tuple[str, float, float]]) -> Dict[str, Dict[str, Any]]:
    params = {
        'latitude': ','.join(f'{lat:.4f}' for _, lat, _ in rows),
        'longitude': ','.join(f'{lon:.4f}' for _, _, lon in rows),
        'current': FIELDS,
        'timezone': 'UTC',
    }
    response = httpx.get(URL, params=params, timeout=TIMEOUT_SECONDS,
                         headers={'User-Agent': USER_AGENT})
    response.raise_for_status()
    payload = response.json()
    items = payload if isinstance(payload, list) else [payload]
    out: Dict[str, Dict[str, Any]] = {}
    for (name, _lat, _lon), item in zip(rows, items):
        current = (item or {}).get('current') or {}
        wind_kmh = _num(current.get('wind_speed_10m'))
        vis = _num(current.get('visibility'))
        out[name] = {
            'tempC': _num(current.get('temperature_2m')),
            'windMps': round(wind_kmh / 3.6, 1) if wind_kmh is not None else None,
            'visM': vis,
            'precipMm': _num(current.get('precipitation')),
            'weatherCode': current.get('weather_code'),
            'ts': (current.get('time') or '') + ':00Z' if current.get('time') else None,
            'low': bool(vis is not None and vis < 3000),
            'source': 'OPEN_METEO',
        }
    return out


def fetch(points: Iterable[Tuple[str, float, float]], force: bool = False) -> Dict[str, Any]:
    """points = [(城市名, 纬度, 经度), ...]；返回 {城市名: 气象}，失败的城不出现。"""
    rows = [(name, float(lat), float(lon)) for name, lat, lon in points]
    key = f'{len(rows)}:{rows[0][0] if rows else ""}:{rows[-1][0] if rows else ""}'
    now = time.monotonic()
    with _lock:
        cached = _cache['value']
        if not force and cached and now < _cache['expires'] and cached.get('key') == key:
            return cached

    merged: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    rate_limited = False
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        for attempt in range(3):          # 公开接口会限流：单批失败退避重试，别整屏缺一块
            try:
                merged.update(_fetch_batch(chunk))
                break
            except Exception as exc:  # noqa: BLE001 - 单批失败不该拖垮整屏
                status = getattr(getattr(exc, 'response', None), 'status_code', None)
                if status == 429:
                    # 限流期间重试没有意义，只会把接口拖成超时；直接放弃这一批，6 分钟后自愈
                    rate_limited = True
                    errors.append(f'batch {start // BATCH}: 429 限流（额度用尽，稍后自动恢复）')
                    break
                if attempt == 2:
                    errors.append(f'batch {start // BATCH}: {str(exc)[:80]}')
                else:
                    time.sleep(0.8 * (attempt + 1))
        if rate_limited:
            break
    if not merged:
        # 一张都没拿到：退回磁盘上最近一份快照，并明确标 stale
        fallback = _load_disk()
        if fallback:
            fallback = dict(fallback)
            fallback['stale'] = True
            fallback['errors'] = errors
            with _lock:
                _cache.update({'value': fallback, 'expires': time.monotonic() + 120.0})
            return fallback
    value = {
        'available': bool(merged),
        'source': 'open-meteo current（公开、免密钥，逐市）',
        'fetchedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'key': key,
        'cities': merged,
        'errors': errors,
    }
    with _lock:
        if merged:
            # 缺城市时只缓存 60 s，下一次请求会补；齐了才按 30 分钟缓存。
            # 被限流时缓存 5 分钟：否则页面每刷一次就来撞一次墙，限额一直不恢复。
            ttl = TTL_SECONDS if len(merged) >= len(rows) else (300.0 if rate_limited else 60.0)
            _cache.update({'value': value, 'expires': now + ttl})
        elif rate_limited:
            # 限流且没有快照可退：把"空"也缓存住。
            # 否则页面每刷一次就重新撞 6 批 429，一次请求要 10 秒以上。
            _cache.update({'value': value, 'expires': now + 300.0})
    if merged:
        _save_disk(value)
    return value


def _load_disk() -> Dict[str, Any] | None:
    try:
        return json.loads(CACHE_FILE.read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001 - 没有快照就是没有
        return None


def _save_disk(value: Dict[str, Any]) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    except Exception:  # noqa: BLE001 - 写盘失败不影响本次结果
        pass
