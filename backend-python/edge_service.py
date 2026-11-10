# -*- coding: utf-8 -*-
"""边缘节点后端（V1.0.1 · `/api/edge/*`）。

只做"记录与值守"，不做放行判定：
- 节点自己算四档，服务端只存它报上来的 `p` / `tier` / `latencyMs` 与**帧来源**；
- 服务端算数据龄（用 `frameTs`，不信节点自报）与三状态（连续 10 min 没成功请求才算 OFFLINE）；
- 不给任何"批准/放行"入口 —— 那条红线写在 `docs/V1.0.1-边缘节点-预留接口清单.md` §7。

开关：`config/application.yml` 的 `edge.enabled`，默认 false（关掉时全部接口 503，
不构成既有契约变更）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
CONFIG_PATH = ROOT / 'config' / 'application.yml'
RULES_FILE = ROOT / 'config' / 'rules-v1.json'
DB = Path(os.environ.get('TIANCHUANG_EDGE_DB', ROOT / '.run' / 'edge.sqlite3'))

OFFLINE_AFTER_MINUTES = 10.0
AGE_STALE_MINUTES = 90.0
AGE_EXPIRED_MINUTES = 180.0
MODES = ('ONLINE', 'DEGRADED', 'OFFLINE')

# 端侧四档（口径卡 §10）：BAN ≥0.8 / CAUTION ≥0.5 / WATCH ≥0.2，其余 FIT；
# `p_unsafe = 1-(1-p_vis)(1-p_gust)`。观测档另有一条：vis<1000 m 或 gust>11.5 m/s → BAN。
EDGE_TIERS = {'ban': 0.8, 'caution': 0.5, 'watch': 0.2}
EDGE_OBSERVATION_BAN = {'visM': 1000.0, 'gustMps': 11.5}
EDGE_OBSERVATION_CAUTION = {'visM': 3000.0}

_LOCK = threading.RLock()
_CORRIDOR_CACHE: Dict[str, Any] = {}


# ---------------------------------------------------------------- 配置

def settings() -> Dict[str, Any]:
    """读 `edge` 段；环境变量优先，便于现场临时开。"""
    value: Dict[str, Any] = {}
    try:
        import yaml
        with open(CONFIG_PATH, 'r', encoding='utf-8') as handle:
            value = (yaml.safe_load(handle) or {}).get('edge') or {}
    except Exception:  # noqa: BLE001 - 配置缺失时按关闭处理，不抛
        value = {}
    enabled = os.getenv('EDGE_ENABLED')
    if enabled is None:
        enabled = value.get('enabled', False)
    secret = os.getenv('EDGE_HMAC_SECRET', str(value.get('hmac-secret') or ''))
    if str(secret).startswith('${'):
        secret = ''
    return {
        'enabled': str(enabled).strip().lower() in ('1', 'true', 'yes', 'on'),
        'hmacSecret': str(secret).strip(),
        'ringLimit': int(value.get('ring-limit') or 500),
        'reportWindowMinutes': int(value.get('report-window-minutes') or 240),
    }


def enabled() -> bool:
    return settings()['enabled']


# ---------------------------------------------------------------- 指纹

def rules_fingerprint() -> str:
    """`rules-v1.json` 的指纹：节点侧拿它校验"规则有没有过期"。"""
    try:
        digest = hashlib.sha256(RULES_FILE.read_bytes()).hexdigest()[:12]
    except OSError:
        digest = 'missing'
    return f'rules-v1:{digest}'


def _corridors() -> List[Dict[str, Any]]:
    if 'value' not in _CORRIDOR_CACHE:
        from traffic import service as traffic_service
        catalog = traffic_service.network()
        _CORRIDOR_CACHE['value'] = [
            {'corridorId': item['id'], 'name': item['name'], 'mode': item['mode'],
             'fromCity': item.get('fromCity'), 'toCity': item.get('toCity')}
            for item in catalog['routes']
        ]
        _CORRIDOR_CACHE['catalog'] = catalog
    return _CORRIDOR_CACHE['value']


def params_version() -> str:
    ids = ';'.join(sorted(item['corridorId'] for item in _corridors()))
    return 'corridors:' + hashlib.sha256(ids.encode('utf-8')).hexdigest()[:12]


def thresholds() -> Dict[str, float]:
    """端侧**四档**阈值（口径卡 §10 / 硬件册 §5 坑 3）。

    这是节点屏上的判决阈值；与走廊判据（`corridor_thresholds()`）是**两套数**，
    混着讲就会出现"裁决一致率 100% 必然失败"的那种错。
    """
    return dict(EDGE_TIERS)


def corridor_thresholds() -> Dict[str, float]:
    """走廊判据阈值，与后端 `traffic.v2` 同源，不许另写一份常量。"""
    from traffic import v2
    return {'block': float(v2.P_PROB_BLOCK),
            'watch': float(v2.P_PROB_WATCH),
            'exposure': float(v2.P_PROB_EXPOSURE)}


def station_codes() -> List[str]:
    from weather import metar_history
    return list(metar_history.STATIONS)


# ---------------------------------------------------------------- 存储

def _now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=10)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS nodes ('
               'node TEXT PRIMARY KEY, site_id TEXT, hw_rev TEXT, fw TEXT, '
               'station_codes TEXT, registered_at TEXT, last_seen TEXT, mode TEXT, '
               'data_age_min REAL, queue_depth INTEGER, token TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS reports ('
               'node TEXT NOT NULL, seq INTEGER NOT NULL, ts TEXT, frame_ts TEXT, '
               'data_age_min REAL, time_source TEXT, mode TEXT, tier TEXT, '
               'p_vis REAL, p_gust REAL, p_unsafe REAL, latency_ms REAL, fw TEXT, '
               'rules_fp TEXT, stale_rules INTEGER, sig_verified INTEGER, '
               'received_at TEXT, PRIMARY KEY (node, seq))')
    db.execute('CREATE TABLE IF NOT EXISTS heartbeats ('
               'node TEXT NOT NULL, ts TEXT, mode TEXT, data_age_min REAL, '
               'queue_depth INTEGER, received_at TEXT)')
    return db


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _minutes_since(moment: Optional[datetime]) -> Optional[float]:
    if moment is None:
        return None
    return round((datetime.now(timezone.utc) - moment).total_seconds() / 60.0, 1)


def age_tier(minutes: Optional[float]) -> str:
    if minutes is None:
        return 'UNKNOWN'
    if minutes > AGE_EXPIRED_MINUTES:
        return 'EXPIRED'
    if minutes > AGE_STALE_MINUTES:
        return 'STALE'
    return 'FRESH'


def _signature(node: str, ts: str, seq: int, body: Dict[str, Any]) -> str:
    payload = f"{node}|{ts}|{seq}|{json.dumps(body, ensure_ascii=False, sort_keys=True)}"
    return hmac.new(settings()['hmacSecret'].encode('utf-8'),
                    payload.encode('utf-8'), hashlib.sha256).hexdigest()


def _verify(payload: Dict[str, Any]) -> bool:
    """密钥没配时不假装验过：返回 False，由响应里的 `sigVerified` 说明。"""
    secret = settings()['hmacSecret']
    given = str(payload.get('sig') or '').strip()
    if not given:
        return False
    if given.startswith('hmac-sha256:'):
        given = given.split(':', 1)[1]
    if not secret:
        return False
    body = {key: value for key, value in payload.items() if key != 'sig'}
    expected = _signature(str(payload.get('node')), str(payload.get('ts')),
                          int(payload.get('seq') or 0), body)
    return hmac.compare_digest(given, expected)


# ---------------------------------------------------------------- 下行

def frames(since: Optional[str] = None, stations: Optional[str] = None,
           limit: int = 7) -> Dict[str, Any]:
    """下发可缓存的 METAR 实测帧。合成帧一律不进缓存，不足就报 `shortfall`。"""
    from weather import metar_history
    wanted = [code.strip().upper() for code in (stations or ','.join(metar_history.STATIONS)).split(',') if code.strip()]
    wanted = [code for code in wanted if code in metar_history.STATIONS]
    limit = max(1, min(int(limit or 7), 24))
    since_dt = _parse_iso(since)
    histories = metar_history.station_histories(hours=max(limit, 7))
    rows: List[Dict[str, Any]] = []
    shortfall = False
    for code in wanted:
        series = histories.get(code) or []
        picked = []
        for item in series:
            moment = datetime.fromtimestamp(int(item['epoch']), tz=timezone.utc)
            if since_dt is not None and moment <= since_dt:
                continue
            picked.append({
                'station': code,
                'ts': item['timeUtc'],
                'source': 'METAR',
                'raw': item.get('rawOb'),
                'visM': item.get('visM'),
                'gustMps': item.get('gustMs'),
                'windMps': item.get('windMs'),
                'tempC': item.get('tempC'),
                'cloudBaseM': item.get('cloudBaseM'),
            })
        chosen = picked[-limit:]
        if len(chosen) < 7 and since_dt is None:
            shortfall = True
        rows.extend(chosen)
    return {
        'generatedAt': _now(),
        'rulesFingerprint': rules_fingerprint(),
        'stationCodes': wanted,
        'count': len(rows),
        'shortfall': shortfall,
        'frames': rows,
    }


def time_payload() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        'serverTimeUtc': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'monotonicMs': int((now - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds() * 1000),
        'source': 'SERVER_HTTP',
        'offlineAfterMinutes': OFFLINE_AFTER_MINUTES,
    }


def params() -> Dict[str, Any]:
    corridors = _corridors()
    return {
        'rulesFingerprint': rules_fingerprint(),
        'paramsVersion': params_version(),
        'thresholds': thresholds(),
        'observationBans': {'ban': EDGE_OBSERVATION_BAN, 'caution': EDGE_OBSERVATION_CAUTION},
        'corridorThresholds': corridor_thresholds(),
        'windowHours': [1, 3],
        'stationCodes': station_codes(),
        'corridorCount': len(corridors),
        'corridors': corridors,
        'ageTiers': {'stale': AGE_STALE_MINUTES, 'expired': AGE_EXPIRED_MINUTES},
        'note': ('`thresholds` 是端侧四档（0.8/0.5/0.2），`corridorThresholds` 是走廊判据，'
                 '两套数不要混着讲；指纹不符时应拒绝裁决，而不是降级。'),
    }


def sites() -> Dict[str, Any]:
    """部署三层：示范点 3 个 vertiport；扩展 216 条配送走廊末端；演进只放机载/车载。"""
    _corridors()
    catalog = _CORRIDOR_CACHE['catalog']
    cities = {city['id']: city for city in catalog['cities']}
    demo = []
    for city_id, station in (('1-01', 'ZYTX'), ('2-01', 'ZYCC'), ('3-01', 'ZYHB')):
        city = cities.get(city_id) or {}
        demo.append({
            'siteId': f'VP-{city_id}', 'name': f"{city.get('name', city_id)}城市起降点值班室",
            'stage': 'demo', 'province': city.get('province'), 'city': city.get('name'),
            'stationCode': station, 'enabled': True,
        })
    planned_pads = set()
    for item in catalog['routes']:
        if item['mode'] == 'DELIVERY':
            planned_pads.add((item.get('toCity'), item.get('toPad')))
    planned = []
    for city_id, pad_id in sorted(planned_pads, key=lambda pair: (str(pair[0]), str(pair[1]))):
        city = cities.get(city_id) or {}
        planned.append({
            'siteId': f'DP-{pad_id}', 'name': f"{city.get('name', '')} 配送末端 {pad_id}",
            'stage': 'planned', 'province': city.get('province'), 'city': city.get('name'),
            'stationCode': None, 'enabled': False,
        })
    future = [{'siteId': 'MOBILE-AIR', 'name': '机载', 'stage': 'future', 'enabled': False,
               'stationCode': None, 'reason': '未做供电/振动/电磁/适航验证'},
              {'siteId': 'MOBILE-CAR', 'name': '车载', 'stage': 'future', 'enabled': False,
               'stationCode': None, 'reason': '同上'}]
    return {
        'generatedAt': _now(),
        'demo': demo,
        'planned': {'count': len(planned), 'sites': planned},
        'future': future,
        'note': '示范点＝三站（ZYTX/ZYCC/ZYHB）所在城市值班室；扩展＝216 条城内配送走廊末端；机载/车载只放展望。',
    }


# ---------------------------------------------------------------- 上行

def register(payload: Dict[str, Any]) -> Dict[str, Any]:
    node = str(payload.get('node') or '').strip()
    if not node:
        return {'status': 'INVALID', 'reason': 'NODE_ID_REQUIRED'}
    site_id = str(payload.get('siteId') or '').strip() or None
    codes = payload.get('stationCodes') or station_codes()
    codes = [str(code).upper() for code in codes if str(code).upper() in station_codes()]
    token = hashlib.sha256(f'{node}|{site_id}|{VERSION}'.encode('utf-8')).hexdigest()[:16]
    with _LOCK:
        db = _connect()
        try:
            with db:
                db.execute('INSERT INTO nodes (node, site_id, hw_rev, fw, station_codes, registered_at, '
                           'last_seen, mode, data_age_min, queue_depth, token) '
                           'VALUES (?,?,?,?,?,?,?,?,?,?,?) '
                           'ON CONFLICT(node) DO UPDATE SET site_id=excluded.site_id, hw_rev=excluded.hw_rev, '
                           'fw=excluded.fw, station_codes=excluded.station_codes, token=excluded.token',
                           (node, site_id, str(payload.get('hwRev') or ''), str(payload.get('fw') or ''),
                            json.dumps(codes, ensure_ascii=False), _now(), None, None, None, 0, token))
        finally:
            db.close()
    return {'status': 'OK', 'enabled': True, 'node': node, 'siteId': site_id,
            'nodeToken': token, 'rulesFingerprint': rules_fingerprint(),
            'paramsVersion': params_version(), 'stationCodes': codes}


def _unknown_node(node: str) -> bool:
    with _LOCK:
        db = _connect()
        try:
            row = db.execute('SELECT 1 FROM nodes WHERE node=?', (node,)).fetchone()
            return row is None
        finally:
            db.close()


def _store_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    node = str(payload.get('node') or '').strip()
    if not node:
        return {'status': 'INVALID', 'reason': 'NODE_ID_REQUIRED'}
    try:
        seq = int(payload.get('seq'))
    except (TypeError, ValueError):
        return {'status': 'INVALID', 'reason': 'SEQ_REQUIRED'}
    mode = str(payload.get('mode') or '').upper()
    if mode not in MODES:
        return {'status': 'INVALID', 'reason': 'MODE_INVALID'}
    if _unknown_node(node):
        return {'status': 'FORBIDDEN', 'reason': 'NODE_NOT_REGISTERED'}
    ts = str(payload.get('ts') or _now())
    frame_ts = payload.get('frameTs')
    frame_moment = _parse_iso(frame_ts)
    data_age = _minutes_since(frame_moment)
    if data_age is None:
        data_age = payload.get('dataAgeMin')
        data_age = None if data_age is None else float(data_age)
    stale_rules = str(payload.get('rulesFingerprint') or '') != rules_fingerprint()
    probabilities = payload.get('p') or {}
    decision = payload.get('decision') or {}
    verified = _verify(payload)
    received = _now()
    with _LOCK:
        db = _connect()
        try:
            with db:
                cursor = db.execute(
                    'INSERT OR IGNORE INTO reports (node, seq, ts, frame_ts, data_age_min, time_source, '
                    'mode, tier, p_vis, p_gust, p_unsafe, latency_ms, fw, rules_fp, stale_rules, '
                    'sig_verified, received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (node, seq, ts, str(frame_ts) if frame_ts else None, data_age,
                     str(payload.get('timeSource') or 'UNKNOWN'), mode, str(decision.get('tier') or ''),
                     probabilities.get('vis'), probabilities.get('gust'), probabilities.get('unsafe'),
                     payload.get('latencyMs'), str(payload.get('fw') or ''), str(payload.get('rulesFingerprint') or ''),
                     1 if stale_rules else 0, 1 if verified else 0, received))
                inserted = cursor.rowcount > 0
                db.execute('UPDATE nodes SET last_seen=?, mode=?, data_age_min=? WHERE node=?',
                           (received, mode, data_age, node))
        finally:
            db.close()
    return {'status': 'OK', 'ok': True, 'duplicate': not inserted, 'seq': seq,
            'staleRules': stale_rules, 'sigVerified': verified,
            'dataAgeMin': data_age, 'ageTier': age_tier(data_age),
            'serverTimeUtc': _now(),
            'note': '' if verified else '未校验签名（密钥未配置或节点未签名）；该记录仅作留痕，不作统计。'}


def report(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _store_report(payload)


def report_batch(payload: Dict[str, Any]) -> Dict[str, Any]:
    node = str(payload.get('node') or '').strip()
    items = payload.get('items') or []
    limit = settings()['ringLimit']
    accepted: List[int] = []
    duplicates: List[int] = []
    rejected: List[Dict[str, Any]] = []
    for item in items[:limit]:
        merged = dict(item)
        merged.setdefault('node', node)
        result = _store_report(merged)
        if result.get('status') != 'OK':
            rejected.append({'seq': item.get('seq'), 'reason': result.get('reason') or result.get('status')})
        elif result.get('duplicate'):
            duplicates.append(result['seq'])
        else:
            accepted.append(result['seq'])
    return {'status': 'OK', 'node': node, 'acceptedSeqs': accepted,
            'duplicateSeqs': duplicates, 'rejected': rejected,
            'received': len(accepted) + len(duplicates) + len(rejected)}


def heartbeat(payload: Dict[str, Any]) -> Dict[str, Any]:
    node = str(payload.get('node') or '').strip()
    if not node:
        return {'status': 'INVALID', 'reason': 'NODE_ID_REQUIRED'}
    if _unknown_node(node):
        return {'status': 'FORBIDDEN', 'reason': 'NODE_NOT_REGISTERED'}
    mode = str(payload.get('mode') or '').upper()
    data_age = payload.get('dataAgeMin')
    queue = int(payload.get('queueDepth') or 0)
    received = _now()
    stale = str(payload.get('rulesFingerprint') or '') != rules_fingerprint()
    with _LOCK:
        db = _connect()
        try:
            with db:
                db.execute('INSERT INTO heartbeats (node, ts, mode, data_age_min, queue_depth, received_at) '
                           'VALUES (?,?,?,?,?,?)',
                           (node, received, mode if mode in MODES else None,
                            None if data_age is None else float(data_age), queue, received))
                db.execute('UPDATE nodes SET last_seen=?, mode=?, data_age_min=?, queue_depth=? WHERE node=?',
                           (received, mode if mode in MODES else None,
                            None if data_age is None else float(data_age), queue, node))
        finally:
            db.close()
    return {'status': 'OK', 'ok': True, 'serverTimeUtc': received,
            'backfill': queue > 0, 'paramsStale': stale,
            'rulesFingerprint': rules_fingerprint()}


# ---------------------------------------------------------------- 观察面

def node_rows() -> List[Dict[str, Any]]:
    with _LOCK:
        db = _connect()
        try:
            rows = db.execute('SELECT node, site_id, fw, station_codes, last_seen, mode, data_age_min, queue_depth '
                              'FROM nodes ORDER BY node').fetchall()
            samples = {}
            for node, p_unsafe, tier, ts in db.execute(
                    'SELECT node, p_unsafe, tier, ts FROM reports WHERE (node, seq) IN '
                    '(SELECT node, MAX(seq) FROM reports GROUP BY node)'):
                samples[node] = {'pUnsafe': p_unsafe, 'tier': tier, 'lastReportAt': ts}
        finally:
            db.close()
    result = []
    for node, site_id, fw, station_codes, last_seen, mode, data_age, queue in rows:
        last_seen_dt = _parse_iso(last_seen)
        idle = _minutes_since(last_seen_dt)
        observed = 'OFFLINE' if (idle is None or idle > OFFLINE_AFTER_MINUTES) else (mode or 'ONLINE')
        sample = samples.get(node) or {}
        result.append({
            'node': node, 'siteId': site_id, 'fw': fw,
            'stationCodes': json.loads(station_codes) if station_codes else [],
            'mode': observed, 'reportedMode': mode, 'lastSeenAt': last_seen,
            'idleMinutes': idle, 'dataAgeMin': data_age,
            'ageTier': age_tier(data_age), 'queueDepth': queue or 0,
            'pUnsafe': sample.get('pUnsafe'), 'tier': sample.get('tier'),
            'lastReportAt': sample.get('lastReportAt'),
        })
    return result


def nodes() -> Dict[str, Any]:
    rows = node_rows()
    return {'status': 'OK', 'generatedAt': _now(), 'count': len(rows), 'nodes': rows,
            'offlineAfterMinutes': OFFLINE_AFTER_MINUTES}


def node_detail(node: str, limit: int = 60) -> Dict[str, Any]:
    rows = node_rows()
    target = next((row for row in rows if row['node'] == node), None)
    if target is None:
        return {'status': 'NOT_FOUND', 'node': node}
    with _LOCK:
        db = _connect()
        try:
            history = db.execute(
                'SELECT ts, frame_ts, data_age_min, mode, tier, p_unsafe, latency_ms, stale_rules, sig_verified '
                'FROM reports WHERE node=? ORDER BY seq DESC LIMIT ?', (node, max(1, min(int(limit), 500)))).fetchall()
        finally:
            db.close()
    return {'status': 'OK', 'node': node, 'summary': target,
            'history': [{'ts': ts, 'frameTs': frame_ts, 'dataAgeMin': age, 'mode': mode,
                         'tier': tier, 'pUnsafe': p_unsafe, 'latencyMs': latency,
                         'staleRules': bool(stale), 'sigVerified': bool(verified)}
                        for (ts, frame_ts, age, mode, tier, p_unsafe, latency, stale, verified) in reversed(history)]}


def backfill(node: Optional[str] = None, window_minutes: Optional[int] = None) -> Dict[str, Any]:
    window = int(window_minutes or settings()['reportWindowMinutes'])
    since = (datetime.now(timezone.utc) - timedelta(minutes=window)).strftime('%Y-%m-%dT%H:%M:%SZ')
    with _LOCK:
        db = _connect()
        try:
            query = ('SELECT node, MIN(received_at), MAX(received_at), COUNT(*), SUM(stale_rules), SUM(sig_verified) '
                     'FROM reports WHERE received_at >= ?')
            args: List[Any] = [since]
            if node:
                query += ' AND node=?'
                args.append(node)
            query += ' GROUP BY node ORDER BY node'
            rows = db.execute(query, args).fetchall()
        finally:
            db.close()
    items = []
    for name, first, last, count, stale, verified in rows:
        items.append({'node': name, 'firstReceivedAt': first, 'lastReceivedAt': last,
                      'count': count, 'staleRules': int(stale or 0),
                      'sigVerified': int(verified or 0),
                      'sigUnverified': int(count - (verified or 0))})
    return {'status': 'OK', 'windowMinutes': window, 'since': since, 'nodes': items,
            'note': '补传台账按批入库时间去重后统计；条数一致、零重复由 `node+seq` 主键保证。'}


def health() -> Dict[str, Any]:
    rows = node_rows()
    counts = {'ONLINE': 0, 'DEGRADED': 0, 'OFFLINE': 0}
    for row in rows:
        counts[row['mode'] if row['mode'] in counts else 'OFFLINE'] += 1
    ages = [row['dataAgeMin'] for row in rows if row['dataAgeMin'] is not None]
    with _LOCK:
        db = _connect()
        try:
            mismatch = db.execute('SELECT COUNT(DISTINCT node) FROM reports WHERE stale_rules=1').fetchone()[0]
            unverified = db.execute('SELECT COUNT(*) FROM reports WHERE sig_verified=0').fetchone()[0]
            total = db.execute('SELECT COUNT(*) FROM reports').fetchone()[0]
        finally:
            db.close()
    return {'status': 'OK', 'enabled': enabled(), 'version': VERSION,
            'nodes': len(rows), 'online': counts['ONLINE'], 'degraded': counts['DEGRADED'],
            'offline': counts['OFFLINE'], 'countsClosed': sum(counts.values()) == len(rows),
            'oldestDataAgeMin': max(ages) if ages else None,
            'fingerprintMismatchNodes': mismatch, 'sigUnverifiedReports': unverified,
            'reports': total, 'rulesFingerprint': rules_fingerprint(),
            'offlineAfterMinutes': OFFLINE_AFTER_MINUTES}
