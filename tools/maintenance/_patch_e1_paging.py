# -*- coding: utf-8 -*-
"""0.11.6 · E-1①②③：session 分页化 + 两个新接口。

**先看清原来的病**：`session` 一次下发 7760 条，slim 之后仍有 7.15 MB / 11.8 s。
`points` 只占 28%，剩下的大头是"**条数**"本身 —— 瘦身救不了它，只能减少条数。

三处改动：

  ① `session` 的 `flights` 只给**首页 100 条**，另给 `flightStats` 告诉前端
     "总共多少、按什么分布"。原来前端靠 `flights.length` 当总数，一旦截断就会
     把 100 当成全部 —— 所以**必须同时给 stats**，不能只截断。
  ② 新增 `GET /traffic/flights?page=&size=&status=&mode=&corridor=` 翻页。
  ③ 新增 `GET /traffic/flights/points?ids=`（上限 50）按需取完整航迹。

**地图怎么办**：地图不能只画 100 条（会显得空）。所以 `session` 额外给
`mapFlights`（600 条，只含画图要的 6 个字段 + 抽稀到 6 点的航迹）。它和
`flights` 是**两个用途**，不共用：前者给列表与选中，后者给地图铺满。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / 'backend-python' / 'main.py'

text = MAIN.read_text(encoding='utf-8')

# ---- 1) 常量 ----
old = """SLIM_MAX_POINTS = 8"""
new = """SLIM_MAX_POINTS = 8
# 首屏列表条数。台账要翻页，地图另有 `mapFlights`，所以这里不需要很多。
SESSION_FLIGHTS = 100
# 地图铺满用的条数。600 条 × 6 点 ≈ 0.7 MB —— 太少地图会空，太多就回到老问题。
MAP_FLIGHTS = 600
MAP_POINTS = 6"""
if old not in text:
    raise SystemExit('SLIM_MAX_POINTS 锚点不存在')
text = text.replace(old, new, 1)

# ---- 2) _slim_session：截断 + stats + mapFlights ----
old = """def _slim_session(payload):
    \"\"\"按白名单裁剪。**不改原对象**（它是缓存里那一份，改了就污染下一次请求）。\"\"\"
    if payload.get('status') != 'READY':
        return payload
    flights = payload.get('flights') or []
    slim = []
    for flight in flights:
        row = {key: flight[key] for key in SLIM_FLIGHT_FIELDS if key in flight}
        if 'points' in row:
            row['points'] = _thin_points(row['points'])
        # 前端据它决定"要不要补取单班"—— 缺字段时它必须知道这是裁剪过的，
        # 而不是"这份计划本来就没有许可信息"。
        row['slim'] = True
        slim.append(row)
    return {**payload, 'flights': slim, 'fields': 'slim'}"""
new = """def _slim_row(flight, max_points=SLIM_MAX_POINTS):
    row = {key: flight[key] for key in SLIM_FLIGHT_FIELDS if key in flight}
    if 'points' in row:
        row['points'] = _thin_points(row['points'], max_points)
    # 前端据它决定"要不要补取单班"—— 缺字段时它必须知道这是裁剪过的，
    # 而不是"这份计划本来就没有许可信息"。
    row['slim'] = True
    return row


