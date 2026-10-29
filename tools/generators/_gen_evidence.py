"""Generate docs/evaluation-v1.3 evidence from an actual measurement run."""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ROOT = Path(ROOT)
import json
import platform
import time
import tracemalloc
from datetime import datetime, timezone


from traffic import service  # noqa: E402
from traffic.catalog import CATALOG_FILE, cities, city_pads, connections  # noqa: E402
from traffic.obstacles import SOURCE_VERSION as OBSTACLE_VERSION  # noqa: E402
from traffic.weather_sources import provider_status  # noqa: E402
from weather.geometry import BOUNDARY_VERSION  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# Cold vs warm catalogue/network cost, measured before anything else warms the caches.
cities.cache_clear()
connections.cache_clear()
_timer = time.perf_counter()
service.network()
network_cold_seconds = round(time.perf_counter() - _timer, 3)
_timer = time.perf_counter()
service.network()
network_warm_seconds = round(time.perf_counter() - _timer, 3)

OUT = ROOT / 'docs' / 'evaluation-v1.3'
OUT.mkdir(parents=True, exist_ok=True)
GENERATED = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('wrote', name)


# ---------------------------------------------------------------- environment
dump('environment.json', {
    'generatedAt': GENERATED,
    'python': sys.version.split()[0],
    'platform': platform.platform(),
    'trafficVersion': service.VERSION,
    'planRevision': service.PLAN_REVISION,
    'fingerprint': service.FINGERPRINT,
    'baseTime': service.SIMULATION_BASE_TIME.isoformat().replace('+00:00', 'Z'),
    'displayTimezone': 'Asia/Shanghai',
    'timelineMinutes': service.TIMELINE_MINUTES,
    'boundaryVersion': BOUNDARY_VERSION,
    'catalogueSchemaVersion': json.loads(CATALOG_FILE.read_text(encoding='utf-8'))['schemaVersion'],
    'catalogueCrs': json.loads(CATALOG_FILE.read_text(encoding='utf-8'))['coordinateReferenceSystem'],
})

# ------------------------------------------------------- 36 city coordinate audit
catalogue = json.loads(CATALOG_FILE.read_text(encoding='utf-8'))
resolved = {city['id']: city for city in cities()}
entries = []
for row in catalogue['cities']:
    city = resolved[row['id']]
    pads = city_pads(city)
    entries.append({
        'cityId': city['id'], 'name': city['name'], 'province': city['province'], 'capital': row['capital'],
        'centerType': row['centerType'], 'coordinateWgs84': city['coordinate'],
        'source': row['source'], 'reviewedAt': row['reviewedAt'], 'quality': row['quality'],
        'coordinateValid': city['coordinateValid'], 'coordinateStatus': city['coordinateStatus'],
        'hubId': pads[0]['id'] if pads else None,
        'hubOffsetFromCentreM': pads[0]['offsetFromCenterM'] if pads else None,
        'hubStatus': pads[0]['status'] if pads else 'NO_HUB_OUTSIDE_BOUNDARY',
    })
