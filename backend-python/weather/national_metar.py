# -*- coding: utf-8 -*-
"""全国 METAR 实况（只读、只做聚合）。

数据源与东三省那套同一个：`aviationweather.gov` 的公开 METAR 接口，一次 bbox 拉全国。
**不合成、不插值、不补零**：拿不到就是拿不到，`available=false`，由上层按"无源"处理。

与 `weather/metar_history.py` 的分工：那边只服务东三省的运行计划（3 站、逐小时序列）；
这边服务全国屏（所有在报文的站，只要最新一帧）。
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from weather.metar_history import KT_TO_MS, parse_visibility

URL = 'https://aviationweather.gov/api/data/metar'
HOURS = 3
TTL_SECONDS = 300.0
TIMEOUT_SECONDS = 25.0
USER_AGENT = 'ALC-tianchuang/1.0.1 (national layer; contact: project maintainer)'

# 省级代表站 + 备选站。**不按省写死映射**：报文回来什么站，就按经纬度落进省界多边形，
# 落不进去（境外站）自然被过滤。某个省一个站都没回，就是没接入，不补零。
STATION_IDS = (
    # 直辖市 / 省会 / 首府
    'ZBAA', 'ZBTJ', 'ZBSJ', 'ZBYN', 'ZBHH',
    'ZYTX', 'ZYCC', 'ZYHB',
    'ZSSS', 'ZSNJ', 'ZSHC', 'ZSOF', 'ZSFZ', 'ZSCN', 'ZSJN', 'ZSQD',
    'ZHCC', 'ZHHH', 'ZGHA', 'ZGGG', 'ZGNN', 'ZJHK', 'ZJSY',
    'ZUCK', 'ZUUU', 'ZUGY', 'ZPPP', 'ZULS',
    'ZLXY', 'ZLLL', 'ZLXN', 'ZLIC', 'ZWWW',
    'RCTP', 'VHHH', 'VMMC',
    # 备选（省会主站不发报文时兜底，仍按坐标归属，不做人为指派）
    'ZSGZ', 'ZSJD', 'ZSYT', 'ZUNZ', 'ZURK', 'ZLGM', 'ZLZW', 'ZLLL', 'ZWWW', 'ZPPP',
)

_cache: Dict[str, Any] = {'expires': 0.0, 'value': None}
_lock = threading.Lock()


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _row(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    code = entry.get('icaoId')
    epoch = entry.get('obsTime')
    lon, lat = _num(entry.get('lon')), _num(entry.get('lat'))
    if not code or not isinstance(epoch, (int, float)) or lon is None or lat is None:
        return None
    wind = _num(entry.get('wspd'))
    gust = _num(entry.get('wgst'))
    vis = parse_visibility(entry.get('visib'))
    return {
        'station': code,
        'name': entry.get('name') or '',
        'lon': round(lon, 4),
        'lat': round(lat, 4),
        'epoch': int(epoch),
        'ts': datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'visM': vis,
        'gustMps': None if gust is None else round(gust * KT_TO_MS, 2),
        'windMps': None if wind is None else round(wind * KT_TO_MS, 2),
        'tempC': _num(entry.get('temp')),
        'raw': entry.get('rawOb'),
    }


def fetch(force: bool = False) -> Dict[str, Any]:
    """拉全国最新一帧。失败返回 `available=false`，不抛给调用方。"""
    now = time.monotonic()
    with _lock:
        cached = _cache['value']
        if not force and cached is not None and now < _cache['expires']:
            return cached
    params = {'ids': ','.join(dict.fromkeys(STATION_IDS)), 'format': 'json', 'hours': str(HOURS)}
    try:
        response = httpx.get(URL, params=params, timeout=TIMEOUT_SECONDS,
                             headers={'User-Agent': USER_AGENT})
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - 网络不可用是常态，不能把页面打崩
        value = {'available': False, 'fetchedAt': datetime.now(timezone.utc)
                 .strftime('%Y-%m-%dT%H:%M:%SZ'), 'error': str(exc)[:120], 'stations': {}}
        with _lock:
            _cache.update({'value': value, 'expires': now + 30.0})
        return value

    latest: Dict[str, Dict[str, Any]] = {}
    for entry in payload if isinstance(payload, list) else []:
        row = _row(entry)
        if row is None:
            continue
        previous = latest.get(row['station'])
        if previous is None or row['epoch'] > previous['epoch']:
            latest[row['station']] = row
    value = {
        'available': True,
        'fetchedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'source': 'METAR (aviationweather.gov)',
        'hours': HOURS,
        'stations': latest,
    }
    with _lock:
        _cache.update({'value': value, 'expires': now + TTL_SECONDS})
    return value
