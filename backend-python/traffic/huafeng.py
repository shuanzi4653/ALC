import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .secret_store import HUAFENG_API_KEY, SecretError, SecretStore, redact

API_BASE = os.environ.get('ALC_HUAFENG_API_BASE', 'https://openapi.weathercn.com').strip()
LANGUAGE = 'zh-cn'
TRUST_ENV = os.environ.get('ALC_HUAFENG_TRUST_ENV', '0').strip() == '1'
DAILY_LIMIT = int(os.environ.get('ALC_HUAFENG_DAILY_LIMIT', '500'))
QPS = float(os.environ.get('ALC_HUAFENG_QPS', '5'))
TIMEOUT = httpx.Timeout(12, connect=5)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUOTA_PATH = PROJECT_ROOT / '.run' / 'huafeng_quota.json'

ROUTE_CITY_SEARCH = '/locations/v1/cities/translate'
ROUTE_GEO_SEARCH = '/locations/v1/cities/geoposition/search.json'
ROUTE_CURRENT = '/currentconditions/v1/{location_key}.json'
ROUTE_ALERTS = '/alerts/v1/{location_key}.json'
ROUTE_HOURLY = '/forecasts/v1/hourly/12hour/{location_key}.json'
ROUTE_DAILY = '/forecasts/v1/daily/1day/{location_key}.json'
ROUTE_NOWCAST = '/nowcast_cn/v3/basic'

ROUTES = {
    'citySearch': ROUTE_CITY_SEARCH,
    'geoSearch': ROUTE_GEO_SEARCH,
    'current': ROUTE_CURRENT,
    'alerts': ROUTE_ALERTS,
    'hourly': ROUTE_HOURLY,
    'daily': ROUTE_DAILY,
    'nowcast': ROUTE_NOWCAST,
}
ABSENT_PRODUCTS = {
    'RADAR_IMAGERY': '雷达/卫星图像仅存在于 api.weathercn.com 旧版，需 apikey+secret；标准 Key 不可用',
    'INDICES': '生活指数在本主机无路由（/indices/v1/daily/1day/{key}.json 返回 404）',
    'AIR_QUALITY': '空气质量在本主机无路由（/airquality/v1/... 返回 404）',
}
CREDENTIAL_HINT = (
    f'请先执行 python -m traffic.secret_store set {HUAFENG_API_KEY} 写入标准 Key。'
)

class HuafengUnavailable(RuntimeError):
    pass

class QuotaExceeded(HuafengUnavailable):
    pass

def safe_url(url, *extra_secrets):
    return redact(url, *extra_secrets)

def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

def api_key(store=None):
    store = store or SecretStore()
    try:
        value = store.get(HUAFENG_API_KEY)
    except SecretError as exc:
        raise HuafengUnavailable(f'华风爱科凭据不可用：{exc} {CREDENTIAL_HINT}') from None
    if not value:
        raise HuafengUnavailable(f'华风爱科凭据为空。{CREDENTIAL_HINT}')
    return value

class QuotaGuard:

    def __init__(self, path=None, daily_limit=None, qps=None):
        self.path = Path(path) if path else QUOTA_PATH
        self.daily_limit = DAILY_LIMIT if daily_limit is None else int(daily_limit)
        self.qps = QPS if qps is None else float(qps)
        self._lock = threading.Lock()
        self._last_call = 0.0

    def _today(self):
        return datetime.now(timezone.utc).strftime('%Y-%m-%d')

    def _load(self):
        try:
            payload = json.loads(self.path.read_text(encoding='utf-8'))
        except Exception:
            payload = {}
        if not isinstance(payload, dict) or payload.get('date') != self._today():
            return {'date': self._today(), 'count': 0}
        return {'date': payload['date'], 'count': int(payload.get('count') or 0)}

    def _save(self, state):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(state), encoding='utf-8')
        except OSError:
            pass

    def snapshot(self):
        state = self._load()
        return {'date': state['date'], 'used': state['count'],
                'limit': self.daily_limit, 'remaining': max(0, self.daily_limit - state['count'])}

    def consume(self, count=1):
        with self._lock:
            state = self._load()
            if state['count'] + count > self.daily_limit:
                raise QuotaExceeded(
                    f'华风爱科当日调用额度已用尽：{state["count"]}/{self.daily_limit}。'
                    '请等待次日重置，或申请更高配额。')
            if self.qps > 0:
                gap = 1.0 / self.qps
                wait = gap - (time.monotonic() - self._last_call)
                if wait > 0:
                    time.sleep(wait)
            self._last_call = time.monotonic()
            state['count'] += count
            self._save(state)
            return state['count']

