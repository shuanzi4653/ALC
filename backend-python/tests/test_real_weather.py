"""真实气象模块（real_weather）的契约测试。

本文件取代了原来的 test_simulator.py。旧测试锁的是合成生成器的行为
（固定 seed + 固定时钟 → 可复现），那套东西已经被删掉；现在要锁的是相反的
性质：**取不到数据时绝不产出任何值**。
"""
import unittest

import real_weather


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            request = httpx.Request('GET', 'https://api.open-meteo.com/v1/forecast')
            raise httpx.HTTPStatusError('boom', request=request,
                                        response=httpx.Response(self.status_code, request=request))

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload=None, status=200, raises=None):
        self.payload = payload
        self.status = status
        self.raises = raises
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        if self.raises is not None:
            raise self.raises
        return _FakeResponse(self.payload, self.status)


def _payload():
    return {
        'current': {
            'time': '2026-09-18T16:00',
            'temperature_2m': 26.4, 'relative_humidity_2m': 36, 'precipitation': 0.0,
            'weather_code': 0, 'wind_speed_10m': 3.9, 'wind_direction_10m': 197,
            'wind_gusts_10m': 10.5, 'surface_pressure': 995.2, 'cloud_cover': 0,
        },
        'hourly': {
            'time': ['2026-09-18T16:00', '2026-09-18T17:00', '2026-09-18T18:00'],
            'temperature_2m': [26.4, 25.6, 24.2],
            'wind_speed_10m': [3.9, 3.3, 2.6],
            'wind_gusts_10m': [10.5, 9.9, 8.1],
            'precipitation': [0.0, 0.0, 0.0],
            'visibility': [27240.0, 27240.0, 24680.0],
        },
    }


class RealWeatherTest(unittest.TestCase):
    def test_snapshot_matches_the_snapshot_contract(self):
        result = real_weather.snapshot(43.9, 125.32, hours=3, client=_FakeClient(_payload()))
        snap = result['snapshot']
        # The Java side deserialises into WeatherSnapshot, which is a fixed field
        # set; every key it reads must be present here.
        for key in ('time', 'source', 'lat', 'lon', 'conditionText', 'tempC', 'humidity',
                    'windSpeed', 'windGust', 'windDeg', 'precipMmh', 'visibilityM',
                    'pressureHpa', 'cloudCover', 'thunderProb'):
            self.assertIn(key, snap, f'快照缺少字段 {key}')
        self.assertEqual(result['provider'], 'OPEN_METEO')
        # Percentages are converted to the internal 0-1 contract.
        self.assertAlmostEqual(snap['humidity'], 0.36)
        self.assertEqual(snap['cloudCover'], 0.0)

    def test_source_is_never_labelled_sim(self):
        result = real_weather.snapshot(43.9, 125.32, client=_FakeClient(_payload()))
        self.assertEqual(result['snapshot']['source'], 'open-meteo')
        self.assertNotEqual(result['snapshot']['source'], 'sim')
        self.assertIn('MODEL_ESTIMATE_NOT_STATION_OBSERVATION',
                      result['snapshot']['qualityFlags'])
        self.assertEqual(result['snapshot']['dataType'], 'MODEL_ESTIMATE')

    def test_thunder_is_absent_rather_than_invented(self):
        result = real_weather.snapshot(43.9, 125.32, client=_FakeClient(_payload()))
        # This source exposes no verified thunder field. Reporting 0.0 would be a
        # claim; None is the truth.
        self.assertIsNone(result['snapshot']['thunderProb'])
        self.assertTrue(all(row['thunderProb'] is None for row in result['hourly']))

    def test_hourly_rows_are_the_declared_length_and_flat(self):
        result = real_weather.snapshot(43.9, 125.32, hours=3, client=_FakeClient(_payload()))
        self.assertEqual(len(result['hourly']), 3)
        for row in result['hourly']:
            self.assertEqual(set(row), {'time', 'tempC', 'windSpeed', 'windGust',
                                        'precipMmh', 'visibilityM', 'thunderProb'})

    def test_missing_values_stay_missing_and_are_not_interpolated(self):
        payload = _payload()
        payload['hourly']['visibility'] = [None, 24680.0, 21520.0]
        payload['current']['wind_gusts_10m'] = None
        result = real_weather.snapshot(43.9, 125.32, hours=3, client=_FakeClient(payload))
        self.assertIsNone(result['snapshot']['windGust'])
        self.assertIsNone(result['hourly'][0]['visibilityM'])
        self.assertAlmostEqual(result['hourly'][1]['visibilityM'], 24680.0)

    def test_http_error_becomes_source_unavailable(self):
        # The whole point: a failed fetch must not be convertible into data.
        with self.assertRaises(real_weather.SourceUnavailable):
            real_weather.snapshot(43.9, 125.32, client=_FakeClient(_payload(), status=503))

    def test_transport_error_becomes_source_unavailable(self):
        import httpx
        with self.assertRaises(real_weather.SourceUnavailable):
            real_weather.snapshot(43.9, 125.32, client=_FakeClient(raises=httpx.ConnectError('no route')))

    def test_empty_current_section_is_unavailable(self):
        with self.assertRaises(real_weather.SourceUnavailable):
            real_weather.snapshot(43.9, 125.32, client=_FakeClient({'hourly': {}}))

    def test_status_reports_no_credentials_and_states_the_caveat(self):
        status = real_weather.status()
        self.assertEqual(status['provider'], 'OPEN_METEO')
        self.assertFalse(status['credentialed'])
        self.assertEqual(status['dataType'], 'MODEL_ESTIMATE')
        self.assertIn('非测站观测', status['note'])

    def test_request_asks_for_the_declared_fields(self):
        client = _FakeClient(_payload())
        real_weather.snapshot(43.9, 125.32, client=client)
        _, params = client.calls[0]
        current = params['current'].split(',')
        self.assertEqual(current, list(real_weather.CURRENT_FIELDS))
        self.assertEqual(params['timezone'], 'Asia/Shanghai')
        self.assertEqual(params['wind_speed_unit'], 'ms')


if __name__ == '__main__':
    unittest.main()
