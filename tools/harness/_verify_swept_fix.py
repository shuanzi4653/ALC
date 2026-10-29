"""Retired: the snapped-envelope cache it verified is gone.

This checked that an outward-snapped cache key still *covered* the exact window
it was rounded from, and that the key space collapsed enough for the plan to stop
spending seconds in `_swept_band`. The finding shipped: grid snapping was
replaced by the convex-hull pruning in `NetworkWeather.envelope` /
`_swept_window`, which the safety probe now covers instead
(`_probe_swept_safety.py`, `test_no_trajectory_point_enters_the_drawn_risk_surface_at_its_own_minute`).

`_swept_snapped`, `swept_bin_floor` and `swept_bin_ceil` no longer exist, so this
cannot run as written. Kept rather than deleted: it is the audit trail for the
measurement that motivated the pruning. See _smoke_tools.py for the contract.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from _retired import retire  # noqa: E402

retire(
    '_verify_swept_fix.py',
    'grid-snapped envelope cache replaced by convex-hull pruning; API removed',
    'tools/harness/_verify_swept_safety.py and tools/benches/_bench_innovations.py',
)
