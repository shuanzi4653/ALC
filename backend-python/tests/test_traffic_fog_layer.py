# -*- coding: utf-8 -*-
"""低能见度（雾）派生通道：两档、独立图层、参与避让但**不拒绝起降**。

这条通道是 0.9.27 新增的，它的存在理由是一个屏幕上看得见、报表上查不到的现象：

  用户报「刚开始有几个标黄的路径不知道原因关闭」。成因是 **能见度 < 1000 m** 走
  `_extreme_kind` → `point_risk_shapes`，在站心生成一个 6 km 的禁止内核；而
  `city_pads(city)[0]` **就是城区代表中心**，所以那个内核必然把枢纽包在里面，该城
  所有班次连起飞都不可能。屏幕上却看不出为什么：那 6 km 圆盘被并进了同一片暖色
  「气象风险区」，在三省全域视图上只有十几像素。

本文件钉住四件事，每一件都对应一个**具体的错法**：

  1. 两条阈值来自 SFI 规则配置（不是本模块另写一份）—— 错法是"评分说这是警戒、
     地图说这是禁区"，两个结论互相矛盾而两边各自都算对了；
  2. 深灰档的几何**与改造前那个内核逐字节相同** —— 错法是"顺手改了半径"，于是
     "让雾看得见"和"改了哪些班次能飞"混成同一次改动，事后无法归因；
  3. 浅灰档**绝不拒绝**一座落在它里面的城 —— 错法是 2026-09-30 那 2488 班关闭
     的重演（"谨慎进入"变成"不许起飞"）。**这是本文件最重要的一条**；
  4. 缺测不等于 0 m —— 错法是把一次"源没发布"读成一次最严重的禁飞。
"""
import pytest
from shapely.geometry import GeometryCollection, Point

from rules import load_spec
from traffic import service, weather as W
from traffic.catalog import cities

# 与 `test_traffic_live_weather.py` 用同一种快照形状：**夹具必须照抄被抓对象的真实形状**，
# 而不是本地另发明一种。差别只有在形状不一致时才不会被发现。
def _snapshot(observation, provider='OPEN_METEO'):
    return {'available': True, 'provider': provider, 'dataType': 'MODEL_ESTIMATE',
            'qualityFlags': ['MODEL_ESTIMATE_NOT_STATION_OBSERVATION'],
            'observations': [observation]}


def _observation(city, visibility_m):
    row = {'cityId': city['id'], 'windGusts10mMps': 0.0, 'precipitationMm': 0.0,
           'conditionClass': None, 'hourly': {'visibility': [10000]}}
    if visibility_m is not None:
        row['hourly'] = {'visibility': [visibility_m]}
    else:
        row['hourly'] = {'visibility': []}
    return row


# ---------------------------------------------------------------------------
# 1. 阈值必须来自配置，且"正好等于阈值"归偏低档
# ---------------------------------------------------------------------------
def test_thresholds_come_from_the_sfi_rule_config():
    """能见度的两条阈值读自 `config/rules-v1.json`，不在这里另写一份。

    断言写成**关系式**（雾档 == SFI 那条因子规则的 warn/ban），不写死 5000/1000：
    写死的话，有人调了配置、忘了调这里，两边会各自"通过"，而屏幕上会出现
    "评分说这是警戒、地图说这是禁区"两个矛盾结论 —— 这正是 M79（同一个量有两份
    副本时，两份各自被钉过也不会报警）。
    """
    W.visibility_thresholds.cache_clear()
    factor = next(f for f in load_spec().factors if f.key == 'visibilityM')
    caution_m, ban_m = W.visibility_thresholds()
    assert caution_m == float(factor.warnValue)
    assert ban_m == float(factor.banValue)


def test_the_boundary_belongs_to_the_milder_tier():
    """`visibility == ban` 归**偏低档**，不是禁飞档 —— 与 `_extreme_kind` 一致。

    `rules.FactorRule.banned` 用的是 `<=`，两处对"正好等于阈值"的读法不同。这里选择
    与既有 `_extreme_kind` 一致的那一种（`<`），并把选择写成断言，否则下一次有人按
    `<=` 读代码时会得到一个与地图不符的结论，而没有任何东西会红。
    """
    city = cities()[0]
    _caution_m, ban_m = W.visibility_thresholds()
    exact = _snapshot(_observation(city, ban_m))
    assert W._extreme_kind(exact['observations'][0]) is None
    rows = W.fog_tiers(exact, cities())
    assert len(rows) == 1
    cell, caution, ban = rows[0]
    assert cell['tier'] == 'CAUTION'
    assert ban.is_empty, '正好等于禁飞阈值不得生成禁止几何'
    assert not caution.is_empty


