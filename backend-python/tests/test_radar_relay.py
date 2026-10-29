"""客户端中继：把「服务器取不到、浏览器能取」这件事钉成判据。

这组判据要拦住的是一整类**自洽的错误**，而不是几个拼写：

1. **时次口径**。路径字面值是北京时。曾经用 UTC 拼路径，于是每次都取到 8 小时前
   的那一档 —— 它存在、返回 200、解码出的 dBZ 也合理，`slotAgeMinutes` 更是自洽地
   报出 ~5 分钟（拿错的时次和"现在"相减）。所有判据全绿，唯一不对的是那是清晨的天。
   所以这里既断言"字面值是北京时"，也断言"绝对时刻与 now 的差在发布滞后量级内"。

2. **中继载荷是外部输入**。一条长度不对的瓦片会解出一张位置正确、内容错误的图。
   判据必须证明它被**拒绝**，而不是被尽力解释。

3. **中继的作用域**。中继数据天然属于"某个访问者的浏览器"，所以它只应影响那个
   工作区。这条如果不钉，症状是"别人塞进来的图出现在我的屏上"，而两侧都不会报错。
"""
import base64
import datetime as dt
import struct

import pytest

from traffic import cma_tiles, service, weather_control

WS_A = 'ws-relay-000001'
WS_B = 'ws-relay-000002'


@pytest.fixture(autouse=True)
def clean():
    weather_control.reset()
    cma_tiles._CACHE.clear()
    yield
    weather_control.reset()
    cma_tiles._CACHE.clear()


def _tile_bytes(entries=()):
    """一块合法的瓦片：全 'missing'，可选地在给定 (row, col) 放 dBZ*10。"""
    grid = [cma_tiles.MISSING] * (cma_tiles.TILE_SIZE * cma_tiles.TILE_SIZE)
    for row, column, dbz in entries:
        grid[row * cma_tiles.TILE_SIZE + column] = int(round(dbz / cma_tiles.SCALE))
    return struct.pack(f'>{cma_tiles.TILE_SIZE * cma_tiles.TILE_SIZE}h', *grid)


def _entry(x=6, y=2, body=None):
    body = _tile_bytes() if body is None else body
    return {'x': x, 'y': y, 'data': base64.b64encode(body).decode('ascii')}


# ------------------------------------------------------- 1. 时次口径（北京时）

def test_slot_literal_is_beijing_time_not_utc():
    """**这条是本文件最重要的回归判据。**

    固定一个 UTC 时刻，路径里的 HH:MM 应当是**北京时**的那一格。
    用 UTC 会得到 07:24（错的，且是个存在时次，所以下游看不出来）。
    """
    now = dt.datetime(2026, 10, 15, 7, 24, tzinfo=dt.timezone.utc)
    slot = cma_tiles.latest_slot(now)
    assert f'{slot:%Y%m%d/%H/%M}' == '20261015/15/24', '路径字面值必须是北京时'
    assert slot.utcoffset() == dt.timedelta(hours=8)
    assert '20261015/15/24' in cma_tiles.tile_url(slot, 3, 6, 2)


def test_slot_instant_equals_the_real_moment():
    """字面值 → 绝对时刻必须减掉 8 小时；不减就会恒定 +8h，而两个错会互相抵消。"""
    now = dt.datetime(2026, 10, 15, 7, 24, tzinfo=dt.timezone.utc)
    instant = cma_tiles.slot_instant(cma_tiles.latest_slot(now))
    assert instant == dt.datetime(2026, 10, 15, 7, 24, tzinfo=dt.timezone.utc)


def test_slot_age_is_not_self_consistent_when_the_offset_is_wrong():
    """把口误写成 UTC 时，年龄会自己骗自己 —— 这里把这个差量钉住。

    同一个 UTC 时刻，若被当成北京时来读，年龄会差 8 小时。判据断言这个差是 480
    分钟而不是 0：0 就说明两个错误的参考系又互相抵消回去了。
    """
    now = dt.datetime(2026, 10, 15, 7, 24, tzinfo=dt.timezone.utc)
    literal_as_beijing = cma_tiles.latest_slot(now)
    naive_as_utc = literal_as_beijing.replace(tzinfo=dt.timezone.utc)
    delta = (naive_as_utc - now).total_seconds() / 60
    assert delta == pytest.approx(480, abs=6)


# --------------------------------------------------- 2. 中继载荷必须被拒绝

