import json

import pytest
from traffic import operations


@pytest.fixture
def plan(monkeypatch, tmp_path):
    flight = dict(id='f1', name='local flight', status='SCHEDULED', departureMinute=30,
                  scheduledMinute=25, delayMinutes=5, detourMinutes=0, points=[], reason='CLEAR')
    data = dict(status='READY', sessionId='a'*24, flights=[flight],
                stats=dict(carRoutes=53, deliveryRoutes=108, accepted=1, closed=0))
    monkeypatch.setattr(operations.service, 'session', lambda *_: data)
    monkeypatch.setattr(operations, 'JOURNAL', tmp_path/'journal.json')
    return data


def test_suspend_resume_persist_without_mutating_frozen_plan(plan):
    operations.command(42, 'clear', 'f1', 10, 'SUSPEND')
    operations.command(42, 'clear', 'f1', 20, 'RESUME')
    assert [r['action'] for r in operations.records(plan['sessionId'])] == ['SUSPEND', 'RESUME']
    assert operations.records('b'*24) == []
    assert plan['flights'][0]['status'] == 'SCHEDULED'


def test_commands_fail_closed_and_reject_time_travel(plan):
    with pytest.raises(ValueError): operations.command(42, 'clear', 'f1', 30, 'SUSPEND')
    operations.command(42, 'clear', 'f1', 20, 'SUSPEND')
    with pytest.raises(ValueError): operations.command(42, 'clear', 'f1', 21, 'SUSPEND')
    with pytest.raises(ValueError): operations.command(42, 'clear', 'f1', 19, 'RESUME')
    plan['flights'][0]['status'] = 'CLOSED'
    with pytest.raises(ValueError): operations.command(42, 'clear', 'f1', 25, 'RESUME')


def test_evidence_uses_operation_time_and_exact_session(plan):
    operations.command(42, 'clear', 'f1', 20, 'SUSPEND')
    before = operations.explain(42, 'clear', 'f1', 19, 'why', {})
    after = operations.explain(42, 'clear', 'f1', 21, 'why', {})
    assert '人工暂停' not in before['answer']
    assert '人工暂停' in after['answer']
    assert after['sessionId'] == plan['sessionId']
    assert after['source'] == 'rule'
    assert after['minute'] == 21


# ------------------------------------------------- 运行操作与决策日志（P0-1）
#
# 一条通道、两种读法：`records()` 只给回放（暂停/恢复），`journal()` 给页面（全部）。
# 下面这组判据的作用是**把这两条通道分开**——单独任何一边都可能"恰好通过"
# （写出去了没读出来、或反过来），成对断言才说明过滤器真的在起作用。

def test_the_two_readers_agree_on_manual_rows_and_disagree_on_system_rows(plan):
    """双向判据：`SYSTEM` 进 `journal` 而不进 `records`。

    只断言 `records() 不含 SYSTEM` 是不够的 —— 一个什么都没写进去的实现同样
    满足它。只断言 `journal() 含 SYSTEM` 也不够 —— 一个不设过滤的实现同样满足
    它。两条一起断言，才排除掉这两种坏法。
    """
    operations.command(42, 'clear', 'f1', 10, 'SUSPEND')
    operations.note_build(plan)
    session = plan['sessionId']
    assert [r['action'] for r in operations.records(session)] == ['SUSPEND']
    assert [r['action'] for r in operations.journal(session)] == ['SUSPEND', 'PLAN_BUILT']


def test_a_plan_is_logged_once_no_matter_how_often_it_is_polled(plan):
    """`/traffic/session` 会被轮询，构建完成只能留一行。

    去掉去重，这一页会按轮询次数增长。
    """
    first = operations.note_build(plan)
    assert first is not None
    assert operations.note_build(plan) is None
    assert operations.note_build(plan) is None
    assert len(operations.journal(plan['sessionId'])) == 1


def test_a_new_plan_revision_is_a_new_row(plan):
    """幂等的键是 (sessionId, planRevision)，不是 sessionId 一个。

    同一份会话重新构建（换了气象通道或种子）是一次**新的**系统决策，
    折叠掉它等于把"结果为什么变了"从日志里删掉。
    """
    operations.note_build(plan)
    plan['planRevision'] = 'rev-2'
    assert operations.note_build(plan) is not None
    assert len(operations.journal(plan['sessionId'])) == 2


