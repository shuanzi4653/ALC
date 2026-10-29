"""两个浏览器必须各看各的 —— 匿名工作区是这件事的唯一来源。

为什么这组判据必须钉在**键**上，而不是钉在界面上：默认参数本来就相同
（seed=42 / scenario=live），所以"隔离生效"和"隔离没生效"两张界面截图长得**一模一样**。
钉界面的判据在这里是量不出差异的；能量出差异的只有计划键、日志行归属和台账过滤。
"""
import hashlib
import json
import sqlite3

import pytest
from traffic import operations, service, weather_control

import decision_service
import workspace

WS_A = 'ws-aaaaaa-000001'
WS_B = 'ws-bbbbbb-000002'


@pytest.fixture(autouse=True)
def clean():
    weather_control.reset()
    yield
    weather_control.reset()


# ------------------------------------------------------------ 身份本身

def test_normalisation_rejects_rather_than_repairs():
    assert workspace.normalize('abcdef') == 'abcdef'
    assert workspace.normalize('a' * 64) == 'a' * 64
    assert workspace.normalize(None) == ''
    assert workspace.normalize('') == ''
    # 太短 / 太长 / 含非法字符 —— 一律落回「未标识」，**不做清洗**：
    # 清洗会把两个不同的客户端拼进同一个空间，那是最难发现的一类串号。
    assert workspace.normalize('abc') == ''
    assert workspace.normalize('a' * 65) == ''
    assert workspace.normalize('ab cd!') == ''


def test_header_wins_over_query_parameter():
    class _Req:
        def __init__(self, headers, params):
            self.headers = headers
            self.query_params = params
    assert workspace.from_request(_Req({'X-ALC-Workspace': WS_A}, {'ws': WS_B})) == WS_A
    assert workspace.from_request(_Req({}, {'ws': WS_B})) == WS_B
    assert workspace.from_request(_Req({}, {})) == ''


# ------------------------------------------------------------ 计划键

def test_same_request_in_two_workspaces_gets_two_different_plan_keys():
    key_a = service.identity(42, 'clear', None, weather_control.MODE_MEASURED, WS_A)
    key_b = service.identity(42, 'clear', None, weather_control.MODE_MEASURED, WS_B)
    assert key_a != key_b
    # 同一工作区、同一输入 ⇒ 仍然必须是同一个键（否则缓存与重放都会失效）
    assert key_a == service.identity(42, 'clear', None, weather_control.MODE_MEASURED, WS_A)


def test_an_unidentified_caller_keeps_the_pre_change_key():
    """**没有标识 ⇒ 和改造前一模一样。**

    否则老的计划缓存全部失效、巡检探针的行为悄悄变了，而"这次改造没有回归"这句话
    就失去了可判性 —— 判据必须能区分「带标识」与「不带标识」，不能把两者并成一个桶。
    """
    # 0.11.16：`identity()` 在 0.11.15 加了 `OPERATIONS_FINGERPRINT`（改阈值即换键），
    # 这条"改造前的键"的镜像算式没跟着改 ⇒ 从 0.11.15 起一直红着（同上一条 M95 的形态）。
    # 判据的本意没变：**空工作区/无雷达帧两个空串都不进哈希**，所以镜像算式里只有
    # 非空的那几维。若哪天有人把空串也塞进键，这条会立刻红。
    legacy = hashlib.sha256(
        f'{service.VERSION}:{service.FINGERPRINT}:{service.PLAN_REVISION}:'
        f'{service.OPERATIONS_FINGERPRINT}:42:clear::'
        f'{weather_control.MODE_MEASURED}'.encode()).hexdigest()[:24]
    assert service.identity(42, 'clear', None) == legacy
    assert service.identity(42, 'clear', None, weather_control.MODE_MEASURED, '') == legacy


# ------------------------------------------------------------ 气象口径

