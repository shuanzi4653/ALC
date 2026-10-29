"""Drives the full city-traffic simulation over HTTP against the running stack.

The plan is built asynchronously: GET /traffic/session returns a build handle that
must be polled until status becomes READY. Only then do /traffic/plan, /traffic/hubs
and /traffic/delivery answer. This script follows exactly that contract.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, artifact  # noqa: E402
import io, json, os, re, time, urllib.error, urllib.request

PY, JAVA, FE = 'http://127.0.0.1:8600', 'http://127.0.0.1:8085', 'http://127.0.0.1:5180'
STORE = os.path.join(ROOT, '.run', 'traffic')


def opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(method, url, payload=None, timeout=240):
    data, headers = None, {}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    t0 = time.time()
    try:
        with opener().open(req, timeout=timeout) as r:
            body = r.read().decode('utf-8', 'replace')
            parsed = json.loads(body) if body.strip().startswith(('{', '[')) else None
            return {'ok': True, 'status': r.status,
                    'seconds': round(time.time() - t0, 3), 'json': parsed,
                    'text': None if parsed is not None else body}
    except urllib.error.HTTPError as e:
        return {'ok': False, 'status': e.code, 'seconds': round(time.time() - t0, 3),
                'error': e.read().decode('utf-8', 'replace')[:500]}
    except Exception as e:
        return {'ok': False, 'status': None, 'seconds': round(time.time() - t0, 3),
                'error': '%s: %s' % (type(e).__name__, str(e)[:300])}


def session_flow(seed, scenario, limit=180):
    """Start (or join) the build and poll until a terminal status is reached."""
    url = '%s/traffic/session?seed=%d&scenario=%s' % (PY, seed, scenario)
    t0 = time.time()
    first = call('GET', url)
    samples = []
    payload = first.get('json') or {}
    if first.get('ok') and payload.get('status') == 'BUILDING':
        samples.append({'t': round(time.time() - t0, 2), 'progress': payload.get('progress')})
        while time.time() - t0 < limit:
            time.sleep(0.4)
            step = call('GET', url)
            payload = step.get('json') or {}
            samples.append({'t': round(time.time() - t0, 2), 'progress': payload.get('progress')})
            if payload.get('status') != 'BUILDING':
                break
    return {'status': payload.get('status'), 'elapsedSeconds': round(time.time() - t0, 3),
            'cached': first.get('seconds', 0) < 0.25 and payload.get('status') == 'READY'
                      and len(samples) == 0,
            'sessionId': payload.get('sessionId'),
            'progressSamples': samples[:8], 'payload': payload}


def flight_stats(payload):
    flights = payload.get('flights') or []
    usage, strategies, clearance, marks = {}, {}, set(), {}
    for f in flights:
        key = '%s:%s m' % (f.get('mode'), f.get('assignedLayerAglM'))
        usage[key] = usage.get(key, 0) + 1
        if f.get('layerStrategy'):
            strategies[f['layerStrategy']] = strategies.get(f['layerStrategy'], 0) + 1
        if f.get('clearanceStatus'):
            clearance.add(f['clearanceStatus'])
        marks[f.get('status')] = marks.get(f.get('status'), 0) + 1
    scheduled = next((f for f in flights if f.get('status') == 'SCHEDULED'), None)
    # A command is only legal before the flight leaves, so pick the earliest
    # departure that is still in the future at the probe's reference minute.
    probe_minute = 30
    suspendable = next((f for f in flights
                        if f.get('status') == 'SCHEDULED'
                        and (f.get('departureMinute') or 0) > probe_minute), None)
    return {
        'sessionId': payload.get('sessionId'),
        'flights': len(flights),
        'statusCounts': marks,
        'layerUsage': dict(sorted(usage.items())),
        'layerStrategies': strategies,
        'clearanceStatuses': sorted(clearance),
        'distinctAssignedLayers': sorted({f.get('assignedLayerAglM') for f in flights
                                          if f.get('assignedLayerAglM') is not None}),
        'trajectoryPointsTotal': sum(len(f.get('points') or []) for f in flights),
        'maxTrajectoryPoints': max((len(f.get('points') or []) for f in flights), default=0),
        'firstScheduled': ({k: scheduled.get(k) for k in
                            ('id', 'mode', 'status', 'assignedLayerAglM', 'layerStrategy',
                             'departureMinute', 'arrivalMinute', 'clearanceStatus')}
                           if scheduled else None),
        'suspendableFlight': ({k: suspendable.get(k) for k in
                               ('id', 'mode', 'status', 'departureMinute')} | {'commandMinute': probe_minute}
                              if suspendable else None),
        'sampleFlight': flights[0] if flights else None,
    }


report = {}

# ---- services ------------------------------------------------------------
report['pythonHealth'] = call('GET', PY + '/health')
report['javaLive'] = call('GET', JAVA + '/api/health/live')
page = call('GET', FE + '/')
title = ''
if page.get('text'):
    m = re.search(r'<title>(.*?)</title>', page['text'], re.S)
    title = m.group(1).strip() if m else ''
report['frontend'] = {'ok': page.get('ok'), 'status': page.get('status'), 'title': title}

# ---- network -------------------------------------------------------------
net = call('GET', PY + '/traffic/network')
report['network'] = net
if net.get('ok'):
    n = net['json']
    boundary = n.get('boundary') or {}
    adm = n.get('administrativeBoundaries') or {}
    feats = adm.get('features') or []
    routes = n.get('routes') or []
    report['networkSummary'] = {
        'seconds': net['seconds'],
        'version': n.get('version'), 'planRevision': n.get('planRevision'),
        'baseTime': n.get('baseTime'), 'timezone': n.get('timezone'), 'source': n.get('source'),
        'cities': len(n.get('cities') or []),
        'pads': len(n.get('pads') or []),
        'routes': len(routes),
        'carRoutes': sum(1 for r in routes if r.get('mode') == 'CAR'),
        'deliveryRoutes': sum(1 for r in routes if r.get('mode') == 'DELIVERY'),
        'routesWithoutGeometry': sum(1 for r in routes if not r.get('path')),
        'interprovincialRoutes': sum(1 for r in routes if r.get('interprovincial')),
        'boundaryGeometryType': boundary.get('type'),
        'boundaryRingCount': len(boundary.get('coordinates') or []),
        'administrativeFeatures': len(feats),
        'administrativeNames': [f.get('properties', {}).get('name') for f in feats],
        'weatherProviders': n.get('weatherProviders'),
        'deliveryConfig': n.get('deliveryConfig'),
        'riskRules': n.get('riskRules'),
        'assumptions': n.get('assumptions'),
        'topKeys': sorted(n.keys()),
    }

# ---- the canonical run ---------------------------------------------------
canonical = session_flow(42, 'moving')
canonical_stats = flight_stats(canonical['payload'])
canonical.pop('payload')
report['canonicalRun'] = canonical
report['canonicalFlightStats'] = canonical_stats

# ---- a genuinely cold run on an unused seed -----------------------------
cold = session_flow(98765, 'moving')
cold_stats = flight_stats(cold['payload'])
cold.pop('payload')
report['coldRun'] = cold
report['coldFlightStats'] = cold_stats

# ---- determinism: same seed twice must give the same fingerprint --------
again = call('GET', PY + '/traffic/plan?seed=42&scenario=moving')
report['planEndpoint'] = again
if again.get('ok'):
    report['planMeta'] = {
        'seconds': again['seconds'], 'planRevision': again['json'].get('planRevision'),
        'version': again['json'].get('version'), 'fingerprint': again['json'].get('fingerprint'),
        'baseTime': again['json'].get('baseTime'), 'stats': again['json'].get('stats'),
        'layerUsage': again['json'].get('layerUsage'),
        'coverage': again['json'].get('coverage'),
        'weatherSnapshot': again['json'].get('weatherSnapshot'),
        'riskRules': again['json'].get('riskRules'),
    }

# ---- weather -------------------------------------------------------------
weather = call('GET', PY + '/traffic/weather?seed=42&scenario=moving&minute=30')
report['weather'] = weather
if weather.get('ok'):
    w = weather['json']
    report['weatherSummary'] = {
        'seconds': weather['seconds'], 'provider': w.get('provider'), 'source': w.get('source'),
        'dataType': w.get('dataType'), 'scenario': w.get('scenario'), 'minute': w.get('minute'),
        'validAt': w.get('validAt'), 'available': w.get('available'),
        'qualityFlags': w.get('qualityFlags'), 'cells': len(w.get('cells') or []),
        'winds': len(w.get('winds') or []), 'riskRules': w.get('riskRules'),
        'keys': sorted(w.keys()),
    }

live = session_flow(42, 'live', limit=90)
live_stats = flight_stats(live['payload'])
live.pop('payload')
report['liveRun'] = live
report['liveFlightStats'] = live_stats
live_plan = call('GET', PY + '/traffic/plan?seed=42&scenario=live')
report['livePlan'] = live_plan
if live_plan.get('ok'):
    report['livePlanMeta'] = {
        'weatherSnapshot': live_plan['json'].get('weatherSnapshot'),
        'coverage': live_plan['json'].get('coverage'),
        'stats': live_plan['json'].get('stats'),
        'layerUsage': live_plan['json'].get('layerUsage'),
        'fingerprint': live_plan['json'].get('fingerprint'),
    }

# ---- hubs + delivery -----------------------------------------------------
hubs = call('GET', PY + '/traffic/hubs?seed=42&scenario=moving')
report['hubs'] = hubs
if hubs.get('ok'):
    h = hubs['json']
    report['hubsSummary'] = {
        'seconds': hubs['seconds'], 'keys': sorted(h.keys()),
        'listSizes': {k: len(v) for k, v in h.items() if isinstance(v, list)},
        'sessionId': h.get('sessionId'), 'planRevision': h.get('planRevision'),
        'sample': {k: v[:1] for k, v in h.items() if isinstance(v, list) and v},
    }

delivery = call('GET', PY + '/traffic/delivery?seed=42&scenario=moving')
report['delivery'] = delivery
if delivery.get('ok'):
    d = delivery['json']
    report['deliverySummary'] = {}
    for k, v in d.items():
        report['deliverySummary'][k] = v if not isinstance(v, list) else 'list[%d]' % len(v)

# ---- one real control command, then read the ledger ---------------------
# The flight must not have departed at the minute the command is issued, or the
# service correctly answers 409 "仅能操作尚未起飞的班次". `firstScheduled` is the
# earliest departure in the plan, so it is precisely the wrong target.
session_id = canonical_stats.get('sessionId')
target = canonical_stats.get('suspendableFlight')
if target and session_id:
    report['commandTarget'] = target
    report['command'] = call('POST', PY + '/traffic/command', {
        'seed': 42, 'scenario': 'moving', 'flightId': target['id'],
        'minute': target['commandMinute'],
        'action': 'SUSPEND', 'planRevision': 'traffic-plan-v1.3', 'commandId': 'sim-suspend-1'})
    report['operations'] = call('GET', PY + '/traffic/operations?sessionId=' + session_id)
    if report['operations'].get('ok'):
        ops = report['operations']['json']
        report['operationsSummary'] = {
            'type': type(ops).__name__,
            'count': len(ops) if isinstance(ops, list) else len(ops.keys()),
            'sample': ops[:1] if isinstance(ops, list) and ops else ops,
        }

# ---- Java weather bridge -------------------------------------------------
report['javaQweatherStatus'] = call('GET', JAVA + '/api/internal/qweather/status')
raw = call('GET', JAVA + '/api/internal/qweather/current?lat=45.75&lon=126.65')
report['javaQweatherCurrent'] = raw
if raw.get('ok'):
    j = raw.get('json') or {}
    report['javaQweatherSummary'] = {k: j.get(k) for k in
                                     ('provider', 'product', 'requestedLocation', 'units',
                                      'thunderEstimate', 'thunderEstimateMethod',
                                      'qualityFlags', 'note')}
elif raw.get('error'):
    report['javaQweatherSummary'] = {'httpStatus': raw.get('status'), 'error': raw['error']}

with io.open(artifact('_sim_report.json'), 'w', encoding='utf-8') as fh:
    json.dump(report, fh, ensure_ascii=False, indent=2, default=str)

for key in ('pythonHealth', 'frontend', 'networkSummary', 'canonicalRun', 'canonicalFlightStats',
            'coldRun', 'coldFlightStats', 'planMeta', 'weatherSummary', 'liveRun',
            'liveFlightStats', 'livePlanMeta', 'hubsSummary', 'deliverySummary', 'commandTarget',
            'command', 'operationsSummary', 'javaQweatherSummary'):
    print('--- ' + key, flush=True)
    print(json.dumps(report.get(key), ensure_ascii=False, default=str)[:2600], flush=True)
