# -*- coding: utf-8 -*-
"""0.11.7 · F-2 后端 + B 载荷：`/traffic/weather` 支持 case。

## 这次修的是"后端静默忽略 case"

复测报告抓到的自相矛盾：案例页左侧说 2025-01-05 大雾 997.8 m，右侧地图是今天的天气，
底部写着"低能见度：本帧无"。两层原因：

  · 前端 weather 请求**没带 case**（`TrafficWorkbench:426`）；
  · 后端 `traffic_weather(seed, scenario, minute, cityId)` **签名里就没有 case**
    —— FastAPI 静默丢弃未知 query，回实时数据。**这比前端忘了传更坏**：
    前端至少有个"忘了"的理由，后端这是"传了也不认还不吭声"。

## 案例模式必须单独一条分支，不能硬塞进实时链

实时链的 `lowVisibility` 由 `fog_tiers(snapshot, city_rows)` 从**36 城市格点**聚类成面。
案例只有 **4 个机场站**（沈阳/大连/长春/哈尔滨），**没有格点场**。所以：

  · `lowVisibility.included = False`，`reason = CASE_OBSERVATION_ONLY`；
  · `detail` 明写"只有 4 站实测，没有城市格点场，因此不产出雾区面"；
  · `stationVisibility` 给 4 站的实测值，**前端按站点画影响圈**（圈是"影响范围示意"，
    不是"实测雾区边界"）。

**`reason` 绝不能是 `NO_LOW_VISIBILITY_READING`** —— 那个值的意思是"读到了、判过了、
这帧没有雾"，而案例是"只有 4 个点、没有面可画"。两者下一步动作相反：
前者继续放行，后者去补数据。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SVC = ROOT / 'backend-python' / 'traffic' / 'service.py'
MAIN = ROOT / 'backend-python' / 'main.py'
WORK = ROOT / 'frontend' / 'src' / 'components' / 'TrafficWorkbench.vue'

svc = SVC.read_text(encoding='utf-8')

# ---- 1) weather_frame 加 case_id 参数 + 前置分流 ----
old = """def weather_frame(seed, scenario, minute, city_id=None):"""
new = """def _case_weather_frame(case_id, minute, city_id=None):
    \"\"\"案例回放的天气帧（0.11.7 / F-2）。

    **不合成任何几何**：只有 4 个站的实测能见度，所以只给点、不给面。
    要画"雾区面"必须有格点场 —— 案例没有，硬造就是编造观测。
    \"\"\"
    from traffic import cases as traffic_cases

    frames = traffic_cases.frames(case_id) or []
    if not frames:
        return {
            'available': False, 'case': case_id,
            'lowVisibility': {'included': False, 'reason': 'CASE_NOT_FOUND',
                              'detail': '案例帧不可用，本帧不产出任何气象几何。'},
            'radar': {'available': False, 'reason': 'CASE_NOT_FOUND'},
            'stationVisibility': [],
        }
    # 推演时刻吸附到最近的案例帧：案例只有 7 帧（每小时），不该插值出中间帧。
    index = 0
    if minute is not None:
        index = max(0, min(len(frames) - 1, int(round(float(minute) / 60.0))))
    frame = frames[index]
    stations = []
    for code, value in frame.items():
        if code == 't' or not isinstance(value, dict):
            continue
        vis = value.get('visM')
        if vis is None:
            continue
        limits = {'ban': 1000.0, 'warn': 5000.0}
        level = 'BAN' if vis <= limits['ban'] else ('CAUTION' if vis <= limits['warn'] else 'CLEAR')
        info = (METAR_STATION_INFO.get(code) or {}) if 'METAR_STATION_INFO' in globals() else {}
        stations.append({
            'station': code,
            'visM': vis, 'visLevel': level,
            'gustMs': value.get('gustMs'),
            'cloudBaseM': value.get('cloudBaseM'),
            'lat': info.get('lat'), 'lon': info.get('lon'),
            'observedAt': frame.get('t'),
        })
    return {
        'available': True,
        'case': case_id,
        'validAt': frame.get('t'),
        'weatherMode': 'measured',
        'frameIndex': index,
        'frameCount': len(frames),
        'lowVisibility': {
            'included': False,
            'reason': 'CASE_OBSERVATION_ONLY',
            'detail': ('本案例只有 %d 个机场站的实测能见度，没有城市格点场，'
                       '因此不产出雾区面 —— 图上按站点画的是**影响范围示意**，'
                       '不是实测雾区边界。' % len(stations)),
            'stations': len(stations),
            'cities': 0,
        },
        'radar': {
            'available': False,
            'reason': 'CASE_NO_RADAR_TILES',
            'detail': '案例不含雷达瓦片，本帧不加入回波避让几何（不拿实时回波冒充历史）。',
        },
        'wind': {'available': bool(stations),
                 'note': '示例：风向风速取自同帧机场站实测。'},
        'stationVisibility': stations,
        'qualityFlags': ['HISTORICAL_REPLAY', 'STATION_OBSERVATION_ONLY_NO_GRID'],
    }


