# -*- coding: utf-8 -*-
"""模型实况（open-meteo）—— 只给「没有 METAR 报文的省」兜底，屏上必须标 MODEL。

原则
----
- 真实报文优先：某省有 METAR 站就完全不用模型值。
- 模型值**不改写任何判据**：它只是让"这一屏不至于空白"，带 `source: MODEL`，
  前端单独着色、单独标注，不和 METAR 混在一起统计。
- 拿不到就返回空，不补零、不插值。

    from weather import model_stations
    model_stations.fetch()['points']
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

URL = 'https://api.open-meteo.com/v1/forecast'
TTL_SECONDS = 600.0
TIMEOUT_SECONDS = 20.0
USER_AGENT = 'ALC-tianchuang/1.0.1 (model fallback; contact: project maintainer)'

# 北方 13 省省会（模型兜底点，仅用于没有 METAR 的省）
CAPITALS = (
    ('北京市', '北京', 116.407, 39.904),
    ('天津市', '天津', 117.201, 39.085),
    ('河北省', '石家庄', 114.514, 38.042),
    ('山西省', '太原', 112.549, 37.857),
    ('内蒙古自治区', '呼和浩特', 111.751, 40.842),
    ('辽宁省', '沈阳', 123.431, 41.805),
    ('吉林省', '长春', 125.324, 43.887),
    ('黑龙江省', '哈尔滨', 126.535, 45.803),
    ('陕西省', '西安', 108.940, 34.341),
    ('甘肃省', '兰州', 103.834, 36.061),
    ('青海省', '西宁', 101.778, 36.617),
    ('宁夏回族自治区', '银川', 106.231, 38.487),
    ('新疆维吾尔自治区', '乌鲁木齐', 87.617, 43.793),
)

_cache: Dict[str, Any] = {'expires': 0.0, 'value': None}
_lock = threading.Lock()


def _num(value: Any) -> Any:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def fetch(force: bool = False) -> Dict[str, Any]:
    now = time.monotonic()
    with _lock:
        if not force and _cache['value'] is not None and now < _cache['expires']:
            return _cache['value']
    params = {
        'latitude': ','.join(f'{lat}' for _, _, _, lat in CAPITALS),
        'longitude': ','.join(f'{lon}' for _, _, lon, _ in CAPITALS),
        'current': 'temperature_2m,wind_speed_10m,visibility,weather_code',
        'timezone': 'UTC',
    }
    payload: Any = None
    error = None
    for attempt in range(2):
        try:
            response = httpx.get(URL, params=params, timeout=TIMEOUT_SECONDS,
                                 headers={'User-Agent': USER_AGENT})
            response.raise_for_status()
            payload = response.json()
            break
        except Exception as exc:  # noqa: BLE001 - 模型源不可用不能把页面打崩
            error = str(exc)[:120]
            time.sleep(1.5 * (attempt + 1))
    if payload is None:
        value = {'available': False, 'error': error, 'points': []}
        with _lock:
            _cache.update({'value': value, 'expires': now + 30.0})
        return value

    rows: List[Dict[str, Any]] = payload if isinstance(payload, list) else [payload]
    points: List[Dict[str, Any]] = []
    for (province, name, lon, lat), row in zip(CAPITALS, rows):
        current = (row or {}).get('current') or {}
        wind_kmh = _num(current.get('wind_speed_10m'))
        points.append({
            'code': f'MODEL-{name}',
            'name': province,
            'city': name,
            'lon': lon,
            'lat': lat,
            'tempC': _num(current.get('temperature_2m')),
            'windMps': round(wind_kmh / 3.6, 1) if wind_kmh is not None else None,
            'visM': _num(current.get('visibility')),
            'weatherCode': current.get('weather_code'),
            'ts': (current.get('time') or '') + ':00Z' if current.get('time') else None,
            'source': 'MODEL',
            'low': (_num(current.get('visibility')) or 99999) < 3000,
        })
    value = {
        'available': True,
        'source': 'open-meteo model (current)',
        'fetchedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'points': points,
    }
    with _lock:
        _cache.update({'value': value, 'expires': now + TTL_SECONDS})
    return value
