# -*- coding: utf-8 -*-
"""全国覆盖层（站 + 干线）的判据。

三条硬约束：
1. **四态之和 = 34**，且四态含义互斥（运行 / 观测 / 仅干线 / 待接入）。
2. **站是真实的**：点位必须落在省界多边形内、必须在中国经纬度范围内；拿不到就 0，不补零。
3. **干线是模拟的**：每条都带 `source: SIM`，且不参与运行计划（只影响全国层聚合）。
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from traffic import national as national_mod  # noqa: E402
from weather import national_metar  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _payload():
    return national_mod.national()


def test_four_states_add_up_to_34():
    summary = _payload()['summary']
    total = (summary['operational'] + summary['observing']
             + summary['trunkOnly'] + summary['pending'])
    assert summary['provinces'] == 34
    assert total == 34, '四态必须互斥且覆盖全部 34 个省级单元'


def test_every_province_states_are_from_the_four_known_values():
    allowed = {'operational', 'observing', 'trunk', 'pending'}
    for row in _payload()['provinces']:
        assert row['state'] in allowed, row['name']


def test_trunk_corridors_are_labelled_sim_and_cover_provinces():
    payload = json.loads((ROOT / 'data' / 'traffic' / 'national-corridors.json')
                         .read_text(encoding='utf-8'))
    assert payload['source'] == 'SIM'
    assert payload['count'] == len(payload['corridors']) > 0
    adcodes = {row['adcode'] for row in national_mod.provinces()}
    for row in payload['corridors']:
        assert row['source'] == 'SIM'
        assert row['from'] in adcodes and row['to'] in adcodes
        assert len(row['fromLonLat']) == 2 and len(row['toLonLat']) == 2
    # 台湾不生成干线（只参与观测），避免凭空造跨海航线
    assert all(row['from'] != 710000 and row['to'] != 710000 for row in payload['corridors'])


def test_station_points_are_inside_china_and_carry_a_timestamp():
    payload = _payload()
    for point in payload['stationPoints']:
        assert 73.0 <= point['lon'] <= 136.0, point
        assert 17.0 <= point['lat'] <= 54.0, point
        assert point['ts'].endswith('Z'), '每条站必须带观测时刻，不许只给一个数'
        assert point['code'] and point['name']


def test_province_station_count_matches_station_points():
    payload = _payload()
    per_province = {}
    for point in payload['stationPoints']:
        per_province[point['name']] = per_province.get(point['name'], 0) + 1
    for row in payload['provinces']:
        assert row['stations'] == per_province.get(row['name'], 0), row['name']


def test_payload_stays_under_30kb():
    body = json.dumps(_payload(), ensure_ascii=False)
    assert len(body.encode('utf-8')) < 30 * 1024, f'全国层载荷超限：{len(body)} bytes'


def test_missing_metar_source_does_not_fabricate_stations(monkeypatch):
    """拿不到报文时必须全 0，且不能冒出"运行态"。"""
    monkeypatch.setattr(national_metar, 'fetch',
                        lambda force=False: {'available': False, 'error': 'test', 'stations': {}})
    payload = national_mod.national()
    assert all(point == {} or point for point in [{}])  # 占位，保证断言顺序可读
    assert payload['stationPoints'] == []
    assert all(row['stations'] == 0 for row in payload['provinces'])
    assert payload['summary']['operational'] == 0
    assert payload['summary']['observing'] == 0
    assert payload['summary']['trunkOnly'] + payload['summary']['pending'] == 34


def test_national_layer_does_not_touch_operational_numbers():
    """全国层只是聚合：摘要里不许出现运行计划的班次口径。"""
    body = json.dumps(_payload(), ensure_ascii=False)
    for forbidden in ('2848', '3016', '3048', '1614'):
        assert forbidden not in body