@pytest.mark.parametrize('entries, keyword', [
    ([], '没有任何瓦片'),
    ([{'x': 6, 'y': 2, 'data': base64.b64encode(b'too short').decode()}], '长度'),
    ([{'x': 6, 'y': 2, 'data': 'not*base64*'}], 'base64'),
    ([{'x': 6, 'y': 2}], 'base64'),          # 没有 data
    ([{'y': 2, 'data': base64.b64encode(_tile_bytes()).decode()}], 'x/y'),
])
def test_ingest_rejects_malformed_tiles(entries, keyword):
    now = dt.datetime(2026, 10, 15, 7, 24, tzinfo=dt.timezone.utc)
    slot = cma_tiles.latest_slot(now)
    with pytest.raises(cma_tiles.RelayPayloadRejected) as excinfo:
        cma_tiles.ingest_tiles(entries, zoom=3, slot=slot.isoformat(), now=now)
    assert keyword in str(excinfo.value)


def test_ingest_rejects_slot_off_the_publication_grid():
    now = dt.datetime(2026, 10, 15, 7, 24, tzinfo=dt.timezone.utc)
    with pytest.raises(cma_tiles.RelayPayloadRejected) as excinfo:
        cma_tiles.ingest_tiles([_entry()], zoom=3,
                               slot='2026-10-15T15:23:00+08:00', now=now)
    assert '网格' in str(excinfo.value)


def test_ingest_rejects_future_and_stale_slots():
    now = dt.datetime(2026, 10, 15, 7, 24, tzinfo=dt.timezone.utc)
    with pytest.raises(cma_tiles.RelayPayloadRejected) as future:
        cma_tiles.ingest_tiles([_entry()], zoom=3,
                               slot='2026-10-15T16:00:00+08:00', now=now)
    assert '未来' in str(future.value)
    old = cma_tiles.latest_slot(now) - dt.timedelta(minutes=6 * (cma_tiles.MAX_LOOKBACK_STEPS + 4))
    with pytest.raises(cma_tiles.RelayPayloadRejected) as stale:
        cma_tiles.ingest_tiles([_entry()], zoom=3, slot=old.isoformat(), now=now)
    assert '过旧' in str(stale.value)


# ------------------------------------------------- 3. 合法载荷 → 与直取同形的帧

def test_ingest_produces_the_direct_fetch_shape_and_names_the_transport():
    now = dt.datetime(2026, 10, 15, 7, 24, tzinfo=dt.timezone.utc)
    slot = cma_tiles.latest_slot(now)
    frame = cma_tiles.ingest_tiles([_entry(6, 2, _tile_bytes([(254, 169, 52.0)]))],
                                   zoom=3, slot=slot.isoformat(), now=now)
    # 与 frame() 同形的键：前端与 radar_field 读的就是这几个，少一个就是静默断链。
    for key in ('available', 'provenance', 'error', 'slot', 'slotLocal', 'slotAgeMinutes',
                'cells', 'degreesPerCell', 'gridTiles', 'stats'):
        assert key in frame, f'中继帧缺少 {key}'
    assert frame['available'] is True
    assert frame['provenance']['provider'] == 'CMA_DATA_NET'      # 来源没变
    assert frame['provenance']['transport'] == 'CLIENT_RELAY'     # 变的是传输路径
    assert frame['slot'] == '2026-10-15T07:24:00Z'
    assert frame['slotLocal'] == '2026-10-15 15:24 +08'
    assert frame['stats']['maxDbz'] == pytest.approx(52.0)
    assert frame['gridTiles'] == [(6, 2)]


# ------------------------------------------- 4. 控制器：优先中继、过期即弃、按工作区

def _relayed_frame(now=None, dbz=48.0):
    now = now or dt.datetime.now(dt.timezone.utc)
    slot = cma_tiles.latest_slot(now)
    return cma_tiles.ingest_tiles([_entry(6, 2, _tile_bytes([(254, 169, dbz)]))],
                                  zoom=3, slot=slot.isoformat(), now=now)


def test_radar_frame_prefers_a_fresh_relay_over_a_failing_direct_fetch(monkeypatch):
    def boom(**kwargs):
        raise AssertionError('有新鲜中继帧时不应再去直取')
    monkeypatch.setattr(cma_tiles, 'frame', boom)
    weather_control.ingest_relay(_relayed_frame(), workspace=WS_A)
    frame = weather_control.radar_frame(workspace=WS_A)
    assert frame['available'] is True
    assert frame['mode'] == 'measured'
    assert frame['provenance']['transport'] == 'CLIENT_RELAY'


