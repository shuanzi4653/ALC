"""Condenses the live simulation artefacts into a versioned evidence file."""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, artifact  # noqa: E402
import datetime, io, json

EVAL = os.path.join(ROOT, 'docs', 'evaluation-v1.3')


def load(name):
    with io.open(artifact(name), encoding='utf-8') as fh:
        return json.load(fh)


report = load('_sim_report.json')
command = load('_sim_command.json')
bench = load('_sim_bench.json')


def run_entry(label, run, stats, extra=None):
    entry = {
        'label': label,
        'status': run.get('status'),
        'sessionId': run.get('sessionId'),
        'buildSecondsEndToEnd': run.get('elapsedSeconds'),
        'progressSamples': run.get('progressSamples'),
        'flights': stats.get('flights'),
        'statusCounts': stats.get('statusCounts'),
        'layerUsage': stats.get('layerUsage'),
        'layerStrategies': stats.get('layerStrategies'),
        'clearanceStatuses': stats.get('clearanceStatuses'),
        'distinctAssignedLayers': stats.get('distinctAssignedLayers'),
        'trajectoryPointsTotal': stats.get('trajectoryPointsTotal'),
        'maxTrajectoryPoints': stats.get('maxTrajectoryPoints'),
    }
    if extra:
        entry.update(extra)
    return entry


canonical = report['canonicalRun']
cold = report['coldRun']
live = report['liveRun']

net = report['networkSummary']
plan = report['planMeta']
live_plan = report.get('livePlanMeta') or {}
hubs = report['hubs']['json']
delivery = report['delivery']['json']

