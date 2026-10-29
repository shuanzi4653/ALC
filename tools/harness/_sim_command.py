"""Exercises a real control command against a flight that has not departed yet,
then reads the operations ledger back. Also reconciles the plan build timing.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, artifact  # noqa: E402
import io, json, time, urllib.error, urllib.request

PY = 'http://127.0.0.1:8600'


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
            return {'ok': True, 'status': r.status, 'seconds': round(time.time() - t0, 3),
                    'json': parsed, 'text': None if parsed is not None else body}
    except urllib.error.HTTPError as e:
        return {'ok': False, 'status': e.code, 'seconds': round(time.time() - t0, 3),
                'error': e.read().decode('utf-8', 'replace')[:400]}
    except Exception as e:
        return {'ok': False, 'status': None, 'seconds': round(time.time() - t0, 3),
                'error': '%s: %s' % (type(e).__name__, str(e)[:200])}


out = {}

session = call('GET', PY + '/traffic/session?seed=42&scenario=moving')
payload = session.get('json') or {}
flights = payload.get('flights') or []
session_id = payload.get('sessionId')
out['session'] = {'status': payload.get('status'), 'sessionId': session_id,
                  'flights': len(flights)}

minute = 30
future = sorted((f for f in flights
                 if f.get('status') == 'SCHEDULED' and f.get('departureMinute', 0) > minute + 5),
                key=lambda f: f['departureMinute'])
out['candidateCount'] = len(future)

if future and session_id:
    target = future[0]
    out['target'] = {k: target.get(k) for k in
                     ('id', 'mode', 'status', 'departureMinute', 'assignedLayerAglM',
                      'layerStrategy', 'separationAction')}

    before = call('GET', PY + '/traffic/operations?sessionId=' + session_id)
    out['operationsBefore'] = {'count': len(before.get('json') or [])}

    suspend = call('POST', PY + '/traffic/command', {
        'seed': 42, 'scenario': 'moving', 'flightId': target['id'], 'minute': minute,
        'action': 'SUSPEND', 'planRevision': 'traffic-plan-v1.3', 'commandId': 'sim-suspend-1'})
    out['suspend'] = suspend

    after = call('GET', PY + '/traffic/operations?sessionId=' + session_id)
    records = after.get('json') or []
    out['operationsAfter'] = {'count': len(records), 'records': records[:3]}

    resume = call('POST', PY + '/traffic/command', {
        'seed': 42, 'scenario': 'moving', 'flightId': target['id'], 'minute': minute + 1,
        'action': 'RESUME', 'planRevision': 'traffic-plan-v1.3', 'commandId': 'sim-resume-1'})
    out['resume'] = resume

    final = call('GET', PY + '/traffic/operations?sessionId=' + session_id)
    final_records = final.get('json') or []
    out['operationsFinal'] = {'count': len(final_records), 'records': final_records[:3]}

    # Replaying the same command id must not append a second record.
    repeat = call('POST', PY + '/traffic/command', {
        'seed': 42, 'scenario': 'moving', 'flightId': target['id'], 'minute': minute,
        'action': 'SUSPEND', 'planRevision': 'traffic-plan-v1.3', 'commandId': 'sim-suspend-1'})
    out['repeatSuspend'] = repeat
    replayed = call('GET', PY + '/traffic/operations?sessionId=' + session_id)
    out['operationsAfterReplay'] = {'count': len(replayed.get('json') or [])}

with io.open(artifact('_sim_command.json'), 'w', encoding='utf-8') as fh:
    json.dump(out, fh, ensure_ascii=False, indent=2, default=str)

print(json.dumps(out, ensure_ascii=False, indent=2, default=str)[:4000])
