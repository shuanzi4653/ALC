"""Make the tools/_repo.py import from every tools/** script actually work.

Repository maintenance script.

The root-reference rewrite emits `from ._repo import ...`, which is only valid
when tools/ is treated as a package and the script is launched with `-m`. Plain
`python tools/probes/foo.py` has no package context, so the relative import
fails.

This inserts the two lines that make the absolute import work from any depth:

    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS

Run with --apply to write. Default is a dry run.
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)

REL_IMPORT = re.compile(r"^from \.+_repo import .*$", re.MULTILINE)


def depth_below_tools(path):
    rel = os.path.relpath(path, TOOLS)
    return rel.count(os.sep)


def replacement(path):
    up = depth_below_tools(path)
    parent_chain = ", ".join(["os.path.dirname"] * up)
    return (
        "import os as _os\n"
        "import sys as _sys\n"
        "\n"
        "_sys.path.insert(0, " + parent_chain + "(_os.path.abspath(__file__)))\n"
        "from _repo import ROOT, BACKEND, FRONTEND, SCRIPTS, DOCS  # noqa: E402"
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
            if not REL_IMPORT.search(text):
                continue
            if "_repo import" not in text:
                continue
            if "_sys.path.insert" in text:
                continue
            new = REL_IMPORT.sub(lambda _m: replacement(full), text, count=1)
            hits.append(os.path.relpath(full, os.path.dirname(TOOLS)))
            if apply:
                io.open(full, "w", encoding="utf-8", newline="\n").write(new)

    print(("APPLIED" if apply else "DRY RUN") + ": " + str(len(hits)) + " files")
    for item in hits:
        print("  " + item)


if __name__ == "__main__":
    main()
