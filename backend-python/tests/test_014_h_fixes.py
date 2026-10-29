"""0.11.14 的 H-1 / H-2③ / H-3 三张工单的判据。

复测报告给的是"现象"（T+2 之后地图没飞机、切通道不生效、minute 参数被忽略），
这里把它翻成**能在这里跑红的判据**，免得下一轮又只靠肉眼看截图。

| 工单 | 判据 |
|---|---|
| H-1 | `mapFlights` 的 `arrivalMinute` 最大值 ≥ 470；`mode=CAR` 条数 == 载客全量；每个 30 分钟桶非空 |
| H-2③ | `planRevision` 是**会变的数字串**，`PLAN_REVISION` 仍是算法版本串（两者不许合并） |
| H-3 | `minute` 过滤真的生效（0 与 300 的在空数不同），不传时行为不变 |
"""
from __future__ import annotations

import re

import pytest

from main import (MAP_BUCKET_MINUTES, MAP_CAR_PER_BUCKET, MAP_DELIVERY_PER_BUCKET,
                  MAP_MAX_ROWS, SLIM_FLIGHT_FIELDS, _slim_session)


def _flight(mode: str, index: int, departure: float, duration: float = 30.0) -> dict:
    row = {key: None for key in SLIM_FLIGHT_FIELDS}
    row.update({
        'id': f'{mode}-{index:05d}',
        'mode': mode,
        'status': 'SCHEDULED',
        'fromCity': f'1-{index % 7:02d}',
        'toCity': f'1-{(index + 3) % 7:02d}',
        'departureMinute': departure,
        'arrivalMinute': departure + duration,
        'points': [[122.0, 41.0, 300.0], [122.5, 41.5, 400.0]],
    })
    return row


