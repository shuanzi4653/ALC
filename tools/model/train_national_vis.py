# -*- coding: utf-8 -*-
"""训练全国低能见度模型（ml-v3），替代"全国层没有模型"的现状。

为什么另起一版，而不是把 ml-v2 拿来用
--------------------------------------
ml-v2 的输入是 METAR：露点、气压、云底、3–6 小时历史，外加 `stationCode`
（只有沈阳/长春/哈尔滨三站）。全国 319 个城市既没有 METAR，也没有那三站的编码，
套上去只能拿默认值补齐 —— 那是拿默认值冒充观测，不能做。

这一版的数据源是 **open-meteo hourly**（公开、免密钥）：温度、露点、相对湿度、
风速、阵风、风向、气压、云量、能见度，逐小时、多城市批量可取。于是全国每个城市
都能凑齐同一套特征，模型也是**在这些城市上真训练出来的**。

口径（必须跟着结论一起说）
--------------------------
- 输入与标签**同源**（都用 open-meteo 的模式能见度），所以指标衡量的是
  "模式能见度的演变可不可预测"，**不等于**"实测低能见度的命中率"。
- 标签定义：`vis(t+1h) < 3000 m`。用时间切分（后 20% 时间做测试集），不随机打乱。
- 训练/测试按**时间**切，避免同一场雾同时出现在两边。

产物：`models/ml-v3-national-vis.json`（权重 + 标准化参数 + 指标 + 数据出处）。

    .venv/Scripts/python.exe tools/model/train_national_vis.py
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx

ROOT = Path(__file__).resolve().parents[2]
CITY_FILE = ROOT / 'data' / 'traffic' / 'cities-cn.json'
NETWORK_FILE = ROOT / 'data' / 'traffic' / 'nation-network.json'
OUT = ROOT / 'models' / 'ml-v3-national-vis.json'
METRICS_OUT = ROOT / 'data' / 'training' / 'national' / 'ml-v3-metrics.json'
CACHE = ROOT / 'data' / 'training' / 'national' / 'dataset.json'

API = 'https://api.open-meteo.com/v1/forecast'
HOURLY = ('temperature_2m,dew_point_2m,relative_humidity_2m,wind_speed_10m,'
          'wind_gusts_10m,wind_direction_10m,surface_pressure,cloud_cover,visibility')
PAST_DAYS = 30
BATCH = 80
TIMEOUT = 90.0
LABEL_M = 3000.0          # 标签门槛：1 小时后能见度 < 3 km
HORIZON = 1               # 前瞻小时数

FEATURES = (
    'visM', 'gustMs', 'windMs', 'wdirSin', 'wdirCos',
    'tempC', 'dewC', 'dewSpread', 'cloudBaseM', 'qnhHpa',
    'visMin3h', 'visMin6h', 'gustMax3h', 'windChange3h', 'qnhTendency3h',
    'visChange3h', 'tempTendency3h', 'spreadTendency3h',
    'hourSin', 'hourCos', 'month', 'lat', 'lon', 'elevM',
    'miss_vis', 'miss_gust', 'miss_cloud', 'miss_temp',
)


def cities() -> List[Dict[str, Any]]:
    allowed = {row['name'] for row in json.loads(NETWORK_FILE.read_text(encoding='utf-8'))['nodes']}
    rows = [row for row in json.loads(CITY_FILE.read_text(encoding='utf-8'))['cities']
            if row.get('lon') is not None and (not allowed or row['name'] in allowed)]
    return rows


def cloud_base_m(temp_c, dew_c) -> float | None:
    """用 LCL 近似云底：125 × (T − Td)，与训练侧的抬升凝结高度同族。

    open-meteo 不直接给云底高，ml-v2 用的是 METAR 的 cloudBaseM；
    这一版按同一物理量换算，缺失就记 miss_cloud。
    """
    if temp_c is None or dew_c is None:
        return None
    return max(0.0, 125.0 * (temp_c - dew_c))


def fetch_batch(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    params = {
        'latitude': ','.join(f"{row['lat']:.3f}" for row in rows),
        'longitude': ','.join(f"{row['lon']:.3f}" for row in rows),
        'hourly': HOURLY,
        'past_days': PAST_DAYS,
        'forecast_days': 0,
        'timezone': 'UTC',
    }
    response = httpx.get(API, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else [payload]


def build_rows(city: Dict[str, Any], hourly: Dict[str, Any],
               elevation: float | None) -> List[Dict[str, Any]]:
    times = hourly.get('time') or []
    series = {key: hourly.get(key) or [] for key in
              ('temperature_2m', 'dew_point_2m', 'wind_speed_10m', 'wind_gusts_10m',
               'wind_direction_10m', 'surface_pressure', 'cloud_cover', 'visibility')}
    out: List[Dict[str, Any]] = []
    for index in range(6, len(times) - HORIZON):
        def at(key: str, offset: int = 0):
            values = series[key]
            position = index + offset
            return values[position] if 0 <= position < len(values) else None

        vis = at('visibility')
        if vis is None:
            continue
        label = 1 if (at('visibility', HORIZON) or 99999) < LABEL_M else 0
        temp, dew = at('temperature_2m'), at('dew_point_2m')
        wdir = at('wind_direction_10m')
        gust = at('wind_gusts_10m')
        past_vis = [at('visibility', -k) for k in range(1, 7)]
        past_vis = [v for v in past_vis if v is not None]
        past_gust = [at('wind_gusts_10m', -k) for k in range(1, 4)]
        past_gust = [v for v in past_gust if v is not None]
        vis3 = at('visibility', -3)
        temp3, dew3 = at('temperature_2m', -3), at('dew_point_2m', -3)
        qnh = at('surface_pressure')
        qnh_past = at('surface_pressure', -3)
        hour = int(times[index][11:13])
        rad = hour * 2 * math.pi / 24.0
        out.append({
            'visM': vis, 'gustMs': gust, 'windMs': at('wind_speed_10m'),
            'wdirSin': None if wdir is None else math.sin(math.radians(wdir)),
            'wdirCos': None if wdir is None else math.cos(math.radians(wdir)),
            'tempC': temp, 'dewC': dew,
            'dewSpread': None if (temp is None or dew is None) else temp - dew,
            'cloudBaseM': cloud_base_m(temp, dew),
            'qnhHpa': qnh,
            'visMin3h': min(past_vis[:3]) if past_vis[:3] else None,
            'visMin6h': min(past_vis) if past_vis else None,
            'gustMax3h': max(past_gust) if past_gust else None,
            'windChange3h': None if (gust is None or not past_gust) else gust - past_gust[0],
            'qnhTendency3h': None if (qnh is None or qnh_past is None) else qnh - qnh_past,
            'visChange3h': None if (vis is None or vis3 is None) else vis - vis3,
            'tempTendency3h': None if (temp is None or temp3 is None) else temp - temp3,
            'spreadTendency3h': None if (temp is None or dew is None or temp3 is None or dew3 is None)
                                else (temp - dew) - (temp3 - dew3),
            'hourSin': math.sin(rad), 'hourCos': math.cos(rad),
            'month': int(times[index][5:7]),
            'lat': city['lat'], 'lon': city['lon'], 'elevM': elevation,
            'miss_vis': 0.0,
            'miss_gust': 1.0 if gust is None else 0.0,
            'miss_cloud': 0.0 if cloud_base_m(temp, dew) is not None else 1.0,
            'miss_temp': 1.0 if temp is None else 0.0,
            'label': label,
            'time': times[index],
            'city': city['name'],
        })
    return out


def vectorize(rows: List[Dict[str, Any]], means: List[float] | None = None,
              stds: List[float] | None = None) -> Tuple[List[List[float]], List[int], List[float], List[float]]:
    columns = []
    for name in FEATURES:
        values = [row.get(name) for row in rows]
        numeric = [v for v in values if isinstance(v, (int, float))]
        fallback = sum(numeric) / len(numeric) if numeric else 0.0
        filled = [float(v) if isinstance(v, (int, float)) else fallback for v in values]
        columns.append(filled)
    if means is None:
        means = [sum(col) / len(col) for col in columns]
        stds = []
        for col, mean in zip(columns, means):
            variance = sum((v - mean) ** 2 for v in col) / len(col)
            stds.append(math.sqrt(variance) or 1.0)
    matrix = [[(col[i] - means[j]) / stds[j] for j, col in enumerate(columns)]
              for i in range(len(rows))]
    labels = [int(row['label']) for row in rows]
    return matrix, labels, means, stds


def train_logistic(matrix: List[List[float]], labels: List[int],
                   epochs: int = 400, lr: float = 0.5, l2: float = 1e-3):
    """全批量梯度下降的 L2 逻辑回归。

    为什么不用 GBDT：本机只有 numpy，没有 lightgbm/sklearn；而这一版的目的是
    "把全国概率变成可复算的模型输出"，线性模型在标准化特征上已经够用，
    而且权重可以原样入库、逐项复核 —— 比一个黑箱更容易在答辩里讲清楚。
    """
    import numpy as np

    x = np.asarray(matrix, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    n, d = x.shape
    positives = float(y.sum()) or 1.0
    weights = np.where(y > 0, n / (2.0 * positives), n / (2.0 * (n - positives)))
    w = np.zeros(d)
    b = 0.0
    for epoch in range(epochs):
        z = x @ w + b
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))
        error = (p - y) * weights
        grad_w = x.T @ error / n + l2 * w
        grad_b = float(error.mean())
        w -= lr * grad_w
        b -= lr * grad_b
        if epoch % 80 == 0:
            print(f'  epoch {epoch}  b={b:.3f}', flush=True)
    return [float(value) for value in w], float(b)


def auc(scores: List[float], labels: List[int]) -> float:
    pairs = sorted(zip(scores, labels))
    positives = sum(labels)
    negatives = len(labels) - positives
    if not positives or not negatives:
        return 0.0
    rank_sum = 0.0
    index = 0
    while index < len(pairs):
        j = index
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[index][0]:
            j += 1
        average_rank = (index + j) / 2.0 + 1
        for k in range(index, j + 1):
            if pairs[k][1]:
                rank_sum += average_rank
        index = j + 1
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def evaluate(scores: List[float], labels: List[int], threshold: float = 0.5) -> Dict[str, float]:
    brier = sum((s - y) ** 2 for s, y in zip(scores, labels)) / len(labels)
    hits = sum(1 for s, y in zip(scores, labels) if s >= threshold and y)
    misses = sum(1 for s, y in zip(scores, labels) if s < threshold and y)
    false_alarms = sum(1 for s, y in zip(scores, labels) if s >= threshold and not y)
    precision = hits / (hits + false_alarms) if hits + false_alarms else 0.0
    recall = hits / (hits + misses) if hits + misses else 0.0
    ts = hits / (hits + misses + false_alarms) if hits + misses + false_alarms else 0.0
    return {'auc': round(auc(scores, labels), 4), 'brier': round(brier, 5),
            'ts': round(ts, 4), 'precision': round(precision, 4), 'recall': round(recall, 4),
            'baseRate': round(sum(labels) / len(labels), 5), 'samples': len(labels)}


def main() -> int:
    started = time.time()
    if CACHE.is_file():
        dataset = json.loads(CACHE.read_text(encoding='utf-8'))
        print(f'复用缓存数据集 {CACHE}（{len(dataset)} 条）', flush=True)
        return _train(dataset, started)
    rows_city = cities()
    print(f'{len(rows_city)} 个城市 · 过去 {PAST_DAYS} 天', flush=True)
    dataset: List[Dict[str, Any]] = []
    for start in range(0, len(rows_city), BATCH):
        chunk = rows_city[start:start + BATCH]
        try:
            payload = fetch_batch(chunk)
        except Exception as exc:  # noqa: BLE001
            print(f'  批 {start} 失败：{exc}', flush=True)
            continue
        for city, body in zip(chunk, payload):
            dataset.extend(build_rows(city, body.get('hourly') or {}, body.get('elevation')))
        print(f'  已取 {min(start + BATCH, len(rows_city))}/{len(rows_city)} 城，样本 {len(dataset)}', flush=True)
    if not dataset:
        print('没有样本，退出')
        return 1
    return _train(dataset, started)


def _train(dataset: List[Dict[str, Any]], started: float) -> int:
    dataset.sort(key=lambda row: row['time'])
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(dataset, ensure_ascii=False), encoding='utf-8')
    print(f'数据集已缓存 {CACHE}（{CACHE.stat().st_size/1024/1024:.1f} MB）', flush=True)
    cut = int(len(dataset) * 0.8)
    train_rows, test_rows = dataset[:cut], dataset[cut:]
    print(f'样本 {len(dataset)}：训练 {len(train_rows)} / 测试 {len(test_rows)}（按时间切）', flush=True)

    matrix, labels, means, stds = vectorize(train_rows)
    w, b = train_logistic(matrix, labels)
    train_scores = [1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, b + sum(w[j] * row[j] for j in range(len(w)))))))
                    for row in matrix]
    test_matrix, test_labels, _, _ = vectorize(test_rows, means, stds)
    test_scores = [1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, b + sum(w[j] * row[j] for j in range(len(w)))))))
                   for row in test_matrix]
    train_metrics = evaluate(train_scores, labels)
    test_metrics = evaluate(test_scores, test_labels)
    print('train', train_metrics, flush=True)
    print('test ', test_metrics, flush=True)

    payload = {
        'model': 'ml-v3-national-vis',
        'modelVersion': f'v3.{time.strftime("%Y%m%d")}',
        'target': f'能见度 {int(LABEL_M)} m 以下（前瞻 {HORIZON} 小时）',
        'kind': 'logistic',
        'features': list(FEATURES),
        'weights': [round(value, 6) for value in w],
        'intercept': round(b, 6),
        'means': [round(value, 6) for value in means],
        'stds': [round(value, 6) for value in stds],
        'metrics': {'train': train_metrics, 'test': test_metrics},
        'provenance': {
            'source': 'open-meteo hourly（公开、免密钥）',
            'cities': len({row['city'] for row in dataset}),
            'pastDays': PAST_DAYS,
            'samples': len(dataset),
            'split': '按时间切分：前 80% 训练、后 20% 测试',
            'caveat': '输入与标签同源（都用 open-meteo 模式能见度）：指标衡量的是'
                      '"模式能见度的演变可不可预测"，不等于实测低能见度命中率。',
        },
        'trainedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    METRICS_OUT.parent.mkdir(parents=True, exist_ok=True)
    METRICS_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'写入 {OUT}（{OUT.stat().st_size / 1024:.0f} KB），用时 {time.time() - started:.0f}s')
    return 0


if __name__ == '__main__':
    sys.exit(main())
