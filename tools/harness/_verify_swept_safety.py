"""Decide the sliver question by testing under-coverage where it would matter.

The slivers sit on the envelope's own boundary, so a thin/large-extent test is
ambiguous. What actually matters operationally is narrower and testable: does
snapping cause the planner to clear a trajectory that the exact envelope would
have blocked?

`swept()` is only ever consumed as a routing obstacle. So this runs the whole
plan with snapping on and with snapping off and compares every accepted flight's
trajectory against the *unsnapped* envelope for that flight's own window. If no
trajectory enters the exact envelope, snapping changed no safety outcome.

That is the assertion worth shipping, and it is the same form as the existing
trajectory-vs-risk-surface guard.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from shapely.geometry import LineString  # noqa: E402

from traffic import service  # noqa: E402
from traffic.weather import NetworkWeather  # noqa: E402

service.network()

# --- run 1: the shipped (snapped) behaviour --------------------------------
snapped = service.simulate(seed=42, scenario='moving')

# --- run 2: exact windows, produced by disabling the snap ------------------
from traffic import weather as weather_module  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


real_floor, real_ceil = weather_module.swept_bin_floor, weather_module.swept_bin_ceil
weather_module.swept_bin_floor = lambda value: int(value)
weather_module.swept_bin_ceil = lambda value: int(value)
NetworkWeather._swept_snapped.cache_clear()
try:
    exact = service.simulate(seed=42, scenario='moving')
finally:
    weather_module.swept_bin_floor, weather_module.swept_bin_ceil = real_floor, real_ceil
    NetworkWeather._swept_snapped.cache_clear()

print('=== plan-level comparison ===', flush=True)
print(f'  snapped accepted/closed: {snapped["stats"]["accepted"]} / {snapped["stats"]["closed"]}', flush=True)
print(f'  exact   accepted/closed: {exact["stats"]["accepted"]} / {exact["stats"]["closed"]}', flush=True)
print(f'  detours snapped/exact  : {snapped["stats"]["detours"]} / {exact["stats"]["detours"]}', flush=True)
same_ids = ({f['id'] for f in snapped['flights'] if f['status'] == 'SCHEDULED'}
            == {f['id'] for f in exact['flights'] if f['status'] == 'SCHEDULED'})
print(f'  identical accepted set : {same_ids}', flush=True)

# --- the safety question: does any accepted trajectory enter the exact env --
weather = NetworkWeather(42, 'moving')
raw = NetworkWeather._swept_snapped.__wrapped__
worst = 0.0
checked = 0
for flight in snapped['flights']:
    if flight['status'] != 'SCHEDULED' or not flight['points']:
        continue
    points = flight['points']
    start = points[0][3]
    end = points[-1][3]
    window = (int(start // 5), -(-int(end) // 5))
    exact_env = raw(weather, *window)
    if exact_env.is_empty:
        continue
    checked += 1
    line = LineString([(p[0], p[1]) for p in points])
    overlap = line.intersection(exact_env).length
    worst = max(worst, overlap)

print(f'\n=== trajectory vs UNSNAPPED envelope at its own minute ===', flush=True)
print(f'  trajectories checked      : {checked}', flush=True)
print(f'  worst intrusion length    : {worst:.6f} m', flush=True)
print(f'  verdict                   : '
      f'{"snapping changed no safety outcome" if worst < 1.0 else "UNDER-COVERED"}', flush=True)