def test_stale_relay_is_dropped_and_direct_fetch_is_used_again(monkeypatch):
    called = {}

    def direct(**kwargs):
        called['yes'] = True
        return {'available': False, 'error': '源站拒绝', 'cells': [], 'slot': None,
                'provenance': {'provider': 'CMA_DATA_NET'}, 'degreesPerCell': 0.1}
    monkeypatch.setattr(cma_tiles, 'frame', direct)
    weather_control.ingest_relay(_relayed_frame(), workspace=WS_A)
    # 让这份中继过期：不动时钟，直接把存活期压成负数。
    monkeypatch.setattr(weather_control, 'RELAY_TTL_SECONDS', -1)
    frame = weather_control.radar_frame(workspace=WS_A)
    assert called.get('yes') is True
    assert frame['available'] is False


def test_relay_is_scoped_to_the_workspace_that_sent_it():
    _relayed_frame(dbz=48.0)
    weather_control.ingest_relay(_relayed_frame(dbz=48.0), workspace=WS_A)
    fresh_a = weather_control.radar_frame(workspace=WS_A)
    # B 没有中继过 ⇒ 拿到的是"要去找浏览器帮忙"的说明，而不是 A 的那一份图。
    relay_b = cma_tiles.relay_instructions(3)
    assert fresh_a['provenance']['transport'] == 'CLIENT_RELAY'
    assert relay_b['needed'] is True
    assert weather_control._fresh_relay(workspace=WS_B) is None


def test_relay_instructions_carry_the_timezone_discipline():
    """下发的说明必须带上时次口径：浏览器按本地时区拼路径会稳定取到错的时次。"""
    relay = cma_tiles.relay_instructions(3)
    assert relay['needed'] is True
    assert relay['slotTimezoneOffsetMinutes'] == 480
    assert relay['cadenceMinutes'] == cma_tiles.CADENCE_MINUTES
    assert relay['tileBytes'] == cma_tiles.TILE_SIZE * cma_tiles.TILE_SIZE * cma_tiles.BYTES_PER_CELL
    assert '{HH}' in relay['tileUrlTemplate'] and '{MM}' in relay['tileUrlTemplate']
    assert relay['postTo'] == '/api/traffic/radar/tiles'


# ------------------------------------- 5. 中继帧进计划键：迟到一步的图不能共享旧计划
#
# 这一节钉的是 2026-10-15 那次线上失效的**另一半**。当时的顺序是"先建计划、再取气象、
# 再中继"：计划那次取帧拿到的是服务器直取，而在云端出口上那是整站 403 ⇒ 计划里没有雷达
# 几何；地图随后读到中继帧、画出一片回波。屏幕上于是是 12 架载具停在禁入区内核里、
# 没有任何绕行 —— 而计划、地图、键、字段全都是合法的。
# 顺序调过来（前端先中继再建计划）只解决"这次"，解决"下次"的是键：中继落地前后必须是
# 两份计划，不是一份计划加一句假话。

def test_a_relayed_frame_changes_the_plan_key():
    """中继落地 ⇒ 标识从空串变成时次 ⇒ 计划键必须跟着变。"""
    before = weather_control.frame_identity(weather_control.MODE_MEASURED, WS_A)
    assert before == '', '没有中继帧时不该有标识：空串才让改造前的键保持不变'
    without = service.identity(42, 'live', 'snap-1', weather_control.MODE_MEASURED, WS_A,
                              radar=before)

    frame = _relayed_frame(dbz=48.0)
    weather_control.ingest_relay(frame, workspace=WS_A)
    after = weather_control.frame_identity(weather_control.MODE_MEASURED, WS_A)
    assert after == frame['slot'], '中继帧的时次就是它的标识'
    with_relay = service.identity(42, 'live', 'snap-1', weather_control.MODE_MEASURED, WS_A,
                                 radar=after)
    assert with_relay != without, '中继落地后键没变：session() 会把那份没有雷达几何的计划原样交还'


def test_the_key_is_a_pure_function_of_the_radar_identity_it_is_given():
    """空标识与 ``None`` 必须是同一个键，否则"改造前行为保持"这条判据无从量起。"""
    base = service.identity(42, 'live', 'snap-1', weather_control.MODE_MEASURED, WS_B)
    assert service.identity(42, 'live', 'snap-1', weather_control.MODE_MEASURED, WS_B,
                            radar=None) == base
    assert service.identity(42, 'live', 'snap-1', weather_control.MODE_MEASURED, WS_B,
                            radar='') == base


