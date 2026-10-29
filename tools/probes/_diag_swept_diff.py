"""RETIRED -- measured the binned-snapping envelope, which no longer exists.

Original question
-----------------
`swept_bin_floor(0)=0` and `swept_bin_ceil(2)=12`, so bins (0,2) snapped to
(0,12) -- strictly wider. A non-zero `wanted.difference(served)` area therefore
could not be explained by narrowing, and needed a concrete cause before the fix
could ship.

Why it is retired
-----------------
The window is no longer snapped to a coarse bin lattice. `envelope()` bins to the
5-minute sampling step and delegates straight to `_swept_window`, and the band's
hull cost was fixed on the *cost* side instead -- `_outline_hull_coords` reduces
820 outline vertices to the handful on the convex hull, so the hull is exact
rather than approximated. There are no snapped/un-snapped pair to compare, and a
"snapped" reading cannot be produced at all: `weather._swept_snapped` is gone.

The finding this probe produced (snapping was never the cause of the area
difference; the slivers were buffer chord artifacts) is written up in
docs/paper-innovations.md. It is kept as the audit trail, not deleted.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from _retired import retire  # noqa: E402  (_repo puts tools/shared on the path)

retire('_diag_swept_diff.py',
       'the coarse binned-snapping envelope and its exact/snapped difference',
       'the hull is now exact (_outline_hull_coords bounds the sampled outline '
       'to its convex hull), so no snapping step exists to differ from')
