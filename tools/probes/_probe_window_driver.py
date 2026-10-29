"""RETIRED -- profiled the binned window cache, which no longer exists.

Original question
-----------------
The swept window was `(floor(departure/5), ceil((departure + duration +
maxExtra)/5))` and 1035 distinct windows meant the pair varied a lot. This
reported which component drove the variance, to key the cache on something that
repeats instead of guessing.

Why it is retired
-----------------
The probe spied by replacing `NetworkWeather.swept`, then restored it with
`NetworkWeather.__dict__['_swept_snapped']`. Both halves are gone: `swept()`
now has no callers in the plan (the planner calls `envelope()`, which bins and
delegates to the cached `_swept_window`), and `_swept_snapped` was removed when
the coarse bin lattice was dropped.

Its replacement is `_probe_swept_keys.py`, which spies on `envelope` -- the call
the planner actually makes -- and reports the same distinct-window and span
histogram (13731 calls, 1061 distinct windows, span 14 dominant). Its finding is
recorded in docs/paper-innovations.md; kept as the audit trail.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from _retired import retire  # noqa: E402  (_repo puts tools/shared on the path)

retire('_probe_window_driver.py',
       'which component of the binned swept window drove its variance',
       '_probe_swept_keys.py now spies on envelope(), the call the planner '
       'actually makes, and reports the same span histogram')
