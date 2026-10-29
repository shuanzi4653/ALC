# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import httpx

from weather.metar_history import USER_AGENT

logger = logging.getLogger(__name__)

URL = 'https://api.open-meteo.com/v1/forecast'
CURRENT = ('temperature_2m,weather_code,wind_speed_10m,wind_direction_10m,'
           'relative_humidity_2m,apparent_temperature')
TTL_SECONDS = 600

_cache: Dict[str, Any] = {'expires': 0.0, 'value': None}
_lock = threading.Lock()

def _condition(code: Any) -> str:
    try:
        c = int(code)
    except (TypeError, ValueError):
        return '—'
    if c == 0:
        return '晴'
    if c in (1, 2):
        return '少云'
    if c == 3:
        return '阴'
    if c in (45, 48):
        return '雾'
    if c in (51, 53, 55, 56, 57):
        return '毛毛雨'
    if c in (61, 63, 65, 66, 67):
        return '雨'
    if c in (71, 73, 75, 77):
        return '雪'
    if c in (80, 81, 82):
        return '阵雨'
    if c in (85, 86):
        return '阵雪'
    if c in (95, 96, 99):
        return '雷暴'
    return '—'

_DIRS = ['北', '东北', '东', '东南', '南', '西南', '西', '西北']

def wind_text(deg: Any) -> Optional[str]:
    try:
        d = float(deg) % 360
    except (TypeError, ValueError):
        return None
    return _DIRS[int((d + 22.5) // 45) % 8] + '风'

def _icon(code: Any) -> str:
    text = _condition(code)
    return {
        '晴': '☀', '少云': '🌤', '阴': '☁', '雾': '🌫', '毛毛雨': '🌦',
        '雨': '🌧', '雪': '🌨', '阵雨': '🌦', '阵雪': '🌨', '雷暴': '⛈',
    }.get(text, '·')

def city_weather(places: Sequence[Dict[str, Any]], force: bool = False) -> Dict[str, Any]:
    rows = [p for p in places if p.get('lat') is not None and p.get('lng') is not None]
    if not rows:
        return {'available': False, 'reason': '没有可用的城市坐标', 'cities': []}

    now = time.monotonic()
    with _lock:
        cached = _cache['value']
        if not force and cached is not None and now < _cache['expires']:
            return {**cached, 'cache': 'HIT'}

    lats = ','.join(f'{float(p["lat"]):.4f}' for p in rows)
    lons = ','.join(f'{float(p["lng"]):.4f}' for p in rows)
    retrieved = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        with httpx.Client(timeout=httpx.Timeout(12, connect=5), trust_env=False) as client:
            response = client.get(URL, params={
                'latitude': lats, 'longitude': lons,
                'current': CURRENT, 'timezone': 'UTC', 'wind_speed_unit': 'ms',
            }, headers={'User-Agent': USER_AGENT})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning('城市当前天气取数失败：%s: %s', type(exc).__name__, exc)
        return {'available': False, 'reason': f'{type(exc).__name__}', 'cities': [],
                'retrievedAt': retrieved}

    items = payload if isinstance(payload, list) else [payload]
    cities: List[Dict[str, Any]] = []
    for place, item in zip(rows, items):
        cur = (item or {}).get('current') or {}
        if cur.get('temperature_2m') is None:
            continue
        cities.append({
            'id': place.get('id'),
            'name': place.get('name'),
            'tempC': round(float(cur['temperature_2m']), 1),
            'feelsC': None if cur.get('apparent_temperature') is None else round(float(cur['apparent_temperature']), 1),
            'windMs': None if cur.get('wind_speed_10m') is None else round(float(cur['wind_speed_10m']), 1),
            'windDirDeg': cur.get('wind_direction_10m'),
            'windDirText': wind_text(cur.get('wind_direction_10m')),
            'humidity': None if cur.get('relative_humidity_2m') is None else int(cur['relative_humidity_2m']),
            'code': cur.get('weather_code'),
            'condition': _condition(cur.get('weather_code')),
            'icon': _icon(cur.get('weather_code')),
        })

    if not cities:
        return {'available': False, 'reason': '返回里没有当前温度字段', 'cities': [], 'retrievedAt': retrieved}

    value = {'available': True, 'cities': cities, 'retrievedAt': retrieved,
             'provider': 'Open-Meteo current', 'dataType': 'PUBLIC_MODEL_CURRENT'}
    with _lock:
        _cache['value'] = value
        _cache['expires'] = now + TTL_SECONDS
    return value