def weather_frame(seed, scenario, minute, city_id=None, case_id=None):"""
if old not in svc:
    raise SystemExit('weather_frame 锚点不存在')
svc = svc.replace(old, new, 1)

# 在函数体最前面分流
old2 = """    \"\"\"The weather picture for one view instant."""
idx = svc.find(old2, svc.find('def weather_frame('))
if idx < 0:
    raise SystemExit('weather_frame docstring 找不到')
# 找到 docstring 结束后，插入分流
doc_end = svc.find('\"\"\"', idx + len(old2))
if doc_end < 0:
    raise SystemExit('docstring 结束找不到')
insert_at = doc_end + len('\"\"\"')
svc = svc[:insert_at] + """
    # 0.11.7（F-2）：案例走**独立分支**。硬塞进实时链会有两个后果：
    # 一是 lowVisibility 由 36 城市格点聚类，案例只有 4 站、算不出面；
    # 二是雷达图层会拿实时回波冒充历史（比没有更糟）。
    if case_id:
        return _case_weather_frame(case_id, minute, city_id)
""" + svc[insert_at:]
SVC.write_text(svc, encoding='utf-8')
print('① service.weather_frame 支持 case（独立分支）')

# ---- 2) main.py：/traffic/weather 加 case ----
m = MAIN.read_text(encoding='utf-8')
old3 = """def traffic_weather(seed: int = Query(42, ge=0, le=99999),
                    scenario: str = Query('live', pattern='^(clear|unknown|live)$'),
                    minute: float = Query(30, ge=0, le=480), cityId: str | None = None):
    try:
        return traffic_service.weather_frame(seed, scenario, minute, cityId)"""
new3 = """def traffic_weather(seed: int = Query(42, ge=0, le=99999),
                    scenario: str = Query('live', pattern='^(clear|unknown|live)$'),
                    minute: float = Query(30, ge=0, le=480), cityId: str | None = None,
                    case: str | None = Query(None, max_length=64)):
    # 0.11.7（F-2）：**案例必须传下去**。原来这个签名里没有 `case`，
    # FastAPI 静默丢弃未知 query → 案例页拿到实时天气，与左侧 2025 年的结论同屏矛盾。
    try:
        return traffic_service.weather_frame(seed, scenario, minute, cityId, case or None)"""
if old3 not in m:
    raise SystemExit('traffic_weather 锚点不存在')
m = m.replace(old3, new3, 1)
MAIN.write_text(m, encoding='utf-8')
print('② main.py：/traffic/weather 接受 case')

# ---- 3) 前端：weather 请求带 case ----
w = WORK.read_text(encoding='utf-8')
old4 = "try{const value=await requestJson(`/api/traffic/weather?seed=${session.value.seed}&scenario=${session.value.scenario}&minute=${t}${city.value?'&cityId='+encodeURIComponent(city.value):''}`)"
new4 = "try{const value=await requestJson(`/api/traffic/weather?seed=${session.value.seed}&scenario=${session.value.scenario}&minute=${t}${city.value?'&cityId='+encodeURIComponent(city.value):''}${activeCaseId?`&case=${encodeURIComponent(activeCaseId)}`:''}`)"
if old4 not in w:
    raise SystemExit('weather 请求锚点不存在')
w = w.replace(old4, new4, 1)
WORK.write_text(w, encoding='utf-8')
print('③ 前端：weather 请求带 case')