def test_a_source_switch_is_visible_from_every_plan(plan):
    """数据源变更不属于任何一份计划，但必须每份都看得见。

    它是"同种子两次结果不同"的唯一解释；挂到某一个 sessionId 上，
    换一份计划就再也看不到它了。
    """
    operations.note_build(plan)
    operations.note_source('virtual', previous='measured', actor='值班员', reason='演习')
    rows = operations.journal(plan['sessionId'])
    assert [r['action'] for r in rows] == ['PLAN_BUILT', 'WEATHER_MODE']
    assert 'measured → virtual' in rows[-1]['detail']
    assert '值班员' in rows[-1]['detail']
    # 另一份会话同样看得到这条全局行（另一条本来就是别的计划的，不该跟过来）。
    assert [r['action'] for r in operations.journal('b' * 24)] == ['WEATHER_MODE']


def test_rows_written_before_this_round_are_still_manual_actions(tmp_path, monkeypatch):
    """旧日志行没有 `kind` 字段，不能因此从回放里消失。

    线上已经有一份写过的日志（`traffic-operations.json`）。升级后把它读成
    "类型未知"而丢掉，等于把用户已经做过的操作从时间轴上抹掉。
    """
    journal = tmp_path / 'legacy.json'
    journal.write_text('[{"id":"x","sessionId":"' + 'a' * 24
                       + '","flightId":"f1","action":"SUSPEND","minute":10}]', encoding='utf-8')
    monkeypatch.setattr(operations, 'JOURNAL', journal)
    assert [r['action'] for r in operations.records('a' * 24)] == ['SUSPEND']


# ------------------------------------------------- 事件处置台状态机（P0-3）

def test_a_disposal_is_recorded_against_the_event_not_the_flight(plan):
    """处置挂在**事件键**上：一个事件压着一组班次，挂在班次上就要重复处置。"""
    row = operations.note_disposal(plan['sessionId'], 'rte-1:WEATHER_BLOCKED:true',
                                   'ACKNOWLEDGED', note='已通知放行席', actor='值班员')
    assert row['kind'] == 'DISPOSAL' and row['eventKey'] == 'rte-1:WEATHER_BLOCKED:true'
    # 这条记录里**没有** `flightId` 这个维度 —— 判决挂在事件上，不在班次上。
    assert 'flightId' not in row
    journal = operations.journal(plan['sessionId'])
    assert journal[-1]['action'] == 'ACKNOWLEDGED'
    assert journal[-1]['actionLabel'] == '确认事件'
    assert journal[-1]['kindLabel'] == '事件处置'
    assert journal[-1]['eventKey'] == 'rte-1:WEATHER_BLOCKED:true'


def test_disposals_do_not_enter_the_replay_channel(plan):
    """处置是记录，不是班次状态变化 —— 不能进 `records()`。"""
    operations.note_disposal(plan['sessionId'], 'rte-1:CLEAR:false', 'HANDLED')
    assert operations.records(plan['sessionId']) == []


def test_an_unknown_disposal_state_is_refused(plan):
    """状态机不能被一个拼错的值悄悄扩展。"""
    with pytest.raises(ValueError):
        operations.note_disposal(plan['sessionId'], 'rte-1:CLEAR:false', 'RESOLVED')


def test_the_state_machine_has_four_writable_states_and_pending_is_not_one(plan):
    """四态（P0-3 ③）。`PENDING` **不在**白名单里 —— 它不是一个可写的值，
    而是"没有任何记录"时的默认读法。把它做成可写，就分不出"没人看过"与
    "有人看过并决定不动它"。"""
    assert set(operations.DISPOSAL_STATES) == {'ACKNOWLEDGED', 'IN_PROGRESS',
                                               'HANDLED', 'REVIEWED'}
    assert 'PENDING' not in operations.DISPOSAL_STATES
    # 0.11.16：**只比较本次新增的四条**。原写法把整个会话的台账拉平再断言，
    # 于是它在整包里跑时（台账里已有别的用例写的行）必红、单跑却绿 ——
    # 一条判据的结论取决于"还有谁跑过"，它量的就不是被测对象了（M67）。
    before = sum(1 for row in operations.journal(plan['sessionId']) if row['kind'] == 'DISPOSAL')
    for state in ('ACKNOWLEDGED', 'IN_PROGRESS', 'HANDLED', 'REVIEWED'):
        operations.note_disposal(plan['sessionId'], 'rte-1:CLEAR:false', state)
    disposal = [row['actionLabel'] for row in operations.journal(plan['sessionId'])
                if row['kind'] == 'DISPOSAL']
    assert disposal[before:] == ['确认事件', '开始处置', '标记已处置', '复核处置']


