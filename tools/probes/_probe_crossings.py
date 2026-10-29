"""Measure how many planned flights actually enter a fixed controlled airspace.

The red-vehicle alert is only worth having if it discriminates. If the default
APPROVAL_REQUIRED policy means nearly every flight crosses an aerodrome
protection area, then "red" carries no information and the presentation has to
separate a prohibition from an approval requirement instead of flagging both
with the same shout. This probe answers that with the planner's own output
rather than with an assumption.

Usage: python _probe_crossings.py [seed] [scenario]
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, ARTIFACTS  # noqa: E402
# _repo exports str; these names are used with path arithmetic.
ARTIFACTS = Path(ARTIFACTS)
import collections
import json
import time


from traffic import service, zones as fixed_zones  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
scenario = sys.argv[2] if len(sys.argv) > 2 else 'moving'

started = time.time()
result = service.simulate(seed, scenario)
elapsed = time.time() - started

flights = result.get('flights') or []
by_mode = collections.Counter()
entering = collections.Counter()
prohibited_entering = collections.Counter()
zones_per_flight = collections.Counter()
reasons = collections.Counter()
stat = result.get('stats', {}).get('staticAirspace', {})
peaks = []

for flight in flights:
    mode = flight.get('mode')
    by_mode[mode] += 1
    reasons[flight.get('reason')] += 1
    block = flight.get('staticAirspace') or {}
    zones = int(block.get('zones') or 0)
    zones_per_flight[zones] += 1
    if zones:
        entering[mode] += 1
        records = block.get('crossings') or []
        for index, record in enumerate(records):
            peaks.append((record.get('maxAglM') or 0, record.get('zoneId'), record.get('enforcement')))
    if int(block.get('prohibited') or 0) > 0:
        prohibited_entering[mode] += 1

total = len(flights) or 1
report = {
    'seed': seed,
    'scenario': scenario,
    'seconds': round(elapsed, 2),
    'policy': service.airport_footprint_policy(),
    'flights': len(flights),
    'byMode': dict(by_mode),
    'reasons': dict(reasons.most_common()),
    'enteringAnyZone': dict(entering),
    'enteringAnyZoneTotal': sum(entering.values()),
    'enteringAnyZoneShare': round(sum(entering.values()) / total, 4),
    'enteringProhibited': dict(prohibited_entering),
    'enteringProhibitedTotal': sum(prohibited_entering.values()),
    'enteringProhibitedShare': round(sum(prohibited_entering.values()) / total, 4),
    'zonesPerFlight': dict(sorted(zones_per_flight.items())),
    'planStats': {key: value for key, value in result.get('stats', {}).items()
                  if not isinstance(value, (list, dict))},
    'serverStats': stat,
    'maxAglWithinZone': {
        'min': round(min(p[0] for p in peaks), 1) if peaks else None,
        'max': round(max(p[0] for p in peaks), 1) if peaks else None,
    },
}
print(json.dumps(report, ensure_ascii=False, indent=2, default=str))

zones_list = json.loads(json.dumps(fixed_zones.status(service.airport_footprint_policy()), default=str))
print('catalog:', json.dumps(zones_list, ensure_ascii=False, default=str)[:400])

out = Path(ARTIFACTS) / '.run' / 'crossing_probe.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
