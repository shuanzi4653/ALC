# -*- coding: utf-8 -*-
"""生成全国省级干线（**模拟派生**）：省会/首府代表点之间的最小生成树 + 就近补边。

为什么是模拟
------------
东北三省那 53 条城际走廊是按真实城市对与省界一次次跑 A* 出来的（`traffic/routing.py`）。
全国没有这套城市对与航路数据，硬造 300 多条 A* 走廊既慢又会和"东三省的数不能动"
打架。所以全国层只生成**省级干线**（省会之间的直连示意线），显式标注 `source: SIM`，
只用于全国屏的"有走廊 / 无走廊"和聚合计数，**不参与任何运行计划与裁决**。

输出：`data/traffic/national-corridors.json`
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHINA = ROOT / 'frontend' / 'src' / 'assets' / 'china.json'
OUT = ROOT / 'data' / 'traffic' / 'national-corridors.json'

# 台湾只参与观测（有真实 METAR 站），不生成干线；港澳各连一条到广东。
NO_CORRIDOR = {710000}
HUB_OVERRIDE = {810000: 440000, 820000: 440000}  # 香港/澳门 → 广东


def haversine(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def main():
    payload = json.loads(CHINA.read_text(encoding='utf-8'))
    nodes = {}
    for feature in payload['features']:
        props = feature.get('properties') or {}
        adcode = props.get('adcode')
        centre = props.get('center') or props.get('centroid')
        if not isinstance(adcode, int) or not centre:
            continue
        nodes[adcode] = {
            'adcode': adcode, 'name': props.get('name'),
            'lon': round(float(centre[0]), 4), 'lat': round(float(centre[1]), 4),
        }
    mainland = {code: node for code, node in nodes.items() if code not in NO_CORRIDOR}
    codes = sorted(mainland)

    # Prim 最小生成树
    connected = {codes[0]}
    edges = []
    while len(connected) < len(codes):
        best = None
        for a in connected:
            for b in codes:
                if b in connected:
                    continue
                d = haversine((mainland[a]['lon'], mainland[a]['lat']),
                              (mainland[b]['lon'], mainland[b]['lat']))
                if best is None or d < best[0]:
                    best = (d, a, b)
        distance, a, b = best
        edges.append((a, b, distance))
        connected.add(b)

    # 就近补边：每个节点连最近的 2 个（已在树里的跳过），让干线成网而不是一根藤
    have = {frozenset((a, b)) for a, b, _ in edges}
    for a in codes:
        near = sorted(
            ((haversine((mainland[a]['lon'], mainland[a]['lat']),
                        (mainland[b]['lon'], mainland[b]['lat'])), b)
             for b in codes if b != a))[:2]
        for distance, b in near:
            key = frozenset((a, b))
            if key in have:
                continue
            have.add(key)
            edges.append((a, b, distance))

    # 港澳挂到广东（不参与 MST 的跨海长边）
    for code, hub in HUB_OVERRIDE.items():
        if code in nodes and hub in nodes:
            d = haversine((nodes[code]['lon'], nodes[code]['lat']),
                          (nodes[hub]['lon'], nodes[hub]['lat']))
            edges.append((hub, code, d))

    rows = []
    for index, (a, b, distance) in enumerate(sorted(edges), start=1):
        first, second = mainland.get(a) or nodes[a], mainland.get(b) or nodes[b]
        rows.append({
            'id': f'NAT-{index:03d}',
            'from': first['adcode'], 'to': second['adcode'],
            'fromName': first['name'], 'toName': second['name'],
            'fromLonLat': [first['lon'], first['lat']],
            'toLonLat': [second['lon'], second['lat']],
            'lengthKm': round(distance, 1),
            'source': 'SIM',
            'note': '省级干线（模拟派生）；不参与运行计划与裁决',
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        'generatedAt': '2026-11-10',
        'source': 'SIM',
        'basis': '省会/首府代表点；MST + 就近两条补边；港澳挂广东；台湾不生成干线',
        'count': len(rows),
        'corridors': rows,
    }, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('corridors', len(rows), 'provinces covered',
          len({r['from'] for r in rows} | {r['to'] for r in rows}))


if __name__ == '__main__':
    main()
