"""Attribute the planning cost of the fixed-zone feature.

The evidence run printed 17.49 s for the default policy and 11.92 s for the strict
one, in that order — the reverse of what the geometry sizes suggest. Either the
first measurement paid a cold-process cost, or the fixed zones really do add
seconds to every plan. This measures four cases in one warm process so the numbers
are comparable:

  A. warm baseline with the feature switched off entirely
  B. warm baseline with only the per-flight crossing report enabled
  C. warm, default policy (approval-gated aerodromes)
  D. warm, strict policy (aerodromes joined to the obstacle set)

Plus the two ``envelope`` unions on their own, since the strict reading unions 48
large rectangles and that is the one operation that could plausibly cost seconds.

Run:  backend-python\\.venv\\Scripts\\python.exe _bench_static_zones.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import time
from pathlib import Path


from shapely.geometry import GeometryCollection  # noqa: E402

from traffic import service, zones  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


EMPTY = ({'zones': 0, 'prohibited': 0, 'approvalRequired': 0, 'clauses': []}, [])

# Snapshot everything that gets monkeypatched so each case starts from the real
# implementation instead of inheriting the previous case's stub.
REAL_ENVELOPE = zones.envelope
REAL_CROSSINGS = zones.crossings
REAL_POLICY = service.airport_footprint_policy


def timed(label, function):
    start = time.perf_counter()
    value = function()
    elapsed = time.perf_counter() - start
    print(f'{label:<40} {elapsed:6.2f} s', flush=True)
    return elapsed, value


def plan():
    return service.simulate(seed=42, scenario='moving')


def restore():
    zones.envelope = REAL_ENVELOPE
    zones.crossings = REAL_CROSSINGS
    service.airport_footprint_policy = REAL_POLICY


print('--- envelope unions ---', flush=True)
timed('envelope(APPROVAL_REQUIRED) first', lambda: zones.envelope(zones.APPROVAL_REQUIRED))
timed('envelope(APPROVAL_REQUIRED) cached', lambda: zones.envelope(zones.APPROVAL_REQUIRED))
timed('envelope(PROHIBITED) first', lambda: zones.envelope(zones.PROHIBITED))
timed('envelope(PROHIBITED) cached', lambda: zones.envelope(zones.PROHIBITED))

print('\n--- warm-up (discarded) ---', flush=True)
service.network()
timed('warm-up simulate', plan)

results = {}

print('\n--- A: feature off ---', flush=True)
zones.envelope = lambda policy=zones.DEFAULT_POLICY: GeometryCollection()
zones.crossings = lambda points, policy=zones.DEFAULT_POLICY, limit=zones.DEFAULT_REPORT_LIMIT: EMPTY
results['A'], _ = timed('A 关闭全部固定管制逻辑', plan)
restore()

print('\n--- B: crossings only ---', flush=True)
zones.envelope = lambda policy=zones.DEFAULT_POLICY: GeometryCollection()
results['B'], _ = timed('B 仅保留逐班次穿越记录', plan)
restore()

print('\n--- C: default policy ---', flush=True)
service.airport_footprint_policy = lambda: zones.APPROVAL_REQUIRED
results['C'], default_plan = timed('C 默认口径（须批准）', plan)
restore()

print('\n--- D: strict policy ---', flush=True)
service.airport_footprint_policy = lambda: zones.PROHIBITED
results['D'], strict_plan = timed('D 严格口径（禁入）', plan)
restore()

print('\n--- attribution (warm, same process) ---')
print(f"A 关闭全部固定管制逻辑        {results['A']:6.2f} s")
print(f"B 只保留穿越记录              {results['B']:6.2f} s")
print(f"C 默认口径                    {results['C']:6.2f} s")
print(f"D 严格口径                    {results['D']:6.2f} s")
print(f"穿越记录净增 (B-A)            {results['B'] - results['A']:+6.2f} s")
print(f"默认口径净增 (C-A)            {results['C'] - results['A']:+6.2f} s")
print(f"严格口径净增 (D-A)            {results['D'] - results['A']:+6.2f} s")

for label, value in (('默认', default_plan), ('严格', strict_plan)):
    stats = value['stats']
    print(f"{label}口径 flights {len(value['flights'])} accepted {stats['accepted']} "
          f"closed {stats['closed']} staticBlocked {stats['staticAirspace']['closedByStaticAirspace']} "
          f"needApproval {stats['staticAirspace']['flightsRequiringApproval']} "
          f"crossings {stats['staticAirspace']['crossingRecords']}")