def test_the_virtual_channel_has_no_frame_identity():
    """虚拟回波由 (种子, 时次) 决定，没有外部观测进来 —— 这两维都已经在键里了。

    若不这样，一份中继帧会顺带把虚拟通道的计划键也挪一次：那是"键里多了不该有的一维"，
    与少了哪一维同样难查。
    """
    weather_control.ingest_relay(_relayed_frame(), workspace=WS_A)
    assert weather_control._fresh_relay(workspace=WS_A) is not None
    assert weather_control.frame_identity(weather_control.MODE_VIRTUAL, WS_A) == ''


def test_a_relay_arriving_late_does_not_reuse_the_plan_built_without_one(monkeypatch, tmp_path):
    """线上的次序原样重演一遍：建计划 → 中继落地 → 再来一次。

    第二次必须要求**重建**。此前它命中了第一次那个键，于是操作员看到的是"地图上有回波、
    计划里没有绕行"，而所有字段都合法 —— 这正是这次线上失效的形状。
    """
    submitted = []

    class Recorder:
        def submit(self, *args):
            submitted.append(args)

    monkeypatch.setattr(service, 'STORE', tmp_path)
    monkeypatch.setattr(service, 'POOL', Recorder())
    saved = dict(service.JOBS)
    try:
        service.JOBS.clear()
        first = service.session(42, 'clear', WS_A)
        assert first['status'] == 'BUILDING'

        weather_control.ingest_relay(_relayed_frame(dbz=48.0), workspace=WS_A)

        second = service.session(42, 'clear', WS_A)
        assert second['status'] == 'BUILDING', \
            '中继落地后复用了那份没有雷达几何的计划'
        assert second['sessionId'] != first['sessionId'], '两次拿到的是同一把钥匙'
    finally:
        with service.LOCK:
            service.JOBS.clear()
            service.JOBS.update(saved)


def test_failed_direct_fetch_carries_the_relay_instructions(monkeypatch):
    """服务器取不到时，载荷里必须带着"让浏览器代取"的说明。

    否则前端只能显示一句"不可用"，真正的下一步丢在服务端 —— 那正是这条通道
    长期以来的状态。
    """
    def boom(slot, zoom, x, y, opener=None):
        # `_fetch_one` 是**位置调用** fetch_tile(attempt, zoom, x, y)，签名必须照抄，
        # 否则失败会以 TypeError 的形式冒出来，看起来像"这条路径坏了"而不是"用例写错了"。
        raise cma_tiles.RadarTileUnavailable('HTTP 403')
    monkeypatch.setattr(cma_tiles, 'fetch_tile', boom)
    frame = cma_tiles.frame(zoom=3, grid=((6, 2),), force=True)
    assert frame['available'] is False
    assert frame['relay']['needed'] is True
    assert frame['relay']['zoom'] == 3


# -------------------------------------------------------------- 5. HTTP 契约

def test_http_endpoint_accepts_a_valid_relay():
    from fastapi.testclient import TestClient
    import main
    now = dt.datetime.now(dt.timezone.utc)
    slot = cma_tiles.latest_slot(now)
    body = {'slot': slot.isoformat(), 'zoom': 3,
            'tiles': [{'x': 6, 'y': 2,
                       'data': base64.b64encode(_tile_bytes([(254, 169, 52.0)])).decode()}]}
    client = TestClient(main.app)
    response = client.post('/traffic/radar/tiles', json=body,
                           headers={'X-ALC-Workspace': WS_A})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['stored'] is True
    assert payload['gridTiles'] == [[6, 2]]


def test_http_endpoint_rejects_a_short_tile_with_422_not_500():
    """长度不对是**调用方的问题**（422）。报成 500 会让前端把"取错了"重试成网络抖动。"""
    from fastapi.testclient import TestClient
    import main
    slot = cma_tiles.latest_slot(dt.datetime.now(dt.timezone.utc))
    body = {'slot': slot.isoformat(), 'zoom': 3,
            'tiles': [{'x': 6, 'y': 2, 'data': base64.b64encode(b'short').decode()}]}
    client = TestClient(main.app)
    response = client.post('/traffic/radar/tiles', json=body,
                           headers={'X-ALC-Workspace': WS_A})
    assert response.status_code == 422
    assert '长度' in response.json()['detail']
