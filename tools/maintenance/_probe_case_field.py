# -*- coding: utf-8 -*-
"""看案例帧下三站各自的概率（诊断"雾在观测里，但走廊概率不高"这件事）。"""
from __future__ import annotations

import json

from traffic import v2

payload = v2.field(case_id='fog-20250105')
print('available:', payload.get('available'), 'flags:', payload.get('qualityFlags'))
for station in payload.get('stations') or []:
    print(json.dumps({
        'station': station.get('station'),
        'available': station.get('available'),
        'observedAt': station.get('observedAt'),
        'observed': station.get('observed'),
        'probabilities': station.get('probabilities'),
        'missing': station.get('missing'),
    }, ensure_ascii=False))
