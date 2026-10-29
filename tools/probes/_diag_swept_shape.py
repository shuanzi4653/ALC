"""RETIRED -- measured the binned-snapping envelope, which no longer exists.

Original question
-----------------
Were the snapped/exact difference slivers (2.9-4662 m2) buffer chord artifacts
rather than real gaps? The snapped envelope was larger in total area with a
strictly containing bounding box, which pointed at the circular-arc join
approximation in `buffer()`: a longer track is buffered with different chording,
so the two arcs cross.

Why it is retired
-----------------
There is no snapped envelope to compare against. The window is no longer snapped
to a coarse bin lattice, and the band's hull cost was addressed on the cost side
-- `_outline_hull_coords` bounds the sampled outline to its convex hull, so the
hull is exact rather than approximated. `weather._swept_snapped` no longer
exists, so the comparison cannot be formed.

The conclusion it produced -- the slivers were buffer chord artifacts, confirmed
by their sub-50 m thickness -- is recorded in docs/paper-innovations.md. Kept as
the audit trail for a finding that shipped.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
from _retired import retire  # noqa: E402  (_repo puts tools/shared on the path)

retire('_diag_swept_shape.py',
       'whether the snapped/exact slivers were buffer chord artifacts',
       'the snapping step is gone; the hull is exact now, so there are no '
       'slivers to attribute')
