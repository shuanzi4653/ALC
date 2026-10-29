# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .forest import Forest, ModelError

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / 'models'
METRICS_FILE = ROOT / 'data' / 'training' / 'metar' / 'model-v2-metrics.json'

FEATURES = (
    'visM', 'gustMs', 'windMs', 'wdirSin', 'wdirCos',
    'tempC', 'dewC', 'dewSpread', 'cloudBaseM', 'qnhHpa',
    'visMin3h', 'visMin6h', 'gustMax3h', 'windChange3h', 'qnhTendency3h',
    'visChange3h', 'tempTendency3h', 'spreadTendency3h', 'stationCode',
    'hourSin', 'hourCos', 'month',
    'miss_vis', 'miss_gust', 'miss_cloud', 'miss_temp',
)

STATION_CODE = {'ZYTX': 0.0, 'ZYCC': 1.0, 'ZYHB': 2.0}

MODEL_FILES = {
    'vis': MODEL_DIR / 'ml-v2-vis.json',
    'vis3k': MODEL_DIR / 'ml-v2-vis3k.json',
    'gust': MODEL_DIR / 'ml-v2-gust.json',
}

def _operations_limits() -> dict:
    try:
        import json as _json
        from pathlib import Path as _Path
        path = _Path(__file__).resolve().parents[2] / 'config' / 'rules-v1.json'
        return (_json.loads(path.read_text(encoding='utf-8')) or {}).get('operations') or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning('operations 阈值读取失败，本次回落 lowVis=1000 / cautionVis=3000 / '
                       'gustMps=11.5（几何侧可能仍是 17，两边会分叉）：%s', exc)
        return {}

_OPERATIONS = _operations_limits()
LOW_VIS_M = float(_OPERATIONS.get('lowVisM') or 1000.0)
CAUTION_VIS_M = float(_OPERATIONS.get('cautionVisM') or 3000.0)
GUST_LIMIT_MS = float(_OPERATIONS.get('gustMps') or 11.5)

_lock = threading.Lock()
_cache: Dict[str, Any] = {}

class Model:
    def __init__(self, payload: Dict[str, Any]):
        self.forest = Forest(payload)
        self.calibration = payload.get('calibration') or {'x': [0.0, 1.0], 'y': [0.0, 1.0]}
        self.provenance = dict(payload.get('provenance') or {})

    def raw(self, vector: List[float]) -> float:
        return float(self.forest.predict(vector)['probabilities']['POS'])

    def probability(self, vector: List[float]) -> Dict[str, float]:
        raw = self.raw(vector)
        cal = _interp(raw, self.calibration['x'], self.calibration['y'])
        return {'raw': round(raw, 4), 'calibrated': round(cal, 4)}

def _interp(x: float, xs: List[float], ys: List[float]) -> float:
    """与训练侧的 `numpy.interp` 同语义：越界取端点，中间线性插值。"""
    if not xs:
        return x
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    for i in range(1, len(xs)):
        if x <= xs[i]:
            span = xs[i] - xs[i - 1]
            if span <= 0:
                return float(ys[i])
            ratio = (x - xs[i - 1]) / span
            return float(ys[i - 1] + ratio * (ys[i] - ys[i - 1]))
    return float(ys[-1])

def load(key: str) -> Optional[Model]:
    path = MODEL_FILES[key]
    with _lock:
        if key in _cache:
            return _cache[key]
        if not path.is_file():
            return None
        try:
            model = Model(json.loads(path.read_text(encoding='utf-8')))
        except (ModelError, ValueError, KeyError, TypeError):
            return None
        _cache[key] = model
        return model

def metrics() -> Optional[Dict[str, Any]]:
    if not METRICS_FILE.is_file():
        return None
    try:
        return json.loads(METRICS_FILE.read_text(encoding='utf-8'))
    except ValueError:
        return None

def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return float(value)

def vector_for(row: Dict[str, Any], history: List[Dict[str, Any]],
               defaults: Dict[str, float]) -> List[float]:
    past = list(reversed(history))[:6]
    pv = [p.get('visM') for p in past if p.get('visM') is not None]
    pg = [p.get('gustMs') for p in past if p.get('gustMs') is not None]
    pq = [p.get('qnhHpa') for p in past if p.get('qnhHpa') is not None]
    ts = datetime.fromtimestamp(int(row['epoch']), tz=timezone.utc)
    hour_rad = ts.hour * 2 * math.pi / 24.0

    vis = row.get('visM')
    gust = row.get('gustMs')
    temp = row.get('tempC')
    dew = row.get('dewC')
    wdir = row.get('wdirDeg')
    qnh = row.get('qnhHpa')
    cloud = row.get('cloudBaseM')

    def at3h(key: str):
        return past[2].get(key) if len(past) >= 3 else None

    vis3, temp3, dew3 = at3h('visM'), at3h('tempC'), at3h('dewC')

    canon = {
        'visM': vis,
        'gustMs': gust,
        'windMs': row.get('windMs'),
        'wdirSin': None if wdir is None else math.sin(wdir * math.pi / 180.0),
        'wdirCos': None if wdir is None else math.cos(wdir * math.pi / 180.0),
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
        'stationCode': STATION_CODE.get(str(row.get('station')), -1.0),
        'hourSin': math.sin(hour_rad),
        'hourCos': math.cos(hour_rad),
        'month': ts.month,
        'miss_vis': 1.0 if vis is None else 0.0,
        'miss_gust': 1.0 if gust is None else 0.0,
        'miss_cloud': 1.0 if cloud is None else 0.0,
        'miss_temp': 1.0 if temp is None else 0.0,
    }
    return [float(canon.get(name)) if canon.get(name) is not None
            else float(defaults.get(name, 0.0)) for name in FEATURES]

