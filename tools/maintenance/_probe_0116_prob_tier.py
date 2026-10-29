"""选 P_PROB_BLOCK / P_PROB_WATCH 的判据：**只有概率档自己的量能给它定档**。

`_probe_0116_close_cause.py` 已量到：计划路径（accepted/closed）根本不读这两个常量
（service.py 不 import v2，三档逐字相同）。所以「关闭 1430 → 123」不能拿来给概率档定档
—— 那等于用一把不接这条线的尺子去量这条线（M65：判据必须落在被告被**实际读取**的
那个对象上）。

概率档真正的作用面是 `v2.counterfactual()` 的三段式融合。可判读量：
  · `divergedProbability` —— 有多少架次**因为概率档**改判（0 = 结构上没参与）
  · `peakUnsafe`           —— 快照里最高的走廊不可飞概率（阈值必须在它以下才可能触发）

**为什么必须用历史案例场而不是当下的实时场**（本轮实测踩到）：
相隔一小时的两次运行给出 peak 0.1563 与 0.1080 —— 实时 METAR 一变，「概率档参不参与」
就从「参与（626 架次）」变成「不参与（0 架次）」。用这样的量给阈值定档，等于让结论
跟着天气走（M27：度量工具必须先自证是确定的，再谈数值）。
所以判据落在**可复现的案例场** `data/traffic/cases/fog-20250105.json`（ZYTX 997.8 m，
pMax 0.3131）上；实时场只作为「当期读数」记录，不参与判定。

三档（0.11.15 §七 的表）+ 负向对照（ablate=prob，必须让 divergedProbability 归 0）：
  0.50/0.30 · 0.27/0.18 · 0.25/0.15 · ablate=prob

用法：python tools/maintenance/_probe_0116_prob_tier.py
退出码：0 全部判据通过 / 1 有判据失败 / 2 无法测量
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend-python'
LAB = ROOT / '.run' / 'threshold-lab'
REPORT = LAB / 'prob-tier.json'
CASE_ID = 'fog-20250105'
sys.path.insert(0, str(BACKEND))

TIERS = [(0.50, 0.30), (0.27, 0.18), (0.25, 0.15)]
ADOPTED = (0.25, 0.15)


def wait_ready(limit_seconds=300):
    """先把计划建完再量。不建完就调 counterfactual 会拿到 NOT_READY，而建场线程
    在解释器退出后还在跑（`cannot schedule new futures after interpreter shutdown`）
    —— 那会让人以为"探针坏了"，其实只是问得太早（M57）。"""
    from traffic import service
    started = time.time()
    while time.time() - started < limit_seconds:
        result = service.session(42, 'live')
        if result.get('status') == 'READY':
            return result
        if result.get('status') not in ('BUILDING', None):
            return result
        time.sleep(5)
    return {'status': 'TIMEOUT'}


def measure(v2, field_payload, tiers):
    """同一份观测场下，逐档跑一次反事实重放。`v2.field` 被钉成这份场，
    三档之间的差异就只能来自阈值（否则差异不可归因）。"""
    v2.field = lambda force=False, case_id=None, _p=field_payload: _p  # type: ignore[assignment]
    rows = []
    for p_block, p_watch in tiers + [(None, None)]:
        ablate = '' if p_block is not None else 'prob'
        if p_block is not None:
            v2.P_PROB_BLOCK, v2.P_PROB_WATCH = p_block, p_watch
        result = v2.counterfactual(seed=42, scenario='live', policy='balanced', ablate=ablate)
        if result.get('status') != 'OK':
            raise RuntimeError('计划未就绪：%s' % result.get('status'))
        delta = result.get('delta') or {}
        rows.append({
            'pBlock': p_block, 'pWatch': p_watch, 'ablate': ablate or None,
            'peakUnsafe': result.get('peakUnsafe'),
            'reviewed': (result.get('scope') or {}).get('reviewed'),
            'exposureA': (result.get('a') or {}).get('exposure'),
            'exposureB': (result.get('b') or {}).get('exposure'),
            'diverged': delta.get('diverged'),
            'divergedProbability': delta.get('divergedProbability'),
            'divergedObservation': delta.get('divergedObservation'),
        })
    return rows


def main() -> int:
    LAB.mkdir(parents=True, exist_ok=True)
    from traffic import v2

    plan = wait_ready()
    if plan.get('status') != 'READY':
        print('无法测量：计划未就绪', plan.get('status'))
        return 2

    report = {'caseId': CASE_ID, 'fields': {}}
    live_field = v2.field(force=True)
    case_field = v2._case_field(CASE_ID)
    if not (live_field.get('stations') and case_field.get('stations')):
        print('无法测量：走廊概率场为空')
        return 2

    for name, payload in (('live', live_field), (CASE_ID, case_field)):
        rows = measure(v2, payload, TIERS)
        report['fields'][name] = rows
        print('场 %s（%d 站）' % (name, len(payload.get('stations') or [])))
        for row in rows:
            label = 'ablate=prob' if row['ablate'] else '%.2f/%.2f' % (row['pBlock'], row['pWatch'])
            print('  %-12s 改判 %-5s（概率档 %-5s · 观测档 %-5s）暴露 %s→%s · peak %.4f' % (
                label, row['diverged'], row['divergedProbability'], row['divergedObservation'],
                row['exposureA'], row['exposureB'], row['peakUnsafe'] or 0.0))

    case_rows = report['fields'][CASE_ID]
    real, control = case_rows[:-1], case_rows[-1]
    adopted = next(r for r in real if (r['pBlock'], r['pWatch']) == ADOPTED)
    legacy = next(r for r in real if (r['pBlock'], r['pWatch']) == (0.50, 0.30))
    verdict = {
        # K-1 的定义式判据：**采用的那一档**在可复现的案例场上必须真的改判过。
        'adoptedTierParticipates': (adopted['divergedProbability'] or 0) > 0,
        # M98：工作点必须落在概率分布之内。0.50 高于案例场峰值 0.3131 ⇒ 结构上不可能触发。
        'adoptedThresholdBelowPeak': (adopted['peakUnsafe'] or 0) > (adopted['pBlock'] or 1),
        # 旧阈值（0.8/0.5 时代的残影）必须在结构上死掉 —— 这条钉的是"为什么改"。
        'legacyTierStructurallyDead': (legacy['divergedProbability'] or 0) == 0,
        # 负向对照自证生效（M58）：关掉概率层后，概率档改判必须归 0。
        'controlZeroesProbability': (control['divergedProbability'] or 0) == 0,
    }
    report['verdict'] = verdict
    print('判据：', json.dumps(verdict, ensure_ascii=False))
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('报告 →', REPORT)
    return 0 if all(verdict.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
