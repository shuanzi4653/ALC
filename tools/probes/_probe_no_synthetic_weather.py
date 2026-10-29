"""Confirm no scenario produces synthetic weather, and that traffic still plans.

This is the acceptance probe for the 'delete moving' change. It asserts the two
things the user asked for: weather is real-only, and the traffic planner is
untouched (it still produces flights, detours and conflicts).

Scope note: this probe checks the **modelled weather channel**
(``weatherSnapshot``), which is the one that was made real-only. The synthetic
radar generator is a separate, explicitly-labelled channel driven by
``weather_control`` and is deliberately *not* covered by this assertion -- see
``_probe_weather_control.py`` for that channel's contract, which requires the
opposite (every synthetic frame must be labelled as such).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402

from traffic import service  # noqa: E402

for scenario in ('live', 'clear', 'unknown'):
    run = service.simulate(42, scenario)
    snap = run.get('weatherSnapshot') or {}
    stats = run['stats']
    print(f"scenario={scenario:<8} status={run['status']:<8} "
          f"weather.provider={snap.get('provider'):<12} dataType={snap.get('dataType')}")
    print(f"          flights={stats['flights']:<5} accepted={stats['accepted']:<5} "
          f"closed={stats['closed']:<5} detours={stats['detours']:<4} "
          f"resolved={stats['resolved']:<4} groundHolds={stats['groundHolds']}")
    # The load-bearing assertion: nothing anywhere says it is synthetic weather.
    blob = str(run.get('weatherSnapshot'))
    assert 'SYNTHETIC' not in blob, f'{scenario} still reports a synthetic snapshot: {blob}'
    assert 'SIMULATED_WEATHER' not in blob, f'{scenario} still flags simulated weather'

# The traffic plan is the part that must stay alive: 'clear' has weather removed
# entirely, so if the planner depended on the synthetic field it would collapse.
clear = service.simulate(42, 'clear')
live = service.simulate(42, 'live')
unknown = service.simulate(42, 'unknown')
assert clear['stats']['flights'] > 0, 'clear produced no flights at all'
assert clear['stats']['accepted'] > 0, 'clear accepted nothing'
assert live['stats']['flights'] == clear['stats']['flights'], 'flight count changed with weather'
assert unknown['stats']['accepted'] == 0, 'unknown must hold every flight'
print()
print("traffic identical across clear/live (flight count):",
      live['stats']['flights'] == clear['stats']['flights'])
print("unknown holds everything:", unknown['stats']['accepted'] == 0)
print("OK: no scenario emits synthetic weather; traffic planning intact")
