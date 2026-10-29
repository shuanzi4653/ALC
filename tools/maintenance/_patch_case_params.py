# -*- coding: utf-8 -*-
"""把 case_id 接到 v2 的四个入口（一次性补丁，执行完即可删除）。

改的是签名与取场方式，不是数值逻辑：
  corridors(limit, mode, case_id)  /  corridor(route_id, case_id)  /
  counterfactual(seed, scenario, policy, case_id)  /  overview(seed, scenario, case_id)
每个函数里原来只有一处 `field()`，改成 `field(case_id=case_id)`。
"""
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'backend-python' / 'traffic' / 'v2.py'
text = PATH.read_text(encoding='utf-8')

pairs = [
    ("def corridors(limit: int = 10, mode: str = 'CAR') -> Dict[str, Any]:\n    field_payload = field()",
     "def corridors(limit: int = 10, mode: str = 'CAR',\n              case_id: Optional[str] = None) -> Dict[str, Any]:\n"
     "    field_payload = field(case_id=case_id)"),
    ("def corridor(route_id: str) -> Dict[str, Any]:\n    field_payload = field()",
     "def corridor(route_id: str, case_id: Optional[str] = None) -> Dict[str, Any]:\n"
     "    field_payload = field(case_id=case_id)"),
    ("def counterfactual(seed: int = 42, scenario: str = 'live', policy: str = 'balanced') -> Dict[str, Any]:\n"
     "    session = traffic.session(seed, scenario)",
     "def counterfactual(seed: int = 42, scenario: str = 'live', policy: str = 'balanced',\n"
     "                   case_id: Optional[str] = None) -> Dict[str, Any]:\n"
     "    session = traffic.session(seed, scenario)"),
    ("    routes = _flight_routes(network)\n    field_payload = field()",
     "    routes = _flight_routes(network)\n    field_payload = field(case_id=case_id)"),
    ("def overview(seed: int = 42, scenario: str = 'live') -> Dict[str, Any]:",
     "def overview(seed: int = 42, scenario: str = 'live',\n             case_id: Optional[str] = None) -> Dict[str, Any]:"),
]

for old, new in pairs:
    if old not in text:
        raise SystemExit('锚点不存在，未做任何修改：\n' + old[:120])
    text = text.replace(old, new, 1)

PATH.write_text(text, encoding='utf-8')
print('patched', PATH.name)
