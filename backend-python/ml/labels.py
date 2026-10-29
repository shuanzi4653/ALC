from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

LEVELS = ('FIT', 'CAUTION', 'DANGER', 'BAN')
_SEVERITY = {name: i for i, name in enumerate(LEVELS)}

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / 'config' / 'labels-v1.json'

REQUIRED_KEYS = ('windSpeed', 'windGust', 'precipMmh', 'visibilityM')

class LabelSpec:
    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw
        self.version = str(raw.get('version') or 'v1')
        self.factors = {f['key']: f for f in raw.get('factors') or []}
        self.combination = raw.get('combinationRules') or []

    def band_of(self, key: str, value: Optional[float]) -> Optional[str]:
        """返回该要素单独给出的档位；缺席返回 None（不判、不当 0）。"""
        spec = self.factors.get(key)
        if spec is None or value is None:
            return None
        bands = spec.get('bands') or {}
        direction = spec.get('direction')
        if direction == 'high':
            if value > float(bands['danger']):
                return 'BAN'
            if value > float(bands['caution']):
                return 'DANGER'
            if value > float(bands['fit']):
                return 'CAUTION'
            return 'FIT'
        if direction == 'low':
            if value < float(bands['danger']):
                return 'BAN'
            if value < float(bands['caution']):
                return 'DANGER'
            if value < float(bands['fit']):
                return 'CAUTION'
            return 'FIT'
        if direction == 'none':
            return None
        if direction == 'range':
            lo_ban, hi_ban = float(bands['banLow']), float(bands['banHigh'])
            lo_warn, hi_warn = float(bands['warnLow']), float(bands['warnHigh'])
            if value < lo_ban or value > hi_ban:
                return 'BAN'
            if value < lo_warn or value > hi_warn:
                return 'CAUTION'
            return 'FIT'
        raise ValueError('未知 direction：%s' % direction)

    def combination_level(self, snapshot: Dict[str, Any]) -> Optional[str]:
        """返回组合规则给出的档位（取其中更坏的一个）。"""
        candidates: List[str] = []

        temp = _num(snapshot.get('tempC'))
        rh = _num(snapshot.get('rhPct'))
        if temp is not None and rh is not None and temp < 2.0 and rh >= 90.0:
            candidates.append('CAUTION')

        wind = _num(snapshot.get('windSpeed'))
        gust = _num(snapshot.get('windGust'))
        if wind is not None and gust is not None and wind >= 3.0:
            spec = next((c for c in self.combination if c.get('key') == 'gustFactor'), None)
            if spec:
                ratio = gust / wind
                if ratio > float(spec['dangerAt']):
                    candidates.append('DANGER')
                elif ratio > float(spec['cautionAt']):
                    candidates.append('CAUTION')

        if not candidates:
            return None
        return max(candidates, key=lambda lv: _SEVERITY[lv])

    def label(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        present = [k for k in REQUIRED_KEYS if _num(snapshot.get(k)) is not None]
        missing = [k for k in REQUIRED_KEYS if k not in present]
        if len(present) < 2:
            return {
                'level': 'SKIP',
                'severity': -1,
                'bands': {},
                'missing': missing,
                'reason': '必需要素缺席 %d 个（<2 个可得）—— 宁可不标，不猜' % len(missing),
            }

        bands: Dict[str, str] = {}
        for key in self.factors:
            band = self.band_of(key, _num(snapshot.get(key)))
            if band is not None:
                bands[key] = band

        candidates: List[str] = list(bands.values())
        combo = self.combination_level(snapshot)
        if combo:
            bands['_combination'] = combo
            candidates.append(combo)

        worst = max(candidates, key=lambda lv: _SEVERITY[lv]) if candidates else 'FIT'
        return {
            'level': worst,
            'severity': _SEVERITY[worst],
            'bands': bands,
            'missing': missing,
            'reason': _explain(worst, bands),
        }

def _explain(level: str, bands: Dict[str, str]) -> str:
    if level == 'FIT':
        return '各要素均在适飞区间'
    hits = [k for k, v in bands.items() if v == level and not k.startswith('_')]
    if not hits and level == 'CAUTION' and '_combination' in bands:
        return '结冰风险（低温高湿）'
    return '；'.join(hits) + ' 落入 %s 段' % level

def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None

_spec_cache: Dict[str, LabelSpec] = {}

def load_spec(path: Optional[Path] = None) -> LabelSpec:
    p = Path(path or DEFAULT_PATH)
    key = str(p)
    if key not in _spec_cache:
        with open(p, encoding='utf-8') as fh:
            _spec_cache[key] = LabelSpec(json.load(fh))
    return _spec_cache[key]