# ---------------------------------------------------------------------------
# 2. 深灰档的几何与改造前的极端内核**同一种造法**
# ---------------------------------------------------------------------------
def test_ban_tier_reuses_the_extreme_core_disc_construction():
    """深灰档 == 改造前 `Point(city.xy).buffer(6000, quad_segs=16).simplify(120)`。

    这条是**归因判据**，不是整洁：本次改动的目标是"让雾看得见 + 分两档"，不是
    "顺便改半径"。两者混在一起的话，构建结果里任何一个数字变了都无法归因到其中之一。
    逐字节对照（`symmetric_difference`）比面积近似更强：面积相同而形状移动过，正是
    这类改动最容易留下的痕迹。
    """
    city = cities()[0]
    _caution_m, ban_m = W.visibility_thresholds()
    rows = W.fog_tiers(_snapshot(_observation(city, ban_m - 1)), cities())
    assert len(rows) == 1
    _cell, _caution, ban = rows[0]
    assert not ban.is_empty

    before = Point(city['xy']).buffer(W.EXTREME_CORE_RADIUS_M, quad_segs=16).simplify(
        W.SIMPLIFY_TOLERANCE, preserve_topology=True)
    assert ban.symmetric_difference(before).area < 1e-6, \
        '深灰档的几何必须与改造前的内核一致，否则半径被动过'
    assert W.FOG_BAN_RADIUS_M == W.EXTREME_CORE_RADIUS_M


def test_caution_ring_never_paints_over_the_ban_core():
    """两档恒不相交，且浅灰是**环**不是整圆。

    直接并 CAUTION 会让更深的那一层被自己的外环涂掉（V1.5 风险区合并量到的同一个
    教训，那里溢出 3.86e8 m²）。所以 CAUTION 必须重建为 `disc(宽) − disc(深)`。
    """
    city = cities()[0]
    _caution_m, ban_m = W.visibility_thresholds()
    _cell, caution, ban = W.fog_tiers(_snapshot(_observation(city, ban_m - 1)), cities())[0]
    assert caution.intersection(ban).area < 1e-6
    assert caution.area > 0 and ban.area > 0


# ---------------------------------------------------------------------------
# 3. 关键：浅灰档不拒绝，且这一条要**两个方向**都自证
# ---------------------------------------------------------------------------
def test_mild_visibility_still_mints_no_risk_cell_in_the_warm_layer():
    """方向一（负）：能见度 3 km **不在**暖色风险层里生成任何几何。

    这正是 `test_mildly_adverse_weather_mints_no_geometry_and_no_obstacle` 守的那条
    2488 班回归线，而它**必须继续成立**：暖色层是"单次读数 → 一个禁止内核"，而站心
    内核必然包含枢纽，所以那条路径上任何"轻度也能出几何"的改动都会重演缺陷。
    """
    city = cities()[0]
    snapshot = _snapshot(_observation(city, 3000.0))
    assert W.point_risk_shapes(snapshot, cities()) == []
    assert W.PublicWeather(snapshot, cities()).envelope(0, 480).is_empty


def test_mild_visibility_does_mint_a_two_tier_fog_region():
    """方向二（正）：同一份 3 km 读数**在雾区通道里**是一个浅灰档。

    只看方向一会得出"3 km 什么也不生成"这个**错的**结论 —— 而它在地图上是有东西的。
    一条判据如果只钉"不再生成几何"，它就无法区分"功能被正确移走"和"功能被删掉了"。
    """
    city = cities()[0]
    rows = W.fog_tiers(_snapshot(_observation(city, 3000.0)), cities())
    assert len(rows) == 1
    cell, caution, ban = rows[0]
    assert cell['tier'] == 'CAUTION'
    assert not caution.is_empty, '浅灰档必须给出几何，否则它在地图上不存在'
    assert ban.is_empty, '没有低于禁飞阈值就不许生成禁止几何'
    assert cell['visibilityM'] == 3000.0
    # 几何必须落在该城自己的位置上，而不是别处
    assert caution.distance(Point(city['xy'])) < 1e-6


