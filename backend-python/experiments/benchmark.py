"""Frozen synthetic comparison. Run from backend-python; never calls network or packages."""
import csv
import hashlib
import json
import math
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from weather.engine import WeatherWorld, REGIONS
from weather.geometry import project, boundary
from planning.router import evaluate, OPEN
from shapely.geometry import Point

OUT = Path(__file__).resolve().parents[2] / 'docs' / 'evaluation-v1'


def fixture(index):
    family = index // 10
    rid = list(REGIONS)[index % 3]
    region = REGIONS[rid]
    scenario = ['clear', 'calm', 'wind', 'rain', 'crossing', 'multi', 'unknown',
                'crossing', 'rain', 'multi', 'wind', 'clear'][family]
    task = dict(regionId=rid, **{'from': region['from'], 'to': region['to']},
                speedKmh=90, departureMinute=0, enduranceMinutes=100,
                latestArrivalMinute=180, workMinutes=5, bufferM=500)
    if family == 7:
        task['departureMinute'] = 95 + index % 10
        task['latestArrivalMinute'] = 270
    if family == 8:
        task['enduranceMinutes'] = 20
    if family == 9:
        task['latestArrivalMinute'] = 25
    if family == 10:
        task['bufferM'] = 3000
    if family == 11:
        task['to'] = [116.4, 39.9]
    return dict(id=f'case-{index:03}', family=family, scenario=scenario,
                seed=42 + index % 10, task=task)


def straight(world, task):
    distance = math.dist(project(task['from']), project(task['to']))
    duration = distance / (task['speedKmh'] * 1000 / 60)
    depart = task['departureMinute']
    return dict(status='DIRECT', coords=[task['from'], task['to']],
                arrivalMinutes=[depart, depart + duration], arrivalMinute=depart + duration + task['workMinutes'],
                flightMinutes=duration, extraMinutes=0, waitMinutes=0)


def independently_safe(world, task, candidate):
    if world.scenario == 'unknown':
        return False
    if candidate['flightMinutes'] + task['workMinutes'] > task['enduranceMinutes']:
        return False
    if candidate['arrivalMinute'] > task['latestArrivalMinute'] or candidate['extraMinutes'] > 60:
        return False
    allowed = boundary(REGIONS[task['regionId']]['name'])
    coords, times = candidate['coords'], candidate['arrivalMinutes']
    # Independent point-at-time check every <=10 seconds; not a proof of continuous safety.
    for i in range(1, len(coords)):
        a, b = project(coords[i - 1]), project(coords[i])
        count = max(1, math.ceil((times[i] - times[i - 1]) * 6))
        for j in range(count + 1):
            f = j / count
            point = Point(a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]))
            minute = times[i - 1] + f * (times[i] - times[i - 1])
            if not allowed.covers(point) or any(point.intersects(a['geometry']) for a in world.risks(minute, task['regionId'], task['bufferM'])):
                return False
    for minute in range(math.floor(times[-1]), math.ceil(candidate['arrivalMinute']) + 1):
        if any(Point(project(coords[-1])).intersects(a['geometry']) for a in world.risks(minute, task['regionId'], task['bufferM'])):
            return False
    return True


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cases = [fixture(i) for i in range(120)]
    raw = json.dumps(cases, ensure_ascii=False, sort_keys=True, indent=2)
    (OUT / 'cases.json').write_text(raw, encoding='utf-8')
    metadata = dict(caseSha256=hashlib.sha256(raw.encode()).hexdigest(), python=sys.version,
                    platform=platform.platform(), caseCount=len(cases), checkStepSeconds=10,
                    source='SIMULATION', deadlineSeconds=2, note='No measured flight outcomes or calibrated probabilities')
    (OUT / 'environment.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    rows = []
    with (OUT / 'results.jsonl').open('w', encoding='utf-8') as output:
        for case in cases:
            for method in ['B0_STRAIGHT', 'B1_STATIC', 'B2_DYNAMIC', 'B3_BUFFERED']:
                world = WeatherWorld(case['seed'], case['scenario'], uncertainty=method == 'B3_BUFFERED')
                begin = time.perf_counter()
                candidates = [straight(world, case['task'])] if method == 'B0_STRAIGHT' else evaluate(
                    world, case['task'], mode='static' if method == 'B1_STATIC' else 'dynamic')
                latency = (time.perf_counter() - begin) * 1000
                available = [c for c in candidates if c['status'] in OPEN]
                chosen = min(available, key=lambda c: c['arrivalMinute']) if available else candidates[0]
                truth = WeatherWorld(case['seed'], case['scenario'], uncertainty=True)
                safe = independently_safe(truth, case['task'], chosen) if available else None
                row = dict(case=case['id'], method=method, status=chosen['status'],
                           conflict=safe is False, latencyMs=round(latency, 3),
                           extraMinutes=chosen.get('extraMinutes'), waitMinutes=chosen.get('waitMinutes'),
                           timeout=any(c.get('reason') == 'PLANNER_TIMEOUT' for c in candidates))
                rows.append(row)
                output.write(json.dumps(row) + '\n'); output.flush()
            if int(case['id'][-3:]) % 10 == 9:
                print(f"Completed {case['id']}", flush=True)
    summary = []
    for method in ['B0_STRAIGHT', 'B1_STATIC', 'B2_DYNAMIC', 'B3_BUFFERED']:
        group = [r for r in rows if r['method'] == method]
        times = sorted(r['latencyMs'] for r in group)
        opened = [r for r in group if r['status'] in OPEN]
        summary.append(dict(method=method, cases=len(group), opened=len(opened),
                            conflicts=sum(r['conflict'] for r in group),
                            safeOpened=sum(not r['conflict'] for r in opened),
                            closed=sum(r['status'] == 'CLOSED' for r in group),
                            unevaluated=sum(r['status'] == 'UNEVALUATED' for r in group),
                            timeout=sum(r['timeout'] for r in group), p95Ms=times[math.ceil(len(times)*.95)-1]))
    with (OUT / 'summary.csv').open('w', newline='', encoding='utf-8-sig') as output:
        writer = csv.DictWriter(output, fieldnames=list(summary[0])); writer.writeheader(); writer.writerows(summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
