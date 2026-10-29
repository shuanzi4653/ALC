"""A/B the plan cost with and without the fixed-zone accounting."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import time
from pathlib import Path


from traffic import service, zones  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


real_crossings = zones.crossings


def run(label):
    for scenario in ('clear', 'moving'):
        start = time.perf_counter()
        service.FP_CACHE = None
        result = service.simulate(seed=42, scenario=scenario)
        print(f'{label:10} {scenario:7} {time.perf_counter() - start:6.2f}s '
              f'accepted={result["stats"]["accepted"]}')


run('with')
zones.crossings = lambda points, policy=zones.DEFAULT_POLICY, limit=8: (
    {'zones': 0, 'prohibited': 0, 'approvalRequired': 0, 'clauses': []}, [])
run('without')
zones.crossings = real_crossings
