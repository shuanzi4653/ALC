"""Local decision records and deterministic replay. No publication or packaging."""
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from functools import lru_cache
from pathlib import Path
from contextlib import contextmanager

from weather.engine import WeatherWorld, REGIONS, MODEL_VERSION, SCENARIOS
from weather.geometry import BOUNDARY_VERSION
from planning.router import evaluate, verify_candidate, OPEN, ALGORITHM_VERSION

ROOT = Path(__file__).resolve().parent.parent
VERSION = (ROOT / 'VERSION').read_text().strip()
DB = Path(os.environ.get('TIANCHUANG_DECISION_DB', ROOT / '.run' / 'decisions.sqlite3'))
LOCK = threading.RLock()
ENGINE_FINGERPRINT = hashlib.sha256(b''.join((Path(__file__).parent / p).read_bytes() for p in
    ('weather/engine.py', 'weather/geometry.py', 'planning/router.py', 'decision_service.py'))).hexdigest()[:20]


@contextmanager
def connection():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, created TEXT NOT NULL, body TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS origins (id TEXT PRIMARY KEY, origin TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS explanations (id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, body TEXT NOT NULL)')
    try:
        with db:
            yield db
    finally:
        db.close()


def valid_origin(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('时间原点必须包含时区')
    return parsed.isoformat()


def scenario_origin(scenario, seed):
    with LOCK, connection() as db:
        key = f'{scenario}:{seed}'
        row = db.execute('SELECT origin FROM origins WHERE id=?', (key,)).fetchone()
        if row:
            return row[0]
        value = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        db.execute('INSERT INTO origins VALUES (?,?)', (key, value))
        return value


@lru_cache(maxsize=24)
def world_for(scenario, seed, origin, uncertainty=True):
    return WeatherWorld(seed, scenario, origin, uncertainty)


def frame(scenario, seed, minute, region_id=None, origin=None, uncertainty=True, buffer_m=500):
    origin = valid_origin(origin or scenario_origin(scenario, seed))
    w = world_for(scenario, seed, origin, uncertainty)
    result = w.frame(minute, region_id, buffer_m)
    result.update({'origin': origin, 'scenario': scenario, 'seed': seed,
                   'validTime': (datetime.fromisoformat(origin) + timedelta(minutes=minute)).isoformat(),
                   'scenarioId': f'{scenario}:{seed}:{origin}', 'revision': 1,
                   'regions': [{'id': key, **value} for key, value in REGIONS.items()]})
    return result


def assess(request):
    start = time.perf_counter()
    scenario, seed = request['scenario'], request['seed']
    origin = valid_origin(request.get('origin') or scenario_origin(scenario, seed))
    task = request['task']
    world = world_for(scenario, seed, origin, request.get('uncertainty', True))
    planner_budget = 8
    candidates = evaluate(world, task, deadline_seconds=planner_budget)
    for i, candidate in enumerate(candidates):
        candidate['candidateId'] = f'candidate-{i}'
        if not verify_candidate(world, task, candidate):
            candidate.update(status='UNEVALUATED', reason='VERIFICATION_FAILED', coords=[])
    available = [c for c in candidates if c['status'] in OPEN]
    chosen = min(available, key=lambda c: c['arrivalMinute']) if available else candidates[0]
    canonical = {'scenario': scenario, 'seed': seed, 'origin': origin, 'task': task,
                 'uncertainty': request.get('uncertainty', True), 'modelVersion': MODEL_VERSION,
                 'algorithmVersion': ALGORITHM_VERSION, 'boundaryVersion': BOUNDARY_VERSION, 'version': VERSION,
                 'engineFingerprint': ENGINE_FINGERPRINT, 'plannerBudgetSeconds': planner_budget}
    interrupted = any(c['reason'] == 'PLANNER_TIMEOUT' for c in candidates)
    if interrupted:
        # A runtime timeout is not a deterministic property of the input. Never pin retries to it.
        canonical['executionAttempt'] = uuid.uuid4().hex
    identity = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    current = frame(scenario, seed, task['departureMinute'], task['regionId'], origin, canonical['uncertainty'], task['bufferM'])
    evidence = [{'id': 'task', 'title': '任务参数', 'text': f"{REGIONS[task['regionId']]['name']}；速度{task['speedKmh']}km/h；续航{task['enduranceMinutes']}分钟；最晚第{task['latestArrivalMinute']}分钟到达。"},
                {'id': 'source', 'title': '数据来源', 'text': '本次使用可复现模拟单体和区域风场，非官方实况预报。情景影响带不是校准概率。'},
                {'id': 'constraints', 'title': '运行约束', 'text': '禁飞和谨慎区域均不可穿越；额外绕行超过60分钟关闭；未知数据不得放行。'},
                {'id': 'decision', 'title': '校验结论', 'text': f"本次选择{chosen['candidateId']}，状态{chosen['status']}，原因{chosen['reason']}。"}]
    for c in candidates:
        detail = f"{c['candidateId']}：{c['status']}，{c['reason']}"
        if c['status'] in OPEN:
            detail += f"；飞行{c['flightMinutes']:.1f}分钟，等待{c['waitMinutes']:.0f}分钟，绕行增加{c['extraMinutes']:.1f}分钟，预计第{c['arrivalMinute']:.1f}分钟完成"
        evidence.append({'id': c['candidateId'], 'title': '候选方案', 'text': detail})
    for area in current['areas']:
        evidence.append({'id': area['id'], 'title': '气象限制', 'text': f"{area['regionId']}单体{area['sourceCellId']}触发{area['zoneType']}；{area['reason']}值{area['value']}；安全缓冲{area['bufferM']}米。"})
    result = {**canonical, 'decisionId': identity, 'runId': identity, 'revision': 1,
              'candidates': candidates, 'selectedCandidateId': chosen['candidateId'],
              'status': chosen['status'], 'evidence': evidence, 'frame': current,
              'evaluationComplete': not interrupted,
              'latencyMs': round((time.perf_counter() - start) * 1000),
              'createdAt': datetime.now(timezone.utc).isoformat()}
    # Content address refers to INPUT and model identity; never overwrite a prior record.
    with LOCK, connection() as db:
        db.execute('INSERT OR IGNORE INTO records VALUES (?,?,?)',
                   (identity, result['createdAt'], json.dumps(result, ensure_ascii=False, allow_nan=False)))
        return json.loads(db.execute('SELECT body FROM records WHERE id=?', (identity,)).fetchone()[0])


def get_record(identity):
    if len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
        raise KeyError('Unknown decision')
    with connection() as db:
        row = db.execute('SELECT body FROM records WHERE id=?', (identity,)).fetchone()
    if not row:
        raise KeyError('Unknown decision')
    return json.loads(row[0])


def history():
    with connection() as db:
        rows = db.execute('SELECT body FROM records ORDER BY created DESC LIMIT 30').fetchall()
    result = []
    for row in rows:
        r = json.loads(row[0])
        result.append({k: r[k] for k in ('decisionId', 'createdAt', 'scenario', 'seed', 'status', 'task')})
    return result


def save_explanation(result):
    body = json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False)
    identity = hashlib.sha256(body.encode()).hexdigest()
    with LOCK, connection() as db:
        db.execute('INSERT OR IGNORE INTO explanations VALUES (?,?,?)', (identity, result['decisionId'], body))
    return identity


def replay(identity):
    recorded = get_record(identity)
    compatible = (recorded['modelVersion'] == MODEL_VERSION and recorded['algorithmVersion'] == ALGORITHM_VERSION
                  and recorded['boundaryVersion'] == BOUNDARY_VERSION
                  and recorded.get('engineFingerprint') == ENGINE_FINGERPRINT)
    if not compatible:
        return {'record': recorded, 'reproduced': False, 'reason': 'VERSION_MISMATCH'}
    world = WeatherWorld(recorded['seed'], recorded['scenario'], recorded['origin'], recorded['uncertainty'])
    if not recorded.get('evaluationComplete', True):
        return {'record': recorded, 'reproduced': False, 'reason': 'ORIGINAL_COMPUTATION_INTERRUPTED',
                'verified': all(verify_candidate(world, recorded['task'], c) for c in recorded['candidates'])}
    candidates = evaluate(world, recorded['task'], deadline_seconds=recorded.get('plannerBudgetSeconds', 8))
    original = recorded['candidates']
    same = len(candidates) == len(original) and all(
        c == {k: v for k, v in old.items() if k != 'candidateId'} for c, old in zip(candidates, original))
    return {'record': recorded, 'reproduced': same, 'reason': 'MATCH' if same else 'RESULT_MISMATCH',
            'verified': all(verify_candidate(world, recorded['task'], c) for c in candidates)}
