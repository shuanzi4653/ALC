from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

FEATURE_NAMES = (
    'windSpeed', 'windGust', 'precipMmh', 'visibilityM', 'tempC', 'rhPct',
    'cloudPct', 'pressureHpa', 'gustFactor', 'precipType',
    'hourSin', 'hourCos', 'month',
    'miss_wind', 'miss_vis', 'miss_precip',
)

MISS_FLAG_KEYS = {
    'miss_wind': 'windSpeed',
    'miss_vis': 'visibilityM',
    'miss_precip': 'precipMmh',
}

pressureNote = (
    '训练侧取的是海平面气压（pressure_msl），运行时快照给的是地面气压（surface_pressure）。'
    '两者不等，但差值主要取决于测站海拔，在同一城市内近似常量；本模型不拿气压做阈值判断，'
    '只作为弱特征，故不做订正，并在模型 JSON 里记下这条口径。'
)

def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    return None

def _scale_percent(value: Any) -> Optional[float]:
    v = _num(value)
    if v is None:
        return None
    return v * 100.0 if v <= 1.5 else v

def from_sample(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'windSpeed': _num(row.get('windMps')),
        'windGust': _num(row.get('gustMps')),
        'precipMmh': _num(row.get('precipMmh')),
        'visibilityM': _num(row.get('visibilityM')),
        'tempC': _num(row.get('temperatureC')),
        'rhPct': _num(row.get('rhPct')),
        'cloudPct': _num(row.get('cloudPct')),
        'pressureHpa': _num(row.get('pressureHpa')),
        'rainMmh': _num(row.get('rainMmh')),
        'snowCmh': _num(row.get('snowCmh')),
        'hour': _num(row.get('hour')),
        'month': _num(row.get('monthNum')),
    }

def from_runtime(snapshot: Dict[str, Any], hour: Optional[float] = None,
                 month: Optional[float] = None) -> Dict[str, Any]:
    return {
        'windSpeed': _num(snapshot.get('windSpeed')),
        'windGust': _num(snapshot.get('windGust')),
        'precipMmh': _num(snapshot.get('precipMmh')),
        'visibilityM': _num(snapshot.get('visibilityM')),
        'tempC': _num(snapshot.get('tempC')),
        'rhPct': _scale_percent(snapshot.get('humidity')),
        'cloudPct': _scale_percent(snapshot.get('cloudCover')),
        'pressureHpa': _num(snapshot.get('pressureHpa')),
        'rainMmh': _num(snapshot.get('rainMmh')),
        'snowCmh': _num(snapshot.get('snowfallCmh')),
        'hour': _num(hour if hour is not None else snapshot.get('hour')),
        'month': _num(month if month is not None else snapshot.get('month')),
    }

def vector(canon: Dict[str, Any], defaults: Dict[str, float]) -> List[float]:
    wind = canon.get('windSpeed')
    gust = canon.get('windGust')
    gust_factor = (gust / wind) if (wind and gust and wind >= 3.0) else None

    rain = canon.get('rainMmh')
    snow = canon.get('snowCmh')
    precip_type = 0.0
    if (rain or 0) > 0 and (snow or 0) > 0:
        precip_type = 3.0
    elif (snow or 0) > 0:
        precip_type = 2.0
    elif (rain or 0) > 0:
        precip_type = 1.0

    hour = canon.get('hour')
    month = canon.get('month')
    hour_rad = (hour % 24) * 2 * math.pi / 24.0 if hour is not None else None
    month_val = month if month is not None else None

    raw = {
        'windSpeed': canon.get('windSpeed'),
        'windGust': canon.get('windGust'),
        'precipMmh': canon.get('precipMmh'),
        'visibilityM': canon.get('visibilityM'),
        'tempC': canon.get('tempC'),
        'rhPct': canon.get('rhPct'),
        'cloudPct': canon.get('cloudPct'),
        'pressureHpa': canon.get('pressureHpa'),
        'gustFactor': gust_factor,
        'precipType': precip_type,
        'hourSin': math.sin(hour_rad) if hour_rad is not None else None,
        'hourCos': math.cos(hour_rad) if hour_rad is not None else None,
        'month': month_val,
    }

    out: List[float] = []
    for name in FEATURE_NAMES:
        if name in MISS_FLAG_KEYS:
            source = raw.get(MISS_FLAG_KEYS[name])
            out.append(1.0 if source is None else 0.0)
            continue
        value = raw.get(name)
        if value is None:
            out.append(float(defaults.get(name, 0.0)))
        else:
            out.append(float(value))
    return out

def missing_of(canon: Dict[str, Any]) -> List[str]:
    keys = ('windSpeed', 'windGust', 'precipMmh', 'visibilityM', 'tempC', 'rhPct')
    return [k for k in keys if canon.get(k) is None]
