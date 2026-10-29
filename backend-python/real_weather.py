# -*- coding: utf-8 -*-

import math
from datetime import datetime, timedelta, timezone

import httpx

CURRENT_FIELDS = (
    'temperature_2m', 'relative_humidity_2m', 'precipitation', 'weather_code',
    'wind_speed_10m', 'wind_direction_10m', 'wind_gusts_10m', 'surface_pressure',
    'cloud_cover',
)
HOURLY_FIELDS = (
    'temperature_2m', 'wind_speed_10m', 'wind_gusts_10m', 'precipitation', 'visibility',
)

API_BASE = 'https://api.open-meteo.com/v1/forecast'
TIMEOUT = httpx.Timeout(12, connect=4)
_WMO_TEXT = {
    0: '晴', 1: '晴间多云', 2: '多云', 3: '阴',
    45: '雾', 48: '雾凇',
    51: '毛毛雨', 53: '小雨', 55: '中雨',
    56: '冻毛毛雨', 57: '冻雨',
    61: '小雨', 63: '中雨', 65: '大雨',
    66: '冻雨', 67: '强冻雨',
    71: '小雪', 73: '中雪', 75: '大雪', 77: '米雪',
    80: '阵雨', 81: '强阵雨', 82: '暴雨',
    85: '阵雪', 86: '强阵雪',
    95: '雷暴', 96: '雷暴伴小冰雹', 99: '雷暴伴大冰雹',
}

class SourceUnavailable(RuntimeError):
    """取数失败。调用方必须显式降级，不得用任何本地生成值替代。"""

def _local_iso(moment):
    if moment is None:
        return None
    return moment if ('+' in moment[10:] or moment.endswith('Z')) else moment + '+08:00'

def _value(series, index, default=None):
    """按索引取一个可能缺项的量。缺项返回 default，绝不插值。"""
    if not isinstance(series, list) or index >= len(series):
        return default
    value = series[index]
    return default if value is None else value

def snapshot(lat, lon, hours=6, client=None):
    params = {
        'latitude': f'{lat:.5f}', 'longitude': f'{lon:.5f}',
        'current': ','.join(CURRENT_FIELDS), 'hourly': ','.join(HOURLY_FIELDS),
        'wind_speed_unit': 'ms', 'timezone': 'Asia/Shanghai', 'forecast_days': 2,
    }
    owned = client is None
    client = client or httpx.Client(timeout=TIMEOUT, trust_env=False)
    try:
        response = client.get(API_BASE, params=params)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise SourceUnavailable(f'Open-Meteo 返回 HTTP {exc.response.status_code}') from None
    except httpx.HTTPError as exc:
        raise SourceUnavailable(f'Open-Meteo 网络失败：{type(exc).__name__}') from None
    except ValueError:
        raise SourceUnavailable('Open-Meteo 返回内容不是合法 JSON') from None
    finally:
        if owned:
            client.close()

    current = payload.get('current') or {}
    hourly = payload.get('hourly') or {}
    if not current:
        raise SourceUnavailable('Open-Meteo 响应缺少 current 段')

    retrieved = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    code = current.get('weather_code')
    observed_at = _local_iso(current.get('time'))
    result = {
        'snapshot': {
            'time': observed_at,
            'source': 'open-meteo',
            'dataType': 'MODEL_ESTIMATE',
            'retrievedAt': retrieved,
            'qualityFlags': ['MODEL_ESTIMATE_NOT_STATION_OBSERVATION'],
            'lat': lat,
            'lon': lon,
            'conditionText': _WMO_TEXT.get(code),
            'weatherCode': code,
            'tempC': _value_list(current, 'temperature_2m'),
            'humidity': _percent(current.get('relative_humidity_2m')),
            'windSpeed': _value_list(current, 'wind_speed_10m'),
            'windGust': _value_list(current, 'wind_gusts_10m'),
            'windDeg': current.get('wind_direction_10m'),
            'precipMmh': _value_list(current, 'precipitation'),
            'visibilityM': _first_hourly(hourly, 'visibility'),
            'pressureHpa': _value_list(current, 'surface_pressure'),
            'cloudCover': _percent(current.get('cloud_cover')),
            'thunderProb': None,
        },
        'hourly': _hourly_rows(hourly, hours),
        'provider': 'OPEN_METEO',
    }
    return result

def _value_list(node, key):
    value = node.get(key)
    return None if isinstance(value, bool) or not isinstance(value, (int, float)) else round(float(value), 2)

def _percent(value):
    """Open-Meteo 给的是 0-100 的百分数；内部契约是 0-1 的小数。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value) / 100.0, 3)

def _first_hourly(hourly, key):
    series = hourly.get(key)
    if not isinstance(series, list):
        return None
    value = next((item for item in series if item is not None), None)
    return None if value is None else round(float(value), 1)

def _hourly_rows(hourly, hours):
    times = hourly.get('time')
    if not isinstance(times, list) or not times:
        return []
    now = datetime.now(timezone(timedelta(hours=8)))
    stamp = now.strftime('%Y-%m-%dT%H:00')
    start = next((index for index, item in enumerate(times) if item and item >= stamp), 0)
    rows = []
    for index in range(start, min(start + hours, len(times))):
        row = {'time': _local_iso(_value(times, index))}
        values = {
            'tempC': ('temperature_2m', 1),
            'windSpeed': ('wind_speed_10m', 1),
            'windGust': ('wind_gusts_10m', 1),
            'precipMmh': ('precipitation', 2),
            'visibilityM': ('visibility', 0),
        }
        for target, (source_key, digits) in values.items():
            value = _value(hourly.get(source_key), index)
            row[target] = None if value is None else round(float(value), digits)
        row['thunderProb'] = None
        rows.append(row)
    return rows

def status():
    return {
        'provider': 'OPEN_METEO',
        'dataType': 'MODEL_ESTIMATE',
        'endpoint': API_BASE,
        'credentialed': False,
        'fields': list(CURRENT_FIELDS),
        'note': '公共模式估算，非测站观测；取数失败时调用方必须显式降级，本模块不产出任何合成值。',
    }
