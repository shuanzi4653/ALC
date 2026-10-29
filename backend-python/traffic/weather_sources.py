import hashlib
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

_CACHE = {'expires': 0.0, 'value': None}
_QW_CACHE = {'expires': 0.0, 'value': None}
CURRENT_FIELDS = ','.join((
    'temperature_2m', 'relative_humidity_2m', 'precipitation', 'weather_code',
    'wind_speed_10m', 'wind_direction_10m', 'wind_gusts_10m',
))
HOURLY_FIELDS = ','.join((
    'precipitation_probability', 'precipitation', 'wind_speed_100m', 'wind_direction_100m', 'visibility',
))

JAVA_BASE = os.environ.get('ALC_JAVA_BASE', 'http://127.0.0.1:8085')
INTERNAL_TOKEN = os.environ.get('ALC_INTERNAL_TOKEN', '')
PROVIDER = os.environ.get('ALC_TRAFFIC_WEATHER_PROVIDER', 'open-meteo').strip().lower()
QWEATHER_MAX_CITIES = int(os.environ.get('ALC_QWEATHER_MAX_CITIES', '36'))

USER_AGENT = os.environ.get(
    'ALC_HTTP_USER_AGENT', 'tianchuang-alc/1.0.0 (low-altitude traffic research)')
MET_NO_URL = 'https://api.met.no/weatherapi/locationforecast/2.0/compact'
MET_NO_MAX_CITIES = int(os.environ.get('ALC_MET_NO_MAX_CITIES', '36'))
AVIATION_URL = 'https://aviationweather.gov/api/data/metar'
AVIATION_BBOX = os.environ.get('ALC_AVIATION_BBOX', '38,115,54,136')
AVIATION_RADIUS_KM = float(os.environ.get('ALC_AVIATION_RADIUS_KM', '150'))
KT_TO_MPS = 0.514444
SM_TO_M = 1609.344
MULTI_MODEL_ENDPOINTS = {
    'GFS': 'https://api.open-meteo.com/v1/gfs',
    'ICON': 'https://api.open-meteo.com/v1/dwd-icon',
}
MET_NO_CACHE = {'expires': 0.0, 'value': None}
AVIATION_CACHE = {'expires': 0.0, 'value': None}
MODEL_CACHE = {'expires': 0.0, 'value': None}
SUPPLEMENT_CACHE_SECONDS = 600

WMO_THUNDER_CODES = frozenset({95, 96, 99})
WMO_HEAVY_RAIN_CODES = frozenset({65, 82})
QWEATHER_THUNDER_CODES = frozenset({302, 303, 304})
QWEATHER_HEAVY_RAIN_CODES = frozenset({307, 308, 310, 311, 312})

def _classify(code, thunder, heavy_rain):
    try:
        value = int(code) if code is not None else None
    except (TypeError, ValueError):
        return None
    if value in thunder:
        return 'THUNDERSTORM'
    if value in heavy_rain:
        return 'HEAVY_RAIN'
    return None

def wmo_condition_class(code):
    return _classify(code, WMO_THUNDER_CODES, WMO_HEAVY_RAIN_CODES)

def qweather_condition_class(code):
    return _classify(code, QWEATHER_THUNDER_CODES, QWEATHER_HEAVY_RAIN_CODES)

def _iso_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

def _normalise(payload, city):
    current = payload.get('current') or {}
    units = payload.get('current_units') or {}
    hourly = payload.get('hourly') or {}
    return {
        'cityId': city['id'], 'cityName': city['name'], 'requestedLocation': city['coordinate'],
        'gridLocation': [payload.get('longitude'), payload.get('latitude')],
        'validAt': current.get('time'), 'intervalSeconds': current.get('interval'),
        'temperatureC': current.get('temperature_2m'), 'humidityPercent': current.get('relative_humidity_2m'),
        'precipitationMm': current.get('precipitation'), 'weatherCode': current.get('weather_code'),
        'conditionClass': wmo_condition_class(current.get('weather_code')),
        'windSpeed10mMps': current.get('wind_speed_10m'), 'windDirection10mDeg': current.get('wind_direction_10m'),
        'windGusts10mMps': current.get('wind_gusts_10m'),
        'hourly': {key: hourly.get(key, []) for key in ('time', 'precipitation_probability', 'precipitation', 'wind_speed_100m', 'wind_direction_100m', 'visibility')},
        'units': units,
    }

