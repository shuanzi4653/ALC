"""时间对齐地测量：航迹点是否落入「同一时刻」的风险面。

上一版探针犯了与它自己要抓的缺陷同源的错误——**口径错配**：
它拿 t=30 的气象面去比对一架在 t=200 恰好路过该坐标的班次。
风险面是**随风移动**的，所以「位置对上」不等于「时间对上」；
必须在**航迹点自己的分钟**取该分钟的气象面。

本脚本只做一件事：对每个航迹点 `(x, y, z, minute)`，取 `minute` 时刻的风险面，
分别判 FIELD（外缘，可飞）与 BAN（核心，不可飞）。

FIELD 命中是**正常**的——避让包络是按「半个计划时域的扫掠」算的，航迹会被推离
核心但可以合法穿过外缘的某些部分。**只有 BAN 命中才是缺陷。**

用法：backend-python\\.venv\\Scripts\\python.exe _probe_trajectory_aligned.py [seed] [scenario]
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


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    scenario = sys.argv[2] if len(sys.argv) > 2 else 'moving'
    print(f'# seed={seed} scenario={scenario}')

    started = time.perf_counter()
    snapshot = service.simulate(seed=seed, scenario=scenario)
    print(f'# simulate {time.perf_counter() - started:.2f}s')

    flights = [f for f in (snapshot.get('flights') or []) if f.get('points')]
    print(f'# 有航迹班次={len(flights)}')

    # 风险面只按「航迹实际用到的分钟」取，避免为 480 个分钟全部算一遍。
    minutes = sorted({int(point[3]) for flight in flights for point in flight['points']})
    print(f'# 航迹涉及的不同分钟数={len(minutes)}  ({minutes[0]}–{minutes[-1]})')

    cache = {}
    for minute in minutes:
        frame = service.weather_frame(seed, scenario, minute)
        fields, bans = [], []
        for cell in frame.get('cells') or []:
            field = cell.get('field')
            ban = cell.get('ban')
            if field:
                geometry = to_shape(field)
                if not geometry.is_empty:
                    fields.append(geometry)
            if ban:
                geometry = to_shape(ban)
                if not geometry.is_empty:
                    bans.append(geometry)
        cache[minute] = (fields, bans)

    field_hits = []
    ban_hits = []
    for flight in flights:
        hit_field = hit_ban = None
        for point in flight['points']:
            fields, bans = cache[int(point[3])]
            location = Point(point[0], point[1])
            if hit_ban is None and any(geometry.contains(location) for geometry in bans):
                hit_ban = (point[0], point[1], int(point[3]))
            if hit_field is None and any(geometry.contains(location) for geometry in fields):
                hit_field = (point[0], point[1], int(point[3]))
        if hit_field:
            field_hits.append((flight['id'], hit_field))
        if hit_ban:
            ban_hits.append((flight['id'], hit_ban))

    print()
    print(f'# 时间对齐后，航迹点落入风险**外缘 FIELD**（可飞，正常）的班次: {len(field_hits)}')
    print(f'# 时间对齐后，航迹点落入风险**核心 BAN**（不可飞，缺陷）的班次: {len(ban_hits)}')
    if ban_hits:
        print('# BAN 命中样例（航迹点时间必须与其自身分钟一致）:')
        for flight_id, hit in ban_hits[:10]:
            print(f'#   {flight_id}  xy=({hit[0]:.0f}, {hit[1]:.0f})  minute={hit[2]}')
    if field_hits and not ban_hits:
        print('# 说明：外缘命中属预期——避让包络按半时域扫掠计算，航迹被推离核心但可合法穿过外缘。')

    print(f'# 汇总: {json.dumps({"field": len(field_hits), "ban": len(ban_hits)}, ensure_ascii=False)}')


if __name__ == '__main__':
    main()
