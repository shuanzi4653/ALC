"""Does the hard-block path actually work? Exercise the strict policy end to end."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import statistics
import json
import time
from pathlib import Path


from traffic import service, zones  # noqa: E402
from traffic.catalog import cities  # noqa: E402


for policy in (zones.APPROVAL_REQUIRED, zones.PROHIBITED):
    envelope = zones.envelope(policy)
    covered = [city['name'] for city in cities()
               if envelope.covers(__import__('shapely.geometry', fromlist=['Point']).Point(city['xy']))]
    print(f'--- policy {policy}')
    print('  prohibited zones:', sum(1 for site in zones.sites(policy) if site['enforcement'] == zones.PROHIBITED))
    print('  envelope area km2:', round(envelope.area / 1e6, 1) if not envelope.is_empty else 0)
    print('  城市枢纽落在硬阻断区内:', len(covered), covered)

# Now drive the scheduler with the strict policy and read the real statistics.
# The policy is read from aircraft-profiles.json, so monkeypatch the accessor
# rather than clearing the profile cache (which would just re-read the file).
service.airport_footprint_policy = lambda: zones.PROHIBITED
service.static_airspace.cache_clear()
for name in ('_by_id', '_geometries', '_index'):
    getattr(zones, name).cache_clear()

print()
print('strict policy resolved as:', service.airport_footprint_policy())
start = time.perf_counter()
result = service.simulate(seed=42, scenario='clear')
print(f'plan {time.perf_counter() - start:.2f}s')
stats = result['stats']
print('flights', stats['flights'], 'accepted', stats['accepted'], 'closed', stats['closed'])
print('staticAirspace', json.dumps(stats['staticAirspace'], ensure_ascii=False))
reasons = {}
for flight in result['flights']:
    if flight['status'] != 'SCHEDULED':
        reasons[flight['reason']] = reasons.get(flight['reason'], 0) + 1
print('closed reasons', json.dumps(reasons, ensure_ascii=False, sort_keys=True))
