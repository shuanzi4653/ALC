"""What does the live radar channel actually return right now?

The frontend layer is only worth anything if real frames sometimes carry a
hazard. A quiet stratiform-only frame would leave the violet fill layer unproven,
so this prints what the real endpoint gives at this moment and what the derived
tiers look like, without asserting anything about the weather.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from traffic import service  # noqa: E402


def main():
    payload = service.radar_regions(60)
    print('available =', payload.get('available'))
    print('error     =', payload.get('error'))
    print('summary   =', json.dumps(payload.get('summary'), ensure_ascii=False))
    for region in payload.get('regions') or []:
        for key, value in region.items():
            if key in ('field', 'ban', 'caution'):
                kind = value.get('type')
                if kind == 'Polygon':
                    rings = len(value.get('coordinates') or [])
                    print(f'   {key}: Polygon rings={rings}')
                elif kind == 'MultiPolygon':
                    polys = value.get('coordinates') or []
                    print(f'   {key}: MultiPolygon polygons={len(polys)}')
                else:
                    print(f'   {key}: {kind}')
            elif key == 'bands':
                print('    bands:', json.dumps(value, ensure_ascii=False))
            else:
                print(f'    {key}: {value}')
    watch = payload.get('watch')
    if watch:
        print('watch.band =', watch.get('band'), 'areaKm2 =', watch.get('areaKm2'))
        print('watch.field =', watch['field']['type'],
              len(watch['field'].get('coordinates') or []), 'ring(s)')


if __name__ == '__main__':
    main()
