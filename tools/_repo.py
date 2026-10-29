"""Repo-root resolver for scripts that live under tools/ (any depth).

Scripts were originally flat in the repository root, so `os.path.dirname(__file__)`
was the repo root. After the tools/ reorganisation they sit in tools/<class>/, so
that expression points one or two levels too deep.

Import this instead of recomputing the root by hand:

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS
    from _repo import artifact, version, package_dir

Use ``artifact('name.json')`` for any file under ``artifacts/``: producers and
consumers then share one definition of where generated files live, instead of
each hard-coding a path that breaks the moment the directory moves.

Executing a script that imports this module works from any working directory.
When you add a name here, add it to `EXPORTED` in
`tools/maintenance/_normalise_all_bootstraps.py` as well -- that list is what the
rewriter preserves, and anything absent from it gets dropped from the files it
normalises.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _find_root(start):
    """Walk up from `start` until a directory containing the repo markers is found."""
    current = start
    for _ in range(6):
        has_backend = os.path.isdir(os.path.join(current, "backend-python"))
        has_frontend = os.path.isdir(os.path.join(current, "frontend"))
        if has_backend and has_frontend:
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    raise RuntimeError("repository root not found above " + start)


ROOT = _find_root(_HERE)
BACKEND = os.path.join(ROOT, "backend-python")
FRONTEND = os.path.join(ROOT, "frontend")
SCRIPTS = os.path.join(ROOT, "scripts")
DOCS = os.path.join(ROOT, "docs")
CONTRACTS = os.path.join(ROOT, "contracts")
ARTIFACTS = os.path.join(ROOT, "artifacts")
TOOLS = os.path.join(ROOT, "tools")
SHARED = os.path.join(TOOLS, "shared")

if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
# `tools/shared/` holds helpers that more than one script needs (cell-geometry
# accessors, the retirement marker). Putting it on the path here means a script
# only has to import _repo -- importing the shared helper needs no extra
# sys.path line of its own. That matters because the bootstrap normaliser
# rewrites the *first* sys.path.insert it finds and would otherwise drop a
# hand-written one pointing at shared/.
if SHARED not in sys.path:
    sys.path.insert(1, SHARED)


def artifact(name):
    """Absolute path of a generated artefact, by file name only.

    Scripts used to write `_sim_report.json` and friends straight into the repo
    root. When those moved into artifacts/, every reader that still said
    ``os.path.join(ROOT, name)`` began failing with FileNotFoundError -- after
    the producer had already succeeded, which is the worst time to find out.

    Keeping both ends on this one function is what makes the directory a single
    fact. Call it with a bare name, never a path.
    """
    if os.path.dirname(name):
        raise ValueError("artifact() takes a file name, not a path: " + name)
    os.makedirs(ARTIFACTS, exist_ok=True)
    return os.path.join(ARTIFACTS, name)


def version():
    """The product version, read from ``VERSION`` (e.g. ``0.9.26-beta``)."""
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as handle:
        return handle.read().strip()


def package_dir():
    """Absolute path of the hand-off package directory, named after ``VERSION``.

    Both the producer and its verifier used to hard-code the release they were
    written for, so the moment the version moved they kept pointing at the old
    directory: found on 2026-10-10 with ``VERSION`` at ``0.9.26-beta`` while
    ``_build_handoff_pack.py`` and ``_verify_handoff_pack.py`` both still said
    ``ALC-交付-0.9.25-beta``. Naming it from one place is what stops the two
    ends drifting apart again -- and drifting *silently*, since the verifier
    would happily re-verify the previous release's directory.
    """
    return os.path.join(os.path.dirname(ROOT), "ALC-交付-" + version())