def defaults() -> Dict[str, float]:
    payload = metrics() or {}
    return {k: float(v) for k, v in (payload.get('defaults') or {}).items()}

def predict_station(station: str, history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """一个站点的当前概率。`history` 按时间升序，最后一条是当前观测。"""
    if not history:
        return {'station': station, 'available': False, 'reason': 'NO_OBSERVATION'}
    row = history[-1]
    past = history[:-1]
    missing = [k for k in ('visM', 'gustMs', 'tempC', 'dewC') if row.get(k) is None]
    if len([p for p in past if p.get('visM') is not None]) < 1:
        return {'station': station, 'available': False,
                'reason': 'INSUFFICIENT_HISTORY', 'observedAt': row.get('timeUtc')}

    defaults_map = defaults()
    vector = vector_for(row, past, defaults_map)
    out: Dict[str, Any] = {
        'station': station,
        'available': True,
        'observedAt': row.get('timeUtc'),
        'observed': {
            'visM': row.get('visM'), 'gustMs': row.get('gustMs'), 'windMs': row.get('windMs'),
            'visLowerBound': bool(row.get('visLowerBound')),
            'visRaw': row.get('visRaw') or '',
            'tempC': row.get('tempC'), 'dewC': row.get('dewC'),
            'dewSpread': None if (row.get('tempC') is None or row.get('dewC') is None)
                         else round(row['tempC'] - row['dewC'], 2),
            'cloudBaseM': row.get('cloudBaseM'),
        },
        'missing': missing,
    }
    probs = {}
    for key in ('vis', 'vis3k', 'gust'):
        model = load(key)
        if model is None:
            out['available'] = False
            out['reason'] = 'MODEL_NOT_FOUND_%s' % key.upper()
            return out
        probs[key] = model.probability(vector)
        out.setdefault('modelVersion', model.forest.model_version)
    p_vis = probs['vis']['calibrated']
    p_gust = probs['gust']['calibrated']
    p_unsafe = 1.0 - (1.0 - p_vis) * (1.0 - p_gust)
    out['probabilities'] = {
        'lowVis': p_vis, 'lowVis3km': probs['vis3k']['calibrated'],
        'gust': p_gust, 'unsafe': round(p_unsafe, 4),
        'raw': {k: v['raw'] for k, v in probs.items()},
    }
    prob_level = ('BAN' if p_unsafe >= 0.8 else
                  'CAUTION' if p_unsafe >= 0.5 else
                  'WATCH' if p_unsafe >= 0.2 else 'FIT')
    obs_level = observation_level(out.get('observed') or {})
    order = {'FIT': 0, 'WATCH': 1, 'CAUTION': 2, 'BAN': 3}
    level = prob_level if order[prob_level] >= order[obs_level] else obs_level
    out['level'] = level
    out['levelProbability'] = prob_level
    out['levelObservation'] = obs_level
    out['levelSource'] = ('OBSERVATION' if order[obs_level] > order[prob_level]
                          else 'PROBABILITY' if order[prob_level] > order[obs_level]
                          else 'BOTH' if level != 'FIT' else 'NONE')
    out['confidence'] = round(abs(p_unsafe - 0.5) * 2, 4)
    return out

def observation_level(observed: Dict[str, Any]) -> str:
    vis = observed.get('visM')
    gust = observed.get('gustMs')
    if (vis is not None and vis < LOW_VIS_M) or (gust is not None and gust > GUST_LIMIT_MS):
        return 'BAN'
    if vis is not None and vis < CAUTION_VIS_M:
        return 'CAUTION'
    return 'FIT'

def field(stations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """三站合并成一个"当前可飞性场"。全部缺席时返回 available:false。"""
    available = [s for s in stations if s.get('available')]
    if not available:
        return {'available': False, 'reason': 'NO_STATION_OBSERVATION',
                'stations': stations,
                'note': '三站 METAR 均不可用；本系统不拿模式值冒充观测'}
    return {
        'available': True,
        'stations': stations,
        'availableStations': len(available),
        'worst': max(available, key=lambda s: s['probabilities']['unsafe']),
        'observedAt': max((s.get('observedAt') or '') for s in available),
        'coverageNote': '仅 3 个机场观测站（沈阳/长春/哈尔滨），站间距 80–150 km；'
                        '走廊值由 1/d² 反距离插值得到，误差带随站距增大',
        'independenceAssumption': '低能见度与强阵风按独立事件合并：p=1-(1-p_vis)(1-p_gust)',
    }
