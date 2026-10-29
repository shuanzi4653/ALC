"""Restore stdlib imports the bootstrap rewrite dropped.

``_normalise_all_bootstraps`` removes a bare ``import os`` / ``import sys`` from
the body because the block re-adds them. An earlier version of that regex also
listed ``io``, which no block line re-adds, so files that did ``import io`` on
its own line lost it. This finds any stdlib name a file uses but no longer
imports and puts the import back, one line per module, next to the block.

Idempotent: a file that has all its imports is left byte-identical.

    _restore_imports.py            # dry run
    _restore_imports.py --apply    # write
"""

import ast
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from _repo import ROOT  # noqa: E402

MODULES = (
    "io", "json", "re", "math", "statistics", "shutil", "tempfile",
    "subprocess", "csv", "datetime", "collections", "time", "socket",
    "random", "itertools", "functools", "hashlib", "textwrap", "traceback",
    "urllib", "glob", "argparse", "decimal", "copy", "operator", "string",
)


def strip_literals(text):
    """Remove docstrings and string literals so `re.` inside prose is not a hit.

    Kept only as a fallback for files that do not parse (see used_modules). It is
    NOT the primary detector any more -- see used_modules for why it was wrong.
    """
    text = re.sub(r'"""[\s\S]*?"""', '""', text)
    text = re.sub(r"'''[\s\S]*?'''", "''", text)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    text = re.sub(r"'(?:[^'\\]|\\.)*'", "''", text)
    return text


def used_modules(text):
    """Stdlib module names this file actually references as `mod.attr`.

    Why the regex scan this replaces was wrong, and wrong in the dangerous
    direction:
        It searched the literal-stripped body for `\\b<module>\\.`. English prose
        in a *comment* survives literal-stripping -- only quotes are removed --
        so the word "runtime" in `which is a NameError at run time.` contains the
        substring `time.` and the scanner reported `time` as a missing import.
        That is a false positive, and a false positive here means `--apply`
        writes a junk `import time` into a file that never needed it.

        The AST cannot be fooled this way: a comment is not an Attribute node,
        and `mod.attr` is only a use when `mod` is a plain Name load. This is the
        same detector `_audit_unbound_names.py` was rewritten to use after its own
        text scanner produced false negatives.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        body = strip_literals(text)
        return {m for m in MODULES if re.search(r"\b" + m + r"\.", body)}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in MODULES:
                found.add(node.value.id)
    return found


def bound_modules(text):
    """Stdlib module names the file binds via any Import / ImportFrom.

    Any binding counts, including a function-local one: the point of this pass is
    to re-add an import the bootstrap rewrite *deleted*, so an over-broad notion
    of "already imported" only makes it quieter, never wrong.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        body = strip_literals(text)
        bound = set()
        for module in MODULES:
            if re.search(r"^[ \t]*import " + module + r"\b", body, re.M):
                bound.add(module)
            if re.search(r"^[ \t]*import [\w, ]*\b" + module + r"\b", body, re.M):
                bound.add(module)
            if re.search(r"^[ \t]*from " + module + r"\b", body, re.M):
                bound.add(module)
        return bound
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = (alias.asname or alias.name).split(".")[0]
                if root in MODULES:
                    bound.add(root)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.asname or alias.name
                if name in MODULES:
                    bound.add(name)
    return bound


def missing(text):
    return sorted(used_modules(text) - bound_modules(text))


def insert(text, modules):
    lines = text.split("\n")
    # Insert after the last line of the bootstrap block (the `from _repo import`).
    anchor = None
    for index, line in enumerate(lines):
        if re.match(r"^[ \t]*from _repo import", line):
            anchor = index
    if anchor is None:
        for index, line in enumerate(lines):
            if re.match(r"^[ \t]*sys\.path\.insert", line):
                anchor = index
    if anchor is None:
        return None
    added = ["import " + module for module in modules]
    return "\n".join(lines[:anchor + 1] + added + lines[anchor + 1:])


def main():
    apply = "--apply" in sys.argv
    hits = []
    for folder, _dirs, files in os.walk(TOOLS):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            full = os.path.join(folder, name)
            text = io.open(full, encoding="utf-8").read()
            need = missing(text)
            if not need:
                continue
            result = insert(text, need)
            if result is None:
                hits.append((os.path.relpath(full, TOOLS), need, "NO ANCHOR"))
                continue
            compile(result, full, "exec")
            hits.append((os.path.relpath(full, TOOLS), need, "ok"))
            if apply:
                io.open(full, "w", encoding="utf-8", newline="\n").write(result)

    print("%s: %d files need imports restored" % ("APPLY" if apply else "DRY", len(hits)))
    for rel, need, status in hits:
        print("  %-52s %-18s %s" % (rel, ",".join(need), status))
    return 0


if __name__ == "__main__":
    sys.exit(main())
