# -*- coding: utf-8 -*-
"""全国层聚合（/traffic/v2/national）的判据。

四条硬约束，对应 V1.0.1 软件册 §10 的验收 1 与人日 W1：
1. 省级单元 35 个、七大区齐全
2. 三态互斥且与数据一致（有走廊才算 operational）
3. 载荷 < 30 KB
4. 本接口不参与规划 —— 不改变任何既有运行数字（用"只读"断言代替，见第 4 条）
"""
import json

from traffic import national as traffic_national


def _payload():
    return traffic_national.national()


def test_province_and_region_coverage():
    payload = _payload()
    provinces = payload['provinces']
    # 底图 35 要素里有 1 个南海诸岛示意（无 adcode），省级单元实为 34
    assert len(provinces) == 34, f'省级单元应为 34，实为 {len(provinces)}'
    assert [region['id'] for region in payload['regions']] == list(traffic_national.REGION_ORDER)
    # 每个省都要落到一个大区（含 other），不允许 region 为空
    assert all(province['region'] for province in provinces)
    # 七大区合计 + 港澳台 = 34
    covered = sum(region['provinceCount'] for region in payload['regions'])
    other = sum(1 for province in provinces if province['region'] == 'other')
    assert covered + other == 34


def test_three_states_are_consistent():
    payload = _payload()
    for province in payload['provinces']:
        if province['state'] == traffic_national.STATE_OPERATIONAL:
            assert province['corridors'] > 0
        elif province['state'] == traffic_national.STATE_OBSERVING:
            assert province['corridors'] == 0 and province['stations'] > 0
        else:
            assert province['corridors'] == 0 and province['stations'] == 0
    summary = payload['summary']
    assert summary['operational'] + summary['observing'] + summary['pending'] == 34
    # 东北三省是当前唯一运行态
    operational = {p['name'] for p in payload['provinces'] if p['state'] == traffic_national.STATE_OPERATIONAL}
    assert operational == {'辽宁省', '吉林省', '黑龙江省'}


def test_payload_under_30kb():
    raw = json.dumps(_payload(), ensure_ascii=False)
    size = len(raw.encode('utf-8'))
    assert size < 30 * 1024, f'全国层载荷 {size} B，超过 30 KB'


def test_corridor_total_matches_network():
    """全国层城际走廊 = 分省城际走廊 + 跨省走廊，一条都不能丢、也不能凭空多。"""
    from traffic import service as traffic

    expected = sum(1 for route in traffic.network().get('routes') or []
                   if route.get('mode') != 'DELIVERY')
    summary = _payload()['summary']
    assert summary['corridors'] + summary['interprovincialCorridors'] == expected
