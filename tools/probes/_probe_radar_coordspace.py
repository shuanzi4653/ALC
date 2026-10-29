"""Print the coordinate space of a live radar payload, and what the map makes of it.

Why this exists: the weather payload carries two serialisation conventions. Model
cells ship in projected metres (AEQD, origin 45N/126E) and the map converts them;
radar regions/watch ship as EPSG:4326 lon/lat and must NOT be converted. On
2026-09-23 the map converted both, which collapsed a Heilongjiang-sized echo to a
~2e-6 degree speck at (126.0016, 45.0005): the layer drew, but invisibly.

What is reproducible here is the CONVENTION, not the numbers: the live mosaic
moves with the clock, so the storm's coordinates differ run to run. What must
never differ is that region coordinates are degrees in NE China, and that the
projection origin (126, 45) does not appear in them.

Run from ``backend-python`` with the project venv.
"""
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# The traffic package lives under backend-python/, not at the repo root, and
# running this file directly puts tools/probes on sys.path -- not the cwd.
sys.path.insert(0, os.path.join(_ROOT, 'backend-python'))
sys.path.insert(0, _ROOT)

from traffic import service  # noqa: E402

# The AEQD origin used by frontend/src/traffic/geography.js.
ORIGIN_LON, ORIGIN_LAT = 126.0, 45.0
# Plausible bounds of the operating area (NE China plus margin).
LON_RANGE = (100.0, 150.0)
LAT_RANGE = (30.0, 60.0)


def vertices(node):
    """Every position of a GeoJSON geometry, flattened."""
    out = []
    if not isinstance(node, dict):
        return out

    def walk(value):
        if isinstance(value, list) and value and isinstance(value[0], (int, float)):
            out.append((float(value[0]), float(value[1])))
            return
        if isinstance(value, list):
            for item in value:
                walk(item)
    walk(node.get('coordinates') or [])
    return out


def describe(label, geometry):
    pts = vertices(geometry)
    if not pts:
        print(f'{label:<22} <empty>')
        return None
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    box = {
        'type': geometry.get('type'),
        'vertices': len(pts),
        'first': pts[0],
        'lon': [min(lons), max(lons)],
        'lat': [min(lats), max(lats)],
        'spanLon': max(lons) - min(lons),
        'spanLat': max(lats) - min(lats),
    }
    in_range = all(LON_RANGE[0] <= x <= LON_RANGE[1] for x in lons) and \
        all(LAT_RANGE[0] <= y <= LAT_RANGE[1] for y in lats)
    box['looksGeographic'] = in_range
    # A geometry wrongly re-projected from degrees lands on the origin.
    box['atProjectionOrigin'] = abs(min(lons) - ORIGIN_LON) < 0.01 and abs(min(lats) - ORIGIN_LAT) < 0.01
    print(f'{label:<22} {json.dumps(box, ensure_ascii=False)}')
    return box


def main():
    result = service.radar_regions(60)
    print('available =', result.get('available'), '| error =', result.get('error'))
    print('summary   =', json.dumps(result.get('summary'), ensure_ascii=False))
    regions = result.get('regions') or []
    print('regions   =', len(regions))
    boxes = []
    for region in regions:
        print(f"--- region {region.get('id')} source={region.get('source')}")
        for key in ('field', 'ban', 'caution'):
            box = describe(key, region.get(key) or {})
            if box:
                boxes.append(box)
    watch = result.get('watch')
    if watch:
        print(f"--- watch {watch.get('id')}")
        box = describe('watch.field', watch.get('field') or {})
        if box:
            boxes.append(box)

    if not boxes:
        print('VERDICT: 本帧没有可绘制的雷达几何，无法判定坐标空间（不是失败，是没有样本）')
        return
    geographic = [b for b in boxes if b['looksGeographic']]
    print(f'VERDICT: {len(geographic)}/{len(boxes)} 个几何在经纬度范围内（作业区 {LON_RANGE} x {LAT_RANGE}）')
    for box in boxes:
        assert box['looksGeographic'], f"雷达几何不是经纬度: {box}"
        assert not box['atProjectionOrigin'], f"雷达几何落在投影原点，疑似被二次投影: {box}"
    print('VERDICT: 全部通过 —— 后端给出的雷达几何确为 EPSG:4326，前端不得再转换')


if __name__ == '__main__':
    main()
