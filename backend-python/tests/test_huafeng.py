"""华风爱科 adapter: unit conversion, quota governance and the radar boundary.

Two things here are easy to get quietly wrong and are therefore asserted
directly. First, the adapter converts provider units (km/h wind, km visibility)
into the shared risk contract (m/s, metres); a missed factor of 3.6 would make
every wind-derived risk zone wrong without changing any shape. Second, the
adapter must never touch a radar route: a location response advertises
``FutureRadar`` in its DataSets, which reads like an invitation to build one, but
the route does not exist for this key.
"""
import json

import pytest

from traffic import huafeng
from traffic.secret_store import HUAFENG_API_KEY, SecretStore

FAKE_KEY = 'hf-fake-standard-key-0001'

CURRENT_PAYLOAD = [{
    'LocalObservationDateTime': '2026-09-16T10:50:09+08:00',
    'EpochTime': 1773111009, 'WeatherIcon': 7, 'WeatherText': '多云',
    'HasPrecipitation': False, 'PrecipitationType': None, 'IsDayTime': True,
    'Temperature': {'Metric': {'Value': 6.0, 'Unit': 'C'}},
    'RealFeelTemperature': {'Metric': {'Value': 3.3, 'Unit': 'C'}},
    'RelativeHumidity': 39,
    'Wind': {'Direction': {'Degrees': 180, 'Localized': '南'},
             'Speed': {'Metric': {'Value': 10.8, 'Unit': 'km/h'}}},
    'WindGust': {'Speed': {'Metric': {'Value': 18.0, 'Unit': 'km/h'}}},
    'Visibility': {'Metric': {'Value': 11.4, 'Unit': 'km'}},
    'Ceiling': {'Metric': {'Value': 8961.0, 'Unit': 'm'}},
    'Pressure': {'Metric': {'Value': 1017.0, 'Unit': 'mb'}},
    'CloudCover': 10, 'UVIndex': 3,
    'Precip1hr': {'Metric': {'Value': 0.0, 'Unit': 'mm'}},
    'PrecipitationSummary': {'Past3Hours': {'Metric': {'Value': 1.5, 'Unit': 'mm'}}},
}]

LOCATION_PAYLOAD = [{
    'Key': '102133', 'Type': 'City', 'LocalizedName': '大连', 'EnglishName': 'Dalian',
    'GeoPosition': {'Latitude': 38.914, 'Longitude': 121.615},
    'TimeZone': {'Name': 'Asia/Shanghai'},
    'DataSets': ['AirQuality', 'Alerts', 'FutureRadar', 'MinuteCast'],
}]

CITY = {'id': '2-01', 'name': '大连', 'coordinate': [121.615, 38.914]}

#: Captured live from GET /alerts/v1/102136.json on 2026-09-16 (沈阳 had an active
#: 大风蓝色预警 at the time). Trimmed only in whitespace, never in field names.
REAL_ALERT = {
    'CountryCode': 'CN', 'AlertID': 102826566,
    'Description': {'Localized': '大风蓝色预警', 'English': 'Blue Warning for Gale'},
    'Category': 'WIND', 'Priority': 307, 'Type': '大风', 'TypeID': 'CN246', 'Class': None,
    'Level': '蓝色', 'AlarmLevel': 'Blue',
    'Color': {'Name': 'Blue', 'Red': 0, 'Green': 0, 'Blue': 255, 'Hex': '#0000FF'},
    'Source': '国家预警信息发布中心', 'SourceId': 62, 'Disclaimer': None,
    'Area': [{
        'Name': '沈阳市', 'StartTime': '2026-09-16T15:13:00+08:00',
        'EpochStartTime': 1789542780, 'EndTime': '2026-09-17T19:09:00+08:00',
        'EpochEndTime': 1789643340,
        'LastAction': {'Localized': '新', 'English': 'New'},
        'Text': ('大风蓝色预警信号：预计17日8时到20时，沈阳市和平区、沈河区、铁西区、'
                 '皇姑区、大东区、于洪区，沈抚示范区偏南风4到5级，阵风7级。请注意出行安全，'
                 '加固临时搭建物，防范高空坠物等风险。沈阳市气象台2026年09月16日15时13分发布'),
        'LanguageCode': 'zh-cn',
        'Summary': '大风蓝色预警 生效，持续时间至 星期四，7:09下午 CST。来源：国家预警信息发布中心',
    }],
    'HaveReadyStatements': True,
    'MobileLink': 'http://m.weathercn.com/zh/cn/shenyang/102136/weather-warnings/102136?lang=zh-cn',
    'Link': 'http://m.weathercn.com/zh/cn/shenyang/102136/weather-warnings/102136?lang=zh-cn',
}

