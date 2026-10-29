# -*- coding: utf-8 -*-
"""0.11.1 训练：**低空可飞性概率**（低能见度 / 强阵风），标签取 METAR 实测。

与 0.10.1 的 `train_model.py` 的关系：**这不是它的升级，是换掉了它的问题定义。**
    0.10.1：四档分类（FIT/CAUTION/DANGER/BAN），标签 = `config/labels-v1.json` 判据，
            指标 macroF1 0.977 —— 衡量的是"复现判据"的能力。
    0.11.1：两个二分类概率，标签 = 3 站 METAR 实测观测（未来 3 h 内是否出现），
            指标 TS/POD/FAR/Brier + 三条基线 —— 衡量的是"预报天气"的能力。
    ⇒ 旧指标不可与新指标并列比较，页面与文档里不许把 0.977 和 TS 放在同一张表。

三条纪律（手册 §8.4，评委一定会问）：
1. **按时间切分，绝不随机**。同一场雾的相邻时刻同时出现在训练与测试里会让指标虚高。
2. **正样本率按真实频率报**，不做平衡采样后再报"准确率"。
3. **事件去重**：提前量按"事件起始"算，一场持续 6 小时的雾算 1 个事件。

产出：
    models/ml-v2-vis.json        低能见度（<1000 m）概率模型 + isotonic 校准表
    models/ml-v2-vis3k.json      低能见度（<3000 m，"注意"级）
    models/ml-v2-gust.json       强阵风（>10 m/s）概率模型
    data/training/model-v2-metrics.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend-python'))

import numpy as np  # noqa: E402
from sklearn.ensemble import RandomForestClassifier  # noqa: E402
from sklearn.isotonic import IsotonicRegression  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from ml.forest import Forest  # noqa: E402
from ml.nowcast import FEATURES  # noqa: E402  —— 特征顺序的唯一来源，训练侧不另写一份

DATA = ROOT / 'data' / 'training' / 'metar'
MODELS = ROOT / 'models'

TRAIN_END = '2023-12-31T23:59:59Z'
VAL_START = '2024-01-01T00:00:00Z'
VAL_END = '2024-12-31T23:59:59Z'
TEST_START = '2025-01-01T00:00:00Z'

TARGETS = {
    'vis':  {'label': 'labelVis',  'threshold': 1000.0, 'op': 'lt', 'title': '低能见度 <1000 m'},
    'vis3k': {'label': 'labelVis3k', 'threshold': 3000.0, 'op': 'lt', 'title': '低能见度 <3000 m'},
    'gust': {'label': 'labelGust', 'threshold': 10.0, 'op': 'gt', 'title': '强阵风 >10 m/s'},
}


def _f(v):
    if v in (None, '', 'M', 'T'):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_station(station: str):
    """读清洗后的逐小时序列，按小时去重（同一小时多条 METAR 取最后一条）。"""
    path = DATA / 'series.csv'
    per_hour = {}
    with path.open(encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            if row['station'] != station:
                continue
            epoch = int(row['epoch'])
            hour = epoch - epoch % 3600
            per_hour[hour] = {
                'hour': hour,
                'visM': _f(row['visM']), 'gustMs': _f(row['gustMs']), 'windMs': _f(row['windMs']),
                'wdirDeg': _f(row['wdirDeg']), 'tempC': _f(row['tempC']), 'dewC': _f(row['dewC']),
                'cloudBaseM': _f(row['cloudBaseM']), 'qnhHpa': _f(row['qnhHpa']),
            }
    return [per_hour[k] for k in sorted(per_hour)]


def load_om(station: str):
    path = DATA / f'om-{station}.csv'
    out = {}
    if not path.is_file():
        return out
    with path.open(encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            # Open-Meteo 的时间串是 `2019-01-01T00:00`（不带秒）。只按
            # `%Y-%m-%dT%H:%M:%S` 解析会**静默跳过每一行**，于是 OM 基线全空、
            # 概率延伸表全 None —— 而指标仍然照常打印（基线 TS=0.0 看起来像"模式很差"）。
            raw = (row.get('timeUtc') or '').strip().rstrip('Z')
            ts = None
            for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M'):
                try:
                    ts = datetime.strptime(raw[:19], fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
            if ts is None:
                continue
            out[int(ts.timestamp())] = {
                'vis': _f(row['visibility']), 'gust': _f(row['wind_gusts_10m']),
                'wind': _f(row['wind_speed_10m']), 'temp': _f(row['temperature_2m']),
            }
    return out


def build(station: str, series, om):
    """逐小时样本 + 未来 3 h 标签。窗口内有效观测不足 2 个的样本丢弃（不补 0）。"""
    index = {r['hour']: r for r in series}
    rows = []
    for r in series:
        h = r['hour']
        window = [index.get(h + k * 3600) for k in (1, 2, 3)]
        valid = [w for w in window if w is not None]
        if len(valid) < 2:
            continue
        vis_vals = [w['visM'] for w in valid if w['visM'] is not None]
        gust_vals = [w['gustMs'] for w in valid if w['gustMs'] is not None]
        if len(vis_vals) < 2 and len(gust_vals) < 2:
            continue
        label_vis = 1 if vis_vals and min(vis_vals) < 1000.0 else (0 if len(vis_vals) >= 2 else None)
        label_vis3k = 1 if vis_vals and min(vis_vals) < 3000.0 else (0 if len(vis_vals) >= 2 else None)
        label_gust = 1 if gust_vals and max(gust_vals) > 10.0 else (0 if len(gust_vals) >= 2 else None)
        if label_vis is None and label_gust is None:
            continue

        past = [index.get(h - k * 3600) for k in (1, 2, 3, 4, 5, 6)]
        pv = [p['visM'] for p in past if p and p['visM'] is not None]
        pg = [p['gustMs'] for p in past if p and p['gustMs'] is not None]
        pq = [p['qnhHpa'] for p in past if p and p['qnhHpa'] is not None]
        ts = datetime.fromtimestamp(h, tz=timezone.utc)
        hour_rad = ts.hour * 2 * np.pi / 24.0
        dew_spread = (r['tempC'] - r['dewC']) if (r['tempC'] is not None and r['dewC'] is not None) else None
        wdir = r['wdirDeg']
        wdir_rad = None if wdir is None else wdir * np.pi / 180.0
        gust_change = (r['gustMs'] - pg[0]) / 1.0 if (r['gustMs'] is not None and pg) else None
        qnh_tend = (r['qnhHpa'] - pq[0]) if (r['qnhHpa'] is not None and pq) else None
        # 3 小时前的同一要素：历史不足 3 小时就留空，由中位数填充 + 缺失口径承担
        def at3h(field):
            return past[2][field] if len(past) >= 3 and past[2] is not None else None
        vis3, temp3, dew3 = at3h('visM'), at3h('tempC'), at3h('dewC')
        rows.append({
            'station': station, 'epoch': h, 'iso': ts.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'visM': r['visM'], 'gustMs': r['gustMs'], 'windMs': r['windMs'],
            'wdirSin': None if wdir_rad is None else float(np.sin(wdir_rad)),
            'wdirCos': None if wdir_rad is None else float(np.cos(wdir_rad)),
            'tempC': r['tempC'], 'dewC': r['dewC'], 'dewSpread': dew_spread,
            'cloudBaseM': r['cloudBaseM'], 'qnhHpa': r['qnhHpa'],
            'visMin3h': min(pv[:3]) if pv[:3] else None,
            'visMin6h': min(pv) if pv else None,
            'gustMax3h': max(pg[:3]) if pg[:3] else None,
            'windChange3h': gust_change,
            'qnhTendency3h': qnh_tend,
            'visChange3h': (r['visM'] - vis3) if (r['visM'] is not None and vis3 is not None) else None,
            'tempTendency3h': (r['tempC'] - temp3) if (r['tempC'] is not None and temp3 is not None) else None,
            'spreadTendency3h': (dew_spread - (temp3 - dew3))
                                if (dew_spread is not None and temp3 is not None and dew3 is not None) else None,
            'stationCode': float({'ZYTX': 0, 'ZYCC': 1, 'ZYHB': 2}[station]),
            'hourSin': float(np.sin(hour_rad)), 'hourCos': float(np.cos(hour_rad)),
            'month': ts.month,
            'miss_vis': 1.0 if r['visM'] is None else 0.0,
            'miss_gust': 1.0 if r['gustMs'] is None else 0.0,
            'miss_cloud': 1.0 if r['cloudBaseM'] is None else 0.0,
            'miss_temp': 1.0 if r['tempC'] is None else 0.0,
            # 诚实基线需要的"当前实况"，不喂给模型
            '_om': om.get(h) or {},
            'labelVis': label_vis, 'labelVis3k': label_vis3k, 'labelGust': label_gust,
        })
    return rows


def vectorise(rows, defaults):
    x = np.zeros((len(rows), len(FEATURES)), dtype=np.float64)
    for i, row in enumerate(rows):
        for j, name in enumerate(FEATURES):
            v = row.get(name)
            x[i, j] = defaults.get(name, 0.0) if v is None else float(v)
    return x


def split(rows):
    train = [r for r in rows if r['iso'] <= TRAIN_END]
    val = [r for r in rows if VAL_START <= r['iso'] <= VAL_END]
    test = [r for r in rows if r['iso'] >= TEST_START]
    return train, val, test


def export_tree(estimator, node=0):
    tree = estimator.tree_
    left, right = tree.children_left[node], tree.children_right[node]
    if left == -1:
        return [float(c) for c in tree.value[node][0]]
    return [int(tree.feature[node]), float(tree.threshold[node]),
            export_tree(estimator, int(left)), export_tree(estimator, int(right))]


def metrics_for(prob, y, threshold=0.5):
    p = np.asarray(prob, dtype=float)
    y = np.asarray(y, dtype=int)
    pred = (p >= threshold).astype(int)
    hit = int(((pred == 1) & (y == 1)).sum())
    miss = int(((pred == 0) & (y == 1)).sum())
    false_alarm = int(((pred == 1) & (y == 0)).sum())
    correct_neg = int(((pred == 0) & (y == 0)).sum())
    ts = hit / (hit + miss + false_alarm) if (hit + miss + false_alarm) else None
    pod = hit / (hit + miss) if (hit + miss) else None
    far = false_alarm / (hit + false_alarm) if (hit + false_alarm) else None
    brier = float(np.mean((p - y) ** 2)) if len(y) else None
    return {
        'n': int(len(y)), 'positives': int(y.sum()), 'positiveRate': round(float(y.mean()), 4) if len(y) else None,
        'hits': hit, 'misses': miss, 'falseAlarms': false_alarm, 'correctNegatives': correct_neg,
        'TS': None if ts is None else round(ts, 4),
        'POD': None if pod is None else round(pod, 4),
        'FAR': None if far is None else round(far, 4),
        'Brier': None if brier is None else round(brier, 4),
        'brierSkillVsClimatology': None,
    }


def reliability(prob, y, bins=10):
    p = np.asarray(prob, dtype=float)
    y = np.asarray(y, dtype=int)
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        mask = (p >= lo) & (p < hi if i < bins - 1 else p <= hi)
        if mask.sum() == 0:
            out.append({'bin': [lo, hi], 'n': 0, 'predicted': None, 'observed': None})
            continue
        out.append({'bin': [lo, hi], 'n': int(mask.sum()),
                    'predicted': round(float(p[mask].mean()), 4),
                    'observed': round(float(y[mask].mean()), 4)})
    return out


def lead_times(rows, prob, label_key, threshold=0.5):
    """事件起始的提前量：p>=0.5 首次出现 → 事件首个正样本，中位数（分钟）。"""
    leads = []
    for station in sorted({r['station'] for r in rows}):
        idx = [i for i, r in enumerate(rows) if r['station'] == station]
        prev = 0
        for pos, i in enumerate(idx):
            y = rows[i].get(label_key)
            if y != 1 or prev == 1:
                prev = y if y is not None else prev
                continue
            lead = None
            for back in range(1, 7):
                j = pos - back
                if j < 0:
                    break
                if prob[idx[j]] >= threshold:
                    lead = back * 60
                    break
            if lead is not None:
                leads.append(lead)
            prev = 1
        # 事件结束时复位
        prev = 0
        for pos, i in enumerate(idx):
            y = rows[i].get(label_key)
            if y == 0:
                prev = 0
            elif y == 1 and prev == 0 and pos > 0 and rows[idx[pos - 1]].get(label_key) != 1:
                prev = 1
    if not leads:
        return {'n': 0, 'medianMin': None, 'note': '测试集内没有可测的"事件起始"（全为持续事件或全为 0）'}
    leads.sort()
    return {'n': len(leads), 'medianMin': int(leads[len(leads) // 2]),
            'p25Min': int(leads[len(leads) // 4]), 'p75Min': int(leads[3 * len(leads) // 4])}


def calibration(prob_val, y_val):
    iso = IsotonicRegression(out_of_bounds='clip', y_min=0.0, y_max=1.0)
    iso.fit(prob_val, y_val)
    xs = np.asarray(iso.X_thresholds_, dtype=float)
    ys = np.asarray(iso.y_thresholds_, dtype=float)
    if len(xs) == 0:
        return {'x': [0.0, 1.0], 'y': [0.0, 1.0]}
    # 端点补齐，运行时按线性插值取值
    if xs[0] > 0:
        xs = np.concatenate(([0.0], xs)); ys = np.concatenate(([ys[0]], ys))
    if xs[-1] < 1:
        xs = np.concatenate((xs, [1.0])); ys = np.concatenate((ys, [ys[-1]]))
    return {'x': [round(float(v), 6) for v in xs], 'y': [round(float(v), 6) for v in ys]}


def apply_calibration(prob, table):
    return np.interp(prob, np.asarray(table['x']), np.asarray(table['y']))


def train_target(key, rows, defaults, out_models):
    label_key = TARGETS[key]['label']
    usable = [r for r in rows if r.get(label_key) is not None]
    train, val, test = split(usable)
    if not train or not val or not test:
        raise SystemExit(f'{key}: 切分后有空集（train {len(train)} / val {len(val)} / test {len(test)}）')

    x_train = vectorise(train, defaults)
    y_train = np.array([r[label_key] for r in train], dtype=int)
    x_val = vectorise(val, defaults); y_val = np.array([r[label_key] for r in val], dtype=int)
    x_test = vectorise(test, defaults); y_test = np.array([r[label_key] for r in test], dtype=int)

    clf = RandomForestClassifier(
        n_estimators=100, max_depth=10, min_samples_leaf=100, max_features='sqrt',
        class_weight='balanced_subsample', random_state=42, n_jobs=-1,
    )
    clf.fit(x_train, y_train)
    raw_val = clf.predict_proba(x_val)[:, 1]
    table = calibration(raw_val, y_val)
    raw_test = clf.predict_proba(x_test)[:, 1]
    prob_test = apply_calibration(raw_test, table)
    prob_val = apply_calibration(raw_val, table)

    # 工作点阈值**只在验证集上选**（最大化 TS），选完再拿到测试集上报告。
    # 直接拿测试集的"最优阈值"报指标就是偷看答案；而在 0.5 上报又会低估一个
    # 稀有事件的模型（校准后的概率很少越过 0.5，这是校准的必然结果，不是模型差）。
    def ts_at(p, y, t):
        pred = p >= t
        hit = int(((pred) & (y == 1)).sum())
        miss = int(((~pred) & (y == 1)).sum())
        fa = int(((pred) & (y == 0)).sum())
        return hit / (hit + miss + fa) if (hit + miss + fa) else 0.0

    grid = [round(0.05 + i * 0.01, 2) for i in range(91)]
    operating = max(grid, key=lambda t: ts_at(prob_val, y_val, t))
    metrics_at_operating = metrics_for(prob_test, y_test, threshold=operating)

    # ---- 三条基线：同一测试集、同一标签 ----
    persistence, om_baseline, rule_baseline = [], [], []
    for r in test:
        threshold = TARGETS[key]['threshold']
        if key == 'gust':
            persistence.append(1.0 if (r['gustMs'] is not None and r['gustMs'] > threshold) else 0.0)
            rule_baseline.append(1.0 if (r['gustMs'] is not None and r['gustMs'] > threshold) else 0.0)
            omv = r['_om'].get('gust')
            om_baseline.append(1.0 if (omv is not None and omv > threshold) else 0.0)
        else:
            persistence.append(1.0 if (r['visM'] is not None and r['visM'] < threshold) else 0.0)
            rule_baseline.append(1.0 if (r['visM'] is not None and r['visM'] < 800.0) else 0.0)
            omv = r['_om'].get('vis')
            om_baseline.append(1.0 if (omv is not None and omv < threshold) else 0.0)

    clim = float(y_train.mean())
    clim_brier = float(np.mean((clim - y_test) ** 2))

    def pack(prob, threshold=0.5):
        m = metrics_for(prob, y_test, threshold=threshold)
        m['brierSkillVsClimatology'] = round(1 - m['Brier'] / clim_brier, 4) if clim_brier else None
        return m

    # **指标必须按工作点阈值报**，否则"操作阈值"这个字段只是装饰：
    # 校准后的概率很少越过 0.5（稀有事件的真实频率就是这样），在 0.5 上报会把
    # 一个 AUC 0.94 的模型报成 TS 0.1。两个口径都留，页面只展示工作点。
    model_m = pack(prob_test, threshold=operating)
    model_m['operatingThreshold'] = operating
    model_m['atThreshold05'] = pack(prob_test, threshold=0.5)
    model_m['tsChosenOn'] = 'validation set (max TS), applied unchanged to test'
    result = {
        'title': TARGETS[key]['title'],
        'threshold': TARGETS[key]['threshold'],
        'model': model_m,
        'baselines': {
            'persistence': pack(np.array(persistence)),
            'openMeteo': pack(np.array(om_baseline)),
            'thresholdRule': pack(np.array(rule_baseline)),
        },
        'climatology': {'rate': round(clim, 4), 'brier': round(clim_brier, 5)},
        'auc': round(float(roc_auc_score(y_test, prob_test)), 4) if len(set(y_test.tolist())) > 1 else None,
        'aucRaw': round(float(roc_auc_score(y_test, raw_test)), 4) if len(set(y_test.tolist())) > 1 else None,
        'reliability': reliability(prob_test, y_test),
        'leadTime': lead_times(test, prob_test, label_key, threshold=operating),
        'sizes': {'train': len(train), 'val': len(val), 'test': len(test),
                  'positives': {'train': int(y_train.sum()), 'val': int(y_val.sum()), 'test': int(y_test.sum())}},
        'valBrier': round(float(np.mean((prob_val - y_val) ** 2)), 5),
    }

    # 失败样本：FP 与 FN 各 10 条（模型卡上"查看失败样本 20 例"的落地）
    fp = [i for i in range(len(y_test)) if prob_test[i] >= 0.5 and y_test[i] == 0]
    fn = [i for i in range(len(y_test)) if prob_test[i] < 0.5 and y_test[i] == 1]
    picks = [(i, 'FP') for i in fp[:10]] + [(i, 'FN') for i in fn[:10]]
    result['failures'] = [{
        'type': kind, 'station': test[i]['station'], 'timeUtc': test[i]['iso'],
        'p': round(float(prob_test[i]), 4), 'observed': int(y_test[i]),
        'visM': test[i]['visM'], 'gustMs': test[i]['gustMs'], 'dewSpread': test[i]['dewSpread'],
        'visMin3h': test[i]['visMin3h'], 'gustMax3h': test[i]['gustMax3h'],
    } for i, kind in picks]

    # ---- 导出：纯 Python 打分器可读的树 ----
    importance = {name: round(float(v), 6) for name, v in zip(FEATURES, clf.feature_importances_)}
    trees = [export_tree(est) for est in clf.estimators_]
    payload = {
        'format': 'alc-forest-v1',
        'modelVersion': f'ml-v2-{key}',
        'labelsVersion': 'metar-v1',
        'classes': ['NEG', 'POS'],
        'featureNames': list(FEATURES),
        'trees': trees,
        'defaults': defaults,
        'featureImportance': importance,
        'trainStats': {},
        'calibration': table,
        'operatingThreshold': operating,
        'provenance': {
            'trainedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'sklearn': __import__('sklearn').__version__,
            'numpy': np.__version__,
            'samples': len(train),
            'split': 'time-ordered: train<=2023-12-31, val=2024, test>=2025-01-01, no shuffle',
            'labelSource': 'METAR observations (ZYTX/ZYCC/ZYHB), Iowa State ASOS archive',
            'note': '标签是实测观测；模型只吃观测历史与时间，不吃任何模式预报值',
            'target': TARGETS[key]['title'],
            'window': 'future 3h (t+1h..t+3h)',
        },
    }
    path = MODELS / f'ml-v2-{key}.json'
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    out_models[key] = {'path': path.name, 'bytes': path.stat().st_size}

    # ---- 导出后 parity：纯 Python 打分器与 sklearn 必须一致 ----
    forest = Forest(payload)
    diffs = []
    for i in range(0, len(test), max(1, len(test) // 200)):
        # sklearn 的树模型内部把 X 转成 **float32** 再比阈值；纯 Python 侧是 float64。
        # 不先把向量压成 float32，会有极少数"正好贴着阈值"的样本走进另一侧叶子，
        # 于是对照报出 1e-3 级差异 —— 那是精度口径不同，不是导出走样。
        vec = np.asarray(x_test[i], dtype=np.float32).astype(np.float64).tolist()
        py = forest.predict(vec)['probabilitiesExact']['POS']
        diffs.append(abs(py - float(raw_test[i])))
    result['exportParity'] = {'checked': len(diffs), 'maxAbsDiff': round(max(diffs), 9),
                              'tolerance': 1e-6,
                              'note': '对照取未舍入概率；输入先压成 float32（与 sklearn 树模型同口径），'
                                      '超过 1e-6 说明导出走样'}
    if max(diffs) > 1e-6:
        raise SystemExit(f'{key}: 导出走样，纯 Python 与 sklearn 最大偏差 {max(diffs)}')

    print(f'{key}: TS={model_m["TS"]} POD={model_m["POD"]} FAR={model_m["FAR"]} '
          f'Brier={model_m["Brier"]} · 基线 persistence TS={result["baselines"]["persistence"]["TS"]} '
          f'om TS={result["baselines"]["openMeteo"]["TS"]} rule TS={result["baselines"]["thresholdRule"]["TS"]}',
          flush=True)
    return result


def om_probability_tables(rows):
    """把 Open-Meteo 的逐时值映射成"该值时实测事件发生的频率"。

    用途只有一个：**模式延伸**。模型本身只吃观测（0–3 h），3–6 h 的曲线由这条
    经验映射给出，页面上必须标成"模式延伸（按历史频率校准）"，不能标成模型结论。
    只用 train + val 段拟合，**不看测试期**，否则延伸曲线会带着测试集信息。
    """
    fit_rows = [r for r in rows if r['iso'] <= VAL_END]
    tables = {}
    for key, cfg in TARGETS.items():
        om_key = 'gust' if key == 'gust' else 'vis'
        # 末段必须贴着数据源的实际上限：Open-Meteo 的能见度在 24 km 处**封顶**
        # （实测最大值 24 140 m），开一个 [25 000, ∞) 的箱子会永远没有样本，
        # 于是"晴空"落进空箱 → 延伸曲线整段消失，而页面上只会显示"模式延伸不可用"。
        bins = ([0, 2, 4, 6, 8, 10, 12, 15, 20, 25, 999] if om_key == 'gust'
                else [0, 200, 500, 800, 1000, 1500, 2000, 3000, 5000, 8000, 10000, 15000, 24000, 99999])
        events, totals = [0] * (len(bins) - 1), [0] * (len(bins) - 1)
        for r in fit_rows:
            value = (r['_om'] or {}).get(om_key)
            observed = r.get('visM') if om_key == 'vis' else r.get('gustMs')
            if value is None or observed is None:
                continue
            idx = None
            for i in range(len(bins) - 1):
                if bins[i] <= value < bins[i + 1]:
                    idx = i
                    break
            if idx is None:
                continue
            totals[idx] += 1
            hit = (observed < cfg['threshold']) if cfg['op'] == 'lt' else (observed > cfg['threshold'])
            events[idx] += 1 if hit else 0
        freq = []
        for i in range(len(bins) - 1):
            freq.append(None if totals[i] == 0 else round(events[i] / totals[i], 4))
        # 空箱向后/向前借用最近的非空频率：延伸曲线的观感要连续，但**借用的箱子
        # 必须留下样本数为 0 的痕迹**，页面据此标"该区间无历史样本"。
        tables[key] = {'var': om_key, 'bins': bins, 'freq': freq, 'n': totals,
                       'threshold': cfg['threshold'], 'op': cfg['op']}
    return tables


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--models', default='all', help='all 或逗号分隔的 vis,vis3k,gust')
    args = parser.parse_args()

    defaults = {}
    all_rows = []
    om_cache = {}
    for station in ('ZYTX', 'ZYCC', 'ZYHB'):
        series = load_station(station)
        om_cache[station] = load_om(station)
        rows = build(station, series, om_cache[station])
        all_rows.extend(rows)
        print(f'{station}: {len(series)} 小时 → {len(rows)} 样本', flush=True)

    # 缺失值用**训练段**中位数填（不是 0，也不是全量中位数——那会漏进测试期信息）
    train_rows, _, _ = split(all_rows)
    for name in FEATURES:
        if name.startswith('miss_'):
            defaults[name] = 0.0
            continue
        vals = [r[name] for r in train_rows if r.get(name) is not None]
        defaults[name] = round(float(np.median(vals)), 4) if vals else 0.0

    targets = list(TARGETS) if args.models == 'all' else args.models.split(',')
    results = {}
    out_models = {}
    for key in targets:
        results[key] = train_target(key, all_rows, defaults, out_models)

    series_bytes = (DATA / 'series.csv').read_bytes()
    payload = {
        'version': 'v2',
        'createdAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'task': '低空可飞性概率（低能见度 / 强阵风），未来 3 小时',
        'labelSource': 'METAR 实测观测（ZYTX / ZYCC / ZYHB），Iowa State ASOS archive',
        'dataset': {'rows': len(all_rows), 'sha256': hashlib.sha256(series_bytes).hexdigest(),
                    'stations': ['ZYTX', 'ZYCC', 'ZYHB'], 'years': '2019-2025'},
        'split': {'train': '<=2023-12-31', 'val': '2024', 'test': '>=2025-01-01',
                  'note': '按时间切分，不随机打乱'},
        'features': list(FEATURES),
        'defaults': defaults,
        'models': out_models,
        'targets': results,
        'omProbability': om_probability_tables(all_rows),
        'baselineNote': '基线 openMeteo 取 historical-forecast-api 的逐时值（不带起报时刻），'
                        '是近似基线，不是同一起报时次的业务预报',
    }
    path = DATA / 'model-v2-metrics.json'
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'→ {path} ({path.stat().st_size} B)', flush=True)
    for key, info in out_models.items():
        print(f'   {info["path"]}: {info["bytes"]} B', flush=True)


if __name__ == '__main__':
    main()
