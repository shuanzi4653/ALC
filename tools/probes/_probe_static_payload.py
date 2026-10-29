"""Throwaway probe: size and shape of the staticAirspace block in /traffic/network.

The fixed-zone catalogue ships inside the network payload, and 48 aerodrome
footprints clipped to the province boundary can produce a lot of vertices. Before
trusting the map code, measure what the browser actually has to parse.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import json
import time
from pathlib import Path


from traffic import service  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


start = time.perf_counter()
catalog = service.network()
elapsed = time.perf_counter() - start

block = catalog['staticAirspace']
zones = block['zones']
with_geometry = [z for z in zones if z.get('geometry')]
registered = [z for z in zones if not z.get('geometry')]


def vertices(geometry):
    if not geometry:
        return 0
    total = 0
    for polygon in geometry['coordinates']:
        for ring in polygon:
            total += len(ring)
    return total


raw = json.dumps(catalog, ensure_ascii=False)
raw_zones = json.dumps(block, ensure_ascii=False)

print(f'network() {elapsed:.2f}s')
print(f'payload total {len(raw.encode()) / 1024:.0f} KiB, staticAirspace {len(raw_zones.encode()) / 1024:.0f} KiB')
print(f'zones {len(zones)} (geometry {len(with_geometry)}, registered {len(registered)})')
print(f'total vertices {sum(vertices(z.get("geometry")) for z in with_geometry)}')
print('status', json.dumps(block['status'], ensure_ascii=False))
print('audit sites', block['audit']['sites'], 'withGeometry', block['audit']['withGeometry'])

biggest = sorted(with_geometry, key=lambda z: -vertices(z['geometry']))[:3]
for zone in biggest:
    print(f"  {zone['id']} {zone['name']}: {vertices(zone['geometry'])} vertices, "
          f"floor {zone['floorAglM']}, displayCeiling {zone['displayCeilingAglM']}, "
          f"openEndedAbove {zone['openEndedAbove']}, enforcement {zone['enforcement']}")

print('--- sample registered ---')
for zone in registered[:3]:
    print(f"  {zone['id']} {zone['name']} status={zone['geometryStatus']} "
          f"ref={zone['referencePoint']['coordinate']} enforcement={zone['enforcement']}")

print('--- sample volume ---')
sample = with_geometry[0]
print(json.dumps({k: v for k, v in sample.items() if k != 'geometry'}, ensure_ascii=False))
print('geometry type', sample['geometry']['type'], 'ring0 first 2 pts', sample['geometry']['coordinates'][0][0][:2])
