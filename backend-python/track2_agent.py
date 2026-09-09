# -*- coding: utf-8 -*-
"""
天窗智巡 · 轨2 大模型研判智能体
====================================
基于 DeepSeek（OpenAI 兼容接口）的低空飞行气象研判智能体。

输出五元组结构化 JSON（与计划书 5.4 节一致）：
  risk_level   适飞 | 谨慎 | 危险 | 禁飞
  confidence   0.0-1.0
  key_factors  主要影响要素及原因（数组）
  advice       具体作业建议
  alert_text   可直接发布的预警文本

可靠性工程（对应计划书 5.4）：
  1. JSON Mode 强约束输出
  2. Schema 校验 + 失败自动重试（2 次）
  3. 全部失败时降级为本地规则研判（source=fallback），主流程零阻塞
"""

import json
import logging

import httpx

log = logging.getLogger("tianchuang.track2")

VALID_LEVELS = ["适飞", "谨慎", "危险", "禁飞"]

SYSTEM_PROMPT = """你是一名低空飞行气象保障专家，负责无人机作业的飞行窗口研判。
你必须严格遵守以下工作原则：
1. 安全优先：当数据存在不确定性或要素接近禁飞阈值时，倾向于给出更保守的风险等级。
2. 仅输出严格的 JSON 对象，不要输出任何其他文字、解释或 markdown 代码块标记。
3. JSON 必须包含且仅包含以下五个字段：
   risk_level: 字符串，取值只能是 适飞/谨慎/危险/禁飞 之一
   confidence: 数字 0.0-1.0，表示你对本次研判的置信度
   key_factors: 字符串数组，列出主要影响气象要素及原因（2-4 条，每条不超过 40 字）
   advice: 字符串，给无人机运营方的具体作业建议（不超过 80 字）
   alert_text: 字符串，可直接向多平台发布的预警/通报文本（不超过 120 字，风险低时输出适飞通报）"""

USER_TEMPLATE = """请根据以下气象数据，分析未来时段无人机飞行气象风险。

【区域】{region}
【任务类型】{task_type}

【实时观测】字段说明：tempC=温度℃，humidity=相对湿度0-1，windSpeed=平均风速m/s，
windGust=阵风m/s，precipMmh=降水强度mm/h，visibilityM=能见度米，thunderProb=雷暴概率0-1。
{snapshot_json}

【未来逐时预报（0-{hours}小时）】字段同上
{forecast_json}

【飞行窗口阈值规则】
- 平均风速：≤8 m/s 适飞，≥12 m/s 禁飞
- 阵风风速：≤12 m/s 适飞，≥18 m/s 禁飞
- 降水强度：0 mm/h 适飞，≥5 mm/h 禁飞
- 能见度：≥5 km 适飞，≤1 km 禁飞
- 雷暴概率：≤20% 适飞，≥60% 禁飞
- 温度：-10℃~40℃ 适飞，<-20℃ 或 >45℃ 禁飞

请输出研判 JSON。"""


