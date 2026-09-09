# -*- coding: utf-8 -*-
"""
天窗智巡 · 模拟气象数据生成器
====================================
生成符合物理规律的时序气象数据，用于演示与测试模式。

输出为与 Java 侧 WeatherSnapshot / ForecastHour 完全对齐的扁平结构：
  snapshot: {time, source, lat, lon, conditionText, tempC, humidity,
             windSpeed, windGust, windDeg, precipMmh, visibilityM,
             pressureHpa, cloudCover, thunderProb}
  hourly:   [{time, tempC, windSpeed, windGust, precipMmh,
              visibilityM, thunderProb}, ...]

四类天气剧本（对应计划书测试样本设计）：
  clear  晴好天气：适飞
  wind   大风过程：阵风超限，谨慎/危险
  rain   强降水过程：降水+低能见度，危险
  storm  雷暴过程：降水尖峰+强阵风+低能见度，禁飞

物理模型：
  温度 = 基准值 + 日变化正弦（峰值 14 时）+ 剧本扰动 + 噪声
  风速/阵风/降水/能见度 = 剧本包络函数（随过程进度爬升/衰减）+ 噪声
"""

import math
import random
from datetime import datetime, timedelta, timezone

# 剧本参数：各要素的过程包络（起点值, 峰值, 起始进度, 结束进度）
SCENARIOS = {
    "clear": {
        "name": "晴好天气",
        "desc": "风速 2-5 m/s，无降水，能见度良好",
        "wind": (2.0, 5.0),
        "gust_add": 2.0,
        "precip": (0.0, 0.0),
        "vis": (15000, 28000),
        "cloud": (0.05, 0.3),
        "temp_shift": 0.0,
        "condition": "晴",
        "thunder_prob": 0.0,
    },
    "wind": {
        "name": "大风过程",
        "desc": "风速爬升至 10-14 m/s，阵风 15-20 m/s，能见度良好",
        "wind": (4.0, 13.0),
        "gust_add": 6.5,
        "precip": (0.0, 0.0),
        "vis": (10000, 20000),
        "cloud": (0.3, 0.7),
        "temp_shift": -2.0,
        "condition": "大风",
        "thunder_prob": 0.05,
    },
    "rain": {
        "name": "强降水过程",
        "desc": "降水强度 2-8 mm/h，能见度降至 2-5 km",
        "wind": (3.0, 8.0),
        "gust_add": 4.0,
        "precip": (0.0, 7.5),
        "vis": (1800, 6000),
        "cloud": (0.8, 1.0),
        "temp_shift": -4.0,
        "condition": "大雨",
        "thunder_prob": 0.15,
    },
    "storm": {
        "name": "雷暴过程",
        "desc": "降水尖峰 5-15 mm/h，阵风 16-22 m/s，能见度低于 1.5 km",
        "wind": (5.0, 15.0),
        "gust_add": 8.0,
        "precip": (0.0, 14.0),
        "vis": (600, 2500),
        "cloud": (0.95, 1.0),
        "temp_shift": -6.0,
        "condition": "雷阵雨",
        "thunder_prob": 0.85,
    },
}

# 一天中的温度基准与日变化幅度（夏季示例，可参数化）
TEMP_BASE = 24.0
TEMP_AMP = 6.0
HUMIDITY_BASE = 0.65
PRESSURE_BASE = 1008.0


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _envelope(progress, start, end):
    """梯形包络：[start, end] 进度区间内从 0 爬升到 1 再保持，区间外为 0 边缘值"""
    if progress <= start:
        return 0.0
    if progress >= end:
        return 1.0
    # 平滑爬升（sigmoid 感受）
    t = (progress - start) / max(end - start, 1e-6)
    return t * t * (3 - 2 * t)


def _base_wind(scenario, progress, hour):
    lo, hi = scenario["wind"]
    base = lo + (hi - lo) * _envelope(progress, 0.15, 0.7)
    # 叠加日变化微波动（午后风力略大）
    base += 0.8 * math.sin(max(0.0, (hour - 9)) / 12.0 * math.pi)
    return base