_LOCK = threading.Lock()
_GUARD = None

def guard():
    global _GUARD
    with _LOCK:
        if _GUARD is None:
            _GUARD = QuotaGuard()
        return _GUARD

def _get(path, params, key, client=None):
    owned = client is None
    client = client or httpx.Client(timeout=TIMEOUT, trust_env=TRUST_ENV)
    try:
        response = client.get(f'{API_BASE}{path}', params={**params, 'apikey': key})
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise HuafengUnavailable(f'华风爱科返回 HTTP {exc.response.status_code}') from None
    except httpx.HTTPError as exc:
        raise HuafengUnavailable(f'华风爱科网络失败：{type(exc).__name__}') from None
    except ValueError:
        raise HuafengUnavailable('华风爱科返回内容不是合法 JSON') from None
    finally:
        if owned:
            client.close()

def _call(path, params, store=None, client=None, guard_=None):
    key = api_key(store)
    (guard_ or guard()).consume(1)
    return _get(path, params, key, client=client)

def _first(payload):
    if isinstance(payload, list):
        return payload[0] if payload else None
    return payload if isinstance(payload, dict) else None

def location_by_text(query, store=None, client=None, guard_=None):
    """Resolve a city name to a Location Key."""
    payload = _call(ROUTE_CITY_SEARCH, {'q': query, 'language': LANGUAGE, 'details': 'false'},
                    store=store, client=client, guard_=guard_)
    record = _first(payload)
    if not record or not record.get('Key'):
        raise HuafengUnavailable(f'未找到地点：{query}')
    return {'locationKey': str(record['Key']), 'name': record.get('LocalizedName'),
            'englishName': record.get('EnglishName'), 'type': record.get('Type'),
            'latitude': (record.get('GeoPosition') or {}).get('Latitude'),
            'longitude': (record.get('GeoPosition') or {}).get('Longitude'),
            'timeZone': (record.get('TimeZone') or {}).get('Name'),
            'dataSets': record.get('DataSets') or []}

def location_by_point(latitude, longitude, store=None, client=None, guard_=None):
    query = f'{round(float(latitude), 3)},{round(float(longitude), 3)}'
    payload = _call(ROUTE_GEO_SEARCH, {'q': query, 'language': LANGUAGE},
                    store=store, client=client, guard_=guard_)
    record = _first(payload)
    if not record or not record.get('Key'):
        raise HuafengUnavailable(f'未能解析坐标：{query}')
    return {'locationKey': str(record['Key']), 'name': record.get('LocalizedName'),
            'englishName': record.get('EnglishName'), 'type': record.get('Type'),
            'latitude': (record.get('GeoPosition') or {}).get('Latitude'),
            'longitude': (record.get('GeoPosition') or {}).get('Longitude'),
            'timeZone': (record.get('TimeZone') or {}).get('Name'),
            'dataSets': record.get('DataSets') or [],
            'parentCity': record.get('ParentCity')}

def _metric(node, scale=1.0):
    if not isinstance(node, dict):
        return None
    metric = node.get('Metric')
    if not isinstance(metric, dict):
        return None
    value = metric.get('Value')
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value) * scale, 4)