def test_weather_mode_is_per_workspace():
    weather_control.set_mode(weather_control.MODE_VIRTUAL, workspace=WS_A)
    assert weather_control.mode(WS_A) == weather_control.MODE_VIRTUAL
    assert weather_control.mode(WS_B) == weather_control.MODE_MEASURED
    assert weather_control.seed(WS_B) == weather_control.DEFAULT_SEED


def test_frame_counters_are_per_workspace():
    weather_control.reset()
    with workspace.bind(WS_A):
        weather_control.set_mode(weather_control.MODE_VIRTUAL)
    with workspace.bind(WS_B):
        assert weather_control.status()['framesServed']['virtual'] == 0
    with workspace.bind(WS_A):
        assert weather_control.status()['mode'] == weather_control.MODE_VIRTUAL


def test_the_context_does_not_leak_after_a_bound_block():
    with workspace.bind(WS_A):
        assert workspace.current() == WS_A
    assert workspace.current() == ''


# ------------------------------------------------------------ 运行日志

def test_a_weather_switch_row_only_shows_in_its_own_journal(monkeypatch, tmp_path):
    monkeypatch.setattr(operations, 'JOURNAL', tmp_path / 'journal.json')
    operations.note_source(weather_control.MODE_VIRTUAL, previous='measured', workspace=WS_A)

    session_a, session_b = 'a' * 24, 'b' * 24
    with workspace.bind(WS_A):
        assert [r['action'] for r in operations.journal(session_a)] == ['WEATHER_MODE']
    with workspace.bind(WS_B):
        assert operations.journal(session_b) == []
    # 未标识的调用方（巡检探针 / curl / 老单元测试）看不到任何带标识的全局行 ——
    # 反过来说，带标识的人也看不到历史遗留下来的那批无标识行。
    assert operations.journal(session_a) == []


# ------------------------------------------------------------ 评估台账

def _body(decision_id, created, scenario='clear'):
    return json.dumps({'decisionId': decision_id, 'createdAt': created, 'scenario': scenario,
                       'seed': 1, 'status': 'OPEN', 'task': {'regionId': 'R'}})


def _insert(db_path, decision_id, ws, created):
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE IF NOT EXISTS records (id TEXT NOT NULL, workspace TEXT NOT NULL DEFAULT '', "
               "created TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (workspace, id))")
    db.execute('INSERT OR REPLACE INTO records (id, workspace, created, body) VALUES (?,?,?,?)',
               (decision_id, ws, created, _body(decision_id, created)))
    db.commit()
    db.close()


def test_decision_history_is_per_workspace(monkeypatch, tmp_path):
    db_path = tmp_path / 'decisions.sqlite3'
    monkeypatch.setattr(decision_service, 'DB', db_path)
    _insert(db_path, 'a1', WS_A, '2026-10-14T00:00:00Z')
    _insert(db_path, 'b1', WS_B, '2026-10-14T00:00:01Z')

    with workspace.bind(WS_A):
        assert [r['decisionId'] for r in decision_service.history()] == ['a1']
    with workspace.bind(WS_B):
        assert [r['decisionId'] for r in decision_service.history()] == ['b1']
    assert decision_service.history() == []


def test_two_workspaces_can_hold_the_same_content_addressed_id(monkeypatch, tmp_path):
    """主键必须是 `(workspace, id)`，不能是 `id`。

    内容寻址 + `INSERT OR IGNORE` + 单主键的后果是：第二个人提交同一组输入时，
    他刚做完的那次评估会被 `IGNORE` 掉 —— 写入按所有判据都是"成功"，而他在历史里
    查不到自己那条。**一个人看不到自己的数据，比串号更难解释。**
    """
    db_path = tmp_path / 'decisions.sqlite3'
    monkeypatch.setattr(decision_service, 'DB', db_path)
    _insert(db_path, 'same', WS_A, '2026-10-14T00:00:00Z')
    _insert(db_path, 'same', WS_B, '2026-10-14T00:00:02Z')

    with workspace.bind(WS_A):
        assert [r['decisionId'] for r in decision_service.history()] == ['same']
    with workspace.bind(WS_B):
        assert [r['decisionId'] for r in decision_service.history()] == ['same']


