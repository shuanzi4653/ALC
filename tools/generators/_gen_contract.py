"""Generate contracts/traffic-v1.3.openapi.json from the live FastAPI application."""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ROOT = Path(ROOT)
import json


import main  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


spec = main.app.openapi()
paths = {key: value for key, value in spec['paths'].items() if key.startswith('/traffic')}

used = set()


def walk(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == '$ref':
                used.add(value.rsplit('/', 1)[-1])
            walk(value)
    elif isinstance(node, list):
        for value in node:
            walk(value)


all_schemas = spec.get('components', {}).get('schemas', {})
walk(paths)
kept = {key: value for key, value in all_schemas.items() if key in used}
changed = True
while changed:
    changed = False
    for value in list(kept.values()):
        before = set(used)
        walk(value)
        if used != before:
            changed = True
    kept = {key: value for key, value in all_schemas.items() if key in used}

document = {
    'openapi': spec['openapi'],
    'info': {
        'title': '东北低空交通运行 API',
        'version': '1.3.0',
        'description': (
            'V1.3 交通运行合同：时间字段分离、已声明高度层、起降与交叉资源日历、'
            '配送订单与载具状态。交通数据为模拟生成；气象为公开来源估算或合成场景，'
            '两者在响应中分别标注。'
        ),
    },
    'paths': paths,
    'components': {'schemas': kept},
}
target = ROOT / 'contracts' / 'traffic-v1.3.openapi.json'
target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('paths:', sorted(paths))
print('schemas:', sorted(kept))
print('written:', target)
