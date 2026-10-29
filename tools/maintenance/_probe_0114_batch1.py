# -*- coding: utf-8 -*-
"""0.11.4 第一批（W-15+ / W-17a）验收探针。

判据全部是"数字与口径"，不是"文案出现过"：
  A. 载客走廊 53 条全部返回（不是 40），货运 216 条另计；
  B. `模型覆盖` 是算出来的（分子分母可核），且非 live 情景下是 None；
  C. 结论条不再出现"未评估"这种把分页说成没算的表述；
  D. 反事实的 diverged 与"处置架次"同向（不再出现改判 0 却降 3016）。
"""
from __future__ import annotations

import sys

from traffic import v2

FAIL = 0


def check(name: str, ok: bool, detail: str = '') -> None:
    global FAIL
    print(('PASS  ' if ok else 'FAIL  ') + name + ('  | ' + detail if detail else ''))
    if not ok:
        FAIL += 1


def main() -> int:
    print('== A. 走廊全量 ==')
    all_car = v2.corridors(limit=None, mode='CAR', case_id='fog-20250105')
    print('  CAR total=%s returned=%s mode=%s' %
          (all_car['total'], all_car['returned'], all_car['mode']))
    check('载客走廊 53 条全部返回', all_car['total'] == 53 and all_car['returned'] == 53)
    cargo = v2.corridors(limit=None, mode='DELIVERY', case_id='fog-20250105')
    print('  DELIVERY total=%s' % cargo['total'])
    check('货运走廊为 216 条', cargo['total'] == 216)
    limited = v2.corridors(limit=20, mode='CAR', case_id='fog-20250105')
    check('limit=20 仍然只返回 20（分页语义保留）',
          limited['returned'] == 20 and limited['total'] == 53)

    print('\n== B. 模型覆盖是算出来的 ==')
    live_like = v2.overview(seed=42, scenario='live', case_id='fog-20250105')
    ai = next(k for k in live_like['kpis'] if k['key'] == 'ai')
    print('  ai =', ai['value'], '| baseline =', ai['baseline'])
    check('覆盖值是数值', isinstance(ai['value'], (int, float)))
    check('baseline 写清分子分母', '/' in str(ai['baseline']) and '走廊' in str(ai['baseline']))
    unknown = v2.overview(seed=42, scenario='unknown')
    ai_u = next(k for k in unknown['kpis'] if k['key'] == 'ai')
    check('非 live 情景覆盖率为 None（不是 0）', ai_u['value'] is None, str(ai_u['value']))

    print('\n== C. 结论口径 ==')
    text = live_like['conclusion']['text']
    print('  case:', text)
    check('案例结论不再出现"未评估"', '未评估' not in text)
    check('案例结论写明观测已达禁飞级', '禁飞级' in text and '观测' in text)
    live = v2.overview(seed=42, scenario='live')
    print('  live:', live['conclusion']['text'][:140])
    live_text = live['conclusion']['text']
    check('实时结论不含"未评估"', '未评估' not in live_text)
    check('实时结论写明载客 53 条', '53' in live_text and '载客走廊' in live_text)
    check('实时结论交代货运走廊', '货运' in live_text)
    check('不再出现"（0%）"这种自相矛盾的最差值', '（0%）' not in live_text and '（0%）' not in text)

    print('\n== D. 反事实改判计数（需要完整计划；本地沙箱会拉雷达瓦片，失败就 SKIP）==')
    try:
        cf = v2.counterfactual(seed=42, scenario='live', case_id='fog-20250105')
    except Exception as exc:  # noqa: BLE001
        print('  SKIP 本地无法建场：%s' % type(exc).__name__)
        cf = None
    if cf is None:
        pass
    elif cf.get('status') != 'OK':
        print('  status', cf.get('status'), '（计划未就绪，跳过 D）')
    else:
        delta = cf['delta']
        b_handled = (cf['b'].get('rerouted') or 0) + (cf['b'].get('delayedFlights') or 0) + (cf['b'].get('cancelled') or 0)
        print('  A=%s B=%s diverged=%s (obs=%s prob=%s) | B处置=%s' %
              (cf['a']['exposure'], cf['b']['exposure'], delta['diverged'],
               delta.get('divergedObservation'), delta.get('divergedProbability'), b_handled))
        check('diverged > 0', delta['diverged'] > 0)
        check('diverged 与 B 处置架次同量级',
              abs(delta['diverged'] - b_handled) <= max(60, b_handled * 0.05),
              'diff=%s' % (delta['diverged'] - b_handled))
        check('观测档 + 概率档 拆分自洽',
              (delta.get('divergedObservation') or 0) + (delta.get('divergedProbability') or 0)
              >= delta['diverged'] - 1)

    print('\nFAIL =', FAIL)
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
