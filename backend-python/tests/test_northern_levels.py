# -*- coding: utf-8 -*-
"""北方地区四级（北方 → 大区 → 省 → 市）的判据。

这一层是"回退并优化"后的主界面：
- 范围只有 13 个省级单元，不再假装覆盖全国；
- 干线是 A* 真算的（`network_builder`），东北 53 条仍走运行计划原网络；
- 四级数据各自独立，前端逐级加载、返回即释放。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from traffic import northern  # noqa: E402

NORTH_PROVINCES = 13


def test_north_level_covers_three_regions_and_13_provinces():
    payload = northern.payload('north')
    assert payload['status'] == 'OK'
    assert payload['summary']['provinces'] == NORTH_PROVINCES
    assert [region['name'] for region in payload['regions']] == ['东北', '华北', '西北']
    assert sum(region['provinces'] for region in payload['regions']) == NORTH_PROVINCES


def test_states_are_from_the_four_known_values():
    payload = northern.payload('north')
    for row in payload['provinces']:
        assert row['state'] in {'operational', 'observing', 'trunk', 'pending'}
        if row['state'] == 'operational':
            assert row['corridors'] > 0 and row['stations'] > 0
        if row['state'] == 'trunk':
            assert row['corridors'] > 0 and row['stations'] == 0


def test_northeast_keeps_the_run_network():
    """东北三省的本地走廊必须还是运行计划那张网（51 条，含跨省另计）。"""
    payload = northern.payload('region', 'northeast')
    assert payload['region']['name'] == '东北'
    run_rows = [row for row in payload['corridors'] if row['source'] == 'RUN']
    assert len(run_rows) == 53, f'东北城际走廊应为 53 条，实际 {len(run_rows)}'
    assert all(row['geometry'] == 'RUN_PLAN' for row in run_rows)


def test_trunk_corridors_are_astar_and_labelled_sim():
    payload = northern.payload('region', 'north')
    trunk = [row for row in payload['corridors'] if row['source'] == 'SIM']
    assert trunk, '华北应该有 A* 生成的干线'
    assert all(row['geometry'] in ('ASTAR', 'STRAIGHT_FALLBACK') for row in trunk)
    assert sum(1 for row in trunk if row['geometry'] == 'ASTAR') > 0
    for row in trunk:
        assert len(row['path']) >= 2
        assert -180 <= row['path'][0][0] <= 180


def test_province_level_lists_cities_and_city_level_is_reachable():
    province = northern.payload('province', '辽宁省')
    assert province['province']['name'] == '辽宁省'
    assert province['cities'], '省层必须给出下一级城市'
    city_name = province['cities'][0]['name']
    city = northern.payload('city', city_name)
    assert city['status'] == 'OK'
    assert city['city']['name'] == city_name


def test_unknown_ident_is_explicit_not_silent():
    assert northern.payload('province', '上海市')['status'] == 'NOT_FOUND'
    assert northern.payload('city', '不存在的市')['status'] == 'NOT_FOUND'
    assert northern.payload('weird')['status'] == 'INVALID'


def test_payload_size_is_bounded_per_level():
    for level, ident in (('north', ''), ('region', 'northeast'), ('province', '辽宁省')):
        body = json.dumps(northern.payload(level, ident), ensure_ascii=False)
        assert len(body.encode('utf-8')) < 120 * 1024, f'{level} 级载荷过大'
