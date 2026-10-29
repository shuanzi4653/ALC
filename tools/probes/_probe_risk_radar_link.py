"""Measure how the drawn risk zones relate to the measured radar echo, and whether
the radar actually moves any route.

Three questions, answered from the real code paths (no synthesis):

1. Where do the drawn risk cells sit, and are they city-centred discs?
2. Does the radar channel carry >=35 dBZ geometry, and does the planner avoid it?
3. For a *measured* frame, how many flights change path *because of* the radar?

Run: backend-python/.venv/Scripts/python.exe tools/probes/_probe_risk_radar_link.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND  # noqa: E402

from shapely.geometry import shape  # noqa: E402

from traffic import service, weather_control  # noqa: E402


def geom_of(geo):
    if not geo or not geo.get('coordinates'):
        return None
    try:
        g = shape(geo)
    except Exception:
        return None
    return None if g.is_empty else g


print('=== weather_control ===')
print('mode   :', weather_control.mode())
print('status :', json.dumps(weather_control.status(), ensure_ascii=False)[:400])
print()

print('=== radar channel (one frame, minute 60) ===')
regions = service.radar_regions(60)
print('available :', regions.get('available'), '| mode', regions.get('mode'), '| error', regions.get('error'))
print('summary   :', json.dumps(regions.get('summary'), ensure_ascii=False)[:600])
for rec in regions.get('regions') or []:
    field = geom_of(rec.get('field'))
    ban = geom_of(rec.get('ban'))
    caution = geom_of(rec.get('caution'))
    print(f"  {rec['id']} source={rec.get('source')} fieldKm2={0 if field is None else round(field.area/1e6,1)}"
          f" banKm2={0 if ban is None else round(ban.area/1e6,1)}"
          f" cautionKm2={0 if caution is None else round(caution.area/1e6,1)}")
    if field is not None:
        print('    field bounds:', [round(v, 3) for v in field.bounds])
watch = geom_of((regions.get('watch') or {}).get('field'))
print('watch     :', 'none' if watch is None else f"{round(watch.area/1e6,1)} km2")
print()

print('=== drawn risk cells (weather frame, minute 60) ===')
frame = service.weather_frame(42, 'live', 60)
print('scenario', frame.get('scenario'), 'provider', frame.get('provider'), 'dataType', frame.get('dataType'))
cities = {c['id']: c for c in service.network()['cities']}
for cell in frame.get('cells') or []:
    f = geom_of(cell.get('field'))
    b = geom_of(cell.get('ban'))
    cx, cy = f.centroid.x, f.centroid.y
    city = cities.get(cell.get('cityId'))
    dx = dy = None
    if city:
        from weather.geometry import project
        px, py = project(tuple(city['coordinate']))
        dx, dy = round(cx - px), round(cy - py)
    print(f"  {cell['id']} kind={cell.get('kind')} city={cell.get('cityId')}"
          f" fieldKm2={round(f.area/1e6,1)} banKm2={0 if b is None else round(b.area/1e6,1)}"
          f" centre=({round(cx)},{round(cy)}) offset-from-city=({dx},{dy})")
print()

print('=== plan: does the radar move any route? ===')
plan = service.simulate(seed=42, scenario='live')
print('radarAvoidance:', json.dumps(plan.get('radarAvoidance'), ensure_ascii=False)[:500])
stats = plan['stats']
print('flights', stats['flights'], 'accepted', stats['accepted'], 'closed', stats['closed'], 'detours', stats['detours'])
print('closedByClosureReason:', json.dumps(stats.get('closedByClosureReason'), ensure_ascii=False)[:400])
print('WEATHER_DETOUR count:', sum(1 for f in plan['flights'] if f['reason'] == 'WEATHER_DETOUR'))
