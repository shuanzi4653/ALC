"""Read-only local source-service integration checks; no external service calls."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[2]
results=[]
with httpx.Client(base_url='http://127.0.0.1:8085',trust_env=False,timeout=20) as client:
    version=client.get('/api/system/version'); version.raise_for_status()
    assert version.json()['version']==(ROOT/'VERSION').read_text().strip()
    network=client.get('/api/traffic/network');network.raise_for_status();network=network.json()
    assert len(network['cities'])==36 and len(network['routes'])==161
    for scenario in ('moving','clear','unknown'):
        start=time.perf_counter()
        for attempt in range(30):
            response=client.get('/api/traffic/session',params=dict(seed=42,scenario=scenario))
            response.raise_for_status(); data=response.json()
            if data['status']=='READY':break
            assert data['status'] in ('BUILDING','BUSY'),data
            time.sleep(.5)
        assert data['status']=='READY'
        assert data['source']=='SIMULATION' and data['scenario']==scenario and data['seed']==42
        assert len(data['flights'])==1614
        assert len({f['id'] for f in data['flights']})==1614
        if scenario=='unknown': assert not data['stats']['accepted']
        else: assert data['stats']['accepted']>0
        if scenario=='moving': assert data['stats']['detours']>0
        repeat=client.get('/api/traffic/session',params=dict(seed=42,scenario=scenario)).json()
        assert data==repeat
        frames=[client.get('/api/traffic/weather',params=dict(seed=42,scenario=scenario,minute=t,cityId='1-01')).json() for t in (30,31)]
        assert all(f['minute']==t for f,t in zip(frames,(30,31)))
        if scenario=='moving':assert frames[0]['cells']!=frames[1]['cells']
        if scenario=='unknown':assert not frames[0]['winds'] and not frames[0]['available']
        results.append(dict(scenario=scenario,sessionId=data['sessionId'],fingerprint=data['fingerprint'],stats=data['stats'],roundTripSeconds=round(time.perf_counter()-start,3)))
    assert client.get('/api/traffic/session?seed=-1').status_code==422
    assert client.get('/api/traffic/weather?cityId=missing').status_code==422
target=ROOT/'docs/evaluation-v1.2/network-api-check.json';target.parent.mkdir(parents=True,exist_ok=True)
target.write_text(json.dumps(dict(checkedAt=datetime.now(timezone.utc).isoformat(),status='PASS',cases=results),ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False))
print('PASS: local Java-to-Python traffic interfaces, deterministic sessions, weather transitions and invalid input')
