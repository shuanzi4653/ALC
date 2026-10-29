"""The planner must avoid what the map paints as a restriction.

Reported 2026-09-24: the virtual demo drew dense no-fly clouds while every
flight flew straight through them, because ``routing`` never saw the radar. The
fix folds radar reflectivity (>=35 dBZ) into the plan's avoidance geometry and
reports what it did in ``radarAvoidance``. These tests pin that contract.

The stratiform tier is the negative case and matters as much as the positive
one: 15-35 dBZ is rain an aircraft flies through, and letting it into the
avoidance set is exactly the "low-grade echo banned everything" confusion the
user reported. A single strong cell must route; a field of drizzle must not.
"""
import inspect
import json
import re
from pathlib import Path

import pytest
from shapely.geometry import GeometryCollection, LineString, Point, box

from traffic import radar_field, routing, service, weather_control, weather_sim
from tests.test_radar_payload import INSIDE_CELLS, _frame

STRONG = (INSIDE_CELLS[0][0], INSIDE_CELLS[0][1], 50.0)
CONVECTIVE = (INSIDE_CELLS[1][0], INSIDE_CELLS[1][1], 40.0)
STRATIFORM = (INSIDE_CELLS[2][0], INSIDE_CELLS[2][1], 25.0)
QUIET = (INSIDE_CELLS[3][0], INSIDE_CELLS[3][1], 8.0)


# ``_build_entry`` is what ``service.session`` hands to the pool, and its tail is
# what the tests below want to inspect. Read the arguments **by name**.
#
# Why not ``submitted[0][-1]``: that used to mean "the weather mode", and it did
# until ``_build_entry`` gained a trailing ``workspace`` parameter. ``[-1]`` then
# silently started reading the workspace (``''``) instead of the channel -- two
# ordinary strings, so nothing raised; the assertion simply compared the wrong
# slot and the tests failed with a message about the weather channel that was, in
# fact, about the workspace. By name it either finds the parameter or raises
# KeyError, which is the failure a reader can act on.
_BUILD_ENTRY_PARAMS = tuple(inspect.signature(service._build_entry).parameters)


def submitted_arg(call, name):
    """One argument out of a recorded ``POOL.submit(_build_entry, ...)`` call.

    ``call[1:]`` drops the function object that ``submit`` receives first.
    """
    return dict(zip(_BUILD_ENTRY_PARAMS, call[1:]))[name]


# The rule block, retyped here **on purpose**. Every other copy of these numbers
# is a read from whichever module owns it, so nothing in the product can drift;
# this is the one place they are written out again, which is what makes a silent
# change to a threshold -- or to the separation standard the clipping depth is
# taken from -- fail loudly instead of quietly re-cutting the tiers the interface
# claims to be using.
RULE = {'tiers': 'CONVECTIVE_AND_STRONG', 'bandFloorDbz': 15.0,
        'convectiveDbz': 35.0, 'strongDbz': 45.0,
        'coreInsetM': 9000.0, 'penetrationM': 250}


@pytest.fixture
def frame_for(monkeypatch):
    """Point the radar frame source at a canned frame for one test.

    **两条通道各有一个取帧入口，这里两个都要钉。** 实测通道经
    ``weather_control.radar_frame``；虚拟通道**不经它** —— ``_virtual_radar_derived``
    直接调生成器。这不是实现细节：它经一个会解析活开关的访问器走过一遭，就是 2026-10-15
    那次"预建虚拟通道的计划却拿到实测帧"的成因。只钉前者，虚拟通道的用例会静默地用上真
    生成器 —— 而它恰好总是返回可用帧，于是用例仍然是绿的，只是量的是另一件事。
    """
    def install(entries, mode='measured', available=True, error=None):
        base = _frame(entries)
        base.update({'mode': mode, 'available': available, 'error': error})
        if mode == 'virtual':
            # 生成器的帧带合成章：``_virtual_radar_sweep`` 的通道自检认的就是它。
            base['provenance'] = {**base['provenance'], 'synthetic': True,
                                  'provider': 'SYNTHETIC_RADAR'}
        monkeypatch.setattr(weather_control, 'radar_frame', lambda **kwargs: base)
        monkeypatch.setattr(weather_sim, 'frame', lambda **kwargs: base)
        # ``*a, **k`` because the real ``mode()`` / ``seed()`` take an optional
        # workspace and ``is_virtual()`` passes it positionally. A zero-arg stub
        # reads fine until a code path calls it that way, then the test fails
        # with a TypeError that says nothing about the behaviour under test.
        monkeypatch.setattr(weather_control, 'mode', lambda *a, **k: mode)
        monkeypatch.setattr(weather_control, 'seed', lambda *a, **k: 42)
        service._virtual_radar_derived.cache_clear()
        service._virtual_radar_samples.cache_clear()
        # Both per-build memos, not just the window one. Their keys are the 5-minute
        # window pair and the tier, *not* the sample tuple, so a stale entry from a
        # previous test's canned frame would be handed back for the same window --
        # and the eroded one would carry the previous frame's storm shape into a
        # test that installed a different sky.
        service._RADAR_WINDOW_CACHE.clear()
        service._RADAR_ERODED_CACHE.clear()
    return install


def test_clear_and_unknown_never_avoid_radar():
    """`clear` claims no adverse weather; `unknown` claims no usable source.

    Either way a radar-driven detour would contradict the scenario's own
    statement, so the radar is excluded and the record says why.

    The expected dict is stated **in full**, including the rule block, rather
    than checked key by key: a subset check would stay green if some later
    change quietly attached geometry or an ``included: True`` to a scenario that
    declares no weather -- which is the one thing this record exists to deny.
    """
    for scenario in ('clear', 'unknown'):
        geometry, info = service._radar_avoidance(scenario)
        assert isinstance(geometry, GeometryCollection) and geometry.is_empty
        assert info == {'included': False, 'reason': 'SCENARIO_DOES_NOT_DECLARE_WEATHER',
                        **RULE}


def test_every_plan_states_the_rule_the_avoidance_geometry_was_cut_by(frame_for):
    """`radarAvoidance.rule` is a declaration, so it is published on every branch.

    The positive branches (`measured` field present, `virtual` sweep) matter, but
    so do the negative ones: a reader who only ever sees the rule when a storm
    exists would reasonably conclude the rule appears because of the storm. These
    six numbers describe how the tiers are cut, not what the sky is doing.

    Three of them were previously **unreadable from the payload** -- the payload
    carried `coreAreaKm2` / `cautionAreaKm2` / `watchAreaKm2`, three areas whose
    dividing lines were stated only in prose. Areas without their thresholds are
    an assertion, not evidence.
    """
    for scenario in ('clear', 'unknown'):
        _geometry, info = service._radar_avoidance(scenario)
        assert {key: info[key] for key in RULE} == RULE, scenario
    frame_for([STRONG], mode='measured')
    assert {key: service._radar_avoidance('live')[1][key] for key in RULE} == RULE
    frame_for([QUIET], mode='measured')
    assert {key: service._radar_avoidance('live')[1][key] for key in RULE} == RULE
    frame_for([], available=False, error='no frame')
    assert {key: service._radar_avoidance('live')[1][key] for key in RULE} == RULE