def open_meteo_snapshot(city_rows, force=False):
    now = time.monotonic()
    if not force and _CACHE['value'] is not None and now < _CACHE['expires']:
        cached = dict(_CACHE['value'])
        cached['cache'] = 'HIT'
        return cached
    params = {
        'latitude': ','.join(f"{city['coordinate'][1]:.5f}" for city in city_rows),
        'longitude': ','.join(f"{city['coordinate'][0]:.5f}" for city in city_rows),
        'current': CURRENT_FIELDS, 'hourly': HOURLY_FIELDS, 'wind_speed_unit': 'ms',
        'timezone': 'Asia/Shanghai', 'forecast_days': 1,
    }
    retrieved = _iso_now()
    try:
        with httpx.Client(timeout=httpx.Timeout(12, connect=4), trust_env=False) as client:
            response = client.get('https://api.open-meteo.com/v1/forecast', params=params)
            response.raise_for_status()
            raw = response.json()
        items = raw if isinstance(raw, list) else [raw]
        if len(items) != len(city_rows):
            raise ValueError(f'Open-Meteo 返回地点数 {len(items)}，预期 {len(city_rows)}')
        observations = [_normalise(item, city) for item, city in zip(items, city_rows)]
        valid_times = [item['validAt'] for item in observations if item['validAt']]
        value = {
            'available': True, 'provider': 'OPEN_METEO', 'dataType': 'MODEL_ESTIMATE', 'retrievedAt': retrieved,
            'validAt': min(valid_times) if valid_times else None,
            'validUntil': (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat().replace('+00:00', 'Z'),
            'modelRunAt': None, 'resolution': '按供应商网格返回；不等同于街区测站或雷达分辨率',
            'coverage': {'requestedCities': len(city_rows), 'returnedCities': len(observations), 'routeCoverage': 'CITY_ENDPOINTS_ONLY'},
            'units': {'windSpeed': 'm/s', 'precipitation': 'mm', 'visibility': 'm'},
            'qualityFlags': ['MODEL_ESTIMATE_NOT_STATION_OBSERVATION', 'ROUTE_INTERIOR_NOT_FULLY_SAMPLED'],
            'observations': observations,
        }
        value['weatherSnapshotId'] = hashlib.sha256(
            (retrieved + ''.join(str(item['validAt']) for item in observations)).encode()
        ).hexdigest()[:24]
        _CACHE.update({'expires': now + 900, 'value': value})
        return {**value, 'cache': 'MISS'}
    except Exception as exc:
        return {
            'available': False, 'provider': 'OPEN_METEO', 'dataType': 'MODEL_ESTIMATE', 'retrievedAt': retrieved,
            'coverage': {'requestedCities': len(city_rows), 'returnedCities': 0, 'routeCoverage': 'UNAVAILABLE'},
            'qualityFlags': ['SOURCE_UNAVAILABLE'], 'errorCode': type(exc).__name__, 'observations': [], 'cache': 'MISS',
        }

def _num(node, scale=1.0):
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        return None
    return round(float(node) * scale, 4)

def _qweather_observation(payload, city):
    raw = payload.get('raw') if isinstance(payload.get('raw'), dict) else {}
    wind = raw.get('wind') if isinstance(raw.get('wind'), dict) else {}
    direction = wind.get('direction') if isinstance(wind.get('direction'), dict) else {}
    speed = wind.get('speed') if isinstance(wind.get('speed'), dict) else {}
    gust = raw.get('windGust') if isinstance(raw.get('windGust'), dict) else {}
    precip = raw.get('precipitation') if isinstance(raw.get('precipitation'), dict) else {}
    intensity = precip.get('intensity') if isinstance(precip.get('intensity'), dict) else {}
    visibility = raw.get('visibility') if isinstance(raw.get('visibility'), dict) else {}
    temperature = raw.get('temperature') if isinstance(raw.get('temperature'), dict) else {}
    pressure = raw.get('pressure') if isinstance(raw.get('pressure'), dict) else {}
    metadata = raw.get('metadata') if isinstance(raw.get('metadata'), dict) else {}
    condition = raw.get('condition') if isinstance(raw.get('condition'), dict) else {}
    visibility_m = _num(visibility.get('value'), 1000.0)
    return {
        'cityId': city['id'], 'cityName': city['name'],
        'requestedLocation': list(city['coordinate']), 'gridLocation': list(city['coordinate']),
        'validAt': metadata.get('obsTime'), 'intervalSeconds': None,
        'temperatureC': _num(temperature.get('value')),
        'humidityPercent': _num(raw.get('humidity'), 100.0),
        'precipitationMm': _num(intensity.get('value')),
        'weatherCode': condition.get('code'), 'conditionText': condition.get('text'),
        'conditionClass': qweather_condition_class(condition.get('code')),
        'windSpeed10mMps': _num(speed.get('value'), 1 / 3.6),
        'windDirection10mDeg': _num(direction.get('degree')),
        'windGusts10mMps': _num(gust.get('value'), 1 / 3.6),
        'visibilityM': visibility_m,
        'pressureHpa': _num(pressure.get('value')),
        'thunderProbability': None,
        'hourly': {'time': [], 'precipitation_probability': [], 'precipitation': [],
                   'wind_speed_100m': [], 'wind_direction_100m': [],
                   'visibility': [visibility_m] if visibility_m is not None else []},
        'hourlyAvailable': False,
        'thunderEstimateSuppressed': payload.get('thunderEstimate'),
        'units': {'windSpeed': 'm/s', 'precipitation': 'mm', 'visibility': 'm',
                  'providerUnits': payload.get('units')},
    }

def _attempt(city, fetch):
    try:
        return city, fetch(city), None
    except Exception as exc:
        return city, None, type(exc).__name__

def qweather_snapshot(city_rows, force=False, base_url=None):
    now = time.monotonic()
    if not force and _QW_CACHE['value'] is not None and now < _QW_CACHE['expires']:
        return {**_QW_CACHE['value'], 'cache': 'HIT'}
    retrieved = _iso_now()
    base = (base_url or JAVA_BASE).rstrip('/')
    rows = list(city_rows)[:QWEATHER_MAX_CITIES]
    headers = {'X-Internal-Token': INTERNAL_TOKEN} if INTERNAL_TOKEN else {}

    def fetch(city):
        params = {'lat': city['coordinate'][1], 'lon': city['coordinate'][0]}
        with httpx.Client(timeout=httpx.Timeout(10, connect=4), trust_env=False) as client:
            response = client.get(f'{base}/api/internal/qweather/current', params=params, headers=headers)
            response.raise_for_status()
            return response.json()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda city: _attempt(city, fetch), rows))
    observations = [_qweather_observation(payload, city) for city, payload, error in results if payload]
    failures = [{'cityId': city['id'], 'errorCode': error} for city, _, error in results if error]
    valid_times = [item['validAt'] for item in observations if item['validAt']]
    value = {
        'available': bool(observations), 'provider': 'QWEATHER',
        'dataType': 'PROVIDER_CURRENT_ESTIMATE_OR_OBSERVATION_UNVERIFIED',
        'retrievedAt': retrieved,
        'validAt': min(valid_times) if valid_times else None,
        'validUntil': (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat().replace('+00:00', 'Z'),
        'modelRunAt': None,
        'resolution': '和风不公开逐点观测/模型网格分辨率；不按街区级精度使用。',
        'coverage': {'requestedCities': len(rows), 'returnedCities': len(observations),
                     'failedCities': failures, 'routeCoverage': 'CITY_ENDPOINTS_ONLY',
                     'citiesOutsideCap': max(0, len(list(city_rows)) - len(rows))},
        'units': {'windSpeed': 'm/s', 'precipitation': 'mm', 'visibility': 'm'},
        'qualityFlags': ['THUNDER_ESTIMATE_NOT_INJECTED_INTO_RISK_ENGINE',
                         'ROUTE_INTERIOR_NOT_FULLY_SAMPLED',
                         'PROVIDER_BRAND_NOT_VERIFIED_AS_STATION_OBSERVATION'],
        'observations': observations,
    }
    value['weatherSnapshotId'] = hashlib.sha256(
        (retrieved + ''.join(str(item['validAt']) for item in observations)).encode()
    ).hexdigest()[:24]
    if not observations:
        value['errorCode'] = failures[0]['errorCode'] if failures else 'NO_CITIES'
        value['qualityFlags'] = ['SOURCE_UNAVAILABLE', *value['qualityFlags']]
        _QW_CACHE.update({'expires': now + 60, 'value': value})
        return {**value, 'cache': 'MISS'}
    _QW_CACHE.update({'expires': now + 900, 'value': value})
    return {**value, 'cache': 'MISS'}

MET_NO_THUNDER_MARK = 'thunder'
MET_NO_HEAVY_RAIN_MARKS = ('heavyrain', 'heavysleet', 'heavyrainandthunder')

def met_no_condition_class(symbol):
    if not isinstance(symbol, str):
        return None
    text = symbol.lower()
    if MET_NO_THUNDER_MARK in text:
        return 'THUNDERSTORM'
    if any(mark in text for mark in MET_NO_HEAVY_RAIN_MARKS):
        return 'HEAVY_RAIN'
    return None

def _met_no_observation(payload, city):
    props = payload.get('properties') if isinstance(payload.get('properties'), dict) else {}
    series = props.get('timeseries') if isinstance(props.get('timeseries'), list) else []
    first = series[0] if series else {}
    data = first.get('data') if isinstance(first.get('data'), dict) else {}
    detail = data.get('instant', {}).get('details', {}) if isinstance(data.get('instant'), dict) else {}
    nxt = data.get('next_1_hours') if isinstance(data.get('next_1_hours'), dict) else {}
    nxt_detail = nxt.get('details') if isinstance(nxt.get('details'), dict) else {}
    symbol = (nxt.get('summary') or {}).get('symbol_code') if isinstance(nxt.get('summary'), dict) else None
    return {
        'cityId': city['id'], 'cityName': city['name'],
        'requestedLocation': list(city['coordinate']), 'gridLocation': list(city['coordinate']),
        'validAt': first.get('time'), 'intervalSeconds': 3600,
        'temperatureC': _num(detail.get('air_temperature')),
        'humidityPercent': _num(detail.get('relative_humidity')),
        'precipitationMm': _num(nxt_detail.get('precipitation_amount')),
        'weatherCode': symbol, 'conditionText': symbol,
        'conditionClass': met_no_condition_class(symbol),
        'windSpeed10mMps': _num(detail.get('wind_speed')),
        'windDirection10mDeg': _num(detail.get('wind_from_direction')),
        'windGusts10mMps': None,
        'visibilityM': None,
        'pressureHpa': _num(detail.get('air_pressure_at_sea_level')),
        'thunderProbability': None,
        'hourly': {'time': [], 'precipitation_probability': [], 'precipitation': [],
                   'wind_speed_100m': [], 'wind_direction_100m': [], 'visibility': []},
        'hourlyAvailable': False,
        'units': {'windSpeed': 'm/s', 'precipitation': 'mm', 'visibility': 'm'},
    }

def met_no_snapshot(city_rows, force=False):
    now = time.monotonic()
    if not force and MET_NO_CACHE['value'] is not None and now < MET_NO_CACHE['expires']:
        return {**MET_NO_CACHE['value'], 'cache': 'HIT'}
    retrieved = _iso_now()
    rows = list(city_rows)[:MET_NO_MAX_CITIES]

    def fetch(city):
        params = {'lat': f"{city['coordinate'][1]:.4f}", 'lon': f"{city['coordinate'][0]:.4f}"}
        with httpx.Client(timeout=httpx.Timeout(12, connect=4), trust_env=False) as client:
            response = client.get(MET_NO_URL, params=params, headers={'User-Agent': USER_AGENT})
            response.raise_for_status()
            return response.json()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda city: _attempt(city, fetch), rows))
    observations = [_met_no_observation(payload, city) for city, payload, error in results if payload]
    failures = [{'cityId': city['id'], 'errorCode': error} for city, _, error in results if error]
    valid_times = [item['validAt'] for item in observations if item['validAt']]
    value = {
        'available': bool(observations), 'provider': 'MET_NORWAY',
        'dataType': 'MODEL_ESTIMATE', 'retrievedAt': retrieved,
        'validAt': min(valid_times) if valid_times else None,
        'validUntil': (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat().replace('+00:00', 'Z'),
        'modelRunAt': None,
        'resolution': 'MET Norway 全球数值预报；逐点返回，不等同于街区测站或雷达分辨率。',
        'coverage': {'requestedCities': len(rows), 'returnedCities': len(observations),
                     'failedCities': failures, 'routeCoverage': 'CITY_ENDPOINTS_ONLY',
                     'citiesOutsideCap': max(0, len(list(city_rows)) - len(rows))},
        'units': {'windSpeed': 'm/s', 'precipitation': 'mm', 'visibility': 'm'},
        'qualityFlags': ['MODEL_ESTIMATE_NOT_STATION_OBSERVATION',
                         'ROUTE_INTERIOR_NOT_FULLY_SAMPLED',
                         'VISIBILITY_NOT_PROVIDED_BY_THIS_SOURCE'],
        'observations': observations,
    }
    value['weatherSnapshotId'] = hashlib.sha256(
        (retrieved + ''.join(str(item['validAt']) for item in observations)).encode()
    ).hexdigest()[:24]
    if not observations:
        value['errorCode'] = failures[0]['errorCode'] if failures else 'NO_CITIES'
        value['qualityFlags'] = ['SOURCE_UNAVAILABLE', *value['qualityFlags']]
        MET_NO_CACHE.update({'expires': now + 60, 'value': value})
        return {**value, 'cache': 'MISS'}
    MET_NO_CACHE.update({'expires': now + 900, 'value': value})
    return {**value, 'cache': 'MISS'}

def _haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_phi = p2 - p1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))

