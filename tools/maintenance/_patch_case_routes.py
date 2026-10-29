# -*- coding: utf-8 -*-
"""把 `case` 查询参数接到 corridors / corridor / counterfactual 三条路由（一次性）。

Java 网关已按 `@RequestParam Map` 原样透传 `/traffic/v2/*` 的 query，
所以 Python 侧接上就等于整条链路通了。
"""
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'backend-python' / 'main.py'
text = PATH.read_text(encoding='utf-8')

pairs = [
    ("@app.get('/traffic/v2/corridors')\n"
     "def traffic_v2_corridors(limit: int = Query(10, ge=1, le=40),\n"
     "                         mode: str = Query('CAR', pattern='^(CAR|DELIVERY)$')):\n"
     "    from traffic import v2 as traffic_v2\n"
     "    return traffic_v2.corridors(limit=limit, mode=mode)",
     "@app.get('/traffic/v2/corridors')\n"
     "def traffic_v2_corridors(limit: int = Query(10, ge=1, le=40),\n"
     "                         mode: str = Query('CAR', pattern='^(CAR|DELIVERY)$'),\n"
     "                         case: str = Query('')):\n"
     "    from traffic import v2 as traffic_v2\n"
     "    return traffic_v2.corridors(limit=limit, mode=mode, case_id=case or None)"),
    ("@app.get('/traffic/v2/corridor/{route_id}')\n"
     "def traffic_v2_corridor(route_id: str):\n"
     "    from traffic import v2 as traffic_v2\n"
     "    return traffic_v2.corridor(route_id)",
     "@app.get('/traffic/v2/corridor/{route_id}')\n"
     "def traffic_v2_corridor(route_id: str, case: str = Query('')):\n"
     "    from traffic import v2 as traffic_v2\n"
     "    return traffic_v2.corridor(route_id, case_id=case or None)"),
    ("                              policy: str = Query('balanced', pattern='^(conservative|balanced|efficiency)$')):\n"
     "    from traffic import v2 as traffic_v2\n"
     "    return traffic_v2.counterfactual(seed=seed, scenario=scenario, policy=policy)",
     "                              policy: str = Query('balanced', pattern='^(conservative|balanced|efficiency)$'),\n"
     "                              case: str = Query('')):\n"
     "    from traffic import v2 as traffic_v2\n"
     "    return traffic_v2.counterfactual(seed=seed, scenario=scenario, policy=policy,\n"
     "                                     case_id=case or None)"),
]

for old, new in pairs:
    if old not in text:
        raise SystemExit('锚点不存在：\n' + old[:160])
    text = text.replace(old, new, 1)

PATH.write_text(text, encoding='utf-8')
print('patched main.py')
