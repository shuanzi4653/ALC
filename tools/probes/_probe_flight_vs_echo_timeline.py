"""Do planned trajectories fly through the echo the map paints *between* samples?

The virtual radar advances with the playback minute -- ``radar_regions`` derives a
frame at ``SIMULATION_BASE_TIME + minute`` for the *exact* minute the scrubber is
on. The planner does not: ``_virtual_radar_samples`` samples the same field every
``RADAR_SWEEP_STRIDE_MINUTES`` (10 since 0.9.24; 60 before that), and
``_radar_window_union`` then unions the samples bracketing a flight's window.

A union of samples is not the swept volume of a moving shape. The echo drifts a
few km per hour, so two adjacent samples are two blobs with a gap between them --
and the real echo spends the intervening minutes *inside that gap*. A path routed
around both samples is therefore free to run straight down the gap, which is
exactly where the storm is on screen.

This probe walks every accepted flight minute by minute and asks the question the
operator asks when looking at the screen: *is this aircraft inside the painted
echo right now?* It reports both tiers, because they carry different verdicts:

* ``core`` is the legend's 禁止进入 -- a single hit is a defect, full stop.
  Exit code 1 if any exist.
* ``field`` is 须绕飞 **with an allowance**: the rule lets the path clip the
  >=35 dBZ field by up to ``separation.horizontalM`` (250 m). So a hit is only a
  defect when the *penetration depth* exceeds it, and the probe measures depth
  rather than counting. Exit code 1 only for hits beyond the allowance.

That distinction is the whole reason the probe reports a number instead of a
verdict: "35 aircraft-minutes grazed the field layer" reads like a defect until
the same 35 hits are measured, and 35 flights nicking the edge by a few metres is
the allowance working as documented. A count cannot tell those apart.

Run from the repository root:

    backend-python\\.venv\\Scripts\\python.exe tools\\probes\\_probe_flight_vs_echo_timeline.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'backend-python'))

from shapely.geometry import Point  # noqa: E402

from traffic import radar_field, service, weather_control  # noqa: E402

SEED = 42
STEP = 5


def at_minute(points, minute):
    """Position along a flight's 4-D polyline at ``minute`` (linear in t)."""
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


def _parts(geometry):
    """Rings of a (Multi)Polygon, so ``.exterior`` is never read off a collection.

    ``MultiPolygon`` has no ``.exterior`` -- reading it raises, and the tempting
    ``geometry.geoms[0]`` silently measures only the largest part. Both mistakes
    are already catalogued in this repo (notes/geometry-and-render.md), so the
    probe shares the same discipline rather than repeating it.
    """
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == 'Polygon':
        return [geometry]
    if geometry.geom_type == 'MultiPolygon':
        return list(geometry.geoms)
    return []


def depth_inside(geometry, point):
    """How far *inside* ``geometry`` the point sits, in metres (0 on the edge).

    This is the number the legend's allowance is written against: the operator's
    statement is "may clip the >=35 dBZ field by up to 250 m", which is a depth,
    not a clearance. Measuring a clearance here would invert the verdict.
    """
    parts = [p for p in _parts(geometry) if p.contains(point)]
    if not parts:
        return None
    return min(point.distance(p.exterior) for p in parts)


