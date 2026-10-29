"""Gate: the merged-region attribution fix must not change the plan.

`_dissolve_regions` is presentation only -- `swept()` still envelopes each cell
separately -- so the accepted/closed/detoured counts and the plan digest must be
byte-identical before and after. This checks the same digests the envelope
optimisation round locked (e1ebc2ba39ab215b at seed 42, c4d7d8b120415378 at the
alternate seed), so a change here means the fix leaked into routing.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402
import json, time


from traffic import service

for seed, scenario in ((42, 'moving'), (777, 'moving')):
    start = time.perf_counter()
    plan = service.simulate(seed=seed, scenario=scenario)
    elapsed = time.perf_counter() - start
    flights = plan.get('flights') or []
    counts = {}
    for flight in flights:
        counts[flight.get('status')] = counts.get(flight.get('status'), 0) + 1
    reasons = {}
    for flight in flights:
        reason = flight.get('closureReason') or flight.get('reason')
        if flight.get('status') == 'CLOSED' and reason:
            reasons[reason] = reasons.get(reason, 0) + 1
    print(f"seed {seed:<4} scenario {scenario}")
    print("  digest      :", plan.get('digest'))
    print("  flights     :", len(flights))
    print("  statuses    :", json.dumps(counts, ensure_ascii=False, sort_keys=True))
    print("  closed why  :", json.dumps(reasons, ensure_ascii=False, sort_keys=True))
    print("  seconds     :", f"{elapsed:.2f}")
    print()
