"""Can the fine radar sweep be afforded, or must the swept geometry be simplified?

``_probe_sweep_resolution.py`` established the dose-response: stride 60 leaves 134
aircraft-minutes inside the painted 禁止进入 core, stride 10 leaves 0. It also
established the price: 28.3 s -> 72.8 s of build time.

``_probe_sweep_cost.py`` attributed that +44 s:

    stride   union s   union %     calls   distinct windows
        60       5.1     17.0%    113107               2420
        10      36.9     50.2%    112260               2511

The number of union *calls* is flat (~112k) and the number of distinct windows is
flat (~2.5k). What changed is the **cost of each uncached union**: 2420 real unions
in 5.1 s is 2.1 ms; 2511 in 36.9 s is 14.7 ms. A window that used to union 3 sample
polygons now unions 8 (the `sample[0] >= bucket_start - STRIDE` look-back plus a
finer stride), and ``unary_union`` grows faster than linearly in both input count
and output complexity. The remaining ~11 s is the 40 extra echo derivations
(49 - 9 samples x ~275 ms), which is irreducible and honest.

So the lever is **the vertex count fed into the union**, not the stride. This probe
holds the stride at the value that measured zero incursions and varies only a
``simplify()`` tolerance applied to the sample geometry *on the plan path only* --
the incursion test still re-derives the exact echo, so it is the independent judge
of whether simplification let a flight back into the storm.

A tolerance that shrinks the boundary is a real risk: the core tier is
禁止进入, i.e. zero tolerance. That is exactly why the decision is made on the
measured incursion count and not on the millisecond saving.

Run from the repository root:

    backend-python\\.venv\\Scripts\\python.exe tools\\probes\\_probe_sweep_affordability.py
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
# (stride, simplify tolerance in degrees, label). 0.0025 deg is ~250 m at this
# latitude -- deliberately the same order as the 250 m separation standard, so a
# tolerance larger than that would be indefensible without measurement.
CASES = (
    (60, 0.0, 'baseline (what 0.9.23 ships)'),
    (10, 0.0, 'fine sweep, exact geometry'),
    (10, 0.0025, 'fine sweep, simplify ~250 m'),
    (10, 0.005, 'fine sweep, simplify ~500 m'),
)

_ORIGINAL_SWEEP = service._virtual_radar_sweep


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


def install_simplifier(tolerance):
    """Simplify each sample **once per build**, not once per union call.

    The first version of this probe wrapped ``_radar_window_union``, which is called
    ~112,000 times per build. Simplifying the whole 49-sample tuple inside that
    wrapper is O(calls x samples) -- about 5.5 million `simplify` calls -- and it
    ran for twenty minutes without finishing. That is a property of the probe, not
    of the planner, and it is worth stating because the obvious place to put a
    geometry transform (where the geometry is consumed) is the wrong place when the
    consumer is a hot loop.

    Wrapping the sweep instead makes the transform per-build, which is also what
    the real fix would do if it shipped.
    """
    if not tolerance:
        service._virtual_radar_sweep = _ORIGINAL_SWEEP
        return

    # 桩必须与**当前**的实参表一致：`_radar_avoidance` 现在按
    # `_virtual_radar_sweep(progress, diagnostics=…)` 调用（出参收三种计数）。少写一个形参
    # 不是"探针跑不起来"，而是 `TypeError: unexpected keyword argument` —— 它看起来像
    # 探针自己坏了，其实是被测实现的实参表变了。
    def patched(progress=None, seed=None, diagnostics=None):
        return tuple(
            (minute,
             field if field.is_empty else field.simplify(tolerance),
             core if core.is_empty else core.simplify(tolerance))
            for minute, field, core in _ORIGINAL_SWEEP(progress, seed, diagnostics))

    service._virtual_radar_sweep = patched


def run(stride, tolerance):
    service.RADAR_SWEEP_STRIDE_MINUTES = stride
    service._virtual_radar_samples.cache_clear()
    service._virtual_radar_derived.cache_clear()
    service._RADAR_WINDOW_CACHE.clear()
    service._RADAR_ERODED_CACHE.clear()
    install_simplifier(tolerance)
    start = time.perf_counter()
    plan = service.simulate(seed=SEED, scenario='live',
                            weather_mode=weather_control.MODE_VIRTUAL)
    elapsed = time.perf_counter() - start
    accepted = [f for f in plan['flights']
                if f.get('status') == 'SCHEDULED' and len(f.get('points') or []) >= 2]
    return plan, accepted, elapsed, len(service._virtual_radar_samples())


def incursions(accepted):
    """Aircraft-minutes inside the painted core, sampled every 5 minutes.

    Deliberately re-derives the echo from ``radar_field.shield`` with no
    simplifier installed, so it judges the plan against the real storm.
    """
    core_hits = 0
    hit_flights = set()
    field_hits = 0
    for minute in range(0, service.TIMELINE_MINUTES + 1, 5):
        slot = service.SIMULATION_BASE_TIME + dt.timedelta(minutes=minute)
        derived = service._virtual_radar_derived(SEED, slot)
        if not derived.get('available'):
            continue
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
    return core_hits, len(hit_flights), field_hits


def main():
    weather_control.set_mode(weather_control.MODE_VIRTUAL, seed=SEED, actor='probe')
    print(f'{"stride":>7} {"simplify":>9} {"sweep":>6} {"build s":>8} {"accepted":>9} '
          f'{"closed":>7} {"detours":>8} {"core hits":>10} {"flights":>8}  case')
    print('-' * 104)
    rows = []
    for stride, tolerance, label in CASES:
        plan, accepted, elapsed, sweep = run(stride, tolerance)
        closed = (plan.get('closedByReason') or {}).get('WEATHER_BLOCKED', 0)
        hits, flights, _field_hits = incursions(accepted)
        rows.append((stride, tolerance, elapsed, plan['stats']['accepted'], hits, flights))
        print(f'{stride:>7} {tolerance:>9.4f} {sweep:>6} {elapsed:>8.1f} '
              f'{plan["stats"]["accepted"]:>9} {closed:>7} '
              f'{plan["stats"].get("detours", 0):>8} {hits:>10} {flights:>8}  {label}')
    print()
    print('decide on the incursion column first: a millisecond saving that reopens the')
    print('禁止进入 core is not a saving. The tolerance is only admissible if its row')
    print('still reads 0 while its build time is close to the fine-sweep row.')
    service._virtual_radar_sweep = _ORIGINAL_SWEEP


if __name__ == '__main__':
    main()
