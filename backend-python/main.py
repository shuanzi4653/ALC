# -*- coding: utf-8 -*-

import time
import logging
import os
from datetime import datetime
from pathlib import Path

import yaml
import hashlib
import json as _json

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response

from traffic import operators as _operators
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[1]

import real_weather
import track2_agent
import workspace

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("tianchuang")

APP_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_ROOT / "config" / "application.yml"

def load_deepseek_cfg():
    """读取共享配置中的 DeepSeek 段；配置文件缺失时返回空 Key（自动降级）"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            yml = yaml.safe_load(f) or {}
        ds = yml.get("deepseek") or {}
        configured_key = os.getenv("DEEPSEEK_API_KEY", str(ds.get("api-key") or "")).strip()
        if configured_key.startswith("${"):
            configured_key = ""
        return {"api_key": configured_key,
                "base_url": str(ds.get("base-url") or "https://api.deepseek.com").strip(),
                "model": str(ds.get("model") or "deepseek-chat").strip()}
    except Exception as e:  # noqa: BLE001
        log.warning("load config failed, deepseek disabled: %s", e)
        return {"api_key": "", "base_url": "https://api.deepseek.com", "model": "deepseek-chat"}

DS_CFG = load_deepseek_cfg()

import decision_service
import agent_tools
import data_sources
from weather.engine import REGIONS, SCENARIOS

app = FastAPI(title="天窗智巡 Python 智能服务", version=decision_service.VERSION)

def _startup_warm():
    import threading

    log = logging.getLogger(__name__)

    def worker():
        time.sleep(5)
        for channel in ('measured', 'virtual'):
            try:
                with workspace.bind(''):
                    weather_control.set_mode(
                        channel, actor='startup-warm', reason='服务启动预热')
                    traffic_service.session(42, 'live')
                log.info('startup warm: %s 已建场', channel)
            except Exception:  # noqa: BLE001
                log.exception('startup warm failed: %s', channel)
        try:
            with workspace.bind(''):
                weather_control.set_mode(
                    'measured', actor='startup-warm', reason='预热结束，复原为实测')
        except Exception:  # noqa: BLE001
            log.exception('startup warm: 复原通道失败')

    threading.Thread(target=worker, name='startup-warm', daemon=True).start()

@app.on_event('startup')
def _on_startup():
    _startup_warm()

@app.middleware('http')
async def bind_workspace(request, call_next):
    token = workspace.use(workspace.from_request(request))
    try:
        return await call_next(request)
    finally:
        workspace.reset(token)

@app.get('/observations')
def regional_observations():
    return data_sources.observations()

@app.get("/health")
def health():
    return {"status": "ok",
            "service": "tianchuang-python",
            "deepseek_configured": bool(DS_CFG["api_key"]),
            "model": DS_CFG["model"] if DS_CFG["api_key"] else "(未配置)",
            "version": decision_service.VERSION, "lastEvidenceCall": agent_tools.LAST_CALL}

class TaskSpec(BaseModel):
    model_config = {'allow_inf_nan': False, 'populate_by_name': True, 'extra': 'forbid'}
    regionId: str
    from_: list[float] = Field(alias='from', min_length=2, max_length=2)
    to: list[float] = Field(min_length=2, max_length=2)
    speedKmh: float = Field(ge=1, le=300)
    enduranceMinutes: float = Field(ge=1, le=600)
    departureMinute: float = Field(0, ge=0, le=1260)
    latestArrivalMinute: float = Field(180, ge=1, le=1440)
    workMinutes: float = Field(0, ge=0, le=120)
    bufferM: float = Field(500, ge=0, le=5000)

@app.post('/weather/layers')
def weather_layers(dashboard: dict):
    from weather.layers import from_dashboard
    try:
        return from_dashboard(dashboard)
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(400, 'Invalid dashboard snapshot') from exc

class EvaluateRequest(BaseModel):
    scenario: str = 'crossing'
    seed: int = Field(42, ge=0, le=1000000)
    origin: str | None = None
    uncertainty: bool = True
    task: TaskSpec

@app.get('/workspace/frame')
def workspace_frame(scenario: str = 'crossing', seed: int = 42, minute: float = 0,
                    regionId: str | None = None, origin: str | None = None, uncertainty: bool = True, bufferM: float = 500):
    import math
    if not math.isfinite(minute) or not 0 <= minute <= 1440 or not 0 <= seed <= 1000000:
        raise HTTPException(400, 'Invalid clock or seed')
    if regionId and regionId not in REGIONS:
        raise HTTPException(400, 'Unknown region')
    if not math.isfinite(bufferM) or not 0 <= bufferM <= 5000:
        raise HTTPException(400, 'Invalid safety buffer')
    try:
        return decision_service.frame(scenario, seed, minute, regionId, origin, uncertainty, bufferM)
    except ValueError as exc:
        raise HTTPException(400, 'Invalid scenario or origin') from exc

@app.post('/tasks/evaluate')
def tasks_evaluate(req: EvaluateRequest):
    try:
        return decision_service.assess({**req.model_dump(), 'task': req.task.model_dump(by_alias=True)})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

@app.get('/decisions')
def decisions():
    return decision_service.history()

@app.get('/decisions/{identity}')
def decision(identity: str):
    try:
        return decision_service.get_record(identity)
    except KeyError as exc:
        raise HTTPException(404, 'Decision not found') from exc

@app.get('/replays/{identity}')
def replay_decision(identity: str):
    try:
        return decision_service.replay(identity)
    except KeyError as exc:
        raise HTTPException(404, 'Decision not found') from exc

class EvidenceQuestion(BaseModel):
    decisionId: str = Field(min_length=64, max_length=64)
    question: str = Field(min_length=1, max_length=1200)

@app.post('/decisions/explain')
def explain_decision(req: EvidenceQuestion):
    try:
        return agent_tools.explain(req.decisionId, req.question, DS_CFG)
    except KeyError as exc:
        raise HTTPException(404, 'Decision not found') from exc

@app.get("/weather/current")
def weather_current(lat: float = 38.91, lon: float = 121.61, hours: int = 6):
    import real_weather

    hours = max(1, min(hours, 24))
    try:
        return real_weather.snapshot(lat, lon, hours)
    except real_weather.SourceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@app.get("/weather/source")
def weather_source_status():
    import real_weather

    return real_weather.status()

class Track2Request(BaseModel):
    run_id: str = ""
    deadline_epoch_ms: int = 0
    snapshot: dict = Field(..., description="实时观测（和风 v1 字段结构）")
    forecast: list = Field(default_factory=list, description="未来逐时预报列表")
    region: str = "演示作业区"
    task_type: str = "巡检"

@app.post("/track2")
def track2(req: Track2Request):
    return track2_agent.analyze(req.snapshot, req.forecast, req.region, req.task_type, DS_CFG,
                                req.run_id, req.deadline_epoch_ms)

class AskRequest(BaseModel):
    question: str
    context: str = ""

@app.post("/agent/ask")
def agent_ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question is empty")
    return track2_agent.ask(req.question.strip(), req.context, DS_CFG)

class Track1MLRequest(BaseModel):
    snapshot: dict = Field(..., description="实时观测（与 /weather/now 返回的 snapshot 同构）")
    hour: float | None = Field(None, ge=0, le=23.999)
    month: int | None = Field(None, ge=1, le=12)

@app.post("/track1/ml")
def track1_ml(req: Track1MLRequest):
    from ml import service as ml_service

    if not req.snapshot:
        raise HTTPException(status_code=400, detail="snapshot is empty")
    return ml_service.predict(req.snapshot, hour=req.hour, month=req.month)

@app.get("/track1/ml/status")
def track1_ml_status():
    from ml import service as ml_service

    return ml_service.status()

from traffic import service as traffic_service
from traffic import operations as traffic_operations
from traffic import weather_control
from traffic import cma_tiles

class TrafficAction(BaseModel):
    seed: int = Field(42, ge=0, le=99999)
    scenario: str = Field('live', pattern='^(clear|unknown|live)$')
    flightId: str = Field(min_length=1, max_length=120)
    minute: float = Field(ge=0, le=480, allow_inf_nan=False)
    action: str = Field(pattern='^(SUSPEND|RESUME)$')
    planRevision: str | None = Field(None, max_length=80)
    commandId: str | None = Field(None, min_length=8, max_length=80)

class TrafficQuestion(BaseModel):
    seed: int = Field(42, ge=0, le=99999)
    scenario: str = Field('live', pattern='^(clear|unknown|live)$')
    flightId: str | None = Field(None, max_length=120)
    minute: float = Field(ge=0, le=480, allow_inf_nan=False)
    question: str = Field(min_length=1, max_length=1200)

@app.post('/traffic/command')
def traffic_command(req: TrafficAction, request: Request):
    _require(request, 'dispose')
    try:
        return traffic_operations.command(req.seed, req.scenario, req.flightId, req.minute, req.action, req.planRevision, req.commandId)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

@app.post('/traffic/explain')
def traffic_explain(req: TrafficQuestion):
    try:
        return traffic_operations.explain(req.seed, req.scenario, req.flightId, req.minute, req.question, DS_CFG)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

@app.get('/traffic/operations')
def traffic_operation_history(sessionId: str = Query(pattern='^[a-f0-9]{24}$')):
    """班次状态操作（暂停/恢复）。这是时间轴回放的输入，不含其它三类事件。"""
    return traffic_operations.records(sessionId)

class JournalExportNote(BaseModel):
    sessionId: str = Field(pattern='^[a-f0-9]{24}$')
    format: str = Field('csv', max_length=16)
    rows: int = Field(ge=0, le=100000)

@app.get('/traffic/flights')
def traffic_flights(page: int = Query(1, ge=1, le=1000),
                    size: int = Query(100, ge=1, le=500),
                    status: str = Query('', max_length=32),
                    mode: str = Query('', max_length=16),
                    corridor: str = Query('', max_length=64),
                    minute: int | None = Query(None, ge=0, le=1440),
                    seed: int = Query(42, ge=0, le=99999),
                    scenario: str = Query('live', pattern='^(clear|unknown|live)$')):
    payload = traffic_service.session(seed, scenario)
    if payload.get('status') != 'READY':
        raise HTTPException(409, '计划尚未就绪')
    rows = payload.get('flights') or []
    if status:
        rows = [f for f in rows if (f.get('status') or '') == status]
    if mode:
        rows = [f for f in rows if (f.get('mode') or '') == mode]
    if corridor:
        rows = [f for f in rows
                if (f.get('routeId') or f.get('corridorId') or '') == corridor]
    if minute is not None:
        rows = [f for f in rows
                if f.get('departureMinute') is not None
                and f['departureMinute'] <= minute < (f.get('arrivalMinute') or 0)]
    total = len(rows)
    start = (page - 1) * size
    window = rows[start:start + size]
    return {
        'page': page, 'size': size, 'total': total,
        'pages': (total + size - 1) // size if size else 0,
        'items': [_slim_row(flight, with_points=False) for flight in window],
        'slim': True,
    }

@app.get('/traffic/flights/points')
def traffic_flights_points(ids: str = Query('', max_length=2000),
                           seed: int = Query(42, ge=0, le=99999),
                           scenario: str = Query('live', pattern='^(clear|unknown|live)$')):
    wanted = [part.strip() for part in (ids or '').split(',') if part.strip()]
    if not wanted:
        raise HTTPException(400, 'ids 不能为空')
    if len(wanted) > 50:
        raise HTTPException(400, '一次最多 50 条（收到 %d 条）。按需取，不要分批拉全量' % len(wanted))
    payload = traffic_service.session(seed, scenario)
    if payload.get('status') != 'READY':
        raise HTTPException(409, '计划尚未就绪')
    index = {f.get('id'): f for f in (payload.get('flights') or [])}
    found = {}
    for flight_id in wanted:
        flight = index.get(flight_id)
        if flight is not None:
            found[flight_id] = {'id': flight_id, 'points': flight.get('points') or []}
    return {'requested': len(wanted), 'found': len(found), 'items': found,
            'missing': [i for i in wanted if i not in found]}

@app.get('/traffic/flight/{flight_id}')
def traffic_flight(flight_id: str,
                   seed: int = Query(42, ge=0, le=99999),
                   scenario: str = Query('live', pattern='^(clear|unknown|live)$')):
    payload = traffic_service.session(seed, scenario)
    if payload.get('status') != 'READY':
        raise HTTPException(409, '计划尚未就绪')
    for flight in payload.get('flights') or []:
        if flight.get('id') == flight_id:
            return flight
    raise HTTPException(404, 'no such flight')

@app.get('/traffic/journal')
def traffic_journal(sessionId: str = Query(pattern='^[a-f0-9]{24}$')):
    """运行操作与决策日志：人工干预 + 系统决策 + 数据源变更 + 导出。"""
    return traffic_operations.journal(sessionId)

@app.post('/traffic/operations/note')
def traffic_journal_note(req: JournalExportNote, request: Request):
    _require(request, 'note')
    """前端把"已导出"这件事登记进来。只收导出，不接受任意事件类型。"""
    return traffic_operations.note_export(req.sessionId, req.format, req.rows)

class DisposalRequest(BaseModel):
    sessionId: str = Field(pattern='^[a-f0-9]{24}$')
    eventKey: str = Field(min_length=3, max_length=200)
    state: str = Field(pattern='^(ACKNOWLEDGED|IN_PROGRESS|HANDLED|REVIEWED)$')
    actor: str | None = Field(None, max_length=64)
    note: str | None = Field(None, max_length=200)

class DisposeRequest(BaseModel):
    seed: int = Field(42, ge=0, le=99999)
    scenario: str = Field('live', pattern='^(clear|unknown|live)$')
    eventKey: str = Field(min_length=3, max_length=200)
    action: str = Field(pattern='^(DELAY|DETOUR|SUSPEND|ACKNOWLEDGED|HANDLED|REVIEWED)$')
    flightId: str | None = Field(None, max_length=64)
    minute: float = Field(0, ge=0, le=100000)
    planRevision: int | None = None
    commandId: str | None = Field(None, max_length=64)
    actor: str | None = Field(None, max_length=64)
    note: str | None = Field(None, max_length=200)

@app.post('/traffic/operations/disposal')
def traffic_event_disposal(req: DisposalRequest, request: Request):
    actor = (req.actor or request.headers.get('X-ALC-Operator') or '').strip()
    if not actor:
        raise HTTPException(403, '处置需要操作者身份：请在设置里选择角色，'
                                 '或让请求带上 X-ALC-Operator 头')
    try:
        return traffic_operations.note_disposal(req.sessionId, req.eventKey, req.state,
                                                req.note, actor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.post('/traffic/operations/dispose')
def traffic_event_dispose(req: DisposeRequest, request: Request):
    _require(request, 'dispose')
    req.actor = (req.actor or request.headers.get('X-ALC-Operator') or '').strip() or None
    """一键处置（P0-3 ①）。

    **本系统不支持的动作返回 200 + `supported=False`，不是错误码。** 这是一条能力
    边界，不是一次故障：改时隙与改航在计划构建时就写定了，运行时不重算。把它做成
    4xx，前端就只能渲染成"失败了，请重试" —— 而重试永远不会成功，用户会一直点。
    """
    try:
        return traffic_operations.dispose(
            req.seed, req.scenario, req.eventKey, req.action, flight_id=req.flightId,
            minute=req.minute, plan_revision=req.planRevision, note=req.note,
            actor=req.actor, command_id=req.commandId)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.get('/traffic/network')
def traffic_network():
    return traffic_service.network()

@app.get('/traffic/v2/overview')
def traffic_v2_overview(seed: int = Query(42),
                        scenario: str = Query('live', pattern='^(clear|unknown|live)$'),
                        case: str = Query(''),
                        minute: float | None = Query(None, ge=0, le=1440)):
    from traffic import v2 as traffic_v2
    return traffic_v2.overview(seed=seed, scenario=scenario, case_id=case or None, minute=minute)

@app.get('/traffic/v2/corridors')
def traffic_v2_corridors(limit: int = Query(53, ge=1, le=300),
                         mode: str = Query('CAR', pattern='^(CAR|DELIVERY)$'),
                         case: str = Query(''),
                         minute: float | None = Query(None, ge=0, le=1440)):
    from traffic import v2 as traffic_v2
    return traffic_v2.corridors(limit=limit, mode=mode, case_id=case or None, minute=minute)

@app.get('/traffic/v2/corridor/{route_id}')
def traffic_v2_corridor(route_id: str, case: str = Query(''),
                        minute: float | None = Query(None, ge=0, le=1440)):
    from traffic import v2 as traffic_v2
    return traffic_v2.corridor(route_id, case_id=case or None, minute=minute)

@app.get('/traffic/v2/modelcard')
def traffic_v2_modelcard():
    from traffic import v2 as traffic_v2
    return traffic_v2.modelcard()

@app.get('/traffic/v2/explain')
def traffic_v2_explain(corridorId: str = Query(..., min_length=3, max_length=40)):
    from traffic import v2 as traffic_v2
    return traffic_v2.translator(corridorId, DS_CFG)

@app.get('/traffic/v2/counterfactual')
def traffic_v2_counterfactual(seed: int = Query(42, ge=0, le=99999),
                              scenario: str = Query('live', pattern='^(clear|unknown|live)$'),
                              policy: str = Query('balanced', pattern='^(conservative|balanced|efficiency)$'),
                              case: str = Query(''),
                              ablate: str = Query('', pattern='^(obs|prob|loss)?$')):
    from traffic import v2 as traffic_v2
    return traffic_v2.counterfactual(seed=seed, scenario=scenario, policy=policy,
                                     case_id=case or None, ablate=ablate)

@app.get('/traffic/v2/divergences')
def traffic_v2_divergences(limit: int = Query(50, ge=1, le=200)):
    from traffic import v2 as traffic_v2
    return traffic_v2.divergences(limit=limit)

@app.post('/traffic/v2/decision')
def traffic_v2_decision(body: dict, request: Request):
    identity = _require(request, 'dispose')
    from traffic import v2 as traffic_v2
    payload = dict(body or {})
    payload['role'] = identity.role
    payload.setdefault('operator', identity.raw or identity.role)
    return traffic_v2.record_decision(payload)

@app.get('/traffic/plan')
def traffic_plan(seed: int = Query(42, ge=0, le=99999),
                 scenario: str = Query('live', pattern='^(clear|unknown|live)$')):
    try:
        return traffic_service.plan_meta(seed, scenario)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

@app.get('/traffic/hubs')
def traffic_hubs(seed: int = Query(42, ge=0, le=99999),
                 scenario: str = Query('live', pattern='^(clear|unknown|live)$')):
    try:
        return traffic_service.hubs(seed, scenario)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

@app.get('/traffic/delivery')
def traffic_delivery(seed: int = Query(42, ge=0, le=99999),
                     scenario: str = Query('live', pattern='^(clear|unknown|live)$')):
    try:
        return traffic_service.delivery_plan(seed, scenario)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

SLIM_FLIGHT_FIELDS = (
    'id', 'name', 'mode', 'fromCity', 'toCity', 'fromPad', 'toPad',
    'routeId',
    'payload',
    'status', 'reason', 'separationAction', 'clearanceStatus',
    'requestedDepartureMinute', 'departureMinute', 'arrivalMinute',
    'delayMinutes', 'detourMinutes', 'maxAltitudeM', 'energyPercentRemainingAtHandover',
    'points',
)
SLIM_MAX_POINTS = 6
SESSION_FLIGHTS = 100
MAP_MAX_ROWS = 900
MAP_BUCKET_MINUTES = 30
MAP_CAR_PER_BUCKET = 20
MAP_DELIVERY_PER_BUCKET = 18
MAP_POINTS = 4

def _thin_points(points, max_points=SLIM_MAX_POINTS):
    """等距抽稀，**首末点必保**。少于上限的原样返回。"""
    if not points or len(points) <= max_points:
        return points
    step = (len(points) - 1) / (max_points - 1)
    picked = [points[round(i * step)] for i in range(max_points)]
    picked[-1] = points[-1]
    return picked

def _slim_row(flight, max_points=SLIM_MAX_POINTS, with_points=True):
    row = {key: flight[key] for key in SLIM_FLIGHT_FIELDS if key in flight}
    if 'points' in row:
        if with_points:
            row['points'] = _thin_points(row['points'], max_points)
        else:
            row.pop('points', None)
    row['slim'] = True
    return row

def _slim_session(payload):
    """按白名单裁剪 + 截断到首页条数。**不改原对象**（它是缓存里那一份）。"""
    if payload.get('status') != 'READY':
        return payload
    flights = payload.get('flights') or []

    car = [f for f in flights if (f.get('mode') or '') == 'CAR']
    delivery = [f for f in flights if (f.get('mode') or '') != 'CAR']
    delivery_events = [f for f in delivery if (f.get('status') or '') != 'SCHEDULED']
    delivery_plain = [f for f in delivery if (f.get('status') or '') == 'SCHEDULED']
    keep = car + delivery_events + delivery_plain[:SESSION_FLIGHTS]
    slim = [_slim_row(flight, with_points=False) for flight in keep]

    car_all = [f for f in flights if (f.get('mode') or '') == 'CAR']
    car_rows = [f for f in car_all if f.get('departureMinute') is not None]
    delivery_rows = [f for f in flights if (f.get('mode') or '') != 'CAR'
                     and f.get('departureMinute') is not None]

    def _bucket(flight):
        return int((flight.get('departureMinute') or 0) // MAP_BUCKET_MINUTES)

    _instants = [MAP_BUCKET_MINUTES * i for i in range(16)]

    def _covers(flight, minute):
        dep = flight.get('departureMinute')
        arr = flight.get('arrivalMinute')
        return dep is not None and arr is not None and dep <= minute < arr

    def _in_air(rows, minute):
        return sum(1 for f in rows if _covers(f, minute))

    def _spread(rows, per_bucket, min_in_air):
        chosen = []
        chosen_ids = set()

        def _take(flight):
            key = flight.get('id')
            if key in chosen_ids:
                return False
            chosen.append(flight)
            chosen_ids.add(key)
            return True

        for minute in _instants:
            while _in_air(chosen, minute) < min_in_air:
                candidates = [f for f in rows if f.get('id') not in chosen_ids and _covers(f, minute)]
                if not candidates:
                    break
                candidates.sort(key=lambda f: -sum(
                    1 for m in _instants if _covers(f, m) and _in_air(chosen, m) < min_in_air))
                _take(candidates[0])

        by_bucket = {}
        for flight in rows:
            by_bucket.setdefault(_bucket(flight), []).append(flight)
        for bucket in sorted(by_bucket):
            if any(_bucket(f) == bucket for f in chosen):
                continue
            group = sorted(by_bucket[bucket], key=lambda f: f.get('departureMinute') or 0)
            _take(group[len(group) // 2])

        quota = per_bucket * max(1, len(by_bucket))
        remaining = sorted((f for f in rows if f.get('id') not in chosen_ids),
                           key=lambda f: f.get('departureMinute') or 0)
        if len(chosen) < quota and remaining:
            need = quota - len(chosen)
            step = max(1, len(remaining) // max(1, need))
            for flight in remaining[::step][:need]:
                _take(flight)
        return chosen

    MAP_MIN_IN_AIR_CAR = 6
    MAP_MIN_IN_AIR_DELIVERY = 5
    car_pool = _spread(car_rows, MAP_CAR_PER_BUCKET, MAP_MIN_IN_AIR_CAR)
    delivery_pool = _spread(delivery_rows, MAP_DELIVERY_PER_BUCKET, MAP_MIN_IN_AIR_DELIVERY)
    map_pool = []
    for i in range(max(len(car_pool), len(delivery_pool))):
        if i < len(car_pool):
            map_pool.append(car_pool[i])
        if i < len(delivery_pool):
            map_pool.append(delivery_pool[i])

    map_rows = []
    for flight in map_pool[:MAP_MAX_ROWS]:
        row = {
            'id': flight.get('id'), 'mode': flight.get('mode'),
            'fromCity': flight.get('fromCity'), 'toCity': flight.get('toCity'),
            'status': flight.get('status'), 'departureMinute': flight.get('departureMinute'),
            'arrivalMinute': flight.get('arrivalMinute'),
            'points': _thin_points(flight.get('points') or [], MAP_POINTS),
            'mapOnly': True,
        }
        map_rows.append(row)

    by_status, by_mode = {}, {}
    for flight in flights:
        by_status[flight.get('status') or 'UNKNOWN'] = by_status.get(flight.get('status') or 'UNKNOWN', 0) + 1
        by_mode[flight.get('mode') or 'UNKNOWN'] = by_mode.get(flight.get('mode') or 'UNKNOWN', 0) + 1
    stats = {
        'total': len(flights),
        'returned': len(slim),
        'carTotal': len(car), 'carReturned': len(car),
        'deliveryTotal': len(delivery), 'deliveryReturned': len(slim) - len(car),
        'byStatus': by_status,
        'byMode': by_mode,
        'pageSize': SESSION_FLIGHTS,
        'mapReturned': len(map_rows),
        'mapCar': sum(1 for row in map_rows if (row.get('mode') or '') == 'CAR'),
        'mapDelivery': sum(1 for row in map_rows if (row.get('mode') or '') == 'DELIVERY'),
        'carClosedNoTime': len(car_all) - len(car_rows),
        'carSampledOut': max(0, len(car_rows) - sum(1 for row in map_rows
                                                   if (row.get('mode') or '') == 'CAR')),
        'mapSampling': ('每 %d 分钟采样一次：飞行汽车每桶 %d 条、配送无人机每桶 %d 条，'
                        '且每个采样时刻至少 %d / %d 架在空'
                        % (MAP_BUCKET_MINUTES, MAP_CAR_PER_BUCKET, MAP_DELIVERY_PER_BUCKET,
                           MAP_MIN_IN_AIR_CAR, MAP_MIN_IN_AIR_DELIVERY)),
        'mapInAir': {
            'instants': [MAP_BUCKET_MINUTES * i for i in range(16)],
            'car': [_in_air([r for r in map_rows if (r.get('mode') or '') == 'CAR'], m)
                    for m in [MAP_BUCKET_MINUTES * i for i in range(16)]],
            'delivery': [_in_air([r for r in map_rows if (r.get('mode') or '') != 'CAR'], m)
                         for m in [MAP_BUCKET_MINUTES * i for i in range(16)]],
            'minInAir': {'car': MAP_MIN_IN_AIR_CAR, 'delivery': MAP_MIN_IN_AIR_DELIVERY},
        },
        'truncated': len(flights) > len(slim),
    }

    return {**payload, 'flights': slim, 'mapFlights': map_rows,
            'flightStats': stats, 'fields': 'slim'}

_PREPARED: dict = {}
_PREPARED_LIMIT = 8
_PREPARED_BYTES_LIMIT = 48 * 1024 * 1024
_PREPARED_BYTES = 0

def _prepared_evict(size: int) -> None:
    global _PREPARED_BYTES
    while _PREPARED and (len(_PREPARED) >= _PREPARED_LIMIT
                         or _PREPARED_BYTES + size > _PREPARED_BYTES_LIMIT):
        oldest = next(iter(_PREPARED))
        old_raw, _old_etag = _PREPARED.pop(oldest)
        _PREPARED_BYTES -= len(old_raw)

def _prepared_key(result, fields):
    if result.get('status') != 'READY':
        return None
    session_id = result.get('sessionId')
    if not session_id:
        return None
    if fields != 'slim':
        return None
    return (session_id, fields)

def _prepare(result):
    """一次序列化，之后所有请求复用这份 bytes。"""
    raw = _json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    etag = '"%s"' % hashlib.sha1(raw).hexdigest()[:16]
    return raw, etag

_STARTED_AT = __import__('time').time()
_COUNTERS = {'sessionRequests': 0, 'preparedHits': 0, 'preparedBuilds': 0}

def _check_plan_store():
    """计划仓：数一数缓存目录里有几份计划文件。读不到就是 down。"""
    try:
        from traffic import service as _svc
        store = getattr(_svc, 'STORE', None)
        if store is None:
            return {'ok': False, 'detail': 'service.STORE 不存在（接口改了？）', 'plans': None}
        path = Path(store)
        if not path.exists():
            return {'ok': True, 'detail': '目录尚未创建（还没有工作区建过场）', 'plans': 0}
        plans = sorted(path.glob('*.json'))
        newest = max((f.stat().st_mtime for f in plans), default=0)
        shown = '/'.join(path.parts[-2:]) if len(path.parts) >= 2 else path.name
        return {'ok': True, 'detail': 'readable', 'path': shown, 'plans': len(plans),
                'newestAgeMinutes': round((__import__('time').time() - newest) / 60, 1) if newest else None}
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'detail': 'unreadable: %s' % exc}

def _check_weather():
    """气象通道：模式 + 雷达帧是否可用。雷达不可用是**降级**，不是 down。"""
    try:
        from traffic import weather_control as _wc
        mode = _wc.mode()
        frames = (_wc._state() or {}).get('frames') or {}
        return {'ok': True, 'judgesWeather': False,
                'detail': '本项只报各通道取帧计数，不判定气象是否健康（0 帧可能是无人使用）',
                'mode': mode,
                'measuredFrames': frames.get('measured', 0) if isinstance(frames, dict) else None,
                'virtualFrames': frames.get('virtual', 0) if isinstance(frames, dict) else None,
                'relayFrames': (_wc._state() or {}).get('relayFrames', 0)}
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'detail': 'unreadable: %s' % exc}

def _check_llm():
    try:
        import agent_tools
        last = dict(getattr(agent_tools, 'LAST_CALL', {}) or {})
        if not last:
            return {'ok': True, 'status': 'IDLE', 'detail': '本次进程尚无大模型调用'}
        status = str(last.get('status') or 'UNKNOWN')
        if status in ('NOT_CALLED', 'IDLE', 'RUNNING', ''):
            return {'ok': True, 'status': 'IDLE', 'source': last.get('source'),
                    'detail': '本次进程尚无大模型调用（未调用 ≠ 故障）'}
        ok = status == 'SUCCESS'
        return {'ok': ok, 'status': status,
                'source': last.get('source'), 'latencyMs': last.get('latencyMs'),
                'detail': '最近一次调用成功' if ok else '最近一次调用失败：%s' % status}
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'status': 'PROBE_ERROR', 'detail': '读调用记录失败：%s' % exc}

def _identity(request):
    return _operators.identify(request.headers)

def _require(request, action):
    identity = _identity(request)
    if not identity.allows(action):
        raise HTTPException(403, _operators.deny_message(identity, action))
    return identity

@app.get('/traffic/health')
def traffic_health():
    checks = {'planStore': _check_plan_store(), 'weather': _check_weather(), 'llm': _check_llm()}
    fatal = not checks['planStore']['ok']
    degraded = (not checks['weather']['ok']) or (not checks['llm']['ok'])
    status = 'down' if fatal else ('degraded' if degraded else 'ok')
    body = {
        'status': status,
        'version': _read_version(),
        'at': datetime.now(__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'uptimeSeconds': round(__import__('time').time() - _STARTED_AT, 1),
        'checks': checks,
    }
    return Response(content=_json.dumps(body, ensure_ascii=False, separators=(',', ':')),
                    media_type='application/json',
                    status_code=503 if fatal else 200,
                    headers={'Cache-Control': 'no-store'})

def _read_version():
    try:
        return (ROOT_DIR / 'VERSION').read_text(encoding='utf-8').strip()
    except Exception:  # noqa: BLE001
        return 'unknown'

@app.get('/traffic/metrics')
def traffic_metrics():
    """Prometheus 文本格式。只报**能算出来的**，不编造。"""
    lines = [
        '# HELP alc_uptime_seconds 进程运行时长',
        '# TYPE alc_uptime_seconds gauge',
        'alc_uptime_seconds %.1f' % (__import__('time').time() - _STARTED_AT),
        '# HELP alc_session_requests_total session 端点请求数',
        '# TYPE alc_session_requests_total counter',
        'alc_session_requests_total %d' % _COUNTERS['sessionRequests'],
        '# HELP alc_session_prepared_hits_total 预序列化命中数',
        '# TYPE alc_session_prepared_hits_total counter',
        'alc_session_prepared_hits_total %d' % _COUNTERS['preparedHits'],
        '# HELP alc_session_prepared_builds_total 预序列化生成数',
        '# TYPE alc_session_prepared_builds_total counter',
        'alc_session_prepared_builds_total %d' % _COUNTERS['preparedBuilds'],
        '# HELP alc_prepared_cache_entries 预序列化缓存条目数',
        '# TYPE alc_prepared_cache_entries gauge',
        'alc_prepared_cache_entries %d' % len(_PREPARED),
        'alc_prepared_cache_bytes %d' % _PREPARED_BYTES,
    ]
    try:
        from traffic import weather_control as _wc
        frames = (_wc._state() or {}).get('frames') or {}
        if isinstance(frames, dict):
            lines += ['# HELP alc_weather_frames_total 各通道取帧数',
                      '# TYPE alc_weather_frames_total counter',
                      'alc_weather_frames_total{channel="measured"} %d' % frames.get('measured', 0),
                      'alc_weather_frames_total{channel="virtual"} %d' % frames.get('virtual', 0),
                      'alc_weather_frames_total{channel="relay"} %d' % (_wc._state() or {}).get('relayFrames', 0)]
    except Exception:  # noqa: BLE001
        pass
    return Response(content='\n'.join(lines) + '\n', media_type='text/plain; version=0.0.4')

@app.middleware('http')
async def _request_id(request: Request, call_next):
    rid = request.headers.get('x-request-id') or __import__('uuid').uuid4().hex[:16]
    response = await call_next(request)
    response.headers['X-Request-Id'] = rid
    return response

@app.get('/traffic/session')
def traffic_session(request: Request,
                    seed: int = Query(42, ge=0, le=99999),
                    scenario: str = Query('live', pattern='^(clear|unknown|live)$'),
                    fields: str = Query('slim', pattern='^(slim|full)$'),
                    mode: str | None = Query(None, pattern='^(measured|virtual)$')):
    result = traffic_service.session(seed, scenario)
    if result.get('status') == 'BUILDING':
        started = result.get('startedAt')
        channel = result.get('weatherMode') or (mode or 'measured')
        budget = 110.0 if channel == 'virtual' else 60.0
        if isinstance(started, (int, float)):
            elapsed = max(0.0, time.time() - started)
            result['elapsedSeconds'] = round(elapsed, 1)
            result['etaSeconds'] = round(max(0.0, budget - elapsed), 0)
        result['etaBasis'] = 'ESTIMATE_BY_CHANNEL'
        result['buildChannel'] = channel
        result['stage'] = result.get('stage') or '准备气象快照与空域目录'
    if mode is not None and result.get('status') == 'READY':
        result['requestedWeatherMode'] = mode
        if (result.get('weatherMode') or '') != mode:
            result['weatherModeMismatch'] = True
    if fields == 'slim':
        result = _slim_session(result)

    _COUNTERS['sessionRequests'] += 1
    key = _prepared_key(result, fields)
    if key is not None:
        global _PREPARED_BYTES
        prepared = _PREPARED.get(key)
        if prepared is not None:
            _COUNTERS['preparedHits'] += 1
            _PREPARED.pop(key, None)
            _PREPARED[key] = prepared
        if prepared is None:
            _COUNTERS['preparedBuilds'] += 1
            prepared = _prepare(result)
            _prepared_evict(len(prepared[0]))
            _PREPARED[key] = prepared
            _PREPARED_BYTES += len(prepared[0])
        raw, etag = prepared
        headers = {'ETag': etag, 'Cache-Control': 'private, max-age=600',
                   'Vary': 'Accept-Encoding'}
        if request.headers.get('if-none-match') == etag:
            return Response(status_code=304, headers=headers)
        return Response(content=raw, media_type='application/json', headers=headers)
    try:
        traffic_operations.note_build(result)
    except Exception:  # noqa: BLE001
        log.exception('运行日志写入失败（不影响计划返回）')
    return result

@app.get('/traffic/weather')
def traffic_weather(seed: int = Query(42, ge=0, le=99999),
                    scenario: str = Query('live', pattern='^(clear|unknown|live)$'),
                    minute: float = Query(30, ge=0, le=480), cityId: str | None = None,
                    case: str | None = Query(None, max_length=64)):
    try:
        return traffic_service.weather_frame(seed, scenario, minute, cityId, case or None)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.get('/traffic/weather/cities')
def traffic_weather_cities(force: bool = False):
    from traffic.city_weather import city_weather
    places = [{
        'id': city['id'], 'name': city['name'],
        'lng': city['coordinate'][0], 'lat': city['coordinate'][1],
    } for city in traffic_service.cities()]
    return city_weather(places, force=force)

@app.get('/traffic/weather/observations')
def traffic_weather_observations(force: bool = False):
    """真实机场观测报文（Aviation Weather Center METAR）。"""
    from traffic.weather_sources import aviation_observations
    return aviation_observations(traffic_service.cities(), force=force)

@app.get('/traffic/weather/models')
def traffic_weather_models(force: bool = False):
    """同一供应商下两个独立模型的差值 —— 不确定性，不是第二份真相。"""
    from traffic.weather_sources import multi_model_spread
    return multi_model_spread(traffic_service.cities(), force=force)

class WeatherModeRequest(BaseModel):
    mode: str = Field(..., description="measured 或 virtual")
    seed: int | None = Field(default=None, ge=0, le=99999,
                             description="虚拟模式下的生成种子，省略则保持不变")
    actor: str | None = Field(default=None, max_length=64, description="操作者标识")
    reason: str | None = Field(default=None, max_length=200, description="切换原因")

@app.get('/traffic/weather/mode')
def weather_mode_status():
    """当前气象通道模式与控制器的完整状态。本接口不触发任何网络请求。"""
    return weather_control.status()

@app.post('/traffic/weather/mode')
def weather_mode_set(req: WeatherModeRequest, request: Request):
    action = ('weather-mode-to-virtual' if str(req.mode).lower() == 'virtual'
              else 'weather-mode-to-measured')
    _require(request, action)
    try:
        result = weather_control.set_mode(req.mode, seed=req.seed,
                                          actor=req.actor, reason=req.reason)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result.get('changed'):
        try:
            traffic_service.forget_other_channels(result.get('mode'))
        except Exception:  # noqa: BLE001
            log.exception('清理其它通道的计划槽失败（不影响切换结果）')
        try:
            traffic_operations.note_source(result.get('mode'), previous=result.get('previous'),
                                           actor=req.actor, reason=req.reason)
        except Exception:  # noqa: BLE001
            log.exception('数据源变更写入运行日志失败（不影响切换结果）')
    return result

class RadarRelayTile(BaseModel):
    x: int = Field(..., ge=0, le=1 << 20)
    y: int = Field(..., ge=0, le=1 << 20)
    data: str = Field(..., description="瓦片原始字节的 base64（不裁剪、不换算）",
                      max_length=cma_tiles.RELAY_TILE_BYTES * 2)

class RadarRelayRequest(BaseModel):
    slot: str = Field(..., max_length=40,
                      description="浏览器**实际取到**的那一档时次，北京时字面值，如 2026-10-15T15:18:00+08:00")
    zoom: int = Field(3, ge=0, le=8)
    tiles: list[RadarRelayTile] = Field(..., min_length=1, max_length=8)

@app.post('/traffic/radar/tiles')
def radar_tiles_relay(req: RadarRelayRequest):
    try:
        frame = cma_tiles.ingest_tiles([tile.model_dump() for tile in req.tiles],
                                       zoom=req.zoom, slot=req.slot)
    except cma_tiles.RelayPayloadRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    return weather_control.ingest_relay(frame)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8600)
