# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import math
import re
import httpx
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ml import nowcast
from weather import metar_history, om_forecast

logger = logging.getLogger(__name__)
from weather.geometry import project, unproject

from . import cases as traffic_cases
from . import service as traffic

ROOT = Path(__file__).resolve().parents[2]
DECISION_DIR = ROOT / '.run' / 'traffic' / 'decisions'

STATIONS = metar_history.STATION_INFO

STEP_KM = 5.0
LOW_CONFIDENCE_KM = 250.0
SIGMA_FLOOR = 0.02
SIGMA_CAP = 0.15
SIGMA_BASE = 0.05
SIGMA_PER_KM = 0.02

LOSS_PARAMS = {
    'conservative': {'incident': 20000.0, 'delay': 1.0, 'reroute': 25.0, 'cancel': 180.0},
    'balanced': {'incident': 10000.0, 'delay': 1.0, 'reroute': 25.0, 'cancel': 180.0},
    'efficiency': {'incident': 4000.0, 'delay': 1.0, 'reroute': 25.0, 'cancel': 180.0},
}
DELAY_STEP_MIN = 40

CANCEL_BLOCK_P_ALT = 0.80

_lock = threading.Lock()
_field_cache: Dict[str, Any] = {'at': 0.0, 'value': None}
_prev_counts: Dict[str, Any] = {}
_sigma_cache: Dict[str, Any] = {'key': None, 'value': None}
_case_field_cache: Dict[str, Any] = {}

def _histories_at_minute(case_id: str, histories: Dict[str, List[Dict[str, Any]]],
                         minute: float) -> Dict[str, List[Dict[str, Any]]]:
    frame = traffic_cases.frame_at_minute(case_id, minute)
    if not frame:
        return histories
    try:
        base_epoch = int(datetime.strptime(frame['t'][:19], '%Y-%m-%dT%H:%M:%S')
                         .replace(tzinfo=timezone.utc).timestamp())
    except (ValueError, KeyError, TypeError):
        return histories
    out = {}
    for station, rows in histories.items():
        obs = frame.get(station)
        if not rows or not isinstance(obs, dict):
            out[station] = rows
            continue
        merged = dict(rows[-1])
        merged.update({
            'visM': obs.get('visM'),
            'gustMs': obs.get('gustMs'),
            'cloudBaseM': obs.get('cloudBaseM'),
            'dewSpread': obs.get('dewSpread'),
            'timeUtc': frame['t'],
            'epoch': base_epoch,
            'visLowerBound': False,
            'visRaw': '',
        })
        out[station] = rows[:-1] + [merged]
    return out

