# -*- coding: utf-8 -*-
"""逐市气象：多源调度 + 后台刷新 + 磁盘快照。

为什么要重写
------------
原来只有 open-meteo 一个源，一次全量要 6 批 × 60 坐标 = 360 次额度。
免费额度按小时计（实测一小时打满就连续 429），一旦打满：
- 每次请求都要撞 6 次 429，接口被拖成 10 秒以上；
- 页面上的"逐市气象"整块变空，看不出是"没数据"还是"接口挂了"。

现在的结构（stale-while-revalidate）
------------------------------------
1. **请求只读缓存**：`fetch()` 命中就返回；过期时也先把旧数据交出去并标 `stale`，
   同时在后台线程里刷新 —— 页面首屏不再被气象源卡住。
2. **多源补数**：open-meteo 批量（有能见度）为主；缺的城市用 wttr.in 逐城补
   （也有能见度，中文城市名直接可用，但要限速 1 次/秒，所以只补关键城市）。
3. **磁盘快照**：拿到就落盘；一路都失败时退回最近一份，并标 `stale`。
4. **每城带 source**：界面能回答"这个温度是谁给的"，不混成一个数。

口径不变：拿不到就是没有，不插值、不补零。
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import httpx

URL = 'https://api.open-meteo.com/v1/forecast'
FIELDS = 'temperature_2m,wind_speed_10m,visibility,weather_code,precipitation'
BATCH = 60
TTL_SECONDS = 1800.0          # 正常一轮缓存 30 分钟（319 城 × 2 ≈ 638 次/小时，远低于额度）
RATE_LIMIT_TTL = 900.0        # 被限流后 15 分钟内不再硬撞主源
STALE_RETRY = 120.0           # 只有旧数据时，2 分钟后允许再试
TIMEOUT_SECONDS = 25.0
USER_AGENT = 'ALC-tianchuang/1.0.1 (city weather; contact: project maintainer)'

# wttr.in 的补数预算：中文名可用、有能见度，但要求 ≤1 次/秒，
# 所以只补前 80 个（调用方把省会与机场城市排在前面）。
WTTR_BUDGET = 80
WTTR_INTERVAL = 1.15

CACHE_FILE = Path(__file__).resolve().parent.parent.parent / 'data' / 'cache' / 'city-weather.json'

_state: Dict[str, Any] = {'value': None, 'expires': 0.0, 'refreshing': False}
_lock = threading.Lock()


def _num(value: Any) -> Any:
    """数值归一。open-meteo 给数字，wttr.in 给的是**字符串**（"5" / "3"），两种都要认。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


# ---------- 源 1：open-meteo 批量 ----------
def _fetch_batch(rows: List[Tuple[str, float, float]]) -> Dict[str, Dict[str, Any]]:
    params = {
        'latitude': ','.join(f'{lat:.4f}' for _, lat, _ in rows),
        'longitude': ','.join(f'{lon:.4f}' for _, _, lon in rows),
        'current': FIELDS,
        'timezone': 'UTC',
    }
    response = httpx.get(URL, params=params, timeout=TIMEOUT_SECONDS,
                         headers={'User-Agent': USER_AGENT})
    response.raise_for_status()
    payload = response.json()
    items = payload if isinstance(payload, list) else [payload]
    out: Dict[str, Dict[str, Any]] = {}
    for (name, _lat, _lon), item in zip(rows, items):
        current = (item or {}).get('current') or {}
        wind_kmh = _num(current.get('wind_speed_10m'))
        vis = _num(current.get('visibility'))
        out[name] = {
            'tempC': _num(current.get('temperature_2m')),
            'windMps': round(wind_kmh / 3.6, 1) if wind_kmh is not None else None,
            'visM': vis,
            'precipMm': _num(current.get('precipitation')),
            'weatherCode': current.get('weather_code'),
            'ts': (current.get('time') or '') + ':00Z' if current.get('time') else None,
            'low': bool(vis is not None and vis < 3000),
            'source': 'OPEN_METEO',
        }
    return out


def _open_meteo(rows: List[Tuple[str, float, float]]) -> Tuple[Dict[str, Dict[str, Any]], List[str], bool]:
    merged: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    rate_limited = False
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        try:
            merged.update(_fetch_batch(chunk))
        except Exception as exc:  # noqa: BLE001 - 单批失败不该拖垮整屏
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if status == 429:
                rate_limited = True
                errors.append(f'batch {start // BATCH}: 429 限流')
                break
            errors.append(f'batch {start // BATCH}: {str(exc)[:80]}')
    return merged, errors, rate_limited


