"""免费补充气象源的契约：单位、编码空间、覆盖如实、降级显式。

为什么这一组判据必须存在
------------------------
2026-10-17 新增三个源（MET Norway / Aviation Weather Center METAR / Open-Meteo 多模型），
它们各自带来一类**会静默出错**的东西：

  ① **单位不同**：METAR 的风是节、能见度是法定英里；和风是 km/h 与 km；MET Norway
     本来就是 m/s。换算写错不会报错，只会让"12 m/s"变成"12 节"。
  ② **编码空间不相交**：MET Norway 用符号串、METAR 用自由文本、Open-Meteo 用 WMO 数字码。
     把三者的并集交给下游，就是把一种天气读成另一种，且没有任何一处报错。
  ③ **`6+` 是下限不是等值**：写成 9656 m 会让下游把"至少 6 英里"读成"正好 9656 米"。
  ④ **覆盖必须如实报低**：33 个地级行政区里只有一部分附近有机场。拿最近的那个站
     冒充整座城市，是"把未验证写成已通过"。

判据里的单位换算值全部用**实测报文自证**（ZYTL 2026-10-17 12:30Z：
rawOb `13009G17MPS ... 6000` ↔ JSON `wspd=17 / wgst=33 / visib=3.73`），
不是凭常数表背下来的。
"""
import traffic.weather_sources as weather_sources

CITY_SY = {'id': 'SY', 'name': '沈阳', 'coordinate': [123.43, 41.80]}
CITY_DL = {'id': 'DL', 'name': '大连', 'coordinate': [121.62, 38.92]}
CITY_MOHE = {'id': 'MOHE', 'name': '漠河', 'coordinate': [122.53, 52.97]}

MET_NO_PAYLOAD = {
    'type': 'Feature',
    'geometry': {'type': 'Point', 'coordinates': [123.43, 41.80, 45]},
    'properties': {
        'meta': {'updated_at': '2026-10-17T12:00:00Z', 'units': {'air_temperature': 'celsius'}},
        'timeseries': [{
            'time': '2026-10-17T12:00:00Z',
            'data': {
                'instant': {'details': {
                    'air_temperature': 18.8, 'relative_humidity': 62.3,
                    'wind_speed': 6.3, 'wind_from_direction': 213.5,
                    'air_pressure_at_sea_level': 1014.2,
                }},
                'next_1_hours': {'summary': {'symbol_code': 'heavyrainandthunder'},
                                 'details': {'precipitation_amount': 4.2}},
            },
        }],
    },
}

METAR_ROWS = [
    # 大连：一条旧的、一条新的 —— 同一站必须只留最新那条。
    {'icaoId': 'ZYTL', 'obsTime': 1792238400, 'lat': 38.961, 'lon': 121.556,
     'temp': 20, 'dewp': 20, 'wdir': 130, 'wspd': 19, 'wgst': 37,
     'visib': 1.86, 'altim': 1012, 'wxString': 'SHRA', 'fltCat': 'IFR',
     'rawOb': 'METAR ZYTL 171120Z 13010G19MPS 3000 SHRA ...'},
    {'icaoId': 'ZYTL', 'obsTime': 1792240200, 'lat': 38.961, 'lon': 121.556,
     'temp': 19, 'dewp': 19, 'wdir': 130, 'wspd': 17, 'wgst': 33,
     'visib': 3.73, 'altim': 1012, 'wxString': '-SHRA', 'fltCat': 'MVFR',
     'rawOb': 'METAR ZYTL 171230Z 13009G17MPS 6000 -SHRA FEW009 BKN020 19/19 Q1012 RESHRA NOSIG'},
    {'icaoId': 'ZYTX', 'obsTime': 1792240200, 'lat': 41.639, 'lon': 123.485,
     'temp': 21, 'dewp': 12, 'wdir': 200, 'wspd': 12, 'wgst': None,
     'visib': '6+', 'altim': 1013, 'wxString': None, 'fltCat': 'VFR',
     'rawOb': 'METAR ZYTX 171230Z 20006MPS 9999 ...'},
    # 韩国襄阳：在 bbox 内但离两座城市都远 —— 必须被半径筛掉，不能冒充本地观测。
    {'icaoId': 'RKNY', 'obsTime': 1792240200, 'lat': 38.061, 'lon': 128.669,
     'temp': 16, 'dewp': 10, 'wdir': 300, 'wspd': 4, 'wgst': None,
     'visib': 4.35, 'altim': 1011, 'wxString': None, 'fltCat': 'VFR',
     'rawOb': 'METAR RKNY 171230Z 30002MPS 7000 ...'},
]

