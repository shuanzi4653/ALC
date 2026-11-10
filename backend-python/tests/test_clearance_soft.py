# -*- coding: utf-8 -*-
"""净空三层（W2 · L-A/L-B/L-C）的判据。

红线：默认口径 `clearance=off` 下，`2848 / 8 班 / 320 min` 一个都不能变。
所以这里先钉 k=0 的不变性，再钉 k>0 的"只在新开关下生效"。

四组断言：
1. `route()` 带不带净空参数、在 `penalty_weight=0.0` 下路径逐字节相同；
2. `penalty_weight>0` 时路径仍接在同一个起终点上，且净空内长度下降；
3. 台账默认 `off`：`penaltyWeight=0`、before 与 after 相等、核心禁飞 0 条；
4. `simulate()` 的 `clearance` 形参默认 `'off'`（调用侧不传就等于没开）。
"""
import os
import sys

import pytest
from shapely.geometry import LineString, Point, box

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from traffic import service as traffic_service  # noqa: E402
from traffic import zones as fixed_zones  # noqa: E402
from traffic.routing import route  # noqa: E402


def _corridors():
    return [item for item in traffic_service.network()['routes'] if item.get('path')][:12]


def test_route_penalty_zero_weight_is_identity():
    """k=0：带净空几何但权重为 0，路径必须与不带参数时完全相同。"""
    geometry = fixed_zones.envelope(fixed_zones.PROHIBITED)
    for item in _corridors():
        allowed = traffic_service._allowed_for_route(item, traffic_service.network())
        start, end = item['path'][0], item['path'][-1]
        baseline = route(start, end, allowed)
        softened = route(start, end, allowed, None,
                         penalty_geometry=geometry, penalty_weight=0.0,
                         exempt_radius_m=8000.0)
        assert softened == baseline, item['id']


def test_route_penalty_avoids_zone_and_keeps_endpoints():
    """k>0：净空内航段长度下降，起终点不动。"""
    allowed = box(0.0, 0.0, 20000.0, 20000.0)
    start, end = (1000.0, 10000.0), (19000.0, 10000.0)
    zone = Point(10000.0, 10000.0).buffer(3000.0, quad_segs=8)
    plain = route(start, end, allowed)
    assert plain is not None
    inside_plain = LineString(plain).intersection(zone).length
    assert inside_plain > 1000.0  # 直连确实穿区，否则这条用例没有意义
    softened = route(start, end, allowed, None,
                     penalty_geometry=zone, penalty_weight=60.0,
                     exempt_radius_m=500.0)
    assert softened is not None
    line = LineString(softened)
    assert line.intersection(zone).length < inside_plain
    assert tuple(softened[0]) == start and tuple(softened[-1]) == end


def test_route_penalty_exempt_zone_is_not_penalised():
    """起降段豁免：起点所在净空挖掉后，同样参数下等于没开。"""
    allowed = box(0.0, 0.0, 20000.0, 20000.0)
    start, end = (1000.0, 10000.0), (19000.0, 10000.0)
    zone = Point(1000.0, 10000.0).buffer(4000.0, quad_segs=8)
    baseline = route(start, end, allowed)
    exempted = route(start, end, allowed, None,
                     penalty_geometry=zone, penalty_weight=60.0,
                     exempt_radius_m=0.0, penalty_exempt=zone)
    assert exempted == baseline


def test_clearance_ledger_off_keeps_baseline_values():
    """默认台账：不带代价、before 等于 after、核心禁飞 0 条。"""
    ledger = traffic_service.clearance_ledger('off')
    assert ledger['mode'] == 'off'
    assert ledger['penaltyWeight'] == 0.0
    assert ledger['inZoneSegmentKm']['before'] == ledger['inZoneSegmentKm']['after']
    assert ledger['coreProhibitedCrossings'] == 0
    assert ledger['reroutedCorridors'] == 0


def test_clearance_switch_defaults_off():
    """L-C 开关：`simulate()` 不传 clearance 就是 off。"""
    import inspect
    params = inspect.signature(traffic_service.simulate).parameters
    assert 'clearance' in params
    assert params['clearance'].default == 'off'
    plan_params = inspect.signature(traffic_service._plan_trajectory).parameters
    assert plan_params['clearance'].default == 'off'


@pytest.mark.skipif(os.environ.get('ALC_SLOW') != '1',
                    reason='需要先算一份完整运行计划（数分钟），设 ALC_SLOW=1 才跑')
def test_counterfactual_baseline_snapshot_unchanged():
    """红线：k=0 时 2848 架次绕飞 / 8 班 / 320 分钟逐字段不变。"""
    from traffic import v2 as traffic_v2
    payload = traffic_v2.counterfactual(seed=42, scenario='live', policy='balanced',
                                        case_id='fog-20250105')
    handled = payload['b']
    assert handled['rerouted'] == 2848
    assert handled['delayedFlights'] == 8
    assert handled['delayMinutes'] == 320
    assert payload['a']['exposure'] == 2640
    assert handled['exposure'] == 0