def test_the_published_rule_matches_the_constants_that_actually_cut_the_tiers():
    """The published numbers must be **reads**, not a second copy.

    If someone retypes `35` as a literal in `_radar_rule_block`, the payload keeps
    saying 35 while `cma_tiles.CONVECTIVE_DBZ` moves -- and the interface would go
    on quoting a threshold the classifier no longer uses. Comparing against the
    owning objects is what catches that, so the comparison is against the modules
    rather than against the numbers repeated in this file.
    """
    from traffic import cma_tiles
    block = service._radar_rule_block()
    assert block['bandFloorDbz'] == cma_tiles.ECHO_FLOOR_DBZ
    assert block['convectiveDbz'] == cma_tiles.CONVECTIVE_DBZ
    assert block['strongDbz'] == cma_tiles.STRONG_DBZ
    # The core inset is the shield's own default: the published value and the
    # value the geometry is actually built with must be the same object of truth.
    assert block['coreInsetM'] == radar_field.shield.__defaults__[2] == radar_field.CORE_INSET_M
    # The clipping depth is the declared horizontal separation; this project does
    # not introduce a second standard for storm contours.
    assert block['penetrationM'] == service.profiles()['separation']['horizontalM']
    # And the band edges the block reports are the ones `radar_field` classifies
    # with, so "≥35 dBZ" in the payload and "CONVECTIVE" in the classifier cannot
    # come apart.
    edges = {name: (low, high) for name, low, high in radar_field.BAND_EDGES}
    assert edges['CONVECTIVE'][0] == block['convectiveDbz']
    assert edges['STRONG'][0] == block['strongDbz']


def test_a_strong_echo_enters_the_avoidance_geometry(frame_for):
    frame_for([STRONG], mode='measured')
    geometry, info = service._radar_avoidance('live')
    assert not geometry.is_empty
    assert info['included'] is True
    assert info['areaKm2'] > 0
    assert info['tiers'] == 'CONVECTIVE_AND_STRONG'
    assert info['slot'] == '2026-09-18T07:18:00Z'
    assert info['mode'] == 'measured'


def test_a_convective_ring_enters_too(frame_for):
    frame_for([CONVECTIVE])
    geometry, info = service._radar_avoidance('live')
    assert not geometry.is_empty
    assert info['included'] is True


def test_stratiform_echo_is_shown_but_never_avoids(frame_for):
    """15-35 dBZ is rain you fly through: the WATCH tier stays out of routing."""
    frame_for([STRATIFORM])
    geometry, info = service._radar_avoidance('live')
    assert geometry.is_empty
    assert info['included'] is False


def test_a_quiet_frame_avoids_nothing(frame_for):
    frame_for([QUIET])
    geometry, info = service._radar_avoidance('live')
    assert geometry.is_empty
    assert info['included'] is False


def test_an_unavailable_radar_excludes_itself_without_failing_the_plan(frame_for):
    """A failed source degrades to an empty envelope with a stated reason.

    Never a partial geometry, never an exception: the plan must still build,
    and ``radarAvoidance`` must say the radar took no part in it.
    """
    frame_for([], available=False, error='最近 12 个时次均不可用：HTTP 404')
    geometry, info = service._radar_avoidance('live')
    assert geometry.is_empty
    assert info['included'] is False
    assert info['reason'] == 'RADAR_UNAVAILABLE'
    assert 'HTTP 404' in info['detail']


def test_the_virtual_frame_is_labelled_as_what_it_is(frame_for, monkeypatch):
    """A synthetic frame drives routing only under its own honest label.

    观察的是**生成器**收到的时次：虚拟通道的取帧入口就是它（``_virtual_radar_derived``
    直接调 ``weather_sim.frame``，理由见那条函数的文档串）。钉在 ``radar_frame`` 上的话，
    这条用例会在虚拟路径改直连之后静默地记录零个时次 —— 而它唯一的断言就是"跨了多个时次"。
    """
    seen_slots = []

    def recording_frame(**kwargs):
        seen_slots.append(kwargs.get('slot'))
        frame = _frame([STRONG]) | {'mode': 'virtual'}
        frame['provenance'] = {**frame['provenance'], 'synthetic': True}
        return frame

    monkeypatch.setattr(weather_sim, 'frame', recording_frame)
    monkeypatch.setattr(weather_control, 'mode', lambda *a, **k: 'virtual')
    monkeypatch.setattr(weather_control, 'seed', lambda *a, **k: 42)
    service._virtual_radar_derived.cache_clear()
    service._virtual_radar_samples.cache_clear()
    samples, info = service._radar_avoidance('live')
    assert isinstance(samples, tuple) and samples
    assert info['mode'] == 'virtual'
    assert len(seen_slots) >= 2, '扫掠必须跨多个时次，否则回波在计划窗口内不动'


def test_a_virtual_sweep_that_lost_the_generator_refuses_the_geometry(monkeypatch):
    """通道自检：虚拟扫掠拿到的帧没有合成章 ⇒ 拒绝这份几何并点名真正的原因。

    这是 2026-10-15 那次失效的**负向对照**。当时的形状是：虚拟分支去问了一个会解析活
    开关的访问器，于是拿到实测帧；实测源对云端出口整站 403，49 个时次全部退化，而计划
    报的是 ``RADAR_UNAVAILABLE`` —— 一句听起来很合理的弃权，把"取帧走了别的通道"盖住了。
    自检在**没有**那场故障的时候也必须能红：这里用一帧"取得到、但没有合成章"的帧来制造
    同一个形状，断言的是那句真话，而不是那句弃权。
    """
    def measured_looking_frame(**kwargs):
        return _frame([STRONG]) | {'mode': 'virtual', 'available': True}

    monkeypatch.setattr(weather_sim, 'frame', measured_looking_frame)
    monkeypatch.setattr(weather_control, 'mode', lambda *a, **k: 'virtual')
    monkeypatch.setattr(weather_control, 'seed', lambda *a, **k: 42)
    service._virtual_radar_derived.cache_clear()
    service._virtual_radar_samples.cache_clear()

    samples, info = service._radar_avoidance('live')
    assert samples.is_empty, '取帧没有走生成器时不能把别人的回波当虚拟回波用'
    assert info['included'] is False
    assert info['reason'] == 'VIRTUAL_FRAME_NOT_SYNTHETIC', \
        '把"取错了通道"报成"回波不可用"，就等于用一句弃权盖住真正的原因'
    assert info['reason'] != 'RADAR_UNAVAILABLE'


def test_shield_output_matches_what_the_avoidance_uses(frame_for):
    """The avoidance geometry is the shield's FIELD tier, nothing invented.

    Cross-checked against ``radar_field.shield`` directly, so the planner and
    the map cannot drift apart: both consume the same derived tiers.
    """
    frame_for([STRONG, CONVECTIVE, STRATIFORM])
    geometry, _info = service._radar_avoidance('live')
    frame_result = weather_control.radar_frame()
    derived = radar_field.derive(frame_result, minute=0)
    field, _core, _caution, watch = radar_field.shield(derived)
    assert not field.is_empty
    assert not watch.is_empty  # the stratiform cell is drawn, just not avoided
    assert geometry.area == pytest.approx(field.area)