def test_exempt_rule_removes_only_the_disc_that_contains_the_pad():
    """枢纽豁免的规则本身。

    "起降点落在某个圆里 → 摘掉**那个圆**"是唯一的写法。摘掉整层的错法是：一座城的
    大雾会让**其它所有城**的浅灰约束同时失效（一个只在雾天出现的隐形裁剪，M25）。
    """
    city_a, city_b = cities()[0], cities()[1]
    discs = [
        {'cityId': city_a['id'], 'geometry': Point(city_a['xy']).buffer(12000, quad_segs=16)},
        {'cityId': city_b['id'], 'geometry': Point(city_b['xy']).buffer(12000, quad_segs=16)},
    ]
    # 起降点就在 city_a 的圆心
    rest, exempt_cities = service._exempt_fog_caution(
        discs, city_a['xy'], city_a['xy'])
    assert exempt_cities == [city_a['id']]
    assert rest is not None
    assert rest.contains(Point(city_b['xy'])), '其它城的圆必须仍然生效'
    assert not rest.contains(Point(city_a['xy'])), '被豁免的圆必须真的被摘掉'


def test_exempt_rule_reports_the_two_cases_apart():
    """「什么都没豁免」与「全豁免了」必须可区分。

    前者沿用整层几何、后者是空几何。用一个空几何表示两者，会让"雾区完全没约束到
    本班次"和"本班次根本不在任何雾区附近"在判据上长得一样 —— 而前者意味着一条
    被跳过的约束，是必须能看见的（M25）。
    """
    city = cities()[0]
    discs = [{'cityId': city['id'],
              'geometry': Point(city['xy']).buffer(12000, quad_segs=16)}]
    far = (city['xy'][0] + 5_000_000, city['xy'][1])
    rest, exempt_cities = service._exempt_fog_caution(discs, far, far)
    assert (rest, exempt_cities) == (None, []), '不在任何圆里时必须返回 None，不是空几何'


# ---------------------------------------------------------------------------
# 4. 缺测 ≠ 0 m
# ---------------------------------------------------------------------------
def test_a_missing_visibility_reading_mints_nothing():
    """源没发布能见度 → 弃权（不生成几何），**不是**读成 0 m 的最严重禁飞。

    `Number(null) === 0` 是前端那个坑的同一族；后端这边对应的是
    `_first_visibility` 返回 None 时不能被当成一个数值参与比较。
    """
    city = cities()[0]
    snapshot = _snapshot(_observation(city, None))
    assert W._first_visibility(snapshot['observations'][0]) is None
    assert W.fog_tiers(snapshot, cities()) == []


def test_an_unavailable_snapshot_mints_nothing():
    assert W.fog_tiers({'available': False, 'observations': []}, cities()) == []


# ---------------------------------------------------------------------------
# 5. 成因词表与图层契约
# ---------------------------------------------------------------------------
def test_low_visibility_is_its_own_weather_route_basis():
    """`LOW_VISIBILITY` 必须在 `ROUTE_BASIS` 里，且**必须算气象**。

    漏掉后者（不在 `WEATHER_BASIS` 里）的症状只在报表上出现：因为雾而改航的班次
    不计入"受气象影响改航"。两个集合都是封闭词表，前端的
    `WEATHER_ROUTE_BASES` / `BASIS_MACHINERY` 逐键与它们对齐。
    """
    assert 'LOW_VISIBILITY' in service.ROUTE_BASIS
    assert 'LOW_VISIBILITY' in service.WEATHER_BASIS


def test_non_live_scenarios_publish_no_fog_geometry():
    """`clear` / `unknown` 是关于"有没有"的陈述，不是场 —— 不许发布雾区几何。

    这里仍然要带**规则数字**：规则是声明不是观测，晴天它也成立（同 `_radar_rule_block`）。
    去取一次真快照就会在"声称没有天气"的画面里画出雾，两个矛盾陈述同屏。
    """
    rules = W.fog_rule_block()
    assert rules['cautionVisibilityM'] < float('inf')
    for scenario in ('clear', 'unknown'):
        frame = service.weather_frame(42, scenario, 0)
        block = frame['lowVisibility']
        assert block['available'] is False
        assert block['regions'] == []
        assert block['cautionVisibilityM'] == rules['cautionVisibilityM']
        assert block['reason'] == 'SCENARIO_DOES_NOT_DECLARE_WEATHER'


