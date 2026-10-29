"""QWeather adapter contract: unit normalisation, provenance and explicit fallback."""
import traffic.weather_sources as weather_sources
from traffic.catalog import cities
from traffic.weather import PublicWeather

PAYLOAD = {
    'available': True, 'provider': 'QWEATHER', 'product': 'weather/v1/current',
    'units': {'temperature': '°C', 'windSpeed': 'km/h', 'precipitation': 'mm',
              'visibility': 'km', 'pressure': 'hPa', 'humidity': 'fraction', 'cloudCover': 'fraction'},
    'thunderEstimate': 0.35, 'thunderEstimateMethod': 'CONDITION_CODE_AND_CLOUD_COVER_HEURISTIC',
    'raw': {
        'metadata': {'obsTime': '2026-09-14T18:15+08:00'},
        'condition': {'text': '雷阵雨', 'code': '302'},
        'temperature': {'value': 18.5}, 'humidity': 0.72, 'cloudCover': 0.9,
        'wind': {'direction': {'degree': 359}, 'speed': {'value': 36.0}},
        'windGust': {'value': 64.8}, 'precipitation': {'intensity': {'value': 0.4}},
        'visibility': {'value': 0.8}, 'pressure': {'value': 1008},
    },
}


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _client(payload, calls, fail=False):
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
            return _Response(payload)

    return Client


def test_qweather_observation_normalises_units_and_keeps_centre_separate(monkeypatch):
    calls = []
    monkeypatch.setattr(weather_sources.httpx, 'Client', _client(PAYLOAD, calls))
    monkeypatch.setattr(weather_sources, '_QW_CACHE', {'expires': 0.0, 'value': None})
    city = cities()[0]
    snapshot = weather_sources.qweather_snapshot([city], force=True)
    assert snapshot['available'] is True
    assert snapshot['provider'] == 'QWEATHER'
    assert snapshot['coverage']['returnedCities'] == 1
    observation = snapshot['observations'][0]
    # km/h -> m/s and km -> m keep both providers on one contract.
    assert observation['windSpeed10mMps'] == 10.0
    assert observation['windGusts10mMps'] == 18.0
    assert observation['visibilityM'] == 800.0
    assert observation['humidityPercent'] == 72.0
    assert observation['windDirection10mDeg'] == 359
    # The city centre is never replaced by a provider grid position.
    assert observation['requestedLocation'] == list(city['coordinate'])
    assert observation['gridLocation'] == list(city['coordinate'])
    # A derived thunder estimate must not be promoted to an observation.
    assert observation['thunderProbability'] is None
    assert observation['thunderEstimateSuppressed'] == 0.35
    assert 'THUNDER_ESTIMATE_NOT_INJECTED_INTO_RISK_ENGINE' in snapshot['qualityFlags']
    assert calls[0]['url'].endswith('/api/internal/qweather/current')
    assert calls[0]['params']['lat'] == city['coordinate'][1]


def test_qweather_observations_drive_derived_risk_cells(monkeypatch):
    monkeypatch.setattr(weather_sources.httpx, 'Client', _client(PAYLOAD, []))
    monkeypatch.setattr(weather_sources, '_QW_CACHE', {'expires': 0.0, 'value': None})
    snapshot = weather_sources.qweather_snapshot([cities()[0]], force=True)
    cells = PublicWeather(snapshot, cities()).frame(0)
    assert len(cells) == 1
    assert cells[0]['source'] == 'QWEATHER_DERIVED_RISK'
    assert cells[0]['derivedFrom']['gustMps'] == 18.0
    assert cells[0]['derivedFrom']['visibilityM'] == 800.0


def test_unreachable_qweather_reports_unavailable_and_falls_back(monkeypatch):
    monkeypatch.setattr(weather_sources.httpx, 'Client', _client(PAYLOAD, [], fail=True))
    monkeypatch.setattr(weather_sources, '_QW_CACHE', {'expires': 0.0, 'value': None})
    failed = weather_sources.qweather_snapshot([cities()[0]], force=True)
    assert failed['available'] is False
    assert failed['errorCode'] == 'RuntimeError'
    assert 'SOURCE_UNAVAILABLE' in failed['qualityFlags']

    monkeypatch.setattr(weather_sources, 'PROVIDER', 'qweather')
    monkeypatch.setattr(weather_sources, 'open_meteo_snapshot',
                        lambda rows, force=False: {'available': True, 'provider': 'OPEN_METEO',
                                                   'qualityFlags': ['MODEL_ESTIMATE_NOT_STATION_OBSERVATION'],
                                                   'observations': []})
    merged = weather_sources.weather_snapshot([cities()[0]], force=True)
    assert merged['provider'] == 'OPEN_METEO'
    assert merged['preferredProvider'] == 'QWEATHER'
    assert 'PROVIDER_FALLBACK_OPEN_METEO' in merged['qualityFlags']


def test_default_provider_reports_its_configuration():
    status = weather_sources.provider_status()
    assert status['requestedProvider'] == weather_sources.PROVIDER
    assert status['configuredProvider'] in ('open-meteo', 'qweather')
    assert status['internalTokenConfigured'] is False or status['internalTokenConfigured'] is True
