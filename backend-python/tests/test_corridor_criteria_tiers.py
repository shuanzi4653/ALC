"""F-3 判据：结论档位与判据区必须自洽（复测 N-5）。

**这条对应的是实测数字，不是假想**：雾案例 53 条走廊里，
· 19 条「不可飞」—— 每条至少一条判据 `passed=false`，自洽；
· **34 条「需谨慎」—— 四条判据全部 `passed=true`**，不自洽，占 64%。

根因不是算错，是**判据区只画了停飞档**，而结论用的是「停飞 ∪ 谨慎」：
能见度 2800 m 按谨慎档 <3000 m 命中，行里却只写「阈值 <1000 m，满足」；
概率 20.2% 按谨慎档 ≥15% 命中，行里却只写「阈值 ≥25%，满足」。

修法是给每条判据补 `watchThreshold / watchPassed / hitTier`（阈值全部来自
verdict 用的那一套 `nowcast.observation_level`，不新造常量），于是
「结论非可飞 ⇒ 必有一条判据未满足（停飞档或谨慎档）」在载荷层就成立。

判据直接打后端函数，不经 HTTP：它验的是**同一份数据**，多一层网络只会多一种假通过。
"""
from __future__ import annotations

import pytest

from ml import nowcast
from traffic import v2

CASE = 'fog-20250105'


@pytest.fixture(scope='module')
def details():
    snap = v2.corridors(limit=None, case_id=CASE)
    return [(it['corridorId'], v2.corridor(it['corridorId'], case_id=CASE))
            for it in snap['items']]


def test_结论非可飞的走廊必须有一条判据未满足(details):
    """核心判据：`verdict != 可飞` ⇒ 至少一条判据的停飞档或谨慎档未满足。"""
    broken = []
    for cid, d in details:
        if d.get('verdict') == '可飞':
            continue
        crit = d.get('criteria') or []
        if not any(c.get('passed') is False or c.get('watchPassed') is False for c in crit):
            broken.append((cid, d.get('verdict'),
                           [(c['metric'], c.get('passed'), c.get('watchPassed')) for c in crit]))
    assert not broken, f'{len(broken)} 条「非可飞」的判据全绿：{broken[:3]}'


def test_需谨慎档的数量与实测一致(details):
    """19 不可飞 / 34 需谨慎 —— 数字变了要么是数据变了，要么是判定被改坏了。"""
    counts = {}
    for _cid, d in details:
        counts[d.get('verdict')] = counts.get(d.get('verdict'), 0) + 1
    assert counts.get('不可飞') == 19, counts
    assert counts.get('需谨慎') == 34, counts


def test_每条判据都带两档信息(details):
    """前端要靠 `hitTier` 一次渲染，缺字段就会退回"自己拼阈值"（那就是两套口径）。"""
    for cid, d in details:
        for c in d.get('criteria') or []:
            assert 'watchPassed' in c, f'{cid} / {c.get("metric")} 缺 watchPassed'
            assert 'tierText' in c, f'{cid} / {c.get("metric")} 缺 tierText'
            assert c.get('hitTier') in (None, 'NONE', 'WATCH', 'BLOCK'), \
                f'{cid} / {c.get("metric")} hitTier={c.get("hitTier")}'


def test_谨慎档阈值与判定层同源(details):
    """能见度谨慎档必须是 `CAUTION_VIS_M`，概率谨慎档必须是 `P_PROB_WATCH`。

    这两个数一旦和 `observation_level()` / `prob_verdict` 用的分叉，
    「判据自洽」就只是这一屏的自洽 —— 换个量又会冒出来。
    """
    for cid, d in details:
        for c in d.get('criteria') or []:
            if c['metric'] == '能见度':
                assert c['watchThreshold'] == nowcast.CAUTION_VIS_M, cid
                assert c['threshold'] == nowcast.LOW_VIS_M, cid
            elif c['metric'] == '概率档':
                assert c['watchThreshold'] == v2.P_PROB_WATCH, cid
                assert c['threshold'] == v2.P_PROB_BLOCK, cid
            elif c['metric'] == '阵风':
                # 阵风没有谨慎档 —— 填一个数就等于在界面上造一条不存在的档位
                assert c['watchThreshold'] is None, cid
            elif c['metric'] == '云底高':
                assert c['watchThreshold'] is None, cid
                assert c.get('affectsVerdict') is False, cid


def test_可飞走廊的两档都必须满足(details):
    """反向：判「可飞」却有一条已触发谨慎档，同样是自相矛盾。"""
    bad = []
    for cid, d in details:
        if d.get('verdict') != '可飞':
            continue
        for c in d.get('criteria') or []:
            if c.get('passed') is False or c.get('watchPassed') is False:
                bad.append((cid, c['metric'], c.get('passed'), c.get('watchPassed')))
    assert not bad, f'判可飞但有判据未满足：{bad[:3]}'