#: Captured live from GET /nowcast_cn/v3/basic?q=38.914,121.615 on 2026-09-16.
REAL_NOWCAST = {
    'Status': '0', 'Msg': 'ok', 'Lat': 38.91, 'Lon': 121.61,
    'Data': {
        'IfPre': False, 'IsLocalPre': False, 'PreTypeCode': 0, 'PreType': '',
        'NearestPreDirection': '', 'NearestPre': 999,
        'Intensity': [0] * 20, 'Interval': 6, 'Description': '未来2小时无降水',
        'ShortPhrase': '', 'Datetime': '2026-09-16T22:04:00+08:00', 'Epochtime': 1789567440,
        'MobileLink': 'https://m.weathercn.com/weatherMap.do?mapType=precip&lang=zh-cn',
        'CurrentConditions': {'WeatherText': '晴', 'WeatherCode': '00'},
        'HourlyForecastsNext2H': [
            {'Datetime': '2026-09-16T23:00:00+08:00', 'Epochtime': 1789570800,
             'WeatherText': '晴', 'WeatherCode': '00', 'PrecipitationProbability': 0},
            {'Datetime': '2026-09-17T00:00:00+08:00', 'Epochtime': 1789574400,
             'WeatherText': '晴', 'WeatherCode': '00', 'PrecipitationProbability': 0},
        ],
    },
}


@pytest.fixture()
def store(tmp_path):
    return SecretStore(path=tmp_path / 'secrets.db', key=b'h' * 32)


@pytest.fixture()
def guard(tmp_path):
    return huafeng.QuotaGuard(path=tmp_path / 'quota.json', daily_limit=100, qps=0)


class _StubResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError('boom', request=None, response=self)

    def json(self):
        return self._payload


class _StubClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        for needle, payload in self.responses.items():
            if needle in url:
                return _StubResponse(payload)
        return _StubResponse({'message': 'no Route matched with those values'}, status=404)

    def close(self):
        return None


def test_provider_units_are_converted_into_the_shared_risk_contract():
    """km/h -> m/s and km -> m; a missed factor silently corrupts every risk zone."""
    item = huafeng.normalise_current(CURRENT_PAYLOAD, CITY, '102133')
    assert item['windSpeed10mMps'] == pytest.approx(10.8 / 3.6, abs=1e-4)
    assert item['windGusts10mMps'] == pytest.approx(5.0, abs=1e-4)
    assert item['visibilityM'] == pytest.approx(11400.0)
    assert item['ceilingM'] == pytest.approx(8961.0)
    assert item['windDirection10mDeg'] == 180
    assert item['temperatureC'] == 6.0
    assert item['cityId'] == '2-01' and item['locationKey'] == '102133'
    assert item['precipitationSummaryMm']['Past3Hours'] == 1.5


def test_a_missing_field_is_reported_as_missing_rather_than_guessed():
    payload = [{'WeatherText': '晴'}]
    item = huafeng.normalise_current(payload, CITY, '1')
    for field in ('windSpeed10mMps', 'visibilityM', 'temperatureC', 'precipitationMm'):
        assert item[field] is None, f'{field} 缺失时必须为 None，不能编造'
    assert item['conditionText'] == '晴'


def test_official_alerts_are_normalised_and_attributed():
    """Driven by a real alert captured live from 沈阳 on 2026-09-16.

    Two details in this payload are traps that a plausible-looking guess gets
    wrong: the localised headline lives under ``Description.Localized`` (not
    ``LocalizedText``), and ``Area`` is a list of objects rather than an object
    holding an ``Areas`` array.
    """
    alert = huafeng.normalise_alert(REAL_ALERT)
    assert alert['headline'] == '大风蓝色预警'
    assert alert['englishHeadline'] == 'Blue Warning for Gale'
    assert alert['type'] == '大风' and alert['typeId'] == 'CN246'
    assert alert['category'] == 'WIND'
    assert alert['level'] == '蓝色' and alert['alarmLevel'] == 'Blue'
    assert alert['color'] == {'name': 'Blue', 'hex': '#0000FF'}
    assert alert['source'] == '国家预警信息发布中心'
    assert alert['alertId'] == '102826566'
    assert alert['areaNames'] == ['沈阳市']
    area = alert['areas'][0]
    assert area['startAt'] == '2026-09-16T15:13:00+08:00'
    assert area['action'] == '新'
    assert '阵风7级' in area['text']
    # The validity window is derived from the areas, because the provider
    # publishes none at the top level.
    assert alert['effectiveEpoch'] == 1789542780 and alert['expiresEpoch'] == 1789643340
    # An official alert must stay distinguishable from the system's own risk zones.
    assert alert['authority'] == 'OFFICIAL_GOVERNMENT_ALERT'