def test_virtual_radar_advances_with_the_playback_minute(monkeypatch):
    """0.9.18 regression: the echo used to sit still while the user scrubbed.

    ``radar_regions(minute)`` in virtual mode must derive from the slot at
    SIMULATION_BASE_TIME + minute, so minute 60 and minute 240 pass *different*
    slots to the frame source. The canned frame has a fixed provenance slot, so
    the assertion watches what slot value the generator actually receives --
    that is the input the advection model keys on, and it is the thing the old
    bug froze (wall clock instead of base+minute).

    钉的是生成器而不是 ``weather_control.radar_frame``：虚拟通道的取帧入口就是生成器
    （见 ``_virtual_radar_derived``）。钉在访问器上，这条用例会在取帧改直连之后收到零个
    时次，而以它"必须收到两个不同时次"的断言，那本来是一次应当变红的失败 —— 写在访问器
    上就变成了"没有东西可记录"的静默通过。
    """
    seen = []

    def recording_frame(**kwargs):
        seen.append(kwargs.get('slot'))
        frame = _frame([STRONG]) | {'mode': 'virtual'}
        frame['provenance'] = {**frame['provenance'], 'synthetic': True}
        return frame

    monkeypatch.setattr(weather_sim, 'frame', recording_frame)
    monkeypatch.setattr(weather_control, 'mode', lambda *a, **k: 'virtual')
    monkeypatch.setattr(weather_control, 'seed', lambda *a, **k: 42)
    service._virtual_radar_derived.cache_clear()
    early = service.radar_regions(60)
    late = service.radar_regions(240)
    assert early['available'] and late['available']
    assert len(seen) == 2
    assert seen[0] != seen[1], 'slot 必须随推演分钟推进，否则回波永远不动'
    expected_gap = 180  # minutes
    assert (seen[1] - seen[0]).total_seconds() == expected_gap * 60


def test_virtual_avoidance_returns_per_slot_samples_not_a_swept_union(frame_for):
    """M25 regression: the swept union of the whole window closed all 7760 flights.

    A storm on one corridor at one hour plus another storm elsewhere at another
    hour must not become "weather everywhere, always". The planner unions only
    the samples inside each flight's own window, so `_radar_avoidance` hands
    back the sample tuple, not one big geometry.
    """
    frame_for([STRONG], mode='virtual')
    samples, info = service._radar_avoidance('live')
    assert isinstance(samples, tuple) and samples, '虚拟模式应返回逐 slot 样本'
    assert info['mode'] == 'virtual'
    # A window that covers no sample must yield an empty union -- that is the
    # whole point of per-window avoidance.
    empty = service._radar_window_union(samples, start=10_000, end=10_060)
    assert empty.is_empty


def test_the_sweep_stride_keeps_up_with_the_display_cadence(frame_for):
    """The planner's sampling must not lag what the map redraws (ISS-0.9.24-02).

    This used to read ``assert info['sweepStrideMinutes'] >= 30``, i.e. the guard
    asserted the stride was **coarse** -- it defended the defect. 0.9.24 measured the
    consequence: with a 60-minute stride the planner assumed the echo held still for
    an hour while the workbench redrew it every 2 minutes, the union of two samples
    left a gap roughly one storm wide, and a route dodging both samples ran down the
    middle of it -- 134 aircraft-minutes inside a painted 禁止进入 core.

    A one-sided ``>=`` bound is what made that possible: it passes for 60, for 600
    and for "never sample again". The contract has to name the cadence the stride is
    bound to, which is why the bound is now expressed in display buckets rather than
    as a bare number.
    """
    frame_for([STRONG], mode='virtual')
    _samples, info = service._radar_avoidance('live')
    stride = info['sweepStrideMinutes']

    assert stride % service.DISPLAY_BUCKET_MINUTES == 0, (
        '步长应是显示节奏的整数倍，否则两次采样会跨在显示桶的两侧'
    )
    limit = service.DISPLAY_BUCKET_MINUTES * service.RADAR_SWEEP_LAG_BUCKETS
    assert stride <= limit, f'步长 {stride} 超过允许滞后 {limit} 分钟'


def test_the_declared_display_cadence_matches_the_frontend():
    """Bind the two constants that the defect left unbound.

    ``frontend/src/traffic/runtime.js`` owns ``WEATHER_BUCKET_MINUTES`` and Python
    owned the stride; nothing joined them, so "60 vs 2" was invisible to every test
    on both sides. This reads the value out of the JavaScript file and asserts the
    Python declaration still agrees -- a real cross-module contract, not a comment.

    If the frontend cadence is ever changed, this fails on purpose: the stride is
    derived from it, and the planner must be re-measured against the new cadence
    (the dose-response table lives next to RADAR_SWEEP_STRIDE_MINUTES).
    """
    runtime = (Path(__file__).resolve().parents[2]
               / 'frontend' / 'src' / 'traffic' / 'runtime.js')
    if not runtime.exists():
        pytest.skip('前端口径文件不在本检出版本中')
    match = re.search(
        r'export\s+const\s+WEATHER_BUCKET_MINUTES\s*=\s*(\d+)',
        runtime.read_text(encoding='utf-8'),
    )
    assert match, '未能从 runtime.js 解析出 WEATHER_BUCKET_MINUTES'
    assert int(match.group(1)) == service.DISPLAY_BUCKET_MINUTES, (
        '前端的显示节奏与 service.DISPLAY_BUCKET_MINUTES 不一致；'
        '步长由后者推导，两者一旦分叉就会重现 ISS-0.9.24-02'
    )


def test_radar_window_union_measured_mode_passes_geometry_through(frame_for):
    """Measured mode hands the planner one geometry; the window helper must
    return it untouched rather than trying to slice a shapely object."""
    geometry = service._radar_window_union(GeometryCollection(), 0, 60)
    assert isinstance(geometry, GeometryCollection)


