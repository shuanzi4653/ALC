#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从**真实观测序列**构造 1000 组 26 维特征，供端云对拍使用。

数据来源与"为什么是它"
======================
`data/training/national/dataset.json`：open-meteo hourly（公开、免密钥）抓下来的
319 个城市 × 30 天逐小时观测，字段与 `tools/model/train_national_vis.py` 的
`build_rows()` 一一对应。这是仓库里**唯一还在的逐小时原始观测序列**——
METAR 的 `data/training/metar/series.csv` 被 .gitignore 排除，本机没有，不能拿它编。

特征构造**不另写一套**：逐条照 `backend-python/ml/nowcast.py` 的 `vector_for()`，
包括
  - 六个派生量用"过去 6 个观测"而不是"过去 6 个整点"（生产侧 history 也是按观测条目给的）；
  - 缺失值填模型的 `defaults`，同时置 `miss_*` 标记；
  - `stationCode` 用三站真实经纬度做最近站映射，150 km 内取 0/1/2，否则 -1
    （`nowcast.STATION_CODE.get(station, -1.0)` 对非三站城市就是这个结果）。
脚本会把它算出来的派生量与 dataset.json 里已有的同名列做一次比对，把差异打在屏幕上——
差异只允许出现在 `qnhTendency3h`（那一列训练脚本用的是 3 小时变压，生产侧用 1 小时变压），
这是"训练侧口径 ≠ 运行时口径"的真实差异，报告里要写清楚。

分层抽样
========
直接随机抽 1000 条会得到一个"几乎全是好天气"的样本：p 全贴在 0 附近，
对拍看起来完美（相对误差小），但根本没压到模型的判别边界。
所以按当前能见度分层（<1000 / 1k–3k / 3k–6k / 6k–10k / ≥10k），按配额抽，
配额用固定随机种子，任何人重跑都得到同一个 cases.csv。

产出（都写在本目录）：
  - `cases.csv`      1000 行 × 26 列，表头是特征名；每个数都是 float32 精确可表示的十进制串
  - `cases_meta.json` 抽样口径、来源指纹、p 分位数、超阈值组数

    python tools/edge-export/gen_cases.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import struct
import sys
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, Iterator, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DATASET = ROOT / 'data' / 'training' / 'national' / 'dataset.json'
METAR_META = ROOT / 'data' / 'training' / 'metar' / 'dataset.json'
MODEL = ROOT / 'models' / 'ml-v2-vis3k.json'
OUT_CASES = HERE / 'cases.csv'
OUT_META = HERE / 'cases_meta.json'

TOTAL_CASES = 1000
SEED = 20261113
HISTORY_LEN = 6

# 三站编码与 training/model 侧一致（nowcast.STATION_CODE）
STATION_CODE = {'ZYTX': 0.0, 'ZYCC': 1.0, 'ZYHB': 2.0}
STATION_MATCH_M = 150000.0

# 分层配额：当前能见度分档 -> 期望条数。低能见度档给足，才能压到判别边界。
STRATA = (
    ('vis<1000', 0.0, 1000.0, 120),
    ('1000-2999', 1000.0, 3000.0, 180),
    ('3000-5999', 3000.0, 6000.0, 200),
    ('6000-9999', 6000.0, 10000.0, 200),
    ('vis>=10000', 10000.0, 1e12, 300),
)
RESERVOIR_FACTOR = 4  # 每档预留 4 倍配额，配额不足时在档内随机补齐


# --------------------------------------------------------------------------- 工具

def f32(value: float) -> float:
    """量化成 float32 再以 float64 返回。"""
    return struct.unpack('<f', struct.pack('<f', float(value)))[0]


def f32_text(value: float) -> str:
    """float32 的最短 round-trip 十进制串（保证 C 侧 strtof 还原成同一个 float32）。"""
    quantized = f32(value)
    for digits in range(6, 10):
        text = '%.*g' % (digits, quantized)
        if f32(float(text)) == quantized:
            return text
    return '%.9g' % quantized


