import json
import data_sources


def test_quality_and_missing_do_not_become_safe_zero():
    sample = data_sources.normalize(dict(DATE='2025-07-01T00:00:00', WND='999,9,N,9999,9',
        TMP='+0250,1', VIS='001000,1,N,1', AA1='06,0012,9,1'))
    assert sample['windSpeedMps'] is None
    assert sample['windDirectionDeg'] is None
    assert sample['temperatureC'] == 25
    assert sample['precipitationAccumulationMm'] == 1.2
    assert sample['precipitationPeriodHours'] == 6
    assert sample['thunderProbability'] is None


def test_regional_cache_failures_are_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(data_sources, 'DATA', tmp_path)
    (tmp_path/'liaoning.json').write_text(json.dumps({'samples': [], 'stations': []}))
    (tmp_path/'jilin.json').write_text('broken')
    result = data_sources.observations()['regions']
    assert [r['status'] for r in result] == ['HISTORICAL', 'ERROR', 'NO_DATA']
    assert all(r['forecastStatus'] == 'NO_DATA' for r in result)