special = [
    {'cityId': e['cityId'], 'name': e['name'], 'centerType': e['centerType'],
     'coordinateWgs84': e['coordinateWgs84'], 'source': e['source'],
     'handling': ('州府城区代表点，按地级行政区纳入，未按自治州几何质心取点。' if e['cityId'] == '2-09'
                  else '行政驻地在内蒙古境内，本省边界内无可覆盖驻地，按三省运行边界选定合规服务枢纽代表点并保留差异说明；未移动省界也未改写坐标。')}
    for e in entries if e['centerType'] != '城区代表中心'
]
dump('city-coordinate-audit.json', {
    'generatedAt': GENERATED,
    'catalogueFile': 'backend-python/data/traffic/city-centers.json',
    'catalogueSchemaVersion': catalogue['schemaVersion'],
    'coordinateReferenceSystem': catalogue['coordinateReferenceSystem'],
    'coordinatePolicy': catalogue['coordinatePolicy'],
    'catalogueCount': len(entries),
    'validCount': sum(1 for e in entries if e['coordinateValid']),
    'outsideProvince': [e['cityId'] for e in entries if not e['coordinateValid']],
    'fixedSouthwestOffsetRemoved': True,
    'removedOffsetMetres': 2690.72,
    'maximumHubOffsetFromCentreM': max((e['hubOffsetFromCentreM'] or 0) for e in entries),
    'specialCases': special,
    'cities': entries,
})

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
        'obstacleSourceVersion': OBSTACLE_VERSION,
        'independentThunderField': {'status': 'UNAVAILABLE',
                                   'impact': '不使用降水概率乘固定系数冒充雷暴概率。'},
        'routeInteriorWeather': '仅城际端点与采样城市有天气值，航路内部未全程采样。',
        'stationNetwork': {'status': 'UNAVAILABLE', 'impact': '不以省级地面测站代替 36 城城区观测。'},
        'aviationMetarTaf': {'status': 'NOT_INTEGRATED', 'impact': '未接入，也不代表 36 城城区覆盖。'},
    },
    'statedCosts': {
        'openMeteo': '免费服务有调用限额且不保证 SLA；多地点多变量计入计量。',
        'qweather': '凭据由 Java 侧持有；Python 只读内部原始接口，端点默认仅本机可调用，并带 60 秒缓存。',
        'scheduling': '36 城每 15 分钟刷新约等于每天 3456 次地点请求，尚未计入变量权重与航路网格。',
    },
})

# ---------------------------------------------------------------- performance
def overview(value):
    accepted = [f for f in value['flights'] if f['status'] == 'SCHEDULED']
    summary = value['deliveryPlan']
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
        'orderOutcomeReasons': summary['outcomeReasons'],
    }


def timed(seed, scenario):
    start = time.perf_counter()
    value = service.simulate(seed, scenario)
    elapsed = time.perf_counter() - start
    return {'seed': seed, 'scenario': scenario, 'planSeconds': round(elapsed, 2), **overview(value)}


combinations = [(42, 'moving'), (42, 'clear'), (7, 'moving'), (2026, 'moving')]
runs = [timed(seed, scenario) for seed, scenario in combinations]

# tracemalloc traces every allocation, so it is measured in a separate pass and
# its wall time is deliberately discarded rather than reported as plan time.
memory = {}
for seed, scenario in [(42, 'moving'), (2026, 'moving')]:
    tracemalloc.start()
    service.simulate(seed, scenario)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    memory[f'{seed}:{scenario}'] = round(peak / 1024 / 1024, 1)

for run in runs:
    run['pythonPeakMemoryMb'] = memory.get(f"{run['seed']}:{run['scenario']}")

dump('performance.json', {
    'generatedAt': GENERATED,
    'note': ('同机同时刻串行测量，含 shapely 连续四维检查与资源日历；'
             'pythonPeakMemoryMb 为独立 tracemalloc 通路的峰值，该通路的墙钟时间不作为计划耗时。'
             '不含浏览器渲染帧率：FPS 与台账筛选响应需在真实界面复核，见完成报告的未验证项。'),
    'networkSecondsCold': network_cold_seconds,
    'networkSecondsWarm': network_warm_seconds,
    'runs': runs,
    'targets': {'planSecondsBudget': 8.0, 'ledgerFilterBudgetMs': 300, 'browserFpsTarget': 30},
    'verdict': {
        'networkWithinBudget': network_cold_seconds <= 2.0,
        'planWithinBudget': all(r['planSeconds'] <= 8.0 for r in runs),
        'slowestPlanSeconds': max(r['planSeconds'] for r in runs),
        'altitudeCeilingRespected': all(
            r['highestCarAglM'] is not None
            and r['highestCarAglM'] <= network['assumptions']['flightCeilingsAglM']['CAR']
            and r['highestDeliveryAglM'] <= network['assumptions']['flightCeilingsAglM']['DELIVERY']
            for r in runs),
    },
})
print('DONE')