def main():
    weather_control.set_mode(weather_control.MODE_VIRTUAL, seed=SEED, actor='probe')
    for cache in (service._virtual_radar_samples, service._virtual_radar_derived):
        cache.cache_clear()

    plan = service.simulate(seed=SEED, scenario='live',
                            weather_mode=weather_control.MODE_VIRTUAL)
    accepted = [f for f in plan['flights']
                if f.get('status') == 'SCHEDULED' and len(f.get('points') or []) >= 2]
    info = plan.get('radarAvoidance') or {}
    stride = service.RADAR_SWEEP_STRIDE_MINUTES
    print(f'accepted flights     {len(accepted)} / {plan["stats"]["flights"]}')
    print(f'radar avoidance      included={info.get("included")} '
          f'sweepSlots={info.get("sweepSlots")} stride={info.get("sweepStrideMinutes")} min')
    print(f'display echo         derived at the exact playback minute, no stride')
    print()

    samples = service._virtual_radar_samples()
    print(f'sampled offsets      {[s[0] for s in samples]}')

    frames = {}
    core_hits = []
    field_hits = []
    core_flights = set()
    field_flights = set()
    for minute in range(0, service.TIMELINE_MINUTES + 1, STEP):
        slot = service.SIMULATION_BASE_TIME + dt.timedelta(minutes=minute)
        derived = service._virtual_radar_derived(weather_control.seed(), slot)
        if not derived.get('available'):
            continue
        field, core, _caution, _watch = radar_field.shield(derived)
        frames[minute] = (field, core)
        flying = [f for f in accepted
                  if f['departureMinute'] <= minute <= f['arrivalMinute']]
        if not flying:
            continue
        for flight in flying:
            pos = at_minute(flight['points'], minute)
            if pos is None:
                continue
            point = Point(pos[0], pos[1])
            core_depth = depth_inside(core, point)
            if core_depth is not None:
                core_hits.append((flight['id'], minute, core_depth))
                core_flights.add(flight['id'])
                continue
            field_depth = depth_inside(field, point)
            if field_depth is not None:
                field_hits.append((flight['id'], minute, field_depth))
                field_flights.add(flight['id'])

    print()
    print('=' * 78)
    print(f'minute-by-minute test, step {STEP} min, {len(frames)} frames derived')
    print('=' * 78)
    if core_hits:
        worst = max(core_hits, key=lambda row: row[2])
        ids = sorted({row[0] for row in core_hits})
        print(f'  CORE (禁止进入) incursions   {len(core_hits):6d} aircraft-minutes')
        print(f'    distinct flights           {len(core_flights):6d} / {len(accepted)}')
        print(f'    minutes involved           '
              f'{sorted({row[1] for row in core_hits})[:12]}{" ..." if len({row[1] for row in core_hits}) > 12 else ""}')
        print(f'    deepest                    {worst[0]} at T+{worst[1]} min, '
              f'{worst[2] / 1000:.2f} km inside the core')
        print(f'    sample ids                 {ids[:6]}')
    else:
        print('  CORE (禁止进入) incursions        0')

    # FIELD is the tier where a hit is not automatically a defect: the rule
    # allows the path to clip the >=35 dBZ field by up to `penetrationM`. Counting
    # hits without measuring depth answers a question nobody asked -- it cannot
    # distinguish "grazing by 40 m, as designed" from "cutting 8 km through the
    # storm, which the stride hid". So depth is the verdict, and the count is
    # only the denominator.
    allowed = service.profiles()['separation']['horizontalM']
    over = [row for row in field_hits if row[2] > allowed]
    print()
    if field_hits:
        worst = max(field_hits, key=lambda row: row[2])
        print(f'  FIELD (须绕飞) incursions    {len(field_hits):6d} aircraft-minutes')
        print(f'    distinct flights           {len(field_flights):6d}')
        print(f'    declared allowance         {allowed:g} m penetration '
              f'(see routing.penetration_limit)')
        print(f'    deepest penetration        {worst[0]} at T+{worst[1]} min, '
              f'{worst[2]:.0f} m')
        print(f'    beyond the allowance       {len(over):6d}')
        if over:
            print('    VERDICT                    DEFECT -- the stride hid a '
                  'penetration the rule forbids')
            for fid, minute, depth in sorted(over, key=lambda r: -r[2])[:6]:
                print(f'      {fid} T+{minute:3d} min  {depth:.0f} m')
        else:
            print(f'    VERDICT                    within allowance '
                  f'(max {worst[2]:.0f} m <= {allowed:g} m) -- grazing, by design')
    else:
        print('  FIELD (须绕飞) incursions         0')

    print()
    print(f'  where the CORE incursions sit relative to the {stride}-minute samples:')
    by_minute = {}
    for _fid, minute, _depth in core_hits:
        by_minute[minute] = by_minute.get(minute, 0) + 1
    for minute in sorted(by_minute):
        nearest = min(samples, key=lambda s: abs(s[0] - minute))[0]
        gap = abs(minute - nearest)
        print(f'    T+{minute:3d} min  {by_minute[minute]:3d} aircraft   '
              f'nearest sample T+{nearest:3d} ({gap:2d} min away)')
    if not by_minute:
        print('    (nothing to attribute -- the hard tier is clean)')

    # The verdict above says a hit is beyond the allowance. It does **not** say
    # whose fault that is, and the two candidates need opposite fixes:
    #
    #   * the planner HAD the geometry (some sample already contains the point)
    #     -> the soft tier's erosion or the path rounding let it through; the
    #        stride is not the problem and shrinking it would only cost time.
    #   * NO sample contains it -> the point sits in the drift gap between two
    #        samples, which is the stride's signature.
    #
    # Asking the samples themselves, rather than reasoning about drift rates,
    # because a 13 km penetration is far larger than the ~2 km the field moves in
    # one stride -- so the drift-gap story does not obviously explain it, and the
    # measurement is the only thing that settles it.
    deepest = sorted((row for row in field_hits if row[2] > allowed),
                     key=lambda row: -row[2])[:6]
    if deepest:
        print()
        print('  attribution of the deepest beyond-allowance hits '
              '(does a sweep sample already contain them?):')
        for fid, minute, depth in deepest:
            flight = next(f for f in accepted if f['id'] == fid)
            pos = at_minute(flight['points'], minute)
            point = Point(pos[0], pos[1])
            containing = [s[0] for s in samples
                          if s[1] is not None and not s[1].is_empty and s[1].contains(point)]
            had = 'planner had it' if containing else 'gap between samples'
            print(f'    {fid} T+{minute:3d} min  {depth:7.0f} m  '
                  f'window {flight["departureMinute"]}-{flight["arrivalMinute"]}  '
                  f'samples containing it: {containing or "none"}  -> {had}')

    return 1 if (core_hits or over) else 0


if __name__ == '__main__':
    sys.exit(main())

