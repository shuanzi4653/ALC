# -*- coding: utf-8 -*-
"""全国层的**运行对象**：班次、分级汇总、机场情报、事件、AI 链。

为什么单独一层
--------------
`nation.py` 是"路网与几何"（节点、航线、回波、绕飞），回答"哪里能飞"。
本模块是"运行与裁决"，回答"这一班几点走、凭什么、出问题谁处置"。

口径纪律
--------
- 班次、许可、事件**全部为 SIM**（模拟交通），与 `data/traffic` 的路网同源；
  不冒充真实航班，也不进 1.0.0 的东北运行计划。
- 气象是**真实公开实况**（open-meteo / METAR），风险概率是由实况按本文件阈值
  算出来的**规则派生值**（`DERIVED`），不是训练模型输出 —— 界面上必须这么写。
- 班次 id 用 `crc32` 而不是 `hash()`：后者每个进程随机加盐，重启后同一班次会换号。
"""
from __future__ import annotations

import zlib
from typing import Any, Dict, Iterable, List, Optional, Tuple

# 风险阈值（与东北层 1.0.0 的低能见度口径同族，但这里是规则派生，不是 ml 模型）
VIS_BANDS = ((1500.0, 0.72), (3000.0, 0.45), (5000.0, 0.22))
WIND_HIGH = 12.0
RISK_HOLD = 0.75
RISK_WATCH = 0.35
# 模型判据的门槛：与规则分分开定。0.35 起提示、0.60 延期 —— 这是**运营阈值**，
# 不是模型自带的，改了要同步改口径页。
MODEL_WATCH = 0.35
MODEL_HOLD = 0.60
CRUISE_M = (600, 1100)

DECISION_LABEL = {'RELEASE': '直飞放行', 'DETOUR': '绕飞放行', 'HOLD': '暂不放行'}
LEVEL_LABEL = {'HIGH': '高', 'MEDIUM': '中', 'LOW': '低'}
CLEARANCE_LABEL = {'RELEASED': '已放行', 'PENDING': '待批', 'SUSPENDED': '已暂停'}


def _seed(corridor_id: str) -> int:
    return zlib.crc32(corridor_id.encode('utf-8')) % 9973


def schedule(row: Dict[str, Any]) -> Dict[str, float]:
    """一条航线的排班参数。确定性：同一条航线永远同一个间隔与相位。"""
    seed = _seed(row['id'])
    headway = 150 + seed % 120                       # 2.5–4.5 h 一班
    speed = 200.0 if row.get('cross') else 180.0
    duration = max(12.0, (row.get('lengthKm') or 100.0) / speed * 60.0)
    return {'headway': float(headway), 'phase': float(seed % headway),
            'speed': speed, 'duration': duration}


def altitude_profile(duration: float, cruise: int, samples: int = 9) -> List[List[float]]:
    """高度剖面：15% 爬升、70% 巡航、15% 下降。时间单位分钟，高度单位米 AGL。"""
    out: List[List[float]] = []
    for index in range(samples):
        t = duration * index / (samples - 1)
        ratio = index / (samples - 1)
        if ratio <= 0.15:
            alt = cruise * (ratio / 0.15)
        elif ratio >= 0.85:
            alt = cruise * ((1 - ratio) / 0.15)
        else:
            alt = cruise
        out.append([round(t, 1), int(alt)])
    return out