def test_a_v1_database_migrates_and_stays_visible_to_unidentified_callers(monkeypatch, tmp_path):
    db_path = tmp_path / 'decisions.sqlite3'
    db = sqlite3.connect(db_path)
    db.execute('CREATE TABLE records (id TEXT PRIMARY KEY, created TEXT NOT NULL, body TEXT NOT NULL)')
    db.execute('INSERT INTO records VALUES (?,?,?)',
               ('old', '2026-10-13T00:00:00Z', _body('old', '2026-10-13T00:00:00Z')))
    db.execute('PRAGMA user_version = 1')
    db.commit()
    db.close()

    monkeypatch.setattr(decision_service, 'DB', db_path)
    assert [r['decisionId'] for r in decision_service.history()] == ['old']

    conn = sqlite3.connect(db_path)
    assert conn.execute('PRAGMA user_version').fetchone()[0] == decision_service.SCHEMA_VERSION
    assert conn.execute("SELECT workspace FROM records WHERE id='old'").fetchone()[0] == ''
    conn.close()


# ------------------------------------------------------------ 端到端（真的走 HTTP）

def test_the_http_header_reaches_the_route_handler(monkeypatch, tmp_path):
    """中间件 → 上下文 → 路由处理函数，这条链必须真的通。

    `@app.middleware('http')` 的中间件在事件循环里跑，而同步路由处理函数在 anyio 的
    工作线程里跑。上下文变量**会**随 `to_thread` 复制过去 —— 这句话必须由判据来说，
    不能靠读文档相信它：一旦不成立，症状是"所有工作区都读到空工作区那一份"，
    也就是隔离静默失效、而每个路由自己都不报错。
    """
    from fastapi.testclient import TestClient
    import main

    monkeypatch.setattr(operations, 'JOURNAL', tmp_path / 'journal.json')
    client = TestClient(main.app)
    a, b = {'X-ALC-Workspace': WS_A}, {'X-ALC-Workspace': WS_B}
    # 0.11.6（E-3）之后，切气象通道是**写操作**：不带 `X-ALC-Operator` 一律 403
    # （不带头 = 观察员 = 只读）。这两条测试本身代表"运维在工作区 A 切通道"，
    # 所以它必须带管理员身份 —— **修测试而不是放宽规则**：放宽之后任何脚本都能
    # 把通道切到虚拟，而那正是不该发生的事。
    # 同日 `bin/verify-remote.sh` 也是这么修的（同一个契约变更的两个消费方）。
    admin = {'X-ALC-Operator': 'admin'}

    assert client.get('/traffic/weather/mode', headers=b).json()['mode'] == 'measured'
    switched = client.post('/traffic/weather/mode', json={'mode': 'virtual'},
                           headers={**a, **admin})
    assert switched.status_code == 200
    assert switched.json()['mode'] == 'virtual'

    assert client.get('/traffic/weather/mode', headers=a).json()['mode'] == 'virtual'
    assert client.get('/traffic/weather/mode', headers=b).json()['mode'] == 'measured'


def test_the_query_parameter_works_as_a_fallback(monkeypatch, tmp_path):
    """WebSocket 握手在浏览器里发不了自定义头，所以退路必须有判据。"""
    from fastapi.testclient import TestClient
    import main

    monkeypatch.setattr(operations, 'JOURNAL', tmp_path / 'journal.json')
    client = TestClient(main.app)

    # 同上：写操作要管理员身份。这里走的是 **query 参数**那条退路（WebSocket 握手
    # 发不了自定义头），身份头仍然走请求头 —— 两者是两条不同的通道，都得验。
    assert client.post('/traffic/weather/mode?ws=' + WS_A, json={'mode': 'virtual'},
                       headers={'X-ALC-Operator': 'admin'}).json()['mode'] == 'virtual'
    assert client.get('/traffic/weather/mode?ws=' + WS_A).json()['mode'] == 'virtual'
    assert client.get('/traffic/weather/mode?ws=' + WS_B).json()['mode'] == 'measured'
