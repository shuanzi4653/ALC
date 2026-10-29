"""Repair repo-root lookups that the tools/ reorganisation broke.

Repository maintenance script.

The helpers used to live flat in the repository root, so both of these were the
root:

    ROOT = os.path.dirname(os.path.abspath(__file__))
    ROOT = Path(__file__).resolve().parent

After the move to tools/<class>/ they point one level too deep, which breaks
`sys.path.insert`, `os.chdir`, and every path built from ROOT. Nothing raises at
import time in most cases -- the script just reads or writes the wrong place,
which is why this is worth a mechanical pass rather than spot fixes.

Both idioms are rewritten to derive the root from tools/_repo.py, which walks up
until it finds the repository markers and therefore works at any depth:

    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from _repo import ROOT

Run with --apply to write. Default is a dry run that lists what would change.
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)

MARKERS = ("backend-python", "frontend", "scripts", "docs", "contracts", ".run")

OS_STYLE = "os.path.dirname(os.path.abspath(__file__))"
PATH_OS_JOIN = re.compile(
    r"os\.path\.join\(\s*os\.path\.dirname\(os\.path\.abspath\(__file__\)\)\s*,\s*(['\"])([^'\"]+)\1\s*\)"
)
PATH_STYLE_PARENT = re.compile(r"Path\(__file__\)\.resolve\(\)\.parent")
PATH_JOIN = re.compile(
    r"Path\(__file__\)\.resolve\(\)\.parent\s*/\s*(['\"])([^'\"]+)\1"
)

IMPORT_PROBE = "_repo import"


def depth_below_tools(path):
    return os.path.relpath(path, TOOLS).count(os.sep)


def bootstrap(path):
    """Lines that make `from _repo import ...` work from this file's depth."""
    up = depth_below_tools(path)
    chain = ", ".join(["os.path.dirname"] * up)
    return (
        "import os as _os\n"
        "import sys as _sys\n"
        "_sys.path.insert(0, " + chain + "(_os.path.abspath(__file__)))\n"
    )


def needs_repo_root(path):
    """True when the file should import ROOT from _repo.py."""
    return True


def rewrite(text, path):
    original = text

    # Case 1: os.path.join(<self>, 'target') -> <TARGET>
    def join_repl(match):
        target = match.group(2)
        alias = target.split("/")[0].split("\\")[0]
        table = {
            "backend-python": "BACKEND",
            "frontend": "FRONTEND",
            "scripts": "SCRIPTS",
            "docs": "DOCS",
            "contracts": "CONTRACTS",
            "artifacts": "ARTIFACTS",
        }
        return table.get(alias, "ROOT")

    text = PATH_OS_JOIN.sub(join_repl, text)

    # Case 2: Path(__file__).resolve().parent / 'target' -> Path(<TARGET>) / 'target'
    # Only for repo-level markers; anything else keeps the self-relative join.
    def path_join_repl(match):
        target = match.group(2)
        head = target.split("/")[0]
        if head == ".run":
            return "Path(ARTIFACTS) / " + match.group(1) + target + match.group(1)
        table = {
            "backend-python": "BACKEND",
            "frontend": "FRONTEND",
            "scripts": "SCRIPTS",
            "docs": "DOCS",
            "contracts": "CONTRACTS",
            "artifacts": "ARTIFACTS",
        }
        if head in table:
            return "Path(" + table[head] + ") / " + match.group(1) + target + match.group(1)
        return match.group(0)

    text = PATH_JOIN.sub(path_join_repl, text)

    # Case 3: the bare self-dir expressions, which were the repo root.
    text = text.replace("Path(__file__).resolve().parent", "Path(ROOT)")
    text = text.replace(OS_STYLE, "ROOT")

    if text == original:
        return None

    # Build the import list actually used.
    needed = ["ROOT"]
    for name in ("BACKEND", "FRONTEND", "SCRIPTS", "DOCS", "CONTRACTS", "ARTIFACTS"):
        if re.search(r"\b" + name + r"\b", text):
            if name not in needed:
                needed.append(name)
    # ROOT is always imported: Path(ROOT) and BACKEND both need it defined.
    import_line = "from _repo import " + ", ".join(needed) + "  # noqa: E402"

    lines = text.split("\n")
    insert_at = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")) and not line.startswith((" ", "\t")):
            insert_at = index + 1
    lines.insert(insert_at, bootstrap(path) + import_line)
    lines.insert(insert_at + 1, "")
    return "\n".join(lines)


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
            if IMPORT_PROBE in text:
                continue
            if OS_STYLE not in text and "Path(__file__)" not in text:
                continue
            if "_find_root" in text:
                continue
            result = rewrite(text, full)
            if result is None:
                continue
            hits.append(os.path.relpath(full, os.path.dirname(TOOLS)))
            if apply:
                io.open(full, "w", encoding="utf-8", newline="\n").write(result)

    print(("APPLIED" if apply else "DRY RUN") + ": " + str(len(hits)) + " files")
    for item in hits:
        print("  " + item)


if __name__ == "__main__":
    main()
