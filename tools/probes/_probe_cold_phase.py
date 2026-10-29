"""Attribute the silent phase: what happens before the first progress tick?

Measured: with a 7760-flight catalogue, `progress` sits at 0 for 82.6 s and the
whole plan takes 196.5 s. The progress callback only fires *inside* the flight
loop, so the 82 s is everything before that loop starts. This times each
pre-loop step separately, because the fix depends on which one dominates.

Called with: python _probe_cold_phase.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND  # noqa: E402
import time
from pathlib import Path


from shapely.geometry import LineString  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

from traffic import service  # noqa: E402


def stamp(label, started):
    now = time.monotonic()
    print(f'{now - started:8.2f}s  {label}', flush=True)
    return now


overall = time.monotonic()
mark = overall

straight = time.monotonic()
catalog = service.network()
mark = stamp('service.network()', straight)

import random  # noqa: E402

from traffic.weather import NetworkWeather  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


weather = NetworkWeather(4242, 'moving')
mark = stamp('NetworkWeather(4242, moving)', straight)

geometries = [LineString(item['path']) for item in catalog['routes'] if item['path']]
mark = stamp(f'LineString x {len(geometries)}', straight)

tree = STRtree(geometries)
mark = stamp('STRtree(geometries)', straight)

static_policy = service.airport_footprint_policy()
static_obstacle = service.fixed_zones.envelope(static_policy)
mark = stamp('fixed_zones.envelope()', straight)

rng = random.Random(4242)
pending = []
for item in catalog['routes']:
    interval = 60 if item['mode'] == 'CAR' else 30
    for departure in range(0, service.TIMELINE_MINUTES, interval):
        for direction in (0, 1):
            wave_offset = (int(item['id'].rsplit('-', 1)[-1]) - 1) * 3 if item['mode'] == 'DELIVERY' else 0
            pending.append((departure + direction * 8 + wave_offset + rng.randint(0, 2), item['id'], direction, item))
pending.sort(key=lambda item: item[:3])
mark = stamp(f'pending 排班 x {len(pending)}', straight)

calendar = service.ResourceCalendar({pad['id']: pad.get('capacity', 1) for pad in catalog['pads']})
mark = stamp('ResourceCalendar', straight)

zone_settings = service.operations()['crossingZone']
profiles = service.profiles()
mark = stamp('operations() + profiles()', straight)

print()
print(f'--- 进入班次循环前共 {time.monotonic() - straight:.2f}s，班次数 {len(pending)} ---')
print(f'    进度回调粒度 = 1/{len(pending)}，即每 {1 / len(pending) * 100:.3f}%')

# Time the first few iterations to see the per-flight cost, which is where the
# other ~114 s goes.
loop = time.monotonic()
for index, (scheduled, route_id, direction, route_item) in enumerate(pending[:5]):
    item_started = time.monotonic()
    flight = service._flight(rng, route_item, direction, scheduled)
    print(f'    第 {index} 班 _flight() {time.monotonic() - item_started:.3f}s', flush=True)
print(f'    前 5 班仅 _flight() 共 {time.monotonic() - loop:.2f}s')
print(f'总计时 {time.monotonic() - overall:.2f}s')
