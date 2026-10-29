"""How widespread is "valid in metres, invalid once published"?

The radar payload publishes self-intersecting polygons because the inverse
(AEQD -> lon/lat) projection introduces a crossing that is not present in the
projected geometry. Before fixing one call site it is worth knowing whether the
fault is local to the radar channel or shared by every geometry the API
publishes -- the fix belongs at whichever layer is actually responsible.

This probe walks every geometry the operator can see and reports validity.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend-python'))

from shapely.geometry import shape  # noqa: E402
from shapely.validation import explain_validity  # noqa: E402

from traffic import service, weather_control  # noqa: E402


def check(label, payload, bucket):
    total = bad = 0
    for key, value in (payload or {}).items():
        if not isinstance(value, dict) or 'type' not in value:
            continue
        if value.get('type') in ('Point', 'MultiPoint', 'LineString', 'MultiLineString'):
            continue
        if not value.get('coordinates'):
            continue
        total += 1
        geometry = shape(value)
        if not geometry.is_valid:
            bad += 1
            bucket.setdefault(label, []).append(
                f'{key}: {explain_validity(geometry)[:60]}')
    return total, bad


def main():
    bucket = {}
    for mode in ('measured', 'virtual'):
        weather_control.set_mode(mode)
        for minute in (0, 60, 120, 180, 240, 300, 360, 420, 480):
            frame = service.weather_frame(42, 'live', minute)
            for cell in frame.get('cells') or []:
                for tier in ('field', 'ban', 'caution'):
                    geometry = shape(cell[tier])
                    if geometry.is_empty:
                        continue
                    bucket.setdefault(f'cells.{tier}', [])
                    if not geometry.is_valid:
                        bucket[f'cells.{tier}'].append(f'min{minute} invalid')
            radar = frame.get('radar') or {}
            for region in radar.get('regions') or []:
                for tier in ('field', 'ban', 'caution'):
                    geometry = shape(region[tier])
                    if geometry.is_empty:
                        continue
                    bucket.setdefault(f'radar.{tier}', [])
                    if not geometry.is_valid:
                        bucket[f'radar.{tier}'].append(f'{mode} min{minute} invalid')
            watch = radar.get('watch')
            if watch:
                bucket.setdefault('radar.watch', [])
                if not shape(watch['field']).is_valid:
                    bucket['radar.watch'].append(f'{mode} min{minute} invalid')
    airspace = service.static_airspace()
    for volume in airspace.get('volumes') or []:
        geometry = shape(volume['geometry'])
        if geometry.is_empty:
            continue
        bucket.setdefault('staticAirspace', [])
        if not geometry.is_valid:
            bucket['staticAirspace'].append(f"{volume.get('id')} invalid")
    print('=== published geometry validity (across 2 modes x 9 minutes) ===')
    for layer in sorted(bucket):
        rows = bucket[layer]
        print(f'{layer:16s} problems={len(rows):3d}  {rows[:3]}')


if __name__ == '__main__':
    main()