def test_the_bbox_shortcut_never_hides_a_real_overlap(frame_for):
    """M29 negative check: the short-circuit must not eat a genuine hit.

    ``_radar_window_union`` now returns on the first sample its probe actually
    intersects, instead of building a union of them all. That rewrite is only
    sound if the probe test is *exact* -- a near-miss must come back empty and a
    real crossing must come back non-empty. A shortcut that answered "clear" for
    a flight cutting through the storm would silently delete the no-fly layer
    from the plan, which is the failure this whole module exists to prevent, so
    both directions are asserted rather than only the convenient one.
    """
    frame_for([STRONG], mode='virtual')
    samples, _info = service._radar_avoidance('live')
    nonzero = [(minute, field) for minute, field, _core in samples if not field.is_empty]
    if not nonzero:
        pytest.skip('该用例构造的样本几何为空，无法验证负向')
    minute, geom = nonzero[len(nonzero) // 2]
    minx, miny, maxx, maxy = geom.bounds
    midy = (miny + maxy) / 2.0

    crossing = LineString([(minx - 5_000, midy), (maxx + 5_000, midy)])
    hit = service._radar_window_union(samples, minute, minute + 30, probe=crossing)
    assert not hit.is_empty, '探针真实穿过回波时，窗口不得被判为净空'
    assert hit.intersects(crossing)

    # The same window, probed far away: must be empty. This is the direction that
    # a sloppy bbox test would get wrong.
    away = LineString([(minx - 5_000_000, midy), (maxx - 5_000_000, midy)])
    clear = service._radar_window_union(samples, minute, minute + 30, probe=away)
    assert clear.is_empty, '探针与回波无交集时，窗口必须判为净空'


def test_a_strong_echo_bends_a_route_and_does_not_close_it(frame_for):
    """回波告警地区必须**改变航路** —— 进避让集合还不够。

    Reported by the user 2026-09-30: 「回波当中告警的地区未实现航路变化」. Every
    test in this file pinned the *set* the planner avoids, and that set was
    correct; what nothing asserted was that a route comes back **changed**. A
    contract about an avoidance set is fully satisfied by a planner that refuses
    every flight, and that is close to what the live build did the day this was
    written: 7760 flights, 2519 closed as WEATHER_BLOCKED, **0 detours**.

    The cause was not here (it was a caution ring in ``PublicWeather.envelope``,
    see tests/test_traffic_live_weather.py) -- but the reason it went unnoticed
    for so long is exactly here: nothing walked the path from "there is a >=35 dBZ
    echo" to "a polyline came back different".

    So this test walks it. Canned echo -> avoidance geometry -> ``route()`` ->
    the returned polyline must exist (不关闭), must stay out of the echo (避让),
    and must be longer than the straight line (绕飞).
    """
    frame_for([STRONG], mode='measured')
    echo, info = service._radar_avoidance('live')
    assert info['included'] is True and not echo.is_empty, '构造用例必须先真的产出回波几何'

    allowed = service.boundary()
    minx, miny, maxx, maxy = echo.bounds
    midy = (miny + maxy) / 2.0
    span = max(maxx - minx, maxy - miny)
    start, end = (minx - span, midy), (maxx + span, midy)
    assert allowed.covers(Point(start)) and allowed.covers(Point(end)), \
        '本用例的起终点必须落在作业区内，否则测的是边界而不是回波'

    straight = LineString([start, end])
    assert straight.intersects(echo), '构造用例：直线必须先真的穿过回波'

    # Baseline: with nothing to avoid, routing returns the direct two-point line.
    direct = service.route(start, end, allowed, GeometryCollection())
    assert direct is not None

    bent = service.route(start, end, allowed, echo)
    assert bent is not None, '回波挡路时必须还能绕出去，而不是把航班关掉'
    path = LineString(bent)
    assert not path.intersects(echo), '绕行后的航迹不得进入回波'
    assert path.length > straight.length, '航路必须真的变长，否则没有发生绕飞'


def test_a_storm_over_the_pad_is_an_honest_closure_not_a_silent_one(frame_for):
    """The negative direction of the test above.

    "Must not close" cannot mean "never closes": a >=35 dBZ echo covering a
    flight's own departure point is exactly the case where no path exists, and
    ``route()`` says so rather than inventing one. Asserted here so the fix above
    is never read as "make routing ignore the echo".
    """
    frame_for([STRONG], mode='measured')
    echo, _info = service._radar_avoidance('live')
    assert not echo.is_empty
    inside = Point(echo.representative_point())
    outside = Point(echo.bounds[0] - 200_000, echo.bounds[1])
    assert service.route((inside.x, inside.y), (outside.x, outside.y),
                         service.boundary(), echo) is None, \
        '起降点在回波内时应当如实返回无路径，而不是安静地画一条穿过去的路'


# ----------------------------------------------------------- the channel contract
#
# Reported by the user 2026-09-30, with a screenshot: aircraft sitting inside a
# painted restricted area and no detour anywhere. Every test above passed at the
# time, and every one of them was right -- the router was avoiding everything it
# was given. The plan had been built against the **measured** echo, whose ban tier
# was empty and whose field did not reach 吉林 at all; the map was drawing the
# **virtual** echo, which covered that province. Two channels, one screen.
#
# So what these tests pin is not a geometry rule but an identity rule: the plan
# and the picture must name the same channel, and a mismatch must be visible in
# the payload rather than expressed as aircraft parked in a no-fly area.

def test_the_weather_channel_is_part_of_the_key_a_plan_is_stored_under():
    """Without this the switch is cosmetic on the plan side: same key, same file."""
    measured = service.identity(42, 'live', 'snap-1', weather_control.MODE_MEASURED)
    virtual = service.identity(42, 'live', 'snap-1', weather_control.MODE_VIRTUAL)
    assert measured != virtual, \
        '两个通道共用同一把钥匙：切换气象通道后重新调度会命中另一通道的计划'
    # And the key is still a pure function of its inputs, or caching is unsound.
    assert service.identity(42, 'live', 'snap-1', weather_control.MODE_MEASURED) == measured


def test_the_key_follows_the_switch_when_the_caller_does_not_pass_a_channel():
    """The default is the live switch, read at call time -- not a frozen import."""
    weather_control.reset()
    try:
        before = service.identity(42, 'clear', None)
        weather_control.set_mode(weather_control.MODE_VIRTUAL)
        after = service.identity(42, 'clear', None)
        assert before != after, '未显式传通道时，钥匙没有跟随开关变化'
    finally:
        weather_control.reset()


def test_switching_the_channel_does_not_hand_back_the_other_channels_plan(monkeypatch, tmp_path):
    """The reported symptom, at the level the session actually decides it.

    ``session()`` is the one place that picks a plan for a request. If it returns
    the in-flight or on-disk plan built for the other channel, the operator gets a
    routing answer about a world the map is not showing -- which is precisely how
    "有飞机在禁飞区、没有绕行" happens with a router that is working correctly.
    """
    submitted = []

    class Recorder:
        def submit(self, *args):
            submitted.append(args)

    monkeypatch.setattr(service, 'STORE', tmp_path)
    monkeypatch.setattr(service, 'POOL', Recorder())
    saved = dict(service.JOBS)
    weather_control.reset()
    try:
        service.JOBS.clear()
        first = service.session(42, 'clear')
        assert first['status'] == 'BUILDING'
        assert submitted_arg(submitted[0], 'weather_mode') == weather_control.MODE_MEASURED, \
            '构建没有拿到本次请求的通道'

        weather_control.set_mode(weather_control.MODE_VIRTUAL)
        second = service.session(42, 'clear')
        assert second['status'] == 'BUILDING', \
            '切换通道后返回了一个已经存在的计划，而不是重建'
        assert second['sessionId'] != first['sessionId'], \
            '切换通道后拿到了另一通道的计划'
        assert submitted_arg(submitted[1], 'weather_mode') == weather_control.MODE_VIRTUAL
    finally:
        weather_control.reset()
        with service.LOCK:
            service.JOBS.clear()
            service.JOBS.update(saved)


def test_a_stored_plan_is_refused_when_its_channel_is_not_the_current_one(monkeypatch, tmp_path):
    """Key equality is not sufficient, and the redundant check is the reason.

    The key is derived from the *request*; this reads what the file *contains*. A
    store restored from a backup, or a build interrupted right after the switch,
    satisfies the current key while holding the other channel's plan -- the one
    failure this whole contract exists to remove. The check is asserted by writing
    exactly that file.
    """
    submitted = []

    class Recorder:
        def submit(self, *args):
            submitted.append(args)

    monkeypatch.setattr(service, 'STORE', tmp_path)
    monkeypatch.setattr(service, 'POOL', Recorder())
    saved = dict(service.JOBS)
    weather_control.reset()
    try:
        service.JOBS.clear()
        weather_control.set_mode(weather_control.MODE_VIRTUAL)
        key = service.identity(42, 'clear', None, weather_control.MODE_VIRTUAL)
        # Correct fingerprint and plan revision, current key -- and the wrong channel.
        (tmp_path / f'{key}.json').write_text(json.dumps({
            'status': 'READY', 'sessionId': key,
            'fingerprint': service.FINGERPRINT, 'planRevision': service.PLAN_REVISION,
            'weatherMode': weather_control.MODE_MEASURED,
        }), encoding='utf-8')

        result = service.session(42, 'clear')
        assert result['status'] == 'BUILDING', \
            '磁盘上另一通道的计划被当成本次请求的命中复用了'
        assert submitted and submitted_arg(submitted[0], 'weather_mode') == weather_control.MODE_VIRTUAL
    finally:
        weather_control.reset()
        with service.LOCK:
            service.JOBS.clear()
            service.JOBS.update(saved)


def test_a_frame_from_the_other_channel_is_refused_rather_than_avoided(frame_for):
    """The controller reads the live switch, so a flip mid-build can hand back the
    other channel's frame.

    Refusing it costs the radar's part in this one plan and says so in
    ``radarAvoidance.reason``. Accepting it would build a plan whose key names one
    channel and whose avoidance set came from the other -- the contradiction this
    change removes, and the only one an operator cannot see.
    """
    frame_for([STRONG], mode=weather_control.MODE_VIRTUAL)
    geometry, info = service._radar_avoidance('live', weather_control.MODE_MEASURED)
    assert geometry.is_empty, '构建期间换了通道，本计划不得使用新通道的回波'
    assert info['included'] is False
    assert info['reason'] == 'CHANNEL_CHANGED_DURING_BUILD'
    assert info['mode'] == weather_control.MODE_MEASURED
    assert weather_control.MODE_VIRTUAL in info['detail']

    # The negative direction: the same frame is *not* refused under its own
    # channel, or the guard above would be satisfied by refusing everything.
    # Virtual mode hands back per-slot samples, so the shape of the good answer is
    # a non-empty tuple, not a geometry.
    samples, info = service._radar_avoidance('live', weather_control.MODE_VIRTUAL)
    assert isinstance(samples, tuple) and samples
    assert info['included'] is True
    assert info['mode'] == weather_control.MODE_VIRTUAL


# ------------------------------------------------------------ the two colours
#
# The second half of the operator's 2026-09-30 message: 「强化绕行逻辑，只要有合适的
# 窗口就可以飞，哪怕路线稍微极限一些也无所谓」. The legend paints two colours and names
# them differently -- the >=45 dBZ core is 禁止进入, the 35-45 dBZ band is 须绕飞 --
# and until 0.9.22 the planner gave both one rule, because both went into the same
# hard obstacle set. In that set touching *is* refusal and a pad inside it is
# inescapable, so a corridor grazing a storm edge by a metre was priced exactly
# like one cutting through the core: 1390 flights closed as WEATHER_BLOCKED
# against 43 detours on the virtual build.
#
# The two tiers are now consumed by different rules -- the hard one may not be
# touched at all, the tolerant one may be clipped by at most `penetration_m` from
# its edge -- and these three tests pin the relation between them rather than
# either shape on its own.
#
# The direction of that second rule is easy to get backwards, and was: the first
# version of this change documented erosion as "forbids entering at all", which is
# the opposite of what `buffer(-depth)` computes. What caught it was measuring a
# finished plan against the painted geometry (``_probe_plan_vs_echo.py``: 48 of
# 7663 flight/sample pairs inside the band), not reading the code. Every assertion
# below is therefore written to state the direction it is testing.


def _tier_samples(field, core, minutes=(0,)):
    """A synthetic `(minute, field, core)` tuple.

    ``_radar_window_union`` accepts any such sequence, and building the boxes by
    hand is what makes the assertions below *strict*: the thing being tested is
    the relation between the two tiers, and a relation asserted against whatever
    ``shield`` happens to produce at a pinned slot is an assertion about a sample,
    not about the code (M39).
    """
    return tuple((minute, box(*field), box(*core)) for minute in minutes)


def test_the_core_tier_is_inside_the_field_tier():
    """The core must be a strict subset of the field it sits in.

    Asserted rather than left implicit because the two tiers now feed two
    different rules, so the old failure would return in a new shape: the map fills
    the field and strokes the core, so a core *outside* its field is geometry the
    operator cannot see while the planner still refuses to enter it. That is the
    "layer exists, carries geometry, cannot be seen" defect this file was written
    for, one level down.
    """
    samples = _tier_samples(field=(0.0, 0.0, 10_000.0, 10_000.0),
                            core=(2_000.0, 2_000.0, 8_000.0, 8_000.0))

    view = service._radar_window_union(samples, 0, 60, tier='field')
    ban = service._radar_window_union(samples, 0, 60, tier='core')

    assert not view.is_empty and not ban.is_empty
    assert view.covers(ban), '禁止进入层必须落在须绕飞层之内，否则图上不可见却被规划拒绝'
    assert ban.area < view.area, '核心层必须严格更小，否则两个颜色是同一个集合'
    # The default tier is the field, which is what keeps every pre-0.9.22 caller
    # -- and the measured branch, which has one geometry and no tiers at all --
    # on exactly the meaning they had.
    assert service._radar_window_union(samples, 0, 60).equals(view)


def test_the_window_union_keeps_every_sample_a_probe_crosses():
    """The router needs the window's echo *set*, not the first sample it touched.

    ``_radar_window_union`` used to return on the first sample the probe hit, on
    the grounds that the union was only ever an intermediate. That is sound for a
    yes/no question and unsound for the router: a detour computed against sample 1
    alone may still cross sample 3, and the plan then ships a path through painted
    echo -- silently, because the final check used the same first-hit shortcut.

    The samples are placed so the probe crosses the first and the last and misses
    the middle, which is the only arrangement that separates "the first hit" from
    "every hit". Both directions are asserted, so the fix cannot be satisfied by
    returning a union of everything in the window either.
    """
    first = (0.0, 0.0, 100.0, 100.0)
    middle = (1_000.0, 0.0, 1_100.0, 100.0)
    last = (2_000.0, 0.0, 2_100.0, 100.0)
    samples = tuple((minute, box(*geometry), box(*geometry))
                    for minute, geometry in ((0, first), (60, middle), (120, last)))

    # Right through the two outer samples; the middle one sits inside the probe's
    # own bounding box, so only the exact predicate can exclude it.
    probe = LineString([(50.0, 500.0), (50.0, -500.0),
                        (2_050.0, -500.0), (2_050.0, 500.0)])
    hit = service._radar_window_union(samples, 0, 120, probe=probe)

    assert not hit.is_empty, '探针穿过样本时窗口不得为空'
    assert hit.intersects(box(*first)), '窗口丢失了探针确实穿过的第一个样本'
    assert hit.intersects(box(*last)), '窗口丢失了探针确实穿过的最后一个样本'
    assert not hit.intersects(box(*middle)), '窗口混进了探针并未穿过的样本'
    # And the bbox gate still short-circuits: a probe nowhere near the window is
    # empty even though the window itself is not.
    away = LineString([(50.0, 500_000.0), (2_050.0, 500_000.0)])
    assert service._radar_window_union(samples, 0, 120, probe=away).is_empty


def test_a_window_landing_between_two_samples_gets_both_of_them(clean_windows):
    """The window union must bracket the window on **both** sides (ISS-0.9.34-01).

    ``_radar_window_union`` has always said it considers "samples bracketing the
    flight's own [start, end]". The filter said ``sample_offset <= floor5(end)``,
    which only ever looks backwards -- so a flight whose whole window sits between
    two samples was planned against the *previous* sample alone, and the bracket
    at its arrival minute was dropped.

    Measured consequence (``tools/probes/_probe_flight_vs_echo_timeline.py``, seed
    42, virtual): 31 of 35 field-layer incursions were deeper than the 250 m
    allowance, the deepest 13.5 km, and in every one of them a sweep sample
    already contained the aircraft -- the geometry was in hand and the window
    filter threw it away. So this is the case that has to stay pinned.

    Both directions are asserted, because "union everything in sight" would also
    satisfy the positive half: a window that *ends on* a sample must not drag in
    the following one.
    """
    early = box(0.0, 0.0, 100.0, 100.0)
    arrival = box(1_000.0, 0.0, 1_100.0, 100.0)
    later = box(2_000.0, 0.0, 2_100.0, 100.0)
    samples = tuple((minute, geometry, geometry)
                    for minute, geometry in ((110, early), (120, arrival), (140, later)))

    # Window entirely between the 110 and 120 samples -- the shape that lost data.
    window = service._radar_window_union(samples, 115, 118.9)
    assert window.intersects(arrival), \
        '窗口落在两个样本之间时，到达时刻那一侧的样本被丢掉了（修复前的行为）'
    assert window.intersects(early), '窗口也不得丢掉起点那一侧的样本'
    assert not window.intersects(later), '窗口不得并进更后面那个样本'

    # Negative control on a **different** key, so it is a fresh lookup rather than
    # the memo above: a window ending at 130 brackets sample 120 and nothing else.
    # Without this, "return the union of every sample" passes the assertions above.
    tail = service._radar_window_union(samples, 125, 130)
    assert tail.intersects(arrival), '窗口应以它之前的那个样本为界'
    assert not tail.intersects(later), \
        '窗口正好停在某个样本之前时，不得把再下一个样本也并进来'


def test_the_tolerant_rule_is_a_bounded_penetration_and_not_a_clearance():
    """The direction of the tolerant rule, asserted rather than described.

    ``penetration_limit(band, depth)`` erodes: the region a path may not reach is
    the band shrunk by ``depth``, so a path may clip the band's outer shell by up
    to ``depth``. Clearing the band instead (which is the *mirror* rule a
    "clearance" would express, ``buffer(+depth)``) would be strictly stronger, and
    confusing the two is the defect this test exists for: the first version of
    this change documented the rule as "forbids entering at all" while computing
    the opposite, and no reading of the code caught it -- measuring the finished
    plan against the painted band did.

    Both consequences are pinned, because either alone is satisfied by the wrong
    reading: a thick band survives the erosion and so still constrains (its
    interior is forbidden), and a band thinner than ``2 * depth`` erodes away
    entirely and constrains nothing -- which is not a special case but what the
    rule literally says about a footprint narrower than twice the allowance.
    """
    thick = box(0.0, 0.0, 10_000.0, 2_000.0)
    thin = box(0.0, 0.0, 10_000.0, 100.0)

    assert not routing.penetration_limit(thick, 250.0).is_empty, \
        '厚于 2 倍许可深度的层必须存活，否则「禁止深入」这一半就失效了'
    assert routing.penetration_limit(thick, 250.0).area < thick.area, \
        '许可深度必须真的收窄禁区，否则这不是「允许触及外层」而是「禁止触及」'
    assert routing.penetration_limit(thin, 250.0) is None, \
        '薄于 2 倍许可深度的层会被腐蚀干净，此时它不构成约束'
    # Zero depth is the module default and must leave the geometry alone: it is
    # plain avoidance, which is what a caller who names no allowance should get.
    assert routing.penetration_limit(thick, 0.0).equals(thick)
    assert routing.penetration_limit(GeometryCollection(), 250.0).is_empty


def test_a_pad_inside_the_ban_tier_is_inseparable_while_the_band_can_be_grazed(frame_for):
    """The relaxation is in the band, not in the core -- asserted both ways.

    The positive direction walks the same path the planner walks (hard set,
    tolerant set, one allowance) and checks the two guarantees separately: the
    returned line must not touch the ban tier at all, and must not reach deeper
    into the band than the allowance. The negative direction is what keeps the fix
    from being read as "routing now ignores the echo": a pad inside the ban tier is
    still inescapable, exactly as before, because no routing can lift an aircraft
    out of a restriction that contains its own take-off point.
    """
    frame_for([STRONG], mode='measured')
    echo, info = service._radar_avoidance('live')
    assert info['included'] is True and not echo.is_empty, '构造用例必须先真的产出回波几何'

    allowed = service.boundary()
    minx, miny, maxx, maxy = echo.bounds
    midy = (miny + maxy) / 2.0
    span = max(maxx - minx, maxy - miny)
    start, end = (minx - span, midy), (maxx + span, midy)
    assert allowed.covers(Point(start)) and allowed.covers(Point(end)), \
        '本用例的起终点必须落在作业区内，否则测的是边界而不是回波'

    # The ban tier is the band inset by a fixed distance -- the same construction
    # `shield` uses, so the containment below is guaranteed rather than hoped for.
    allowance = 250.0
    core = routing.penetration_limit(echo, 5_000.0)
    assert core is not None and not core.is_empty, '构造用例需要一层真正位于回波内部的禁止层'
    assert echo.covers(core)

    path = service.route(start, end, allowed, core, soft_obstacles=echo,
                         penetration_m=allowance)
    assert path is not None, '回波挡路时必须还能绕出去，而不是把航班关掉'
    line = LineString(path)
    assert not line.intersects(core), '绕行后的航迹进入了禁止进入层'
    assert not line.intersects(routing.penetration_limit(echo, allowance)), \
        '绕行后的航迹侵入了超过许可深度的部分，须绕飞层的约束被穿过了'

    inside = Point(core.representative_point())
    assert service.route((inside.x, inside.y), (end[0], end[1]), allowed,
                         core, soft_obstacles=echo, penetration_m=allowance) is None, \
        '起降点位于禁止进入层内时应当如实返回无路径，而不是安静地画一条穿过去的路'



# ---------------------------------------------------------------------------
# 航路成因（用户 2026-10-03 第 2 条）
# ---------------------------------------------------------------------------
# 用户原话：「他的轨迹我知道是之前的受气象影响的……明明他直飞的路线没有气象干扰
# 为什么不变。」计划里当时没有任何字段能回答"这条航路是为谁而弯的"，于是这里给出
# `routeBasis`。这一组测试钉的是**判据落在哪个几何上**，因为第一版判错了对象：它判
# 了"声明走廊"，而 `route()` 实际规划的是走廊**两端点**之间的最短避障路径，中间航路
# 点根本不参与。判错对象的后果是 7641 班全部报 CLEAR，而同一份计划里有 42 班标着
# `WEATHER_DETOUR` —— 两个各自都"跑完了"的判据给出互相矛盾的结论（M26）。
@pytest.fixture
def clean_windows():
    """Clear the per-build window memos before a test that feeds its own samples.

    Their keys are the 5-minute window pair and the tier, **not** the sample tuple,
    so an entry left behind by another test's canned frame is handed straight back
    for the same window -- and the cases below all use the same window on purpose.
    Without this the "no sample touches the line" case returns the previous test's
    storm, which is a failure that looks like a criterion bug and is not one.
    """
    service._RADAR_WINDOW_CACHE.clear()
    service._RADAR_ERODED_CACHE.clear()
    yield
    service._RADAR_WINDOW_CACHE.clear()
    service._RADAR_ERODED_CACHE.clear()


def _corridor(allowed, bend=0.05):
    """一条带折角的声明走廊，两端点连线就是"直连段"。

    折角是刻意加的：若走廊本身就是直线，"判走廊"与"判直连段"会给出同一个答案，
    这个用例就对那个缺陷完全不敏感（判据必须具备能察觉差异的形状）。
    """
    anchor = allowed.representative_point()
    start = (anchor.x - 0.10, anchor.y)
    end = (anchor.x + 0.10, anchor.y)
    return LineString([start, (anchor.x, anchor.y + bend), end]), start, end


def test_the_route_basis_names_the_constraint_that_bent_the_corridor(clean_windows):
    allowed = service.boundary()
    corridor, start, end = _corridor(allowed)
    empty = GeometryCollection()
    # 挡住直连段的一小块，以及**存在但不在直连段上**的另一小块（负向对照）。
    on_line = box((start[0] + end[0]) / 2 - 0.01, start[1] - 0.01,
                  (start[0] + end[0]) / 2 + 0.01, start[1] + 0.01)
    off_line = box(start[0] - 0.02, start[1] + 0.20, start[0] - 0.01, start[1] + 0.21)

    # ① 什么都没有 → 直飞段可用，而且**没有分钟**（不是 0 分钟）。
    assert service._route_basis(corridor, empty, empty, empty, allowed, 0, 60) == ('CLEAR', None)
    # ② 负向对照：挡块存在、但不在直连段上 —— 仍然必须是 CLEAR。
    #    这一条是"处处报成因"的反面：一个永远能给出成因的判据不携带信息。
    assert service._route_basis(corridor, off_line, empty, empty, allowed, 0, 60) == ('CLEAR', None)
    # ③ 固定管制区
    assert service._route_basis(corridor, on_line, empty, empty, allowed, 0, 60) == ('STATIC_AIRSPACE', None)
    # ④ 点观测派生风险区（envelope）
    assert service._route_basis(corridor, empty, on_line, empty, allowed, 0, 60) == ('POINT_WEATHER', None)
    # ⑤ 四类同时在场 → 报最具体的那个（顺序与规划器 union 的顺序一致）
    samples = ((0, on_line, on_line),)
    assert service._route_basis(corridor, on_line, on_line, samples, allowed, 0, 60) == ('STATIC_AIRSPACE', None)
    assert service._route_basis(corridor, empty, on_line, samples, allowed, 0, 60) == ('POINT_WEATHER', None)
    # ⑥ 雷达两级：内核优先于场。
    #
    # 两个子用例**必须用不同的窗口**：`_radar_window_union` 的记忆键是
    # ``(5 分钟窗口, 分级)``，**不含样本元组**（它自己的 docstring 写明了这一点，
    # 因为样本表是每轮构建的全局量）。同一个窗口喂两份不同的样本，第二次会拿到
    # 第一次的几何 —— 于是"内核"那一格会把"场"的用例答成 RADAR_CORE，而这不是判据
    # 的错，是夹具把两个不同的问题问了同一个键。
    assert service._route_basis(corridor, empty, empty, samples, allowed, 0, 60) == ('RADAR_CORE', 0)
    field_only = ((120, on_line, empty),)
    assert service._route_basis(corridor, empty, empty, field_only, allowed, 120, 180) == ('RADAR_FIELD', 120)
    # ⑦ 作业区边界：把 allowed 收成只剩起点那一小块，直连段就出界了。
    #    这是实测通道里**唯一真正生效**的那一类成因（42 班全中）。
    tight = allowed.intersection(Point(start).buffer(0.005))
    assert service._route_basis(corridor, empty, empty, empty, tight, 0, 60) == ('BOUNDARY', None)
    # ⑧ 成因名必须在闭集里，否则前端会给它配不出名字（静默少一行）。
    for code in ('CLEAR', 'STATIC_AIRSPACE', 'POINT_WEATHER', 'LOW_VISIBILITY',
                 'RADAR_CORE', 'RADAR_FIELD', 'BOUNDARY'):
        assert code in service.ROUTE_BASIS
    # `LOW_VISIBILITY` 必须在**气象族**里，而不只是"某个闭集的成员"。它不在的话，
    # 因为低能见度绕行的班次不会被算进「受气象影响改航」，而屏幕上那一行会照常显示
    # 一个更小的数字 —— 少记的班次不会报错，只会静默变成别的口径。
    # 这里不是把集合放宽，是**两向都钉**（少了要红、多了也要红）：
    assert set(service.WEATHER_BASIS) == {'POINT_WEATHER', 'LOW_VISIBILITY',
                                          'RADAR_CORE', 'RADAR_FIELD'}
    # 反面对照：静态空域与作业区边界**不是**气象。它们混进这一族，就会把
    # "官方管制挡的"和"飞出作业区"一起记成"天气不好"，那是另一个方向的口径错误。
    assert 'STATIC_AIRSPACE' not in service.WEATHER_BASIS
    assert 'BOUNDARY' not in service.WEATHER_BASIS
    assert 'CLEAR' not in service.WEATHER_BASIS


def test_the_first_echo_minute_is_the_first_sample_that_really_touches_the_line(clean_windows):
    """成因的"从第几分钟起"必须取**第一帧真正相交**的样本。

    两条容易写错的地方，各有一个断言：
      * 第 0 分钟**是**一个分钟，不能因为它假值化就被当成"没有分钟"（§五 ⑥ 的同一族坑）；
      * 不相交的样本必须先被跳过，而不是取窗口里的第一帧 —— 后者会让每一班都显示
        "从第 0 分钟起"，那个数字就与"什么时候开始绕"无关了。
    """
    allowed = service.boundary()
    corridor, start, end = _corridor(allowed)
    empty = GeometryCollection()
    midx = (start[0] + end[0]) / 2
    later = box(midx - 0.01, start[1] - 0.01, midx + 0.01, start[1] + 0.01)
    earlier_elsewhere = box(start[0] - 0.30, start[1] - 0.30, start[0] - 0.29, start[1] - 0.29)

    # 第 0 分钟就交上 → 返回 0，而且是 `is not None`（0 与"没有"必须能区分）
    samples = ((0, later, later),)
    basis, minute = service._route_basis(corridor, empty, empty, samples, allowed, 0, 60)
    assert (basis, minute) == ('RADAR_CORE', 0)
    assert minute is not None

    # 不相交的第 0 帧必须被跳过，答案取真正相交的那一帧。窗口换成 (200, 260)，
    # 理由同上：记忆键是窗口不是样本，同一个窗口喂两份样本会互相答对方的问题。
    samples = ((200, earlier_elsewhere, earlier_elsewhere), (220, later, later))
    assert service._route_basis(corridor, empty, empty, samples, allowed, 200, 260) == ('RADAR_CORE', 220)

    # 负向对照：窗口内一帧都不相交 → 不得报成因，更不得报一个分钟。
    samples = ((300, earlier_elsewhere, earlier_elsewhere),)
    assert service._route_basis(corridor, empty, empty, samples, allowed, 300, 360) == ('CLEAR', None)


def test_every_scheduled_flight_carries_a_route_basis_and_the_label_follows_it():
    """最终产物形状的对照（M40）：成因必须真的随计划发出来，而且与 `reason` 一致。

    上面两条测的是纯函数，纯函数对"规划器有没有把它接上、有没有在写出载荷前丢掉"
    完全不敏感。所以这里走一遍真实构建，钉住两件事：
      * 每一个受理班次都带 `routeBasis`，且取值在闭集里（`None` 只属于被关闭的班次）；
      * `reason == 'WEATHER_DETOUR'` 与 `routeBasis ∈ WEATHER_BASIS` **互为充要** ——
        这两句话在屏幕上分属台账与地图，一旦分家，读者会看到"台账说气象改航、地图
        说作业区边界"，而两边都自洽（§八 ⑭）。
    """
    plan = service.simulate(seed=42, scenario='clear')
    flights = plan['flights']
    assert flights, '构建必须真的产出班次，否则下面两条恒真'
    scheduled = [f for f in flights if f['status'] == 'SCHEDULED']
    assert scheduled, '本用例需要一个非空的受理集合'
    for f in scheduled:
        assert f.get('routeBasis') in service.ROUTE_BASIS, f['id']
        assert (f['reason'] == 'WEATHER_DETOUR') == (f.get('routeBasis') in service.WEATHER_BASIS), f['id']
    for f in flights:
        if f['status'] == 'CLOSED':
            assert f.get('routeBasis') is None, f['id']


# ------------------------------- 通道由实参决定，不由活开关决定（2026-10-15 线上）
#
# 操作台上 12 架载具停在禁入区内核里。成因不是一个几何错误，而是"这条路径属于哪个通道"
# 在**下一层**被活开关决定了：``_prewarm_sibling`` 会在还处于实测通道的工作区里预建虚拟
# 通道的计划，于是虚拟扫掠拿到实测帧；实测源对云端出口整站 403，49 个时次全部退化，计划
# 报 ``sweepSlots: 0``。上面那组通道判据全都钉在 ``_radar_avoidance`` 这一层，而**漏洞
# 就在它们下面一层** —— 所以这一节的形状是"把访问器接成一碰就炸"，而不是再看一遍文案。

def test_the_virtual_sweep_never_asks_the_controller_which_channel_is_live(monkeypatch):
    """活开关说"实测"、请求说"虚拟" ⇒ 扫掠仍必须从生成器取帧。

    这就是预建通道（``_prewarm_sibling``）跑的那条路：它在工作区还是实测通道时就把虚拟
    通道的计划先算出来。旧实现走的是一个会解析活开关的访问器，于是拿到实测帧 —— 而在这
    条用例里，那个访问器一碰就炸。它不是"从旁边推断"，是让读了就红。
    """
    calls = []

    def generator(**kwargs):
        calls.append(kwargs)
        frame = _frame([STRONG]) | {'mode': 'virtual'}
        frame['provenance'] = {**frame['provenance'], 'synthetic': True}
        return frame

    def boom(**kwargs):
        raise AssertionError('虚拟通道的取帧走到了会解析活开关的访问器上')

    monkeypatch.setattr(weather_sim, 'frame', generator)
    monkeypatch.setattr(weather_control, 'radar_frame', boom)
    weather_control.reset()
    try:
        weather_control.set_mode(weather_control.MODE_MEASURED)
        service._virtual_radar_derived.cache_clear()
        service._virtual_radar_samples.cache_clear()
        service._RADAR_WINDOW_CACHE.clear()
        service._RADAR_ERODED_CACHE.clear()
        geometry, info = service._radar_avoidance('live', weather_control.MODE_VIRTUAL)
    finally:
        weather_control.reset()

    assert calls, '虚拟扫掠根本没有调用生成器'
    assert info['mode'] == weather_control.MODE_VIRTUAL
    assert info['sweepSlots'] > 0, '预建虚拟计划时扫掠为空 —— 线上失效的形状'
    assert info['included'] is True
    # 虚拟分支交回的是**逐 slot 样本元组**，不是一块几何（M25：整窗并集会把 7760 班
    # 全部关掉）。所以这里量的是"有样本"，不是"几何非空" —— 写成 `geometry.is_empty`
    # 会让这条用例以 AttributeError 变红，而不是以它声称的判据变红。
    assert isinstance(geometry, tuple) and len(geometry) == info['sweepSlots']


def test_a_virtual_sweep_with_no_convective_echo_is_not_reported_as_an_outage(frame_for):
    """「帧都取到了、只是天晴」与「取帧失败」是两件事，下一步动作也相反。

    虚拟通道里 `sweepSlots == 0` 曾经一律报 ``RADAR_UNAVAILABLE``。那是个听起来很合理的
    弃权：它同时盖住了"天晴"（继续放行）和"取帧走了别的通道"（去查源 —— 也就是 2026-10-15
    真正发生的那件事）。缺值按原因拆开，缺的是哪一样就说哪一样。
    """
    frame_for([QUIET], mode='virtual')
    samples, info = service._radar_avoidance('live')
    assert info['sweepSlots'] == 0
    assert info['reason'] == 'NO_CONVECTIVE_ECHO', '本窗口内没有对流回波是合法状态'
    assert info['reason'] != 'RADAR_UNAVAILABLE'
