# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import logging

import httpx

from .metar_history import STATION_INFO, STATIONS, USER_AGENT

URL = 'https://api.open-meteo.com/v1/forecast'
HOURLY = 'visibility,wind_gusts_10m,wind_speed_10m,temperature_2m,relative_humidity_2m'

logger = logging.getLogger(__name__)

_cache: Dict[str, Any] = {'expires': 0.0, 'value': None}
_lock = threading.Lock()

def _fetch_station(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    try:
        with httpx.Client(timeout=httpx.Timeout(10, connect=4), trust_env=False) as client:
            response = client.get(URL, params={
                'latitude': lat, 'longitude': lon, 'hourly': HOURLY,
                'forecast_days': 2, 'timezone': 'UTC', 'wind_speed_unit': 'ms',
            }, headers={'User-Agent': USER_AGENT})
            response.raise_for_status()
            payload = response.json()
        return payload.get('hourly')
    except Exception as exc:  # noqa: BLE001
        logger.warning('Open-Meteo 预报取数失败 lat=%.3f lon=%.3f：%s: %s',
                       lat, lon, type(exc).__name__, exc)
        return None

def forecast(hours: int = 8, force: bool = False) -> Dict[str, Any]:
    now = time.monotonic()
    with _lock:
        if not force and _cache['value'] is not None and now < _cache['expires']:
            return {**_cache['value'], 'cache': 'HIT'}
    retrieved = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    stations: Dict[str, Any] = {}
    for station in STATIONS:
        info = STATION_INFO[station]
        hourly = _fetch_station(info['lat'], info['lon'])
        if not hourly or 'time' not in hourly:
            stations[station] = {'available': False, 'reason': 'OPEN_METEO_UNREACHABLE'}
            continue
        times = hourly['time']
        try:
            start = next(i for i, t in enumerate(times)
                         if datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
                         >= datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0))
        except StopIteration:
            start = 0
        step = []
        for i in range(start, min(len(times), start + hours)):
            step.append({
                'timeUtc': times[i] + 'Z' if not times[i].endswith('Z') else times[i],
                'visM': hourly['visibility'][i],
                'gustMs': hourly['wind_gusts_10m'][i],
                'windMs': hourly['wind_speed_10m'][i],
                'tempC': hourly['temperature_2m'][i],
                'rhPct': hourly['relative_humidity_2m'][i],
            })
        stations[station] = {'available': bool(step), 'hours': step}
    available = [s for s in stations.values() if s.get('available')]
    value = {
        'available': bool(available),
        'provider': 'OPEN_METEO',
        'dataType': 'MODEL_FORECAST',
        'retrievedAt': retrieved,
        'stations': stations,
        'note': '模式逐时值，不带起报时刻；只用于 3–6 h 延伸，不参与模型输入',
    }
    with _lock:
        _cache['value'] = value
        _cache['expires'] = now + 600
    return {**value, 'cache': 'MISS'}

def station_hours(hours: int = 8) -> Dict[str, List[Dict[str, Any]]]:
    payload = forecast(hours=hours)
    return {s: ((payload.get('stations') or {}).get(s) or {}).get('hours') or [] for s in STATIONS}
