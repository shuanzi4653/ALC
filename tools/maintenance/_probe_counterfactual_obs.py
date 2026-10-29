# -*- coding: utf-8 -*-
"""反事实对照在"观测已达禁飞级"的案例上是否真的产生差值（0.11.3 追加）。

判据三条：
  1. A 组暴露 > 0（规则放行 → 飞进雾里）；
  2. B 组暴露 < A 组（AI 改判）；
  3. 结论句与数字同向（不会出现"两组都没有"而 A>0 的自相矛盾）。
"""
from __future__ import annotations

import sys

from traffic import v2


def main() -> int:
    failed = 0
    for label, kwargs in (('实时', dict(seed=42, scenario='live')),
                          ('案例', dict(seed=42, scenario='live', case_id='fog-20250105'))):
        data = v2.counterfactual(**kwargs)
        print('\n== %s ==' % label)
        if data.get('status') != 'OK':
            print('  status', data.get('status'), '· 计划还没算完，跳过')
            continue
        a, b = data['a'], data['b']
        print('  A 暴露 %s | B 暴露 %s | Δ %s (%s%%)' %
              (a['exposure'], b['exposure'], data['delta']['exposure'],
               data['delta']['exposurePct']))
        print('  B 取消 %s · 延误 %s 分钟 / %s 班' %
              (b['cancelled'], b['delayMinutes'], b.get('delayedFlights')))
        print('  peak', data.get('peakUnsafe'))
        print('  结论', data['conclusion'])

    print('\n== live 概览（应当仍是 0 禁飞）==')
    live = v2.overview(seed=42, scenario='live')
    print('  high', live['kpis'][1]['value'], '| pending', live['kpis'][0]['value'])
    print('  concl', live['conclusion']['text'][:90])
    print('\nFAIL =', failed)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
