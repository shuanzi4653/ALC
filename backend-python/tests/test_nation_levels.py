# -*- coding: utf-8 -*-
"""全国航线网四级（全国 → 大区 → 省 → 市）的判据。

这一层是 2026-11-10 用户拍板后的主界面：
- 范围 30 个省级单元，**不含台湾、西藏、港澳**（不通航）；
- 每市一个节点，省内 MST 保证市市相连；
- **没有机场的市必须有一条直连最近机场城市的接驳航线**（叠加，不替代省内网）；
- 跨省收窄到每省最近 1–2 个省（飞行汽车分担城际，不取代飞机火车）；
- 四级数据各自独立，前端逐级加载、返回即释放。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from traffic import nation  # noqa: E402

EXPECTED_PROVINCES = 30
EXCLUDED = ('台湾省', '西藏自治区', '香港特别行政区', '澳门特别行政区')


def test_nation_level_covers_six_regions_and_30_provinces():
    payload = nation.payload('nation')
    assert payload['status'] == 'OK'
    assert payload['summary']['provinces'] == EXPECTED_PROVINCES
    assert [region['name'] for region in payload['regions']] == ['华北', '东北', '华东', '中南', '西南', '西北']
    assert sum(region['provinces'] for region in payload['regions']) == EXPECTED_PROVINCES


def test_excluded_provinces_are_not_in_network():
    payload = nation.payload('nation')
    names = {row['name'] for row in payload['provinces']}
    for name in EXCLUDED:
        assert name not in names, f'{name} 不应纳入航线网'
    for name in EXCLUDED:
        assert nation.payload('province', name)['status'] == 'NOT_FOUND'


def test_every_non_airport_city_has_one_feed_corridor():
    """核心判据：没有机场的市，必须至少有一条 AIRPORT_FEED 直连机场城市。"""
    payload = nation.payload('nation')
    feed: dict = {}
    for row in payload['corridors']:
        if not row.get('feed'):
            continue
        for side in (row['fromName'], row['toName']):
            feed.setdefault(side, []).append(row)
    missing = [node['name'] for node in payload['nodes']
               if not node['hasAirport'] and not feed.get(node['name'])]
    assert not missing, f'这些市没有机场也没有接驳航线：{missing[:8]}'
    # 接驳航线的另一端必须是机场城市
    airport_names = {node['name'] for node in payload['nodes'] if node['hasAirport']}
    for row in payload['corridors']:
        if not row.get('feed'):
            continue
        assert row['fromName'] in airport_names or row['toName'] in airport_names


def test_intra_network_keeps_every_city_connected():
    """接驳是"多一条"，省内网照常跑：每个市在省内/跨省网里也得有边，不能只有接驳。"""
    payload = nation.payload('nation')
    linked: dict = {}
    for row in payload['corridors']:
        flags = set()
        if row.get('cross'):
            flags.add('cross')
        if row.get('feed'):
            flags.add('feed')
        if not flags:
            flags.add('intra')
        linked.setdefault(row['fromName'], set()).update(flags)
        linked.setdefault(row['toName'], set()).update(flags)
    lonely = [node['name'] for node in payload['nodes'] if not linked.get(node['name'])]
    assert not lonely, f'这些市没有任何航线：{lonely[:8]}'
    only_feed = [name for name, kinds in linked.items() if kinds == {'feed'}]
    # 只靠接驳线连网的市不应该太多（省内 MST 应已把它们接进网络）
    assert len(only_feed) <= len(payload['nodes']) * 0.15, f'只靠接驳连网的市过多：{len(only_feed)}'


def test_cross_province_is_narrowed_to_two_per_province():
    payload = nation.payload('nation')
    counter: dict = {}
    total = 0
    for row in payload['corridors']:
        if not row.get('cross'):
            continue
        total += 1
        for province in {row['fromProvince'], row['toProvince']}:
            counter[province] = counter.get(province, 0) + 1
    provinces = payload['summary']['provinces']
    assert len(counter) == provinces, f'有省份没有跨省通道：{provinces - len(counter)} 个'
    assert min(counter.values()) >= 1
    worst = max(counter.items(), key=lambda item: item[1])
    # 口径：省级 MST 保证连通（每省至少 1 条），再补最近邻；枢纽省份最多 4 条
    assert worst[1] <= 4, f'{worst[0]} 跨省通道 {worst[1]} 条，超过"每省 1–2 条最近邻"的口径'
    assert total <= 1.5 * provinces, f'跨省通道 {total} 条，太密（等于全互联）'


def test_province_level_lists_cities_and_city_level_is_reachable():
    province = nation.payload('province', '广东省')
    assert province['province']['name'] == '广东省'
    assert province['cities'], '省层必须给出下一级城市'
    city_name = next(row['name'] for row in province['cities'] if not row['hasAirport'])
    city = nation.payload('city', city_name)
    assert city['status'] == 'OK'
    assert city['city']['name'] == city_name
    assert city['city']['feedTarget'], '无机场市必须给出接驳目标'


def test_unknown_ident_is_explicit_not_silent():
    assert nation.payload('province', '不存在的省')['status'] == 'NOT_FOUND'
    assert nation.payload('city', '不存在的市')['status'] == 'NOT_FOUND'
    assert nation.payload('weird')['status'] == 'INVALID'


def test_payload_size_is_bounded_per_level():
    for level, ident in (('nation', ''), ('region', 'east'), ('province', '广东省')):
        body = json.dumps(nation.payload(level, ident), ensure_ascii=False)
        assert len(body.encode('utf-8')) < 400 * 1024, f'{level} 级载荷过大'