def _case_field(case_id: str, minute: Optional[float] = None) -> Dict[str, Any]:
    now = time.monotonic()
    slot = (case_id, None if minute in (None, 0) else round(float(minute), 1))
    with _lock:
        cached = _case_field_cache.get(slot)
        if cached:
            return cached['value']
    histories = traffic_cases.station_histories(case_id)
    if slot[1] is not None:
        histories = _histories_at_minute(case_id, histories, slot[1])
    meta = traffic_cases.describe(case_id)
    if not histories or not meta.get('available'):
        payload = {'available': False, 'stations': [], 'reason': 'CASE_NOT_FOUND',
                   'caseId': case_id, 'qualityFlags': ['CASE_NOT_FOUND']}
    else:
        stations = [nowcast.predict_station(station, history)
                    for station, history in sorted(histories.items())]
        payload = nowcast.field(stations)
        payload['provider'] = 'AVIATION_WEATHER_CENTER'
        payload['dataType'] = 'STATION_OBSERVATION_METAR'
        payload['retrievedAt'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        payload['caseId'] = case_id
        payload['replay'] = meta
        payload['stationVisibility'] = [
            {'station': s['station'],
             'visM': (s.get('observed') or {}).get('visM'),
             'visLevel': _vis_level((s.get('observed') or {}).get('visM')),
             'observedAt': s.get('observedAt')}
            for s in stations if (s.get('observed') or {}).get('visM') is not None
        ]
        payload['qualityFlags'] = [
            'HISTORICAL_REPLAY',
            'ONLY_%d_AIRPORT_STATIONS' % len(histories),
            'IDW_INTERPOLATION_1_OVER_D2',
            'SIGMA_FROM_LOOCV_RESIDUALS',
            'VISIBILITY_LOWER_BOUND_WHEN_REPORTED_WITH_PLUS',
            'GUST_FALLBACK_TO_SUSTAINED_WIND_WHEN_NOT_REPORTED',
        ]
    with _lock:
        _case_field_cache[slot] = {'at': now, 'value': payload}
    return payload

def field(force: bool = False, case_id: Optional[str] = None,
          minute: Optional[float] = None) -> Dict[str, Any]:
    if case_id:
        return _case_field(case_id, minute)
    now = time.monotonic()
    with _lock:
        if not force and _field_cache['value'] is not None and now - _field_cache['at'] < 60:
            return _field_cache['value']
    histories = metar_history.station_histories(hours=7, force=force)
    stations = [nowcast.predict_station(station, history) for station, history in histories.items()]
    payload = nowcast.field(stations)
    payload['provider'] = 'AVIATION_WEATHER_CENTER'
    payload['dataType'] = 'STATION_OBSERVATION_METAR'
    payload['retrievedAt'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    payload['qualityFlags'] = [
        'ONLY_THREE_AIRPORT_STATIONS',
        'IDW_INTERPOLATION_1_OVER_D2',
        'SIGMA_FROM_LOOCV_RESIDUALS',
        'VISIBILITY_LOWER_BOUND_WHEN_REPORTED_WITH_PLUS',
        'GUST_FALLBACK_TO_SUSTAINED_WIND_WHEN_NOT_REPORTED',
    ]
    with _lock:
        _field_cache.update({'at': now, 'value': payload})
    return payload

def _station_xy() -> Dict[str, Tuple[float, float]]:
    out = {}
    for station, info in STATIONS.items():
        x, y = project((info['lon'], info['lat']))
        out[station] = (x, y)
    return out

def _loocv_sigma(field_payload: Dict[str, Any]) -> Dict[str, Any]:
    stations = [s for s in field_payload.get('stations') or [] if s.get('available')]
    if len(stations) < 3:
        return {'sigma': 0.10, 'n': 0, 'residuals': [], 'method': 'FALLBACK_FIXED',
                'note': '可用站少于 3 个，留一站交叉验证无法进行；取固定 0.10 并如实标注'}
    key = field_payload.get('observedAt') or field_payload.get('retrievedAt')
    with _lock:
        if _sigma_cache['key'] == key and _sigma_cache['value'] is not None:
            return _sigma_cache['value']
    xy = _station_xy()
    residuals = []
    for held in stations:
        hx, hy = xy[held['station']]
        total, weighted = 0.0, 0.0
        for other in stations:
            if other['station'] == held['station']:
                continue
            ox, oy = xy[other['station']]
            d = max(math.hypot(hx - ox, hy - oy) / 1000.0, 1.0)
            w = 1.0 / d ** 2
            total += w
            weighted += w * other['probabilities']['unsafe']
        predicted = weighted / (total or 1.0)
        actual = held['probabilities']['unsafe']
        residuals.append({'station': held['station'], 'predicted': round(predicted, 4),
                          'actual': round(actual, 4), 'residual': round(predicted - actual, 4)})
    rms = math.sqrt(sum(r['residual'] ** 2 for r in residuals) / len(residuals))
    value = {'sigma': round(min(SIGMA_CAP, max(SIGMA_FLOOR, rms)), 4), 'n': len(residuals),
             'residuals': residuals, 'method': 'LOOCV_RESIDUAL_RMS',
             'note': '留一站交叉验证残差均方根；上限 %.2f、下限 %.2f 是判据' % (SIGMA_CAP, SIGMA_FLOOR)}
    with _lock:
        _sigma_cache.update({'key': key, 'value': value})
    return value

def _visibility_thresholds() -> Dict[str, float]:
    global _VIS_CACHE
    if _VIS_CACHE is not None:
        return _VIS_CACHE
    ban, warn = 1000.0, 5000.0
    try:
        import json as _json
        rules = _json.loads((ROOT / 'config' / 'rules-v1.json').read_text(encoding='utf-8'))
        for group in rules.get('groups') or []:
            for rule in group.get('rules') or []:
                if rule.get('key') == 'visibilityM':
                    ban = float(rule.get('banValue') or ban)
                    warn = float(rule.get('warnValue') or warn)
    except Exception as exc:  # noqa: BLE001
        logger.warning('能见度阈值读取失败，本次回落到内置默认值 ban=%s warn=%s：%s',
                       ban, warn, exc)
    _VIS_CACHE = {'ban': ban, 'warn': warn}
    return _VIS_CACHE

_VIS_CACHE = None

def _vis_level(vis_m) -> Optional[str]:
    """能见度 -> 三档。`None` 就是 `None`，**不回落成"能见"**。"""
    if vis_m is None:
        return None
    limits = _visibility_thresholds()
    if vis_m <= limits['ban']:
        return 'BAN'
    if vis_m <= limits['warn']:
        return 'CAUTION'
    return 'CLEAR'

def _idw_visibility(x: float, y: float, field_payload: Dict[str, Any]) -> Dict[str, Any]:
    stations = [s for s in field_payload.get('stations') or []
                if s.get('available') and ((s.get('observed') or {}).get('visM') is not None)]
    if not stations:
        return {'visM': None, 'visLevel': None, 'nearestKm': None, 'contributors': [],
                'visLowerBound': False, 'visRaw': ''}
    xy = _station_xy()
    ranked = []
    for s in stations:
        point = xy.get(s['station'])
        if point is None:
            continue
        ranked.append((math.hypot(x - point[0], y - point[1]) / 1000.0, s))
    if not ranked:
        return {'visM': None, 'visLevel': None, 'nearestKm': None, 'contributors': [],
                'visLowerBound': False, 'visRaw': ''}
    ranked.sort(key=lambda item: item[0])
    picked = ranked[:3]
    weights = [1.0 / max(d, 1.0) ** 2 for d, _ in picked]
    total = sum(weights) or 1.0
    value = sum(w * s['observed']['visM'] for w, (_, s) in zip(weights, picked)) / total
    nearest_vis = ranked[0][1]['observed']['visM']
    nearest_observed = ranked[0][1]['observed']
    return {
        'visM': nearest_vis,
        'visLevel': _vis_level(nearest_vis),
        'visLowerBound': bool(nearest_observed.get('visLowerBound')),
        'visRaw': nearest_observed.get('visRaw') or '',
        'visMidpointM': round(value, 0),
        'nearestKm': round(ranked[0][0], 1),
        'nearestStation': ranked[0][1]['station'],
        'contributors': [{'station': s['station'], 'distanceKm': round(d, 1),
                          'visM': s['observed']['visM']} for d, s in picked],
    }

def _verdict_explain(row: Dict[str, Any]) -> Dict[str, Any]:
    verdict = row.get('verdict') or '可飞'
    source = row.get('verdictSource') or 'NONE'
    p_max = row.get('pMax')
    pct = '—' if p_max is None else '%.1f%%' % (p_max * 100)
    if source == 'PROBABILITY':
        text = ('观测判据未命中停飞阈值，最终判定来自概率档：不可飞概率 %s，'
                '达到停飞判据阈值 %.0f%%，因此判为「%s」。'
                % (pct, P_PROB_BLOCK * 100, verdict))
    elif source == 'OBSERVATION':
        text = ('最终判定来自**观测判据**（此刻最近站实测已越阈值），与概率档无关：'
                '概率 %s 只是未来的估算。' % pct)
    elif source == 'BOTH':
        text = ('观测判据与概率档同时命中（概率 %s），两档结论一致，因此判为「%s」。'
                % (pct, verdict))
    else:
        text = ('观测判据全部满足，概率 %s 也低于停飞阈值 %.0f%%，因此判为「%s」。'
                % (pct, P_PROB_BLOCK * 100, verdict))
    return {
        'source': source,
        'text': text,
        'blockThreshold': P_PROB_BLOCK,
        'watchThreshold': P_PROB_WATCH,
        'divergent': bool(row.get('verdictObservation') != row.get('verdict')),
        'observationVerdict': row.get('verdictObservation'),
        'probabilityVerdict': row.get('verdictProbability'),
    }

def _idw(x: float, y: float, field_payload: Dict[str, Any]) -> Dict[str, Any]:
    """1/d² 反距离加权。返回概率、σ、最近站距与参与加权的站点。"""
    stations = [s for s in field_payload.get('stations') or [] if s.get('available')]
    if not stations:
        return {'p': None, 'sigma': None, 'nearestKm': None, 'contributors': []}
    xy = _station_xy()
    ranked = []
    for s in stations:
        sx, sy = xy[s['station']]
        d = math.hypot(x - sx, y - sy) / 1000.0
        ranked.append((d, s))
    ranked.sort(key=lambda item: item[0])
    picked = ranked[:3]
    weights = [1.0 / max(d, 1.0) ** 2 for d, _ in picked]
    total = sum(weights) or 1.0
    p = sum(w * s['probabilities']['unsafe'] for w, (_, s) in zip(weights, picked)) / total
    nearest = picked[0][0]
    sigma = min(SIGMA_CAP, _loocv_sigma(field_payload)['sigma'] * (1.0 + nearest / 120.0))
    return {
        'p': round(p, 4), 'sigma': round(sigma, 4), 'nearestKm': round(nearest, 1),
        'contributors': [{'station': s['station'], 'distanceKm': round(d, 1),
                          'p': s['probabilities']['unsafe']} for d, s in picked],
    }

def _resample(points: List[Tuple[float, float]], step_km: float = STEP_KM) -> List[Dict[str, float]]:
    """沿折线每 `step_km` 取一点（含首尾）。"""
    if len(points) < 2:
        return [{'km': 0.0, 'x': points[0][0], 'y': points[0][1]}] if points else []
    out = [{'km': 0.0, 'x': points[0][0], 'y': points[0][1]}]
    travelled = 0.0
    next_at = step_km * 1000.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        if seg <= 0:
            continue
        while next_at <= travelled + seg:
            ratio = (next_at - travelled) / seg
            out.append({'km': round(next_at / 1000.0, 2),
                        'x': x1 + ratio * (x2 - x1), 'y': y1 + ratio * (y2 - y1)})
            next_at += step_km * 1000.0
        travelled += seg
    last = points[-1]
    if out[-1]['x'] != last[0] or out[-1]['y'] != last[1]:
        out.append({'km': round(travelled / 1000.0, 2), 'x': last[0], 'y': last[1]})
    return out

def _route_points(route: Dict[str, Any]) -> List[Tuple[float, float]]:
    raw = route.get('referencePath') or route.get('path') or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = []
    return [(float(p[0]), float(p[1])) for p in raw if isinstance(p, (list, tuple)) and len(p) >= 2]

def _elevation(route_id: str) -> Optional[List[float]]:
    path = ROOT / 'data' / 'traffic' / 'corridor-elevation.json'
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except ValueError:
        return None
    return payload.get(route_id)

def _terrain_factor(dem: Optional[float], station_mean: Optional[float]) -> Tuple[float, str]:
    if dem is None or station_mean is None:
        return 1.0, 'NO_DEM'
    factor = 1.0 - 0.08 * (dem - station_mean) / 100.0
    return max(0.6, min(1.1, factor)), 'APPLIED'

def _station_mean_elevation(field_payload: Dict[str, Any]) -> Optional[float]:
    values = []
    for s in field_payload.get('stations') or []:
        info = STATIONS.get(s['station']) or {}
        if info:
            values.append({'ZYTX': 60.0, 'ZYCC': 215.0, 'ZYHB': 139.0}.get(s['station']))
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None

def _corridor_row(route: Dict[str, Any], field_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    points = _route_points(route)
    if len(points) < 2:
        return None
    samples = _resample(points)
    dems = _elevation(route['id'])
    mean_elev = _station_mean_elevation(field_payload)
    probs = []
    sigmas = []
    nearest = []
    for index, sample in enumerate(samples):
        estimate = _idw(sample['x'], sample['y'], field_payload)
        if estimate['p'] is None:
            return None
        dem = dems[index] if dems and index < len(dems) else None
        factor, _ = _terrain_factor(dem, mean_elev)
        probs.append(min(1.0, estimate['p'] * factor))
        sigmas.append(estimate['sigma'])
        nearest.append(estimate['nearestKm'])
    max_p = max(probs)
    mean_p = sum(probs) / len(probs)
    mid = samples[len(samples) // 2]
    visibility = _idw_visibility(mid['x'], mid['y'], field_payload)
    prob_verdict = ('不可飞' if max_p >= P_PROB_BLOCK else '需谨慎' if max_p >= P_PROB_WATCH else '可飞')
    obs_level = _nearest_observation_level(route, field_payload)
    obs_verdict = {'BAN': '不可飞', 'CAUTION': '需谨慎'}.get(obs_level, '可飞')
    order = {'可飞': 0, '需谨慎': 1, '不可飞': 2}
    verdict = prob_verdict if order[prob_verdict] >= order[obs_verdict] else obs_verdict
    return {
        'corridorId': route['id'],
        'name': route['name'],
        'mode': route['mode'],
        'fromCity': route['fromCity'], 'toCity': route['toCity'],
        'lengthKm': samples[-1]['km'],
        'samples': [{'km': s['km'], 'p': round(p, 4), 'sigma': sigma,
                     'lng': round(unproject((s['x'], s['y']))[0], 5),
                     'lat': round(unproject((s['x'], s['y']))[1], 5)}
                    for s, p, sigma in zip(samples, probs, sigmas)],
        'pMax': round(max_p, 4), 'pMean': round(mean_p, 4),
        'sigmaMean': round(sum(sigmas) / len(sigmas), 4),
        'nearestStationKm': round(min(nearest), 1),
        'confidence': 'LOW' if min(nearest) > LOW_CONFIDENCE_KM else 'OK',
        'verdict': verdict,
        'visM': visibility['visM'],
        'visLevel': visibility['visLevel'],
        'visLowerBound': bool(visibility.get('visLowerBound')),
        'visRaw': visibility.get('visRaw') or '',
        'visMidpointM': visibility.get('visMidpointM'),
        'visNearestKm': visibility['nearestKm'],
        'visNearestStation': visibility.get('nearestStation'),
        'verdictProbability': prob_verdict,
        'verdictObservation': obs_verdict,
        'verdictSource': ('OBSERVATION' if order[obs_verdict] > order[prob_verdict]
                          else 'PROBABILITY' if order[prob_verdict] > order[obs_verdict]
                          else 'BOTH' if verdict != '可飞' else 'NONE'),
        'terrainCorrection': 'APPLIED' if dems else 'NO_DEM',
    }

def _pct_text(p: Optional[float]) -> str:
    if p is None:
        return '—'
    value = p * 100.0
    if value <= 0:
        return '0'
    if value < 0.1:
        return '<0.1'
    if value < 1:
        return '%.1f' % value
    return '%d' % round(value)

def _mode_total(mode: str) -> int:
    return sum(1 for r in traffic.network().get('routes') or [] if r.get('mode') == mode)

def _vis_display(vis_m: float, lower: bool, raw: str) -> str:
    text = ('%.0f m' % vis_m) if vis_m < 1000 else ('%.1f km' % (vis_m / 1000.0))
    return ('≥ %s（%s 为下界）' % (text, raw or '报文')) if lower else text

def _nearest_observation_level(route: Dict[str, Any], field_payload: Dict[str, Any]) -> Optional[str]:
    points = _route_points(route)
    if not points:
        return None
    centre = points[len(points) // 2]
    xy = _station_xy()
    stations = [s for s in field_payload.get('stations') or [] if s.get('available')]
    if not stations:
        return None
    nearest = min(stations, key=lambda s: math.hypot(centre[0] - xy[s['station']][0],
                                                    centre[1] - xy[s['station']][1]))
    level = nearest.get('levelObservation')
    if level:
        return level
    return nowcast.observation_level(nearest.get('observed') or {})

def corridors(limit: Optional[int] = 10, mode: str = 'CAR',
              case_id: Optional[str] = None,
              minute: Optional[float] = None) -> Dict[str, Any]:
    field_payload = field(case_id=case_id, minute=minute)
    routes = [r for r in traffic.network().get('routes') or [] if r.get('mode') == mode]
    rows = [row for row in (_corridor_row(r, field_payload) for r in routes) if row]
    rows.sort(key=lambda r: r['pMax'], reverse=True)
    taken = rows if limit is None else rows[:max(1, limit)]
    return {
        'status': 'OK',
        'generatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'observation': {
            'available': field_payload.get('available'),
            'dataType': field_payload.get('dataType'),
            'observedAt': field_payload.get('observedAt'),
            'stations': [{'station': s['station'], 'available': s.get('available'),
                          'lat': (STATIONS.get(s['station']) or {}).get('lat'),
                          'lon': (STATIONS.get(s['station']) or {}).get('lon'),
                          'observedAt': s.get('observedAt'),
                          'p': (s.get('probabilities') or {}).get('unsafe'),
                          'level': s.get('level'),
                          'observed': s.get('observed')} for s in field_payload.get('stations') or []],
            'coverageNote': field_payload.get('coverageNote'),
            'qualityFlags': field_payload.get('qualityFlags'),
        },
        'total': len(rows),
        'mode': mode,
        'modeTotal': len(rows),
        'returned': len(taken),
        'items': taken,
    }

def _extension_curve(field_payload: Dict[str, Any], centre_xy: Tuple[float, float]) -> List[Dict[str, Any]]:
    tables = (nowcast.metrics() or {}).get('omProbability') or {}
    hours = om_forecast.station_hours(hours=7)
    if not tables or not any(hours.values()):
        return []
    xy = _station_xy()
    out = []
    for index in range(7):
        weighted = {'vis': 0.0, 'gust': 0.0}
        total = 0.0
        detail = []
        for station, series in hours.items():
            if index >= len(series):
                continue
            row = series[index]
            sx, sy = xy[station]
            distance = max(math.hypot(centre_xy[0] - sx, centre_xy[1] - sy) / 1000.0, 1.0)
            weight = 1.0 / distance ** 2
            p_vis = _table_prob(tables.get('vis'), 'vis', row.get('visM'))
            p_gust = _table_prob(tables.get('gust'), 'gust', row.get('gustMs'))
            if p_vis is None or p_gust is None:
                continue
            weighted['vis'] += weight * p_vis
            weighted['gust'] += weight * p_gust
            total += weight
            detail.append({'station': station, 'distanceKm': round(distance, 1),
                           'visM': row.get('visM'), 'gustMs': row.get('gustMs'),
                           'pVis': p_vis, 'pGust': p_gust})
        if total == 0:
            continue
        p_vis = weighted['vis'] / total
        p_gust = weighted['gust'] / total
        out.append({
            'index': index,
            'timeUtc': (hours.get('ZYTX') or [{}] * 8)[index].get('timeUtc') if index < len(hours.get('ZYTX') or []) else None,
            'p': round(1 - (1 - p_vis) * (1 - p_gust), 4),
            'pVis': round(p_vis, 4), 'pGust': round(p_gust, 4),
            'source': 'MODEL_EXTENSION',
            'stations': detail,
        })
    return out

def _table_prob(table: Optional[Dict[str, Any]], _key: str, value: Optional[float]) -> Optional[float]:
    if not table or value is None:
        return None
    bins, freq = table.get('bins') or [], table.get('freq') or []
    for i in range(len(bins) - 1):
        if bins[i] <= value < bins[i + 1]:
            if freq[i] is None:
                return None
            return float(freq[i])
    return None

def _deduction(field_payload: Dict[str, Any], row: Dict[str, Any], route: Dict[str, Any],
               centre: Tuple[float, float],
               alternatives: List[Dict[str, Any]]) -> Dict[str, Any]:
    xy = _station_xy()
    stations = [s for s in field_payload.get('stations') or [] if s.get('available')]
    ranked = []
    for station in stations:
        sx, sy = xy[station['station']]
        distance = math.hypot(centre[0] - sx, centre[1] - sy) / 1000.0
        ranked.append((distance, station))
    ranked.sort(key=lambda item: item[0])
    picked = ranked[:3]
    raw = [1.0 / max(d, 1.0) ** 2 for d, _ in picked]
    total = sum(raw) or 1.0
    station_rows = []
    for (distance, station), weight in zip(picked, raw):
        observed = station.get('observed') or {}
        info = STATIONS.get(station['station']) or {}
        station_rows.append({
            'station': station['station'],
            'name': info.get('name', station['station']),
            'lng': info.get('lon'), 'lat': info.get('lat'),
            'distanceKm': round(distance, 1),
            'weight': round(weight / total, 3),
            'visM': observed.get('visM'),
            'gustMs': observed.get('gustMs'),
            'cloudBaseM': observed.get('cloudBaseM'),
            'level': station.get('level'),
            'pUnsafe': (station.get('probabilities') or {}).get('unsafe'),
            'observedAt': station.get('observedAt'),
        })
    p_vis = sum(w * ((st.get('probabilities') or {}).get('lowVis') or 0.0)
                for w, (_, st) in zip(raw, picked)) / total
    p_gust = sum(w * ((st.get('probabilities') or {}).get('gust') or 0.0)
                 for w, (_, st) in zip(raw, picked)) / total
    params = dict(LOSS_PARAMS['balanced'])
    alt_p = min([a['pMax'] for a in alternatives], default=None)
    decision = _decision(p_unsafe=row['pMax'], p_delay=None, p_alt=alt_p,
                         params=params,
                         observed_ban=(row.get('verdictObservation') == '不可飞'))
    decision.update({
        'params': params,
        'pUnsafe': round(row['pMax'], 4),
        'pAlt': None if alt_p is None else round(alt_p, 4),
        'altCorridorId': (min(alternatives, key=lambda a: a['pMax'])['corridorId']
                          if alternatives else None),
    })
    return {
        'midpoint': {'km': round(row['lengthKm'] / 2.0, 1),
                     'lng': round(unproject(centre)[0], 5),
                     'lat': round(unproject(centre)[1], 5)},
        'stations': station_rows,
        'midpointProbs': {
            'pVis': round(p_vis, 4),
            'pGust': round(p_gust, 4),
            'pUnsafe': round(1 - (1 - p_vis) * (1 - p_gust), 4),
            'pMax': round(row['pMax'], 4),
            'sigma': round(row['sigmaMean'], 4),
            'confidence': row['confidence'],
            'nearestKm': row['nearestStationKm'],
        },
        'decision': decision,
    }

def corridor(route_id: str, case_id: Optional[str] = None,
             minute: Optional[float] = None) -> Dict[str, Any]:
    field_payload = field(case_id=case_id, minute=minute)
    route = next((r for r in traffic.network().get('routes') or [] if r['id'] == route_id), None)
    if route is None:
        return {'status': 'NOT_FOUND', 'corridorId': route_id}
    row = _corridor_row(route, field_payload)
    if row is None:
        return {'status': 'NO_OBSERVATION', 'corridorId': route_id}
    points = _route_points(route)
    centre = points[len(points) // 2]
    model_now = row['pMax']
    stride = max(1, len(points) // 8)
    path = [{'lng': round(unproject(p)[0], 5), 'lat': round(unproject(p)[1], 5)}
            for p in points[::stride]]
    if path and path[-1] != {'lng': round(unproject(points[-1])[0], 5),
                             'lat': round(unproject(points[-1])[1], 5)}:
        path.append({'lng': round(unproject(points[-1])[0], 5),
                     'lat': round(unproject(points[-1])[1], 5)})
    if case_id:
        hourly = []
        for index in range(7):
            frame_field = field(case_id=case_id, minute=index * 60.0)
            frame_row = _corridor_row(route, frame_field)
            hourly.append({'index': index,
                           'p': frame_row['pMax'] if frame_row else None,
                           'source': 'MODEL',
                           'frameObserved': True,
                           'timeUtc': frame_field.get('observedAt')})
    else:
        curve = _extension_curve(field_payload, centre)
        hourly = []
        for index in range(7):
            if index <= 3:
                hourly.append({'index': index, 'p': model_now, 'source': 'MODEL'})
            else:
                extension = next((c for c in curve if c['index'] == index), None)
                hourly.append({'index': index,
                               'p': extension['p'] if extension else None,
                               'source': 'MODEL_EXTENSION' if extension else 'UNAVAILABLE'})
    window = []
    start = None
    for item in hourly:
        if item['p'] is not None and item['p'] < 0.5:
            start = item['index'] if start is None else start
        elif start is not None:
            window.append([start, item['index'] - 1]); start = None
    if start is not None:
        window.append([start, hourly[-1]['index']])
    alternatives = []
    for other in traffic.network().get('routes') or []:
        if other['id'] == route_id or other.get('mode') != route.get('mode'):
            continue
        if {other.get('fromCity'), other.get('toCity')} & {route.get('fromCity'), route.get('toCity')}:
            candidate = _corridor_row(other, field_payload)
            if candidate:
                alternatives.append({'corridorId': candidate['corridorId'], 'name': candidate['name'],
                                     'pMax': candidate['pMax'], 'lengthKm': candidate['lengthKm']})
    alternatives.sort(key=lambda a: a['pMax'])
    return {
        'status': 'OK',
        'corridorId': row['corridorId'], 'name': row['name'],
        'fromCity': row['fromCity'], 'toCity': row['toCity'],
        'lengthKm': row['lengthKm'],
        'pMax': row['pMax'], 'pMean': row['pMean'], 'sigmaMean': row['sigmaMean'],
        'nearestStationKm': row['nearestStationKm'], 'confidence': row['confidence'],
        'verdict': row['verdict'],
        'verdictProbability': row.get('verdictProbability'),
        'verdictObservation': row.get('verdictObservation'),
        'verdictSource': row.get('verdictSource'),
        'samples': row['samples'],
        'hourly': hourly, 'window': window,
        'alternatives': alternatives[:3],
        'criteria': (_criteria(field_payload, points[len(points) // 2])
                     + [_probability_criterion(row['pMax'], row['confidence'],
                                               row['nearestStationKm'])]),
        'verdictExplain': _verdict_explain(row),
        'path': path,
        'deduction': _deduction(field_payload, row, route, centre, alternatives),
        'observation': {
            'observedAt': field_payload.get('observedAt'),
            'dataType': field_payload.get('dataType'),
            'stations': [{'station': st['station'],
                          'name': (STATIONS.get(st['station']) or {}).get('name', st['station']),
                          'lng': (STATIONS.get(st['station']) or {}).get('lon'),
                          'lat': (STATIONS.get(st['station']) or {}).get('lat'),
                          'available': st.get('available'),
                          'level': st.get('level'),
                          'observedAt': st.get('observedAt'),
                          'observed': st.get('observed')}
                         for st in field_payload.get('stations') or []],
        },
        'terrainCorrection': row['terrainCorrection'],
        'assumptions': {
            'interpolation': '1/d² 反距离加权，取最近 3 站',
            'sigma': 'σ = 留一站交叉验证残差 RMS × (1 + 最近站距/120 km)，上限 0.15',
            'independence': 'p = 1-(1-p_vis)(1-p_gust)',
            'extension': '3–6 h 由 Open-Meteo 逐时值按历史频率表映射，不是本模型',
        },
    }

def _first_hit_criterion(item: Dict[str, Any],
                         field_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    routes = {r['id']: r for r in traffic.network().get('routes') or []}
    route = routes.get(item.get('corridorId'))
    if not route:
        return None
    points = _route_points(route)
    if not points:
        return None
    for row in _criteria(field_payload, points[len(points) // 2]):
        if row.get('passed') is False and row.get('value') is not None:
            return row
    return None

_PROBABILITY_DEFAULTS = {'block': 0.25, 'watch': 0.15, 'exposure': 0.25,
                         'humanReviewBelow': 0.65}

def _probability_settings() -> Dict[str, Any]:
    settings = dict(_PROBABILITY_DEFAULTS)
    try:
        payload = json.loads((Path(__file__).resolve().parents[2] / 'config'
                              / 'rules-v1.json').read_text(encoding='utf-8'))
        for key in _PROBABILITY_DEFAULTS:
            value = ((payload.get('probability') or {}).get(key))
            if isinstance(value, (int, float)):
                settings[key] = float(value)
    except (OSError, ValueError):
        pass
    return settings

PROBABILITY = _probability_settings()
P_PROB_BLOCK = PROBABILITY['block']
P_PROB_WATCH = PROBABILITY['watch']
P_PROB_EXPOSURE = PROBABILITY['exposure']
P_HUMAN_REVIEW_BELOW = PROBABILITY['humanReviewBelow']

def _hit_tier(passed, watch_passed) -> Optional[str]:
    if passed is None:
        return None
    if passed is False:
        return 'BLOCK'
    if watch_passed is False:
        return 'WATCH'
    return 'NONE'

def _criteria(field_payload: Dict[str, Any], centre: Tuple[float, float]) -> List[Dict[str, Any]]:
    """三条判据：能见度 / 阵风 / 云底高。值取最近站的实测，阈值写死在载荷里。"""
    xy = _station_xy()
    stations = [s for s in field_payload.get('stations') or [] if s.get('available')]
    if not stations:
        return []
    nearest = min(stations, key=lambda s: math.hypot(centre[0] - xy[s['station']][0],
                                                     centre[1] - xy[s['station']][1]))
    observed = nearest.get('observed') or {}
    rows = []
    vis = observed.get('visM')
    vis_lower = bool(observed.get('visLowerBound'))
    vis_raw = observed.get('visRaw') or ''
    vis_passed = None if vis is None else vis >= nowcast.LOW_VIS_M
    vis_watch_passed = None if vis is None else vis >= nowcast.CAUTION_VIS_M
    rows.append({'metric': '能见度', 'value': vis, 'unit': 'm', 'threshold': nowcast.LOW_VIS_M,
                 'operator': '<', 'passed': vis_passed,
                 'watchThreshold': nowcast.CAUTION_VIS_M, 'watchPassed': vis_watch_passed,
                 'hitTier': _hit_tier(vis_passed, vis_watch_passed),
                 'tierText': '停飞档 < %.1f km · 谨慎档 < %.1f km'
                             % (nowcast.LOW_VIS_M / 1000, nowcast.CAUTION_VIS_M / 1000),
                 'lowerBound': vis_lower,
                 'display': (None if vis is None else _vis_display(vis, vis_lower, vis_raw)),
                 'source': 'METAR %s 实测' % nearest['station'], 'observedAt': nearest.get('observedAt')})
    gust = observed.get('gustMs')
    gust_passed = None if gust is None else gust <= nowcast.GUST_LIMIT_MS
    rows.append({'metric': '阵风', 'value': gust, 'unit': 'm/s', 'threshold': nowcast.GUST_LIMIT_MS,
                 'operator': '>', 'passed': gust_passed,
                 'watchThreshold': None, 'watchPassed': None,
                 'hitTier': _hit_tier(gust_passed, None),
                 'tierText': '停飞档 > %.0f m/s（本项无谨慎档）' % nowcast.GUST_LIMIT_MS,
                 'source': 'METAR %s 实测' % nearest['station'], 'observedAt': nearest.get('observedAt')})
    cloud = observed.get('cloudBaseM')
    cloud_passed = None if cloud is None else cloud >= 300.0
    rows.append({'metric': '云底高', 'value': cloud, 'unit': 'm', 'threshold': 300.0,
                 'operator': '<', 'passed': cloud_passed,
                 'watchThreshold': None, 'watchPassed': None,
                 'hitTier': _hit_tier(cloud_passed, None),
                 'affectsVerdict': False,
                 'tierText': '停飞档 < %.0f m（本项无谨慎档，且不单独改变结论）' % 300.0,
                 'source': 'METAR %s 实测（晴空按 5000 m 哨兵）' % nearest['station'],
                 'observedAt': nearest.get('observedAt')})
    return rows

def _probability_criterion(p_max: Optional[float], confidence: str,
                           nearest_km: Optional[float]) -> Dict[str, Any]:
    if p_max is None:
        return {'metric': '概率档', 'value': None, 'unit': '', 'threshold': P_PROB_BLOCK,
                'operator': '≥', 'passed': None, 'kind': 'PROBABILITY',
                'watchThreshold': P_PROB_WATCH, 'watchPassed': None, 'hitTier': None,
                'tierText': '停飞档 ≥ %.0f%% · 谨慎档 ≥ %.0f%%' % (P_PROB_BLOCK * 100, P_PROB_WATCH * 100),
                'display': '未取得', 'source': '模型 v2 · 走廊中点 1/d² 插值',
                'note': '本帧没有可用的走廊概率，概率档弃权（这是"没算"，不是"没风险"）。'}
    triggered = p_max >= P_PROB_BLOCK
    watch_triggered = p_max >= P_PROB_WATCH
    return {'metric': '概率档', 'value': round(p_max, 4), 'unit': '', 'threshold': P_PROB_BLOCK,
            'operator': '≥', 'passed': not triggered, 'kind': 'PROBABILITY',
            'watchThreshold': P_PROB_WATCH, 'watchPassed': not watch_triggered,
            'hitTier': _hit_tier(not triggered, not watch_triggered),
            'tierText': '停飞档 ≥ %.0f%% · 谨慎档 ≥ %.0f%%' % (P_PROB_BLOCK * 100, P_PROB_WATCH * 100),
            'display': '%.1f%%（阈值 ≥ %.0f%%）' % (p_max * 100, P_PROB_BLOCK * 100),
            'source': '模型 v2 · 走廊中点 1/d² 插值（最近站距 %s km，置信 %s）'
                      % ('—' if nearest_km is None else nearest_km, confidence or '—'),
            'note': ('本走廊最终判定由**概率档**触发' if triggered
                     else '概率档未触发（距离阈值还差 %.1f 个百分点）'
                          % ((P_PROB_BLOCK - p_max) * 100))}

def _window_phrase(case_id: Optional[str], minute: Optional[float]) -> str:
    if not case_id:
        return '未来 3 小时内'
    try:
        meta = traffic_cases.describe(case_id)
        window = (meta or {}).get('window') or {}
        start, end = window.get('from'), window.get('to')
        if not start or not end:
            return '未来 3 小时内'
        span = int(round(traffic_cases._gap(start, end) / 60.0))
        now_minute = 0.0 if minute is None else float(minute)
        remain = span - now_minute
    except (ValueError, TypeError, KeyError, AttributeError):
        return '未来 3 小时内'
    if remain <= 0.5:
        return '案例推演已结束（T+%02d:00）' % int(round(span / 60.0))
    if remain < 180:
        return '剩余 %d 分钟内' % int(round(remain))
    return '未来 3 小时内'

def overview(seed: int = 42, scenario: str = 'live',
             case_id: Optional[str] = None,
             minute: Optional[float] = None) -> Dict[str, Any]:
    field_payload = field(case_id=case_id, minute=minute)
    snapshot = corridors(limit=None, case_id=case_id, minute=minute)
    items = snapshot['items']
    _window = _window_phrase(case_id, minute)
    high = [i for i in items if i['verdict'] == '不可飞']
    watch = [i for i in items if i['verdict'] == '需谨慎']
    metrics_payload = nowcast.metrics() or {}
    targets = metrics_payload.get('targets') or {}
    lead_obj = ((targets.get('vis3k') or {}).get('leadTime') or {})
    lead_gust_obj = ((targets.get('gust') or {}).get('leadTime') or {})
    lead = lead_obj.get('medianMin')
    lead_gust = lead_gust_obj.get('medianMin')
    lead_n = lead_obj.get('n') if lead is not None else lead_gust_obj.get('n')
    lead_baseline = ('离线回放：三站 METAR 的 %d 次跨阈事件中位值（%s）；本帧触发 %d 条，非本帧读数'
                     % (lead_n or 0,
                        '能见度 <3000 m' if lead is not None else '阵风 >10 m/s',
                        len(high)))
    _rank = {'不可飞': 2, '需谨慎': 1, '可飞': 0}
    worst = (sorted(items, key=lambda i: (_rank.get(i['verdict'], 0), i['pMax']), reverse=True)[0]
             if items else None)

    now_key = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H')
    previous = _prev_counts.get('high')
    delta = None if (previous is None or case_id) else len(high) - previous
    if scenario == 'live' and not case_id:
        _prev_counts['high'] = len(high)
        _prev_counts['at'] = now_key

    observation_ok = bool(field_payload.get('available')) and worst is not None
    conclusion = '机场站 METAR 观测暂不可用，本系统不给结论。'
    tone = 'unknown'
    if scenario == 'unknown':
        conclusion = ('气象通道中断：本情景不声明任何气象，全部班次暂停放行，'
                      '等待人工确认恢复。')
        tone = 'danger'
    elif scenario == 'clear':
        conclusion = ('本情景未声明气象（无气象声明 · 交通交汇），本轮不给气象结论；'
                      '走廊不可飞概率与观测档判定均未参与本次计划。')
        tone = 'info'
    elif observation_ok:
        if high:
            observed_ban = [i for i in high if i.get('verdictSource') == 'OBSERVATION']
            prob_ban = [i for i in high if (i.get('pMax') or 0) >= P_PROB_BLOCK]
            if observed_ban and not prob_ban:
                first = observed_ban[0]
                hit = _first_hit_criterion(first, field_payload)
                if hit is not None:
                    value_text = ('%.2f' % hit['value']) if isinstance(hit['value'], float) else str(hit['value'])
                    evidence = '%s %s %s（阈值 %s %s）' % (hit['metric'], value_text, hit['unit'],
                                                          hit['operator'], hit['threshold'])
                else:
                    evidence = '模型概率档'
                conclusion = ('今日 %d 条走廊触发停飞判据（%s 等，依据 %s）；'
                              '模型未来 3 小时概率 %s%%。按"此刻已在阈值内"处置。'
                              % (len(high), first['name'], evidence,
                                 _pct_text(first['pMax'])))
            else:
                conclusion = (_window + ' · %d 条走廊触发停飞判据，最差 %s %s%%。'
                              % (len(high), worst['name'], _pct_text(worst['pMax'])))
            tone = 'danger'
        elif watch:
            conclusion = (_window + ' · %d 条走廊需谨慎（概率 %.0f–%.0f%%），'
                          '最差 %s %s%%。'
                          % (len(watch), P_PROB_WATCH * 100, P_PROB_BLOCK * 100,
                             worst['name'], _pct_text(worst['pMax'])))
            tone = 'watch'
        else:
            evaluated, total = len(items), snapshot['total']
            cargo = _mode_total('DELIVERY')
            scope = ('%d 条载客走廊全部评估' % evaluated if total <= evaluated
                     else '已评估的 %d 条载客走廊（本模式共 %d 条）' % (evaluated, total))
            cargo_note = ('（另有 %d 条货运走廊不在本页）' % cargo) if cargo else ''
            worst_pct = _pct_text(worst['pMax'])
            if case_id:
                lows = [(s.get('observed') or {}).get('visM')
                        for s in field_payload.get('stations') or []
                        if s.get('available') and (s.get('observed') or {}).get('visM') is not None]
                vis_text = ('%.0f m' % min(lows)) if lows else '未取到'
                conclusion = ('历史回放：%d 站实测最低能见度 %s，模型给出的最高走廊不可飞概率 %s%%'
                              '（最差 %s），未达 %.0f%% 处置线。观测里确实有雾，但校准后的概率没有越过阈值 —— '
                              '本页不因此把结论改写成"禁飞"。'
                              % (len([x for x in field_payload.get('stations') or []
                                      if x.get('available')]), vis_text, worst_pct,
                                 worst['name']))
                tone = 'watch'
            else:
                conclusion = (_window + '，%s的不可飞概率低于 %.0f%%，可按计划运行；最差为 %s（%s%%）%s。'
                              % (scope, P_PROB_BLOCK * 100, worst['name'], worst_pct, cargo_note))
                if total > evaluated:
                    conclusion += '另有 %d 条未返回，不计入本结论。' % (total - evaluated)
                tone = 'ok'
    weather_scoped = scenario == 'live' and observation_ok
    pending_obs = [i for i in items if i.get('verdictObservation') == '不可飞']
    pending_watch = [i for i in items if (i.get('pMax') or 0) >= P_PROB_WATCH]
    pending_union_ids = {i['corridorId'] for i in pending_obs} | {i['corridorId'] for i in pending_watch}
    pending_union = [i for i in items if i['corridorId'] in pending_union_ids]
    only_obs_watch = [i for i in items
                      if i.get('verdict') == '需谨慎' and (i.get('pMax') or 0) < P_PROB_WATCH]
    if weather_scoped:
        pending_value = len(pending_union)
        pending_tone = 'danger' if high else 'watch' if watch else 'ok'
        pending_baseline = (('较上次 +%d' % delta) if delta is not None and delta > 0
                            else ('较上次 %d' % delta) if delta is not None
                            else (('模型概率未达 %.0f%% 处置线（%s；不等于观测无风险）'
                                   % (P_PROB_BLOCK * 100, worst['name'])
                                   if case_id else '当前无风险（各站均未达 %.0f%% 判据）'
                                   % (P_PROB_BLOCK * 100))
                                  if not (high or watch) else None))
        pending_reason = None if delta is not None or (high or watch) else '机场站观测已就绪，本轮没有需要处置的走廊'
        high_value = len(high)
        high_tone = 'danger' if high else 'ok'
        high_baseline = ('、'.join(i['corridorId'] for i in high[:3]) if high
                         else ('模型概率未达 %.0f%% 判据（回放帧）' % (P_PROB_BLOCK * 100) if case_id
                               else '当前无风险（未达 %.0f%% 判据）' % (P_PROB_BLOCK * 100)))
        covered = sum(1 for i in items if i.get('pMax') is not None)
        ai_value = round(covered / len(items) * 100) if items else None
        ai_baseline = ('%d / %d 条载客走廊有概率输出' % (covered, len(items))
                       if items else '本轮没有载客走廊')
        ai_baseline_reason = None
    else:
        pending_value = high_value = None
        pending_tone = high_tone = 'unknown'
        pending_baseline = high_baseline = ('气象通道中断，本轮不评估走廊' if scenario == 'unknown'
                                            else '本情景未声明气象，走廊概率未评估')
        pending_reason = pending_baseline
        ai_value = None
        ai_baseline = pending_baseline
        ai_baseline_reason = pending_baseline
    observed_ban_rows = [i for i in items
                         if i.get('verdictObservation') == '不可飞']
    prob_ban_rows = [i for i in items
                     if (i.get('pMax') or 0) >= P_PROB_BLOCK]
    kpis = [
        {'key': 'pending', 'label': '需复核走廊', 'value': pending_value, 'unit': '条',
         'baseline': pending_baseline, 'baselineReason': pending_reason,
         'direction': None if not weather_scoped or delta is None
         else ('up' if delta > 0 else 'down' if delta < 0 else 'flat'),
         'tone': pending_tone},
        {'key': 'high', 'label': '已触发停飞判据的走廊', 'value': high_value, 'unit': '条',
         'baseline': high_baseline,
         'baselineReason': None, 'direction': None, 'tone': high_tone},

        {'key': 'lead', 'label': '平均提前量', 'value': lead if lead is not None else lead_gust,
         'unit': '分钟', 'baseline': lead_baseline, 'baselineReason': None,
         'scope': 'offline', 'direction': None, 'tone': 'info'},
        {'key': 'ai', 'label': '模型覆盖', 'value': ai_value, 'unit': '%',
         'baseline': ai_baseline, 'baselineReason': ai_baseline_reason,
         'direction': None, 'tone': 'info'},
    ]
    try:
        from . import weather_control as _wc
        channel = _wc.mode()
    except Exception:  # noqa: BLE001
        channel = 'measured'
    result = {
        'status': 'OK',
        'weatherChannel': {
            'mode': channel,
            'label': '模拟气象通道' if channel == 'virtual' else '实测气象通道',
            'note': ('走廊概率固定按三站 METAR 实测计算，不随虚拟通道切换；'
                     '本页地图上的雷达回波与风险区来自虚拟通道，两者不同源、不可互相印证。'
                     if channel == 'virtual' else
                     '走廊概率按三站 METAR 实测计算；3–6 h 为 Open-Meteo 模式延伸。'),
        },
        'generatedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'planId': traffic.identity(seed, scenario),
        'scenario': scenario,
        'scenarioLabel': {'live': '公开天气驱动', 'clear': '无气象声明',
                          'unknown': '气象中断'}.get(scenario, scenario),
        'case': traffic_cases.describe(case_id) if case_id else None,
        'timeBase': ((snapshot['observation'] or {}).get('observedAt')
                     or (traffic_cases.describe(case_id).get('timeBase') if case_id else None)),
        'observation': snapshot['observation'],
        'conclusion': {
            'text': conclusion,
            'tone': tone,
            'corridorId': worst['corridorId'] if (weather_scoped and worst) else None,
            'action': '查看走廊' if (weather_scoped and worst) else None,
        },
        'kpis': kpis,
        'kpiDetail': {
            'pending': {
                'observations': len(pending_obs),
                'probabilityWatch': len(pending_watch),
                'union': len(pending_union),
                'watchThreshold': P_PROB_WATCH,
                'blockThreshold': P_PROB_BLOCK,
            },
            'observations': len(observed_ban_rows),
            'probability': len(prob_ban_rows),
            'probabilityThreshold': P_PROB_BLOCK,
            'probabilityWatchThreshold': P_PROB_WATCH,
            'definitionHigh': '观测判据（能见度 <1000 m / 阵风 >阈值 / 云底 <300 m）或概率档'
                              '（p ≥ %.2f）任一命中的城际走廊数' % P_PROB_BLOCK,
            'definitionPending': (
                '需复核 %d 条（观测或概率 ≥%.0f%%）'
                % (len(pending_union), P_PROB_WATCH * 100)
                + (' · 仅观测 %d 条' % len(only_obs_watch) if only_obs_watch else '')
                + ' · 需谨慎 %d 条'
                % len([i for i in items if i.get('verdict') == '需谨慎'])),
            'denominator': len(items),
        },
        'corridors': {'total': snapshot['total'], 'high': len(high), 'watch': len(watch),
                      'worst': worst,
                      'ribbon': [
                          {'id': row.get('corridorId'), 'name': row.get('name'),
                           'verdict': row.get('verdict'),
                           'p': row.get('pMax'), 'sigma': row.get('sigmaMean'),
                           'samples': row.get('samples') or []}
                          for row in sorted((i for i in items
                                             if i.get('verdict') != '不可飞' and i.get('samples')),
                                            key=lambda i: -(i.get('pMax') or 0))[:6]
                      ]},
        'model': {
            'available': bool(metrics_payload),
            'trainedAt': metrics_payload.get('createdAt'),
            'labelSource': metrics_payload.get('labelSource'),
            'targets': {k: {'TS': (v.get('model') or {}).get('TS'),
                            'POD': (v.get('model') or {}).get('POD'),
                            'FAR': (v.get('model') or {}).get('FAR'),
                            'Brier': (v.get('model') or {}).get('Brier')} for k, v in targets.items()},
        },
    }
    if channel == 'virtual':
        result['conclusion']['text'] = (
            result['conclusion']['text']
            + ' 当前为模拟气象通道：走廊概率仍按三站 METAR 实测计算，'
              '与地图上的虚拟回波不是同一份气象。')
    return result

def _system_version() -> str:
    try:
        from decision_service import VERSION as _release
        return _release
    except Exception:  # noqa: BLE001
        try:
            return (Path(__file__).resolve().parents[2] / 'VERSION').read_text(encoding='utf-8').strip()
        except OSError:
            return ''

def modelcard() -> Dict[str, Any]:
    payload = nowcast.metrics()
    if not payload:
        return {'status': 'MODEL_CARD_MISSING',
                'note': 'data/training/model-v2-metrics.json 不存在；模型卡不给数字，也不编'}
    status = {key: (nowcast.load(key).forest.model_version if nowcast.load(key) else None)
              for key in ('vis', 'vis3k', 'gust')}
    training_gust = ((payload.get('targets') or {}).get('gust') or {}).get('threshold')
    runtime_gust = nowcast.GUST_LIMIT_MS
    same = (isinstance(training_gust, (int, float))
            and abs(float(training_gust) - float(runtime_gust)) < 1e-9)
    return {
        'status': 'OK',
        'systemVersion': _system_version(),
        'gustThreshold': {
            'training': training_gust,
            'runtime': runtime_gust,
            'consistent': bool(same),
            'note': ('模型按训练阈值打标签、运行期读配置阈值；两者一致时这段文字就是凭据，'
                     '不一致时必须在这里说出来，而不是等读者去比对两个页面。'),
        },
        'modelVersion': 'ml-v2',
        'version': payload.get('version'),
        'task': payload.get('task'),
        'trainedAt': payload.get('createdAt'),
        'labelSource': payload.get('labelSource'),
        'dataset': payload.get('dataset'),
        'split': payload.get('split'),
        'features': payload.get('features'),
        'defaults': payload.get('defaults'),
        'targets': payload.get('targets'),
        'baselineNote': payload.get('baselineNote'),
        'loaded': status,
        'tasks': [
            {'key': 'vis3k', 'title': '低能见度 <3000 m（注意级）'},
            {'key': 'vis', 'title': '低能见度 <1000 m（不可飞）'},
            {'key': 'gust', 'title': '强阵风 >10 m/s'},
        ],
    }

def _rule_level(flight: Dict[str, Any]) -> Tuple[int, str]:
    reason = str(flight.get('reason') or '')
    action = str(flight.get('separationAction') or '')
    state = str(flight.get('state') or flight.get('status') or '')
    if state in ('CLOSED', 'CANCELLED') or flight.get('closedClosed'):
        return 2, '规则已关闭（计划或气象）'
    if reason in ('WEATHER', 'WEATHER_LOW_VISIBILITY', 'WEATHER_WIND', 'WEATHER_STORM'):
        return 1, '规则判气象受限'
    if action in ('GROUND_DELAY', 'REROUTE', 'HOLD'):
        return 1, '规则已改航/地面等待'
    return 0, '规则判可飞'

def _fuse(rule_level: int, p_unsafe: float, confidence: float,
          use_probability: bool = True) -> Tuple[int, str]:
    if rule_level == 2:
        return 2, '规则一票否决（安全硬约束）'
    if not use_probability:
        return rule_level, '本轮为消融实验：概率层未参与'
    if confidence < P_HUMAN_REVIEW_BELOW:
        return rule_level, '低置信转人工复核'
    if p_unsafe >= P_PROB_BLOCK and rule_level < 2:
        return 1, '模型升级为观察（待人工确认）'
    if p_unsafe >= P_PROB_WATCH and rule_level < 1:
        return 1, '模型提示风险，升为注意'
    return rule_level, '规则优先'

def _decision(p_unsafe: float, p_delay: Optional[float], p_alt: Optional[float],
              params: Dict[str, float], observed_ban: bool = False) -> Dict[str, Any]:
    incident = params['incident']
    losses = {
        'DIRECT': p_unsafe * incident,
        'DELAY': params['delay'] * DELAY_STEP_MIN + (p_delay if p_delay is not None else p_unsafe) * incident,
        'REROUTE': params['reroute'] + (p_alt if p_alt is not None else p_unsafe) * incident,
        'CANCEL': params['cancel'],
    }
    eligible = ['DIRECT', 'DELAY', 'REROUTE', 'CANCEL']
    excluded: Dict[str, str] = {}
    if observed_ban:
        eligible.remove('DIRECT')
        excluded['DIRECT'] = '走廊当前观测已达不可飞档，直飞不在可执行动作里'
    reroute_ok = p_alt is not None and p_alt < CANCEL_BLOCK_P_ALT
    if not reroute_ok:
        eligible.remove('REROUTE')
        excluded['REROUTE'] = '无可用备选走廊' if p_alt is None else '备选走廊同样不可飞'
    if reroute_ok:
        eligible.remove('CANCEL')
        excluded['CANCEL'] = '存在可绕飞走廊时，取消会丢掉整班任务'
    elif p_unsafe < P_PROB_WATCH and not observed_ban:
        eligible.remove('CANCEL')
        excluded['CANCEL'] = '不可飞概率低于 0.50，取消不在考虑范围'
    chosen = min(eligible, key=lambda k: losses[k])
    return {'chosen': chosen,
            'losses': {k: round(v, 1) for k, v in losses.items()},
            'eligible': eligible,
            'excluded': excluded,
            'delayMinutes': DELAY_STEP_MIN if chosen == 'DELAY' else 0}

def _flight_routes(network: Dict[str, Any]) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    out = {}
    for route in network.get('routes') or []:
        out[(route.get('mode'), route.get('fromCity'), route.get('toCity'))] = route
    return out

def counterfactual(seed: int = 42, scenario: str = 'live', policy: str = 'balanced',
                   case_id: Optional[str] = None,
                   ablate: str = '',
                   minute: Optional[float] = None) -> Dict[str, Any]:
    session = traffic.session(seed, scenario)
    if session.get('status') != 'READY':
        return {'status': session.get('status', 'NOT_READY'), 'progress': session.get('progress'),
                'note': '运行计划尚未就绪；反事实对照要等同一份计划算完'}
    flights = session.get('flights') or []
    network = traffic.network()
    routes = _flight_routes(network)
    field_payload = field(case_id=case_id, minute=minute)
    params = LOSS_PARAMS.get(policy) or LOSS_PARAMS['balanced']
    xy_cache: Dict[str, Tuple[float, float]] = {}

    def route_point(route: Dict[str, Any]) -> Optional[Tuple[float, float]]:
        points = _route_points(route)
        return points[len(points) // 2] if points else None

    use_obs = ablate != 'obs'
    use_prob = ablate != 'prob'
    use_loss = ablate != 'loss'
    exposure_a = exposure_b = 0
    cancelled = delayed = rerouted = 0
    diverged = diverged_obs = diverged_prob = 0
    corridor_ban_flights = 0
    corridor_ban_actioned = 0
    delay_minutes = 0
    reviewed = 0
    records = []
    for flight in flights:
        route = routes.get((flight.get('mode'), flight.get('fromCity'), flight.get('toCity')))
        if route is None:
            continue
        key = route['id']
        if key not in xy_cache:
            point = route_point(route)
            if point is None:
                continue
            xy_cache[key] = point
        estimate = _idw(xy_cache[key][0], xy_cache[key][1], field_payload)
        if estimate['p'] is None:
            continue
        p_unsafe = estimate['p']
        current_obs_ban = _nearest_observation_level(route, field_payload) == 'BAN'
        current_ban = current_obs_ban or p_unsafe >= P_PROB_EXPOSURE
        obs_ban = use_obs and current_obs_ban
        ban_hit = obs_ban or (use_prob and p_unsafe >= P_PROB_BLOCK)
        rule_level, rule_note = _rule_level(flight)
        confidence = abs(p_unsafe - 0.5) * 2
        prob_change = use_prob and confidence >= P_HUMAN_REVIEW_BELOW and p_unsafe >= P_PROB_WATCH
        fused, fused_note = _fuse(rule_level, p_unsafe, confidence, use_probability=use_prob)
        reviewed += 1
        changed = (fused != rule_level) or obs_ban
        if changed:
            diverged += 1
        if obs_ban:
            diverged_obs += 1
        if fused != rule_level:
            diverged_prob += 1
        if current_ban:
            corridor_ban_flights += 1
        if rule_level < 2 and current_ban:
            exposure_a += 1
        if obs_ban or (fused >= 1 and prob_change):
            alternatives = [r for r in network.get('routes') or []
                            if r.get('mode') == route.get('mode') and r['id'] != route['id']
                            and {r.get('fromCity'), r.get('toCity')} & {route.get('fromCity'), route.get('toCity')}]
            best_alt = None
            for alt in alternatives[:3]:
                point = route_point(alt)
                if point is None:
                    continue
                alt_estimate = _idw(point[0], point[1], field_payload)
                if alt_estimate['p'] is None:
                    continue
                if best_alt is None or alt_estimate['p'] < best_alt[1]:
                    best_alt = (alt['id'], alt_estimate['p'])
            if use_loss:
                decision = _decision(p_unsafe, None, best_alt[1] if best_alt else None, params,
                                     observed_ban=obs_ban)
            else:
                decision = {'chosen': 'DELAY', 'losses': {}, 'eligible': ['DELAY'],
                            'excluded': {'LOSS_MODEL': '本轮为消融实验，期望损失未参与'},
                            'delayMinutes': DELAY_STEP_MIN}
            if current_ban:
                corridor_ban_actioned += 1
            if decision['chosen'] == 'CANCEL':
                cancelled += 1
            elif decision['chosen'] == 'DELAY':
                delayed += 1
                delay_minutes += decision['delayMinutes']
            elif decision['chosen'] == 'REROUTE':
                rerouted += 1
            if decision['chosen'] == 'DIRECT' and current_ban:
                exposure_b += 1
        else:
            if current_ban and fused < 2:
                exposure_b += 1
        records.append({'flightId': flight.get('id'), 'corridorId': route['id'],
                        'p': p_unsafe, 'ruleLevel': rule_level, 'fusedLevel': fused,
                        'obsBan': obs_ban, 'changed': changed,
                        'confidence': round(confidence, 4),
                        'effectiveLevel': 2 if obs_ban else fused,
                        'note': fused_note if changed else '低置信 · 留痕未改判'})

    total = len(flights) or 1
    peak_p = max((record['p'] for record in records), default=None)
    unactioned = max(0, corridor_ban_flights - corridor_ban_actioned)
    if exposure_a > exposure_b:
        parts = []
        if rerouted:
            parts.append('绕飞 %d' % rerouted)
        if delayed:
            parts.append('延误 %d 班 %d 分钟' % (delayed, delay_minutes))
        if cancelled:
            parts.append('取消 %d' % cancelled)
        handled = rerouted + delayed + cancelled
        conclusion = ('A 组 %d 架次飞入不可飞走廊；B 组处置 %d 架次（%s），'
                      '暴露 %d 架次（−%.0f%%）。'
                      % (exposure_a, handled, '、'.join(parts) or '无动作',
                         exposure_b,
                         (exposure_a - exposure_b) / max(exposure_a, 1) * 100))
    elif peak_p is None:
        conclusion = '本快照下没有可用的走廊概率，两组都不计数（这是"没算"，不是"没风险"）。'
    elif exposure_a == exposure_b == 0:
        obs_ban_flights = sum(1 for record in records if record.get('obsBan'))
        if obs_ban_flights:
            conclusion = ('本快照下有 %d 架次所在走廊的观测已达不可飞档，但两组都没有把它们算作暴露 —— '
                          '这是一个内部矛盾，请报告：`obsBan` 与 `exposure` 应当同向。'
                          % obs_ban_flights)
        else:
            conclusion = ('本快照下两组都没有穿越「触发停飞判据」走廊的班次：模型给出的最高走廊不可飞概率 '
                          '%d%%，三站观测也均未达停飞阈值，因此没有任何一班被判为"必须改航或取消"。'
                          % round(peak_p * 100))
    else:
        obs_ban_flights = sum(1 for record in records if record.get('obsBan'))
        if corridor_ban_flights == 0:
            conclusion = ('本快照下没有班次落在「触发停飞判据」的走廊上（最高走廊概率 %d%%），'
                          '两组暴露都是 0。注意这不是"处置成功"—— 是没有需要处置的对象。'
                          % round(peak_p * 100))
        else:
            conclusion = ('本快照下 A 组暴露 %d 架次、B 组暴露 %d 架次：**没有降险**。'
                          '落在停飞走廊上的 %d 架次里，B 组处置了 %d 架次，另有 %d 架次只留痕未改判'
                          '（置信度低于 0.65 或已起飞）。'
                          % (exposure_a, exposure_b, corridor_ban_flights,
                             corridor_ban_actioned, unactioned))
    return {
        'status': 'OK',
        'policy': policy, 'params': params,
        'case': traffic_cases.describe(case_id) if case_id else None,
        'peakUnsafe': None if peak_p is None else round(peak_p, 4),
        'ablation': ({'disabled': ablate,
                      'label': {'obs': '去掉观测档', 'prob': '去掉概率层',
                                'loss': '去掉期望损失决策'}.get(ablate, '')}
                     if ablate else None),
        'scope': {'flights': len(flights), 'reviewed': reviewed,
                  'plan': session.get('sessionId'), 'policy': policy},
        'a': {'label': '关掉 AI（规则全权）', 'exposure': exposure_a,
              'cancelled': 0, 'delayMinutes': 0},
        'b': {'label': '开启 AI（概率 + 期望损失）', 'exposure': exposure_b,
              'cancelled': cancelled, 'delayMinutes': delay_minutes,
              'delayedFlights': delayed, 'rerouted': rerouted},
        'delta': {
            'exposure': exposure_b - exposure_a,
            'exposurePct': None if exposure_a == 0 else round((exposure_b - exposure_a) / exposure_a * 100, 1),
            'delayMinutes': delay_minutes,
            'delaySharePct': round(delay_minutes / (total * 40) * 100, 2),
            'diverged': diverged,
            'divergedObservation': diverged_obs,
            'divergedProbability': diverged_prob,
        },
        'conclusion': conclusion,
        'note': ('反事实重放：同一份运行计划与同一份气象快照，只改裁决规则。'
                 '本快照只重放一次裁决 —— 延期之后的风险不再重算，因此"延期"永远不被记成降险手段'
                 '（走廊剖面里的 0–6 h 曲线是概率外推，与这里的单次裁决不是同一件事）。'
                 '「暴露」的判据 = 走廊不可飞概率 ≥ %.2f（与走廊判定同一个常量 `P_PROB_BLOCK`）'
                 '**或** 走廊中点最近站的观测已达停飞阈值。'
                 % P_PROB_BLOCK),
        'caveat': '样本为模拟班次；METAR 实测覆盖 %d 个机场站（插值取最近 3 站），走廊概率由插值得到' % len(STATIONS),
        'probabilityReview': {
            'corridorBanFlights': corridor_ban_flights,
            'actioned': corridor_ban_actioned,
            'unactioned': unactioned,
            'blockThreshold': P_PROB_BLOCK,
            'watchThreshold': P_PROB_WATCH,
        },
        'sample': (
            sorted([r for r in records if r['changed']], key=lambda r: -r['p'])
            + [r for r in records if not r['changed']]
        )[:20],
        'casePanels': ({
            'caseLabel': (traffic_cases.describe(case_id) or {}).get('label'),
            'flightsHandled': cancelled + delayed + rerouted,
            'rerouted': rerouted,
            'delayed': delayed,
            'delayMinutes': delay_minutes,
            'exposureA': exposure_a,
            'exposureB': exposure_b,
        } if case_id else None),
    }

def _ledger_path() -> Path:
    try:
        import workspace as workspace_ctx
        ws = workspace_ctx.current() or 'anonymous'
    except Exception:  # noqa: BLE001
        ws = 'anonymous'
    DECISION_DIR.mkdir(parents=True, exist_ok=True)
    return DECISION_DIR / ('%s.jsonl' % ws.replace('/', '_'))

def record_decision(payload: Dict[str, Any]) -> Dict[str, Any]:
    row = {
        'at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'corridorId': payload.get('corridorId'),
        'flightId': payload.get('flightId'),
        'ruleLevel': payload.get('ruleLevel'),
        'p': payload.get('p'),
        'confidence': payload.get('confidence'),
        'verdict': payload.get('verdict'),
        'note': payload.get('note'),
        'operator': payload.get('operator') or 'operator',
        'role': payload.get('role'),
        'rolledBack': False,
    }
    with _lock:
        with _ledger_path().open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    return {'status': 'OK', 'row': row}

def divergences(limit: int = 50) -> Dict[str, Any]:
    path = _ledger_path()
    if not path.is_file():
        return {'status': 'OK', 'empty': True, 'rows': [], 'note': '尚无裁决记录'}
    rows = []
    with path.open(encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    rows.reverse()
    return {'status': 'OK', 'empty': not rows, 'total': len(rows), 'rows': rows[:limit]}

_ACTION_LABELS = {'DIRECT': '按计划放行', 'DELAY': '推迟起飞',
                  'REROUTE': '改走备选走廊', 'CANCEL': '取消本班'}

_NUMBER_RE = re.compile(r'\d+(?:\.\d+)?')

def _normalise_number(token: str) -> str:
    value = token.rstrip('.')
    try:
        return ('%g' % float(value))
    except ValueError:
        return value

def _numbers_in(text: str) -> set:
    return {_normalise_number(m) for m in _NUMBER_RE.findall(text or '')}

def _fmt_threshold(text: str) -> str:
    out = []
    for token in str(text or '').split():
        try:
            value = float(token)
        except ValueError:
            out.append(token)
            continue
        out.append(('%d' % value) if value == int(value) else token)
    return ' '.join(out)

def _template_sentence(evidence: Dict[str, Any]) -> str:
    parts = [evidence['corridor']['name']]
    if evidence.get('window'):
        parts.append('未来 %s 小时内' % evidence['leadTimeHours'])
    parts.append('不可飞概率 %d%%' % round(evidence['pUnsafe'] * 100))
    for item in evidence['evidence'][:2]:
        parts.append('%s %s（判据 %s）' % (item['metric'], item['value'], _fmt_threshold(item['threshold'])))
    if evidence['pUnsafe'] >= P_PROB_BLOCK:
        parts.append('建议%s' % evidence['decision']['label'])
        if evidence.get('costMinutes'):
            parts.append('代价约 %d 分钟当量' % evidence['costMinutes'])
    else:
        parts.append('低于停飞判据阈值 %.0f%%，可按计划运行' % (P_PROB_BLOCK * 100))
        if evidence.get('alternatives'):
            parts.append('另有备选走廊 %s 可选' % evidence['alternatives'][0]['corridorId'])
    return '，'.join(parts) + '。'

def translator(route_id: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = corridor(route_id)
    if payload.get('status') != 'OK':
        return {'status': payload.get('status', 'NOT_FOUND'), 'corridorId': route_id,
                'note': '走廊剖面不可用（没有观测或走廊不存在），不给解读'}

    alternatives = payload.get('alternatives') or []
    p_alt = alternatives[0]['pMax'] if alternatives else None
    decision = _decision(payload['pMax'], None, p_alt, LOSS_PARAMS['balanced'])
    criteria = payload.get('criteria') or []
    metrics = nowcast.metrics() or {}
    lead = ((metrics.get('targets') or {}).get('vis3k') or {}).get('leadTime') or {}

    evidence_items = []
    for row in criteria[:2]:
        evidence_items.append({'metric': row.get('metric') or row.get('key'),
                               'value': ('%s %s' % (row.get('value'), row.get('unit') or '')).strip(),
                               'threshold': ('%s %s' % (row.get('operator') or '', row.get('threshold'))).strip(),
                               'source': row.get('source') or 'METAR 实测'})
    evidence = {
        'corridor': {'id': payload['corridorId'], 'name': payload['name']},
        'leadTimeHours': 3,
        'pUnsafe': payload['pMax'],
        'verdict': payload['verdict'],
        'confidence': payload['confidence'],
        'nearestStationKm': payload['nearestStationKm'],
        'evidence': evidence_items,
        'decision': dict(decision,
                         label=('按计划放行' if payload['pMax'] < P_PROB_BLOCK
                                else _ACTION_LABELS.get(decision['chosen'], decision['chosen'])),
                         note=('低于停飞判据阈值 %.0f%%：对外建议按计划放行；'
                               '期望损失的最小项只在达到该阈值后才作为建议'
                               % (P_PROB_BLOCK * 100)
                               if payload['pMax'] < P_PROB_BLOCK else '')),
        'pUnsafePct': round(payload['pMax'] * 100, 1),
        'costMinutes': decision.get('delayMinutes'),
        'leadTimeMinutes': lead.get('medianMin'),
        'alternatives': alternatives,
        'window': payload.get('window'),
        'assumptions': payload.get('assumptions', {}),
    }

    allowed = set()
    for value in (payload['pMax'], payload['nearestStationKm'], evidence['leadTimeMinutes'],
                  evidence['costMinutes']):
        if value is not None:
            allowed.add(_normalise_number(str(value)))
            if isinstance(value, float):
                allowed.add(_normalise_number(str(round(value * 100))))
    for item in evidence_items:
        allowed |= _numbers_in('%s %s' % (item.get('value'), item.get('threshold')))
    allowed.add('3')

    template = _template_sentence(evidence)
    result = {'status': 'OK', 'corridorId': payload['corridorId'],
              'template': template, 'text': template, 'source': 'TEMPLATE',
              'guard': {'violations': [], 'retried': False}, 'evidence': evidence,
              'note': '模板只填证据字段，不推算任何新数字'}

    api_key = (cfg or {}).get('api_key')
    if not api_key:
        result['note'] = '未配置大模型 Key，本句由模板生成（同一套字段）'
        return result

    system = ('你是低空运行的值班员。把给定的结构化证据翻译成一句中文结论，'
              '只能使用输入 JSON 里已有的数字，禁止推算、四舍五入到新数值或补充任何输入里没有的数字。'
              '不超过 80 字，不要分点，不要自称 AI。')
    messages = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': json.dumps(evidence, ensure_ascii=False)}]
    for attempt in range(2):
        try:
            with httpx.Client(timeout=httpx.Timeout(15, connect=5), trust_env=False) as client:
                response = client.post((cfg.get('base_url') or '').rstrip('/') + '/chat/completions',
                                       headers={'Authorization': 'Bearer ' + api_key},
                                       json={'model': cfg.get('model', 'deepseek-chat'),
                                             'temperature': 0, 'max_tokens': 220,
                                             'messages': messages})
                response.raise_for_status()
                text = (response.json()['choices'][0]['message']['content'] or '').strip()
            extra = sorted(_numbers_in(text) - allowed)
            if not extra:
                result.update({'text': text, 'source': 'MODEL',
                               'guard': {'violations': [], 'retried': attempt > 0}})
                return result
            result['guard'] = {'violations': extra, 'retried': attempt > 0}
            messages.append({'role': 'assistant', 'content': text})
            messages.append({'role': 'user',
                             'content': '上一句出现了输入里没有的数字（%s）。只能引用给定数字，重写一句。'
                                        % '、'.join(extra)})
        except Exception as exc:
            result['note'] = '大模型不可用（%s），已降级为模板句' % type(exc).__name__
            return result
    result['note'] = '两次生成都引入了输入里没有的数字（%s），已降级为模板句' % '、'.join(result['guard']['violations'])
    return result
