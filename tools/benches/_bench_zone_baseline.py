"""Confirm the baseline flight count is unchanged when the fixed zones are disabled.

The report has to say whether this round made planning slower. The warm
measurement showed 12.71 s with the feature stubbed out and 13.88 s with it on, but
that only proves the delta if the stubbed run is genuinely the same plan. This
prints the flight accounting for both, side by side.
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
REAL_ENVELOPE = zones.envelope
REAL_CROSSINGS = zones.crossings

service.network()
print('warm-up done', flush=True)


def describe(label):
    start = time.perf_counter()
    plan = service.simulate(seed=42, scenario='moving')
    elapsed = time.perf_counter() - start
    stats = plan['stats']
    from collections import Counter
    reasons = Counter(flight['reason'] for flight in plan['flights'])
    print(f'{label}: {elapsed:6.2f} s  flights={len(plan["flights"])} accepted={stats["accepted"]} '
          f'closed={stats["closed"]} reasons={dict(sorted(reasons.items(), key=lambda kv: -kv[1]))}',
          flush=True)


zones.envelope = lambda policy=zones.DEFAULT_POLICY: GeometryCollection()
zones.crossings = lambda points, policy=zones.DEFAULT_POLICY, limit=zones.DEFAULT_REPORT_LIMIT: EMPTY
try:
    describe('feature off ')
finally:
    zones.envelope = REAL_ENVELOPE
    zones.crossings = REAL_CROSSINGS

describe('feature on  ')
