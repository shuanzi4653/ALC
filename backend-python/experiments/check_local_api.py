"""20 local scenario/region transitions through the Java facade, no external requests."""
import json
import sys
import time
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from weather.engine import REGIONS
from planning.router import OPEN

rows = []
with httpx.Client(base_url='http://127.0.0.1:8085', trust_env=False, timeout=20) as client:
    for i in range(20):
        rid = list(REGIONS)[i % 3]; r = REGIONS[rid]
        scenario = ['clear', 'crossing', 'rain', 'multi', 'unknown'][i % 5]
        task = dict(regionId=rid, **{'from':r['from'],'to':r['to']}, speedKmh=90,
                    departureMinute=i, enduranceMinutes=100, latestArrivalMinute=180, workMinutes=5, bufferM=500)
        start = time.perf_counter()
        response = client.post('/api/tasks/evaluate', json=dict(scenario=scenario, seed=42,
            origin='2026-09-13T00:00:00+08:00', task=task)); response.raise_for_status()
        record = response.json()
        assert record['task'] == task and record['scenario'] == scenario
        for c in record['candidates']:
            if c['status'] in OPEN:
                assert c['coords'][0] == task['from'] and c['coords'][-1] == task['to']
        if scenario == 'unknown': assert record['status'] == 'UNEVALUATED'
        frame = client.get('/api/workspace/frame', params=dict(scenario=scenario, seed=42, minute=i,
            origin=record['origin'], bufferM=3000)); frame.raise_for_status()
        assert all(a['bufferM'] == 3000 for a in frame.json()['areas'])
        replay = client.get('/api/replays/' + record['decisionId']); replay.raise_for_status()
        assert replay.json()['reproduced'] and replay.json()['verified']
        rows.append(dict(index=i, region=rid, scenario=scenario, status=record['status'],
                         replay=True, latencyMs=round((time.perf_counter()-start)*1000)))
    stations = client.get('/api/observations'); stations.raise_for_status()
    assert [r['status'] for r in stations.json()['regions']] == ['HISTORICAL']*3
out = Path(__file__).resolve().parents[2] / 'docs' / 'evaluation-v1' / 'local-integration.json'
out.write_text(json.dumps(dict(transitions=rows, observations='3 historical regions',
    note='Short integration run, not a two-hour soak test'), indent=2), encoding='utf-8')
print(f'{len(rows)} transitions, exact endpoints, buffer consistency and replays passed')