def _chat(messages, cfg, timeout=45.0):
    """调用 DeepSeek chat completions（OpenAI 兼容接口）"""
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": "Bearer " + cfg["api_key"], "Content-Type": "application/json"}
    body = {
        "model": cfg.get("model", "deepseek-chat"),
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _parse_five(text):
    """解析并校验五元组输出"""
    obj = json.loads(text)
    level = str(obj.get("risk_level", "")).strip()
    if level not in VALID_LEVELS:
        raise ValueError("invalid risk_level: %s" % level)
    conf = float(obj.get("confidence", 0.5))
    factors = obj.get("key_factors") or []
    if not isinstance(factors, list) or not factors:
        factors = ["未给出明确要素"]
    return {
        "risk_level": level,
        "confidence": round(_clamp(conf, 0.0, 1.0), 2),
        "key_factors": [str(f)[:60] for f in factors[:4]],
        "advice": str(obj.get("advice", ""))[:120],
        "alert_text": str(obj.get("alert_text", ""))[:200],
    }


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _fallback(snapshot, hours, region, task_type):
    """本地规则降级研判：与 Java 侧 SFI 阈值逻辑一致的简化版。
    读取扁平字段（与 WeatherSnapshot 对齐），兼容旧嵌套结构。"""

    def _num(d, *keys, default=0.0):
        cur = d
        for k in keys:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(k, default)
        try:
            return float(cur)
        except (TypeError, ValueError):
            return default

    # 扁平结构优先（Java 侧传入），嵌套结构兜底（和风原始 JSON）
    wind = _num(snapshot, "windSpeed", default=-1)
    if wind < 0:
        wind = _num(snapshot, "wind", "speed", "value")
    gust = _num(snapshot, "windGust", default=-1)
    if gust < 0:
        gust = _num(snapshot, "windGust", "value")
    precip = _num(snapshot, "precipMmh", default=-1)
    if precip < 0:
        precip = _num(snapshot, "precipitation", "intensity", "value")
    vis_m = _num(snapshot, "visibilityM", default=-1)
    if vis_m < 0:
        vis_m = _num(snapshot, "visibility", "value", default=20000)
    thunder = _num(snapshot, "thunderProb")
    if thunder == 0:
        thunder = _num(snapshot, "thunderProbability")

    score = 0
    reasons = []
    if wind >= 12:
        score += 40; reasons.append("平均风速 %.1f m/s 达禁飞阈值" % wind)
    elif wind >= 8:
        score += 22; reasons.append("平均风速 %.1f m/s 超适飞阈值" % wind)
    if gust >= 18:
        score += 30; reasons.append("阵风 %.1f m/s 达禁飞阈值" % gust)
    elif gust >= 12:
        score += 16; reasons.append("阵风 %.1f m/s 超适飞阈值" % gust)
    if precip >= 5:
        score += 35; reasons.append("降水强度 %.1f mm/h 达禁飞阈值" % precip)
    elif precip >= 1:
        score += 15; reasons.append("出现降水 %.1f mm/h" % precip)
    if vis_m <= 1000:
        score += 30; reasons.append("能见度 %.1f km 过低" % (vis_m / 1000))
    elif vis_m <= 5000:
        score += 12; reasons.append("能见度 %.1f km 偏低" % (vis_m / 1000))
    if thunder >= 0.6:
        score += 35; reasons.append("雷暴概率 %.0f%% 过高" % (thunder * 100))
    elif thunder >= 0.2:
        score += 12; reasons.append("存在雷暴风险 %.0f%%" % (thunder * 100))

    if score >= 70:
        level, conf = "禁飞", 0.8
        advice = "立即停止作业，设备撤收或就近降落"
    elif score >= 40:
        level, conf = "危险", 0.72
        advice = "不建议飞行，已起飞的应立即返航"
    elif score >= 15:
        level, conf = "谨慎", 0.7
        advice = "可短暂作业，需持续关注气象变化"
    else:
        level, conf = "适飞", 0.75
        advice = "气象条件适宜飞行，可按计划作业"

    if not reasons:
        reasons = ["各要素均在适飞阈值内"]
    alert_text = "【低空飞行气象通报】%s %s任务：%s。主要影响：%s。%s" % (
        region, task_type, level, "；".join(reasons[:3]), advice)
    return {
        "risk_level": level,
        "confidence": conf,
        "key_factors": reasons[:4],
        "advice": advice,
        "alert_text": alert_text[:200],
    }


def analyze(snapshot, forecast, region, task_type, cfg):
    """
    轨2 研判主入口。
    cfg 为 DeepSeek 配置 dict：{api_key, base_url, model}；api_key 为空时直接走降级。
    返回: {五元组..., "source": "deepseek" | "fallback", "latency_ms": int}
    """
    import time
    t0 = time.time()

    if not cfg.get("api_key"):
        result = _fallback(snapshot, len(forecast), region, task_type)
        result["source"] = "fallback"
        result["latency_ms"] = int((time.time() - t0) * 1000)
        return result

    user_text = USER_TEMPLATE.format(
        region=region, task_type=task_type,
        hours=len(forecast),
        snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        forecast_json=json.dumps(forecast, ensure_ascii=False),
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text}]
    last_err = None
    for attempt in range(3):
        try:
            text = _chat(messages, cfg)
            result = _parse_five(text)
            result["source"] = "deepseek"
            result["latency_ms"] = int((time.time() - t0) * 1000)
            return result
        except Exception as e:  # noqa: BLE001 网络异常/格式漂移统一重试
            last_err = e
            log.warning("track2 attempt %d failed: %s", attempt + 1, e)

    # 三次尝试全部失败 → 规则降级，主流程零阻塞
    log.error("track2 degraded to fallback: %s", last_err)
    result = _fallback(snapshot, len(forecast), region, task_type)
    result["source"] = "fallback"
    result["latency_ms"] = int((time.time() - t0) * 1000)
    return result


ASK_SYSTEM = """你是低空飞行气象保障智能助手"天窗"，面向无人机运营方与飞手。
请依据提供的实时气象上下文，用简洁中文回答用户的飞行咨询（不超过 150 字），
先给结论（能飞/不能飞/谨慎），再说明原因与建议。气象数据之外的问题请礼貌说明职责范围。"""


def ask(question, context_text, cfg):
    """
    智能体问答（大屏右栏交互窗口）。
    context_text 为 Java 侧拼接的当前气象态势文本。
    返回: {"answer": str, "source": "deepseek"|"fallback"}
    """
    if not cfg.get("api_key"):
        return {"answer": "（模拟模式）当前系统未配置大模型服务。基于本地规则研判：" + context_text[:120],
                "source": "fallback"}
    messages = [{"role": "system", "content": ASK_SYSTEM},
                {"role": "user", "content": "当前气象态势：\n%s\n\n我的问题：%s" % (context_text, question)}]
    try:
        url = cfg["base_url"].rstrip("/") + "/chat/completions"
        headers = {"Authorization": "Bearer " + cfg["api_key"], "Content-Type": "application/json"}
        body = {"model": cfg.get("model", "deepseek-chat"), "messages": messages,
                "temperature": 0.4, "max_tokens": 400, "stream": False}
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            return {"answer": resp.json()["choices"][0]["message"]["content"].strip(),
                    "source": "deepseek"}
    except Exception as e:  # noqa: BLE001
        log.warning("agent ask degraded: %s", e)
        return {"answer": "（降级回答）大模型服务暂不可用。基于当前数据：" + context_text[:120],
                "source": "fallback"}
