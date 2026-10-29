"""End-to-end harness for the V1.3 simulation run.

Modes:
  start  - launch the three services detached from the sandbox job, wait until all
           three ports answer, record PIDs, then hold them up for --minutes.
  probe  - drive the full traffic simulation over HTTP and write _sim_report.json.
  stop   - terminate the recorded services.

The sandbox denies CREATE_BREAKAWAY_FROM_JOB, so `start` is meant to be run as a
background task: the services stay alive for as long as this process does.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, artifact  # noqa: E402
from _node import NODE as NODE_EXE  # noqa: E402
import io, json, os, socket, subprocess, sys, time, urllib.error, urllib.request

RUN = os.path.join(ROOT, '.run')
JDK = r'C:\Users\12921\.jdks\ms-17.0.19'
PY_EXE = os.path.join(ROOT, 'backend-python', '.venv', 'Scripts', 'python.exe')
JAVA_EXE = os.path.join(JDK, 'bin', 'java.exe')
VITE = os.path.join(ROOT, 'frontend', 'node_modules', 'vite', 'bin', 'vite.js')
CLASSPATH_FILE = os.path.join(RUN, 'java-classpath.txt')
CLASSES = os.path.join(ROOT, 'backend-java', 'target', 'classes')
# Process ids are runtime state, not an artefact: they belong under .run/.
PIDS = os.path.join(RUN, '_sim_pids.json')

PY = 'http://127.0.0.1:8600'
JAVA = 'http://127.0.0.1:8085'
FE = 'http://127.0.0.1:5180'

DETACHED = 0x00000008 | 0x00000200


def child_env():
    env = {k.upper(): v for k, v in os.environ.items()}
    # A normal workstation has no localhost proxy; the sandbox exports one, which
    # would make the Python service proxy its call to the Java weather bridge.
    env['NO_PROXY'] = '127.0.0.1,localhost'
    env['no_proxy'] = '127.0.0.1,localhost'
    env['JAVA_HOME'] = JDK
    return env


def port_open(port, timeout=0.6):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect(('127.0.0.1', port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def start(minutes):
    os.makedirs(RUN, exist_ok=True)
    env = child_env()
    classpath = CLASSES + ';' + io.open(CLASSPATH_FILE, encoding='utf-8').read().strip()
    java_args = [JAVA_EXE, '-cp', classpath, 'com.tianchuang.TianchuangApplication',
                 '--server.port=8085', '--server.address=127.0.0.1', '--local.source-mode=true',
                 '--push.mail.enabled=false', '--push.dingtalk-webhook=', '--push.feishu-webhook=',
                 '--push.wecom-webhook=']
    specs = [
        ('python', [PY_EXE, '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8600'],
         os.path.join(ROOT, 'backend-python'), 'python-dev'),
        ('java', java_args, ROOT, 'java-dev'),
        ('frontend', [NODE_EXE, VITE, '--host', '127.0.0.1', '--port', '5180', '--strictPort'],
         os.path.join(ROOT, 'frontend'), 'frontend-dev'),
    ]
    started = {}
    for name, args, cwd, stem in specs:
        out = io.open(os.path.join(RUN, stem + '.out.log'), 'wb')
        err = io.open(os.path.join(RUN, stem + '.err.log'), 'wb')
        proc = subprocess.Popen(args, cwd=cwd, env=env, stdout=out, stderr=err,
                                creationflags=DETACHED, close_fds=True,
                                stdin=subprocess.DEVNULL)
        started[name] = {'pid': proc.pid, 'startedAt': time.strftime('%Y-%m-%dT%H:%M:%S')}
        print(name, 'pid', proc.pid, flush=True)

    deadline = time.time() + 150
    ready = False
    while time.time() < deadline:
        if port_open(8600) and port_open(8085) and port_open(5180):
            ready = True
            break
        time.sleep(1)
    print('ready =', ready, flush=True)
    with io.open(PIDS, 'w', encoding='utf-8') as fh:
        json.dump({'ready': ready, 'services': started}, fh, ensure_ascii=False, indent=2)

    if not ready:
        return 1
    # Hold the services up so the probe can run from a separate command.
    until = time.time() + minutes * 60
    while time.time() < until:
        if not port_open(8600, 0.3):
            print('python went away, stopping hold', flush=True)
            break
        time.sleep(5)
    stop()
    return 0


def stop():
    try:
        state = json.load(io.open(PIDS, encoding='utf-8'))
    except Exception:
        print('no pid file')
        return
    for name, info in state.get('services', {}).items():
        pid = info.get('pid')
        if not pid:
            continue
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'],
                       capture_output=True, text=True)
        print('stopped', name, pid)
    try:
        os.remove(PIDS)
    except OSError:
        pass


def opener():
    # Bypass the sandbox HTTP proxy for loopback calls.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(method, url, payload=None, timeout=180):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    start_at = time.time()
    try:
        with opener().open(req, timeout=timeout) as r:
            body = r.read().decode('utf-8', 'replace')
            parsed = None
            if body.strip().startswith(('{', '[')):
                parsed = json.loads(body)
            return {'ok': True, 'status': r.status,
                    'seconds': round(time.time() - start_at, 3),
                    'json': parsed, 'text': None if parsed is not None else body}
    except urllib.error.HTTPError as e:
        return {'ok': False, 'status': e.code, 'seconds': round(time.time() - start_at, 3),
                'error': e.read().decode('utf-8', 'replace')[:500]}
    except Exception as e:
        return {'ok': False, 'status': None, 'seconds': round(time.time() - start_at, 3),
                'error': '%s: %s' % (type(e).__name__, str(e)[:300])}


def probe():
    import re
    report = {}

    report['pythonHealth'] = call('GET', PY + '/health')
    report['javaLive'] = call('GET', JAVA + '/api/health/live')
    page = call('GET', FE + '/')
    title = ''
    if page.get('text'):
        m = re.search(r'<title>(.*?)</title>', page['text'], re.S)
        title = m.group(1).strip() if m else ''
    report['frontend'] = {'ok': page.get('ok'), 'status': page.get('status'), 'title': title}

    net = call('GET', PY + '/traffic/network')
    report['network'] = net
    if net.get('ok'):
        n = net['json']
        adm = n.get('administrativeBoundaries') or {}
        feats = adm.get('features') or []
        boundary = n.get('boundary') or {}
        report['networkSummary'] = {
            'seconds': net['seconds'],
            'cities': len(n.get('cities') or []),
            'connections': len(n.get('connections') or []),
            'pads': len(n.get('pads') or []),
            'routes': len(n.get('routes') or []),
            'crossingZones': len(n.get('crossingZones') or []),
            'weatherProviders': n.get('weatherProviders'),
            'boundaryGeometryType': (boundary.get('geometry') or {}).get('type'),
            'boundaryVersion': boundary.get('properties', {}).get('version')
                               or n.get('boundaryVersion'),
            'administrativeFeatures': len(feats),
            'administrativeNames': [f.get('properties', {}).get('name') for f in feats],
            'deliveryConfig': n.get('deliveryConfig'),
            'topKeys': sorted(n.keys()),
        }

    weather = call('GET', PY + '/traffic/weather?seed=42&scenario=moving&minute=30')
    report['weather'] = weather
    if weather.get('ok'):
        w = weather['json']
        report['weatherSummary'] = {
            'seconds': weather['seconds'],
            'provider': w.get('provider'), 'source': w.get('source'),
            'riskRules': w.get('riskRules'), 'clearance': w.get('clearance'),
            'coverage': w.get('coverage'), 'cells': len(w.get('cells') or []),
            'thunderProbability': w.get('thunderProbability'),
            'thunderEstimateSuppressed': w.get('thunderEstimateSuppressed'),
            'keys': sorted(w.keys()),
        }

    plan = call('GET', PY + '/traffic/plan?seed=42&scenario=moving')
    report['plan'] = plan
    if plan.get('ok'):
        p = plan['json']
        flights = p.get('flights') or []
        usage, strategies, clearance = {}, {}, set()
        for f in flights:
            usage['%s:%s' % (f.get('mode'), f.get('assignedLayerAglM'))] = \
                usage.get('%s:%s' % (f.get('mode'), f.get('assignedLayerAglM')), 0) + 1
            if f.get('layerStrategy'):
                strategies[f['layerStrategy']] = strategies.get(f['layerStrategy'], 0) + 1
            if f.get('clearanceStatus'):
                clearance.add(f['clearanceStatus'])
        report['planSummary'] = {
            'seconds': plan['seconds'],
            'planRevision': p.get('planRevision'), 'version': p.get('version'),
            'fingerprint': p.get('fingerprint'),
            'flights': len(flights),
            'scheduled': sum(1 for f in flights if f.get('status') == 'SCHEDULED'),
            'closed': sum(1 for f in flights if f.get('status') == 'CLOSED'),
            'layerUsage': usage, 'layerStrategies': strategies,
            'clearanceStatuses': sorted(clearance),
            'distinctAssignedLayers': sorted({f.get('assignedLayerAglM') for f in flights
                                              if f.get('assignedLayerAglM') is not None}),
            'conflictsResolved': p.get('conflictsResolved') or p.get('resolvedConflicts'),
            'detours': p.get('detours') or p.get('detourCount'),
            'crossingReservations': p.get('crossingReservations') or p.get('reservations'),
            'deliveryConfig': p.get('deliveryConfig'),
            'topKeys': sorted(p.keys()),
            'sampleFlight': flights[0] if flights else None,
        }

    session = call('GET', PY + '/traffic/session?seed=42&scenario=moving')
    report['session'] = session
    if session.get('ok'):
        s = session['json']
        report['sessionSummary'] = {
            'seconds': session['seconds'],
            'sessionId': s.get('sessionId'), 'planRevision': s.get('planRevision'),
            'version': s.get('version'), 'baseTime': s.get('baseTime'),
            'topKeys': sorted(s.keys()),
            'flightCount': len(s.get('flights') or []),
            'nested': {k: (len(v) if isinstance(v, list) else type(v).__name__)
                       for k, v in s.items() if k not in ('sessionId', 'planRevision',
                                                          'version', 'baseTime')},
        }

    hubs = call('GET', PY + '/traffic/hubs?seed=42&scenario=moving')
    report['hubs'] = hubs
    if hubs.get('ok'):
        h = hubs['json']
        report['hubsSummary'] = {
            'keys': sorted(h.keys()) if isinstance(h, dict) else type(h).__name__,
            'counts': {k: len(v) for k, v in h.items() if isinstance(v, list)}
            if isinstance(h, dict) else None,
        }

    delivery = call('GET', PY + '/traffic/delivery?seed=42&scenario=moving')
    report['delivery'] = delivery
    if delivery.get('ok'):
        d = delivery['json']
        report['deliverySummary'] = {}
        if isinstance(d, dict):
            for k, v in d.items():
                report['deliverySummary'][k] = v if not isinstance(v, list) else 'list[%d]' % len(v)

    # A real control command, then read back the ledger.
    target = None
    for f in (plan.get('json') or {}).get('flights', []) if plan.get('ok') else []:
        if f.get('status') == 'SCHEDULED':
            target = f
            break
    session_id = (report.get('sessionSummary') or {}).get('sessionId')
    plan_rev = (report.get('sessionSummary') or {}).get('planRevision') or 'traffic-plan-v1.3'
    if target and session_id:
        report['commandTarget'] = target['id']
        report['command'] = call('POST', PY + '/traffic/command', {
            'seed': 42, 'scenario': 'moving', 'flightId': target['id'], 'minute': 30,
            'action': 'HOLD', 'planRevision': plan_rev, 'commandId': 'sim-probe-hold-1'})
        report['operations'] = call('GET', PY + '/traffic/operations?sessionId=' + session_id)
        if report['operations'].get('ok'):
            ops = report['operations']['json']
            report['operationsSummary'] = {
                'type': type(ops).__name__,
                'count': len(ops) if isinstance(ops, list) else len(ops.keys()),
                'sample': (ops[:1] if isinstance(ops, list) and ops else ops),
            }

    report['javaQweatherStatus'] = call('GET', JAVA + '/api/internal/qweather/status')
    report['javaQweatherCurrent'] = call(
        'GET', JAVA + '/api/internal/qweather/current?lat=45.75&lon=126.65')
    if report['javaQweatherCurrent'].get('ok'):
        j = report['javaQweatherCurrent'].get('json') or {}
        report['javaQweatherSummary'] = {
            'provider': j.get('provider'), 'product': j.get('product'),
            'requestedLocation': j.get('requestedLocation'), 'units': j.get('units'),
            'thunderEstimate': j.get('thunderEstimate'),
            'thunderEstimateMethod': j.get('thunderEstimateMethod'),
            'qualityFlags': j.get('qualityFlags'), 'note': j.get('note'),
        }
    else:
        report['javaQweatherSummary'] = {'error': report['javaQweatherCurrent'].get('error')}

    with io.open(artifact('_sim_report.json'), 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, default=str)

    for key in ('pythonHealth', 'frontend', 'networkSummary', 'weatherSummary', 'planSummary',
                'sessionSummary', 'hubsSummary', 'deliverySummary', 'commandTarget', 'command',
                'operationsSummary', 'javaQweatherSummary'):
        print('---', key, flush=True)
        print(json.dumps(report.get(key), ensure_ascii=False, default=str)[:2000], flush=True)
    return 0


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'probe'
    if mode == 'start':
        mins = float(sys.argv[2]) if len(sys.argv) > 2 else 20
        sys.exit(start(mins))
    if mode == 'stop':
        stop()
        sys.exit(0)
    sys.exit(probe())
