"""Did relaxing the rules let flights fly through painted echo?

The 0.9.22 planner lets a flight clip the >=35 dBZ band by a declared allowance,
routes against the flight's own window instead of the padded one, and may hold a
flight on the ground until a usable window opens. Every one of those is a
*relaxation*, and a relaxation without a safety proof is just a removed check --
especially here, because the whole reason the radar entered routing at all was the
operator's 2026-09-24 report that the map painted no-fly clouds while every flight
flew straight through them.

So this probe takes the *accepted* plan and re-tests it against the geometry the
map actually paints, at each flight's own times:

  * ``ban``  -- ``shield()[1]``, the >=45 dBZ core the legend calls 禁止进入. A
    single intersection here is a defect, not a tolerance;
  * ``field``-- ``shield()[0]``, the >=35 dBZ band the legend calls 须绕飞, which
    the tolerant rule lets be clipped by at most ``penetration_m``.

It reads the same sample tuple the plan build already computed, so it costs one
derivation pass and a linear scan of the accepted flights.

Run from the repository root:

    backend-python\\.venv\\Scripts\\python.exe tools\\probes\\_probe_plan_vs_echo.py
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shapely.geometry import LineString  # noqa: E402

from _repo import artifact  # noqa: E402
from traffic import service, weather_control  # noqa: E402

SEED = 42
PIN = 'weather_snapshot_pin.json'


def pinned_snapshot():
    path = artifact(PIN)
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def main():
    snapshot = pinned_snapshot()
    weather_control.set_mode(weather_control.MODE_VIRTUAL, seed=SEED, actor='probe')
    plan = service.simulate(seed=SEED, scenario='live', live_snapshot=snapshot,
                            weather_mode=weather_control.MODE_VIRTUAL)
    samples = service._virtual_radar_samples()
    stride = service.RADAR_SWEEP_STRIDE_MINUTES
    graze = service.profiles()['separation']['horizontalM']
    accepted = [flight for flight in plan['flights'] if flight.get('status') == 'SCHEDULED']

    print(f"weather snapshot   {snapshot.get('weatherSnapshotId')}  (pinned)")
    print(f'accepted           {len(accepted)} / {plan["stats"]["flights"]}')
    print(f'radar samples      {len(samples)}  stride {stride} min  clearance {graze:g} m')
    print()

    ban_hits, field_hits, checked_pairs = [], [], 0
    deep_hits, shallow_hits = [], []
    worst = None
    for flight in accepted:
        points = flight.get('points') or []
        if len(points) < 2:
            continue
        line = LineString([point[:2] for point in points])
        begin, end = points[0][3], points[-1][3]
        for minute, field, band in samples:
            # The same window rule `_radar_window_union` applies, so this audits
            # the geometry the planner actually treated as in force.
            if not (minute >= begin - stride and minute <= end):
                continue
            checked_pairs += 1
            if line.intersects(band):
                ban_hits.append((flight['id'], begin, end, minute))
            if line.intersects(field):
                field_hits.append((flight['id'], begin, end, minute))
                # The rule as implemented is a *bounded penetration allowance*:
                # a path may clip the obstacle's edge by at most `graze`, and may
                # not reach deeper. `buffer(-graze)` is exactly the forbidden
                # interior, so intersecting it is a violation of the rule while
                # intersecting the field is not. Both are reported, because a
                # count of "clips" alone cannot tell the two apart.
                (deep_hits if line.intersects(field.buffer(-graze)) else shallow_hits).append(
                    (flight['id'], minute))
            else:
                gap = line.distance(field)
                if worst is None or gap < worst[0]:
                    worst = (gap, flight['id'], minute)

    print(f'(flight, sample) pairs checked   {checked_pairs}')
    print(f'禁止进入 core crossed            {len(ban_hits)}'
          + (f'  e.g. {ban_hits[:3]}' if ban_hits else '   <- must be 0'))
    print(f'须绕飞 band touched              {len(field_hits)}'
          + (f'   <- within the declared {graze:g} m allowance' if field_hits else ''))
    print(f'  ... penetrating BEYOND {graze:g} m   {len(deep_hits)}'
          + (f'  e.g. {deep_hits[:3]}' if deep_hits else '   <- must be 0'))
    print(f'  ... clipping the outer shell   {len(shallow_hits)}')
    if worst is not None:
        print(f'closest non-touching approach    {worst[0]:.1f} m  ({worst[1]} @ t={worst[2]})')

    out = artifact('plan_vs_echo.json')
    with open(out, 'w', encoding='utf-8') as handle:
        json.dump({'checkedPairs': checked_pairs, 'accepted': len(accepted),
                   'banHits': ban_hits, 'fieldHits': field_hits,
                   'beyondAllowance': deep_hits, 'outerShellOnly': shallow_hits,
                   'smallestApproachM': None if worst is None else round(worst[0], 2),
                   'allowanceM': graze}, handle, ensure_ascii=False, indent=2)
    print(f'\nwrote {out}')


if __name__ == '__main__':
    main()
