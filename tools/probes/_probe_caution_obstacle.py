"""Quantify the routing fix: only the prohibited core is an obstacle.

`weather.PublicWeather.envelope` unions `ban | caution`, so a "enter with care"
disc over a city is treated as an airspace the planner may not enter -- and
`route()` refuses outright when the start/end point is inside the obstacle set.
Measured 2026-09-30 (live/measured, seed 42): 2519 WEATHER_BLOCKED, 0 detours,
2488 of them with their own pad inside a *caution* disc and zero ban cores
anywhere in the frame.

This probe patches `envelope` to the ban tier only and re-runs the plan, so the
size of the effect is measured rather than asserted.
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND  # noqa: E402

from shapely.geometry import GeometryCollection  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from traffic import service, weather  # noqa: E402

SEED, SCENARIO = 42, 'live'


def report(tag, plan):
    stats = plan['stats']
    print(f"{tag:28s} flights={stats['flights']} accepted={stats['accepted']} closed={stats['closed']}"
          f" detours={stats['detours']}")
    print('   closure reasons:', dict(Counter(f['reason'] for f in plan['flights']
                                              if f['status'] != 'SCHEDULED').most_common(6)))
    detour_minutes = sorted((f.get('detourMinutes') or 0) for f in plan['flights']
                            if f['reason'] == 'WEATHER_DETOUR')
    if detour_minutes:
        print(f"   detour minutes: n={len(detour_minutes)} min={detour_minutes[0]} "
              f"median={detour_minutes[len(detour_minutes)//2]} max={detour_minutes[-1]}")
    return stats


baseline = service.simulate(seed=SEED, scenario=SCENARIO)
report('baseline (ban|caution)', baseline)

original = weather.PublicWeather.envelope


def ban_only(self, start, end):
    if not self.snapshot.get('available'):
        return GeometryCollection()
    bans = [ban for _cell, _field, ban, _caution in self.shapes(_minute=None)
            if ban is not None and not ban.is_empty]
    return unary_union(bans) if bans else GeometryCollection()


weather.PublicWeather.envelope = ban_only
try:
    patched = service.simulate(seed=SEED, scenario=SCENARIO)
finally:
    weather.PublicWeather.envelope = original
report('ban-only obstacle', patched)