def test_alert_normaliser_tolerates_a_single_area_object_and_missing_fields():
    """``Area`` is observed as a list; a single object must not silently yield none."""
    single = huafeng.normalise_alert({
        'alertid': 'A1', 'AlertID': 'A1', 'Type': '大风', 'AlarmLevel': 'Yellow',
        'Description': {'Localized': '大风黄色预警'}, 'Source': '国家预警信息发布中心',
        'Area': {'Name': '大连市'},
    })
    assert single['headline'] == '大风黄色预警' and single['areaNames'] == ['大连市']
    assert single['effectiveEpoch'] is None and single['expiresEpoch'] is None, \
        '无时间字段时不得编造有效期'
    assert single['color'] == {'name': None, 'hex': None}
    assert huafeng.normalise_alert(None) is None


def test_radar_routes_are_absent_and_must_stay_absent():
    """A location response advertises FutureRadar, but the route does not exist.

    This is a guard against a contributor reading DataSets and adding a guessed
    radar path: radar imagery belongs to 华风爱科's older apikey+secret platform.
    """
    joined = ' '.join(huafeng.ROUTES.values()).lower()
    for forbidden in ('radar', 'imagery', 'radsat', 'mosaic', 'minutecast', 'satellite'):
        assert forbidden not in joined, f'不应出现未经证实的路由：{forbidden}'
    assert 'RADAR_IMAGERY' in huafeng.ABSENT_PRODUCTS
    assert 'secret' in huafeng.ABSENT_PRODUCTS['RADAR_IMAGERY']
    # Every route in the table was probed; the minutely route is genuinely present.
    assert huafeng.ROUTES['nowcast'] == '/nowcast_cn/v3/basic'


def test_minutely_precipitation_is_normalised_without_claiming_a_unit():
    """Real 大连 payload: dry, so the intensity unit could not be established."""
    result = huafeng.normalise_nowcast(REAL_NOWCAST)
    assert result['hasPrecipitation'] is False
    assert result['description'] == '未来2小时无降水'
    assert result['intervalMinutes'] == 6
    assert len(result['intensityCodes']) == 20, '20 个样本 × 6 分钟 = 2 小时'
    assert result['currentCondition'] == '晴'
    assert len(result['hourly']) == 2
    assert result['hourly'][0]['precipitationProbability'] == 0
    # The unit is unverified, so it must never be presented as a rainfall rate.
    assert result['units']['intensity'] == 'PROVIDER_CODE_UNVERIFIED'
    assert not any('mm' in str(key).lower() for key in result)

    with pytest.raises(huafeng.HuafengUnavailable):
        huafeng.normalise_nowcast({'Status': '5', 'Msg': '参数错误'})
    with pytest.raises(huafeng.HuafengUnavailable):
        huafeng.normalise_nowcast(['not', 'a', 'dict'])



def test_missing_key_fails_closed_without_calling_the_network(store, guard):
    client = _StubClient({'currentconditions': CURRENT_PAYLOAD})
    result = huafeng.observe_city(CITY, location_key='102133', store=store, client=client, guard_=guard)
    assert result['observation'] is None and result['error']
    assert '凭据' in result['error']
    assert client.calls == [], '无凭据时不应发起请求'
    assert guard.snapshot()['used'] == 0, '未发出的调用不应计入额度'


def test_observation_and_alerts_are_returned_with_provenance(store, guard):
    store.put(HUAFENG_API_KEY, FAKE_KEY)
    client = _StubClient({'currentconditions': CURRENT_PAYLOAD, 'alerts': [REAL_ALERT]})
    result = huafeng.observe_city(CITY, location_key='102133', store=store, client=client, guard_=guard)

    assert result['error'] is None
    assert result['observation']['cityId'] == '2-01'
    assert len(result['alerts']) == 1
    assert result['alerts'][0]['source'] == '国家预警信息发布中心'
    assert result['provenance']['provider'] == 'HUAFENG_ACCUWEATHER'
    assert result['provenance']['alertCount'] == 1
    assert 'OFFICIAL_ALERT_IS_AUTHORITATIVE' in result['provenance']['qualityFlags']
    # The key travels as a query parameter and must be presented as configured.
    assert client.calls[0][1]['apikey'] == FAKE_KEY
    assert guard.snapshot()['used'] == 2


