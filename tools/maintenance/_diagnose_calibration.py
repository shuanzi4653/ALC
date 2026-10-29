# -*- coding: utf-8 -*-
"""模型诊断：0.3077 到底是"模型老了"还是"校准层塌了"（0.11.3 · 追加）。

三问：
  Q1 原始概率在 test 集上的可靠性如何（raw 在 0.9 附近实际发生多少）？
  Q2 现有 isotonic 校准表在高端给出多少？它和 Q1 差多远？
  Q3 换成两参数 Platt（logistic）校准，Brier 与高端可靠性会不会更好？

判据：Q1 与 Q2 若差得远 ⇒ 问题在校准层，不在森林；不要把锅甩给"模型太老"。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'ml'))
sys.path.insert(0, str(ROOT / 'backend-python'))

import train_nowcast as tn                      # noqa: E402
from ml import nowcast                          # noqa: E402

METRICS = ROOT / 'data' / 'training' / 'metar' / 'model-v2-metrics.json'
TARGETS = (('vis', 'labelVis'), ('vis3k', 'labelVis3k'), ('gust', 'labelGust'))


def brier(p, y):
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    return float(np.mean((p - y) ** 2))


def high_band(p, y, floor=0.8):
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = p >= floor
    if mask.sum() == 0:
        return {'n': 0}
    return {'n': int(mask.sum()), 'meanP': round(float(p[mask].mean()), 4),
            'observed': round(float(y[mask].mean()), 4)}


def main() -> int:
    metrics = json.loads(METRICS.read_text(encoding='utf-8'))
    defaults = metrics['defaults']
    rows = []
    for station in ('ZYTX', 'ZYCC', 'ZYHB'):
        rows += tn.build(station, tn.load_station(station), tn.load_om(station))
    train, val, test = tn.split(rows)
    print('rows: train %d / val %d / test %d' % (len(train), len(val), len(test)))
    report = {}
    for key, label in TARGETS:
        model = nowcast.load(key)
        if model is None:
            print('%s: model missing' % key)
            continue
        started = time.time()
        xv = tn.vectorise(val, defaults)
        xt = tn.vectorise(test, defaults)
        raw_v = np.array([model.raw(list(row)) for row in xv])
        raw_t = np.array([model.raw(list(row)) for row in xt])
        y_v = np.array([row[label] for row in val], dtype=float)
        y_t = np.array([row[label] for row in test], dtype=float)
        iso_t = np.array([nowcast._interp(p, model.calibration['x'], model.calibration['y'])
                          for p in raw_t])

        # Platt：在 val 上拟合 a,b（logit(p)=a*logit(raw)+b），再在 test 上评估
        from sklearn.linear_model import LogisticRegression
        eps = 1e-6
        def logit(p):
            p = np.clip(p, eps, 1 - eps)
            return np.log(p / (1 - p))
        keep = np.isfinite(y_v)
        lr = LogisticRegression(solver='lbfgs')
        lr.fit(logit(raw_v[keep]).reshape(-1, 1), y_v[keep].astype(int))
        platt_t = lr.predict_proba(logit(raw_t).reshape(-1, 1))[:, 1]

        report[key] = {
            'n_test': int(len(y_t)), 'positives': int(y_t.sum()),
            'brier': {'raw': round(brier(raw_t, y_t), 5),
                      'isotonic': round(brier(iso_t, y_t), 5),
                      'platt': round(brier(platt_t, y_t), 5)},
            'high_0.8': {'raw': high_band(raw_t, y_t),
                         'isotonic': high_band(iso_t, y_t),
                         'platt': high_band(platt_t, y_t)},
            'raw_max': round(float(raw_t.max()), 4),
            'iso_max': round(float(iso_t.max()), 4),
            'platt_max': round(float(platt_t.max()), 4),
            'platt_params': {'a': round(float(lr.coef_[0][0]), 4),
                             'b': round(float(lr.intercept_[0]), 4)},
            'seconds': round(time.time() - started, 1),
        }
        print('\n== %s (%.1fs)' % (key, report[key]['seconds']))
        print('  Brier  raw %.5f | isotonic %.5f | platt %.5f' %
              (report[key]['brier']['raw'], report[key]['brier']['isotonic'],
               report[key]['brier']['platt']))
        print('  max    raw %.4f | iso %.4f | platt %.4f' %
              (report[key]['raw_max'], report[key]['iso_max'], report[key]['platt_max']))
        for name in ('raw', 'isotonic', 'platt'):
            band = report[key]['high_0.8'][name]
            print('  >=0.8  %-9s %s' % (name, band))
        print('  platt a=%s b=%s' % (report[key]['platt_params']['a'],
                                      report[key]['platt_params']['b']))

    out = ROOT / '.run' / 'model-calibration-diagnosis.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\nwrote', out.relative_to(ROOT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