def _gen_point(scenario, progress, dt_local, lat, lon, rng):
    """生成单个时间点的气象数据（扁平结构，与 WeatherSnapshot 对齐）"""
    hour = dt_local.hour + dt_local.minute / 60.0

    # 温度：日变化正弦（峰值 14 时）+ 剧本降温 + 噪声
    temp = (TEMP_BASE + TEMP_AMP * math.sin((hour - 8) / 24.0 * 2 * math.pi)
            + scenario["temp_shift"] * _envelope(progress, 0.1, 0.6)
            + rng.uniform(-0.4, 0.4))

    # 风速与阵风
    wind = _base_wind(scenario, progress, hour) + rng.uniform(-0.5, 0.5)
    wind = _clamp(wind, 0.5, 25.0)
    gust = wind + scenario["gust_add"] * _envelope(progress, 0.2, 0.75) + rng.uniform(-0.5, 1.0)
    gust = _clamp(gust, wind + 0.5, 30.0)

    # 降水强度
    p_lo, p_hi = scenario["precip"]
    precip = (p_lo + (p_hi - p_lo) * _envelope(progress, 0.25, 0.8)) + (rng.uniform(0, 0.4) if p_hi > 0 else 0)
    precip = _clamp(precip, 0.0, 30.0)

    # 能见度（降水越大能见度越低）
    v_lo, v_hi = scenario["vis"]
    vis = (v_lo + (v_hi - v_lo) * (1.0 - _envelope(progress, 0.2, 0.7))) + rng.uniform(-300, 300)
    vis = _clamp(vis, 200, 30000)

    # 湿度：降水时升高
    humidity = _clamp(HUMIDITY_BASE + (0.25 if precip > 1 else 0) * _envelope(progress, 0.2, 0.6)
                      + rng.uniform(-0.05, 0.05), 0.2, 1.0)

    # 云量
    c_lo, c_hi = scenario["cloud"]
    cloud = _clamp(c_lo + (c_hi - c_lo) * _envelope(progress, 0.1, 0.5) + rng.uniform(-0.03, 0.03), 0.0, 1.0)

    # 气压：雷暴/降水过程气压略降
    pressure = PRESSURE_BASE - 6.0 * _envelope(progress, 0.2, 0.7) + rng.uniform(-0.5, 0.5)

    # 雷暴概率
    thunder = scenario["thunder_prob"] * _envelope(progress, 0.25, 0.8)

    # 风向（过程性缓慢旋转 + 抖动）
    deg = int((200 + progress * 40 + rng.uniform(-8, 8)) % 360)

    # 现象文本：降水明显或过程已展开时用剧本天气，否则显示多云
    active = precip > 0.5 or progress > 0.3
    return {
        "time": dt_local.strftime("%Y-%m-%dT%H:%M") + "+08:00",
        "source": "sim",
        "lat": lat,
        "lon": lon,
        "conditionText": scenario["condition"] if active else "多云",
        "tempC": round(temp, 1),
        "humidity": round(humidity, 2),
        "windSpeed": round(wind, 1),
        "windGust": round(gust, 1),
        "windDeg": deg,
        "precipMmh": round(precip, 2),
        "visibilityM": int(vis),
        "pressureHpa": round(pressure, 1),
        "cloudCover": round(cloud, 2),
        "thunderProb": round(thunder, 2),
    }


def generate(scenario_key: str, hours: int = 6, lat: float = 38.91, lon: float = 121.61,
             seed: int = None):
    """
    生成模拟数据。
    返回: {"scenario": {...}, "snapshot": {...当前观测...}, "hourly": [...未来逐时预报...]}
    hourly 覆盖未来 hours 小时，逐小时一个点（内部按 10 分钟细粒度演化取整点）。
    """
    if scenario_key not in SCENARIOS:
        raise ValueError("unknown scenario: %s" % scenario_key)
    scenario = SCENARIOS[scenario_key]
    rng = random.Random(seed)  # seed=None 时每次随机；同 seed 可复现

    # 当前观测从过程中段开始（切换剧本立即体现天气强度），预报沿过程继续演化
    START_PROGRESS = 0.45
    now = datetime.now(timezone(timedelta(hours=8)))
    total_steps = hours * 6  # 10 分钟粒度
    points = []
    for i in range(total_steps + 1):
        t = now + timedelta(minutes=10 * i)
        progress = min(1.0, START_PROGRESS + i / max(total_steps, 1))
        points.append(_gen_point(scenario, progress, t, lat, lon, rng))

    return {
        "scenario": {"key": scenario_key, "name": scenario["name"], "desc": scenario["desc"]},
        "snapshot": points[0],
        "hourly": [{k: p[k] for k in ("time", "tempC", "windSpeed", "windGust",
                                      "precipMmh", "visibilityM", "thunderProb")}
                   for p in [points[i * 6] for i in range(1, hours + 1)]],
    }
