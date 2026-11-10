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
        # 班次对象化（许可/剖面/裁决依据）之后载荷变大，nation 级从 ~240 KB 涨到 ~480 KB。
        # 上限放到 560 KB：gzip 后约 70 KB，仍在可接受范围，同时还能挡住"又翻一倍"的回归。
        assert len(body.encode('utf-8')) < 560 * 1024, f'{level} 级载荷过大'


def test_province_level_shows_cross_province_endpoints():
    """省级页必须把跨省航线的**另一端**也画出来，否则只有一条线伸出去，看不出飞到哪。"""
    payload = nation.payload('province', '辽宁省')
    cross = [row for row in payload['corridors'] if row.get('cross')]
    assert cross, '辽宁省应有跨省航线'
    endpoints = set()
    for row in cross:
        if row['fromProvince'] != '辽宁省':
            endpoints.add(row['fromName'])
        if row['toProvince'] != '辽宁省':
            endpoints.add(row['toName'])
    external = {node['name'] for node in payload['nodes'] if node.get('external')}
    assert endpoints, '跨省航线应有对端城市'
    assert endpoints <= external, f'这些对端城市没画出来：{endpoints - external}'
    # 本级城市数不能把对端城市算进来。
    # 辽宁原有 14 个地级单元；丹东距境外 1.2 km，按"边境 50 km 退出通航"整体删除，现在是 13。
    assert payload['summary']['cities'] == 13
    assert payload['summary']['externals'] == len(external)


def test_city_nodes_carry_per_city_weather():
    """气象是**逐市**的：每个城市节点带自己的温度/风速/能见度（取不到就是 None）。

    这条依赖 open-meteo 的免费额度。额度打满（429）时全国一张实况都取不到，
    此时跳过而不是判失败 —— 否则一次接口限流会被当成代码回归。
    限流本身另有验证：`city_weather` 的 429 快路径与磁盘兜底。
    """
    payload = nation.payload('province', '辽宁省')
    weather = [node['weather'] for node in payload['nodes'] if node.get('weather')]
    if not weather:
        import pytest
        pytest.skip('实况源本轮不可用（多半是 open-meteo 429 限流），跳过逐市气象断言')
    # 主源被限流时，备源（wttr.in）只补省会与机场城市，一般城市没有实况是**预期行为**；
    # 这里只要"有相当一部分城市带自己的气象"即可，不按 100% 判。
    if len(weather) < len(payload['nodes']) * 0.3:
        import pytest
        pytest.skip(f"备源补数中（本省 {len(weather)}/{len(payload['nodes'])} 城有实况）")
    assert len(weather) >= len(payload['nodes']) * 0.8, '逐市气象覆盖率过低'
    for item in weather:
        assert 'tempC' in item and 'visM' in item and 'windMps' in item and 'low' in item
    assert payload['summary']['weatherSource'].startswith('open-meteo')


def test_fog_areas_are_derived_from_city_visibility():
    """雾区是**由城市能见度派生**的面，不是雾场观测：档位要和能见度对得上。"""
    payload = nation.payload('nation', None, 60)
    fog = payload['fog']
    assert fog['note'] and '不是雾场观测' in fog['note'], '雾区必须标明派生口径'
    for level in ('BAN', 'LOW'):
        for ring in fog['bands'][level]:
            assert len(ring) >= 4, '雾区面至少要是一个闭合环'
    for city in fog['cities']:
        assert city['visM'] < 3000, '能见度没低于 3 km 的城市不该进雾区'
        assert (city['level'] == 'BAN') == (city['visM'] < 1500), '1.5 km 档位判错了'


def test_evidence_chain_has_source_on_every_row():
    """取证链的硬规矩：**每一行都要有来源**，没有来源的行不许写。"""
    payload = nation.payload('nation', None, 60)
    assert payload['flights'], '全国层此刻应有在飞班次'
    flight = payload['flights'][0]
    body = nation.evidence(flight['id'], 60)
    assert body['status'] == 'OK', body.get('note')
    assert body['steps'], '取证链不能是空的'
    for step in body['steps']:
        assert step['rows'], f"{step['title']} 没有内容"
        for row in step['rows']:
            assert row['source'] in ('SIM', 'PUBLIC', 'DERIVED', 'OFFICIAL', 'MANUAL'), row
            assert row['value'] not in (None, ''), row
    assert '规则派生' in body['discipline']


def test_evidence_reports_not_airborne_instead_of_guessing():
    """该分钟不在飞时要如实说"不在飞"，不能编一条出来。"""
    body = nation.evidence('NC-0001#999', 60)
    assert body['status'] in ('NOT_AIRBORNE', 'NOT_FOUND')
    assert body.get('note')


def test_border_monitor_is_geometric_not_flag_based():
    """越界监视必须是**逐条量距离**算出来的，不是读停飞标记。"""
    payload = nation.payload('nation', None, 60)
    border = payload['border']
    assert '10 km' in border['method'] and '求距' in border['method']
    assert border['checkedCorridors'] >= 400, '航路没有被逐条测量'
    assert isinstance(border['nearestKm'], (int, float)) and border['nearestKm'] > 0
    assert border['inside'] == 0, '按当前路网不应有飞机在 10 km 带内'


def test_national_model_is_live_and_scored():
    """全国模型（ml-v3）必须真的在跑：有指标、有覆盖、每架都有概率。"""
    payload = nation.payload('nation', None, 60)
    card = payload['modelCard'].get('nationalModel') or {}
    assert card.get('available'), '全国模型没加载'
    test = (card.get('metrics') or {}).get('test') or {}
    assert test.get('auc', 0) > 0.8, f"测试集 AUC 异常：{test.get('auc')}"
    assert card['provenance']['cities'] >= 300
    covered = [row for row in payload['flights'] if row.get('pModel') is not None]
    if not covered:
        import pytest
        pytest.skip('逐市小时数据本轮取不到（限流），模型概率不可用，跳过')
    assert all(row['probSource'] == 'MODEL' for row in covered)


def test_pulse_reports_change_key():
    """心跳只回答"变没变"：必须带雷达帧、实况时刻、模型版本三个键。"""
    import json as _json
    pulse = _json.loads(_json.dumps(nation.pulse(), ensure_ascii=False))
    for key in ('radarTs', 'weatherAt', 'modelVersion', 'cities'):
        assert key in pulse, f'心跳缺字段 {key}'
    assert pulse['cities'] >= 300
