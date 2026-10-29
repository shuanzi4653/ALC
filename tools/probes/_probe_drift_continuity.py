"""Does the virtual echo move continuously, or does it teleport?

The user reported: during playback a large blob of virtual weather suddenly
disappears and comes back at its starting position. That is the signature of a
**sawtooth**: the shipped 0.9.21 law was

    travelled = (0.0045 * span) % 0.08

so the whole field was carried a fixed distance and then snapped back in a
single step.

This probe measures the single-step displacement of the field along the playback
timeline, in km, so the size of that snap is a number rather than an impression.
It reports the median step (what steady drift looks like), the largest step
(what a snap looks like) and their ratio -- **for both laws**, because the "was"
number is only worth quoting if it can be reproduced after the code has moved on.
The sawtooth is therefore reconstructed here, exactly as 0.9.21 shipped it,
rather than kept alive in the generator for the probe's benefit.

The metric is the **centroid of the live cells' field positions**. Every cell
carries the same advection offset, so the centroid moves exactly as the painted
echo does, and it is ~50x cheaper than rasterising a frame -- which is what makes
a scan of every slot in the timeline affordable.

Run from the repository root:

    backend-python\\.venv\\Scripts\\python.exe tools/probes/_probe_drift_continuity.py
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _repo import artifact  # noqa: E402
from traffic import weather_sim  # noqa: E402

# The law as 0.9.21 shipped it, so the "before" column stays reproducible.
LEGACY_RATE = 0.0045
LEGACY_PERIOD = 0.08


def tile_to_lonlat(x, y, zoom=weather_sim.ZOOM):
    """Inverse of ``weather_sim.lonlat_to_tile``, for human-readable output."""
    scale = float(2 ** zoom)
    lon = x / scale * 360.0 - 180.0
    mercator_y = math.pi - y / scale * 2.0 * math.pi
    lat = math.degrees(2.0 * math.atan(math.exp(mercator_y)) - math.pi / 2.0)
    return lon, lat


def legacy_law(span):
    """The 0.9.21 sawtooth, in tiles."""
    total = (LEGACY_RATE * span) % LEGACY_PERIOD
    bearing = math.radians(weather_sim.DRIFT_BEARING_DEG)
    return math.cos(bearing) * total, -math.sin(bearing) * total


def current_law(span):
    """The shipped law, evaluated at ``span`` slots past the timeline anchor."""
    return weather_sim._advection(0.0, since=weather_sim._reference_slot() + int(span))


def centroid(seed, slot_index):
    """Mean **undrifted** placement of the live cells, in tile units, or ``None``.

    Rebuilt from the generator's own placement and life-cycle helpers rather than
    read off ``_cell_state``, because ``_cell_state`` has already added the
    advection -- and the whole point here is to apply a *different* advection law
    to the same placement. The per-cell vigour offset is deliberately left out:
    it is the same for both laws, so including it would add a constant to both
    sides of the comparison.

    Unweighted over live cells: a cell's radius is not part of "where is the
    weather", and weighting by radius would let the life cycle mask a
    displacement -- exactly the failure this probe exists to detect.
    """
    xs = ys = 0.0
    count = 0
    for index in range(weather_sim.CELL_COUNT):
        phase = weather_sim._cohort_phase(seed, index)
        age = (slot_index + phase) % weather_sim.LIFE_SLOTS
        if weather_sim._life_curve(age) <= 0.0:
            continue
        cycle = (slot_index + phase) // weather_sim.LIFE_SLOTS
        x, y = weather_sim._position(seed, index * 100003 + cycle % 100003)
        xs += x
        ys += y
        count += 1
    if not count:
        return None
    return xs / count, ys / count


def field_point(seed, span, law):
    """Where the field sits, in tile units: placement centroid plus advection."""
    base = centroid(seed, weather_sim._reference_slot() + int(span))
    if base is None:
        return None
    dx, dy = law(span)
    return base[0] + dx, base[1] + dy


def scan_offset(law, slots, step=1):
    """Per-step movement of the advection offset, in km.

    This is the cleanest available measure of the artefact: it involves no live
    cell set, no life cycle and no centroid, so a step here can only come from
    the advection law. The box centre is used as the anchor because the tile
    grid's y axis is Mercator -- a tile is 45 degrees of longitude but only
    ~31.5 degrees of latitude at 45N, and converting a tile offset to km near the
    tile origin (which sits close to the pole) understates it by an order of
    magnitude.
    """
    centre = weather_sim.lonlat_to_tile(
        (weather_sim.FIELD_LON_MIN + weather_sim.FIELD_LON_MAX) / 2.0,
        (weather_sim.FIELD_LAT_MIN + weather_sim.FIELD_LAT_MAX) / 2.0)

    def point(span):
        dx, dy = law(span)
        return centre[0] + dx, centre[1] + dy

    steps = []
    for span in range(step, slots + 1, step):
        steps.append((span, km_between(point(span - step), point(span))))
    return steps


def km_between(a, b):
    """Great-circle distance, so a step is comparable with a storm's speed."""
    lon1, lat1 = tile_to_lonlat(*a)
    lon2, lat2 = tile_to_lonlat(*b)
    mean_lat = math.radians((lat1 + lat2) / 2.0)
    dx = (lon2 - lon1) * 111.32 * math.cos(mean_lat)
    dy = (lat2 - lat1) * 110.57
    return math.hypot(dx, dy)


