"""Shared marker for a probe whose target implementation has been removed.

A probe is *retired*, not broken, when the thing it measured no longer exists
because the design moved past it. The probe is still worth keeping: it is the
measurement that justified the change, and `docs/paper-innovations.md` cites it.
Deleting it would destroy the audit trail; letting it crash would drown the real
failures in the smoke run.

Contract
--------
Call ``retire(name, why, replaced_by)`` from the probe's top and exit 0. The
smoke harness treats a line starting with ``RETIRED:`` on stdout as a clean
result and reports it in its own bucket.

Example::

    from _retired import retire
    retire('_diag_swept_diff.py',
           'measured the binned-snapping envelope',
           'the envelope is now exact (convex-hull support pruning), so there '
           'are no bins to snap -- see weather.NetworkWeather._swept_window')
"""
import sys

MARKER = 'RETIRED:'


def retire(name, why, replaced_by=None):
    """Print a RETIRED line and exit 0."""
    lines = [
        '%s %s' % (MARKER, name),
        '  measured : %s' % why,
    ]
    if replaced_by:
        lines.append('  now      : %s' % replaced_by)
    lines.append('  status   : kept as the audit trail for a finding that shipped.')
    sys.stdout.write('\n'.join(lines) + '\n')
    sys.stdout.flush()
    sys.exit(0)
