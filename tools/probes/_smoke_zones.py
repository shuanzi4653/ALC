"""Smoke test: does the plan still build, and what do the fixed zones do to it?"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import json
import time
from pathlib import Path


from traffic import service, zones  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


print('zones status:', json.dumps(zones.status(), ensure_ascii=False))
print()

start = time.perf_counter()
network = service.network()
print(f'network() {time.perf_counter() - start:.2f}s')
static = network['staticAirspace']
print('staticAirspace rules keys:', sorted(static['rules']))
print('staticAirspace status:', json.dumps(static['status'], ensure_ascii=False))
print('zones with geometry:', sum(1 for zone in static['zones'] if 'geometry' in zone))
print('registered only:', sum(1 for zone in static['zones'] if 'geometry' not in zone))
print()

for scenario in ('moving', 'clear'):
    start = time.perf_counter()
    result = service.simulate(seed=42, scenario=scenario)
    elapsed = time.perf_counter() - start
    stats = result['stats']
    print(f'--- {scenario}: {elapsed:.2f}s')
    print('  flights', stats['flights'], 'accepted', stats['accepted'], 'closed', stats['closed'])
    print('  staticAirspace', json.dumps(stats['staticAirspace'], ensure_ascii=False))
    reasons = {}
    for flight in result['flights']:
        if flight['status'] != 'SCHEDULED':
            reasons[flight['reason']] = reasons.get(flight['reason'], 0) + 1
    print('  closed reasons', json.dumps(reasons, ensure_ascii=False, sort_keys=True))
    example = next((f for f in result['flights'] if f['staticAirspace']['zones']), None)
    if example:
        print('  example flight', example['id'], example['name'])
        print('   ', json.dumps(example['staticAirspace'], ensure_ascii=False)[:600])