def normalise_current(payload, city=None, location_key=None):
    record = _first(payload) or {}
    city = city or {}
    return {
        'cityId': city.get('id'), 'cityName': city.get('name') or location_key,
        'locationKey': str(location_key) if location_key else None,
        'requestedLocation': city.get('coordinate'),
        'validAt': record.get('LocalObservationDateTime'),
        'epochTime': record.get('EpochTime'),
        'temperatureC': _metric(record.get('Temperature')),
        'realFeelC': _metric(record.get('RealFeelTemperature')),
        'humidityPercent': record.get('RelativeHumidity'),
        'dewPointC': _metric(record.get('DewPoint')),
        'precipitationMm': _metric(record.get('Precip1hr')),
        'precipitationSummaryMm': {
            key: _metric((record.get('PrecipitationSummary') or {}).get(key))
            for key in ('PastHour', 'Past3Hours', 'Past6Hours', 'Past12Hours', 'Past24Hours')
        },
        'weatherCode': record.get('WeatherIcon'), 'conditionText': record.get('WeatherText'),
        'hasPrecipitation': record.get('HasPrecipitation'),
        'precipitationType': record.get('PrecipitationType'),
        'isDayTime': record.get('IsDayTime'),
        'windSpeed10mMps': _metric((record.get('Wind') or {}).get('Speed'), 1 / 3.6),
        'windDirection10mDeg': ((record.get('Wind') or {}).get('Direction') or {}).get('Degrees'),
        'windGusts10mMps': _metric((record.get('WindGust') or {}).get('Speed'), 1 / 3.6),
        'visibilityM': _metric(record.get('Visibility'), 1000.0),
        'obstructionsToVisibility': record.get('ObstructionsToVisibility'),
        'ceilingM': _metric(record.get('Ceiling')),
        'cloudCoverPercent': record.get('CloudCover'),
        'pressureHpa': _metric(record.get('Pressure')),
        'uvIndex': record.get('UVIndex'),
        'units': {'windSpeed': 'm/s', 'precipitation': 'mm', 'visibility': 'm',
                  'providerUnits': {'windSpeed': 'km/h', 'visibility': 'km', 'pressure': 'mb'}},
    }

def _localised(value):
    if isinstance(value, dict):
        for key in ('Localized', 'LocalizedText', 'Text', 'Name', 'English', 'EnglishText'):
            if value.get(key):
                return value[key]
        return None
    return value

def _as_list(value):
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]

def normalise_alert(record):
    if not isinstance(record, dict):
        return None
    folded = {str(name).lower(): value for name, value in record.items()}

    areas = []
    for item in _as_list(folded.get('area')):
        if not isinstance(item, dict):
            continue
        entry = {str(name).lower(): value for name, value in item.items()}
        areas.append({
            'name': entry.get('name'),
            'startAt': entry.get('starttime'),
            'endAt': entry.get('endtime'),
            'startEpoch': entry.get('epochstarttime'),
            'endEpoch': entry.get('epochendtime'),
            'text': entry.get('text'),
            'summary': entry.get('summary'),
            'action': _localised(entry.get('lastaction')),
            'language': entry.get('languagecode'),
        })

    starts = [area['startEpoch'] for area in areas if area.get('startEpoch') is not None]
    ends = [area['endEpoch'] for area in areas if area.get('endEpoch') is not None]
    color = folded.get('color') if isinstance(folded.get('color'), dict) else {}

    description = folded.get('description') if isinstance(folded.get('description'), dict) else {}
    headline = _localised(description) or _localised(folded.get('headline'))
    if not headline and areas:
        headline = areas[0].get('summary')
    english = description.get('English') or description.get('EnglishText')
    return {
        'alertId': str(folded.get('alertid') or folded.get('id') or '') or None,
        'type': folded.get('type'), 'typeId': folded.get('typeid'),
        'category': folded.get('category'),
        'level': folded.get('level'), 'alarmLevel': folded.get('alarmlevel'),
        'urgencyClass': folded.get('class'), 'priority': folded.get('priority'),
        'headline': headline, 'englishHeadline': english,
        'source': _localised(folded.get('source')), 'sourceId': folded.get('sourceid'),
        'countryCode': folded.get('countrycode'),
        'color': {'name': color.get('Name'), 'hex': color.get('Hex')},
        'areas': areas, 'areaNames': [area['name'] for area in areas if area.get('name')],
        'effectiveEpoch': min(starts) if starts else None,
        'expiresEpoch': max(ends) if ends else None,
        'haveReadyStatements': folded.get('havereadystatements'),
        'disclaimer': folded.get('disclaimer'),
        'link': folded.get('link'), 'mobileLink': folded.get('mobilelink'),
        'authority': 'OFFICIAL_GOVERNMENT_ALERT',
    }

