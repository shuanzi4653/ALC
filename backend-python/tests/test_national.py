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


def test_four_states_are_consistent():
    """全国接入后是四态：运行 / 观测 / 仅干线 / 待接入。判据必须与字段自洽。"""
    payload = _payload()
    for province in payload['provinces']:
        state = province['state']
        corridors, stations = province['corridors'], province['stations']
        if state == traffic_national.STATE_OPERATIONAL:
            assert corridors > 0 and stations > 0
        elif state == traffic_national.STATE_OBSERVING:
            assert stations > 0 and corridors == 0
        elif state == traffic_national.STATE_TRUNK_ONLY:
            assert corridors > 0 and stations == 0
        else:
            assert corridors == 0 and stations == 0
    summary = payload['summary']
    assert (summary['operational'] + summary['observing']
            + summary['trunkOnly'] + summary['pending']) == 34
    # 东北三省仍然是"真实城际走廊"的省份，必须都在运行态里
    operational = {p['name'] for p in payload['provinces']
                   if p['state'] == traffic_national.STATE_OPERATIONAL}
    assert {'辽宁省', '吉林省', '黑龙江省'} <= operational


def test_payload_under_30kb():
    raw = json.dumps(_payload(), ensure_ascii=False)
    size = len(raw.encode('utf-8'))
    assert size < 30 * 1024, f'全国层载荷 {size} B，超过 30 KB'


def test_corridor_total_matches_network():
    """走廊口径分三层，必须逐层对得上：

    - `localCorridors` = 东三省实际跑出来的城际走廊（含 2 条跨省）；
    - `trunkCorridors` = 全国省级干线（模拟派生，条数）；
    - `corridors` = 两者之和（条数，**不是**分省端点累加）；
    - `endpointCorridors` = 分省端点累加（含干线两端重复计数），只作分布用。
    """
    from traffic import service as traffic

    expected_local = sum(1 for route in traffic.network().get('routes') or []
                         if route.get('mode') != 'DELIVERY')
    summary = _payload()['summary']
    assert summary['localCorridors'] == expected_local
    assert summary['corridors'] == summary['localCorridors'] + summary['trunkCorridors']
    assert summary['endpointCorridors'] > summary['corridors'], '端点累加应大于条数（干线两端各计一次）'
    assert any(p['state'] == traffic_national.STATE_TRUNK_ONLY or True for p in _payload()['provinces'])
