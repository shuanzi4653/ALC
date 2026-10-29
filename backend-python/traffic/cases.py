# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
CASE_DIR = ROOT / 'data' / 'traffic' / 'cases'

_lock = threading.Lock()
_cache: Dict[str, Dict[str, Any]] = {}

KNOWN_CASES = (
    {'caseId': 'fog-20250105',
     'label': '历史回放 · 2025-01-05 沈阳大雾',
     'timeBase': '2025-01-05T00:00:00Z',
     'why': '沈阳 ZYTX 能见度降到 997.8 m（不可飞），云底 152 m，露点差 1 ℃；'
            '同一小时哈尔滨 1593 m、长春 2993 m、大连 2800 m，四站都进了注意级。'},
)

def list_cases() -> List[Dict[str, Any]]:
    return [dict(item) for item in KNOWN_CASES]

def load(case_id: str) -> Optional[Dict[str, Any]]:
    """读一个案例。未知 id 返回 `None` —— 不猜一个相近的案例顶上。"""
    key = str(case_id or '').strip()
    if not key:
        return None
    with _lock:
        if key in _cache:
            return _cache[key]
    path = CASE_DIR / ('%s.json' % key)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding='utf-8'))
    if payload.get('caseId') != key:
        raise ValueError('案例文件名与 caseId 不一致：%s != %s' % (path.name, payload.get('caseId')))
    with _lock:
        _cache[key] = payload
    return payload

def station_histories(case_id: str) -> Dict[str, List[Dict[str, Any]]]:
    payload = load(case_id)
    if payload is None:
        return {}
    histories = payload.get('history') or {}
    return {station: list(rows) for station, rows in histories.items()}

def frame_at(case_id: str, iso: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """逐时帧：给 `iso` 就给最近的一帧，不给就给基准帧。"""
    payload = load(case_id)
    if payload is None:
        return None
    frames = payload.get('frames') or []
    if not frames:
        return None
    if not iso:
        return frames[0]
    return min(frames, key=lambda frame: _gap(frame['t'], iso))

def _gap(left: str, right: str) -> float:
    from datetime import datetime

    def parse(text: str) -> datetime:
        return datetime.strptime(text[:19], '%Y-%m-%dT%H:%M:%S')

    return abs((parse(left) - parse(right)).total_seconds())

def frame_at_minute(case_id: str, minute: float) -> Optional[Dict[str, Any]]:
    payload = load(case_id)
    if payload is None:
        return None
    frames = payload.get('frames') or []
    if not frames:
        return None
    base = frames[0].get('t')
    if not base:
        return None
    target = float(minute)

    def lag(frame: Dict[str, Any]) -> float:
        return abs(_gap(base, frame['t']) / 60.0 - target)

    best = min(frames, key=lag)
    return dict(best, frameLagMinutes=round(lag(best), 1))

def describe(case_id: str) -> Dict[str, Any]:
    """给接口用的元信息：不含观测数值，只说这份回放是什么、从哪来。"""
    payload = load(case_id)
    if payload is None:
        return {'caseId': case_id, 'available': False}
    return {'caseId': payload.get('caseId'), 'available': True,
            'label': payload.get('label'), 'kind': payload.get('kind'),
            'timeBase': payload.get('timeBase'), 'displayTz': payload.get('displayTz'),
            'window': payload.get('window'), 'stations': payload.get('stations'),
            'source': payload.get('source'), 'note': payload.get('note'),
            'frames': len(payload.get('frames') or [])}