# ------------------------------------------------- 一键处置（P0-3 ①）
#
# 这一族判据的全部要点：**做不到的动作必须说出来**。
# 三种结局（真的做了 / 本系统不支持 / 请求本身非法）必须两两不同形 ——
# 把它们合并成"动作没成功"，界面就只能渲染成"失败了请重试"，而重试永远不会成功。

def test_one_click_suspend_actually_suspends_and_advances_the_state(plan):
    result = operations.dispose(42, 'clear', 'rte-1:WEATHER_BLOCKED:true', 'SUSPEND',
                                flight_id='f1', minute=10)
    assert result['applied'] is True and result['supported'] is True
    assert result['state'] == 'IN_PROGRESS'
    # ① 班次操作真的写进了回放通道 —— 这是"世界变了"的证据，不是一条自述。
    assert [r['action'] for r in operations.records(plan['sessionId'])] == ['SUSPEND']
    # ② 事件状态也真的推进了，且带上**动作名**（SUSPEND 与 HANDLED 都推状态机，
    #    但交班时要读得出是哪一种）。
    row = [r for r in operations.journal(plan['sessionId']) if r['kind'] == 'DISPOSAL'][-1]
    assert row['action'] == 'IN_PROGRESS' and row['disposalAction'] == 'SUSPEND'
    assert '停止放行' in row['detail']


def test_an_unsupported_action_is_refused_with_a_reason_and_changes_nothing(plan):
    """延迟与改航**在运行时做不到**：改时隙与绕行几何在构建时就写定了。"""
    for action in ('DELAY', 'DETOUR'):
        result = operations.dispose(42, 'clear', 'rte-1:WEATHER_BLOCKED:true', action,
                                    flight_id='f1', minute=10)
        assert result['applied'] is False
        assert result['supported'] is False, '必须显式自述"本系统不支持"'
        assert result['state'] is None, '不支持的动作不得推进状态机'
        assert len(result['reason']) > 20, '只回一句"不支持"与报错长得一样'
        assert '本系统不支持' in result['detail']
    # 负向对照：一次"不支持"之后，日志里不能出现任何 DISPOSAL 记录。
    # 否则界面会把这一条读成"已经在处理了"，而世界没有变化。
    assert [r for r in operations.journal(plan['sessionId']) if r['kind'] == 'DISPOSAL'] == []
    assert operations.records(plan['sessionId']) == []


def test_an_unknown_action_raises_while_an_unsupported_one_returns(plan):
    """「请求非法」与「能力边界」必须是两种不同的形状。

    前者走异常（HTTP 422），后者走 200 + `supported=False`。把它们合起来，
    用户就无法分辨"我传错了"和"这个系统不提供该功能" —— 而两者的下一步动作相反。
    """
    with pytest.raises(ValueError):
        operations.dispose(42, 'clear', 'rte-1:CLEAR:false', 'RESOLVE_EVERYTHING', minute=10)
    assert operations.dispose(42, 'clear', 'rte-1:CLEAR:false', 'DELAY',
                              minute=10)['supported'] is False


def test_disposal_actions_publish_whether_they_can_run_and_why(plan):
    """动作表本身要能被核对：每一个不支持的都必须带原因，每一个支持的都必须有落点。"""
    assert operations.DISPOSAL_ACTIONS['SUSPEND']['supported'] is True
    for key, spec in operations.DISPOSAL_ACTIONS.items():
        assert spec['label']
        assert spec['reason']
        if not spec['supported']:
            assert len(spec['reason']) > 20, f'{key} 声明不支持就必须说清为什么'
        assert spec['state'] in operations.DISPOSAL_STATES



# ------------------------------------------------- AI 作为算法的一部分（AL-7）
#
# 这一族判据要钉住的是**降级的完整性**：模型越出证据集合时，整条回答必须变成规则
# 证据，而不是把越界的编号丢掉、其余照旧。后者最危险的地方在于它看起来完全正常 ——
# 界面显示"外部模型检索成功"，而回答里的引用没有一条是核对过的。

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return {'choices': [{'message': {'content': json.dumps(self._payload)}}]}


class _FakeClient:
    def __init__(self, payload, **_kwargs):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def post(self, *_args, **_kwargs):
        return _FakeResponse(self._payload)


def _answer_with(monkeypatch, payload):
    monkeypatch.setattr(operations.httpx, 'Client', lambda **kw: _FakeClient(payload))
    cfg = dict(api_key='test-key', base_url='http://model.invalid', model='deepseek-chat')
    return operations.explain(42, 'clear', 'f1', 21, 'why', cfg)


