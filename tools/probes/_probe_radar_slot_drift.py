"""Does the measured radar's own publication cadence move the painted echo?

Why this probe exists. The session key (``service.identity``) is

    VERSION : FINGERPRINT : PLAN_REVISION : seed : scenario : snapshot : weather_mode

The radar is absent from it. But the measured radar is a **real observation with
a 6-minute publication cadence** (``cma_tiles.CADENCE_MINUTES``), while a plan is
built once and reused for as long as the key matches. So the sequence

    build at slot S   ->  plan avoids the echo as it was at S
    ten minutes later  ->  the map fetches slot S+2 and paints the echo as it is now

leaves a plan whose avoidance geometry describes an older storm than the one on
screen. That is the 2026-09-30 report (aircraft inside a painted no-fly area)
returning on the *time* axis instead of the channel axis -- ADR-30 keyed on which
channel supplied the observation but not on *which observation* of that channel.

This probe measures the size of the discrepancy before anything is changed:

  * part 1 -- the echo's own slot-to-slot motion (area, centroid, max vertex
    displacement) over the last few published slots, read with ``force=True``
    because ``cma_tiles.frame`` caches on ``(zoom, grid)`` and ignores the
    requested slot;
  * part 2 -- the accepted plan re-tested against the ban tier of the slot it was
    built on and of a later slot, so "how many flights does the drift put inside
    the prohibition" is a number rather than an argument.

Run from the repository root:

    backend-python\\.venv\\Scripts\\python.exe tools\\probes\\_probe_radar_slot_drift.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'backend-python'))

from shapely.geometry import LineString  # noqa: E402

from traffic import cma_tiles, radar_field, service, weather_control  # noqa: E402

SEED = 42


def frame_at(moment):
    """One frame for one slot. ``force`` defeats the (zoom, grid) cache."""
    return cma_tiles.frame(now=moment, force=True)


def tier(file_name, result):
    derived = radar_field.derive(result, minute=0)
    if not derived.get('available'):
        return None, None, derived.get('error')
    field, core, caution, watch = radar_field.shield(derived)
    return field, core, watch


def describe(geom):
    if geom is None or geom.is_empty:
        return 'empty'
    c = geom.centroid
    return f'area={geom.area / 1e6:9.1f} km2  centroid=({c.x:12.1f}, {c.y:11.1f}) m'


def part_one():
    print('=' * 78)
    print('part 1 -- the echo across consecutive published slots')
    print('=' * 78)
    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    for step in range(5):
        moment = now - dt.timedelta(minutes=cma_tiles.CADENCE_MINUTES * step)
        result = frame_at(moment)
        field, core, watch = tier('measured', result)
        slot = result.get('slot')
        age = result.get('slotAgeMinutes')
        rows.append((step, slot, field, core))
        print(f'  step {step}  slot={slot}  reportedAge={age} min  cache={result.get("cache")}')
        if result.get('error'):
            print(f'          error: {result["error"]}')
        print(f'          field  {describe(field)}')
        print(f'          ban    {describe(core)}')
    print()
    print('  consecutive-slot change (field tier):')
    for i in range(len(rows) - 1):
        a, b = rows[i][2], rows[i + 1][2]
        if a is None or b is None or a.is_empty or b.is_empty:
            print(f'    {rows[i][1]} -> {rows[i+1][1]}:  (a tier was empty)')
            continue
        ca, cb = a.centroid, b.centroid
        drift = ((ca.x - cb.x) ** 2 + (ca.y - cb.y) ** 2) ** 0.5
        darea = (b.area - a.area) / 1e6
        # How far the boundary itself moved: the area added and dropped.
        sym = a.symmetric_difference(b).area / 1e6
        print(f'    {rows[i][1]} -> {rows[i+1][1]}:  centroid moved {drift / 1000:7.2f} km'
              f'   area {darea:+9.1f} km2   symmetric-difference {sym:9.1f} km2')
    return rows


def part_two():
    print()
    print('=' * 78)
    print('part 2 -- a plan built on one slot, tested against a later slot')
    print('=' * 78)
    weather_control.set_mode(weather_control.MODE_MEASURED, seed=SEED, actor='probe')
    plan = service.simulate(seed=SEED, scenario='live')
    accepted = [f for f in plan['flights'] if f.get('status') == 'SCHEDULED']
    info = plan.get('radarAvoidance') or {}
    print(f"  flights accepted       {len(accepted)} / {plan['stats']['flights']}")
    print(f"  radarAvoidance         included={info.get('included')} slot={info.get('slot')}")
    print(f"                         areaKm2={info.get('areaKm2')} reason={info.get('reason')}")

    now = dt.datetime.now(dt.timezone.utc)
    for step in (0, 1, 2, 4):
        moment = now - dt.timedelta(minutes=cma_tiles.CADENCE_MINUTES * step)
        result = frame_at(moment)
        field, core, watch = tier('measured', result)
        if field is None or field.is_empty:
            print(f'  slot {result.get("slot")}: field empty, skipped')
            continue
        ban = core if (core is not None and not core.is_empty) else None
        hit_field = 0
        hit_ban = 0
        worst = None
        for flight in accepted:
            points = flight.get('points') or []
            if len(points) < 2:
                continue
            line = LineString([p[:2] for p in points])
            if line.intersects(field):
                hit_field += 1
            if ban is not None and line.intersects(ban):
                hit_ban += 1
                overlap = line.intersection(ban).length / 1000
                if worst is None or overlap > worst[1]:
                    worst = (flight.get('id'), overlap)
        print(f'  slot {result.get("slot")}  field={field.area / 1e6:8.1f} km2  '
              f'ban={0 if ban is None else ban.area / 1e6:8.1f} km2  ->  '
              f'accepted flights crossing field {hit_field:5d}   crossing ban {hit_ban:5d}')
        if worst:
            print(f'          deepest ban crossing: {worst[0]}  {worst[1]:.2f} km inside')


def main():
    part_one()
    part_two()


if __name__ == '__main__':
    main()
