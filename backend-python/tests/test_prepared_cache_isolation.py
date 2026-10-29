"""预序列化缓存（`_PREPARED`）的隔离判据。

**这条测试对应的缺陷是 2026-10-24 线上实测抓到的**，不是假想：

    ws-alpha → 200, sessionId=9538a9f497088955fa0c2270, md5=864b8a70…
    ws-beta  → 200, sessionId=9538a9f497088955fa0c2270, md5=864b8a70…   ← 同一份

两个工作区用完全相同的参数请求，`_PREPARED` 的键却算出同一个值，于是 B 拿到的
是 A 的**整份计划**（航班、处置建议、sessionId 全部）。这正是不该发生的那件事：
键里少了工作区这一维，那一维就被静默共享。

根因：旧键用 `result['fingerprint']` —— 它是 **代码指纹**（`traffic/*.py` 的哈希），
全工作区、全种子、全场景都是同一个值。现在键改用 `sessionId`（`identity()` 的产物，
已含 seed／scenario／气象快照／雷达通道／工作区）。

判据是纯函数级（`_prepared_key`），毫秒级、不建场。
"""
from __future__ import annotations

import pytest

from main import _prepared_key


def _ready(session_id: str, **extra) -> dict:
    row = {
        'status': 'READY',
        'sessionId': session_id,
        # 其余维度**故意完全相同**：只有 sessionId 不同。
        # 这正是线上复现时的形状（同 seed、同 scenario、同 baseTime、同通道）。
        'fingerprint': 'e7a96d38f3441efd',
        'seed': 42,
        'scenario': 'clear',
        'baseTime': '2026-10-24T10:00:00Z',
        'weatherMode': 'measured',
    }
    row.update(extra)
    return row


def test_两个工作区绝不能共用同一个缓存槽():
    """核心判据：sessionId 不同 ⇒ 键必须不同。修复前这里会是同一个元组。"""
    alpha = _prepared_key(_ready('9538a9f497088955fa0c2270'), 'slim')
    beta = _prepared_key(_ready('6f9832800c50dec8de9b6e3d'), 'slim')
    assert alpha is not None and beta is not None
    assert alpha != beta, (
        '两个工作区的预序列化缓存键相同 ⇒ B 会拿到 A 的整份计划。'
        f'alpha={alpha} beta={beta}'
    )


def test_同一份计划的不同投影不互相覆盖():
    """`fields` 仍要参与键：slim 与 full 是两份不同的载荷。"""
    plan = _ready('same-session-id')
    assert _prepared_key(plan, 'slim') != _prepared_key(plan, 'full')


def test_未就绪的计划不进缓存():
    """BUILDING / ERROR 的载荷每次都在变，缓存它们等于返回半成品。"""
    for status in ('BUILDING', 'SCHEDULED', 'ERROR', 'FAILED', None):
        assert _prepared_key({'status': status, 'sessionId': 'x'}, 'slim') is None


def test_没有计划键就不缓存():
    """拿不到 sessionId 时宁可多序列化一次，也不许两份计划共用一个槽。"""
    assert _prepared_key({'status': 'READY'}, 'slim') is None
    assert _prepared_key({'status': 'READY', 'sessionId': ''}, 'slim') is None
