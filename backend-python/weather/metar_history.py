# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

URL = 'https://aviationweather.gov/api/data/metar'
STATIONS = ('ZYTX', 'ZYCC', 'ZYHB')
STATION_INFO = {
    'ZYTX': {'name': '沈阳桃仙', 'lat': 41.6398, 'lon': 123.4833},
    'ZYCC': {'name': '长春龙嘉', 'lat': 43.9962, 'lon': 125.6853},
    'ZYHB': {'name': '哈尔滨太平', 'lat': 45.6234, 'lon': 126.2500},
    'ZYTL': {'name': '大连周水子', 'lat': 38.9657, 'lon': 121.5386},
}
USER_AGENT = 'ALC-tianchuang/0.11.1 (low-altitude nowcast; contact: project maintainer)'
KT_TO_MS = 0.514444
SM_TO_M = 1609.344

_cache: Dict[str, Any] = {'expires': 0.0, 'value': None}
_lock = threading.Lock()

def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)

def parse_visibility_detail(raw: Any) -> Tuple[Optional[float], bool, str]:
    if raw is None:
        return None, False, ''
    text = str(raw).strip().upper()
    if not text:
        return None, False, ''
    lower_bound = text.endswith('+')
    body = text.rstrip('+')
    try:
        if '/' in body:
            total = 0.0
            for part in body.split():
                if '/' in part:
                    a, b = part.split('/')
                    total += float(a) / float(b)
                else:
                    total += float(part)
            miles = total
        else:
            miles = float(body)
    except (ValueError, ZeroDivisionError):
        return None, False, str(raw)
    return round(miles * SM_TO_M, 1), lower_bound, str(raw)

def parse_visibility(raw: Any) -> Optional[float]:
    value, _lower, _raw = parse_visibility_detail(raw)
    return value

def _row(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    station = entry.get('icaoId')
    epoch = entry.get('obsTime')
    if station not in STATIONS or not isinstance(epoch, (int, float)):
        return None
    wind = _num(entry.get('wspd'))
    gust = _num(entry.get('wgst'))
    wind_ms = None if wind is None else round(wind * KT_TO_MS, 2)
    gust_ms = None if gust is None else round(gust * KT_TO_MS, 2)
    gust_source = 'OBSERVED'
    if gust_ms is None:
        gust_ms, gust_source = wind_ms, 'FALLBACK_WIND'
    clouds = entry.get('clouds') or []
    bases = [c.get('base') for c in clouds if isinstance(c, dict) and isinstance(c.get('base'), (int, float))]
    cover = (entry.get('cover') or '').strip() or None
    cloud_base = round(min(bases) * 0.3048, 1) if bases else None
    cloud_source = 'OBSERVED'
    if cloud_base is None and cover in ('CLR', 'SKC', 'NSC', 'NCD', 'CAVOK', None):
        cloud_base, cloud_source = 5000.0, 'CLEAR_SENTINEL'
    vis_value, vis_lower, vis_raw = parse_visibility_detail(entry.get('visib'))
    return {
        'station': station,
        'epoch': int(epoch),
        'timeUtc': datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'visM': vis_value,
        'visLowerBound': vis_lower,
        'visRaw': vis_raw,
        'gustMs': gust_ms,
        'gustSource': gust_source,
        'windMs': wind_ms,
        'wdirDeg': _num(entry.get('wdir')),
        'tempC': _num(entry.get('temp')),
        'dewC': _num(entry.get('dewp')),
        'cloudBaseM': cloud_base,
        'cloudSource': cloud_source,
        'skyCover': cover,
        'qnhHpa': _num(entry.get('altim')),
        'rawOb': entry.get('rawOb'),
    }

def _hourly(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    per: Dict[str, Dict[int, Dict[str, Any]]] = {s: {} for s in STATIONS}
    for row in rows:
        hour = row['epoch'] - row['epoch'] % 3600
        prev = per[row['station']].get(hour)
        if prev is None or row['epoch'] > prev['epoch']:
            per[row['station']][hour] = row
    return {s: [per[s][k] for k in sorted(per[s])] for s in STATIONS}

def fetch(force: bool = False, hours: int = 9) -> Dict[str, Any]:
    now = time.monotonic()
    with _lock:
        if not force and _cache['value'] is not None and now < _cache['expires']:
            return {**_cache['value'], 'cache': 'HIT'}
    retrieved = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        with httpx.Client(timeout=httpx.Timeout(12, connect=5), trust_env=False) as client:
            response = client.get(URL, params={'ids': ','.join(STATIONS), 'format': 'json', 'hours': hours},
                                  headers={'User-Agent': USER_AGENT})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001 — 外部源失败是正常状态，不是崩溃
        value = {
            'available': False, 'reason': 'METAR_UNREACHABLE', 'detail': str(exc)[:200],
            'retrievedAt': retrieved, 'provider': 'AVIATION_WEATHER_CENTER',
            'dataType': 'STATION_OBSERVATION_METAR', 'stations': {},
        }
        with _lock:
            _cache['value'] = value
            _cache['expires'] = now + 120
        return value

    rows = [r for r in (_row(e) for e in payload if isinstance(e, dict)) if r]
    grouped = _hourly(rows)
    stations = {}
    for station, series in grouped.items():
        info = STATION_INFO[station]
        stations[station] = {
            'station': station, 'name': info['name'], 'lat': info['lat'], 'lon': info['lon'],
            'observations': len(series),
            'latest': series[-1] if series else None,
            'series': series,
        }
    value = {
        'available': bool(rows),
        'provider': 'AVIATION_WEATHER_CENTER',
        'dataType': 'STATION_OBSERVATION_METAR',
        'retrievedAt': retrieved,
        'horizonHours': hours,
        'stations': stations,
        'qualityFlags': [
            'STATION_OBSERVATION_NOT_AREA_FIELD',
            'VISIBILITY_IS_LOWER_BOUND_WHEN_REPORTED_WITH_PLUS',
            'GUST_FALLBACK_TO_SUSTAINED_WIND_WHEN_NOT_REPORTED',
            'AIRPORT_POINT_MAY_DIFFER_FROM_CORRIDOR',
        ],
    }
    with _lock:
        _cache['value'] = value
        _cache['expires'] = now + 600
    return {**value, 'cache': 'MISS'}

def station_histories(hours: int = 7, force: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """每站最近 `hours+1` 个小时的逐小时观测（最后一条是当前时刻）。"""
    payload = fetch(force=force)
    out = {}
    for station in STATIONS:
        series = ((payload.get('stations') or {}).get(station) or {}).get('series') or []
        out[station] = series[-(hours + 1):]
    return out
