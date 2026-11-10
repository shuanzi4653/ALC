# -*- coding: utf-8 -*-
"""全国低能见度模型（ml-v3）推理。

模型的来历见 `tools/model/train_national_vis.py`：用 open-meteo hourly 在
全国 319 个城市上训练的 L2 逻辑回归，标签是"1 小时后能见度 < 3 km"。
权重、标准化参数、指标、数据出处都在 `models/ml-v3-national-vis.json` 里，
可以逐项复核，不需要再跑一遍训练。

用法
----
    from ml import national_model
    p = national_model.probability(features)      # 单个城市
    ps = national_model.probability_map(feature_map)   # {城市: 特征}
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[2]
MODEL_FILE = ROOT / 'models' / 'ml-v3-national-vis.json'

_cache: Dict[str, Any] = {'payload': None, 'mtime': None}


def load() -> Optional[Dict[str, Any]]:
    if not MODEL_FILE.is_file():
        return None
    mtime = MODEL_FILE.stat().st_mtime
    if _cache['payload'] is None or _cache['mtime'] != mtime:
        try:
            _cache['payload'] = json.loads(MODEL_FILE.read_text(encoding='utf-8'))
            _cache['mtime'] = mtime
        except Exception:  # noqa: BLE001 - 模型坏了就退回规则，不让页面挂
            return None
    return _cache['payload']


def probability(features: Dict[str, Any]) -> Optional[float]:
    """单个城市的低能见度概率。缺特征时该维按均值（标准化后为 0）处理。"""
    model = load()
    if not model or not features:
        return None
    z = float(model['intercept'])
    for name, weight, mean, std in zip(model['features'], model['weights'],
                                       model['means'], model['stds']):
        value = features.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        z += weight * ((float(value) - mean) / (std or 1.0))
    z = max(-30.0, min(30.0, z))
    return round(1.0 / (1.0 + math.exp(-z)), 4)


def probability_map(features_by_city: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for name, features in (features_by_city or {}).items():
        value = probability(features)
        if value is not None:
            out[name] = value
    return out


def card() -> Dict[str, Any]:
    """给界面用的模型卡：指标 + 数据出处 + 局限。"""
    model = load()
    if not model:
        return {'available': False, 'note': '全国模型文件不存在，界面应退回规则派生'}
    metrics = model.get('metrics') or {}
    provenance = model.get('provenance') or {}
    return {
        'available': True,
        'key': model.get('model'),
        'version': model.get('modelVersion'),
        'target': model.get('target'),
        'kind': model.get('kind'),
        'features': len(model.get('features') or []),
        'metrics': {'train': metrics.get('train'), 'test': metrics.get('test')},
        'provenance': {
            'source': provenance.get('source'),
            'cities': provenance.get('cities'),
            'days': provenance.get('pastDays'),
            'samples': provenance.get('samples'),
            'split': provenance.get('split'),
            'caveat': provenance.get('caveat'),
        },
        'trainedAt': model.get('trainedAt'),
    }
