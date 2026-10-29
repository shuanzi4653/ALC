# -*- coding: utf-8 -*-
"""0.11.7 · B 方案后端：走廊能见度 + 站点影响圈（案例模式）。

## 只做一件事：把"雾在哪"变成可查询的字段

原来案例模式只有概率（`pMax`），没有能见度。所以地图上画不出雾，只能写一句
"21 条走廊观测已达禁飞级"——**结论有了，但图上找不到**。

现在给三样东西：
  · `corridors[].visM` / `visLevel` —— 每条走廊**中点**的 IDW 能见度（三站/四站加权）；
  · `corridors[].visNearestKm` —— 最近站距（让"离站远=不可信"这件事可见）；
  · `field.stationVisibility` —— 4 个站的实测值，给地图画影响圈用。

## 三条纪律

1. **阈值从配置读**（`rules-v1.json::visibilityM` 的 `banValue` / `warnValue`），
   不硬编码 1000/5000 —— 否则改配置时这里会静默不一致；
2. **不新增第二套插值**：能见度加权用与概率同一套 `1/d²`、同样取最近 3 站。
   两套插值同时存在，迟早出现"概率说禁飞、能见度说没事"；
3. **`ONLY_THREE_AIRPORT_STATIONS` 这个 flag 现在是错的** —— 案例已经是 4 站，
   写死"三站"会让读日志的人以为大连没进来。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / 'backend-python' / 'traffic' / 'v2.py'

text = V2.read_text(encoding='utf-8')

# ---- 1) 能见度阈值（从配置读，带兜底） ----
anchor = "def _idw(x: float, y: float, field_payload: Dict[str, Any]) -> Dict[str, Any]:"
helper = '''def _visibility_thresholds() -> Dict[str, float]:
    """能见度两档阈值。**从 `config/rules-v1.json` 读**，读不到才用兜底值。"""
    global _VIS_CACHE
    if _VIS_CACHE is not None:
        return _VIS_CACHE
    ban, warn = 1000.0, 5000.0
    try:
        import json as _json
        rules = _json.loads((ROOT_DIR / 'config' / 'rules-v1.json').read_text(encoding='utf-8'))
        for group in rules.get('groups') or []:
            for rule in group.get('rules') or []:
                if rule.get('key') == 'visibilityM':
                    ban = float(rule.get('banValue') or ban)
                    warn = float(rule.get('warnValue') or warn)
    except Exception:  # noqa: BLE001
        pass
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
    """中点能见度。**与 `_idw` 同一套权重**（1/d²、最近 3 站），只是被加权的量不同。

    为什么不复用 `_idw`：它加权的是 `probabilities.unsafe`（模型输出），而这里要加权的
    是 `observed.visM`（实测）。把两者塞进一个函数会让"到底在插值什么"变得含糊。
    但**权重算法必须一致** —— 否则同一位置会出现"概率说禁飞、能见度说没事"。
    """
    stations = [s for s in field_payload.get('stations') or []
                if s.get('available') and ((s.get('observed') or {}).get('visM') is not None)]
    if not stations:
        return {'visM': None, 'visLevel': None, 'nearestKm': None, 'contributors': []}
    xy = _station_xy()
    ranked = []
    for s in stations:
        point = xy.get(s['station'])
        if point is None:
            continue
        ranked.append((math.hypot(x - point[0], y - point[1]) / 1000.0, s))
    if not ranked:
        return {'visM': None, 'visLevel': None, 'nearestKm': None, 'contributors': []}
    ranked.sort(key=lambda item: item[0])
    picked = ranked[:3]
    weights = [1.0 / max(d, 1.0) ** 2 for d, _ in picked]
    total = sum(weights) or 1.0
    value = sum(w * s['observed']['visM'] for w, (_, s) in zip(weights, picked)) / total
    return {
        'visM': round(value, 0),
        'visLevel': _vis_level(value),
        'nearestKm': round(ranked[0][0], 1),
        'contributors': [{'station': s['station'], 'distanceKm': round(d, 1),
                          'visM': s['observed']['visM']} for d, s in picked],
    }


''' + anchor
if anchor not in text:
    raise SystemExit('_idw 锚点不存在')
if '_idw_visibility' not in text:
    text = text.replace(anchor, helper, 1)

# ---- 2) _corridor_row 增加中点能见度 ----
old = """    max_p = max(probs)
    mean_p = sum(probs) / len(probs)"""
new = """    max_p = max(probs)
    mean_p = sum(probs) / len(probs)
    # 0.11.7（B）：走廊**中点**的能见度。取 samples 的中间那一段 —— 走廊是线，
    # 用中点代表整条线是近似，但足以回答"这条走廊被雾罩住了吗"。
    mid = samples[len(samples) // 2]
    visibility = _idw_visibility(mid['x'], mid['y'], field_payload)"""
if old not in text:
    raise SystemExit('max_p 锚点不存在')
text = text.replace(old, new, 1)

# 在返回里加字段（找到 _corridor_row 的 return dict）
old = """        'verdict': verdict,"""
new = """        'verdict': verdict,
        # 0.11.7（B）：能见度三档。`visM` 是中点插值值，`visNearestKm` 是最近站距 ——
        # 离站越远越不可信，这个数要让调用方看得见。
        'visM': visibility['visM'],
        'visLevel': visibility['visLevel'],
        'visNearestKm': visibility['nearestKm'],"""
# 只改 _corridor_row 里的那一处（前面 302 行附近）
idx = text.find('def _corridor_row')
if idx < 0:
    raise SystemExit('_corridor_row 不存在')
head, tail = text[:idx], text[idx:]
if "'visM': visibility['visM']" not in tail:
    tail = tail.replace(old, new, 1)
    text = head + tail

# ---- 3) qualityFlags：不再写死"三站" ----
old = """            'ONLY_THREE_AIRPORT_STATIONS',"""
new = """            # 0.11.7：案例已从 3 站扩到 4 站（补大连 ZYTL）。写死"三站"会让读日志的人
            # 以为大连没进来 —— 而它进来了，且是"偏低但不禁飞"的那一档。
            'ONLY_%d_AIRPORT_STATIONS' % len(histories),"""
if old in text:
    text = text.replace(old, new, 1)
    print('qualityFlags 已改成动态站数')

# ---- 4) field 里带 stationVisibility（给地图画影响圈） ----
old = """        payload['replay'] = meta"""
new = """        payload['replay'] = meta
        # 0.11.7（B）：4 个站的实测能见度，给地图画"影响圈"。
        # **只给实测值，不给半径** —— 半径是渲染决策（6/12 km），放前端算，
        # 免得"改个圈大小要重启后端"。
        payload['stationVisibility'] = [
            {'station': s['station'],
             'visM': (s.get('observed') or {}).get('visM'),
             'visLevel': _vis_level((s.get('observed') or {}).get('visM')),
             'observedAt': s.get('observedAt')}
            for s in stations if (s.get('observed') or {}).get('visM') is not None
        ]"""
if old in text:
    text = text.replace(old, new, 1)

V2.write_text(text, encoding='utf-8')
print('B 后端：走廊 visM/visLevel + stationVisibility 已加')