def _risk(row: Dict[str, Any], weather: Dict[str, Dict[str, Any]],
          detour: Optional[Dict[str, Any]],
          model_probs: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """规则派生的风险概率 + 依据。**不是训练模型**，界面标 DERIVED。"""
    a = weather.get(row['fromName']) or {}
    b = weather.get(row['toName']) or {}
    vis_values = [v.get('visM') for v in (a, b) if v.get('visM') is not None]
    winds = [v.get('windMps') for v in (a, b) if v.get('windMps') is not None]
    vis = min(vis_values) if vis_values else None
    wind = max(winds) if winds else None

    risk = 0.05
    drivers: List[str] = []
    if vis is not None:
        for threshold, value in VIS_BANDS:
            if vis < threshold:
                risk = max(risk, value)
                drivers.append(f'端点能见度 {vis/1000:.1f} km')
                break
    else:
        drivers.append('端点无实况（能见度按未知处理）')
        risk = max(risk, 0.2)
    if wind is not None and wind >= WIND_HIGH:
        risk = min(0.95, risk + 0.12)
        drivers.append(f'端点风速 {wind:.1f} m/s')
    if detour:
        risk = min(0.95, risk + 0.18)
        drivers.append(f"航路穿回波，绕飞 {detour.get('shiftKm', 0)} km")
    risk = round(min(0.95, max(0.0, risk)), 3)

    # 全国模型（ml-v3）：端点两城的低能见度概率按独立事件合并。
    # **不并进 risk 分**，而是作为第二道判据 —— 规则分回答"这条航路的运行风险"，
    # 模型概率回答"端点会不会看不见"。两者任一触发就降级，谁也别替谁背书。
    p_model = None
    source = 'RULE'
    probs = model_probs or {}
    p_from, p_to = probs.get(row['fromName']), probs.get(row['toName'])
    if p_from is not None or p_to is not None:
        p_model = round(1.0 - (1.0 - (p_from or 0.0)) * (1.0 - (p_to or 0.0)), 4)
        source = 'MODEL'
        if p_model >= 0.35:
            drivers.append(
                f"模型低能见度概率 {p_model:.0%}（{row['fromName']} {p_from if p_from is not None else '—'}"
                f" / {row['toName']} {p_to if p_to is not None else '—'}）")

    level = 'HIGH' if (risk >= RISK_HOLD or (p_model or 0) >= MODEL_HOLD) else (
        'MEDIUM' if (risk >= RISK_WATCH or (p_model or 0) >= MODEL_WATCH) else 'LOW')
    if detour:
        decision = 'DETOUR'
    elif risk >= RISK_HOLD or (p_model or 0) >= MODEL_HOLD:
        decision = 'HOLD'
    else:
        decision = 'RELEASE'
    return {'riskP': risk, 'riskLevel': level, 'riskLevelLabel': LEVEL_LABEL[level],
            'decision': decision, 'decisionLabel': DECISION_LABEL[decision],
            'drivers': drivers, 'visM': vis, 'windMps': wind,
            'pModel': p_model, 'probSource': source}


def _clearance(row: Dict[str, Any], sched: Dict[str, float], depart: float,
               arrive: float, risk: Dict[str, Any], detour: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    band_low = CRUISE_M[0]
    band_high = CRUISE_M[1]
    if risk['decision'] == 'HOLD':
        status = 'PENDING'
    elif risk['decision'] == 'DETOUR':
        status = 'RELEASED'
    else:
        status = 'RELEASED'
    conditions = []
    if risk.get('visM') is not None:
        vis_km = risk['visM'] / 1000.0
        conditions.append(f'端点能见度实况 {vis_km:.1f} km（门槛 3 km）' if vis_km < 10
                          else '端点能见度 ≥ 10 km')
    conditions.append('侧风 ≤ 12 m/s')
    if detour:
        conditions.append(f"按绕飞航路执行（外偏 {detour.get('shiftKm', 0)} km）")
    if row.get('borderDetour'):
        conditions.append('已按边境带改线')
    return {
        'status': status, 'statusLabel': CLEARANCE_LABEL[status],
        'route': f"{row['fromName']} → {row['toName']}",
        'corridor': row['id'],
        'altitudeBand': f'{band_low}–{band_high} m AGL（按航向分层）',
        'timeWindow': f'{_clock(depart)}–{_clock(arrive)}',
        'conditions': conditions,
    }


def _clock(minute: float) -> str:
    """分钟数 → HH:MM，**按北京时间（UTC+8）**。

    时间轴本身是"当日第几分钟"，界面顶部把它显示成本地时刻（09:00 = minute 60）。
    这里必须跟着加 8 小时，否则同一屏上会出现"数据时刻 09:00、班次 22:24"两个基准，
    评审一眼就能看出对不上。
    """
    total = int(round(minute)) % 1440
    local = (total + 8 * 60) % 1440
    return f'{local // 60:02d}:{local % 60:02d}'


def flight_objects(corridors: Iterable[Dict[str, Any]], minute: int,
                   detours: Dict[str, Dict[str, Any]],
                   weather: Dict[str, Dict[str, Any]],
                   model_probs: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """某一分钟在飞的班次对象。

    **每架一个独立对象**：有自己的编号、起降城市、计划时刻、许可、风险、裁决与高度剖面，
    前端点哪一架就是哪一架，不再是一堆无名的点。
    """
    out: List[Dict[str, Any]] = []
    for row in corridors:
        if row.get('borderBlocked'):
            continue
        sched = schedule(row)
        headway, phase = sched['headway'], sched['phase']
        duration = sched['duration']
        elapsed = (minute - phase) % headway
        if elapsed > duration:
            continue
        progress = elapsed / duration
        path = row.get('path') or [row['fromLonLat'], row['toLonLat']]
        if len(path) < 2:
            continue
        detour = detours.get(row['id'])
        # 绕飞航迹是真的在飞的那条，位置也跟着它走
        if detour and detour.get('path'):
            path = detour['path']
        seg = max(1, len(path) - 1)
        pos = progress * seg
        idx = min(seg - 1, int(pos))
        frac = pos - idx
        lon = path[idx][0] + (path[idx + 1][0] - path[idx][0]) * frac
        lat = path[idx][1] + (path[idx + 1][1] - path[idx][1]) * frac
        ahead = path[min(seg, idx + 1)]
        heading = 0.0
        if ahead and (ahead[0] != lon or ahead[1] != lat):
            import math as _math
            heading = _math.degrees(_math.atan2(ahead[1] - lat, ahead[0] - lon))

        late = int(6 + detour['shiftKm'] / 6.0) if detour else 0
        depart = minute - elapsed
        arrive = depart + duration + late
        cruise = CRUISE_M[0] + int(min(1.0, (row.get('lengthKm') or 100) / 260.0) * (CRUISE_M[1] - CRUISE_M[0]))
        risk = _risk(row, weather, detour, model_probs)
        slot = int((minute - phase) // headway)
        callsign = f"TC{row['id'].split('-')[-1]}{slot % 10}"

        alerts: List[Dict[str, str]] = []
        if detour:
            alerts.append({'code': 'ECHO_DETOUR', 'label': '绕飞回波', 'tone': 'warn'})
        if risk['riskLevel'] == 'HIGH':
            alerts.append({'code': 'LOW_VIS', 'label': '低能见度', 'tone': 'bad'})
        if row.get('borderDetour'):
            alerts.append({'code': 'BORDER_REROUTE', 'label': '边境改线', 'tone': 'quiet'})
        if late:
            alerts.append({'code': 'DELAY', 'label': f'延误 {late} min', 'tone': 'warn'})

        out.append({
            'id': f"{row['id']}#{slot}",
            'callsign': callsign,
            'corridor': row['id'],
            'fromName': row['fromName'], 'toName': row['toName'],
            'fromProvince': row['fromProvince'], 'toProvince': row['toProvince'],
            'fromLonLat': row['fromLonLat'], 'toLonLat': row['toLonLat'],
            'kind': row['kind'], 'kindLabel': row.get('kindLabel'),
            'lon': round(lon, 4), 'lat': round(lat, 4), 'heading': round(heading, 1),
            'progress': round(progress, 3),
            'altM': int(cruise * (1 - abs(progress - 0.5) * 1.4)) if progress < 0.15 or progress > 0.85 else cruise,
            'speedKmh': int(sched['speed']),
            'departMinute': round(depart, 1), 'arriveMinute': round(arrive, 1),
            'durationMin': round(duration, 1), 'elapsedMin': round(elapsed, 1),
            'departAt': _clock(depart), 'arriveAt': _clock(arrive),
            # 申请 / 计划 / 实际是三个不同时刻，不能三列写同一个数：
            # 申请 = 起飞前 8 分钟提交；计划 = 排班时刻；实际 = 计划 + 绕飞延误。
            'requestAt': _clock(depart - 8), 'planAt': _clock(depart),
            'actualAt': _clock(depart + late) if elapsed > 0 else '',
            'status': 'DELAYED' if detour else 'ON_TIME',
            'delayMin': late, 'detourKm': detour['shiftKm'] if detour else 0.0,
            'riskP': risk['riskP'], 'riskLevel': risk['riskLevel'],
            'riskLevelLabel': risk['riskLevelLabel'], 'probSource': risk['probSource'],
            'pModel': risk['pModel'],
            'decision': risk['decision'], 'decisionLabel': risk['decisionLabel'],
            'drivers': risk['drivers'],
            'clearance': _clearance(row, sched, depart, arrive, risk, detour),
            'altProfile': altitude_profile(duration, cruise),
            'alerts': alerts,
            'exposure': {
                'directMin': round((detour.get('hitKm', 0.0) / max(1.0, sched['speed'])) * 60.0, 1) if detour else 0.0,
                'detourMin': 0.0,
            },
            'source': 'SIM',
        })
    out.sort(key=lambda item: item['departMinute'])
    return out


def upcoming(corridors: Iterable[Dict[str, Any]], minute: int,
             horizon: int = 90) -> List[Dict[str, Any]]:
    """未来 `horizon` 分钟内将要起飞的班次（用于台账的"未起飞"一栏）。"""
    rows: List[Dict[str, Any]] = []
    for row in corridors:
        if row.get('borderBlocked'):
            continue
        sched = schedule(row)
        headway, phase, duration = sched['headway'], sched['phase'], sched['duration']
        elapsed = (minute - phase) % headway
        wait = headway - elapsed if elapsed > duration else 0
        if wait > horizon:
            continue
        depart = minute + wait
        rows.append({
            'id': f"{row['id']}#{int((depart - phase) // headway)}",
            'corridor': row['id'], 'fromName': row['fromName'], 'toName': row['toName'],
            'fromProvince': row['fromProvince'], 'toProvince': row['toProvince'],
            'departMinute': round(depart, 1), 'arriveMinute': round(depart + duration, 1),
            'departAt': _clock(depart), 'arriveAt': _clock(depart + duration),
            'durationMin': round(duration, 1), 'waitMin': round(wait, 1),
            'state': 'SCHEDULED', 'speedKmh': int(sched['speed']),
            'source': 'SIM',
        })
    rows.sort(key=lambda item: item['departMinute'])
    return rows


def _airborne_by_province(flights: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """按**起飞机省**归属，避免跨省航线被两边各算一次。"""
    table: Dict[str, Dict[str, int]] = {}
    for flight in flights:
        bucket = table.setdefault(flight['fromProvince'], {'airborne': 0, 'delayed': 0, 'hold': 0})
        bucket['airborne'] += 1
        if flight['status'] == 'DELAYED':
            bucket['delayed'] += 1
        if flight['decision'] == 'HOLD':
            bucket['hold'] += 1
    return table


def _corridors_by_province(corridors: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    table: Dict[str, Dict[str, int]] = {}
    for row in corridors:
        provinces = {row['fromProvince']}
        if row['toProvince'] != row['fromProvince']:
            provinces.add(row['toProvince'])
        for province in provinces:
            bucket = table.setdefault(province, {'corridors': 0, 'blocked': 0, 'detour': 0})
            bucket['corridors'] += 1
            if row.get('borderBlocked'):
                bucket['blocked'] += 1
            if row.get('detour'):
                bucket['detour'] += 1
    return table


def province_blocks(provinces: Iterable[Dict[str, Any]], corridors: List[Dict[str, Any]],
                    flights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """给每个省一个**自己的块**：本省多少航线、在飞几架、异常几架、停飞几条。"""
    air = _airborne_by_province(flights)
    lines = _corridors_by_province(corridors)
    out: List[Dict[str, Any]] = []
    for row in provinces:
        name = row['name']
        a = air.get(name) or {'airborne': 0, 'delayed': 0, 'hold': 0}
        c = lines.get(name) or {'corridors': 0, 'blocked': 0, 'detour': 0}
        out.append({
            'name': name, 'region': row.get('region'), 'regionLabel': row.get('regionLabel'),
            'cities': row.get('cities'), 'airports': row.get('airports'),
            'corridors': c['corridors'], 'blocked': c['blocked'], 'detour': c['detour'],
            'airborne': a['airborne'], 'delayed': a['delayed'], 'hold': a['hold'],
            'lowVisCities': row.get('lowVisCities') or 0,
            'state': row.get('state'),
        })
    return out


def city_blocks(province: Optional[str], cities: Iterable[Dict[str, Any]],
                corridors: List[Dict[str, Any]], flights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """市一级的块：每个城市自己的航线数与在飞数。"""
    out: List[Dict[str, Any]] = []
    air_counter: Dict[str, int] = {}
    delay_counter: Dict[str, int] = {}
    for flight in flights:
        air_counter[flight['fromName']] = air_counter.get(flight['fromName'], 0) + 1
        if flight['status'] == 'DELAYED':
            delay_counter[flight['fromName']] = delay_counter.get(flight['fromName'], 0) + 1
    for city in cities:
        name = city['name']
        links = [row for row in corridors if name in (row['fromName'], row['toName'])]
        out.append({
            'name': name, 'province': city.get('province') or province,
            'airport': city.get('airport'), 'hasAirport': city.get('hasAirport'),
            'corridors': len(links),
            'airborne': air_counter.get(name, 0),
            'delayed': delay_counter.get(name, 0),
            'blocked': sum(1 for row in links if row.get('borderBlocked')),
            'links': len(links),
            'coordSource': city.get('coordSource'),
            'lon': city.get('lon'), 'lat': city.get('lat'),
        })
    out.sort(key=lambda item: (-item['airborne'], -item['corridors'], item['name']))
    return out


def intel(cities: Iterable[Dict[str, Any]], weather: Dict[str, Dict[str, Any]],
          airport_by_city: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """机场情报：全国机场城市的实况与放行建议（**实况为公开源，建议为规则派生**）。"""
    rows: List[Dict[str, Any]] = []
    for city in cities:
        station = airport_by_city.get(city['name'])
        if not station:
            continue
        live = weather.get(city['name']) or {}
        vis = live.get('visM')
        wind = live.get('windMps')
        if vis is None:
            status, tone = '无实况', 'quiet'
        elif vis < 1500:
            status, tone = '不建议放行', 'bad'
        elif vis < 3000:
            status, tone = '需谨慎', 'warn'
        else:
            status, tone = '可放行', 'good'
        rows.append({
            'city': city['name'], 'province': city['province'],
            'icao': station.get('icao'), 'station': station.get('site'),
            'visM': vis, 'windMps': wind, 'tempC': live.get('tempC'),
            'low': bool(live.get('low')), 'status': status, 'tone': tone,
            'hasWeather': bool(live),
        })
    rows.sort(key=lambda item: (item['status'] == '可放行', item['visM'] or 99999))
    return rows


def alerts(corridors: List[Dict[str, Any]], flights: List[Dict[str, Any]],
           weather: Dict[str, Dict[str, Any]], cities: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """事件处置：把本视图内需要处置的事凑成一条条事件，带处置动作与状态。"""
    out: List[Dict[str, Any]] = []
    for city in cities:
        live = weather.get(city['name']) or {}
        if live.get('low'):
            out.append({
                'id': f"EV-VIS-{city['name']}", 'code': 'LOW_VIS', 'kind': '低能见度',
                'severity': 'warn', 'place': city['name'], 'province': city['province'],
                'detail': f"能见度 {live.get('visM', 0)/1000:.1f} km，低于 3 km 门槛",
                'action': '端点城市降档：该端起降班次提高一层高度带，能见度 <1.5 km 的暂不放行',
                'status': '自动处置', 'auto': True,
            })
    for row in corridors:
        if row.get('borderBlocked'):
            out.append({
                'id': f"EV-BORDER-{row['id']}", 'code': 'BORDER_HOLD', 'kind': '边境受限',
                'severity': 'bad', 'place': f"{row['fromName']} → {row['toName']}",
                'province': row['fromProvince'],
                'detail': '航路落在我方一侧 10 km 管制带内；'
                          + ('绕飞后仍越界' if row.get('detour') else '没有可用的绕飞方案'),
                'action': '该航线停飞，不进入排班；恢复需空管批准',
                'status': '已停飞', 'auto': True,
            })
        elif row.get('detour'):
            out.append({
                'id': f"EV-ECHO-{row['id']}", 'code': 'ECHO_DETOUR', 'kind': '回波绕飞',
                'severity': 'warn', 'place': f"{row['fromName']} → {row['toName']}",
                'province': row['fromProvince'],
                'detail': f"原航路穿对流回波，外偏 {row['detour'].get('shiftKm', 0)} km 改航",
                'action': '已按法线侧移改航，航迹图上琥珀色段为实际航路',
                'status': '自动处置', 'auto': True,
            })
    for flight in flights:
        if flight['decision'] == 'HOLD':
            # 判据要写"到底是哪一条"触发的。
            # 以前这里固定写"风险概率 X，高于 0.75 暂不放行"，而 HOLD 还可能是
            # 模型概率 ≥0.60 触发的 —— 于是页面上出现过"风险概率 0.05，高于 0.75 暂不放行"
            # 这种自相矛盾的句子（0.05 当然不高于 0.75）。
            rule = float(flight.get('riskP') or 0.0)
            p_model = flight.get('pModel')
            if rule >= RISK_HOLD:
                why = f'规则风险 {rule:.2f} ≥ {RISK_HOLD:.2f}'
            elif p_model is not None and p_model >= MODEL_HOLD:
                why = f'模型低能见概率 {p_model:.0%} ≥ {MODEL_HOLD:.0%}'
            else:
                why = '放行条件未满足'
            out.append({
                'id': f"EV-HOLD-{flight['id']}", 'code': 'FLIGHT_HOLD', 'kind': '延期起飞',
                'severity': 'bad', 'place': f"{flight['fromName']} → {flight['toName']}",
                'province': flight['fromProvince'],
                'detail': f'{why}，暂不放行',
                'action': '留在地面等待下一个时隙；判据回落后自动恢复',
                'status': '待处置', 'auto': False, 'flightId': flight['id'],
            })
    # 聚合：同一类事件在同一省里合成一条，卡内列影响清单。
    # 不聚合的话，50 条走廊同时绕飞就是 50 张内容雷同的卡 ——
    # 之前处置页"8 张卡一模一样"就是这么来的（逐走廊生成、字段全取模板）。
    # 聚合键用 (成因, 省)：跨省的事件各自留在本省，这样切到大区/省时看到的是本级的事。
    merged: Dict[tuple, Dict[str, Any]] = {}
    for item in out:
        key = (item['code'], item.get('province') or '')
        slot = merged.get(key)
        if slot is None:
            merged[key] = {
                **item,
                'id': f"EV-{item['code']}-{item.get('province') or '全国'}",
                'count': 1,
                'places': [item['place']],
                'memberIds': [item['id']],
            }
        else:
            slot['count'] += 1
            if item['place'] not in slot['places'] and len(slot['places']) < 20:
                slot['places'].append(item['place'])
            slot['memberIds'].append(item['id'])
            if item['severity'] == 'bad':
                slot['severity'] = 'bad'
            # 多人待处置的，状态要跟着最严重的那个走
            if not item.get('auto'):
                slot['auto'] = False
    out = []
    for slot in merged.values():
        count = slot['count']
        if count > 1:
            head = '、'.join(slot['places'][:3])
            more = f" 等 {count} 处" if count > 3 else ''
            slot['place'] = f"{slot.get('province') or '全国'} · {count} 处"
            slot['detail'] = f"{slot['detail']}；同类共 {count} 处（{head}{more}）"
        out.append(slot)

    order = {'bad': 0, 'warn': 1, 'quiet': 2}
    out.sort(key=lambda item: (order.get(item['severity'], 3), -item.get('count', 1), item['kind']))
    return out


def border_monitor(corridors: List[Dict[str, Any]], flights: List[Dict[str, Any]],
                   border_table: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """越界监视（全国版）：**按几何逐架判**，不再读停飞标记。

    每条航路的离境距离与"进入 10/30 km 带"的进度区间由 `nation._corridor_border` 算好，
    这里只做查表 + 比对航班的实时进度。10 km 是硬限（条例第十九条(2)的保守执行），
    30 km 是预警带（提前量，不是管制线）。
    """
    table = border_table or {}
    inside: List[Dict[str, Any]] = []
    warning: List[Dict[str, Any]] = []
    for flight in flights:
        info = table.get(flight['corridor'])
        if not info:
            continue
        progress = flight.get('progress') or 0.0
        if any(start <= progress <= end for start, end in info.get('band10') or []):
            inside.append(flight)
        elif any(start <= progress <= end for start, end in info.get('band30') or []):
            warning.append(flight)
    measured = [table[row['id']]['minKm'] for row in corridors if row['id'] in table]
    blocked = [row for row in corridors if row.get('borderBlocked')]
    nearest = min(measured) if measured else None
    return {
        'method': '航路按约 8 km 加密，逐点与邻国边界求距；10 km 为硬限，30 km 为预警带',
        'checkedCorridors': len(measured),
        'inside': len(inside),
        'flights': [{'id': f['id'], 'place': f"{f['fromName']} → {f['toName']}"} for f in inside[:6]],
        'warning': len(warning),
        'warningFlights': [{'id': f['id'], 'place': f"{f['fromName']} → {f['toName']}"} for f in warning[:6]],
        'nearestKm': nearest,
        'blockedCorridors': len(blocked),
        'blockedNames': [f"{row['fromName']} → {row['toName']}" for row in blocked],
        'scope': '国界/实际控制线向我方一侧 10 km 管制带（本项目保守口径）；30 km 为预警带',
        'note': '越界数逐架按几何算出：每条航路都量了到境外的最近距离。',
    }


# 模型适用范围：训练侧的 26 个特征里，全国城市实况**缺**哪些，一条条列出来。
MODEL_FEATURES_TOTAL = 26
MODEL_MISSING_FOR_NATIONAL = (
    'dewC 露点',
    'qnhHpa 海平面气压',
    'cloudBaseM 云底高',
    'visMin3h / visMin6h 三、六小时最低能见度',
    'gustMax3h 三小时最大阵风',
    'qnhTendency3h / visChange3h / tempTendency3h / spreadTendency3h 三小时趋势',
    'stationCode 站点编码（训练只有 ZYTX/ZYCC/ZYHB）',
)


def model_card() -> Dict[str, Any]:
    """全国层的模型口径卡：有什么模型、覆盖到哪、为什么全国用不了。"""
    models: List[Dict[str, Any]] = []
    try:
        from ml import nowcast
        metrics = nowcast.metrics() or {}
        table = metrics.get('models') or {}
        for key, label in (('vis', '低能见度 <1 km'), ('vis3k', '低能见度 <3 km'), ('gust', '强阵风')):
            model = nowcast.load(key)
            if model is None:
                continue
            row = table.get(key) or {}
            models.append({
                'key': key, 'label': label,
                'version': model.forest.model_version,
                'auc': row.get('auc'), 'ts': row.get('ts'), 'brier': row.get('brier'),
                'trainScope': '沈阳 ZYTX / 长春 ZYCC / 哈尔滨 ZYHB 三站 METAR',
                'samples': row.get('samples'),
            })
    except Exception:  # noqa: BLE001 - 模型读不到不能让全国层打不开
        models = []
    return {
        'models': models,
        'national': {
            'applicable': False,
            'coverage': '仅东北三站；全国 319 市无对应训练分布',
            'missing': list(MODEL_MISSING_FOR_NATIONAL),
            'featuresTotal': MODEL_FEATURES_TOTAL,
            'reason': '训练输入依赖 METAR 的露点、气压、云底与 3–6 小时历史，全国城市实况（open-meteo current）'
                      '只给温度、风速、能见度三项；用默认值补齐再套模型，等于拿默认值冒充观测，'
                      '所以全国层一律用规则派生，并把来源标在每一个概率上。',
        },
        'fallback': {'probSource': 'RULE', 'note': '规则派生：端点能见度分档 + 风速门槛 + 回波加分'},
    }


def counterfactual(flights: List[Dict[str, Any]]) -> Dict[str, Any]:
    """反事实：**含回波** 与 **不含回波** 两套规则下，裁决会怎么变。

    这不是"AI vs 规则"那种反事实（全国层没有模型，做不出来），
    而是同一套规则里"要不要看回波"的对照 —— 能算、可复现，也能回答
    "绕飞这 3 架，是不是雷达逼出来的"。
    """
    changed: List[Dict[str, Any]] = []
    for flight in flights:
        if flight['decision'] != 'DETOUR':
            continue
        # 回波在风险里加 0.18；去掉它再看会不会低于暂缓线
        without = round(max(0.0, flight['riskP'] - 0.18), 3)
        before = 'DETOUR' if flight['decision'] == 'DETOUR' else flight['decision']
        after = 'HOLD' if without >= 0.75 else 'RELEASE'
        if before != after:
            changed.append({'id': flight['id'], 'place': f"{flight['fromName']} → {flight['toName']}",
                            'withEcho': before, 'withoutEcho': after,
                            'riskWith': flight['riskP'], 'riskWithout': without})
    return {
        'withEcho': {'detour': sum(1 for f in flights if f['decision'] == 'DETOUR'),
                     'hold': sum(1 for f in flights if f['decision'] == 'HOLD')},
        'withoutEcho': {'release': len(flights) - sum(1 for f in flights if f['decision'] == 'HOLD'),
                        'hold': sum(1 for f in flights if f['decision'] == 'HOLD')},
        'changed': changed,
        'changedCount': len(changed),
        'note': '对照的是同一套规则"看不看回波"，不是 AI 与规则的对照（全国层无模型可用）。',
    }