def test_live_frame_publishes_the_layer_with_flat_rule_numbers():
    """live 帧里雾区是与 `cells` / `radar` 并列的**独立**一块。

    规则数字**平铺在本块顶层**，不放在 `rule` 子对象里 —— `radarRuleBlock` 曾经读的
    就是那个在任何分支上都不存在的键，于是恒返回 null，而调用方有一条读起来很合理的
    弃权分支，判据栏长期印着假话。一个约定，两处照做。
    """
    frame = service.weather_frame(42, 'live', 0)
    block = frame['lowVisibility']
    # 取不到实测（上游/网络）时**跳过而不是失败**：这是环境状态，不是分层缺陷。
    # 但只在这一种原因下跳过 —— "读到了、却没有区域"仍然是失败，
    # 因为那才说明这一块的产出逻辑破了。两者在 `reason` 上分得开，
    # 所以不需要靠"看起来像网络问题"来判断（那种判断没法复核）。
    if not block.get('available') and block.get('reason') == 'WEATHER_UNAVAILABLE':
        pytest.skip('本次没取到实测气象（WEATHER_UNAVAILABLE）—— 环境状态，非分层缺陷')
    assert block['available'] is True, f'雾区不可用，原因：{block.get("reason")}'
    assert 'rule' not in block, '规则数字必须平铺，不许另开子对象'
    for key in ('cautionVisibilityM', 'banVisibilityM', 'cautionRadiusM',
                'banRadiusM', 'hardTier', 'softTier', 'padExemptTier',
                'thresholdSource'):
        assert key in block, key
    assert block['thresholdSource'] == 'config/rules-v1.json::visibilityM'
    # 每条记录必须自证它是哪一档、多少米，否则界面没法把两档分开画
    for region in block['regions']:
        assert region['tier'] in ('BAN', 'CAUTION')
        assert isinstance(region['visibilityM'], (int, float))


def test_the_layer_is_not_the_radar_layer():
    """两条通道必须各自成立：雾区不因为雷达不可用而消失，反之亦然。"""
    frame = service.weather_frame(42, 'live', 0)
    assert 'lowVisibility' in frame and 'radar' in frame
    assert frame['lowVisibility'] is not frame['radar']
    assert frame['lowVisibility'].get('source') is None, \
        '雾区是点观测派生，不带雷达的 source 标记'


# ---------------------------------------------------------------------------
# 6. 端到端：浅灰档不许关闭任何班次
# ---------------------------------------------------------------------------
def test_no_flight_is_closed_by_the_caution_tier(monkeypatch):
    """一份**只有**浅灰档的天气里，没有任何班次被气象关闭。

    这是"画 + 也参与避让"这个口径能不能成立的**唯一**判据。浅灰档接进了避让机制
    （软障碍，可擦边），而站心圆必然包含自己的枢纽 —— 如果不豁免，任何一条从该城
    出发的航路都必须先穿过包围自己的环，`route()` 必然无解，于是那座城的每一班都
    被关掉。实测口径下这就是 2488 班那个缺陷的形状。

    雷达在这里被显式摘掉：本测试要问的是"雾区关了谁"，让回波也在场就会得到
    `WEATHER_BLOCKED > 0` 却无法归因到哪一条通道 —— 而**归因**正是这条判据的全部内容。
    """
    city = cities()[0]
    monkeypatch.setattr(service, '_radar_avoidance',
                        lambda *args, **kwargs: (GeometryCollection(),
                                                 {'included': False,
                                                  'reason': 'TEST_ISOLATION'}))
    plan = service.simulate(seed=42, scenario='live',
                            live_snapshot=_snapshot(_observation(city, 3000.0)))
    fog = plan['lowVisibilityAvoidance']
    assert fog['cautionCities'] == 1, '构造用例必须真的产出一个浅灰档'
    assert fog['banCities'] == 0
    assert fog['padExemptFlights'] > 0, \
        '该城的班次必须被豁免，否则它们会因为自己的浅灰圆而被关'
    blocked = [item for item in plan['flights'] if item.get('reason') == 'WEATHER_BLOCKED']
    assert blocked == [], '浅灰档不许关闭任何班次（口径：须绕飞，可擦边，不是拒绝）'


def test_a_ban_tier_city_is_still_refused(monkeypatch):
    """方向对照：深灰档仍然拒绝 —— 否则"雾区参与避让"就退化成了一个纯装饰图层。

    没有这一条，上一条判据可以用"干脆不接进避让"来通过。
    """
    city = cities()[0]
    _caution_m, ban_m = W.visibility_thresholds()
    monkeypatch.setattr(service, '_radar_avoidance',
                        lambda *args, **kwargs: (GeometryCollection(),
                                                 {'included': False,
                                                  'reason': 'TEST_ISOLATION'}))
    plan = service.simulate(seed=42, scenario='live',
                            live_snapshot=_snapshot(_observation(city, ban_m - 1)))
    fog = plan['lowVisibilityAvoidance']
    assert fog['banCities'] == 1
    assert fog['padExemptFlights'] == 0, '深灰档不豁免：它的语义就是拒绝'
    blocked = [item for item in plan['flights'] if item.get('reason') == 'WEATHER_BLOCKED']
    assert blocked, '起降点位于深灰内核内的班次必须被拒绝'
    assert all(item['fromCity'] == city['id'] or item['toCity'] == city['id']
               for item in blocked), '只有该城的班次该被关'