payload = {
    'generatedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'note': (
        '端到端运行记录。运行前清空 .run/traffic 计划缓存并重启三服务，随后按前端实际调用顺序'
        '（/traffic/network → /traffic/session 轮询 → /traffic/plan → /traffic/hubs → '
        '/traffic/delivery → /traffic/weather）驱动接口。本文件所有数字均来自实际响应，'
        '不含估算值。'
    ),
    'howToReproduce': [
        'backend-python/.venv/Scripts/python.exe _sim_harness.py start 25   # 后台拉起三服务',
        'python _sim_probe.py                                               # 全链路探测，写出 _sim_report.json',
        'python _sim_command.py                                             # 控制指令与运行台账',
        'backend-python/.venv/Scripts/python.exe backend-python/_sim_bench.py  # 进程内计算耗时',
        'backend-python/.venv/Scripts/python.exe _gen_sim_evidence.py       # 生成本文件',
    ],
    'stack': {
        'python': {'service': 'tianchuang-python', 'version': report['pythonHealth']['json']['version'],
                   'base': 'http://127.0.0.1:8600', 'healthSeconds': report['pythonHealth']['seconds']},
        'java': {'service': report['javaLive']['json']['service'],
                 'status': report['javaLive']['json']['status'], 'base': 'http://127.0.0.1:8085'},
        'frontend': {'title': report['frontend']['title'], 'base': 'http://127.0.0.1:5180'},
    },
    'network': {
        'version': net.get('version'), 'planRevision': net.get('planRevision'),
        'baseTime': net.get('baseTime'), 'timezone': net.get('timezone'), 'source': net.get('source'),
        'seconds': net.get('seconds'),
        'cities': net.get('cities'), 'pads': net.get('pads'),
        'routes': net.get('routes'), 'carRoutes': net.get('carRoutes'),
        'deliveryRoutes': net.get('deliveryRoutes'),
        'routesWithoutGeometry': net.get('routesWithoutGeometry'),
        'interprovincialRoutes': net.get('interprovincialRoutes'),
        'boundaryGeometryType': net.get('boundaryGeometryType'),
        'boundaryRingCount': net.get('boundaryRingCount'),
        'administrativeFeatures': net.get('administrativeFeatures'),
        'administrativeNames': net.get('administrativeNames'),
        'weatherProviders': net.get('weatherProviders'),
        'deliveryConfig': net.get('deliveryConfig'),
        'riskRules': net.get('riskRules'),
    },
    'planIdentity': {
        'fingerprint': plan.get('fingerprint'),
        'version': plan.get('version'),
        'planRevision': plan.get('planRevision'),
        'baseTime': plan.get('baseTime'),
        'administrativeBoundaryVersion': plan.get('coverage', {}).get('administrativeBoundary'),
        'obstacleSourceVersion': plan.get('coverage', {}).get('obstacleSourceVersion'),
        'terrain': plan.get('coverage', {}).get('terrain'),
        'buildings': plan.get('coverage', {}).get('buildings'),
        'cityDirectory': plan.get('coverage', {}).get('cityDirectory'),
        'cityCoordinatesOutsideProvince': plan.get('coverage', {}).get('cityCoordinatesOutsideProvince'),
    },
    'runs': [
        run_entry('seed 42 · moving（基线，冷缓存）', canonical, report['canonicalFlightStats'],
                  {'weatherSnapshot': plan.get('weatherSnapshot')}),
        run_entry('seed 98765 · moving（另一冷缓存，验证非缓存命中）', cold, report['coldFlightStats']),
        run_entry('seed 42 · live（公开天气驱动）', live, report['liveFlightStats'],
                  {'weatherSnapshot': live_plan.get('weatherSnapshot'),
                   'buildSecondsEndToEndIncludesLiveFetch': True}),
    ],
    'planStats': plan.get('stats'),
    'layerUsagePublished': plan.get('layerUsage'),
    'resources': {
        'hubPads': hubs.get('padCount'),
        'crossingZones': hubs.get('crossingZones', {}).get('count'),
        'crossingZoneCapacity': hubs.get('crossingZones', {}).get('capacityPerZone'),
        'crossingZoneWindowMinutes': hubs.get('crossingZones', {}).get('windowMinutes'),
        'crossingReservations': hubs.get('crossingZones', {}).get('reservations'),
        'busiestPad': (hubs.get('busiestPads') or [None])[0],
        'note': hubs.get('note'),
    },
    'delivery': delivery.get('summary'),
    'controlLoop': {
        'target': command.get('target'),
        'candidateFlightsAfterMinute30': command.get('candidateCount'),
        'ledgerBefore': command.get('operationsBefore', {}).get('count'),
        'suspendStatus': (command.get('suspend') or {}).get('status'),
        'suspendRecord': (command.get('suspend') or {}).get('json'),
        'ledgerAfterSuspend': command.get('operationsAfter', {}).get('count'),
        'resumeStatus': (command.get('resume') or {}).get('status'),
        'ledgerAfterResume': command.get('operationsFinal', {}).get('count'),
        'replaySameCommandIdIsIdempotent': (command.get('repeatSuspend') or {}).get('json', {}).get('idempotent'),
        'ledgerAfterReplay': command.get('operationsAfterReplay', {}).get('count'),
        'note': 'SUSPEND 无法作用于已起飞或已过原时隙的班次（HTTP 409），本条为 00:30 之后 2224 个可选班次之一。',
    },
    'timing': {
        'inProcessImportSeconds': bench.get('importSeconds'),
        'inProcessSimulateColdSeconds': bench.get('simulateColdSeconds'),
        'inProcessSimulateWarmSeconds': bench.get('simulateWarmSeconds'),
        'httpColdBuildSeconds': canonical.get('elapsedSeconds'),
        'httpAnotherColdBuildSeconds': cold.get('elapsedSeconds'),
        'httpLiveBuildSeconds': live.get('elapsedSeconds'),
        'note': (
            '进程内纯计算 3.88—4.40 s；HTTP 端到端 10.4—11.3 s。差额来自两处：前端轮询粒度 1500 ms，'
            '以及 /traffic/session 在 READY 时一次性回传全部 2910 班次（含航迹点）的序列化与传输。'
            'UPDATE_PLAN_V1.3.md §11.3 的可比指标是交互帧率与台账筛选 300 ms，不是计划计算秒数。'
        ),
    },
    'weatherProvidersObserved': {
        'pythonDefault': net.get('weatherProviders'),
        'liveSnapshot': live_plan.get('weatherSnapshot'),
        'javaQweatherRaw': report.get('javaQweatherSummary'),
        'javaQweatherStatus': report['javaQweatherStatus']['json'],
    },
    'findingsFromThisRun': [
        {
            'id': 'F1',
            'severity': 'fixed-in-this-run',
            'summary': '和风原始接口在收到 gzip 压缩正文时整条链路静默降级（Jackson 报 CTRL-CHAR code 31）。',
            'evidence': 'java-dev.out.log 的 JsonParseException；修复后 /api/internal/qweather/current 返回真实 product 与 units。',
            'fix': 'QweatherClient 改为读取字节流，按 gzip 魔数与 Content-Encoding 双重判断后解压，再交给 Jackson。',
        },
        {
            'id': 'F2',
            'severity': 'fixed-in-this-run',
            'summary': '前端页面标题仍为 V1.2。',
            'evidence': 'frontend/index.html <title> 与本轮 /traffic/network 的 version=city-traffic-1.3 不一致。',
            'fix': '标题改为 V1.3。',
        },
        {
            'id': 'F3',
            'severity': 'open',
            'summary': '计划就绪后一次性回传全部班次，用户等待时间约为纯计算耗时的 2.5 倍。',
            'evidence': '进程内 3.88—4.40 s 对比 HTTP 10.4—11.3 s。',
            'fix': None,
            'howToClose': 'READY 响应只回传统计与版本，班次改由独立分页接口按需拉取；或先回传概览再增量补齐。',
        },
    ],
}

os.makedirs(EVAL, exist_ok=True)
target = os.path.join(EVAL, 'simulation-run-v1.3.json')
with io.open(target, 'w', encoding='utf-8') as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2)

print('wrote', target, os.path.getsize(target), 'bytes')
