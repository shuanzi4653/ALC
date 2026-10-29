# -*- coding: utf-8 -*-
"""0.11.3 W 阶段后端探针：情景联动 / 历史回放 / σ 标定。

三个结论必须分别可判：
  A. 切到 unknown / clear 后，结论不再是"可按计划运行"，且走廊 KPI 给 None（不是 0）；
  B. 案例 fog-20250105 能出结论，且三站里至少一站跌进禁飞级；
  C. σ 已由 LOOCV 残差标定，且 ≤ 0.15（原公式给 0.41–0.45）。
"""
from __future__ import annotations

import json
import sys

from traffic import v2

FAIL = 0


def check(name, ok, detail=''):
    global FAIL
    print(('PASS  ' if ok else 'FAIL  ') + name + ('  | ' + detail if detail else ''))
    if not ok:
        FAIL += 1


def main() -> int:
    print('== A. 情景联动 ==')
    live = v2.overview(seed=42, scenario='live')
    print('  live  :', live['conclusion']['text'][:80])
    print('  planId:', live['planId'], 'scenario:', live['scenario'])
    check('live 结论带 planId', bool(live.get('planId')))
    check('live 结论不是气象中断口吻', '气象通道中断' not in live['conclusion']['text'])

    unknown = v2.overview(seed=42, scenario='unknown')
    print('  unk   :', unknown['conclusion']['text'])
    print('  kpis  :', [(k['key'], k['value']) for k in unknown['kpis']])
    check('unknown 结论写"暂停放行"', '暂停放行' in unknown['conclusion']['text'])
    check('unknown 不再说"可按计划运行"', '可按计划运行' not in unknown['conclusion']['text'])
    check('unknown 走廊 KPI 是 None 而不是 0',
          unknown['kpis'][0]['value'] is None and unknown['kpis'][1]['value'] is None)
    check('unknown 的 planId 与 live 不同', unknown['planId'] != live['planId'])

    clear = v2.overview(seed=42, scenario='clear')
    print('  clear :', clear['conclusion']['text'])
    check('clear 不给气象结论', '不给气象结论' in clear['conclusion']['text'])
    check('clear 也不说"可按计划运行"', '可按计划运行' not in clear['conclusion']['text'])

    print('\n== B. 历史回放 fog-20250105 ==')
    case = v2.overview(seed=42, scenario='live', case_id='fog-20250105')
    meta = case.get('case') or {}
    print('  case  :', meta.get('label'), '| 帧数', meta.get('frames'), '| timeBase', case.get('timeBase'))
    print('  concl :', case['conclusion']['text'][:110])
    print('  kpis  :', [(k['key'], k['value'], k['baseline']) for k in case['kpis']])
    check('案例可用', bool(meta.get('available')))
    check('案例 timeBase 是 2025-01-05', str(case.get('timeBase') or '').startswith('2025-01-05'))
    check('案例结论与实时不同', case['conclusion']['text'] != live['conclusion']['text'])
    high = case['kpis'][1]['value']
    check('案例出现禁飞级走廊（>0）', isinstance(high, int) and high > 0, '禁飞级=%s' % high)

    rows = case.get('corridors') or {}
    print('  worst :', json.dumps(rows.get('worst'), ensure_ascii=False)[:160])

    print('\n== C. σ 标定 ==')
    corr = v2.corridors(limit=5, case_id='fog-20250105')
    sig = [row.get('sigmaMean') for row in corr.get('items') or []]
    print('  sigmaMean:', sig)
    check('每行都有 σ', all(isinstance(x, (int, float)) for x in sig))
    check('σ ≤ 0.15', all(isinstance(x, (int, float)) and x <= 0.1501 for x in sig))
    rule = (corr.get('items') or [{}])[0].get('formula') or corr.get('formula') or {}
    print('  formula:', json.dumps(rule, ensure_ascii=False)[:200])

    print('\n== D. 能见度下界 ==')
    one = v2.corridor((case.get('corridors') or {}).get('worst', {}).get('corridorId') or 'CAR-1-02',
                      case_id='fog-20250105')
    for criterion in one.get('criteria') or []:
        if criterion.get('metric') == '能见度':
            print('  ', json.dumps(criterion, ensure_ascii=False))
            check('能见度带 display 字段', bool(criterion.get('display')))

    print('\n== 结果 ==')
    print('FAIL =', FAIL)
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