GFS_PAYLOAD = {'current': {'time': '2026-10-17T12:45', 'temperature_2m': 19.9, 'wind_speed_10m': 5.1}}
ICON_PAYLOAD = {'current': {'time': '2026-10-17T12:45', 'temperature_2m': 16.8, 'wind_speed_10m': 7.4}}


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _client(payload, calls, fail=False, by_url=None):
    class Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None, headers=None):
            calls.append({'url': url, 'params': params, 'headers': headers})
            if fail:
                raise RuntimeError('offline')
            if by_url is not None and url in by_url:
                return _Response(by_url[url])
            return _Response(payload)

    return Client


# ---- ① 编码空间：三套映射各管各的，不许互通 --------------------------------

def test_met_no_symbol_codes_map_into_the_shared_vocabulary():
    assert weather_sources.met_no_condition_class('heavyrainandthunder') == 'THUNDERSTORM'
    assert weather_sources.met_no_condition_class('rainandthunder') == 'THUNDERSTORM'
    assert weather_sources.met_no_condition_class('heavyrain') == 'HEAVY_RAIN'
    # 轻度降水不生成风险几何 —— 与 weather.py 的 `_extreme_kind` 同一条纪律。
    assert weather_sources.met_no_condition_class('lightrain') is None
    assert weather_sources.met_no_condition_class('clearsky') is None
    assert weather_sources.met_no_condition_class(None) is None


def test_metar_weather_strings_map_into_the_same_vocabulary():
    assert weather_sources._metar_condition_class('TSRA') == 'THUNDERSTORM'
    assert weather_sources._metar_condition_class('+TSRA') == 'THUNDERSTORM'
    assert weather_sources._metar_condition_class('+RA') == 'HEAVY_RAIN'
    assert weather_sources._metar_condition_class('+SHRA') == 'HEAVY_RAIN'
    # `-SHRA` 是轻度阵雨：大连这套报文是常态天气，不该生成任何风险几何。
    assert weather_sources._metar_condition_class('-SHRA') is None
    assert weather_sources._metar_condition_class('BR') is None
    assert weather_sources._metar_condition_class(None) is None


# ---- ② 单位：用实测报文自证 ------------------------------------------------

def test_metar_wind_is_knots_and_visibility_is_statute_miles():
    # 自证：rawOb `13009G17MPS` ⇒ 9 / 17 m/s ⇒ 17.5 / 33.0 kt ⇒ JSON 17 / 33。
    obs = weather_sources._metar_observation(METAR_ROWS[1], CITY_DL, 0.4)
    assert obs['units']['sourceUnits']['windSpeed'] == 'kt'
    assert round(obs['windSpeed10mMps'], 2) == round(17 * weather_sources.KT_TO_MPS, 2)
    assert round(obs['windGusts10mMps'], 2) == round(33 * weather_sources.KT_TO_MPS, 2)
    # 9 m/s ≈ 17.5 kt，反算回 m/s 必须落在报文写的那两个数上（舍入余量 0.6）。
    assert abs(obs['windSpeed10mMps'] - 9) < 0.6
    assert abs(obs['windGusts10mMps'] - 17) < 0.6
    # 自证：rawOb 报 6000 米；JSON visib=3.73 法定英里 ⇒ 6003 m。
    assert obs['visibilityM'] == round(3.73 * weather_sources.SM_TO_M, 4)
    assert abs(obs['visibilityM'] - 6000) < 10


def test_six_plus_visibility_stays_a_lower_bound_not_a_number():
    # `6+` = **大于** 6 英里。报成 9656 m 会让下游把"至少"读成"正好"。
    assert weather_sources._metar_visibility_m('6+') == (None, True)
    assert weather_sources._metar_visibility_m(None) == (None, False)
    value, is_bound = weather_sources._metar_visibility_m(3.73)
    assert is_bound is False and abs(value - 6003) < 1


