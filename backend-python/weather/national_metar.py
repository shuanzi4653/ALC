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
from functools import lru_cache
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from weather.metar_history import KT_TO_MS, parse_visibility_detail

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
# 最近一次成功快照：网络抽风时回退到它，并在返回里标 stale + 距今年龄。
# 这不是"补零"——数据仍是真实报文，只是旧了几分钟，界面必须照实说"几点的"。
_last_good: Dict[str, Any] = {'value': None, 'at': 0.0}
STALE_MAX_SECONDS = 1800.0
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
    vis, vis_lower, _ = parse_visibility_detail(entry.get('visib'))
    return {
        'station': code,
        'name': entry.get('name') or '',
        'lon': round(lon, 4),
        'lat': round(lat, 4),
        'epoch': int(epoch),
        'ts': datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'visM': vis,
        # 报文里写 "6+" 的，6 是**下界**不是实测值（aviationweather 对 ≥6 SM 一律给 "6+"）。
        # 界面必须显示 "≥"，否则一排站全变成同一个 9656 m，看着像假数据。
        'visLower': bool(vis_lower),
        'gustMps': None if gust is None else round(gust * KT_TO_MS, 2),
        'windMps': None if wind is None else round(wind * KT_TO_MS, 2),
        'tempC': _num(entry.get('temp')),
        'raw': entry.get('rawOb'),
    }


NORTH_PROVINCES = ('北京市', '天津市', '河北省', '山西省', '内蒙古自治区', '辽宁省', '吉林省',
                   '黑龙江省', '陕西省', '甘肃省', '青海省', '宁夏回族自治区', '新疆维吾尔自治区')


@lru_cache(maxsize=2)
def province_bounds() -> Dict[str, Any]:
    import json
    from pathlib import Path
    from shapely.geometry import shape
    asset = Path(__file__).resolve().parents[2] / 'frontend' / 'src' / 'assets' / 'china.json'
    payload = json.loads(asset.read_text(encoding='utf-8'))
    out: Dict[str, Any] = {}
    for feature in payload.get('features') or []:
        name = (feature.get('properties') or {}).get('name')
        geometry = feature.get('geometry')
        if not name or not geometry:
            continue
        out[name] = shape(geometry)
    return out


def _rows_from(payload: Any) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for entry in payload if isinstance(payload, list) else []:
        row = _row(entry)
        if row is None:
            continue
        previous = latest.get(row['station'])
        if previous is None or row['epoch'] > previous['epoch']:
            latest[row['station']] = row
    return latest


def fetch_north(force: bool = False) -> Dict[str, Any]:
    """按省 bbox 拉北方 13 省的报文站（一次 bbox 会被截断到 400 行，分省更稳）。

    归属用**点在面**：站必须真的落在这个省的多边形里，边境站不会两边都算。
    """
    now = time.monotonic()
    with _lock:
        cached = _cache.get('north')
        if not force and cached and now < _cache.get('north_expires', 0.0):
            return cached
    from shapely.geometry import Point
    from shapely.prepared import prep
    merged: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    for name in NORTH_PROVINCES:
        geometry = province_bounds().get(name)
        if geometry is None:
            continue
        minx, miny, maxx, maxy = geometry.bounds
        params = {'bbox': f'{miny:.2f},{minx:.2f},{maxy:.2f},{maxx:.2f}',
                  'format': 'json', 'hours': str(HOURS)}
        try:
            response = httpx.get(URL, params=params, timeout=TIMEOUT_SECONDS,
                                 headers={'User-Agent': USER_AGENT})
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            errors.append(f'{name}: {str(exc)[:60]}')
            continue
        prepared = prep(geometry)
        for row in _rows_from(payload).values():
            if not prepared.contains(Point(row['lon'], row['lat'])):
                continue
            row = {**row, 'province': name}
            previous = merged.get(row['station'])
            if previous is None or row['epoch'] > previous['epoch']:
                merged[row['station']] = row
    value = {
        'available': True, 'source': 'METAR (aviationweather.gov，分省 bbox)',
        'fetchedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'stations': merged, 'errors': errors,
    }
    with _lock:
        _cache['north'] = value
        _cache['north_expires'] = now + TTL_SECONDS
    return value


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
        good = _last_good.get('value')
        age = now - float(_last_good.get('at') or 0.0)
        if good and age <= STALE_MAX_SECONDS:
            value = {**good, 'stale': True, 'error': str(exc)[:120],
                     'staleMinutes': round(age / 60.0, 1)}
        else:
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
        _last_good.update({'value': {**value, 'stale': False}, 'at': now})
    return value
