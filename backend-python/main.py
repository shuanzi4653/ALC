# -*- coding: utf-8 -*-
"""
天窗智巡 · Python 智能服务（FastAPI）
====================================
端口 8600，由 Spring Boot 主服务（8085）调用。

端点：
  GET  /health                          健康检查 + DeepSeek 配置状态
  GET  /sim/generate                    模拟数据生成（剧本/时长/坐标）
  POST /track2                          轨2 大模型研判（未配置 Key 自动降级）
  POST /agent/ask                       智能体问答（大屏交互窗口）
  POST /track1/ml                       轨1 机器学习增强（L2 预留）

配置来源：../config/application.yml 中 deepseek 段（与 Java 侧共用一份配置）
"""

import logging
import os
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

import simulator
import track2_agent

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


@app.get('/observations')
def regional_observations():
    return data_sources.observations()


# ---------------- 健康检查 ----------------

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


# ---------------- 模拟数据生成器 ----------------

@app.get("/sim/generate")
def sim_generate(scenario: str = "clear", hours: int = 6,
                 lat: float = 38.91, lon: float = 121.61, seed: int = None,
                 now: str = None):
    if scenario not in simulator.SCENARIOS:
        raise HTTPException(status_code=400,
                            detail="unknown scenario, must be one of: " + ",".join(simulator.SCENARIOS))
    hours = max(1, min(hours, 12))
    try:
        fixed_now = datetime.fromisoformat(now) if now else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="now must be ISO-8601") from exc
    return simulator.generate(scenario, hours, lat, lon, seed, fixed_now)


@app.get("/sim/scenarios")
def sim_scenarios():
    return [{"key": k, "name": v["name"], "desc": v["desc"]} for k, v in simulator.SCENARIOS.items()]


# ---------------- 轨2 研判 ----------------

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


# ---------------- 智能体问答 ----------------

class AskRequest(BaseModel):
    question: str
    context: str = ""


@app.post("/agent/ask")
def agent_ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question is empty")
    return track2_agent.ask(req.question.strip(), req.context, DS_CFG)


# ---------------- 轨1 ML 预留 ----------------

@app.post("/track1/ml")
def track1_ml():
    """L2 机器学习增强预留端点：XGBoost 离线训练 + ONNX 在线推理将在后续版本接入"""
    return {"status": "not_implemented",
            "note": "轨1 当前由 Java 侧规则基线承担；XGBoost 增强按计划书分级策略为可选增强项"}


from traffic import service as traffic_service
from traffic import operations as traffic_operations


class TrafficAction(BaseModel):
    seed: int = Field(42, ge=0, le=99999)
    scenario: str = Field('moving', pattern='^(clear|moving|unknown)$')
    flightId: str = Field(min_length=1, max_length=120)
    minute: float = Field(ge=0, le=480, allow_inf_nan=False)
    action: str = Field(pattern='^(SUSPEND|RESUME)$')


class TrafficQuestion(BaseModel):
    seed: int = Field(42, ge=0, le=99999)
    scenario: str = Field('moving', pattern='^(clear|moving|unknown)$')
    flightId: str | None = Field(None, max_length=120)
    minute: float = Field(ge=0, le=480, allow_inf_nan=False)
    question: str = Field(min_length=1, max_length=1200)


@app.post('/traffic/command')
def traffic_command(req: TrafficAction):
    try:
        return traffic_operations.command(req.seed, req.scenario, req.flightId, req.minute, req.action)
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
    return traffic_operations.records(sessionId)


@app.get('/traffic/network')
def traffic_network():
    return traffic_service.network()


@app.get('/traffic/session')
def traffic_session(seed: int = Query(42, ge=0, le=99999),
                    scenario: str = Query('moving', pattern='^(clear|moving|unknown)$')):
    return traffic_service.session(seed, scenario)


@app.get('/traffic/weather')
def traffic_weather(seed: int = Query(42, ge=0, le=99999),
                    scenario: str = Query('moving', pattern='^(clear|moving|unknown)$'),
                    minute: float = Query(30, ge=0, le=480), cityId: str | None = None):
    try:
        return traffic_service.weather_frame(seed, scenario, minute, cityId)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8600)
