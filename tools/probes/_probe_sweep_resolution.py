"""How fine must the virtual radar sweep be before the plan stops missing the storm?

``RADAR_SWEEP_STRIDE_MINUTES`` is 60, but the virtual echo moves ~50 km in that
hour while the whole field is only ~100-150 km across. The union of two sampled
positions therefore leaves a gap roughly one storm wide, and the intermediate
minutes -- which is where every flight actually is -- are not covered.

This probe is the A/B that decides the fix: it rebuilds the same plan at several
strides and reports, for each, the build cost and the three numbers the operator
sees (accepted / weather-closed / detoured). Then it re-runs the minute-by-minute
incursion test so the improvement is measured on the thing the operator reported
(aircraft inside painted echo), not on the obstacle's area.

Run from the repository root:

    backend-python\\.venv\\Scripts\\python.exe tools\\probes\\_probe_sweep_resolution.py
"""
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'backend-python'))

from shapely.geometry import Point  # noqa: E402

from traffic import radar_field, service, weather_control  # noqa: E402

SEED = 42
STRIDES = (60, 30, 20, 10)


def at_minute(points, minute):
    if not points:
        return None
    if minute <= points[0][3]:
        return points[0]
    if minute >= points[-1][3]:
        return points[-1]
    for a, b in zip(points, points[1:]):
        if a[3] <= minute <= b[3]:
            span = b[3] - a[3]
            if span <= 0:
                return a
            ratio = (minute - a[3]) / span
            return tuple(a[i] + (b[i] - a[i]) * ratio for i in range(len(a)))
    return points[-1]


def derive_cost():
    slot = service.SIMULATION_BASE_TIME
    service._virtual_radar_derived.cache_clear()
    start = time.perf_counter()
    for step in range(5):
        service._virtual_radar_derived.cache_clear()
        service._virtual_radar_derived(SEED, slot + dt.timedelta(minutes=step))
    return (time.perf_counter() - start) / 5


def run(stride):
    service.RADAR_SWEEP_STRIDE_MINUTES = stride
    service._virtual_radar_samples.cache_clear()
    service._virtual_radar_derived.cache_clear()
    start = time.perf_counter()
    plan = service.simulate(seed=SEED, scenario='live',
                            weather_mode=weather_control.MODE_VIRTUAL)
    elapsed = time.perf_counter() - start
    stats = plan['stats']
    accepted = [f for f in plan['flights']
                if f.get('status') == 'SCHEDULED' and len(f.get('points') or []) >= 2]
    sweep = len(service._virtual_radar_samples())
    return plan, stats, accepted, elapsed, sweep


def incursions(accepted):
    """Aircraft-minutes inside the painted core, sampled every 5 minutes."""
    core_hits = 0
    hit_flights = set()
    field_hits = 0
    frames = 0
    for minute in range(0, service.TIMELINE_MINUTES + 1, 5):
        slot = service.SIMULATION_BASE_TIME + dt.timedelta(minutes=minute)
        derived = service._virtual_radar_derived(SEED, slot)
        if not derived.get('available'):
            continue
        frames += 1
        field, core, _c, _w = radar_field.shield(derived)
        for flight in accepted:
            if not (flight['departureMinute'] <= minute <= flight['arrivalMinute']):
                continue
            pos = at_minute(flight['points'], minute)
            if pos is None:
                continue
            point = Point(pos[0], pos[1])
            if not core.is_empty and core.contains(point):
                core_hits += 1
                hit_flights.add(flight['id'])
            elif not field.is_empty and field.contains(point):
                field_hits += 1
    return core_hits, len(hit_flights), field_hits, frames


def main():
    weather_control.set_mode(weather_control.MODE_VIRTUAL, seed=SEED, actor='probe')
    cost = derive_cost()
    print(f'one virtual frame derivation   {cost * 1000:.0f} ms')
    print()
    print(f'{"stride":>7} {"sweep":>6} {"build s":>8} {"accepted":>9} {"weather-closed":>15} '
          f'{"detours":>8} {"core hits":>10} {"flights":>8}')
    print('-' * 84)
    rows = []
    for stride in STRIDES:
        plan, stats, accepted, elapsed, sweep = run(stride)
        closed = plan.get('closedByReason') or {}
        weather = closed.get('WEATHER_BLOCKED', 0)
        hits, flights, _field_hits, _frames = incursions(accepted)
        rows.append((stride, sweep, elapsed, stats['accepted'], weather, hits, flights))
        print(f'{stride:>7} {sweep:>6} {elapsed:>8.1f} {stats["accepted"]:>9} '
              f'{weather:>15} {stats.get("detours", 0):>8} {hits:>10} {flights:>8}')
    print()
    print('note: the incursion test re-derives the echo every 5 minutes, so it is')
    print('      independent of the stride each plan was built with.')


if __name__ == '__main__':
    main()