def test_minutely_precipitation_costs_one_call_and_is_point_scoped(store, guard):
    store.put(HUAFENG_API_KEY, FAKE_KEY)
    client = _StubClient({'nowcast_cn': REAL_NOWCAST})
    result = huafeng.nowcast(38.914, 121.615, store=store, client=client, guard_=guard)
    assert result['hasPrecipitation'] is False
    assert client.calls[0][1]['q'] == '38.914,121.615'
    assert result['provenance']['route'] == '/nowcast_cn/v3/basic'
    assert 'POINT_FORECAST_NOT_AREA_FIELD' in result['provenance']['qualityFlags']
    assert guard.snapshot()['used'] == 1


def test_the_credential_never_appears_in_a_result(store, guard):
    import httpx

    store.put(HUAFENG_API_KEY, FAKE_KEY)

    class _Failing:
        def get(self, url, params=None):
            raise httpx.ConnectError(f'boom apikey={FAKE_KEY} url={url}')

        def close(self):
            return None

    result = huafeng.observe_city(CITY, location_key='1', store=store, client=_Failing(), guard_=guard)
    assert result['observation'] is None and result['error']
    assert FAKE_KEY not in json.dumps(result, ensure_ascii=False)


def test_coordinates_resolve_to_a_location_key(store, guard):
    store.put(HUAFENG_API_KEY, FAKE_KEY)
    client = _StubClient({'geoposition': LOCATION_PAYLOAD})
    resolved = huafeng.location_by_point(38.914, 121.615, store=store, client=client)
    assert resolved['locationKey'] == '102133'
    assert resolved['name'] == '大连'
    assert client.calls[0][1]['q'] == '38.914,121.615'


def test_quota_is_persisted_and_refuses_rather_than_returning_empty(store, guard, tmp_path):
    """A trial key that silently stops answering is worse than one that refuses."""
    store.put(HUAFENG_API_KEY, FAKE_KEY)
    small = huafeng.QuotaGuard(path=tmp_path / 'quota.json', daily_limit=3, qps=0)
    small.consume(3)
    with pytest.raises(huafeng.QuotaExceeded):
        small.consume(1)
    # The budget survives a new object, so a restart cannot reset the day.
    reopened = huafeng.QuotaGuard(path=tmp_path / 'quota.json', daily_limit=3, qps=0)
    assert reopened.snapshot()['used'] == 3 and reopened.snapshot()['remaining'] == 0

    client = _StubClient({'currentconditions': CURRENT_PAYLOAD})
    result = huafeng.observe_city(CITY, location_key='1', store=store, client=client,
                                  guard_=huafeng.QuotaGuard(path=tmp_path / 'quota.json',
                                                            daily_limit=3, qps=0))
    assert result['observation'] is None
    assert client.calls == []


def test_a_truncated_batch_is_reported_as_truncated(store, tmp_path):
    store.put(HUAFENG_API_KEY, FAKE_KEY)
    exhausted = huafeng.QuotaGuard(path=tmp_path / 'q.json', daily_limit=0, qps=0)
    batch = huafeng.observe_cities([CITY], store=store,
                                   client=_StubClient({'currentconditions': CURRENT_PAYLOAD}),
                                   guard_=exhausted)
    assert batch['coverage']['truncatedByQuota'] is True
    assert batch['available'] is False
    assert batch['coverage']['failedCities'][0]['errorCode'] == 'QUOTA_EXCEEDED'


def test_status_reports_capability_and_quota_without_revealing_the_key(store, tmp_path):
    report = huafeng.status(store=store)
    assert report['ready'] is False and 'hint' in report
    assert 'RADAR_IMAGERY' in report['absentProducts']
    store.put(HUAFENG_API_KEY, FAKE_KEY)
    report = huafeng.status(store=store)
    assert report['ready'] is True
    assert report['tier'] == 'STANDARD_TRIAL' and report['dailyLimit'] == 500
    assert FAKE_KEY not in json.dumps(report, ensure_ascii=False)