def _metar_visibility_m(raw):
    if raw is None:
        return None, False
    if isinstance(raw, str):
        return None, True
    return _num(raw, SM_TO_M), False

def _metar_observation(row, city, distance_km):
    visibility_m, is_bound = _metar_visibility_m(row.get('visib'))
    obs_time = row.get('obsTime')
    valid_at = None
    if isinstance(obs_time, (int, float)):
        valid_at = datetime.fromtimestamp(obs_time, timezone.utc).isoformat().replace('+00:00', 'Z')
    return {
        'cityId': city['id'], 'cityName': city['name'],
        'requestedLocation': list(city['coordinate']),
        'gridLocation': [row.get('lon'), row.get('lat')],
        'stationId': row.get('icaoId'), 'stationName': row.get('name'),
        'stationDistanceKm': round(distance_km, 1),
        'validAt': valid_at, 'intervalSeconds': None,
        'temperatureC': _num(row.get('temp')),
        'dewpointC': _num(row.get('dewp')),
        'humidityPercent': None,
        'precipitationMm': None,
        'weatherCode': row.get('wxString'), 'conditionText': row.get('wxString'),
        'conditionClass': _metar_condition_class(row.get('wxString')),
        'windSpeed10mMps': _num(row.get('wspd'), KT_TO_MPS),
        'windDirection10mDeg': _num(row.get('wdir')),
        'windGusts10mMps': _num(row.get('wgst'), KT_TO_MPS),
        'visibilityM': visibility_m,
        'visibilityIsLowerBound': is_bound,
        'pressureHpa': _num(row.get('altim')),
        'flightCategory': row.get('fltCat'),
        'clouds': row.get('clouds') if isinstance(row.get('clouds'), list) else [],
        'rawText': row.get('rawOb'),
        'thunderProbability': None,
        'hourly': {'time': [], 'precipitation_probability': [], 'precipitation': [],
                   'wind_speed_100m': [], 'wind_direction_100m': [], 'visibility': []},
        'hourlyAvailable': False,
        'units': {'windSpeed': 'm/s', 'precipitation': 'mm', 'visibility': 'm',
                  'sourceUnits': {'windSpeed': 'kt', 'visibility': 'statute_mile'}},
    }

