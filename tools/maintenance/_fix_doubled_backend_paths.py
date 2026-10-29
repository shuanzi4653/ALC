"""Repair the doubled backend segment left by the root-reference rewrite.

Repository maintenance script.

Files that expressed the backend path as

    sys.path.insert(0, str(Path(__file__).resolve().parent / 'backend-python'))

were rewritten to

    sys.path.insert(0, str(Path(BACKEND) / 'backend-python'))

because the rewrite mapped the self-directory to BACKEND while leaving the
trailing segment in place. The result points at backend-python/backend-python.

The correct form is a plain `sys.path.insert(0, BACKEND)`. This also runs after
the bootstrap insert, so the two-line shape is handled as well.

Run with --apply to write. Default is a dry run.
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)

PATTERNS = [
    (re.compile(r"sys\.path\.insert\(0,\s*str\(Path\(BACKEND\)\s*/\s*'backend-python'\)\)"),
     "sys.path.insert(0, BACKEND)"),
    (re.compile(r'sys\.path\.insert\(0,\s*str\(Path\(BACKEND\)\s*/\s*"backend-python"\)\)'),
     "sys.path.insert(0, BACKEND)"),
    (re.compile(r"sys\.path\.insert\(0,\s*str\(Path\(ROOT\)\s*/\s*'backend-python'\)\)"),
     "sys.path.insert(0, BACKEND)"),
    (re.compile(r"sys\.path\.insert\(0,\s*str\(Path\(FRONTEND\)\s*/\s*'frontend'\)\)"),
     "sys.path.insert(0, FRONTEND)"),
    # The same doubling can appear without the str() wrapper.
    (re.compile(r"sys\.path\.insert\(0,\s*os\.path\.join\(BACKEND,\s*'backend-python'\)\)"),
     "sys.path.insert(0, BACKEND)"),
    (re.compile(r"sys\.path\.insert\(0,\s*Path\(BACKEND\)\s*/\s*'backend-python'\)"),
     "sys.path.insert(0, BACKEND)"),
]


def main():
    apply = "--apply" in sys.argv
    hits = []

    for folder, _dirs, files in os.walk(TOOLS):
        if os.path.normpath(folder) == os.path.normpath(HERE):
            continue
        for name in files:
            if not name.endswith(".py") or name == "_repo.py":
                continue
            full = os.path.join(folder, name)
            text = io.open(full, encoding="utf-8").read()
            new = text
            for pattern, replacement in PATTERNS:
                new = pattern.sub(replacement, new)
            if new == text:
                continue
            hits.append(os.path.relpath(full, os.path.dirname(TOOLS)))
            if apply:
                io.open(full, "w", encoding="utf-8", newline="\n").write(new)

    print(("APPLIED" if apply else "DRY RUN") + ": " + str(len(hits)) + " files")
    for item in hits:
        print("  " + item)


if __name__ == "__main__":
    main()