NOWCAST_INTERVAL_MINUTES = 6

def normalise_nowcast(payload):
    if not isinstance(payload, dict):
        raise HuafengUnavailable('分钟降水返回结构无法识别')
    status = payload.get('Status')
    if status is not None and str(status) != '0':
        raise HuafengUnavailable(f'分钟降水返回错误状态 {status}：{payload.get("Msg") or "未知"}')
    data = payload.get('Data') if isinstance(payload.get('Data'), dict) else {}
    intensity = [value for value in (data.get('Intensity') or []) if isinstance(value, (int, float))]
    hours = data.get('HourlyForecastsNext2H') or []
    current = data.get('CurrentConditions') if isinstance(data.get('CurrentConditions'), dict) else {}
    return {
        'latitude': payload.get('Lat'), 'longitude': payload.get('Lon'),
        'validAt': data.get('Datetime'), 'epochTime': data.get('Epochtime'),
        'hasPrecipitation': data.get('IfPre'), 'isLocalPrecipitation': data.get('IsLocalPre'),
        'precipitationTypeCode': data.get('PreTypeCode'), 'precipitationType': data.get('PreType'),
        'nearestPrecipitationDirection': data.get('NearestPreDirection'),
        'nearestPrecipitation': data.get('NearestPre'),
        'intensityCodes': intensity,
        'intervalMinutes': data.get('Interval') or NOWCAST_INTERVAL_MINUTES,
        'description': data.get('Description'), 'shortPhrase': data.get('ShortPhrase'),
        'currentCondition': current.get('WeatherText'), 'currentWeatherCode': current.get('WeatherCode'),
        'hourly': [{'validAt': item.get('Datetime'), 'epochTime': item.get('Epochtime'),
                    'condition': item.get('WeatherText'), 'weatherCode': item.get('WeatherCode'),
                    'precipitationProbability': item.get('PrecipitationProbability')}
                   for item in hours if isinstance(item, dict)],
        'units': {'intensity': 'PROVIDER_CODE_UNVERIFIED', 'interval': 'minutes'},
    }

def observe_city(city, location_key=None, store=None, client=None, guard_=None):
    guard_ = guard_ or guard()
    provenance = {
        'provider': 'HUAFENG_ACCUWEATHER', 'retrievedAt': _now(),
        'transport': 'HTTPS_QUERY_APIKEY', 'language': LANGUAGE,
        'tier': 'STANDARD_TRIAL', 'dailyLimit': guard_.daily_limit,
        'endpoints': ['currentconditions/v1', 'alerts/v1'],
        'qualityFlags': ['OFFICIAL_ALERT_IS_AUTHORITATIVE',
                         'CITY_ENDPOINT_NOT_ROUTE_INTERIOR',
                         'STANDARD_TRIAL_QUOTA_500_PER_DAY'],
    }
    try:
        if not location_key:
            resolved = location_by_point(city['coordinate'][1], city['coordinate'][0],
                                        store=store, client=client, guard_=guard_)
            location_key = resolved['locationKey']
            provenance['resolvedFrom'] = 'GEOPOSITION'
        current = _call(ROUTE_CURRENT.format(location_key=location_key),
                        {'language': LANGUAGE, 'details': 'true'},
                        store=store, client=client, guard_=guard_)
        alerts_raw = _call(ROUTE_ALERTS.format(location_key=location_key),
                           {'language': LANGUAGE, 'details': 'true'},
                           store=store, client=client, guard_=guard_)
    except HuafengUnavailable as exc:
        return {'observation': None, 'alerts': [], 'provenance': provenance, 'error': str(exc)}

    alerts = [item for item in (normalise_alert(record) for record in (alerts_raw or [])) if item]
    provenance['locationKey'] = str(location_key)
    provenance['alertCount'] = len(alerts)
    return {'observation': normalise_current(current, city, location_key),
            'alerts': alerts, 'provenance': provenance, 'error': None}