def _metar_condition_class(wx):
    if not isinstance(wx, str):
        return None
    text = wx.upper()
    if 'TS' in text:
        return 'THUNDERSTORM'
    if '+RA' in text or '+SHRA' in text:
        return 'HEAVY_RAIN'
    return None

def aviation_observations(city_rows, force=False, bbox=None, radius_km=None):
    now = time.monotonic()
    if not force and AVIATION_CACHE['value'] is not None and now < AVIATION_CACHE['expires']:
        return {**AVIATION_CACHE['value'], 'cache': 'HIT'}
    retrieved = _iso_now()
    box = bbox or AVIATION_BBOX
    limit = float(radius_km if radius_km is not None else AVIATION_RADIUS_KM)
    try:
        with httpx.Client(timeout=httpx.Timeout(15, connect=5), trust_env=False) as client:
            response = client.get(AVIATION_URL,
                                  params={'bbox': box, 'format': 'json', 'hours': 2},
                                  headers={'User-Agent': USER_AGENT})
            response.raise_for_status()
            raw = response.json()
        rows = raw if isinstance(raw, list) else []
        latest = {}
        for row in rows:
            station = row.get('icaoId')
            if not station:
                continue
            prev = latest.get(station)
            if prev is None or (row.get('obsTime') or 0) > (prev.get('obsTime') or 0):
                latest[station] = row
        observations, unmatched = [], []
        for city in city_rows:
            lon, lat = city['coordinate'][0], city['coordinate'][1]
            best, best_km = None, None
            for row in latest.values():
                if not isinstance(row.get('lat'), (int, float)) or not isinstance(row.get('lon'), (int, float)):
                    continue
                distance = _haversine_km(lat, lon, row['lat'], row['lon'])
                if distance <= limit and (best_km is None or distance < best_km):
                    best, best_km = row, distance
            if best is None:
                unmatched.append(city['id'])
            else:
                observations.append(_metar_observation(best, city, best_km))
        value = {
            'available': bool(observations),
            'provider': 'AVIATION_WEATHER_CENTER',
            'dataType': 'STATION_OBSERVATION_METAR',
            'retrievedAt': retrieved,
            'validAt': None,
            'coverage': {
                'requestedCities': len(list(city_rows)),
                'returnedCities': len(observations),
                'stationsSeen': len(latest),
                'citiesWithoutNearbyStation': unmatched,
                'radiusKm': limit, 'bbox': box,
                'routeCoverage': 'AIRPORT_POINT_OBSERVATIONS_ONLY',
            },
            'units': {'windSpeed': 'm/s', 'precipitation': 'mm', 'visibility': 'm'},
            'qualityFlags': ['STATION_OBSERVATION_NOT_AREA_FIELD',
                             'AIRPORT_POINT_MAY_DIFFER_FROM_CITY_CENTRE',
                             'VISIBILITY_IS_LOWER_BOUND_WHEN_REPORTED_AS_6PLUS',
                             'NOT_A_RADAR_ECHO_DO_NOT_CONVERT_TO_DBZ'],
            'observations': observations,
        }
        valid_times = [item['validAt'] for item in observations if item['validAt']]
        value['validAt'] = min(valid_times) if valid_times else None
        AVIATION_CACHE.update({'expires': now + SUPPLEMENT_CACHE_SECONDS, 'value': value})
        return {**value, 'cache': 'MISS'}
    except Exception as exc:
        value = {
            'available': False, 'provider': 'AVIATION_WEATHER_CENTER',
            'dataType': 'STATION_OBSERVATION_METAR', 'retrievedAt': retrieved,
            'coverage': {'requestedCities': len(list(city_rows)), 'returnedCities': 0,
                         'routeCoverage': 'UNAVAILABLE'},
            'qualityFlags': ['SOURCE_UNAVAILABLE'], 'errorCode': type(exc).__name__,
            'observations': [], 'cache': 'MISS',
        }
        AVIATION_CACHE.update({'expires': now + 60, 'value': value})
        return value

