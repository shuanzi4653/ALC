"""姊妹通道预建 —— 「换通道不该再等一次全量重算」的判据。

预建那一条红了的症状是**容量悄悄变小**：预建占着一个 worker 的时候，真实请求
若被更早地判成 BUSY，并发容量就从 2 变成了 1，而界面上没有任何一句话解释。
所以这里同时钉住"预建要换通道/只落盘/会让位"，和"预建不吃 BUSY 名额"。

2026-10-15 本轮把这个文件里的**发布精度**那三条判据删掉了，因为那段设计已被回滚：
取整 x/y/z/t 会让规划期恰好压在上限上的速率越界（垂速比最大 3.000300 / 上限 3.0，
6521 对越界；水平速度占比最大 1.003623，3351 对越界），并让航迹端点不再等于
``network()`` 已发布的设施坐标（最大差 0.067 m）。也就是说**取整与载荷契约不兼容**，
不是"换个位数"能解决的。现在"发布出去的点必须与算出来的一模一样"这条判据在
``tests/test_traffic_network.py::test_flight_endpoints_rates_limits_and_geography``
（端点相等 + 逐段速率上限），不要再把精度判据加回来。

判据里出现的数字（110 MB、1056 MB、4 条上限）都是 2026-10-15 在真实载荷上量出来的。
"""
import inspect

import pytest

from traffic import service, weather_control

_BUILD_ENTRY_PARAMS = tuple(inspect.signature(service._build_entry).parameters)


def submitted_arg(call, name):
    """``POOL.submit(_build_entry, ...)`` 记录里按**名字**取一个实参。

    按名取而不是取下标：``retain`` 是后来追到参数表末尾的，将来再加一个参数，
    ``[-1]`` 就会安静地读到别的东西 —— 两个普通值，不会抛，只会比错槽位。
    """
    return dict(zip(_BUILD_ENTRY_PARAMS, call[1:]))[name]


@pytest.fixture
def clean_jobs():
    """``JOBS`` 是模块级全局，测试改完必须还原，否则污染同一进程里的其它用例。"""
    saved = dict(service.JOBS)
    service.JOBS.clear()
    try:
        yield service.JOBS
    finally:
        with service.LOCK:
            service.JOBS.clear()
            service.JOBS.update(saved)


class RecorderPool:
    """只记录、不执行。预建一旦真的跑起来就是一次 17 秒的仿真。"""

    def __init__(self):
        self.calls = []

    def submit(self, *args):
        self.calls.append(args)


# ---------------------------------------------------------------------------
# 姊妹通道预建
# ---------------------------------------------------------------------------

def test_prewarm_builds_the_other_channel_and_does_not_retain_it(monkeypatch, tmp_path,
                                                                 clean_jobs):
    """预建：换到**另一个**通道、``retain=False``（只落盘）、条目带 ``prewarm`` 标记。

    ``retain=False`` 是内存判据不是性能开关：一份计划在 Python 里约 110 MB
    （tracemalloc 实测），服务器可用内存 1056 MB，``JOBS`` 上限 4 条 —— 让姊妹通道
    也常驻会把上限顶到约 440 MB。
    """
    pool = RecorderPool()
    monkeypatch.setattr(service, 'STORE', tmp_path)
    monkeypatch.setattr(service, 'POOL', pool)

    service._prewarm_sibling(42, 'clear', None, service.weather_control.MODE_MEASURED)

    assert len(pool.calls) == 1, '没有为另一个通道排预建'
    assert submitted_arg(pool.calls[0], 'weather_mode') == weather_control.MODE_VIRTUAL
    assert submitted_arg(pool.calls[0], 'retain') is False, '预建被留在了内存里'
    sibling = submitted_arg(pool.calls[0], 'key')
    assert sibling != service.identity(42, 'clear', None, weather_control.MODE_MEASURED)
    assert service.JOBS[sibling]['prewarm'] is True