def test_met_no_already_speaks_metres_per_second_and_has_no_visibility():
    obs = weather_sources._met_no_observation(MET_NO_PAYLOAD, CITY_SY)
    assert obs['windSpeed10mMps'] == 6.3          # 不乘任何系数
    assert obs['temperatureC'] == 18.8
    assert obs['conditionClass'] == 'THUNDERSTORM'
    assert obs['precipitationMm'] == 4.2
    # compact 产品不给能见度 —— 留 None 并让 qualityFlags 说出来，不许填一个像样的数。
    assert obs['visibilityM'] is None
    # 没有独立雷暴概率来源，就不声称。与和风那条同一个处置。
    assert obs['thunderProbability'] is None


# ---- ③ 覆盖：距离筛选与"每站只留最新" -------------------------------------

def test_haversine_matches_a_known_distance():
    # 沈阳桃仙(41.639,123.485) ↔ 大连周水子(38.961,121.556) 实测约 330 km。
    distance = weather_sources._haversine_km(41.639, 123.485, 38.961, 121.556)
    assert 320 < distance < 345


def test_metar_keeps_only_the_latest_report_per_station_and_respects_the_radius(monkeypatch):
    calls = []
    monkeypatch.setattr(weather_sources.httpx, 'Client', _client(METAR_ROWS, calls))
    monkeypatch.setattr(weather_sources, 'AVIATION_CACHE', {'expires': 0.0, 'value': None})
    result = weather_sources.aviation_observations([CITY_SY, CITY_DL], force=True, radius_km=150)
    assert result['available'] is True
    by_city = {row['cityId']: row for row in result['observations']}
    # 沈阳匹配到 ZYTX（同城），大连匹配到 ZYTL；韩国的 RKNY 被半径筛掉。
    assert by_city['SY']['stationId'] == 'ZYTX'
    assert by_city['DL']['stationId'] == 'ZYTL'
    # 大连那条必须是 obsTime 更大的那一条，不是一小时前 visib=1.86 那版。
    assert by_city['DL']['rawText'].endswith('NOSIG')
    assert by_city['DL']['stationDistanceKm'] < 150
    assert 'RKNY' not in {row['stationId'] for row in result['observations']}
    # 覆盖口径必须自称"只有机场点"，且带上"不是雷达回波"的旗标。
    assert result['coverage']['routeCoverage'] == 'AIRPORT_POINT_OBSERVATIONS_ONLY'
    assert 'STATION_OBSERVATION_NOT_AREA_FIELD' in result['qualityFlags']
    assert 'NOT_A_RADAR_ECHO_DO_NOT_CONVERT_TO_DBZ' in result['qualityFlags']


def test_cities_without_a_nearby_station_are_reported_not_filled(monkeypatch):
    calls = []
    monkeypatch.setattr(weather_sources.httpx, 'Client', _client([METAR_ROWS[2]], calls))
    monkeypatch.setattr(weather_sources, 'AVIATION_CACHE', {'expires': 0.0, 'value': None})
    result = weather_sources.aviation_observations([CITY_SY, CITY_MOHE], force=True, radius_km=150)
    assert result['coverage']['citiesWithoutNearbyStation'] == ['MOHE']
    assert len(result['observations']) == 1
    # 「没有邻近站」必须是**缺席**，不能拿最近的站补一个 —— 补出来的值看起来和真的一样。
    assert {row['cityId'] for row in result['observations']} == {'SY'}


# ---- ④ 多模型：差值只在两个模型都有值时才存在 -----------------------------

def test_single_model_yields_no_spread_instead_of_zero(monkeypatch):
    # 报 0 会被读成"两个模型完全一致"，而事实是"只有一个模型回答了"。
    calls = []
    by_url = {
        weather_sources.MULTI_MODEL_ENDPOINTS['GFS']: GFS_PAYLOAD,
        weather_sources.MULTI_MODEL_ENDPOINTS['ICON']: {},   # ICON 没有值
    }
    monkeypatch.setattr(weather_sources.httpx, 'Client', _client({}, calls, by_url=by_url))
    monkeypatch.setattr(weather_sources, 'MODEL_CACHE', {'expires': 0.0, 'value': None})
    result = weather_sources.multi_model_spread([CITY_SY], force=True)
    assert result['available'] is True
    assert result['rows'][0]['temperatureSpreadC'] is None
    assert result['rows'][0]['windSpreadMps'] is None


