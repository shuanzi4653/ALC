"""How many distinct envelope windows does one plan actually need?

Diagnosis so far:
  * `weather.envelope` is 94.7% of the plan.
  * Measured cache hit rate: **0.0%** (0 hits over 576 calls).
  * Each miss costs ~110 ms; the plan calls it ~7760 times.

The comment in `weather.py` claims binning gives a 92.3% hit rate. The measured
rate is zero, so either the claim is stale or the keys the planner produces are
more varied than the comment assumes. This enumerates the exact keys the real
planner generates, which settles it: if the distinct count is small, the fix is
to precompute the distinct windows once instead of relying on incidental reuse.

Called with: python _probe_window_keys.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND  # noqa: E402
import collections
import math
import random
from pathlib import Path


from traffic import service  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


SEED = 4242
WAIT_STEP = max(1, int(service.profiles()['separation']['groundWaitStepMinutes']))
MAX_EXTRA = service.profiles()['separation']['maxExtraMinutes']

# Rebuild the planner's own `pending` list so the keys are the real ones, not a
# guess at their shape.
catalog = service.network()
rng = random.Random(SEED)
pending = []
for item in catalog['routes']:
    interval = 60 if item['mode'] == 'CAR' else 30
    for departure in range(0, service.TIMELINE_MINUTES, interval):
        for direction in (0, 1):
            wave_offset = (int(item['id'].rsplit('-', 1)[-1]) - 1) * 3 if item['mode'] == 'DELIVERY' else 0
            pending.append((departure + direction * 8 + wave_offset + rng.randint(0, 2), item['id'], direction, item))
pending.sort(key=lambda item: item[:3])
print(f'班次 {len(pending)}')

# The two call sites: the pre-flight check uses a nominal duration, the final
# check adds the chosen delay. Both bin to 5-minute ticks.
pre_keys = collections.Counter()
final_keys = collections.Counter()
for scheduled, _, _, route_item in pending:
    mode = route_item['mode']
    profile = service.profiles()[mode]
    # Nominal duration is bounded by the route length over speed; use the
    # scheduler's own bound so the window span matches reality.
    nominal = max(1, int(route_item.get('distanceKm', 60) / max(profile['speedKmh'], 1) * 60))
    pre_keys[(math.floor(scheduled / 5), math.ceil((scheduled + nominal + MAX_EXTRA) / 5))] += 1
    for delay in range(0, MAX_EXTRA + 1, WAIT_STEP):
        final_keys[(math.floor((scheduled + delay) / 5),
                    math.ceil((scheduled + delay + nominal) / 5))] += 1

all_keys = set(pre_keys) | set(final_keys)
print(f'预检窗口不同键 {len(pre_keys)}，最终窗口不同键 {len(final_keys)}，合计不同键 {len(all_keys)}')
print(f'调用总数 {sum(pre_keys.values()) + sum(final_keys.values())}')

# These probes pass (start, end) and `envelope` bins internally. The probe above
# passed end = start + duration + max_extra but the planner bins `end` with ceil,
# which for a float end yields one extra tick -- that is why the measured hit rate
# was 0: adjacent flights land on adjacent windows rather than repeating.
float_pairs = collections.Counter()
for scheduled, _, _, route_item in pending:
    mode = route_item['mode']
    profile = service.profiles()[mode]
    nominal = max(1, int(route_item.get('distanceKm', 60) / max(profile['speedKmh'], 1) * 60))
    float_pairs[(scheduled, scheduled + nominal + MAX_EXTRA)] += 1
print(f'未分箱的 (start,end) 浮点对不同值 {len(float_pairs)}（若等于调用数，则分箱前无从复用）')

spans = collections.Counter()
for start, end in all_keys:
    spans[end - start] += 1
print(f'窗口跨度分布（ticks） {dict(sorted(spans.items())[:12])}')