def multi_model_spread(city_rows, force=False):
    now = time.monotonic()
    if not force and MODEL_CACHE['value'] is not None and now < MODEL_CACHE['expires']:
        return {**MODEL_CACHE['value'], 'cache': 'HIT'}
    retrieved = _iso_now()
    rows = list(city_rows)[:MET_NO_MAX_CITIES]
    params = {
        'latitude': ','.join(f"{city['coordinate'][1]:.5f}" for city in rows),
        'longitude': ','.join(f"{city['coordinate'][0]:.5f}" for city in rows),
        'current': 'temperature_2m,wind_speed_10m', 'wind_speed_unit': 'ms',
        'timezone': 'Asia/Shanghai', 'forecast_days': 1,
    }

    def fetch(url):
        with httpx.Client(timeout=httpx.Timeout(12, connect=4), trust_env=False) as client:
            response = client.get(url, params=params, headers={'User-Agent': USER_AGENT})
            response.raise_for_status()
            return response.json()

    models, failures = {}, []
    for name, url in MULTI_MODEL_ENDPOINTS.items():
        try:
            models[name] = fetch(url)
        except Exception as exc:
            failures.append({'model': name, 'errorCode': type(exc).__name__})
    if not models:
        value = {
            'available': False, 'provider': 'OPEN_METEO_MULTI_MODEL', 'retrievedAt': retrieved,
            'models': list(MULTI_MODEL_ENDPOINTS), 'failures': failures,
            'qualityFlags': ['SOURCE_UNAVAILABLE'], 'rows': [], 'cache': 'MISS',
        }
        MODEL_CACHE.update({'expires': now + 60, 'value': value})
        return value

    def pick(payload):
        item = payload[0] if isinstance(payload, list) else payload
        current = (item or {}).get('current') or {}
        return _num(current.get('temperature_2m')), _num(current.get('wind_speed_10m'))

    rows_out = []
    for index, city in enumerate(rows):
        cells = {}
        for name, payload in models.items():
            items = payload if isinstance(payload, list) else [payload]
            if index >= len(items):
                continue
            cell = items[index].get('current') or {}
            cells[name] = {'temperatureC': _num(cell.get('temperature_2m')),
                           'windSpeed10mMps': _num(cell.get('wind_speed_10m'))}
        temps = [c['temperatureC'] for c in cells.values() if c['temperatureC'] is not None]
        winds = [c['windSpeed10mMps'] for c in cells.values() if c['windSpeed10mMps'] is not None]
        rows_out.append({
            'cityId': city['id'], 'cityName': city['name'], 'models': cells,
            'temperatureSpreadC': round(max(temps) - min(temps), 3) if len(temps) >= 2 else None,
            'windSpreadMps': round(max(winds) - min(winds), 3) if len(winds) >= 2 else None,
        })
    value = {
        'available': True, 'provider': 'OPEN_METEO_MULTI_MODEL', 'retrievedAt': retrieved,
        'models': sorted(models), 'failures': failures,
        'qualityFlags': ['MODEL_DISAGREEMENT_IS_UNCERTAINTY_NOT_ERROR',
                         'NOT_A_SECOND_OBSERVATION'],
        'rows': rows_out,
    }
    MODEL_CACHE.update({'expires': now + SUPPLEMENT_CACHE_SECONDS, 'value': value})
    return {**value, 'cache': 'MISS'}

