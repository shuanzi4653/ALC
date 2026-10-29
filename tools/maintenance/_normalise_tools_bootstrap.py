"""Finish the tools/ reorg repair: add missing imports, put the bootstrap first.

Repository maintenance script.

Two defects remain from the mechanical rewrite, both harmless at compile time and
both fatal at run time:

1. `os` is referenced but never imported. The bootstrap line uses
   `os.path.dirname(...)`, so a file that only had `import sys` now raises
   NameError. The bootstrap should not depend on names the file may not import --
   use the `_os` alias it defines itself.

2. The bootstrap sits after project imports it is supposed to enable. Project
   imports need `backend-python` on sys.path, so the bootstrap has to come first.

This normalises every tools/** file to one shape:

    <standard library imports>

    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from _repo import ROOT, ...            # noqa: E402

    sys.path.insert(0, BACKEND)

    <project imports>

Run with --apply to write. Default is a dry run.
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)

BOOTSTRAP = (
    "import os as _os\n"
    "import sys as _sys\n"
    "_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))\n"
)

# The bootstrap block as it may currently appear, with any of several bodies.
CURRENT = re.compile(
    r"^(\s*)import os as _os\n"
    r"(\s*)import sys as _sys\n"
    r"\s*_sys\.path\.insert\(0,\s*(?:os|_os)\.path\.dirname\((?:os|_os)\.path\.abspath\(__file__\)\)\)\n"
    r"\s*from _repo import ([^\n]*?)(\s*# noqa: E402)?\s*$",
    re.MULTILINE,
)

STDLIB = {
    "abc", "argparse", "collections", "copy", "csv", "datetime", "functools",
    "glob", "io", "itertools", "json", "math", "os", "pathlib", "random",
    "re", "shutil", "statistics", "subprocess", "sys", "tempfile", "time",
    "typing", "unicodedata", "urllib", "warnings",
}


def standard_lib_imports(text):
    """Top-level import lines that only pull in the standard library."""
    found = []
    for line in text.split("\n"):
        if not line or line[0] in " \t#":
            continue
        stripped = line.strip()
        if stripped.startswith("import "):
            name = stripped[7:].split()[0].split(".")[0].split(",")[0]
            if name in STDLIB:
                found.append(line)
        elif stripped.startswith("from "):
            name = stripped.split()[1].split(".")[0]
            if name in STDLIB and name != "_repo":
                found.append(line)
    return found


def main():
    apply = "--apply" in sys.argv
    hits = []

    for folder, _dirs, files in os.walk(TOOLS):
        if os.path.normpath(folder) == os.path.normpath(HERE):
            continue
        for name in files:
            if not name.endswith(".py") or name in ("_repo.py",):
                continue
            full = os.path.join(folder, name)
            text = io.open(full, encoding="utf-8").read()
            match = CURRENT.search(text)
            if not match:
                continue

            names = match.group(3).strip()
            body_start = match.start()
            rest = text[match.end():].lstrip("\n")

            head = text[:body_start]
            # Drop the old bootstrap lines and any stray duplicate imports that
            # were left floating in head.
            head = head.replace("import os as _os\n", "")
            head = head.replace("import sys as _sys\n", "")
            head = re.sub(
                r"^\s*_sys\.path\.insert\(0,\s*(?:os|_os)\.path\.dirname\((?:os|_os)\.path\.abspath\(__file__\)\)\)\s*$",
                "", head, flags=re.MULTILINE)
            head = re.sub(r"\n{3,}", "\n\n", head).rstrip() + "\n"

            block = BOOTSTRAP + "from _repo import " + names + "  # noqa: E402\n"
            if "BACKEND" in names or re.search(r"\bBACKEND\b", text):
                block += "\nsys.path.insert(0, BACKEND)\n"

            new = head + "\n" + block + "\n" + rest
            new = re.sub(r"\n{4,}", "\n\n\n", new)
            if not new.endswith("\n"):
                new += "\n"

            hits.append(os.path.relpath(full, os.path.dirname(TOOLS)))
            if apply:
                io.open(full, "w", encoding="utf-8", newline="\n").write(new)

    print(("APPLIED" if apply else "DRY RUN") + ": " + str(len(hits)) + " files")
    for item in hits:
        print("  " + item)


if __name__ == "__main__":
    main()