# ---------- 源 2：wttr.in 逐城（补缺） ----------
def _wttr_one(name: str, lat: float, lon: float) -> Dict[str, Any] | None:
    """单城实况。wttr.in 支持中文城市名，也有能见度，正好补 open-meteo 的缺口。"""
    try:
        response = httpx.get(f'https://wttr.in/{name}',
                             params={'format': 'j1'},
                             timeout=15.0,
                             headers={'User-Agent': 'ALC-tianchuang/1.0.1'})
        if response.status_code != 200:
            return None
        body = response.json()
        current = ((body.get('current_condition') or [{}])[0]) or {}
        temp = _num(current.get('temp_C'))
        wind_kmh = _num(current.get('windspeedKmph'))
        vis_km = _num(current.get('visibility'))
        if temp is None and vis_km is None:
            return None
        vis = vis_km * 1000.0 if vis_km is not None else None
        return {
            'tempC': temp,
            'windMps': round(wind_kmh / 3.6, 1) if wind_kmh is not None else None,
            'visM': vis,
            'precipMm': _num(current.get('precipMM')),
            'weatherCode': None,
            'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:00Z'),
            'low': bool(vis is not None and vis < 3000),
            'source': 'WTTR',
        }
    except Exception:  # noqa: BLE001 - 备源失败就当这城没有
        return None


def _wttr_fill(missing: List[Tuple[str, float, float]],
               merged: Dict[str, Dict[str, Any]]) -> int:
    added = 0
    for index, (name, lat, lon) in enumerate(missing[:WTTR_BUDGET]):
        if index:
            time.sleep(WTTR_INTERVAL)
        got = _wttr_one(name, lat, lon)
        if got:
            merged[name] = got
            added += 1
    return added


# ---------- 快照 ----------
def _load_disk(key: str) -> Dict[str, Any] | None:
    try:
        payload = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001 - 没有快照就是没有
        return None
    if payload.get('key') != key:
        return None
    return payload


def _save_disk(value: Dict[str, Any]) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    except Exception:  # noqa: BLE001 - 写盘失败不影响本次结果
        pass


# ---------- 刷新 ----------
def _do_refresh(rows: List[Tuple[str, float, float]], key: str) -> Dict[str, Any]:
    merged, errors, rate_limited = _open_meteo(rows)
    filled = 0
    missing = [row for row in rows if row[0] not in merged]
    if missing and (rate_limited or len(merged) < len(rows) * 0.85):
        # 主源被限流、或缺口很大时才动用备源（wttr 慢，别没事就拉一遍）
        filled = _wttr_fill(missing, merged)
        if filled:
            errors.append(f'wttr 补 {filled} 城（主源缺 {len(missing)} 城）')
    if not merged:
        fallback = _load_disk(key)
        if fallback:
            out = dict(fallback, stale=True, errors=errors)
            with _lock:
                _state.update({'value': out, 'expires': time.monotonic() + STALE_RETRY})
            return out
    sources: Dict[str, int] = {}
    for item in merged.values():
        sources[item['source']] = sources.get(item['source'], 0) + 1
    value = {
        'available': bool(merged),
        'source': 'open-meteo current + wttr.in（公开、免密钥，逐市）',
        'fetchedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'key': key,
        'cities': merged,
        'sources': sources,
        'errors': errors,
        'stale': False,
    }
    with _lock:
        if merged:
            ttl = TTL_SECONDS if len(merged) >= len(rows) * 0.85 else STALE_RETRY
            if rate_limited and not filled:
                ttl = RATE_LIMIT_TTL
            _state.update({'value': value, 'expires': time.monotonic() + ttl})
        elif rate_limited:
            _state.update({'value': value, 'expires': time.monotonic() + RATE_LIMIT_TTL})
    if merged:
        _save_disk(value)
    return value


def _refresh_background(rows: List[Tuple[str, float, float]], key: str) -> None:
    try:
        _do_refresh(rows, key)
    finally:
        with _lock:
            _state['refreshing'] = False


def fetch(points: Iterable[Tuple[str, float, float]], force: bool = False) -> Dict[str, Any]:
    """points = [(城市名, 纬度, 经度), ...]；调用方按重要程度排序（省会、机场城市在前）。

    命中缓存直接返回；过期时**先把旧数据交出去**并在后台刷新。
    只有完全没有数据（首次启动）才同步等一次。
    """
    rows = [(name, float(lat), float(lon)) for name, lat, lon in points]
    key = f'{len(rows)}:{rows[0][0] if rows else ""}:{rows[-1][0] if rows else ""}'
    now = time.monotonic()
    with _lock:
        cached = _state['value']
        hit = bool(cached and cached.get('key') == key)
        if hit and not force and now < _state['expires']:
            return cached
        if not _state['refreshing']:
            _state['refreshing'] = True
            threading.Thread(target=_refresh_background, args=(rows, key), daemon=True).start()
        if hit:
            stale = dict(cached)
            stale['stale'] = True
            return stale
    disk = _load_disk(key)
    if disk:
        with _lock:
            if not _state['value']:
                _state['value'] = disk
        return dict(disk, stale=True)
    # 首次启动、内存和磁盘都没有：**也不要同步等**。
    # 319 城一次全量 + 备源补数要一分多钟，让首屏等这个是不可接受的；
    # 后台线程已经在补，这里先如实交一个"补数中"的空壳，补齐后下一次请求就有。
    with _lock:
        placeholder = {
            'available': False, 'refreshing': True, 'stale': False,
            'source': 'open-meteo current + wttr.in（补数中）',
            'fetchedAt': None, 'key': key, 'cities': {}, 'sources': {},
            'errors': ['首次取数中，逐市实况随后补齐'],
        }
        if not _state['value'] or _state['value'].get('key') != key:
            _state['value'] = placeholder
            _state['expires'] = time.monotonic() + 10.0
        return placeholder
