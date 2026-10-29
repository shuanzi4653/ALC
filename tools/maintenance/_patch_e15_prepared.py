# -*- coding: utf-8 -*-
"""0.11.6 · E-1⑤：预序列化 + ETag + Cache-Control。

**先量后改**（2026-10-21 14:45 实测）：

    slim   total=11.8s  size=7.49 MB  ttfb=1.27s
    full   total=42.0s  size=25.3 MB  ttfb=4.04s

`ttfb` 只有 1.3–4 秒，**总时长几乎全在传输**（服务器出口带宽小）。
所以这一刀的定位不是"消掉 13.7 秒"，而是：

  · **省掉每次请求的重新序列化**（`jsonable_encoder` 对 7760 班 × 20 字段是很贵的）；
  · **让第 2 次起命中缓存**（`ETag` + `max-age`），重复刷新从 11.8s 变 0；
  · 根治传输时长要靠 E-1①②③④ 的分页，这一刀只是把它变"可承受"。

**不做**：不在 Python 里手写 gzip。nginx 已经开着 `gzip on`（`gzip_types` 含
`application/json`），手写会造成双重压缩的判断负担；而 nginx 看到上游已带
`Content-Encoding` 就不会再压。**让一层负责一件事。**

**注意**：`BUILDING` 的响应**不进缓存** —— 它是中间态，缓存等于把"还没算完"
固化成"就是没算完"。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / 'backend-python' / 'main.py'

text = MAIN.read_text(encoding='utf-8')

# ---- 1) 导入 ----
old_imp = """from fastapi import FastAPI, HTTPException, Query"""
new_imp = """import hashlib
import json as _json

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response"""
if old_imp not in text:
    raise SystemExit('import 锚点不存在')
text = text.replace(old_imp, new_imp, 1)

# ---- 2) 预序列化缓存 ----
old_fn = """@app.get('/traffic/session')
def traffic_session(seed: int = Query(42, ge=0, le=99999),
                    scenario: str = Query('live', pattern='^(clear|unknown|live)$'),
                    fields: str = Query('slim', pattern='^(slim|full)$')):
    result = traffic_service.session(seed, scenario)
    if fields == 'slim':
        result = _slim_session(result)"""
new_fn = """# ---- 预序列化缓存（0.11.6 / E-1⑤）-----------------------------------------
#
# 键里必须同时含 `fields` 与**工作区的 plan 键**：不同工作区是不同计划，
# 共用一份缓存等于把 A 的计划发给 B（这正是项目纪律里最忌的那种隔离失效）。
# 这里用 `traffic_service.session` 返回的 `fingerprint + baseTime` 参与键，
# 计划一重建，键就变，旧缓存自然不会被命中。
_PREPARED: dict = {}
_PREPARED_LIMIT = 8  # 每个工作区最多留 8 份；超出按插入序淘汰，避免无界增长


def _prepared_key(result, fields):
    if result.get('status') != 'READY':
        return None
    return (result.get('fingerprint'), result.get('seed'), result.get('scenario'),
            result.get('baseTime'), result.get('weatherMode'), fields)


def _prepare(result):
    \"\"\"一次序列化，之后所有请求复用这份 bytes。\"\"\"
    raw = _json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    etag = '"%s"' % hashlib.sha1(raw).hexdigest()[:16]
    return raw, etag


@app.get('/traffic/session')
def traffic_session(request: Request,
                    seed: int = Query(42, ge=0, le=99999),
                    scenario: str = Query('live', pattern='^(clear|unknown|live)$'),
                    fields: str = Query('slim', pattern='^(slim|full)$')):
    result = traffic_service.session(seed, scenario)
    if fields == 'slim':
        result = _slim_session(result)

    key = _prepared_key(result, fields)
    if key is not None:
        prepared = _PREPARED.get(key)
        if prepared is None:
            prepared = _prepare(result)
            if len(_PREPARED) >= _PREPARED_LIMIT:
                _PREPARED.pop(next(iter(_PREPARED)))
            _PREPARED[key] = prepared
        raw, etag = prepared
        # 同一份计划在 10 分钟内不会变（它由 seed+scenario+气象快照决定），
        # 所以允许客户端缓存；`ETag` 负责让"变了"这件事仍然能被发现。
        headers = {'ETag': etag, 'Cache-Control': 'private, max-age=600',
                   'Vary': 'Accept-Encoding'}
        if request.headers.get('if-none-match') == etag:
            return Response(status_code=304, headers=headers)
        return Response(content=raw, media_type='application/json', headers=headers)"""
if old_fn not in text:
    raise SystemExit('session 端点锚点不存在')
text = text.replace(old_fn, new_fn, 1)

MAIN.write_text(text, encoding='utf-8')
print('E-1⑤：预序列化 + ETag + Cache-Control 已加')
