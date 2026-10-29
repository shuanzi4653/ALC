"""Which closures are "no path exists" and which are "the search stopped looking"?

Reported by the operator as: with storm echo on the map, flights are closed even
where a usable window is visible. Two questions have to be separated before any
constant is touched:

1. How many flights does the virtual plan close, and for what reason?
2. Of those, how many would fly if the route search were given a wider box, a
   finer grid, or more node expansions?

The second question is the one the old code could not answer: the three numbers
that decide whether a detour is *found* were literals inside ``route()``, so
"no path exists" and "the search gave up" produced the same ``None`` and the
same ``WEATHER_BLOCKED``. They are now arguments, so this probe can sweep them
against a single fixed weather situation and report the exchange rate between
accepted flights and build time.

One weather snapshot is fetched and reused for every variant -- otherwise each
run would meet a different sky and the comparison would be between weathers
rather than between search settings.

Run from the repository root (a full plan is ~1 min, so allow ~10 min):

    backend-python\\.venv\\Scripts\\python.exe tools/probes/_probe_route_window.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _repo import artifact  # noqa: E402
from traffic import routing, service, weather_control  # noqa: E402

SEED = 42

# (label, kwargs forwarded to `route`) -- every variant keeps the module's own
# defaults for anything it does not name, so a row differs from "baseline" by
# exactly one lever.
VARIANTS = (
    ('baseline (0.9.21 literals)', {}),
    ('margin x2', {'margin_m': routing.SEARCH_MARGIN_MAX_M * 2}),
    ('margin x4', {'margin_m': routing.SEARCH_MARGIN_MAX_M * 4}),
    ('checks x4', {'max_checks': routing.SEARCH_MAX_CHECKS * 4}),
    ('step finer (1.6 km)', {'step_m': 1600.0}),
    ('margin x4 + checks x4 + step 1.6 km',
     {'margin_m': routing.SEARCH_MARGIN_MAX_M * 4,
      'max_checks': routing.SEARCH_MAX_CHECKS * 4,
      'step_m': 1600.0}),
)


def build(snapshot, overrides):
    """One full plan with `route` pinned to the given search settings."""
    original = service.route

    def pinned(start, end, allowed, obstacles=None, **kwargs):
        merged = dict(overrides)
        merged.update(kwargs)
        return routing.route(start, end, allowed, obstacles, **merged)

    try:
        service.route = pinned
        started = time.time()
        plan = service.simulate(seed=SEED, scenario='live', live_snapshot=snapshot,
                                weather_mode=weather_control.MODE_VIRTUAL)
        elapsed = time.time() - started
    finally:
        service.route = original
    return plan, elapsed


def main():
    weather_control.set_mode(weather_control.MODE_VIRTUAL, seed=SEED, actor='probe')
    snapshot = service.weather_snapshot_entry(service.cities())
    print(f'weather snapshot   {snapshot.get("weatherSnapshotId")}')
    print(f'availability       {snapshot.get("available")}')
    print()

    rows = []
    baseline = None
    for label, overrides in VARIANTS:
        plan, elapsed = build(snapshot, overrides)
        stats = plan['stats']
        radar = plan.get('radarAvoidance') or {}
        row = {
            'label': label,
            'flights': stats['flights'],
            'accepted': stats['accepted'],
            'closed': stats['closed'],
            'detours': stats['detours'],
            'weatherClosed': stats['closedByWeather'],
            'seconds': round(elapsed, 1),
            'radarKm2': radar.get('areaKm2'),
        }
        rows.append(row)
        if baseline is None:
            baseline = row
        print(f'{label}')
        print(f'  accepted {row["accepted"]:6d} / {row["flights"]}   '
              f'closed {row["closed"]:5d}   detours {row["detours"]:5d}   '
              f'weather-closed {row["weatherClosed"]:5d}   {row["seconds"]:6.1f} s')
        if row is not baseline:
            print(f'  vs baseline: accepted {row["accepted"] - baseline["accepted"]:+d}, '
                  f'weather-closed {row["weatherClosed"] - baseline["weatherClosed"]:+d}, '
                  f'time {row["seconds"] - baseline["seconds"]:+.1f} s')
        print()

    print('closed-flight reasons at baseline (first row above):')
    plan, _ = build(snapshot, {})
    tally = plan['stats']['closedByClosureReason']
    for reason, count in sorted(tally.items(), key=lambda item: -item[1]):
        print(f'  {count:6d}  {reason}')

    out = artifact('route_window.json')
    with open(out, 'w', encoding='utf-8') as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)
    print(f'\nwrote {out}')


if __name__ == '__main__':
    main()