def iter_json_array(path: Path, chunk: int = 1 << 20) -> Iterator[Any]:
    """流式解析一个大 JSON 数组。

    为什么不 `json.load`：dataset.json 有 150 MB / 22 万条，整读要吃掉 1 GB 以上内存，
    在 8 GB 的办公本上会和别的程序抢内存。这里用 `JSONDecoder.raw_decode` 一条一条解，
    缓冲区随解随裁，峰值内存只有几 MB。
    """
    decoder = json.JSONDecoder()
    with open(path, 'r', encoding='utf-8') as handle:
        buffer = handle.read(chunk)
        start = buffer.index('[') + 1
        while True:
            while start < len(buffer) and buffer[start] in ' \t\r\n,':
                start += 1
            if start >= len(buffer):
                more = handle.read(chunk)
                if not more:
                    return
                buffer = buffer[start:] + more
                start = 0
                continue
            if buffer[start] == ']':
                return
            while True:
                try:
                    item, end = decoder.raw_decode(buffer, start)
                    break
                except json.JSONDecodeError:
                    more = handle.read(chunk)
                    if not more:
                        raise
                    buffer = buffer[start:] + more
                    start = 0
            yield item
            start = end
            if start > chunk:  # 裁掉已消费的头部，避免缓冲区无限增长
                buffer = buffer[start:]
                start = 0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def station_table() -> Dict[str, Tuple[float, float]]:
    """三站经纬度取自 METAR 数据集清单（真实坐标，不在这里另抄一份）。"""
    try:
        meta = json.loads(METAR_META.read_text(encoding='utf-8'))
        table = {code: (float(row['lat']), float(row['lon']))
                 for code, row in (meta.get('stations') or {}).items() if code in STATION_CODE}
        if len(table) == 3:
            return table
    except (OSError, ValueError, KeyError):
        pass
    return {'ZYTX': (41.6398, 123.4833), 'ZYCC': (43.9962, 125.6853), 'ZYHB': (45.6234, 126.25)}


def nearest_station(lat: float, lon: float, table: Dict[str, Tuple[float, float]]) -> Tuple[float, str, float]:
    best_code, best_distance = '', float('inf')
    for code, (station_lat, station_lon) in table.items():
        distance = haversine_m(lat, lon, station_lat, station_lon)
        if distance < best_distance:
            best_code, best_distance = code, distance
    if best_distance <= STATION_MATCH_M:
        return STATION_CODE[best_code], best_code, best_distance
    return -1.0, best_code, best_distance


# --------------------------------------------------------------------------- 特征

def build_vector(current: Dict[str, Any], past: List[Dict[str, Any]],
                 defaults: Dict[str, float], feature_names: List[str],
                 station_code: float) -> Tuple[List[float], List[str]]:
    """与 `nowcast.vector_for()` 逐行对应地构造 26 维向量。

    `past` 按时间**由近到远**排列（past[0] 是上一个观测），与 nowcast 里
    `list(reversed(history))` 的结果同序。返回 (向量, 被 defaults 填过的特征名)。
    """
    pv = [p.get('visM') for p in past if p.get('visM') is not None]
    pg = [p.get('gustMs') for p in past if p.get('gustMs') is not None]
    pq = [p.get('qnhHpa') for p in past if p.get('qnhHpa') is not None]

    vis = current.get('visM')
    gust = current.get('gustMs')
    temp = current.get('tempC')
    dew = current.get('dewC')
    wdir_sin = current.get('wdirSin')
    wdir_cos = current.get('wdirCos')
    qnh = current.get('qnhHpa')
    cloud = current.get('cloudBaseM')

    def at3h(key: str):
        return past[2].get(key) if len(past) >= 3 else None

    vis3, temp3, dew3 = at3h('visM'), at3h('tempC'), at3h('dewC')

    hour_rad = current['hour'] * 2 * math.pi / 24.0

    canon: Dict[str, Optional[float]] = {
        'visM': vis,
        'gustMs': gust,
        'windMs': current.get('windMs'),
        'wdirSin': wdir_sin,
        'wdirCos': wdir_cos,
        'tempC': temp,
        'dewC': dew,
        'dewSpread': None if (temp is None or dew is None) else temp - dew,
        'cloudBaseM': cloud,
        'qnhHpa': qnh,
        'visMin3h': min(pv[:3]) if pv[:3] else None,
        'visMin6h': min(pv) if pv else None,
        'gustMax3h': max(pg[:3]) if pg[:3] else None,
        'windChange3h': None if (gust is None or not pg) else gust - pg[0],
        'qnhTendency3h': None if (qnh is None or not pq) else qnh - pq[0],
        'visChange3h': None if (vis is None or vis3 is None) else vis - vis3,
        'tempTendency3h': None if (temp is None or temp3 is None) else temp - temp3,
        'spreadTendency3h': None if (temp is None or dew is None or temp3 is None or dew3 is None)
                            else (temp - dew) - (temp3 - dew3),
        'stationCode': station_code,
        'hourSin': math.sin(hour_rad),
        'hourCos': math.cos(hour_rad),
        'month': float(current['month']),
        'miss_vis': 1.0 if vis is None else 0.0,
        'miss_gust': 1.0 if gust is None else 0.0,
        'miss_cloud': 1.0 if cloud is None else 0.0,
        'miss_temp': 1.0 if temp is None else 0.0,
    }

    vector: List[float] = []
    filled: List[str] = []
    for name in feature_names:
        value = canon.get(name)
        if value is None:
            vector.append(float(defaults.get(name, 0.0)))
            if not name.startswith('miss_'):
                filled.append(name)
        else:
            vector.append(float(value))
    return vector, filled


