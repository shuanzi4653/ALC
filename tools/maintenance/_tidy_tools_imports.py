"""Collapse the two-pass bootstrap block in tools/** into one clean import.

Repository maintenance script.

Pass one rewrote the repo-root expressions, pass two inserted a bootstrap that
referenced `os` and `sys` under aliases. Files that already import os and sys at
module level now carry those twice. This collapses the block to a single import,
keeping the one `__file__`-relative sys.path line because tools/_repo.py is not
importable until tools/ is on the path.

Before:
    import os
    ...
    import os as _os
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(_os.path.abspath(__file__)))
    from _repo import ROOT, BACKEND  # noqa: E402

After:
    import os
    ...
    import os as _os
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(_os.path.abspath(__file__)))
    from _repo import ROOT, BACKEND

Run with --apply to write. Default is a dry run.
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)

BLOCK = re.compile(
    r"import os as _os\nimport sys as _sys\n"
    r"_sys\.path\.insert\(0, (?:os\.path\.dirname\()*_os\.path\.abspath\(__file__\)\)+\)\n"
    r"from _repo import ([^\n]*?)  # noqa: E402",
)

CLEAN = (
    "import os as _os\n"
    "import sys as _sys\n"
    "_sys.path.insert(0, os.path.dirname(_os.path.abspath(__file__)))\n"
    "from _repo import {names}  # noqa: E402"
)


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
            if "import os as _os" not in text:
                continue
            depth = os.path.relpath(full, TOOLS).count(os.sep)
            if depth > 1:
                # Nested depth keeps the generated dirname chain; skip.
                continue
            new, count = BLOCK.subn(
                lambda m: CLEAN.format(names=m.group(1).strip()), text, count=1
            )
            if not count:
                continue
            hits.append(os.path.relpath(full, os.path.dirname(TOOLS)))
            if apply:
                io.open(full, "w", encoding="utf-8", newline="\n").write(new)

    print(("APPLIED" if apply else "DRY RUN") + ": " + str(len(hits)) + " files")
    for item in hits:
        print("  " + item)


if __name__ == "__main__":
    main()