_PRIMARY_SOURCES = {
    'qweather': ('QWEATHER', qweather_snapshot),
    'met-no': ('MET_NORWAY', met_no_snapshot),
}

def weather_snapshot(city_rows, force=False):
    chosen = _PRIMARY_SOURCES.get(PROVIDER)
    if chosen is None:
        return open_meteo_snapshot(city_rows, force=force)
    label, fetch = chosen
    value = fetch(city_rows, force=force)
    if value.get('available'):
        return value
    fallback = open_meteo_snapshot(city_rows, force=force)
    if not fallback.get('available'):
        return fallback
    flags = list(dict.fromkeys(list(fallback.get('qualityFlags', [])) + [
        'PROVIDER_FALLBACK_OPEN_METEO', f"{label}_UNAVAILABLE_{value.get('errorCode') or 'UNKNOWN'}"]))
    return {**fallback, 'qualityFlags': flags, 'preferredProvider': label}

def provider_status():
    return {
        'configuredProvider': PROVIDER if PROVIDER in ('open-meteo', 'qweather', 'met-no') else 'open-meteo',
        'requestedProvider': PROVIDER,
        'javaBase': JAVA_BASE,
        'internalTokenConfigured': bool(INTERNAL_TOKEN),
        'qweatherCityCap': QWEATHER_MAX_CITIES,
        'primarySources': [
            {'key': 'open-meteo', 'label': 'Open-Meteo', 'kind': 'MODEL_ESTIMATE',
             'requiresKey': False, 'role': 'default',
             'note': '批量接口，一次请求覆盖全部城市；模型估算，不是测站观测。'},
            {'key': 'met-no', 'label': 'MET Norway', 'kind': 'MODEL_ESTIMATE',
             'requiresKey': False, 'role': 'alternative',
             'note': '全球数值预报；逐点请求（并发），要求可识别的 User-Agent。'},
            {'key': 'qweather', 'label': '和风天气', 'kind': 'PROVIDER_CURRENT_ESTIMATE_OR_OBSERVATION_UNVERIFIED',
             'requiresKey': True, 'role': 'alternative',
             'note': '凭据由 Java 侧持有；Python 只读内部原始接口。'},
        ],
        'supplementChannels': [
            {'key': 'aviation', 'label': 'Aviation Weather Center METAR',
             'kind': 'STATION_OBSERVATION_METAR', 'requiresKey': False,
             'endpoint': '/traffic/weather/observations',
             'note': '真实机场观测报文；按外接矩形取站并就近匹配，覆盖不全时如实报低。'
                     '它不是雷达回波，不换算 dBZ。'},
            {'key': 'multi-model', 'label': 'Open-Meteo GFS / ICON',
             'kind': 'MODEL_ESTIMATE', 'requiresKey': False,
             'endpoint': '/traffic/weather/models',
             'note': '同一供应商下两个独立模型的差值，用来看不确定性；不是第二份真相。'},
        ],
        'note': '和风凭据由 Java 侧持有；Python 只读取内部原始接口，任一来源缺失时降级并标注。',
    }
