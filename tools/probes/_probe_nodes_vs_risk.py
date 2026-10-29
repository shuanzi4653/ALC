"""测量：枢纽 / 配送节点 / 航迹 与（合并后）风险区域的空间关系。

回答用户第 3 项的后半句：「可能需要根据新的风险区域重新去做起始点位置、配送点位置和航迹」。

三件事必须分开看，否则结论会互相污染：

  场区（FIELD）  —— 本系统推演的天气不利区，会随风移动。它不改变设施坐标，
                    只应改变「什么时候能飞、走哪条路」。
  枢纽 / 节点     —— 城市代表坐标与商户/收货点，是**模拟运行数据里的固定设施**。
                    因为一阵雨把配送点挪走，是把气象问题写成规划问题。
  航迹           —— 唯一应当随风险区变化的东西，而 `swept()` 已经是它的避让依据。

所以本脚本要给出的是**事实**，不是主张：有多少设施真的落在风险面上，
以及绕行机制是否已经覆盖它们。若「落入」数长期为 0，则「重做起始点」是不必要的改动。

坐标口径：`pads[].xy` 与 `flight['points']` 的 `(x, y, z, minute)` 都是**投影米**；
`frame()` 里 `field/ban/caution` 也是投影米（已与 `boundary()` 求交）。因此两边可直接比较。

用法：backend-python\\.venv\\Scripts\\python.exe _probe_nodes_vs_risk.py [seed] [scenario]
"""

from __future__ import annotations
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402

import json
import time


from shapely.geometry import Point, shape as to_shape  # noqa: E402

from traffic import service  # noqa: E402


BINS = [0, 30, 60, 120, 240, 360, 480]


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    scenario = sys.argv[2] if len(sys.argv) > 2 else 'moving'
    print(f'# seed={seed} scenario={scenario}')

    started = time.perf_counter()
    snapshot = service.simulate(seed=seed, scenario=scenario)
    elapsed = time.perf_counter() - started

    net = service.network()
    pads = [pad for pad in net['pads'] if pad.get('xy')]
    print(f'# simulate {elapsed:.2f}s; pads={len(pads)}')

    per_bin = {}
    for minute in BINS:
        frame = service.weather_frame(seed, scenario, minute)
        cells = frame.get('cells') or []
        fields = []
        for cell in cells:
            geometry = cell.get('field')
            if geometry:
                candidate = to_shape(geometry)
                if not candidate.is_empty:
                    fields.append(candidate)
        per_bin[minute] = fields

    total_inside = 0
    for minute in BINS:
        fields = per_bin[minute]
        inside = []
        for pad in pads:
            point = Point(pad['xy'][:2])
            if any(geometry.contains(point) for geometry in fields):
                inside.append(pad)
        total_inside += len(inside)
        names = ', '.join(f"{pad.get('id')}" for pad in inside[:8])
        suffix = f'  {names}' if names else ''
        print(f'  t={minute:>3} min  区域={len(fields):>2}  落入设施的枢纽/节点 {len(inside):>3}{suffix}')

    flights = snapshot.get('flights') or []
    accepted = [f for f in flights if f.get('points')]
    reasons = {}
    for flight in flights:
        if flight.get('points'):
            continue
        reason = flight.get('reason') or 'UNKNOWN'
        reasons[reason] = reasons.get(reason, 0) + 1
    print(f'# flights={len(flights)} 有航迹={len(accepted)}')
    print(f'# 关闭原因: {json.dumps(reasons, sort_keys=True, ensure_ascii=False)}')
    print(f'# 绕行(WEATHER_DETOUR)={sum(1 for f in accepted if f.get("reason") == "WEATHER_DETOUR")}')

    crossings = {}
    for minute in BINS:
        fields = per_bin[minute]
        hits = 0
        for flight in accepted:
            for point in flight['points'][::2]:
                if any(geometry.contains(Point(point[0], point[1])) for geometry in fields):
                    hits += 1
                    break
        crossings[minute] = hits
    print(f'# 航迹落入风险面的班次（按时刻）: {json.dumps(crossings, sort_keys=True)}')
    print(f'# 设施落入风险面合计（7 个时刻求和）: {total_inside}')


if __name__ == '__main__':
    main()
