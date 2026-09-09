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
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
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
        return {"api_key": str(ds.get("api-key") or "").strip(),
                "base_url": str(ds.get("base-url") or "https://api.deepseek.com").strip(),
                "model": str(ds.get("model") or "deepseek-chat").strip()}
    except Exception as e:  # noqa: BLE001
        log.warning("load config failed, deepseek disabled: %s", e)
        return {"api_key": "", "base_url": "https://api.deepseek.com", "model": "deepseek-chat"}


DS_CFG = load_deepseek_cfg()

app = FastAPI(title="天窗智巡 Python 智能服务", version="0.1.0")


# ---------------- 健康检查 ----------------

@app.get("/health")
def health():
    return {"status": "ok",
            "service": "tianchuang-python",
            "deepseek_configured": bool(DS_CFG["api_key"]),
            "model": DS_CFG["model"] if DS_CFG["api_key"] else "(未配置)"}


# ---------------- 模拟数据生成器 ----------------

@app.get("/sim/generate")
def sim_generate(scenario: str = "clear", hours: int = 6,
                 lat: float = 38.91, lon: float = 121.61, seed: int = None):
    if scenario not in simulator.SCENARIOS:
        raise HTTPException(status_code=400,
                            detail="unknown scenario, must be one of: " + ",".join(simulator.SCENARIOS))
    hours = max(1, min(hours, 12))
    return simulator.generate(scenario, hours, lat, lon, seed)


@app.get("/sim/scenarios")
def sim_scenarios():
    return [{"key": k, "name": v["name"], "desc": v["desc"]} for k, v in simulator.SCENARIOS.items()]


# ---------------- 轨2 研判 ----------------

class Track2Request(BaseModel):
    snapshot: dict = Field(..., description="实时观测（和风 v1 字段结构）")
    forecast: list = Field(default_factory=list, description="未来逐时预报列表")
    region: str = "演示作业区"
    task_type: str = "巡检"


@app.post("/track2")
def track2(req: Track2Request):
    return track2_agent.analyze(req.snapshot, req.forecast, req.region, req.task_type, DS_CFG)


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8600)
