"""K-4 判据：首屏三格的**作用域**必须写在载荷里。

背景（用户 2026-10-27）：「最上面的框里面的数据；复核与触发停飞、平均提前量数字；
右下方的放行率、时隙重排、改航绕飞、停止放行。这些数据应该是同步且公用的，
请检查，避免出现同一页面的数据不同这种情况。」

实测的成因不是算错，是**三格里的第三格不是本帧的数**：
  · `pending` / `high` 是本帧走廊计数（随观测变）；
  · `lead` = 60 分钟，读的是 `data/training/metar/model-v2-metrics.json` 的
    离线回放中位值（2019–2025 三站 METAR，vis3k 62 次跨阈事件）。
三格并排在同一条 44 px 数字带上，读者只能把它们读成同一次求值，于是
「已触发停飞判据 0 条」与「平均提前量 60 分钟」被读成"提前 60 分钟报了 0 次警"。

所以判据钉两件事：
  ① `lead` 必须带 `scope='offline'`（前端据此打角标），另两格**不许**带；
  ② 它的 `baseline` 里必须写出**本帧触发数**，且那个数与 `high.value` 是同一个数 ——
     「前缀 + 数字」拼接必须验数字同源（0.11.19b 的同一类缺陷）。

判据直接打后端函数，不经 HTTP：验的是同一份数据，多一层网络只会多一种假通过。
"""
from __future__ import annotations

import re

import pytest

from traffic import v2

CASE = 'fog-20250105'


@pytest.fixture(scope='module')
def payload():
    return v2.overview(case_id=CASE)


def _by_key(payload):
    return {kpi['key']: kpi for kpi in payload['kpis']}


def test_平均提前量必须是离线口径(payload):
    kpi = _by_key(payload)['lead']
    assert kpi['scope'] == 'offline', (
        '这一格读的是离线回放中位数，不打 offline 角标就会与旁边两格的本帧计数混读')
    # 另外两格是本帧计数，带上 offline 就等于把"这一轮有几条"说成"历史上平均多久"。
    for key in ('pending', 'high'):
        assert 'scope' not in _by_key(payload)[key] or \
            _by_key(payload)[key]['scope'] != 'offline'


def test_离线口径的基线必须写出样本量与本帧触发数(payload):
    kpis = _by_key(payload)
    baseline = kpis['lead']['baseline']
    assert '离线回放' in baseline
    assert '非本帧读数' in baseline
    # 样本量来自 metrics 文件里的 `targets.vis3k.leadTime.n`
    assert re.search(r'\d+ 次跨阈事件', baseline), baseline
    # **同源判据**：baseline 里的"本帧触发 N 条"必须等于 high 这一格的值。
    # 两处各自算一次就会出现"基线说 19 条、卡片说 28 条"而两边都不报错。
    match = re.search(r'本帧触发 (\d+) 条', baseline)
    assert match, baseline
    assert int(match.group(1)) == kpis['high']['value'], (
        'baseline 里的触发数与「已触发停飞判据的走廊」不同源：%s vs %s'
        % (match.group(1), kpis['high']['value']))


def test_平均提前量不再用方向箭头暗示变化(payload):
    # 原来写 `direction: 'up'`，而它的基线是"规则基线 0（无预报能力）"——
    # 一个没有基线的 ▲ 说的是"在变好"，而它其实只是"离线中位数是 60"。
    assert _by_key(payload)['lead']['direction'] is None