def scan(seed, law, slots, step=1):
    """Per-step displacement of the field along ``slots`` slots of playback."""
    steps = []
    previous = field_point(seed, 0, law)
    for span in range(step, slots + 1, step):
        current = field_point(seed, span, law)
        if previous is None or current is None:
            steps.append((span, None))
        else:
            steps.append((span, km_between(previous, current)))
        previous = current
    return steps


def summarise(label, steps):
    values = [value for _span, value in steps if value is not None]
    ordered = sorted(values)
    median = ordered[len(ordered) // 2]
    largest = max(values)
    jumps = [(span, value) for span, value in steps if value is not None and value > 3.0 * median]
    print(f'{label}')
    print(f'  steps measured        {len(values)}  (each = 6 min of playback)')
    print(f'  median step           {median:8.1f} km')
    print(f'  largest step          {largest:8.1f} km')
    print(f'  ratio max/median      {largest / median if median else float("inf"):8.1f}x')
    print(f'  steps > 3x median     {len(jumps)}  {[(s, round(v)) for s, v in jumps][:6]}')
    return {
        'medianStepKm': round(median, 1),
        'largestStepKm': round(largest, 1),
        'ratioMaxOverMedian': round(largest / median, 1) if median else None,
        'stepsOverThreeTimesMedian': len(jumps),
    }


def main():
    seed = 42
    half_cycle_slots = weather_sim.DRIFT_PERIOD_SLOTS / 2.0
    print('=' * 74)
    print('virtual echo drift continuity')
    print('=' * 74)
    print(f'  excursion             {weather_sim.DRIFT_EXCURSION_TILES} tiles '
          f'(was a {LEGACY_PERIOD}-tile modulo)')
    print(f'  period                {weather_sim.DRIFT_PERIOD_SLOTS:.0f} slots '
          f'= {weather_sim.DRIFT_PERIOD_MINUTES:.0f} min')
    print(f'  monotone over         the first {half_cycle_slots:.0f} slots '
          f'({half_cycle_slots * 6:.0f} min of playback)')
    print(f'  anchor                {weather_sim.DRIFT_REFERENCE_TIME.isoformat()}')
    print()

    # The timeline the workbench plays: 0-480 min = 80 slots.
    was_offset = summarise('0.9.21 sawtooth -- advection offset only',
                           scan_offset(legacy_law, slots=80))
    print()
    now_offset = summarise('current law -- advection offset only',
                           scan_offset(current_law, slots=80))
    print()
    was = summarise('0.9.21 sawtooth -- field centroid', scan(seed, legacy_law, slots=80))
    print()
    now = summarise('current law -- field centroid', scan(seed, current_law, slots=80))
    print()
    # Beyond the timeline: the current law must stay bounded and continuous
    # where it turns around. The sawtooth does neither.
    was_long = summarise('0.9.21 sawtooth -- offset over 320 slots',
                         scan_offset(legacy_law, slots=320))
    print()
    now_long = summarise('current law -- offset over 320 slots',
                         scan_offset(current_law, slots=320))

    payload = {
        'seed': seed,
        'excursionTiles': weather_sim.DRIFT_EXCURSION_TILES,
        'periodSlots': weather_sim.DRIFT_PERIOD_SLOTS,
        'anchor': weather_sim.DRIFT_REFERENCE_TIME.isoformat(),
        'offset': {'sawtooth': was_offset, 'current': now_offset,
                   'sawtoothBeyond': was_long, 'currentBeyond': now_long},
        'centroid': {'sawtooth': was, 'current': now},
    }
    out = artifact('drift_continuity.json')
    with open(out, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(f'\nwrote {out}')


if __name__ == '__main__':
    main()