def test_a_model_citing_evidence_outside_the_set_is_vetoed_whole(plan, monkeypatch):
    """**整条**降级，不是部分降级。这是「AI 被规则否决」的唯一正确形态。"""
    result = _answer_with(monkeypatch, {'evidenceIds': ['flight', 'network', 'no-such-evidence']})
    assert result['source'] == 'rule'
    assert result['ai']['outcome'] == 'VETOED'
    assert 'no-such-evidence' in result['vetoed']
    assert [c['origin'] for c in result['citations']] == ['RULE'] * len(result['citations'])
    # 越界之后一条 AI 选取都不许留下；`ai.selected` 也必须是空的。
    assert result['ai']['selected'] == []


def test_an_accepted_selection_marks_only_the_ids_the_model_chose(plan, monkeypatch):
    """反向对照：合法选取必须**保留** AI 标记，否则上一条判据量的是"永远不会标记"。"""
    result = _answer_with(monkeypatch, {'evidenceIds': ['flight', 'constraints']})
    assert result['source'] == 'deepseek'
    assert result['ai']['outcome'] == 'ACCEPTED'
    assert result['ai']['selected'] == ['constraints', 'flight']
    origins = {c['id']: c['origin'] for c in result['citations']}
    assert origins['flight'] == 'AI' and origins['constraints'] == 'AI'
    # 规则强制带上的 `source` 仍是规则证据 —— 模型没有选过它。
    # （给定 `flightId` 时强制项是 `flight` 而非 `network`；这一条就是在钉这件事：
    #  模型选中的 `flight` 与规则强制的 `flight` 合流后，标记应取"AI"。）
    assert origins['source'] == 'RULE'
    assert [c['id'] for c in result['citations']] == ['flight', 'constraints', 'source']


def test_an_empty_or_oversized_selection_is_also_a_veto(plan, monkeypatch):
    """两条边界各自可指名，不合并成一句"返回不合法"。"""
    empty = _answer_with(monkeypatch, {'evidenceIds': []})
    assert empty['ai']['outcome'] == 'VETOED' and '没有返回' in empty['vetoed']
    oversized = _answer_with(monkeypatch, {'evidenceIds': ['flight'] * 6})
    assert oversized['ai']['outcome'] == 'VETOED' and '6 条' in oversized['vetoed']


def test_not_configured_is_not_a_veto(plan):
    """没配密钥与"被否决"是两件事，不能都显示成坏消息。"""
    result = operations.explain(42, 'clear', 'f1', 21, 'why', {})
    assert result['source'] == 'rule' and result['vetoed'] is None
    assert result['ai'] == {'used': False, 'outcome': 'NOT_CONFIGURED', 'model': None,
                            'vetoed': None, 'errorCode': 'NOT_CONFIGURED', 'selected': [],
                            'available': sorted(c['id'] for c in result['citations']),
                            'note': result['ai']['note']}


def test_every_journal_row_carries_a_human_label(plan):
    """页面不自己拼文案：`actionLabel` 由服务端给出（同 M59）。"""
    operations.note_build(plan)
    operations.note_source('virtual', previous='measured')
    operations.note_export(plan['sessionId'], 'csv', 12)
    rows = operations.journal(plan['sessionId'])
    assert [r['kindLabel'] for r in rows] == ['系统决策', '数据源变更', '导出']
    assert [r['actionLabel'] for r in rows] == ['运行计划构建完成', '气象通道切换', '导出运行日志']
    assert rows[-1]['detail'] == '导出运行日志 · csv · 12 条'


# ------------------------------------------------- 数字型验收（§十七①）
#
# P0-1 的验收原话里有一个数字：「走完一次完整演示后，本页**不少于 20 条记录**且可
# 导出为可读表格」。数字型验收必须配数字型判据 —— 否则"20"只是一句话，而"日志不空"
# 这条却极其容易满足（写一行就算不空）。
#
# 下面这条判据做两件事，缺一不可：
#   ① **逐类计数**：总数达标但 20 条全是同一类，等于演示动线里有一半的写入口根本
#      没跑过；
#   ② **计数与写入次数逐一对齐**：写完 24 次恰好读回 24 行 —— 少一行说明被去重吞了，
#      多一行说明轮询/重复调用写了两遍（这两件事在页面上表现相同，都是"数字对不上"）。

