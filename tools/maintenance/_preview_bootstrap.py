"""Retired: the rewrite it previewed has been applied and verified.

This printed the before/after of the bootstrap normaliser so the transform could
be eyeballed before it ran across the tree. The transform is done -- measured
across tools/, zero files still carry the old `import os as _os` form -- and the
normaliser is now idempotent, so there is nothing left to preview.

Kept, not deleted, because it is the audit trail for how the rewrite was
reviewed before being trusted. See _smoke_tools.py for the RETIRED contract.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Importing _repo is what puts tools/shared on the path, so it has to come
# before _retired (which lives there). Two separate inserts would work too, but
# the bootstrap normaliser keeps only the first one it finds.
from _repo import ROOT  # noqa: E402,F401
from _retired import retire  # noqa: E402

retire(
    '_preview_bootstrap.py',
    'target style no longer exists in tools/ (0 matches), normaliser is idempotent',
    'tools/maintenance/_normalise_all_bootstraps.py --apply (dry-run shows the diff)',
)
