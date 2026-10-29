"""Read one live radar payload and print its shape, for frontend wiring.

The frontend consumes ``weather.radar`` and had never been written, so the first
question is what a real frame actually contains -- not what the docstring says.
Run from ``backend-python`` with the project venv.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from traffic import service  # noqa: E402


def describe_geometry(node, label):
    if not isinstance(node, dict):
        return f'{label}: <not a geojson dict> {node!r}'
    kind = node.get('type')
    if kind == 'Polygon':
        rings = len(node.get('coordinates') or [])
        return f'{label}: Polygon rings={rings}'
    if kind == 'MultiPolygon':
        polys = node.get('coordinates') or []
        rings = sum(len(p or []) for p in polys)
        return f'{label}: MultiPolygon polygons={len(polys)} rings={rings}'
    return f'{label}: {kind}'

def main():
    result = service.radar_regions(60)
    print('available =', result.get('available'))
    print('error     =', result.get('error'))
    print('summary   =', json.dumps(result.get('summary'), ensure_ascii=False))
    regions = result.get('regions') or []
    print('regions   =', len(regions))
    for region in regions:
        print('--- region')
        for key, value in region.items():
            if key in ('field', 'ban', 'caution'):
                print('   ', describe_geometry(value, key))
            else:
                print('   ', key, '=', json.dumps(value, ensure_ascii=False)[:400])
    watch = result.get('watch')
    print('watch     =', 'None' if not watch else '')
    if watch:
        for key, value in watch.items():
            if key == 'field':
                print('   ', describe_geometry(value, key))
            else:
                print('   ', key, '=', json.dumps(value, ensure_ascii=False)[:400])


if __name__ == '__main__':
    main()
