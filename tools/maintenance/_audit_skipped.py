"""Classify the files the bootstrap normaliser skipped.

A file legitimately has no bootstrap when it touches nothing repo-relative: the
pure HTTP probes only speak to 127.0.0.1 and never open a file under the repo.
Anything else that was skipped is a real miss and needs a bootstrap added.

    _audit_skipped.py
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, TOOLS  # noqa: E402
import io
import re  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _normalise_all_bootstraps as N  # noqa: E402

# Anything that would need the repo root, one way or another.
NEEDS_ROOT = [
    (re.compile(r"""['"][^'"]*(?:backend-python|frontend|contracts|artifacts|changelog)"""), "repo-relative string"),
    (re.compile(r"open\(|io\.open\(|Path\([^)]*\)\.(?:read|write)|read_text|write_text"), "file I/O"),
    (re.compile(r"\.run[/\\]|__file__"), "repo layout reference"),
    (re.compile(r"from traffic import|import traffic"), "project import"),
    (re.compile(r"_repo"), "already uses _repo"),
]


def main():
    for folder, _dirs, files in os.walk(TOOLS):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            full = os.path.join(folder, name)
            rel = os.path.relpath(full, TOOLS)
            text = io.open(full, encoding="utf-8").read()
            result, note = N.rewrite(full, text)
            if result is not None:
                continue
            if name in N.SELF_CONTAINED:
                print("  [self-contained] %-48s %s" % (rel, note))
                continue
            hits = [label for pattern, label in NEEDS_ROOT if pattern.search(text)]
            verdict = "NEEDS BOOTSTRAP" if hits else "clean (no repo reference)"
            print("  %-16s %-48s %s" % (verdict, rel, ", ".join(hits) or "-"))


if __name__ == "__main__":
    main()