def _payload(car=848, delivery=900, minutes=480):
    """载客每 30 分钟均匀铺开；配送全部堆在**头两小时**（复测里的真实形状）。"""
    flights = []
    for i in range(car):
        flights.append(_flight('CAR', i, departure=(i % minutes)))
    # 配送起飞时刻**均匀铺满** 0~479：真实物流是全天候的，不是只有头两小时。
    # （第一版夹具把配送全堆在 0~120，于是"每桶 18 条"永远达不到 —— 夹具形状不对，
    #   判据就会红在一个跟实现无关的地方。这条与 MEMORY 里"夹具必须照抄被抓对象的
    #   真实形状"是同一件事。）
    for i in range(delivery):
        flights.append(_flight('DELIVERY', i, departure=(i * minutes) // max(1, delivery)))
    return {'status': 'READY', 'flights': flights, 'seed': 42, 'scenario': 'live',
            'stats': {}, 'flightStats': {}, 'fleet': [], 'network': {}}


def test_map_rows_cover_the_whole_timeline():
    """H-1：地图数据必须覆盖到时间轴末尾，不能只覆盖头两小时。"""
    out = _slim_session(_payload())
    maps = out['mapFlights']
    arrivals = [row['arrivalMinute'] for row in maps if row.get('arrivalMinute') is not None]
    assert arrivals, 'mapFlights 为空'
    assert max(arrivals) >= 470, (
        'mapFlights 最大到达时间只有 %.1f 分钟，时间轴开到 480 —— 后半段地图上会没有飞机'
        % max(arrivals))


def test_map_rows_give_delivery_its_own_quota():
    """K-5（0.11.15）：配送必须**每条桶都有**，不能由载客先装满。

    0.11.14 是一个桶里 CAR 先装满（698 条），配送只在"整桶没 CAR"时补 4 条 ⇒
    mapFlights 722 条里配送只有 24 条、起飞时刻集中在 6 个桶。浏览器实测
    T+15 之后「配送无人机」全程 0 架，而业务上配送占 89%（6912 / 7760）。

    这条判据钉两件事：① 配送条数达到每桶配额（约 16 × 18）；② 每个桶都有配送。
    """
    payload = _payload()
    out = _slim_session(payload)
    maps = out['mapFlights']
    delivery = [row for row in maps if row['mode'] == 'DELIVERY']
    expected_min = (480 // MAP_BUCKET_MINUTES) * (MAP_DELIVERY_PER_BUCKET - 2)
    assert len(delivery) >= expected_min, (
        '地图里只有 %d 条配送，按每桶 %d 条应有约 %d 条' %
        (len(delivery), MAP_DELIVERY_PER_BUCKET, expected_min))

    delivery_buckets = {int((row['departureMinute'] or 0) // MAP_BUCKET_MINUTES) for row in delivery}
    car_buckets = {int((row['departureMinute'] or 0) // MAP_BUCKET_MINUTES)
                   for row in maps if row['mode'] == 'CAR'}
    expected = set(range(0, 480 // MAP_BUCKET_MINUTES))
    assert not (expected - delivery_buckets), (
        '这些时间桶没有一架配送无人机：%s' % sorted(expected - delivery_buckets))
    assert not (expected - car_buckets), (
        '这些时间桶没有一架飞行汽车：%s' % sorted(expected - car_buckets))

    # 地图侧的账仍要对得上：地图上的 + 抽样没画的 + 因关闭没时刻的 = 载客全量。
    # `carSampledOut` 是 K-5 新增的那个数 —— 少了它，读者只能得出"地图漏了 500 多条"。
    stats = out['flightStats']
    assert (stats['mapCar'] + stats['carSampledOut'] + stats['carClosedNoTime']
            == stats['carReturned']), (
        '账对不上：地图 %s + 抽样未画 %s + 关闭无时刻 %s ≠ 载客全量 %s'
        % (stats['mapCar'], stats['carSampledOut'], stats['carClosedNoTime'], stats['carReturned']))
    assert 'mapSampling' in stats, '地图抽样口径必须随载荷发布'


def test_map_rows_keep_enough_passenger_rows_for_corridor_coverage():
    """K-5：载客每桶配额不许低于 20 —— 低于这个数，53 条走廊在图上会缺段。"""
    assert MAP_CAR_PER_BUCKET >= 20, '每桶载客配额 %d 太低，走廊会缺段' % MAP_CAR_PER_BUCKET


def test_every_half_hour_bucket_has_at_least_one_row():
    """H-1：每个 30 分钟桶都要有样本，档与档之间不许出现"整段空白"。"""
    maps = _slim_session(_payload())['mapFlights']
    buckets = {int((row['departureMinute'] or 0) // MAP_BUCKET_MINUTES) for row in maps}
    # 480 分钟切成 16 个桶：[0,30) … [450,480)。第 17 个桶（480 之后）没有起飞航班。
    expected = set(range(0, 480 // MAP_BUCKET_MINUTES))
    missing = sorted(expected - buckets)
    assert not missing, '这些时间桶在地图上一条载具都没有：%s' % missing


def test_map_rows_stay_under_the_cap():
    maps = _slim_session(_payload())['mapFlights']
    assert len(maps) <= MAP_MAX_ROWS, '地图行超过上限 %d（体积会失控）' % MAP_MAX_ROWS


def test_delivery_quota_is_not_larger_than_passenger_quota():
    """K-5：配送有自己的桶，但**不许反过来挤掉载客** —— 载客配额必须 ≥ 配送配额。"""
    assert MAP_CAR_PER_BUCKET >= MAP_DELIVERY_PER_BUCKET, (
        '载客每桶 %d 条反而少于配送每桶 %d 条' % (MAP_CAR_PER_BUCKET, MAP_DELIVERY_PER_BUCKET))


def test_plan_revision_is_a_moving_number_while_version_string_stays():
    """H-2③：修订号会变、算法版本串不变 —— 两个字段各司其职，不许合并回一个。"""
    from traffic import service

    assert re.fullmatch(r'traffic-plan-v[\d.]+', service.PLAN_REVISION), \
        'PLAN_REVISION 应是算法版本串（不随重建变化）'
    first = next(service._PLAN_REV_SEQ)
    second = next(service._PLAN_REV_SEQ)
    assert isinstance(first, int) and second == first + 1, \
        '修订号序列必须是递增整数（前端 `Number(planRevision)` 要能读成数字）'
    assert service.PLAN_REVISION == 'traffic-plan-v1.3', \
        '算法版本串被改动了 —— 它现在只作为 `planVersion` 发布'


def test_flights_minute_filter_is_declared_and_used():
    """H-3：`minute` 不能只是"声明了但不用"。

    判据读的是**函数签名与实现**：签名里要有 `minute`，实现里要真的用它过滤。
    这样"参数写进文档但没接线"（复测 N-3）就过不去。
    """
    import inspect

    from main import traffic_flights

    signature = inspect.signature(traffic_flights)
    assert 'minute' in signature.parameters, '端点签名里没有 minute 参数'
    source = inspect.getsource(traffic_flights)
    assert re.search(r'if\s+minute\s+is\s+not\s+None', source), \
        'minute 参数被声明了但实现里没有使用 —— 传什么时刻都会返回同一份'
    assert 'departureMinute' in source and 'arrivalMinute' in source, \
        '"在空"的过滤必须同时看起飞与到达'
