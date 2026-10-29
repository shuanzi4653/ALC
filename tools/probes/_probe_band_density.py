# -*- coding: utf-8 -*-
"""Measure the virtual squall band: coverage, segmentation, and corridor crossings.

Why this exists
---------------
The virtual weather generator places its convective cells on a **corridor-aligned
band** so that the demonstration shows a storm that actually sits over the flight
network. Two properties are asserted by ``tests/test_weather_control.py`` and both
are statements about measured geometry, not about code structure:

  * **coverage** -- how much of the operating area the field covers
    (the operator's "there are a lot of cloud masses" requirement);
  * **alignment** -- how many of the planner's corridors the band crosses,
    compared against the same generator with the band placement disabled
    (the "the rain band affects the routes" requirement).

Those two are in tension: a denser field makes the *legacy free placement* cross
more corridors too, so the alignment advantage shrinks as the cell count rises.
This script prints both numbers together so a parameter change can be judged
against **both** requirements at once instead of only the one being optimised.

The slot is pinned, not defaulted
---------------------------------
``weather_sim.frame(seed)`` treats ``slot=None`` as *now*, so a probe that omits
it measures each seed at a different wall-clock minute and returns a **different
answer on every run** (measured: `.run` 40-seed runs gave aligned median
13.5 then 15.0 and legacy 11.0 then 12.5 on identical code). The generator is a
pure function of ``(seed, slot)``; the probe has to supply both. ``SLOT`` below
is a fixed instant, which makes the figures in the docstrings reproducible by
re-running this file.

Run from the repository root::

    python tools/probes/_probe_band_density.py

It is read-only: it never switches the weather mode and never writes a file.
"""
import datetime as dt
import os
import statistics
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'backend-python',
    ),
)

from traffic import radar_field, weather_sim  # noqa: E402
from weather.geometry import boundary  # noqa: E402

SEEDS = 40
THRESHOLD = 8

# The instant every seed is measured at. Pinned so the numbers do not move
# between runs; the life-cycle stage of a cell is a function of the slot, so an
# unpinned slot silently re-measures a different weather situation every time.
SLOT = dt.datetime(2026, 9, 23, 4, 0, tzinfo=dt.timezone.utc)


def _corridor_lines():
    """The planner's own corridor segments, in projected metres.

    Rebuilt from the catalog the way the planner builds them, so "the band crosses
    the corridors" is a statement about the plan, not about a second projection.
    """
    from shapely.geometry import LineString

    from traffic.catalog import cities, connections

    by_id = {city['id']: city for city in cities()}
    lines = []
    for origin, destination in connections():
        a, b = by_id.get(origin), by_id.get(destination)
        if not a or not b:
            continue
        lines.append(LineString([tuple(a['xy'][:2]), tuple(b['xy'][:2])]))
    return lines


def _field(seed):
    """The drawn field for one seed, in projected metres, at the pinned slot."""
    frame = weather_sim.frame(seed=seed, slot=SLOT)
    return radar_field.shield(radar_field.derive(frame, minute=60))[0]


def _components(field):
    from shapely.geometry import MultiPolygon

    parts = list(field.geoms) if isinstance(field, MultiPolygon) else [field]
    return len([part for part in parts if part.area > 0])


def main():
    lines = _corridor_lines()
    area = boundary().area / 1e6

    aligned, areas, comps = [], [], []
    for seed in range(SEEDS):
        field = _field(seed)
        aligned.append(sum(1 for line in lines if line.intersects(field)))
        areas.append(field.area / 1e6)
        comps.append(_components(field))

    original = weather_sim._band_placement
    try:
        weather_sim._band_placement = lambda seed, index: None
        legacy = [sum(1 for line in lines if line.intersects(_field(seed)))
                  for seed in range(SEEDS)]
    finally:
        weather_sim._band_placement = original

    reliable = sum(1 for value in aligned if value >= THRESHOLD)
    legacy_reliable = sum(1 for value in legacy if value >= THRESHOLD)

    print('CELL_COUNT=%d  CORE_RADIUS_CELLS_MIN=%.1f  seeds=%d  corridors=%d'
          % (weather_sim.CELL_COUNT, weather_sim.CORE_RADIUS_CELLS_MIN,
             SEEDS, len(lines)))
    print()
    print('coverage   %.1f%% - %.1f%%   (median %.1f%%) of the operating area'
          % (min(areas) / area * 100, max(areas) / area * 100,
             statistics.median(areas) / area * 100))
    print('area       %d - %d km2   (median %d)'
          % (min(areas), max(areas), statistics.median(areas)))
    print('components %d - %d        (median %d)'
          % (min(comps), max(comps), statistics.median(comps)))
    print()
    print('crossings  aligned median %.1f  legacy median %.1f'
          % (statistics.median(aligned), statistics.median(legacy)))
    print('             aligned mean %.1f    legacy mean %.1f'
          % (statistics.mean(aligned), statistics.mean(legacy)))
    print('reliability  aligned >=%d on %d/%d seeds   legacy on %d/%d'
          % (THRESHOLD, reliable, SEEDS, legacy_reliable, SEEDS))
    print('worst case   aligned %d             legacy %d'
          % (min(aligned), min(legacy)))
    print()
    print('The alignment property holds while aligned_reliable > legacy_reliable.')
    print('If a density change makes the two converge, the legacy placement has')
    print('caught up and the band is no longer doing the work the demo claims.')


if __name__ == '__main__':
    main()