# --------------------------------------------------------------------------- 主流程

def main() -> int:
    parser = argparse.ArgumentParser(description='构造对拍用例（真实观测序列 -> 26 维特征）')
    parser.add_argument('--dataset', default=str(DATASET))
    parser.add_argument('--out', default=str(OUT_CASES))
    parser.add_argument('--meta', default=str(OUT_META))
    parser.add_argument('--total', type=int, default=TOTAL_CASES)
    parser.add_argument('--seed', type=int, default=SEED)
    parser.add_argument('--stations-only', action='store_true',
                        help='只保留三站（ZYTX/ZYCC/ZYHB）200 km 内的用例：模型训练口径就是这个范围')
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.is_file():
        print('[FAIL] 找不到观测序列 %s' % dataset_path)
        print('       这份文件由 tools/model/train_national_vis.py 生成（open-meteo 缓存），'
              '仓库里应已入库；若缺失，先按该脚本重新抓取。')
        return 2

    payload = json.loads(MODEL.read_text(encoding='utf-8'))
    feature_names: List[str] = list(payload['featureNames'])
    defaults: Dict[str, float] = {k: float(v) for k, v in (payload.get('defaults') or {}).items()}
    model_version = str(payload['modelVersion'])

    sys.path.insert(0, str(ROOT / 'backend-python'))
    from ml.forest import Forest  # noqa: WPS433 - 只在生成阶段需要

    forest = Forest(payload)

    table = station_table()
    rng = random.Random(args.seed)
    quotas = [row[3] for row in STRATA]
    scale = args.total / float(sum(quotas))
    quotas = [max(1, int(round(q * scale))) for q in quotas]
    reservoirs: List[List[Tuple[List[float], Dict[str, Any]]]] = [
        [] for _ in STRATA]
    seen = [0 for _ in STRATA]
    caps = [q * RESERVOIR_FACTOR for q in quotas]

    history: Dict[str, Deque[Dict[str, Any]]] = {}
    total_rows = 0
    usable_rows = 0
    skipped_short_history = 0
    filled_counter: Dict[str, int] = {}
    station_counter: Dict[str, int] = {}
    precomputed_diff: Dict[str, float] = {}
    precomputed_checked = 0

    def strata_of(vis: float) -> Optional[int]:
        for index, (_, low, high, _) in enumerate(STRATA):
            if low <= vis < high:
                return index
        return None

    for row in iter_json_array(dataset_path):
        total_rows += 1
        city = row.get('city') or ''
        time_text = row.get('time') or ''
        if len(time_text) < 16:
            continue
        try:
            hour = int(time_text[11:13])
            month = int(time_text[5:7])
        except ValueError:
            continue

        observation = {
            'visM': row.get('visM'),
            'gustMs': row.get('gustMs'),
            'windMs': row.get('windMs'),
            'wdirSin': row.get('wdirSin'),
            'wdirCos': row.get('wdirCos'),
            'tempC': row.get('tempC'),
            'dewC': row.get('dewC'),
            'cloudBaseM': row.get('cloudBaseM'),
            'qnhHpa': row.get('qnhHpa'),
            'hour': hour,
            'month': month,
        }

        city_history = history.setdefault(city, deque(maxlen=HISTORY_LEN))
        past = list(reversed(city_history))  # 由近到远
        if len(past) >= HISTORY_LEN and row.get('visM') is not None:
            usable_rows += 1
            station_code, station_name, _ = nearest_station(
                float(row.get('lat') or 0.0), float(row.get('lon') or 0.0), table)
            if args.stations_only and station_code < 0:
                city_history.append(observation)
                continue
            vector, filled = build_vector(observation, past, defaults, feature_names, station_code)
            for name in filled:
                filled_counter[name] = filled_counter.get(name, 0) + 1
            station_counter[station_name if station_code >= 0 else 'OTHER'] = \
                station_counter.get(station_name if station_code >= 0 else 'OTHER', 0) + 1

            # 派生量比对：只比现在还能对得上的那几列，把差异留在屏幕上（不掩盖）
            if precomputed_checked < 500:
                precomputed_checked += 1
                index_of = {name: i for i, name in enumerate(feature_names)}
                for name in ('visMin3h', 'visMin6h', 'gustMax3h', 'visChange3h',
                             'tempTendency3h', 'spreadTendency3h', 'qnhTendency3h'):
                    stored = row.get(name)
                    if stored is None:
                        continue
                    diff = abs(float(stored) - vector[index_of[name]])
                    if diff > precomputed_diff.get(name, 0.0):
                        precomputed_diff[name] = diff

            bucket = strata_of(float(row['visM']))
            if bucket is not None:
                seen[bucket] += 1
                record = (vector, {
                    'city': city, 'time': time_text, 'visM': float(row['visM']),
                    'stationCode': station_code, 'filled': filled,
                })
                pool = reservoirs[bucket]
                if len(pool) < caps[bucket]:
                    pool.append(record)
                else:  # 蓄水池抽样：保证档内均匀，且与文件顺序无关
                    pick = rng.randrange(seen[bucket])
                    if pick < caps[bucket]:
                        pool[pick] = record
        city_history.append(observation)

    # ---- 配额不足的档把余量转给"还有富余"的档，保证总数正好 1000
    cases: List[Tuple[List[float], Dict[str, Any]]] = []
    remaining = args.total
    available = [len(pool) for pool in reservoirs]
    for index, quota in enumerate(quotas):
        take = min(quota, available[index], remaining)
        cases.extend(rng.sample(reservoirs[index], take))
        available[index] -= take
        remaining -= take
    while remaining > 0:
        candidates = [i for i in range(len(reservoirs)) if available[i] > 0]
        if not candidates:
            break
        for index in candidates:
            if remaining <= 0:
                break
            cases.append(reservoirs[index][len(reservoirs[index]) - available[index]])
            available[index] -= 1
            remaining -= 1

    if len(cases) < args.total:
        print('[FAIL] 只凑到 %d 组，少于要求的 %d 组' % (len(cases), args.total))
        return 3

    rng.shuffle(cases)  # 打乱档序，避免连续同类样本掩盖"某一档特别慢"这类现象

    # ---- 量化到 float32（这一步不是"顺手"，是对拍能不能成立的前提）
    # 端侧只有 float32。用例文件里写的是 float32 的最短 round-trip 十进制串，
    # 所以 `strtof("9.4")` 与 `float32(9.4)` 是同一个数，而 Python 的 `float("9.4")` 是
    # float64 的 9.4 —— 它与 float32 的 9.3999996185 差 3.8e-7，足以让某些叶子翻边
    # （第一轮对拍 40 组超差就是这么来的，且错在 Python 侧读文件的方式，不在 C）。
    # 所以生成时就量化，cases.csv 里存的就是两侧逐位相同的输入。
    cases = [([f32(value) for value in vector], meta) for vector, meta in cases]

    # ---- 逐条用参考实现验证 + 记录 p
    probabilities: List[float] = []
    for vector, _ in cases:
        if len(vector) != len(feature_names):
            print('[FAIL] 向量维度 %d != %d' % (len(vector), len(feature_names)))
            return 4
        for name, value in zip(feature_names, vector):
            if not math.isfinite(value):
                print('[FAIL] 特征 %s 出现非有限值 %r' % (name, value))
                return 5
        probabilities.append(float(forest.predict(vector)['probabilitiesExact']['POS']))

    # ---- 写 cases.csv：26 列，float32 精确可表示的十进制串
    lines = [','.join(feature_names)]
    for vector, _ in cases:
        lines.append(','.join(f32_text(v) for v in vector))
    Path(args.out).write_text('\n'.join(lines) + '\n', encoding='utf-8')

    sampled_stations: Dict[str, int] = {}
    for _, meta in cases:
        code = int(meta['stationCode'])
        label = {-1: 'OTHER', 0: 'ZYTX', 1: 'ZYCC', 2: 'ZYHB'}.get(code, 'OTHER')
        sampled_stations[label] = sampled_stations.get(label, 0) + 1

    ordered = sorted(probabilities)

    def quantile(q: float) -> float:
        if not ordered:
            return 0.0
        position = (len(ordered) - 1) * q
        low = int(math.floor(position))
        high = min(low + 1, len(ordered) - 1)
        weight = position - low
        return ordered[low] * (1 - weight) + ordered[high] * weight

    tiers = {'p>=0.2(WATCH)': 0, 'p>=0.3(operatingThreshold)': 0, 'p>=0.5(CAUTION)': 0, 'p>=0.8(BAN)': 0}
    for p in probabilities:
        if p >= 0.2:
            tiers['p>=0.2(WATCH)'] += 1
        if p >= 0.3:
            tiers['p>=0.3(operatingThreshold)'] += 1
        if p >= 0.5:
            tiers['p>=0.5(CAUTION)'] += 1
        if p >= 0.8:
            tiers['p>=0.8(BAN)'] += 1

    stats = {
        'model': model_version,
        'modelFeatures': feature_names,
        'seed': args.seed,
        'cases': len(cases),
        'source': {
            'file': dataset_path.name,
            'sha256': hashlib.sha256(dataset_path.read_bytes()).hexdigest()[:16],
            'rowsScanned': total_rows,
            'rowsUsable': usable_rows,
            'strata': [{'name': row[0], 'quota': q, 'candidates': s, 'taken': sum(
                1 for _, meta in cases if row[1] <= meta['visM'] < row[2])}
                for row, q, s in zip(STRATA, quotas, seen)],
        },
        'precomputedDiff': precomputed_diff,
        'missingFilled': filled_counter,
        # 扫描全量 vs 抽样后的站点构成分开记：混在一起会被误读成"用例里有 21 万条 OTHER"
        'stationScanned': station_counter,
        'stationSampled': sampled_stations,
        'probability': {
            'min': round(min(probabilities), 6),
            'p01': round(quantile(0.01), 6),
            'p10': round(quantile(0.10), 6),
            'p25': round(quantile(0.25), 6),
            'p50': round(quantile(0.50), 6),
            'p75': round(quantile(0.75), 6),
            'p90': round(quantile(0.90), 6),
            'p95': round(quantile(0.95), 6),
            'p99': round(quantile(0.99), 6),
            'max': round(max(probabilities), 6),
            'mean': round(sum(probabilities) / len(probabilities), 6),
            'tiers': tiers,
        },
    }
    Path(args.meta).write_text(json.dumps(stats, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    print('观测序列   : %s（指纹 %s）' % (dataset_path.name, stats['source']['sha256']))
    print('扫描 / 可用: %d / %d 行（历史不足 6 个观测的已跳过）' % (total_rows, usable_rows))
    print('用例       : %d 组 -> %s' % (len(cases), Path(args.out).name))
    print('站点覆盖   : 扫描 %s' % ', '.join('%s=%d' % (k, v) for k, v in sorted(station_counter.items())))
    print('            抽样 %s' % ', '.join('%s=%d' % (k, v) for k, v in sorted(sampled_stations.items())))
    if filled_counter:
        print('defaults 填充: %s' % ', '.join('%s=%d' % (k, v) for k, v in sorted(filled_counter.items())))
    else:
        print('defaults 填充: 0（本批用例全部有真实观测，缺省路径由导出自检里那条全 defaults 向量覆盖）')
    print('')
    print('与 dataset.json 已有派生列的最大差异（口径差异，不是 bug）：')
    for name, diff in sorted(precomputed_diff.items()):
        print('  %-18s %.6f' % (name, diff))
    print('')
    print('Python 参考实现 p(POS) 分布（n=%d）：' % len(probabilities))
    for key in ('min', 'p01', 'p10', 'p25', 'p50', 'p75', 'p90', 'p95', 'p99', 'max', 'mean'):
        print('  %-5s %.6f' % (key, stats['probability'][key]))
    for key, value in tiers.items():
        print('  %-26s %d 组' % (key, value))

    # ---- 分布守卫：p 全贴在 0 附近说明特征构造有问题，必须当场失败而不是事后解释
    spread = max(probabilities) - min(probabilities)
    above = sum(1 for p in probabilities if p >= 0.3)
    if spread < 0.05 or above < 20:
        print('')
        print('[FAIL] p 分布过窄（极差 %.6f，p>=0.3 只有 %d 组），特征构造多半有问题，'
              '不要拿去对拍。' % (spread, above))
        return 6
    print('')
    print('[OK] 分布检查通过：极差 %.6f，p>=0.3 有 %d 组，可以进入对拍。' % (spread, above))
    return 0


if __name__ == '__main__':
    sys.exit(main())
