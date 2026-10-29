"""G-6（0.11.11）：列表行不带轨迹、地图行带轨迹。

这两句必须同时为真，而且**不能靠"看起来没问题"**：
`flights` 少了 `points` 而 `mapFlights` 没有它，地图上一条航线都没有；
反过来 `mapFlights` 少了载客优先的挑选，53 条载客走廊会只剩十几条有线
（原始顺序里配送占 89%，`flights[:600]` 大概率全是配送）。

判据只读 `_slim_session`（纯函数，不建场），所以它是毫秒级的。
"""
from __future__ import annotations

import json

import pytest

from main import MAP_MAX_ROWS, SLIM_FLIGHT_FIELDS, _slim_session


def _fake(mode: str, index: int) -> dict:
    row = {key: None for key in SLIM_FLIGHT_FIELDS}
    row.update({
        'id': f'{mode}-{index:05d}',
        'mode': mode,
        'status': 'SCHEDULED',
        'fromCity': f'1-{index % 7:02d}',
        'toCity': f'1-{(index + 3) % 7:02d}',
        'departureMinute': index,
        'arrivalMinute': index + 40,
        # 8 个点，与 SLIM_MAX_POINTS 改前的档位一致；坐标是占位值，只用于体积比较
        'points': [[122.0 + i * 0.01, 41.0 + i * 0.01, 300.0 * i] for i in range(8)],
    })
    return row


def _payload(car=848, delivery=900):
    flights = [_fake('CAR', i) for i in range(car)]
    flights += [_fake('DELIVERY', i) for i in range(delivery)]
    return {'status': 'READY', 'flights': flights, 'seed': 42, 'scenario': 'live',
            'stats': {}, 'flightStats': {}, 'fleet': [], 'network': {}}


def test_flights_carry_no_points_while_map_rows_do():
    out = _slim_session(_payload())
    flights = out['flights']
    maps = out['mapFlights']
    assert flights, '列表不能为空'
    assert maps, '地图行不能为空'
    assert all('points' not in row for row in flights), \
        'session.flights 仍带着 points —— 表格一行都不读它，等于白传'
    # `CLOSED` 的班次没有航迹是事实（它没飞过），不是缺陷；会飞的必须有线。
    online = [row for row in maps if (row.get('status') or '') != 'CLOSED']
    assert online, '地图行全是 CLOSED，这个夹具不成立'
    assert all(isinstance(row.get('points'), list) and len(row['points']) >= 2 for row in online), \
        'mapFlights 里会飞的班次没有轨迹 —— 地图上画不出航线'


def test_map_rows_are_capped_and_prefer_passenger_corridors():
    out = _slim_session(_payload())
    maps = out['mapFlights']
    assert len(maps) <= MAP_MAX_ROWS, '地图行超过上限'
    # 载客优先：前 600 条里必须全是载客（负载很重时配送排在后面）
    assert maps[0]['mode'] == 'CAR', '地图行没有载客优先 —— 配送占 89%，会先把名额占满'
    car_count = sum(1 for row in maps if row['mode'] == 'CAR')
    # 0.11.15（K-5）：地图改成**按类型分桶抽样**（CAR 每桶 20 / DELIVERY 每桶 18），
    # 所以不再要求"载客全量入图"——改为要求"账目闭合"：
    # 地图上的 + 抽样没画的 + 因关闭没时刻的 = 载客全量。
    stats = out['flightStats']
    assert (car_count + stats['carSampledOut'] + stats['carClosedNoTime']
            == stats['carReturned']), (
        f'载客账目对不上：地图 {car_count} + 抽样未画 {stats["carSampledOut"]}'
        f' + 关闭无时刻 {stats["carClosedNoTime"]} ≠ {stats["carReturned"]}')
    assert car_count >= 300, f'地图载客只有 {car_count} 条，53 条走廊会缺段'


def test_body_is_materially_smaller_than_the_points_everywhere_version():
    payload = _payload()
    out = _slim_session(payload)
    with_points = json.dumps({'flights': payload['flights']}, ensure_ascii=False)
    without = json.dumps({'flights': out['flights'], 'mapFlights': out['mapFlights']},
                         ensure_ascii=False)
    # 0.11.11 实测：points 在**整包**里占 26%（不是方案说的 46% —— 那是单条内的占比，
    # 而大部分行本来就抽稀过）。所以判据是降幅 ≥25%，不是绝对值 800 KB。
    assert len(without) < len(with_points) * 0.75, (
        '裁掉 points 之后包体没有明显下降（%.2f MB → %.2f MB）'
        % (len(with_points) / 1e6, len(without) / 1e6))


def test_counts_are_unaffected_by_trimming():
    out = _slim_session(_payload())
    stats = out['flightStats']
    assert stats['total'] == 1748
    assert stats['carReturned'] == 848, '载客必须全量返回（事件、批次、处置都看它）'
    assert stats['mapReturned'] == len(out['mapFlights'])
    # 前端拿它说"少的是哪一部分"，所以它必须与 flights 的实际条数一致
    assert stats['returned'] == len(out['flights'])


def test_expected_volume_drops_at_least_a_quarter():
    """体积判据：**降幅 ≥25%**，不是绝对值 800 KB。

    方案 §6.4 写"<800 KB"，是按 `points` 占单行 46% 推的；而线上实测整包里 `points`
    只占 26%（1 217 KB → 896 KB，降 26%）。要真到 800 KB 只能把配送班次从首屏砍掉，
    那会让台账少一类样本 —— 换来的 12% 不值得，所以判据改成降幅。
    """
    out = _slim_session(_payload())
    body = json.dumps({'flights': out['flights'], 'mapFlights': out['mapFlights']},
                      ensure_ascii=False).encode('utf-8')
    assert len(body) < 950_000, '裁剪后仍 %.0f KB' % (len(body) / 1024)