CALLS_PER_CITY = 3

def nowcast(latitude, longitude, store=None, client=None, guard_=None):
    query = f'{round(float(latitude), 3)},{round(float(longitude), 3)}'
    payload = _call(ROUTE_NOWCAST, {'q': query}, store=store, client=client, guard_=guard_)
    result = normalise_nowcast(payload)
    result['provenance'] = {
        'provider': 'HUAFENG_ACCUWEATHER', 'retrievedAt': _now(),
        'transport': 'HTTPS_QUERY_APIKEY', 'route': ROUTE_NOWCAST, 'tier': 'STANDARD_TRIAL',
        'qualityFlags': ['POINT_FORECAST_NOT_AREA_FIELD', 'INTENSITY_UNIT_UNVERIFIED'],
    }
    return result

def observe_cities(city_rows, store=None, client=None, limit=None, guard_=None):
    guard_ = guard_ or guard()
    rows = list(city_rows)[:int(limit)] if limit else list(city_rows)
    observations, alerts, failures = [], [], []
    truncated = False
    for city in rows:
        if guard_.snapshot()['remaining'] < CALLS_PER_CITY:
            truncated = True
            failures.append({'cityId': city.get('id'), 'errorCode': 'QUOTA_EXCEEDED'})
            break
        result = observe_city(city, store=store, client=client, guard_=guard_)
        if result['observation']:
            observations.append(result['observation'])
        alerts.extend(result['alerts'])
        if result['error']:
            failures.append({'cityId': city.get('id'), 'errorCode': result['error'][:60]})
    return {'available': bool(observations), 'observations': observations, 'alerts': alerts,
            'coverage': {'requestedCities': len(rows), 'returnedCities': len(observations),
                         'failedCities': failures, 'truncatedByQuota': truncated},
            'quota': guard_.snapshot(),
            'error': '当日调用额度不足以覆盖全部城市，已提前停止。' if truncated else None,
            'provenance': _batch_provenance(len(observations), guard_)}

def _batch_provenance(returned, guard_):
    return {
        'provider': 'HUAFENG_ACCUWEATHER', 'retrievedAt': _now(),
        'dataType': 'PROVIDER_OBSERVATION_OR_ESTIMATE',
        'transport': 'HTTPS_QUERY_APIKEY', 'tier': 'STANDARD_TRIAL',
        'returnedCities': returned, 'quota': guard_.snapshot(),
        'qualityFlags': ['CITY_ENDPOINT_NOT_ROUTE_INTERIOR',
                         'STANDARD_TRIAL_QUOTA_500_PER_DAY',
                         'RADAR_NOT_AVAILABLE_ON_THIS_KEY'],
    }

def status(store=None):
    store = store or SecretStore()
    report = {
        'provider': 'HUAFENG_ACCUWEATHER', 'apiBase': API_BASE,
        'routes': dict(ROUTES), 'absentProducts': dict(ABSENT_PRODUCTS),
        'tier': 'STANDARD_TRIAL', 'dailyLimit': DAILY_LIMIT, 'qps': QPS,
    }
    if getattr(store, 'key_warning', None):
        report['keyWarning'] = store.key_warning
    try:
        entries = [row for row in store.names() if row['name'] == HUAFENG_API_KEY]
        report['keyConfigured'] = bool(entries)
        report['credentials'] = [{'name': row['name'], 'fingerprint': row['fingerprint'],
                                  'updatedAt': row['updated_at']} for row in entries]
    except Exception:
        report['keyConfigured'] = False
    report['ready'] = report['keyConfigured']
    report['quota'] = guard().snapshot()
    if not report['ready']:
        report['hint'] = CREDENTIAL_HINT
    return report