def test_two_models_produce_a_spread_and_say_it_is_uncertainty(monkeypatch):
    calls = []
    by_url = {
        weather_sources.MULTI_MODEL_ENDPOINTS['GFS']: GFS_PAYLOAD,
        weather_sources.MULTI_MODEL_ENDPOINTS['ICON']: ICON_PAYLOAD,
    }
    monkeypatch.setattr(weather_sources.httpx, 'Client', _client({}, calls, by_url=by_url))
    monkeypatch.setattr(weather_sources, 'MODEL_CACHE', {'expires': 0.0, 'value': None})
    result = weather_sources.multi_model_spread([CITY_SY], force=True)
    row = result['rows'][0]
    assert row['temperatureSpreadC'] == 3.1
    assert row['windSpreadMps'] == 2.3
    assert 'MODEL_DISAGREEMENT_IS_UNCERTAINTY_NOT_ERROR' in result['qualityFlags']
    assert 'NOT_A_SECOND_OBSERVATION' in result['qualityFlags']


# ---- ⑤ 单一入口与降级链 ----------------------------------------------------

def test_met_no_can_be_selected_as_the_primary_source(monkeypatch):
    calls = []
    monkeypatch.setattr(weather_sources.httpx, 'Client', _client(MET_NO_PAYLOAD, calls))
    monkeypatch.setattr(weather_sources, 'MET_NO_CACHE', {'expires': 0.0, 'value': None})
    result = weather_sources.met_no_snapshot([CITY_SY], force=True)
    assert result['available'] is True
    assert result['provider'] == 'MET_NORWAY'
    assert result['dataType'] == 'MODEL_ESTIMATE'
    # User-Agent 不是可选项：MET Norway 的服务条款要求可识别标识，缺了会 403。
    assert calls and calls[0]['headers']['User-Agent']


def test_failure_falls_back_to_open_meteo_with_both_facts_stated(monkeypatch):
    # 接缝提醒：`weather_snapshot()` 是**查表**取主源（`_PRIMARY_SOURCES`），而这张表在
    # **模块导入时**就把函数对象绑进去了。所以 `monkeypatch.setattr(weather_sources,
    # 'met_no_snapshot', …)` 只换掉模块属性、换不掉表里那个引用 —— 那样写会真的发起
    # 网络请求，然后拿回一个 `ConnectTimeout`，本该红的断言反而"通过了前缀"。必须 setitem。
    # （降级那一路的 `open_meteo_snapshot` 相反：函数体里按全局名解析，setattr 有效。）
    monkeypatch.setitem(weather_sources._PRIMARY_SOURCES, 'met-no',
                        ('MET_NORWAY', lambda rows, force=False: {
                            'available': False, 'errorCode': 'ConnectError'}))
    monkeypatch.setattr(weather_sources, 'PROVIDER', 'met-no')
    monkeypatch.setattr(weather_sources, 'open_meteo_snapshot',
                        lambda rows, force=False: {'available': True, 'provider': 'OPEN_METEO',
                                                   'qualityFlags': ['MODEL_ESTIMATE_NOT_STATION_OBSERVATION']})
    result = weather_sources.weather_snapshot([CITY_SY], force=True)
    assert result['provider'] == 'OPEN_METEO'
    # 两件事都要说：一是降级了，二是**哪个源**挂了。只说"降级"等于让下一个人猜。
    assert 'PROVIDER_FALLBACK_OPEN_METEO' in result['qualityFlags']
    assert 'MET_NORWAY_UNAVAILABLE_ConnectError' in result['qualityFlags']
    assert result['preferredProvider'] == 'MET_NORWAY'


def test_provider_status_lists_both_primary_sources_and_the_two_supplement_channels():
    status = weather_sources.provider_status()
    primary = {row['key'] for row in status['primarySources']}
    assert {'open-meteo', 'met-no', 'qweather'} <= primary
    supplements = {row['key']: row for row in status['supplementChannels']}
    assert set(supplements) == {'aviation', 'multi-model'}
    # 补充通道必须自带端点，否则"有这个能力"与"够得着这个能力"是两句话。
    assert supplements['aviation']['endpoint'] == '/traffic/weather/observations'
    assert supplements['multi-model']['endpoint'] == '/traffic/weather/models'
    # METAR 不是雷达 —— 这个词必须出现在能力说明里，不能只写在代码注释里。
    assert '不换算 dBZ' in supplements['aviation']['note']
