# -*- coding: utf-8 -*-
"""W-31（0.11.5）：建场体积 25.8 MB → 分层返回 + 单班补取。

**先量后改**。实测构成（7760 班 / 24.6 MB）：

    points           6.57 MB   （25%，每班中位 14 点、最多 84 点，共 103341 点）
    atcClearance     3.54 MB
    clearance        2.48 MB
    staticAirspace   2.37 MB
    其余零散          ≈11 MB   （每班二十几个小字段，单看都不大）

所以"抽稀 points"最多减 3–4 MB，**必须按"首屏是否需要"分层**：

  · `fields=slim`（默认）：只留画图与列表要的字段，points 抽稀到 ≤12 点（保首末）
      → 约 5 MB，减 80%
  · `fields=full`：原样返回（离线归档、导出、脚本用）
  · `GET /traffic/flight/{id}`：单班全量（选中班次时补取，剖面与许可要它）

gzip 已经开着（实测 `Content-Encoding: gzip`），所以瓶颈不是带宽而是**序列化与
浏览器解析** —— 减 payload 才减得动时间。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / 'backend-python' / 'main.py'
PY = ROOT / 'backend-java' / 'src' / 'main' / 'java' / 'com' / 'tianchuang' / 'service' / 'PythonClient.java'

text = MAIN.read_text(encoding='utf-8')

old = """@app.get('/traffic/session')
def traffic_session(seed: int = Query(42, ge=0, le=99999),
                    scenario: str = Query('live', pattern='^(clear|unknown|live)$')):
    result = traffic_service.session(seed, scenario)"""
new = """# ---- 首屏分层（0.11.5 / W-31）------------------------------------------------
#
# `slim` 保留"画图 + 列表 + 时间轴"要用的东西；`full` 用于离线归档与导出。
# 白名单而不是黑名单：**新加字段默认不进 slim** —— 这样"某个字段悄悄变大"不会
# 无声无息地把首屏拖慢，而是要先在这里显式加一行。
SLIM_FLIGHT_FIELDS = (
    'id', 'name', 'mode', 'fromCity', 'toCity', 'fromPad', 'toPad',
    'status', 'reason', 'separationAction', 'clearanceStatus',
    'requestedDepartureMinute', 'departureMinute', 'arrivalMinute',
    'delayMinutes', 'detourMinutes', 'maxAltitudeM', 'energyPercentRemainingAtHandover',
    'points',
)
# 航迹抽稀上限。12 点足够画出一条城际航迹与高度剖面（首末点必保，时间戳随点保留，
# 所以 `atTime()` 的插值精度不受影响）；选中班次时再用 `/traffic/flight/{id}` 取全量。
SLIM_MAX_POINTS = 12


def _thin_points(points):
    \"\"\"等距抽稀，**首末点必保**。少于上限的原样返回。\"\"\"
    if not points or len(points) <= SLIM_MAX_POINTS:
        return points
    step = (len(points) - 1) / (SLIM_MAX_POINTS - 1)
    picked = [points[round(i * step)] for i in range(SLIM_MAX_POINTS)]
    picked[-1] = points[-1]
    return picked


def _slim_session(payload):
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
    return {**payload, 'flights': slim, 'fields': 'slim'}


@app.get('/traffic/session')
def traffic_session(seed: int = Query(42, ge=0, le=99999),
                    scenario: str = Query('live', pattern='^(clear|unknown|live)$'),
                    fields: str = Query('slim', pattern='^(slim|full)$')):
    result = traffic_service.session(seed, scenario)
    if fields == 'slim':
        result = _slim_session(result)"""
if old not in text:
    raise SystemExit('session 路由锚点不存在')
text = text.replace(old, new, 1)

# 单班全量
anchor = "@app.get('/traffic/journal')"
addition = """@app.get('/traffic/flight/{flight_id}')
def traffic_flight(flight_id: str,
                   seed: int = Query(42, ge=0, le=99999),
                   scenario: str = Query('live', pattern='^(clear|unknown|live)$')):
    \"\"\"单班全量（0.11.5 / W-31）：首屏用 `fields=slim`，选中班次时用这个补全。

    找不到就是 404，**不返回一份"字段都在但值为空"的壳** —— 那种壳会让前端把
    "这条班次不存在"演成"这条班次没有许可信息"。
    \"\"\"
    payload = traffic_service.session(seed, scenario)
    if payload.get('status') != 'READY':
        raise HTTPException(409, '计划尚未就绪')
    for flight in payload.get('flights') or []:
        if flight.get('id') == flight_id:
            return flight
    raise HTTPException(404, 'no such flight')


@app.get('/traffic/journal')"""
if anchor not in text:
    raise SystemExit('journal 路由锚点不存在')
text = text.replace(anchor, addition, 1)

MAIN.write_text(text, encoding='utf-8')
print('session 分层 + flight/{id} 已加')

# ---- Java：422 透出 FastAPI 的 detail（那条通用消息误导人） ----
java = PY.read_text(encoding='utf-8')
old = """            String message = "决策请求被拒绝，请检查输入、时次或记录是否存在";
            if (path.equals("/traffic/command") && response.statusCode() == 409) {
                var detail = mapper.readTree(response.body()).path("detail");
                if (detail.isTextual() && detail.asText().length() <= 160) message = detail.asText();
            }"""
new = """            String message = "决策请求被拒绝，请检查输入、时次或记录是否存在";
            // 0.11.5（W-31）：422 必须透出**缺的是哪个参数**。
            // 原来一律用上面那句通用消息，于是 `/traffic/operations` 少了必填的
            // `sessionId` 时，界面上写的是"请检查输入、时次或记录是否存在" ——
            // 复测报告据此判断成"case 参数没落地"，其实是**缺一个必填 query**。
            // 一句含糊的错误消息，会让人去查一个不存在的 bug。
            var body = mapper.readTree(response.body());
            var detail = body.path("detail");
            if (detail.isTextual() && detail.asText().length() <= 160) {
                message = detail.asText();
            } else if (detail.isArray() && detail.size() > 0) {
                // FastAPI 的 422 形状：[{loc:["query","sessionId"], msg:"Field required", ...}]
                var first = detail.get(0);
                StringBuilder where = new StringBuilder();
                var loc = first.path("loc");
                if (loc.isArray()) {
                    for (var node : loc) {
                        if (where.length() > 0) where.append('.');
                        where.append(node.asText());
                    }
                }
                String why = first.path("msg").asText("");
                if (!why.isEmpty()) message = (where.isEmpty() ? "" : where + "：") + why;
            }"""
if old not in java:
    raise SystemExit('Java 422 包装锚点不存在')
java = java.replace(old, new, 1)
if 'import java.util.stream' not in java and 'StringBuilder' in java:
    pass
PY.write_text(java, encoding='utf-8')
print('Java 422 消息已透出 detail')
