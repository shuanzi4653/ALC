"""计划仓（`.run/traffic/`）的容量判据。

**对应 2026-10-24 线上实测**：同一代次积了 20 份 / 494 MB，后来涨到 **694 MB**。
`_prune_stale_store()` 只清「指纹不匹配」的旧代次 —— 而指纹只在改代码时才变，
于是同一代次内的文件**完全没有上限**，每个新工作区都会写一份 25 MB。

判据分三件事，缺一条都会让"清理看起来在工作"：
  1. 同代次的文件数必须收敛到 `KEEP_PER_GENERATION` 以内；
  2. **最近动过的文件不许删** —— 那可能正是有人正在轮询的那一份，
     删了会让下一次请求从"读盘 0.5 秒"退化成"重建 20 秒"（体验回退）；
  3. 旧代次的文件照旧必须清掉（原有的行为不能被新逻辑挤掉）。

用 `monkeypatch` 把 `STORE` 指到临时目录：**判据不许碰真实的计划仓**，
否则跑一次测试就会把演示环境正在用的缓存删掉。
"""
from __future__ import annotations

import json
import os
import time

import pytest

from traffic import service


def _write(path, fingerprint: str, age_seconds: float):
    path.write_text(json.dumps({'fingerprint': fingerprint, 'status': 'READY'}),
                    encoding='utf-8')
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))
    return path


def test_同代次缓存必须收敛到上限以内(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'STORE', tmp_path)
    # 12 份同代次、都是 2 小时前写的（避开"最近 10 分钟保护"）
    for i in range(12):
        _write(tmp_path / f'{i:04d}.json', service.FINGERPRINT, age_seconds=7200 + i * 60)

    service._prune_stale_store()

    left = list(tmp_path.glob('*.json'))
    assert len(left) <= service.KEEP_PER_GENERATION, (
        f'同代次仍留着 {len(left)} 份（上限 {service.KEEP_PER_GENERATION}）——'
        ' 磁盘会无界增长'
    )
    # 留的必须是最新的那几份。注意造数据时 `i` 越大越旧（age 随 i 增加），
    # 所以"最新"是 i 最小的那些 —— 断言按 mtime 语义写，不要按文件名大小直觉写。
    kept_names = sorted(p.stem for p in left)
    assert kept_names == [f'{i:04d}' for i in range(len(left))], kept_names


def test_最近写过的缓存不许被淘汰(tmp_path, monkeypatch):
    """正在轮询的那一份可能刚写过；删它等于把读盘换成重建。"""
    monkeypatch.setattr(service, 'STORE', tmp_path)
    for i in range(service.KEEP_PER_GENERATION + 4):
        _write(tmp_path / f'old-{i:02d}.json', service.FINGERPRINT, age_seconds=7200 + i)
    hot = _write(tmp_path / 'hot.json', service.FINGERPRINT, age_seconds=5)  # 5 秒前

    service._prune_stale_store()

    assert hot.exists(), '最近 10 分钟内写过的缓存在上限淘汰里被删掉了'


def test_旧代次照旧必须清掉(tmp_path, monkeypatch):
    """新增的容量逻辑不许把「清旧代次」这条老职责挤掉。"""
    monkeypatch.setattr(service, 'STORE', tmp_path)
    stale = _write(tmp_path / 'stale.json', 'deadbeefdeadbeef', age_seconds=60)
    live = _write(tmp_path / 'live.json', service.FINGERPRINT, age_seconds=60)

    service._prune_stale_store()

    assert not stale.exists(), '指纹不匹配的旧代次没被清掉'
    assert live.exists(), '当前代次的缓存被误删'


def test_认不出指纹的文件按旧代次处理(tmp_path, monkeypatch):
    """读不出 fingerprint 就当过期 —— 安全方向是多算一次，不是留着占盘。"""
    monkeypatch.setattr(service, 'STORE', tmp_path)
    broken = tmp_path / 'broken.json'
    broken.write_text('{"no_fingerprint": true}', encoding='utf-8')
    stamp = time.time() - 3600
    os.utime(broken, (stamp, stamp))

    service._prune_stale_store()

    assert not broken.exists()
