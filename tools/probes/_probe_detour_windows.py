"""Attribute the 0.9.22 detour gain to the lever that produced it.

The operator's ask was 「只要有合适的窗口就可以飞，哪怕路线稍微极限一些也无所谓」.
Three separate things were changed to serve it, and a combined before/after number
would not say which of them did the work -- or whether any of them did nothing:

  1. **window** -- route against the flight's own span instead of
     ``[scheduled, scheduled + base + max_extra]``. The padded union is the worst
     the weather could do over every hour the flight *might* have been airborne,
     so a band crossing the corridor becomes a swept band lying across it;
  2. **ladder**  -- try the corridor again at later departures, so a flight can
     wait for the band to clear instead of being shut by it;
  3. **tiers**   -- the radar's >=45 dBZ core stays hard, the >=35 dBZ field
     becomes the soft tier the legend already calls 须绕飞.

Each is emulated in-process by monkeypatching, against **one** weather snapshot
pinned to an artifact. Comparing two runs that each fetched their own sky would
compare two weathers, not two planners -- the failure the project notes call a
stale reference object.

Run from the repository root (each case is a full ~11 s plan):

    backend-python\\.venv\\Scripts\\python.exe tools/probes/_probe_detour_windows.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _repo import artifact  # noqa: E402
from traffic import routing, service, weather_control  # noqa: E402

SEED = 42
PIN = 'weather_snapshot_pin.json'

# (label, padding minutes, wait probes, fold the soft tier back into the hard one)
CASES = (
    ('legacy 0.9.21 (padded window, one tier, no ladder)', 60.0, (0.0,), True),
    ('+ actual window', 0.0, (0.0,), True),
    ('+ wait ladder', 0.0, (0.0, 0.5, 1.0), True),
    ('+ two tiers  (shipped 0.9.22)', 0.0, (0.0, 0.5, 1.0), False),
)


def pinned_snapshot():
    """Fetch the sky once, then reuse it for every run of this probe."""
    path = artifact(PIN)
    if os.path.exists(path):
        with open(path, encoding='utf-8') as handle:
            snapshot = json.load(handle)
        print(f'weather snapshot   {snapshot.get("weatherSnapshotId")}  (pinned)')
        return snapshot
    snapshot = service.weather_snapshot_entry(service.cities())
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(snapshot, handle, ensure_ascii=False)
    print(f'weather snapshot   {snapshot.get("weatherSnapshotId")}  (newly pinned)')
    return snapshot


def build(snapshot, padding, wait, soft_is_hard):
    """One full plan with the three levers set to the given reading."""
    original_route = service.route
    original_padding = service.DETOUR_WINDOW_PADDING_MINUTES
    original_wait = service.RADAR_WAIT_PROBES

    def folded(start, end, allowed, obstacles=None, *, soft_obstacles=None,
               penetration_m=0.0, **kwargs):
        if soft_obstacles is not None and not soft_obstacles.is_empty:
            obstacles = soft_obstacles if obstacles is None else obstacles.union(soft_obstacles)
        return routing.route(start, end, allowed, obstacles, **kwargs)

    try:
        service.DETOUR_WINDOW_PADDING_MINUTES = padding
        service.RADAR_WAIT_PROBES = wait
        if soft_is_hard:
            service.route = folded
        started = time.time()
        plan = service.simulate(seed=SEED, scenario='live', live_snapshot=snapshot,
                                weather_mode=weather_control.MODE_VIRTUAL)
        elapsed = time.time() - started
    finally:
        service.route = original_route
        service.DETOUR_WINDOW_PADDING_MINUTES = original_padding
        service.RADAR_WAIT_PROBES = original_wait
    return plan, elapsed


def summarise(plan, elapsed):
    stats = plan['stats']
    accepted = [flight for flight in plan['flights'] if flight.get('status') == 'SCHEDULED']
    waited = sum(1 for flight in accepted
                 if flight.get('delayMinutes') and abs(flight.get('detourMinutes') or 0.0) < 0.01)
    return {
        'flights': stats['flights'],
        'accepted': stats['accepted'],
        'closed': stats['closed'],
        'detours': stats['detours'],
        'weatherClosed': stats['closedByWeather'],
        'waitedStraight': waited,
        'seconds': round(elapsed, 1),
        'tally': stats['closedByClosureReason'],
    }


def main():
    weather_control.set_mode(weather_control.MODE_VIRTUAL, seed=SEED, actor='probe')
    snapshot = pinned_snapshot()
    print(f'availability       {snapshot.get("available")}')
    print()

    rows, legacy = [], None
    for label, padding, wait, soft_is_hard in CASES:
        plan, elapsed = build(snapshot, padding, wait, soft_is_hard)
        row = summarise(plan, elapsed)
        row['label'] = label
        rows.append(row)
        if legacy is None:
            legacy = row
        print(f'{label}')
        print(f'  accepted {row["accepted"]:6d} / {row["flights"]}   '
              f'closed {row["closed"]:5d}   detours {row["detours"]:5d}   '
              f'weather-closed {row["weatherClosed"]:5d}   '
              f'waited-and-flew-straight {row["waitedStraight"]:4d}   {row["seconds"]:6.1f} s')
        if row is not legacy:
            print(f'  vs legacy: accepted {row["accepted"] - legacy["accepted"]:+d}, '
                  f'weather-closed {row["weatherClosed"] - legacy["weatherClosed"]:+d}, '
                  f'time {row["seconds"] - legacy["seconds"]:+.1f} s')
        print()

    for row in rows:
        print(f'closed-flight reasons -- {row["label"]}')
        for reason, count in sorted(row['tally'].items(), key=lambda item: -item[1]):
            print(f'  {count:6d}  {reason}')
        print()

    out = artifact('detour_windows.json')
    with open(out, 'w', encoding='utf-8') as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