def _slim_session(payload):
    \"\"\"按白名单裁剪 + 截断到首页条数。**不改原对象**（它是缓存里那一份）。\"\"\"
    if payload.get('status') != 'READY':
        return payload
    flights = payload.get('flights') or []

    # ① 首页条数：只给前 SESSION_FLIGHTS 条
    slim = [_slim_row(flight) for flight in flights[:SESSION_FLIGHTS]]

    # ② 地图铺满用的轻量行（只留画图要的字段，航迹再抽稀到 6 点）
    map_rows = []
    for flight in flights[:MAP_FLIGHTS]:
        row = {
            'id': flight.get('id'), 'mode': flight.get('mode'),
            'fromCity': flight.get('fromCity'), 'toCity': flight.get('toCity'),
            'status': flight.get('status'), 'departureMinute': flight.get('departureMinute'),
            'arrivalMinute': flight.get('arrivalMinute'),
            'points': _thin_points(flight.get('points') or [], MAP_POINTS),
            'mapOnly': True,
        }
        map_rows.append(row)

    # ③ 计数必须**单独给**：前端原来拿 `flights.length` 当总数，
    #    一旦截断，100 就会被当成"全部只有 100 条"。
    by_status, by_mode = {}, {}
    for flight in flights:
        by_status[flight.get('status') or 'UNKNOWN'] = by_status.get(flight.get('status') or 'UNKNOWN', 0) + 1
        by_mode[flight.get('mode') or 'UNKNOWN'] = by_mode.get(flight.get('mode') or 'UNKNOWN', 0) + 1
    stats = {
        'total': len(flights),
        'returned': len(slim),
        'byStatus': by_status,
        'byMode': by_mode,
        'pageSize': SESSION_FLIGHTS,
        'mapReturned': len(map_rows),
        'truncated': len(flights) > len(slim),
    }

    return {**payload, 'flights': slim, 'mapFlights': map_rows,
            'flightStats': stats, 'fields': 'slim'}"""
if old not in text:
    raise SystemExit('_slim_session 锚点不存在')
text = text.replace(old, new, 1)

# ---- 3) _thin_points 支持自定义上限 ----
old = """def _thin_points(points):
    \"\"\"等距抽稀，**首末点必保**。少于上限的原样返回。\"\"\"
    if not points or len(points) <= SLIM_MAX_POINTS:
        return points
    step = (len(points) - 1) / (SLIM_MAX_POINTS - 1)
    picked = [points[round(i * step)] for i in range(SLIM_MAX_POINTS)]"""
new = """def _thin_points(points, max_points=SLIM_MAX_POINTS):
    \"\"\"等距抽稀，**首末点必保**。少于上限的原样返回。\"\"\"
    if not points or len(points) <= max_points:
        return points
    step = (len(points) - 1) / (max_points - 1)
    picked = [points[round(i * step)] for i in range(max_points)]"""
if old not in text:
    raise SystemExit('_thin_points 锚点不存在')
text = text.replace(old, new, 1)

# ---- 4) 两个新接口（放在 flight/{id} 之前，避免被路径参数抢先匹配） ----
old = """@app.get('/traffic/flight/{flight_id}')"""
new = """@app.get('/traffic/flights')
def traffic_flights(page: int = Query(1, ge=1, le=1000),
                    size: int = Query(100, ge=1, le=500),
                    status: str = Query('', max_length=32),
                    mode: str = Query('', max_length=16),
                    corridor: str = Query('', max_length=64),
                    seed: int = Query(42, ge=0, le=99999),
                    scenario: str = Query('live', pattern='^(clear|unknown|live)$')):
    \"\"\"台账翻页（0.11.6 / E-1②）。

    **为什么不复用 `session` 的 `flights`**：那是"首屏那 100 条"，翻页要的是全量
    里的一段。两者用途不同，共用一个字段就会互相拉扯 —— 首屏想看 100 条，
    台账想翻到第 70 页，谁也不该改谁。
    \"\"\"
    payload = traffic_service.session(seed, scenario)
    if payload.get('status') != 'READY':
        raise HTTPException(409, '计划尚未就绪')
    rows = payload.get('flights') or []
    if status:
        rows = [f for f in rows if (f.get('status') or '') == status]
    if mode:
        rows = [f for f in rows if (f.get('mode') or '') == mode]
    if corridor:
        rows = [f for f in rows if (f.get('corridorId') or '') == corridor]
    total = len(rows)
    start = (page - 1) * size
    window = rows[start:start + size]
    return {
        'page': page, 'size': size, 'total': total,
        'pages': (total + size - 1) // size if size else 0,
        'items': [_slim_row(flight) for flight in window],
        # 明确告诉调用方"这一页是裁剪过的"，别把 100 字段当全量
        'slim': True,
    }


@app.get('/traffic/flights/points')
def traffic_flights_points(ids: str = Query('', max_length=2000),
                           seed: int = Query(42, ge=0, le=99999),
                           scenario: str = Query('live', pattern='^(clear|unknown|live)$')):
    \"\"\"按 id 批量取**完整航迹**（0.11.6 / E-1③）。

    上限 50 条：这不是为了省事，是为了让调用方**别把"按需取"用成"分批取全量"** ——
    每次 50 条、翻 156 次，就等于把 7760 条又拉了一遍，只是慢 156 倍。
    超过上限返回 400，并说明上限是多少。
    \"\"\"
    wanted = [part.strip() for part in (ids or '').split(',') if part.strip()]
    if not wanted:
        raise HTTPException(400, 'ids 不能为空')
    if len(wanted) > 50:
        raise HTTPException(400, '一次最多 50 条（收到 %d 条）。按需取，不要分批拉全量' % len(wanted))
    payload = traffic_service.session(seed, scenario)
    if payload.get('status') != 'READY':
        raise HTTPException(409, '计划尚未就绪')
    index = {f.get('id'): f for f in (payload.get('flights') or [])}
    found = {}
    for flight_id in wanted:
        flight = index.get(flight_id)
        if flight is not None:
            found[flight_id] = {'id': flight_id, 'points': flight.get('points') or []}
    return {'requested': len(wanted), 'found': len(found), 'items': found,
            'missing': [i for i in wanted if i not in found]}


@app.get('/traffic/flight/{flight_id}')"""
if old not in text:
    raise SystemExit('flight/{id} 锚点不存在')
text = text.replace(old, new, 1)

MAIN.write_text(text, encoding='utf-8')
print('E-1①②③：session 截断 + flightStats + mapFlights + /flights + /flights/points')
