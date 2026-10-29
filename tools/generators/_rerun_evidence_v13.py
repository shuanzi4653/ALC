"""Re-measure the V1.3 evidence directory against the current code.

The V1.3 snapshots were taken when the network produced 2910 flights. The network
now produces 7760 and the rain-band fix changed the closure counts, so every
flight/performance number in ``docs/evaluation-v1.3/`` is a stale measurement of
a code version that no longer exists. This script re-runs the real measurement
pass (no estimates) and adds a provenance header describing what changed and
which numbers must not be mixed with the old ones.

Run:  backend-python/.venv/Scripts/python.exe _rerun_evidence_v13.py
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
from datetime import datetime, timezone


from traffic import service  # noqa: E402
from traffic.catalog import CATALOG_FILE, cities, connections  # noqa: E402
from traffic.weather_sources import provider_status  # noqa: E402
from weather.geometry import BOUNDARY_VERSION  # noqa: E402

OUT = ROOT / 'docs' / 'evaluation-v1.3'
OUT.mkdir(parents=True, exist_ok=True)
GENERATED = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
PY_EXE = 'backend-python/.venv/Scripts/python.exe'

# ---- Numbers this script cannot measure itself, carried in from the probes that
# ---- did. Recording them here keeps every figure in performance.json traceable
# ---- to the tool that produced it, instead of to a hand-edited value.
#
# END_TO_END is produced by _sim_harness.py + _sim_probe.py (three services up).
# It stays a literal because those runs need a live HTTP stack, not just an import.
END_TO_END = {
    'measurements': [
        {'label': 'canonical', 'scenario': 'moving', 'seed': 42, 'seconds': 14.516,
         'note': '默认口径，三方服务全部在线。'},
        {'label': 'cold', 'scenario': 'moving', 'seed': 98765, 'seconds': 14.743,
         'note': '换种子以避开计算缓存，观察冷缓存下的端到端等待。'},
        {'label': 'live', 'scenario': 'live', 'seconds': 16.888,
         'note': '实时气象源（open-meteo）参与，含外部取数与降级判断，比同口径离线慢约 2.1 s。'},
    ],
}

# What the V1.3 snapshot recorded before this round, kept for traceability only.
SUPERSEDED_END_TO_END = {
    'secondsRange': [10.4, 11.3],
    'supersededBecause': ('测得于 2910 班次时期的网络与雨带修复之前，当前网络 7760 班次。'
                          '见本文件 measurementNote。'),
}

# LEDGER is produced by _bench_ledger.py, which runs the two pure functions that
# DispatchBoard.vue calls on every keystroke (scoped filter, groupFlights,
# virtualWindow) over the real 7760-flight payload under node. It measures the
# data path, not paint: render and FPS still need a real browser and are reported
# as unmeasured below rather than inferred from these numbers.
LEDGER = {
    'measuredBy': '_bench_ledger.py',
    'payloadFlights': 7760,
    'budgetMs': 300,
    'worstMs': 0.185,
    'worstCase': 'groupFlights minute=60',
    'verdict': 'PASS',
    'headroomFactor': 1622,
    'note': ('筛选与分组的最坏值 0.185 ms，虚拟窗口为常数级（0.000 ms）；'
             '相对 300 ms 预算有约 1620 倍余量。这是数据通路耗时，不含浏览器绘制。'),
}

# Browser render metrics are deliberately absent rather than estimated. They need
# a real browser measuring requestAnimationFrame, which the offline evidence pass
# cannot do, so the field states that instead of carrying a plausible-looking number.
BROWSER_RENDER = {
    'fpsMeasured': None,
    'ledgerPaintMeasuredMs': None,
    'note': ('未经真实浏览器实测。台账的**数据通路**已由 _bench_ledger.py 实测（最坏 0.185 ms），'
             '但合成与绘制帧率需在真实界面用 requestAnimationFrame 采样，'
             '本轮未做，故留空而不是给估值。'),
}

# COMPUTE_ATTRIBUTION is produced by _profile_final.py / _profile_own.py /
# _verify_band_cache.py. Every figure below is a measured value.
COMPUTE_ATTRIBUTION = {
    'measuredAt': GENERATED,
    'note': ('计划纯计算的归因结果，来自 _profile_final.py（空闲机器、单次 warm 计划）。'
             '此前只证明了固定管制空域**不是**原因，本轮定位到真正热点并已修复。'),
    'profileBefore': {
        'planSeconds': 13.32,
        'envelopeSeconds': 11.25,
        'envelopeCalls': 13419,
        'sweptBandSeconds': 8.31,
        'windowCacheHitRate': 0.0,
        'cause': ('envelope() 的调用点传入的是浮点分钟，13419 次调用产生 13411 个互不相同的'
                  '浮点键，lru_cache 命中率为 0，于是每个窗口都重算雨带凸包。'),
    },
    'profileAfter': {
        'planSeconds': 12.69,
        'envelopeSeconds': 5.60,
        'envelopeCalls': 13419,
        'sweptBandSeconds': 3.38,
        'windowCacheHitRate': 0.923,
        'cause': ('envelope() 先按 5 分钟刻度分箱再进缓存，键数收敛到 1035，命中率 92.3%；'
                  '_band_hull 只对落在缓动轨迹自身凸包上的偏移求外延，其余偏移不可能产生极点。'),
    },
    'correctnessGate': {
        'geometrySymmetricDifferenceM2': 0.0,
        'planDigestSeed42': 'e1ebc2ba39ab215b',
        'planDigestSeed98765': 'c4d7d8b120415378',
        'note': ('九个真实窗口的对称差均为 0.0000 m²，两个种子的计划摘要与优化前逐字节一致，'
                 'accepted/closed 同为 5724/2036 与 5922/1838。提速**未**改变任何计划结论。'),
    },
    'rejectedOptimisations': [
        {'what': '把窗口向外吸附到 1 小时网格以扩大缓存复用', 'safe': True,
         'but': '包络更保守，关闭 2258 班而非 2036 班，属行为变更而非优化，已回退。'},
        {'what': '用雨带缓动偏移凸包与轮廓凸包的并集近似扫描包络', 'safe': False,
         'but': ('缓动轨迹远非凸（97 个采样中 92 个落在自身凸包内部），该近似在 96 刻度窗口上'
                 '只有 121,638,561,897 m²，比真实的 174,724,291,628 m² 少 53,085,729,730 m²，'
                 '正是曾让航迹穿雨带的缺陷形态，已回退。')},
        {'what': '按固定步长抽样刻度来减少凸包点数', 'safe': False,
         'but': ('步长 2 在窗口 (0,36) 上就少 303,023 m²，步长 5 在 (56,70) 上少 '
                 '21,694,389 m²，不精确，未采用。')},
    ],
}


def log(*parts):
    print(*parts, flush=True)


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8')
    log('wrote', name)


# --------------------------------------------------------------- stale values
# Read before overwriting so the provenance record can name the exact numbers
# that changed, instead of vaguely saying "out of date".
previous = {}
perf_path = OUT / 'performance.json'
if perf_path.exists():
    old = json.loads(perf_path.read_text(encoding='utf-8'))
    previous = {
        'generatedAt': old.get('generatedAt'),
        'flightsPerRun': sorted({r['flights'] for r in old.get('runs', [])}),
        'acceptedSample': old['runs'][0]['accepted'] if old.get('runs') else None,
        'closedSample': old['runs'][0]['closed'] if old.get('runs') else None,
        'planSecondsRange': [min(r['planSeconds'] for r in old.get('runs', [])),
                             max(r['planSeconds'] for r in old.get('runs', []))]
                            if old.get('runs') else None,
    }

# Cold vs warm catalogue cost, measured before anything else warms the caches.
cities.cache_clear()
connections.cache_clear()
_timer = time.perf_counter()
service.network()
network_cold_seconds = round(time.perf_counter() - _timer, 3)
_timer = time.perf_counter()
service.network()
network_warm_seconds = round(time.perf_counter() - _timer, 3)
log('network cold', network_cold_seconds, 'warm', network_warm_seconds)

# ---------------------------------------------------------------- environment
cat = json.loads(CATALOG_FILE.read_text(encoding='utf-8'))
dump('environment.json', {
    'generatedAt': GENERATED,
    'python': sys.version.split()[0],
    'trafficVersion': service.VERSION,
    'planRevision': service.PLAN_REVISION,
    'fingerprint': service.FINGERPRINT,
    'baseTime': service.SIMULATION_BASE_TIME.isoformat().replace('+00:00', 'Z'),
    'displayTimezone': 'Asia/Shanghai',
    'timelineMinutes': service.TIMELINE_MINUTES,
    'boundaryVersion': BOUNDARY_VERSION,
    'catalogueSchemaVersion': cat['schemaVersion'],
    'catalogueCrs': cat['coordinateReferenceSystem'],
})

# ------------------------------------------------------- city coordinate audit
resolved = {city['id']: city for city in cities()}
from traffic.catalog import city_pads  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


entries = []
for row in cat['cities']:
    city = resolved[row['id']]
    pads = city_pads(city)
    entries.append({
        'cityId': city['id'], 'name': city['name'], 'province': city['province'],
        'capital': row['capital'], 'centerType': row['centerType'],
        'coordinateWgs84': city['coordinate'], 'source': row['source'],
        'reviewedAt': row['reviewedAt'], 'quality': row['quality'],
        'coordinateValid': city['coordinateValid'], 'coordinateStatus': city['coordinateStatus'],
        'hubId': pads[0]['id'] if pads else None,
        'hubOffsetFromCentreM': pads[0]['offsetFromCenterM'] if pads else None,
        'hubStatus': pads[0]['status'] if pads else 'NO_HUB_OUTSIDE_BOUNDARY',
    })
special = [
    {'cityId': e['cityId'], 'name': e['name'], 'centerType': e['centerType'],
     'coordinateWgs84': e['coordinateWgs84'], 'source': e['source'],
     'handling': ('州府城区代表点，按地级行政区纳入，未按自治州几何质心取点。'
                  if e['cityId'] == '2-09'
                  else '行政驻地在内蒙古境内，本省边界内无可覆盖驻地，按三省运行边界选定合规服务枢纽代表点并保留差异说明；未移动省界也未改写坐标。')}
    for e in entries if e['centerType'] != '城区代表中心'
]
dump('city-coordinate-audit.json', {
    'generatedAt': GENERATED,
    'catalogueFile': 'backend-python/data/traffic/city-centers.json',
    'catalogueSchemaVersion': cat['schemaVersion'],
    'coordinateReferenceSystem': cat['coordinateReferenceSystem'],
    'coordinatePolicy': cat['coordinatePolicy'],
    'catalogueCount': len(entries),
    'validCount': sum(1 for e in entries if e['coordinateValid']),
    'outsideProvince': [e['cityId'] for e in entries if not e['coordinateValid']],
    'fixedSouthwestOffsetRemoved': True,
    'removedOffsetMetres': 2690.72,
    'maximumHubOffsetFromCentreM': max((e['hubOffsetFromCentreM'] or 0) for e in entries),
    'specialCases': special,
    'cities': entries,
})
log('city audit:', len(entries), 'cities,',
    sum(1 for e in entries if e['coordinateValid']), 'valid')

# ------------------------------------------------------------- data coverage
network = service.network()
dump('data-coverage.json', {
    'generatedAt': GENERATED,
    'cityDirectory': {
        'file': 'backend-python/data/traffic/city-centers.json',
        'cities': len(network['cities']),
        'validated': sum(1 for c in network['cities'] if c['coordinateValid']),
        'invalid': [c['id'] for c in network['cities'] if not c['coordinateValid']],
    },
    'aircraftProfiles': {
        'file': 'backend-python/data/traffic/aircraft-profiles.json',
        'cruiseLayersAglM': network['assumptions']['cruiseLayers'],
        'ceilingsAglM': network['assumptions']['flightCeilingsAglM'],
        'noAltitudeStacking': network['assumptions']['noAltitudeStacking'],
        'altitudeDatum': network['assumptions']['altitudeDatum'],
    },
    'deliveryConfig': network['deliveryConfig'],
    'riskRules': network['riskRules'],
    'staticAirspace': {
        'module': 'traffic/zones.py + data/traffic/fixed-zones.json',
        'status': network['staticAirspace']['status'],
        'rules': network['staticAirspace']['rules'],
        'audit': network['staticAirspace']['audit'],
        'zoneCount': len(network['staticAirspace']['zones']),
        'withGeometry': network['staticAirspace']['status']['withGeometry'],
        'evidence': 'docs/evaluation-v1.4/fixed-airspace.json',
    },
    'derivedRiskRegions': {
        'module': 'traffic/weather.py（NetworkWeather）+ traffic/service._risk_rules()',
        'layerName': network['riskRules'].get('layerName'),
        'derivation': network['riskRules'].get('derivation'),
        'labels': network['riskRules']['labels'],
        'mergeState': ('按场区连通分量合并后展示：单体 → 区域，CAUTION 重建为「成员外缘 − 合并后核心」，'
                       '两层恒不相交；避让包络仍逐单体计算，因此恒为已画区域的超集。'
                       '见 docs/evaluation-v1.5/risk-merge-and-flat-render.json。'),
        'renderMode': '平面范围（填充 + 轮廓），不画立体柱体；未公布垂直限制则不作图示。',
        'authority': 'SYSTEM_DERIVED_NOT_OFFICIAL_AIRSPACE_CONTROL',
    },
    'networkSummary': {
        'pads': len(network['pads']),
        'routes': len(network['routes']),
        'carRoutes': sum(1 for r in network['routes'] if r['mode'] == 'CAR'),
        'deliveryRoutes': sum(1 for r in network['routes'] if r['mode'] == 'DELIVERY'),
        'interprovincialRoutes': sum(1 for r in network['routes'] if r['interprovincial']),
    },
    'weatherProviders': provider_status(),
    'missingOrUnverified': {
        'terrainDem': {'status': 'UNAVAILABLE', 'impact': '净空判定为条件未验证，不按零高度地面放行。'},
        'buildingHeights': {'status': 'UNAVAILABLE', 'impact': '楼宇仅用于显示，未进入后端避障。'},
        'obstacleSourceVersion': 'no-local-dem-or-building-catalog-v1',
        'independentThunderField': {'status': 'UNAVAILABLE',
                                   'impact': '不使用降水概率乘固定系数冒充雷暴概率。'},
        'routeInteriorWeather': '仅城际端点与采样城市有天气值，航路内部未全程采样。',
        'stationNetwork': {'status': 'UNAVAILABLE', 'impact': '不以省级地面测站代替 36 城城区观测。'},
        'aviationMetarTaf': {'status': 'NOT_INTEGRATED', 'impact': '未接入，也不代表 36 城城区覆盖。'},
        'radarDerivedRiskRegions': {
            'status': 'IMPLEMENTED_IMAGE_CHANNEL_ONLY',
            'impact': '中国气象数据网雷达为图像产品，色标反查 dBZ 的阈值与配准尚未标定，'
                      '未接入运行计划，仅作为派生飞行风险区的待接入第二源。',
            'namingRule': '标定完成前不得把回波强度写入风险区名称或阈值口径。',
        },
        'derivedRegionGranularity': {
            'status': 'MEASURED',
            'impact': '按场区连通分量合并后实测 15—17 个展示区域；雷达源接入后若沿用同一条'
                      '「栅格场 → 风险区」管线，该粒度是否适用须重新测量，不得直接沿用。',
            'evidence': 'docs/evaluation-v1.5/risk-merge-and-flat-render.json',
        },
    },
    'statedCosts': {
        'openMeteo': '免费服务有调用限额且不保证 SLA；多地点多变量计入计量。',
        'qweather': '凭据由 Java 侧持有；Python 只读内部原始接口，端点默认仅本机可调用，并带 60 秒缓存。',
        'scheduling': '36 城每 15 分钟刷新约等于每天 3456 次地点请求，尚未计入变量权重与航路网格。',
    },
})
log('coverage: pads', len(network['pads']), 'routes', len(network['routes']))

# ---------------------------------------------------------------- performance
def overview(value):
    accepted = [f for f in value['flights'] if f['status'] == 'SCHEDULED']
    summary = value['deliveryPlan']
    reasons = {}
    for flight in value['flights']:
        if flight['status'] == 'CLOSED':
            reasons[flight['reason']] = reasons.get(flight['reason'], 0) + 1
    return {
        'flights': len(value['flights']), 'accepted': len(accepted),
        'closed': len(value['flights']) - len(accepted),
        'detours': value['stats']['detours'], 'groundHolds': value['stats']['groundHolds'],
        'alternateLayers': value['stats']['alternateLayers'],
        'resolvedConflicts': value['stats']['resolved'],
        'layerUsage': value['layerUsage'],
        'delivery': {k: summary[k] for k in
                     ('orders', 'delivered', 'cancelled', 'beyondTimeline', 'deliveryRate',
                      'averageGroundWaitMinutes', 'maxGroundWaitMinutes')},
        'hubPads': len(value['hubs']['pads']),
        'crossingZones': value['hubs']['crossingZones']['count'],
        'crossingReservations': value['hubs']['crossingZones']['reservations'],
        'highestCarAglM': max((f['maxAltitudeM'] for f in accepted if f['mode'] == 'CAR'), default=None),
        'highestDeliveryAglM': max((f['maxAltitudeM'] for f in accepted if f['mode'] == 'DELIVERY'), default=None),
        'clearanceStatuses': sorted({f['clearanceStatus'] for f in accepted}),
        'closureReasons': dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        'orderOutcomeReasons': summary['outcomeReasons'],
    }


def timed(seed, scenario):
    start = time.perf_counter()
    value = service.simulate(seed, scenario)
    elapsed = time.perf_counter() - start
    log(f'  seed={seed} scenario={scenario}: {elapsed:.2f}s '
        f'{len(value["flights"])} flights')
    return {'seed': seed, 'scenario': scenario, 'planSeconds': round(elapsed, 2),
            **overview(value)}


combinations = [(42, 'moving'), (42, 'clear'), (7, 'moving'), (2026, 'moving')]
log('measuring plan computation (sequential, same machine, same moment)')
runs = [timed(seed, scenario) for seed, scenario in combinations]

# tracemalloc traces every allocation, so it gets its own pass and its wall time
# is deliberately discarded rather than reported as plan time.
memory = {}
for seed, scenario in [(42, 'moving'), (2026, 'moving')]:
    import tracemalloc
    tracemalloc.start()
    service.simulate(seed, scenario)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    memory[f'{seed}:{scenario}'] = round(peak / 1024 / 1024, 1)
    log(f'  peak memory {seed}:{scenario} = {memory[f"{seed}:{scenario}"]} MB')

for run in runs:
    run['pythonPeakMemoryMb'] = memory.get(f"{run['seed']}:{run['scenario']}")

dump('performance.json', {
    'generatedAt': GENERATED,
    'measurementNote': (
        '本文件在 2026-09-17 的命名统一轮次中被**整份重跑**。重跑原因是计划结论已发生变化：'
        'V1.3 快照采集时运行网络生成 2910 个班次，当前网络为 7760 个班次；'
        '气象雨带的几何投影缺陷修复后，一度被径直放行穿越雨带的班次被正确阻断，'
        '关闭班次数因此显著上升。旧快照测量的是一个已不存在的代码版本，'
        'spuriousMetrics 字段列出其具体数值，仅供追溯，**不得与本次数字混用**。'
    ),
    'spuriousMetrics': previous,
    'scopeNote': (
        '同机同时刻串行测量，含 shapely 连续四维检查与资源日历；'
        'pythonPeakMemoryMb 为独立 tracemalloc 通路的峰值，该通路的墙钟时间不作为计划耗时。'
        'runs[].planSeconds 是**进程内纯计算**耗时（直接调用 traffic.service.simulate），'
        '不是用户等待时间。不含浏览器渲染帧率：FPS 与台账筛选响应需在真实界面复核。'
    ),
    'networkSecondsCold': network_cold_seconds,
    'networkSecondsWarm': network_warm_seconds,
    'runs': runs,
    'endToEndRuns': {
        'note': ('HTTP 端到端等待时间由 _sim_harness.py 探测链路单独测量（三服务全栈启动后'
                 '经 5180 前端代理打 8600 的 /traffic/session 并轮询到 READY）。'
                 'planSeconds 是进程内纯计算，本字段是用户实际等待时间，两者不可互推。'),
        'measurements': END_TO_END.get('measurements', []),
        # Always the pre-V1.5 range, never inherited from the file being rewritten.
        # Inheriting it once already published the *current* numbers as "superseded".
        'supersededMeasurements': SUPERSEDED_END_TO_END['secondsRange'],
        'supersededBecause': SUPERSEDED_END_TO_END['supersededBecause'],
    },
    'computeAttribution': COMPUTE_ATTRIBUTION,
    'ledgerFilter': LEDGER,
    'browserRender': BROWSER_RENDER,
    'targets': {'planSecondsBudget': 8.0, 'ledgerFilterBudgetMs': 300, 'browserFpsTarget': 30},
    'verdict': {
        'networkWithinBudget': network_cold_seconds <= 2.0,
        'planComputeWithinBudget': all(r['planSeconds'] <= 8.0 for r in runs),
        'slowestPlanSeconds': max(r['planSeconds'] for r in runs),
        'altitudeCeilingRespected': all(
            r['highestCarAglM'] is not None
            and r['highestCarAglM'] <= network['assumptions']['flightCeilingsAglM']['CAR']
            and r['highestDeliveryAglM'] <= network['assumptions']['flightCeilingsAglM']['DELIVERY']
            for r in runs),
        'note': ('纯计算耗时仍超出 8 秒内部工程预算。已排除固定管制空域（整体关闭后同计划 '
                 '11.42 s，开启 12.51 s，净增 1.09 s 约 9%，且班次口径逐项相同 —— '
                 '_bench_zone_baseline.py 本轮实测）。真正的热点是气象包络计算，'
                 '本轮回退了两处不安全的提速、落实了两处等价提速，把 envelope 从 11.25 s '
                 '降到 5.60 s；剩余超出部分属网络规模（7760 班次）带来的遗留项，尚未消除。'),
    },
})
log('DONE')
