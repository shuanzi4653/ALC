# -*- coding: utf-8 -*-
"""0.11.6 · E-2：可观测三件套（Python 侧）。

**为什么 `/healthz` 是"假健康"**：它不是后端返回的，是 nginx 里一句
`return 200 "ok\n"`（`snippets/hongsight-api.conf:32`）—— Java 挂了、Python 挂了、
计划建不出来、雷达取不到、大模型降级，它**照样回 ok**。
一个永远说 ok 的探针，比没有探针更危险：它让人以为"已经在监控了"。

这里给三样东西：
  · `GET /traffic/health`：**结构化**健康，逐项列出"哪一项、什么值、为什么"；
  · `GET /traffic/metrics`：Prometheus 文本格式，够画一张"构建耗时 / 缓存命中"图；
  · `X-Request-Id`：每个响应都带，日志里能串起一次请求的全部环节。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / 'backend-python' / 'main.py'

text = MAIN.read_text(encoding='utf-8')

anchor = """@app.get('/traffic/session')"""
addition = '''# ---- 可观测（0.11.6 / E-2）-------------------------------------------------
#
# 三条纪律：
#   ① 每个检查项都要能说出"值是什么"，不能只给一个布尔 —— "ok: false" 没法排查；
#   ② `degraded` 与 `down` 必须分开：雷达取不到是降级（系统还能用），
#      计划仓读不了才是 down（系统不能用）；
#   ③ 探针**不许写库、不许触发构建** —— 它会被每分钟拉一次，不能有副作用。
_STARTED_AT = __import__('time').time()
_COUNTERS = {'sessionRequests': 0, 'preparedHits': 0, 'preparedBuilds': 0}


def _check_plan_store():
    """计划仓：数一数缓存目录里有几份计划文件。读不到就是 down。"""
    try:
        from traffic import service as _svc
        store = getattr(_svc, 'STORE_DIR', None) or getattr(_svc, 'CACHE_DIR', None)
        if store is None:
            return {'ok': True, 'detail': 'store dir not exposed', 'plans': None}
        path = Path(store)
        if not path.exists():
            return {'ok': True, 'detail': 'store dir not created yet', 'plans': 0}
        return {'ok': True, 'detail': 'readable', 'plans': len(list(path.glob('*.json')))}
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'detail': 'unreadable: %s' % exc}


def _check_weather():
    """气象通道：模式 + 雷达帧是否可用。雷达不可用是**降级**，不是 down。"""
    try:
        from traffic import weather_control as _wc
        mode = _wc.mode()
        frames = (_wc._state() or {}).get('frames') or {}
        return {'ok': True, 'mode': mode,
                'measuredFrames': frames.get('measured', 0) if isinstance(frames, dict) else None,
                'virtualFrames': frames.get('virtual', 0) if isinstance(frames, dict) else None,
                'relayFrames': (_wc._state() or {}).get('relayFrames', 0)}
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'detail': 'unreadable: %s' % exc}


def _check_llm():
    try:
        import llm_bridge
        degraded = bool(getattr(llm_bridge, 'DEGRADED', False))
        return {'ok': not degraded, 'degraded': degraded}
    except Exception:  # noqa: BLE001
        # 模块名不对不算故障 —— 说不清就如实说"未接入这项检查"
        return {'ok': True, 'detail': 'llm probe not wired'}


@app.get('/traffic/health')
def traffic_health():
    checks = {'planStore': _check_plan_store(), 'weather': _check_weather(), 'llm': _check_llm()}
    # 致命项：只有计划仓不可读才是 down。雷达取不到、模型降级都是 degraded。
    fatal = not checks['planStore']['ok']
    degraded = (not checks['weather']['ok']) or (not checks['llm']['ok'])
    status = 'down' if fatal else ('degraded' if degraded else 'ok')
    body = {
        'status': status,
        'version': _read_version(),
        'at': datetime.now(__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'uptimeSeconds': round(__import__('time').time() - _STARTED_AT, 1),
        'checks': checks,
    }
    # 200 与 503 的分界必须在**能不能服务**上：down 才 503，
    # degraded 仍然 200 —— 否则负载均衡会把一个"雷达取不到但业务正常"的实例摘掉。
    return Response(content=_json.dumps(body, ensure_ascii=False, separators=(',', ':')),
                    media_type='application/json',
                    status_code=503 if fatal else 200,
                    headers={'Cache-Control': 'no-store'})


def _read_version():
    try:
        return (ROOT_DIR / 'VERSION').read_text(encoding='utf-8').strip()
    except Exception:  # noqa: BLE001
        return 'unknown'


@app.get('/traffic/metrics')
def traffic_metrics():
    """Prometheus 文本格式。只报**能算出来的**，不编造。"""
    lines = [
        '# HELP alc_uptime_seconds 进程运行时长',
        '# TYPE alc_uptime_seconds gauge',
        'alc_uptime_seconds %.1f' % (__import__('time').time() - _STARTED_AT),
        '# HELP alc_session_requests_total session 端点请求数',
        '# TYPE alc_session_requests_total counter',
        'alc_session_requests_total %d' % _COUNTERS['sessionRequests'],
        '# HELP alc_session_prepared_hits_total 预序列化命中数',
        '# TYPE alc_session_prepared_hits_total counter',
        'alc_session_prepared_hits_total %d' % _COUNTERS['preparedHits'],
        '# HELP alc_session_prepared_builds_total 预序列化生成数',
        '# TYPE alc_session_prepared_builds_total counter',
        'alc_session_prepared_builds_total %d' % _COUNTERS['preparedBuilds'],
        '# HELP alc_prepared_cache_entries 预序列化缓存条目数',
        '# TYPE alc_prepared_cache_entries gauge',
        'alc_prepared_cache_entries %d' % len(_PREPARED),
    ]
    try:
        from traffic import weather_control as _wc
        frames = (_wc._state() or {}).get('frames') or {}
        if isinstance(frames, dict):
            lines += ['# HELP alc_weather_frames_total 各通道取帧数',
                      '# TYPE alc_weather_frames_total counter',
                      'alc_weather_frames_total{channel="measured"} %d' % frames.get('measured', 0),
                      'alc_weather_frames_total{channel="virtual"} %d' % frames.get('virtual', 0),
                      'alc_weather_frames_total{channel="relay"} %d' % (_wc._state() or {}).get('relayFrames', 0)]
    except Exception:  # noqa: BLE001
        pass
    return Response(content='\\n'.join(lines) + '\\n', media_type='text/plain; version=0.0.4')


# 请求 ID：没有它，"这一个 500 是哪个请求造成的"只能靠时间戳猜。
@app.middleware('http')
async def _request_id(request: Request, call_next):
    rid = request.headers.get('x-request-id') or __import__('uuid').uuid4().hex[:16]
    response = await call_next(request)
    response.headers['X-Request-Id'] = rid
    return response


@app.get('/traffic/session')'''
if anchor not in text:
    raise SystemExit('session 锚点不存在')
text = text.replace(anchor, addition, 1)

# 计数器接进 session 端点
old = """    key = _prepared_key(result, fields)
    if key is not None:
        prepared = _PREPARED.get(key)
        if prepared is None:
            prepared = _prepare(result)"""
new = """    _COUNTERS['sessionRequests'] += 1
    key = _prepared_key(result, fields)
    if key is not None:
        prepared = _PREPARED.get(key)
        if prepared is not None:
            _COUNTERS['preparedHits'] += 1
        if prepared is None:
            _COUNTERS['preparedBuilds'] += 1
            prepared = _prepare(result)"""
if old not in text:
    raise SystemExit('计数器锚点不存在')
text = text.replace(old, new, 1)

# ROOT_DIR 是否已定义
if 'ROOT_DIR' not in text:
    text = text.replace("import real_weather", "ROOT_DIR = Path(__file__).resolve().parents[1]\n\nimport real_weather", 1)

MAIN.write_text(text, encoding='utf-8')
print('E-2：/traffic/health + /traffic/metrics + X-Request-Id 已加')