def test_the_demo_run_reaches_the_promised_twenty_rows_with_every_kind_present(plan):
    # 演示动线（与 README 里那份一致）：首次构建 → 两次换通道各重建一次 → 改种子
    # 再重建 → 暂停 / 恢复 → 对两组事件各做两次处置 → 导出一次。换通道、换种子都会让
    # `planRevision` 变化，因此每一次重建都是一条**新的**系统决策行。
    #
    # 每一类的**期望条数**写成独立的常量，而不是在断言的右边现推一个算式：
    # 算式算错时读者要重新推一遍才能发现，而常量写错会直接与左边的名字不匹配。
    builds = 1 + 2 + 20
    sources = 2
    commands = 2
    disposals = 2 * 2
    exports = 1
    writes = builds + sources + commands + disposals + exports

    operations.note_build(plan)
    for index, (mode, previous) in enumerate([('virtual', 'measured'), ('measured', 'virtual')]):
        operations.note_source(mode, previous=previous, actor='值班员')
        plan['planRevision'] = 'rev-%d' % (index + 1)
        operations.note_build(plan)
    for index in range(20):
        plan['planRevision'] = 'demo-%d' % index
        operations.note_build(plan)
    operations.command(42, 'clear', 'f1', 10, 'SUSPEND')
    operations.command(42, 'clear', 'f1', 20, 'RESUME')
    for _index in range(2):
        operations.note_disposal(plan['sessionId'], 'R1:WEATHER:0', 'ACKNOWLEDGED',
                                 actor='值班员')
        operations.note_disposal(plan['sessionId'], 'R1:WEATHER:0', 'HANDLED',
                                 actor='值班员', action='SUSPEND')
    operations.note_export(plan['sessionId'], 'csv', 24)

    rows = operations.journal(plan['sessionId'])
    assert len(rows) == writes, (
        '写完 %d 次却读回 %d 行 —— 少行就是被去重吞掉，多行就是重复写了两遍'
        % (writes, len(rows)))
    assert len(rows) >= 20, '演示动线跑完必须达到验收承诺的 20 条，实测 %d 条' % len(rows)

    kinds = {}
    for row in rows:
        kinds[row['kind']] = kinds.get(row['kind'], 0) + 1
    assert set(kinds) == {'SYSTEM', 'SOURCE', 'MANUAL', 'DISPOSAL', 'EXPORT'}, (
        '五类记录必须各自都被写过；只有一类说明演示动线里其余入口没跑过：%s' % kinds)
    assert (kinds['SYSTEM'], kinds['SOURCE'], kinds['MANUAL'],
            kinds['DISPOSAL'], kinds['EXPORT']) == (builds, sources, commands,
                                                    disposals, exports)


def test_a_manual_command_survives_a_journal_that_already_has_system_rows(plan):
    """**顺序**判据：先写系统事件、再点「暂停班次」。

    界面上这个顺序是必然的 —— 打开页面就会构建计划并写下 `PLAN_BUILT`，用户才会去点
    暂停。而 `command()` 原先用 `r['flightId']` 直接下标取一个**只有人工行才有**的
    字段，于是这份日志里只要先有一行系统事件，第一次点暂停就是 `KeyError` → HTTP 500。

    一整套既有测试之所以全绿，只是因为它们碰巧都先调 `command` 再写别的行 ——
    一条从未被走到的组合（§十八⑫）。这条判据把那个顺序钉住。
    """
    operations.note_build(plan)
    operations.note_source('virtual', previous='measured', actor='值班员')
    operations.note_export(plan['sessionId'], 'csv', 3)
    record = operations.command(42, 'clear', 'f1', 10, 'SUSPEND')
    assert record['action'] == 'SUSPEND'
    # 回放通道仍然只看见人工行 —— 修的是取值方式，不是过滤器。
    assert [r['action'] for r in operations.records(plan['sessionId'])] == ['SUSPEND']
    assert len(operations.journal(plan['sessionId'])) == 4


def test_a_command_survives_a_journal_that_already_has_disposal_rows(plan):
    """处置行同样**没有 `flightId`**（它绑的是事件，不是班次）—— 同一处取值方式的
    第二个受害者。

    写入顺序是演示动线里连着的一步：先在预警中心一键处置，再点「暂停班次」。
    旧实现的 `r['flightId']` 会在第一行处置记录上就 `KeyError`。处置行也**没有
    `minute`**，所以它本来就不该参与"时间轴倒退"那条守卫 —— 把范围收窄到 `MANUAL`
    与修取值方式是同一件事的两面。
    """
    operations.note_disposal(plan['sessionId'], 'R1:WEATHER:0', 'HANDLED',
                             actor='值班员', action='SUSPEND')
    record = operations.command(42, 'clear', 'f1', 10, 'SUSPEND')
    assert record['action'] == 'SUSPEND'
    assert record['minute'] == 10
    # 回放通道仍然只看见人工行 —— 修的是取值方式与比较范围，不是过滤器。
    assert [r['action'] for r in operations.records(plan['sessionId'])] == ['SUSPEND']


