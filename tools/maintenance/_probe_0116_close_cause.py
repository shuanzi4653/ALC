"""0.11.15 §七 未收敛项的对照实验：关闭班次 1430 → 123 到底由谁引起。

背景（`docs/0.11.15-执行记录.md` §七）：0.11.14 是 6330 / 1430（18.4%），
0.11.15 是 7637 / 123（1.6%）。文档给的候选原因是「概率档阈值 0.25/0.15 让
`v2._fuse()` 的『降级为可飞』分支走进更多班次」。**这个候选原因必须先被证伪或证实**，
不能直接照它去调参 —— M3（先问"我的期望有依据吗"）与 M64（归因标签必须由成因判据产出）。

实验设计（每条都能被机器判读）：

  A 静态：计划构建路径（`traffic/service.py::_plan_trajectory`）到底读了 `operations` 的哪些键。
    `_fuse` 住在 `traffic/v2.py`，只有 `counterfactual()` 调它 —— 若计划路径根本不 import v2，
    概率档在结构上就不可能改变 accepted/closed。

  B 冻结快照的三档对照：同一份气象快照，P_BLOCK/P_WATCH = 0.50/0.30 · 0.27/0.18 · 0.25/0.15，
    各建一次计划。若三次 accepted/closed **逐字相同**，候选原因被证伪。

  C 真正的杠杆：同一份快照下扫 `extremeGustMps`（几何阈值，决定风险区内核），
    因为它是计划路径唯一会读到的阵风量。

  D 快照本身：站点级能见度/阵风计数。若当期快照里没有一条站点越过任一判据，
    那 1430 这个数在**当期快照上**本来就不该出现（它属于 10-23 早些时候的那份快照）。

用法：
  python tools/maintenance/_probe_0116_close_cause.py            # A + D + B（三次重建）
  python tools/maintenance/_probe_0116_close_cause.py --levers   # 追加 C（再两次重建）
  python tools/maintenance/_probe_0116_close_cause.py --reuse    # 复用已冻结快照
退出码：0 全部量到 / 1 有实验失败 / 2 无法测量（快照取不到）
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend-python'
LAB = ROOT / '.run' / 'threshold-lab'
SNAPSHOT_FILE = LAB / 'snapshot.json'
REPORT_FILE = LAB / 'report.json'

sys.path.insert(0, str(BACKEND))

TIERS = [(0.50, 0.30), (0.27, 0.18), (0.25, 0.15)]


# --- A 静态：计划路径读了哪些 operations 键 ---------------------------------
def plan_path_operations_keys() -> dict:
    """AST 扫 `service.py`：`operations()[...]` 的键集合 + 是否 import 了 v2。"""
    source = (BACKEND / 'traffic' / 'service.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    keys, imports_v2 = [], False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or '').endswith('v2'):
            imports_v2 = True
        if isinstance(node, ast.Name) and node.id == 'v2':
            imports_v2 = True
        # operations()['key']
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name) and node.value.func.id == 'operations'
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
            keys.append(node.slice.value)
    # 跨模块：weather.py / nowcast.py 里的阈值是否进计划路径，由 B 段的实测回答。
    return {'planPathOperationsKeys': sorted(set(keys)), 'serviceImportsV2': imports_v2}


def snapshot_station_stats(snapshot: dict) -> dict:
    rows = snapshot.get('observations') or snapshot.get('rows') or []
    vis = [r.get('visibilityM') for r in rows if r.get('visibilityM') is not None]
    gust = [r.get('windGusts10mMps') for r in rows if r.get('windGusts10mMps') is not None]
    def count(seq, fn):
        return sum(1 for v in seq if fn(v))
    return {
        'stations': len(rows),
        'visSamples': len(vis), 'visMin': min(vis) if vis else None,
        'visLt1000': count(vis, lambda v: v < 1000),
        'visLt3000': count(vis, lambda v: v < 3000),
        'gustSamples': len(gust), 'gustMax': max(gust) if gust else None,
        'gustGt10': count(gust, lambda v: v > 10.0),
        'gustGt115': count(gust, lambda v: v > 11.5),
        'gustGt17': count(gust, lambda v: v > 17.0),
        'capturedAt': snapshot.get('generatedAt') or snapshot.get('snapshotId') or snapshot.get('id'),
        'source': snapshot.get('source'),
        'qualityFlags': snapshot.get('qualityFlags'),
    }


# --- B/C 重建 -----------------------------------------------------------------
def build_once(snapshot: dict, p_block: float, p_watch: float, extreme_gust: float | None) -> dict:
    from traffic import v2, weather
    v2.P_PROB_BLOCK = p_block
    v2.P_PROB_WATCH = p_watch
    if extreme_gust is not None:
        weather.EXTREME_WIND_GUST_MPS = extreme_gust
    from traffic import service
    started = time.time()
    payload = service.simulate(seed=42, scenario='live', live_snapshot=snapshot,
                               weather_mode='measured')
    stats = payload.get('stats') or {}
    return {
        'pBlock': p_block, 'pWatch': p_watch, 'extremeGust': extreme_gust,
        'seconds': round(time.time() - started, 1),
        'accepted': stats.get('accepted'), 'closed': stats.get('closed'),
        'flights': stats.get('flights'),
        'closedRatio': (round((stats.get('closed') or 0) / max(1, stats.get('flights') or 1), 4)),
        'closedByReason': stats.get('closedByReason'),
        'mapCar': stats.get('mapCar'), 'mapDelivery': stats.get('mapDelivery'),
        'arrivalMax': stats.get('arrivalMax'),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--levers', action='store_true', help='追加 extremeGust 扫描')
    parser.add_argument('--reuse', action='store_true', help='复用已冻结快照')
    parser.add_argument('--fog', action='store_true', help='追加雾档注入实验（消融，不对外）')
    args = parser.parse_args()

    LAB.mkdir(parents=True, exist_ok=True)
    report: dict = {'static': plan_path_operations_keys()}
    print('A 计划路径读到的 operations 键：', report['static']['planPathOperationsKeys'])
    print('  service.py 是否 import v2：', report['static']['serviceImportsV2'])

    from traffic.catalog import cities
    if SNAPSHOT_FILE.exists() and args.reuse:
        snapshot = json.loads(SNAPSHOT_FILE.read_text(encoding='utf-8'))
        print('快照：复用', SNAPSHOT_FILE)
    else:
        from traffic.weather_sources import weather_snapshot
        snapshot = weather_snapshot(cities(), force=True)
        if not snapshot.get('available'):
            print('无法测量：气象快照不可用', snapshot.get('error') or snapshot.get('qualityFlags'))
            return 2
        SNAPSHOT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
        print('快照：新取并冻结 →', SNAPSHOT_FILE)
    report['snapshot'] = snapshot_station_stats(snapshot)
    print('D 快照站点统计：', json.dumps(report['snapshot'], ensure_ascii=False))

    report['tiers'] = []
    for p_block, p_watch in TIERS:
        row = build_once(snapshot, p_block, p_watch, None)
        report['tiers'].append(row)
        print(f"B {p_block:.2f}/{p_watch:.2f} → accepted {row['accepted']} / closed {row['closed']}"
              f"（{row['closedRatio']:.1%}）· {row['seconds']}s · {row['closedByReason']}")

    identical = len({json.dumps([r['accepted'], r['closed'], r['closedByReason']], sort_keys=True)
                     for r in report['tiers']}) == 1
    report['tiersIdentical'] = identical
    print('B 三档是否逐字相同：', identical)

    if args.levers:
        report['levers'] = []
        for gust in (17.0, 15.0, 13.0, 11.5):
            row = build_once(snapshot, 0.25, 0.15, gust)
            report['levers'].append(row)
            print(f"C extremeGust {gust} → accepted {row['accepted']} / closed {row['closed']}"
                  f"（{row['closedRatio']:.1%}）· {row['seconds']}s · {row['closedByReason']}")

    if args.fog:
        # E 雾档注入：把逐时能见度压到 900 m（低于 1000 m 判据）再建一次。
        # **这是消融实验，不是业务口径** —— 它只回答一个问题：关闭班次回到 1400 量级
        # 需要哪个量。`fog_tiers()` 读的是快照里的能见度，所以这一步不改任何代码、
        # 不改任何阈值，只改输入。结果**不得**写进任何对外数字。
        def inject(count):
            foggy = json.loads(json.dumps(snapshot))
            rows = foggy.get('observations') or []
            def min_vis(row):
                values = [v for v in ((row.get('hourly') or {}).get('visibility') or [])
                          if isinstance(v, (int, float))]
                return min(values) if values else 1e9
            chosen = sorted(rows, key=min_vis)[:count]
            for row in chosen:
                hourly = row.get('hourly') or {}
                vis = hourly.get('visibility')
                if isinstance(vis, list) and vis:
                    hourly['visibility'] = [900.0 if v is not None else None for v in vis]
            return foggy, [row.get('cityName') for row in chosen]

        report['fogInjection'] = []
        # 剂量-反应：1 / 3 / 6 座城压到 900 m。若关闭班次随城数单调上升、
        # 且 1–3 座城就回到 1000 班量级，则"1430 属于雾档"这件事有证据，
        # 而不是"我猜是天气"。
        for count in (1, 3, 6):
            foggy, names = inject(count)
            row = build_once(foggy, 0.25, 0.15, None)
            row.update({'injected': 'HOURLY_VISIBILITY_900M_EXPERIMENT_ONLY',
                        'citiesInjected': count, 'cityNames': names})
            report['fogInjection'].append(row)
            print(f"E 雾档注入 {count} 城（{('、'.join(names))}）→ accepted {row['accepted']} / "
                  f"closed {row['closed']}（{row['closedRatio']:.1%}）· {row['closedByReason']}")

    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('报告 →', REPORT_FILE)
    return 0


if __name__ == '__main__':
    os.environ.setdefault('ALC_NO_PREWARM', '1')
    raise SystemExit(main())
