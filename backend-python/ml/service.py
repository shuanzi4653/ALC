from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from . import features as F
from .forest import Forest, ModelError

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = ROOT / 'models' / 'ml-v1.json'

LEVEL_LABELS = {'FIT': '适飞', 'CAUTION': '谨慎', 'DANGER': '危险', 'BAN': '禁飞'}

_lock = threading.Lock()
_cache: Dict[str, Any] = {}

def model_path() -> Path:
    return Path(os.environ.get('ALC_ML_MODEL') or DEFAULT_MODEL)

def load(force: bool = False) -> Optional[Forest]:
    path = model_path()
    key = str(path)
    with _lock:
        if force:
            _cache.pop(key, None)
        if key in _cache:
            return _cache[key]
        if not path.is_file():
            return None
        try:
            forest = Forest(json.loads(path.read_text(encoding='utf-8')))
        except (ModelError, ValueError, KeyError):
            return None
        _cache[key] = forest
        return forest

def status() -> Dict[str, Any]:
    forest = load()
    if forest is None:
        return {'available': False, 'reason': 'MODEL_NOT_FOUND', 'path': str(model_path())}
    return {
        'available': True,
        'modelVersion': forest.model_version,
        'labelsVersion': forest.labels_version,
        'featureCount': len(forest.feature_names),
        'trees': len(forest.trees),
        'provenance': forest.provenance,
    }

LOW_CONFIDENCE_MARGIN = 0.10
DEGRADED_MISSING = 3

def predict(snapshot: Dict[str, Any], hour: Optional[float] = None,
            month: Optional[float] = None) -> Dict[str, Any]:
    forest = load()
    if forest is None:
        return {
            'available': False,
            'status': 'MODEL_NOT_FOUND',
            'reason': 'MODEL_NOT_FOUND',
            'note': '轨1 模型文件不存在；本端点不返回任何档位（编一个档位比不返回更糟）',
            'path': str(model_path()),
        }

    canon = F.from_runtime(snapshot, hour=hour, month=month)
    vector = F.vector(canon, forest.defaults)
    result = forest.predict(vector)
    factors = forest.top_factors(vector, k=3)
    missing = F.missing_of(canon)

    probs = sorted(result['probabilities'].values(), reverse=True)
    margin = round(probs[0] - probs[1], 4) if len(probs) > 1 else 1.0

    degraded = {
        'flag': len(missing) >= DEGRADED_MISSING,
        'reason': ('关键要素缺测 %d 个（%s），档位基于训练中位数填充'
                   % (len(missing), '、'.join(missing))) if len(missing) >= DEGRADED_MISSING else None,
    }

    return {
        'available': True,
        'status': 'OK',
        'level': result['level'],
        'levelLabel': LEVEL_LABELS.get(result['level'], result['level']),
        'confidence': result['confidence'],
        'lowConfidence': margin < LOW_CONFIDENCE_MARGIN,
        'margin': margin,
        'probabilities': result['probabilities'],
        'top3': factors,
        'missingFeatures': missing,
        'degraded': degraded,
        'modelVersion': forest.model_version,
        'labelsVersion': forest.labels_version,
        'decidedBy': 'MODEL',
        'attribution': 'top3 = 全局分裂重要性 × 该样本标准化偏离（近似归因，不是逐条 SHAP）',
        'provenance': {
            'labelsSha256': forest.payload.get('labelsSha256'),
            'datasetSha256': forest.payload.get('datasetSha256'),
            'trainedAt': (forest.provenance or {}).get('trainedAt'),
            'sklearn': (forest.provenance or {}).get('sklearn'),
            'labelSource': (forest.provenance or {}).get('labelSource'),
        },
    }