def test_prewarm_does_not_stack_when_a_build_is_already_running(monkeypatch, tmp_path,
                                                                clean_jobs):
    """已经有构建在跑就不再排队：唯一 worker 上一个就够。

    排第二个的效果是把**后面真实请求**的等待时间翻倍 —— 那正是预建要消除的东西，
    所以这条是"预建不能帮倒忙"的判据。
    """
    pool = RecorderPool()
    monkeypatch.setattr(service, 'STORE', tmp_path)
    monkeypatch.setattr(service, 'POOL', pool)
    service.JOBS['busy'] = {'status': 'BUILDING'}

    service._prewarm_sibling(42, 'clear', None, service.weather_control.MODE_MEASURED)

    assert pool.calls == [], '构建在跑的时候还排了一次预建'


def test_a_prewarm_yields_and_leaves_no_placeholder(monkeypatch, clean_jobs):
    """真实请求一到，预建立刻放弃，且**不留 ERROR 记录**。

    留 ERROR 的症状是：用户看到一句"运行计划计算失败，请查看本地 Python 日志"，
    而他从来没有发起过这次构建 —— 报一次并不存在的故障。
    """
    monkeypatch.setattr(service, 'POOL', RecorderPool())
    service.JOBS['pre-x'] = {'status': 'BUILDING', 'prewarm': True}

    def fake_simulate(seed, scenario, progress, live_snapshot, weather_mode):
        service.JOBS['real-user'] = {'status': 'BUILDING'}
        progress(50)  # 预建的每一次回调都应当先检查是否需要让位
        raise AssertionError('预建没有让位 —— 它仍占着唯一的 worker')

    monkeypatch.setattr(service, 'simulate', fake_simulate)
    service._build('pre-x', 42, 'clear', None, weather_control.MODE_MEASURED, False)

    assert 'pre-x' not in service.JOBS
    assert all(entry.get('status') != 'ERROR' for entry in service.JOBS.values())


def test_a_real_build_is_never_abandoned(monkeypatch, clean_jobs):
    """让位只对预建生效。真实构建即使有人在等也必须跑完 —— 否则请求方永远等不到计划。"""
    monkeypatch.setattr(service, 'POOL', RecorderPool())
    monkeypatch.setattr(service, 'STORE', __import__('pathlib').Path('/tmp/alc-prewarm-test'))
    seen = []

    def fake_simulate(seed, scenario, progress, live_snapshot, weather_mode):
        service.JOBS['someone-else'] = {'status': 'BUILDING'}
        progress(50)
        seen.append(True)
        return {'status': 'READY', 'flights': [], 'weatherMode': weather_mode}

    monkeypatch.setattr(service, 'simulate', fake_simulate)
    try:
        service.JOBS['real'] = {'status': 'BUILDING'}
        service._build('real', 42, 'clear', None, weather_control.MODE_MEASURED, True)
        assert seen == [True], '真实构建被让位逻辑中断了'
        assert service.JOBS['real']['status'] == 'READY'
    finally:
        import shutil
        shutil.rmtree('/tmp/alc-prewarm-test', ignore_errors=True)


def test_prewarm_placeholders_do_not_consume_the_user_busy_allowance(monkeypatch, tmp_path,
                                                                     clean_jobs):
    """``BUSY`` 只数用户发起的构建。

    否则预建会把并发容量从 2 悄悄削到 1，而界面上没有任何一句话解释 ——
    为性能做的改动顺手削掉并发度，是这类回归里最难被发现的一种。
    """
    pool = RecorderPool()
    monkeypatch.setattr(service, 'POOL', pool)
    monkeypatch.setattr(service, 'STORE', tmp_path)

    service.JOBS['pre'] = {'status': 'BUILDING', 'prewarm': True}
    service.JOBS['u1'] = {'status': 'BUILDING'}
    assert service.session(7, 'clear')['status'] == 'BUILDING', \
        '预建占着一个 worker 时，第二个真实请求被误判成 BUSY'

    service.JOBS['u2'] = {'status': 'BUILDING'}
    assert service.session(8, 'clear')['status'] == 'BUSY', \
        '两个真实构建在跑时应当判 BUSY，否则无限排队'
