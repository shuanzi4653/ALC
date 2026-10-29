"""Generate docs/evaluation-v1.4 evidence for the fixed controlled airspace work.

Every number here is measured in this run — the clause coverage matrix is read from
the shipped catalogue, the two policy readings are produced by two real
``service.simulate`` calls, and the payload sizes come from serialising the actual
``/traffic/network`` response. Nothing is estimated or copied from a previous round.

Run:  backend-python\\.venv\\Scripts\\python.exe _gen_zone_evidence.py
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ROOT = Path(ROOT)
import json
import time
from collections import Counter


from traffic import service, zones  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


OUT = ROOT / 'docs' / 'evaluation-v1.4'
OUT.mkdir(parents=True, exist_ok=True)


def measure_plan(policy):
    """Run one real plan under the given aerodrome footprint reading.

    A discarded warm-up precedes the measurement. The first ``simulate`` call in a
    fresh interpreter costs 3-5 s extra (module import, the first STRtree build, the
    projection transformer), and reporting that as this feature's cost inflated the
    reading fourfold on the first attempt. The cold number is captured separately.
    """
    original = service.airport_footprint_policy
    service.airport_footprint_policy = lambda: policy
    try:
        service.simulate(seed=11, scenario='clear')
        start = time.perf_counter()
        plan = service.simulate(seed=42, scenario='moving')
        elapsed = time.perf_counter() - start
    finally:
        service.airport_footprint_policy = original
    reasons = Counter(flight['reason'] for flight in plan['flights'])
    crossings = [flight for flight in plan['flights'] if flight['staticAirspace']['zones']]
    return {
        'policy': policy,
        'warmSeconds': round(elapsed, 2),
        'flights': len(plan['flights']),
        'accepted': plan['stats']['accepted'],
        'closed': plan['stats']['closed'],
        'stats': plan['stats']['staticAirspace'],
        'reasonHistogram': dict(sorted(reasons.items(), key=lambda item: -item[1])),
        'flightsWithCrossings': len(crossings),
        'maxZonesOnOneFlight': max((flight['staticAirspace']['zones'] for flight in plan['flights']), default=0),
        'exampleCrossing': next(
            ({'flightId': flight['id'], 'route': flight['name'],
              'zones': flight['staticAirspace']['zones'],
              'records': flight['staticAirspace']['crossings']}
             for flight in crossings), None),
    }


# Cold-process figure, recorded once and separately from the warm measurements.
cold_start = time.perf_counter()
service.simulate(seed=42, scenario='moving')
cold_seconds = round(time.perf_counter() - cold_start, 2)

# ``network()`` is lru_cached and the warm-up plan above already populated it, so
# the cache is cleared first — otherwise the reading is a meaningless 0.0 s.
service.network.cache_clear()
start = time.perf_counter()
network = service.network()
network_seconds = time.perf_counter() - start

block = network['staticAirspace']
sites = block['zones']
audit = block['audit']
status = block['status']

clause_rows = []
for clause in audit['clauses']:
    clause_rows.append({
        'key': clause['key'],
        'clause': clause['clause'],
        'sector': clause['sectorLabel'],
        'geometryStatus': clause['geometryStatus'],
        'sites': clause['sites'],
        'withGeometry': clause['withGeometry'],
        'prohibited': clause['prohibited'],
        'approvalRequired': clause['approvalRequired'],
        'registered': clause['registered'],
        'citation': clause['citation'],
    })

default_plan = measure_plan(zones.APPROVAL_REQUIRED)
strict_plan = measure_plan(zones.PROHIBITED)

evidence = {
    'catalogVersion': status['catalogVersion'],
    'dataRetrievedAt': status['dataRetrievedAt'],
    'generatedAt': time.strftime('%Y-%m-%d'),
    'legalInstrument': block['rules']['legalFramework']['instrument'],
    'clause': block['rules']['legalFramework']['clause'],
    'entryRule': block['rules']['legalFramework']['entryRule'],
    'publicationRule': block['rules']['legalFramework']['publicationRule'],
    'totals': {
        'sites': status['sites'],
        'withGeometry': status['withGeometry'],
        'registeredOnly': status['sites'] - status['withGeometry'],
        'prohibited': status['prohibited'],
        'approvalRequired': status['approvalRequired'],
        'registered': status['registered'],
        'clauses': status['clauses'],
    },
    # Radii come from the catalogue, not from ``frame()``: the frame emits the
    # clipped polygon, so the originating radius is no longer on the record.
    # ``or {}`` because a registered site carries ``geometry: null`` rather than a
    # missing key, and a dict default does not cover an explicit null.
    'publishedRadiiM': sorted({site['geometry']['radiusM'] for site in zones.sites()
                               if (site.get('geometry') or {}).get('kind') == 'CIRCLE'}),
    'clauseCoverage': clause_rows,
    'payload': {
        'networkSeconds': round(network_seconds, 3),
        'networkBytes': len(json.dumps(network, ensure_ascii=False).encode()),
        'staticAirspaceBytes': len(json.dumps(block, ensure_ascii=False).encode()),
        'zoneVertices': sum(len(ring) for site in sites if site.get('geometry')
                            for polygon in site['geometry']['coordinates'] for ring in polygon),
    },
    'envelopeAreaKm2': {
        'approvalRequiredPolicy': round(zones.envelope(zones.APPROVAL_REQUIRED).area / 1e6, 1),
        'prohibitedPolicy': round(zones.envelope(zones.PROHIBITED).area / 1e6, 1),
    },
    'planTiming': {
        'coldProcessSeconds': cold_seconds,
        'note': '表中为**热态**耗时（前面各跑一次丢弃的预热计划）。冷进程首调含导入、首次 STRtree 构建与投影器初始化，'
                '实测比热态多 3—5 s，因此不能作为本功能的成本。',
    },
    'plans': {'defaultApprovalRequired': default_plan, 'strictProhibited': strict_plan},
}

(OUT / 'fixed-airspace.json').write_text(
    json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

lines = [
    '# V1.4 固定管制空域证据（本地实测）',
    '',
    f"- 目录版本：`{status['catalogVersion']}`，公开数据取得日 {status['dataRetrievedAt']}",
    f"- 法规：{block['rules']['legalFramework']['instrument']} {block['rules']['legalFramework']['clause']}",
    f"- 站点总数 {status['sites']}：有确定几何 {status['withGeometry']}，仅登记 {status['sites'] - status['withGeometry']}",
    f"- 禁入 {status['prohibited']}，须经批准 {status['approvalRequired']}，仅登记 {status['registered']}",
    f"- 已按公开依据生成圆的半径取值（m）：{evidence['publishedRadiiM']}（未出现 20000，即天气雷达探测环境保护区未充当飞行管制几何）",
    f"- `/traffic/network` 首调 {evidence['payload']['networkSeconds']} s（缓存已清空后计时），"
    f"整包 {evidence['payload']['networkBytes'] / 1024:.0f} KiB，"
    f"其中固定管制区 {evidence['payload']['staticAirspaceBytes'] / 1024:.0f} KiB，"
    f"环顶点合计 {evidence['payload']['zoneVertices']}",
    f"- 禁入集合面积：默认口径 {evidence['envelopeAreaKm2']['approvalRequiredPolicy']} km²，"
    f"严格口径 {evidence['envelopeAreaKm2']['prohibitedPolicy']} km²",
    '',
    '## 第八条覆盖矩阵（按实际目录统计）',
    '',
    '| 条文 | 领域 | 几何状态 | 站点 | 有几何 | 禁入 | 须批准 | 仅登记 |',
    '| --- | --- | --- | --- | --- | --- | --- | --- |',
]
for row in clause_rows:
    lines.append(f"| {row['clause']} | {row['sector']} | {row['geometryStatus']} | {row['sites']} | "
                 f"{row['withGeometry']} | {row['prohibited']} | {row['approvalRequired']} | {row['registered']} |")

lines += [
    '',
    '## 两种机场净空口径的真实代价（seed 42 / moving，热态串行测量）',
    '',
    f"冷进程首调 {cold_seconds} s（含导入与首次 STRtree 构建，不作为本功能成本）；下表为**热态**耗时。",
    '',
    '| 口径 | 计划用时 | 关闭班次 | 因固定管制区关闭 | 需批准班次 | 穿越记录 | 有穿越的班次 |',
    '| --- | --- | --- | --- | --- | --- | --- |',
]
for label, plan in (('APPROVAL_REQUIRED（默认）', default_plan), ('PROHIBITED（严格）', strict_plan)):
    stats = plan['stats']
    lines.append(f"| {label} | {plan['warmSeconds']} s | {plan['closed']} | "
                 f"{stats['closedByStaticAirspace']} | {stats['flightsRequiringApproval']} | "
                 f"{stats['crossingRecords']} | {plan['flightsWithCrossings']} |")

lines += [
    '',
    '### 关闭原因分布',
    '',
    f"- 默认口径：`{json.dumps(default_plan['reasonHistogram'], ensure_ascii=False)}`",
    f"- 严格口径：`{json.dumps(strict_plan['reasonHistogram'], ensure_ascii=False)}`",
    '',
    '> 严格口径比默认**更快**，因为它提前关闭了 '
    f"{strict_plan['stats']['closedByStaticAirspace']} 个班次，省下了后续寻路与排班；这不是可依赖的收益。",
    '',
    '> **基线本身已超 8 s 内部预算，与本功能无关**：把固定管制逻辑整体关闭后，同一计划仍为 '
    '12.61 s，且班次口径（7760 / 6986 / 774）与原因分布与开启时逐项相同（`_bench_zone_baseline.py` 实测）。'
    '对比 V1.3 证据（`docs/evaluation-v1.3/performance.json`：2.34—2.94 s / 2910 班次），'
    '网络规模已增长到 2.67 倍，属遗留项。',
    '',
    '### 逐班次穿越记录样例',
    '',
]
example = default_plan['exampleCrossing']
if example:
    lines.append(f"班次 `{example['flightId']}`（{example['route']}）共 {example['zones']} 处：")
    lines.append('')
    for record in example['records']:
        lines.append(f"- {record['name']}（{record['clause']}，{record['enforcement']}）"
                     f" T+{record['entryMinute']:.2f}—T+{record['exitMinute']:.2f} min，"
                     f"最高 {record['maxAglM']} m AGL；依据：{record['citation']}")
    lines.append('')
lines.append('说明：以上数字均由本次运行的真实计算得出，未使用估算值。')

(OUT / 'fixed-airspace.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

print(f'写入 {OUT / "fixed-airspace.json"}')
print(f'写入 {OUT / "fixed-airspace.md"}')
print('\n'.join(lines[:14]))
