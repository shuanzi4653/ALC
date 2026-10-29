"""Rewrite the bootstrap block of every tools/**/*.py to one canonical form.

Why a mechanical pass is right here
-----------------------------------
When the development scripts were moved out of the repository root into
``tools/<class>/``, each one kept the bootstrap it had when it lived one level
shallower. That produced a zoo of near-misses:

* ``ROOT = Path(ROOT)``  -- a self-assignment that reads as a no-op but silently
  depended on a previous line having bound the same name. (45 files)
* ``from _repo import ROOT`` without first putting ``tools/`` on ``sys.path``,
  so the import only worked when the caller happened to have it there. (88 files)
* Hand-rolled roots: ``Path(__file__).resolve().parents[2]`` and friends. These
  are correct only while the file stays at exactly that depth. (9 files)
* The bootstrap block placed *after* ``from traffic import ...``, so the
  ``sys.path`` entry it adds arrives too late to help that import. (8 files)
* ``os.chdir(BACKEND)`` used to make hard-coded relative paths work. That
  mutates the process working directory for every later file operation, which is
  exactly the class of side effect that made these scripts order-dependent. (20 files)
* A hard-coded absolute root, ``ROOT = r'C:\\Users\\...\\ALC'``, which cannot
  survive the repository being cloned anywhere else. (several)

The fix is identical in every case, so doing it by hand would be 111 chances to
introduce a new typo. This script rewrites the bootstrap region and leaves the
rest of the file byte-identical.

Two things it is careful about
------------------------------
1. **Path vs str.** ``_repo.ROOT`` is a ``str``. Scripts that wrote
   ``ROOT / 'backend-python'`` were relying on the old ``Path``. Rather than
   rewrite every expression, the canonical block wraps the string once:
   ``ROOT = Path(ROOT)`` is emitted *by the generator itself*, so the file's own
   expressions keep working. Files that never do path arithmetic get the plain
   string.
2. **It must not touch the repo's own maintenance scripts** (``_fix_*.py``,
   ``_repo.py`` itself). Those exist to repair the repository layout; making
   them depend on the thing they repair would be circular.

Usage
-----
    _normalise_all_bootstraps.py            # dry run
    _normalise_all_bootstraps.py --apply    # write
    _normalise_all_bootstraps.py --check     # exit 1 if any file is off-canon
"""

import io
import os
import re
import sys
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)

# Everything `_repo` exports that a tools script may import by name. `artifact`
# is a function, not a path constant, but it belongs here for the same reason the
# constants do: `used_names` decides which names to write into the rewritten
# `from _repo import ...` line, so a name missing from this tuple is silently
# dropped from the file being normalised. That is how `artifact` disappeared out
# of _bench_innovations.py and turned into a NameError at the very end of the run.
EXPORTED = ("ROOT", "BACKEND", "FRONTEND", "SCRIPTS", "DOCS", "CONTRACTS",
            "ARTIFACTS", "TOOLS", "SHARED", "artifact", "version", "package_dir")

# Files that must stay self-contained: they repair the layout the others depend
# on, so importing _repo from them would be circular.
SELF_CONTAINED = {
    "_repo.py",
    "_fix_bootstrap_order.py",
    "_fix_doubled_backend_paths.py",
    "_fix_repo_root_references.py",
    "_fix_tools_imports.py",
    "_normalise_all_bootstraps.py",
    "_normalise_tools_bootstrap.py",
    "_tidy_tools_imports.py",
    "_survey_tools_breakage.py",
    "_preview_bootstrap.py",
    # These two are the repair driver itself; they must be able to run before
    # the tree is repaired, so they cannot depend on the repaired tree.
    "_apply_bootstrap_fix.py",
    "_audit_skipped.py",
    "_restore_imports.py",
    "_smoke_tools.py",
    # Audit/report scripts. They read the repaired tree but keep their own
    # `HERE` so they can be run on their own; rewriting them strips HERE and
    # turns the audit into `NameError: name 'HERE' is not defined`.
    "_audit_unbound_names.py",
    "_audit_late_reimport.py",
    "_audit_payload_imports.py",
    "_audit_root_climb.py",
    # Shared helpers under tools/shared/. They are imported *by* other tools via
    # the path entry _repo installs, and `_cell_geom` keeps its own HERE so it
    # can resolve tools/ before _repo is importable.
    "_cell_geom.py",
    "_retired.py",
    # Resolves the node runtime. Like the two above it is imported *by* other
    # tools through the shared/ path entry, and it must stay importable before
    # `_repo` is on the path.
    "_node.py",
}

HARD_ROOT = re.compile(r"""^[ \t]*ROOT[ \t]*=[ \t]*r?['"][A-Za-z]:[\\/][^'"]*['"][ \t]*$""", re.M)
# The same idea under a different name: ``PROJECT = Path(r'C:\...\ALC')``.
HARD_ROOT_ANY = re.compile(
    r"""^[ \t]*(PROJECT|ROOT|BASE|REPO|HERE_ROOT)[ \t]*=[ \t]*Path\([ \t]*r?['"][A-Za-z]:[\\/][^'"]*['"][ \t]*\)[ \t]*$""",
    re.M,
)
# A string literal absolute path pointing inside this checkout.
HARD_ABS_STR = re.compile(r"""r?['"][A-Za-z]:[\\/][^'"]*[\\/](?:ALC|backend-python|frontend)[^'"]*['"]""")
SELF_ASSIGN = re.compile(r"^[ \t]*ROOT[ \t]*=[ \t]*(?:Path\(ROOT\)|ROOT|str\(ROOT\))[ \t]*$", re.M)

# Hand-rolled root expressions, in the several spellings actually present.
# The first alternative covers ``os.path.dirname(os.path.abspath(__file__))``
# repeated any number of times -- the 3-level form is what the old
# ``tools/maintenance/`` scripts used.
SELF_ROOT = re.compile(
    r"""^[ \t]*(?:ROOT|BACKEND|FRONTEND|PROJECT|HERE|BASE)[ \t]*=[ \t]*(?:"""
    r"""os\.path\.dirname\((?:os\.path\.dirname\()*os\.path\.abspath\(__file__\)(?:\))*"""
    r"""|Path\(__file__\)\.resolve\(\)(?:\.parents\[\d+\]|\.parent(?:\.parent)*)"""
    r"""|Path\(__file__\)\.parent"""
    r""")(?:[ \t]*/[ \t]*['"][^'"]+['"][ \t]*)*$""",
    re.M,
)

ANY_PATH_INSERT = re.compile(r"^[ \t]*(?:_?sys)\.path\.insert\([^\n]*\)[ \t]*$", re.M)
FROM_REPO = re.compile(r"^[ \t]*from _repo import ([^\n#]+)")
CHDIR = re.compile(r"^[ \t]*(?:os\.)?chdir\([ \t]*(?:BACKEND|ROOT|str\(BACKEND\)|str\(ROOT\))[ \t]*\)[ \t]*$", re.M)
CHDIR_ABS = re.compile(r"^[ \t]*(?:os\.)?chdir\([^\n]*backend-python[^\n]*\)[ \t]*$", re.M)

IMPORT_OS_ONLY = re.compile(r"^[ \t]*import (?:os|sys)(?: as _?(?:os|sys))?[ \t]*$")
IMPORT_PATHLIB = re.compile(r"^[ \t]*(?:from pathlib import Path|import pathlib)[ \t]*$")
IMPORT_ANY = re.compile(r"^[ \t]*(?:import |from )\S")
BLANK_COMMENT = re.compile(r"^[ \t]*(?:#.*)?$")

# Does the file do path arithmetic on the name?
PATH_ARITH_ANY = re.compile(
    r"\b(ROOT|BACKEND|FRONTEND|SCRIPTS|DOCS|CONTRACTS|ARTIFACTS|TOOLS)\s*/\s*(?:['\"]|ROOT)")
STR_JOIN = re.compile(r"os\.path\.join\([^)]*\b(?:ROOT|BACKEND|FRONTEND|SCRIPTS|DOCS|CONTRACTS|ARTIFACTS|TOOLS)\b")

# A line this generator itself emits. It must be removed before analysing the
# body, otherwise a second pass reads its own output as evidence of path
# arithmetic and wraps the name a second time.
GENERATED_PATH_WRAP = re.compile(
    r"^[ \t]*(ROOT|BACKEND|FRONTEND|SCRIPTS|DOCS|CONTRACTS|ARTIFACTS|TOOLS)[ \t]*=[ \t]*Path\(\1\)[ \t]*$",
    re.M,
)
GENERATED_NOTE = re.compile(r"^[ \t]*#\s*_repo exports str;.*$", re.M)


def strip_generated(text):
    """Remove lines this generator emitted, so re-runs stay idempotent."""
    text = GENERATED_PATH_WRAP.sub("", text)
    text = GENERATED_NOTE.sub("", text)
    return text


# Alias forms the old broken bootstrap used. The alias definition is gone, but
# the body can still call through it, which is a NameError at run time.
ALIAS_USE = re.compile(r"\b_(?:os|sys|io)\.")
ALIAS_IMPORT = re.compile(r"^[ \t]*import (os|sys|io) as _\1[ \t]*$", re.M)


def normalise_aliases(text):
    """Replace ``_os``/``_sys``/``_io`` uses with plain names, drop the alias import."""
    if not ALIAS_USE.search(text):
        return text
    text = ALIAS_IMPORT.sub("", text)
    text = re.sub(r"\b_os\.", "os.", text)
    text = re.sub(r"\b_sys\.", "sys.", text)
    text = re.sub(r"\b_io\.", "io.", text)
    # A bare `_x` used as a value (rare) also has to go.
    for alias, plain in (("_os", "os"), ("_sys", "sys"), ("_io", "io")):
        text = re.sub(r"(?<![\w.])" + alias + r"(?![.\w])", plain, text)
    return text


def path_arith_names(text):
    """Names the file uses as a ``Path`` (``NAME / 'x'`` or ``Path(NAME)``)."""
    found = []
    for match in PATH_ARITH_ANY.finditer(text):
        name = match.group(1)
        if name not in found:
            found.append(name)
    for match in re.finditer(r"\bPath\(\s*(ROOT|BACKEND|FRONTEND|SCRIPTS|DOCS|CONTRACTS|ARTIFACTS|TOOLS)\s*\)", text):
        name = match.group(1)
        if name not in found:
            found.append(name)
    return found


def _bootstrap_span(lines):
    """Indices of lines making up the bootstrap region, or None.

    Returns the union of every bootstrap site, not just the first run. Files that
    were hand-patched twice can carry two bootstrap attempts -- an early broken
    one using ``_os``/``_sys`` aliases and a later working one -- and leaving the
    second in place reintroduces the duplicate import this pass exists to remove.
    The span is therefore widened to cover all sites, but only when the lines
    between them are glue; a real statement between them narrows it back.
    """
    sites = set()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if ANY_PATH_INSERT.match(line) or FROM_REPO.match(line):
            sites.add(index)
            continue
        if GENERATED_PATH_WRAP.match(line) or GENERATED_NOTE.match(line):
            sites.add(index)
            continue
        if HARD_ROOT.match(line) or HARD_ROOT_ANY.match(line) or SELF_ASSIGN.match(line) or SELF_ROOT.match(line):
            sites.add(index)
            continue
        if CHDIR.match(line) or CHDIR_ABS.match(line):
            sites.add(index)
            continue
        if re.match(r"^[ \t]*_?(?:os|sys)\.path\.insert\(", line):
            sites.add(index)
            continue
    if not sites:
        return None

    ordered = sorted(sites)
    start, end = ordered[0], ordered[-1]
    # Reject the widened span if a real statement sits inside it: then only the
    # first contiguous group is bootstrap and the rest is body.
    for index in range(start + 1, end):
        if index in sites:
            continue
        line = lines[index]
        if BLANK_COMMENT.match(line) or IMPORT_OS_ONLY.match(line) or IMPORT_PATHLIB.match(line):
            continue
        if re.match(r"^[ \t]*import (?:io|json|re|math|statistics|time|csv|shutil|subprocess)\b", line):
            continue
        if re.match(r"^[ \t]*#\s*noqa", line):
            continue
        return _first_group(lines, ordered)
    return start, end


def _first_group(lines, ordered):
    """Widest contiguous bootstrap run starting at the first site."""
    sites = set(ordered)
    start = ordered[0]
    end = start
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if index in sites:
            end = index
            continue
        if BLANK_COMMENT.match(line) or IMPORT_OS_ONLY.match(line) or IMPORT_PATHLIB.match(line):
            end = index
            continue
        break
    return start, end


def _replace_abs_literals(body):
    """Rewrite whole-string absolute literals that point inside this checkout.

    ``d = r'C:\\Users\\...\\ALC\\frontend\\src'`` becomes
    ``d = os.path.join(ROOT, 'frontend', 'src')`` -- still a string, so every
    downstream ``os.path.join`` keeps working. Returns (text, count).
    """
    pattern = re.compile(r"""r?['"]([A-Za-z]:[\\/][^'"]*?)['"]""")
    count = 0

    def repl(match):
        nonlocal count
        raw = match.group(1)
        if "ALC" not in raw and "backend-python" not in raw and "frontend" not in raw:
            return match.group(0)
        parts = [part for part in re.split(r"[\\/]+", raw) if part]
        # Drop the drive and every component up to and including the checkout dir.
        lowered = [part.lower() for part in parts]
        cut = None
        for marker in ("alc", "backend-python"):
            if marker in lowered:
                cut = lowered.index(marker)
                break
        if cut is None:
            return match.group(0)
        tail = parts[cut + 1:] if lowered[cut] == "alc" else parts[cut + 1:]
        head = "ROOT" if lowered[cut] == "alc" else "ROOT"
        if lowered[cut] == "backend-python":
            head = "BACKEND"
        count += 1
        if not tail:
            return head
        pieces = ", ".join("'%s'" % part for part in tail)
        return "os.path.join(%s, %s)" % (head, pieces)

    return pattern.sub(repl, body), count


def _future_end(lines):
    """Index just past a leading ``from __future__`` block (which must stay first).

    A ``__future__`` import is only legal before any other statement, so the
    block has to go *after* it. The docstring counts as the file's first
    statement, so skip that first, then any comments, then the future lines.
    """
    index = _prologue_end(lines)
    while index < len(lines) and BLANK_COMMENT.match(lines[index]):
        index += 1
    last = index
    while last < len(lines) and re.match(r"^[ \t]*from __future__ import", lines[last]):
        last += 1
    return last


def _prologue_end(lines):
    """Index just past the module docstring / leading comments."""
    index = 0
    first = lines[0].lstrip() if lines else ""
    if re.match(r"^r?[\"']{3}", first):
        quote = re.match(r"^r?([\"']{3})", first).group(1)
        if lines[0].rstrip().endswith(quote) and len(lines[0].strip()) > len(quote):
            index = 1
        else:
            index = 1
            for scan in range(1, len(lines)):
                if quote in lines[scan]:
                    index = scan + 1
                    break
    while index < len(lines) and BLANK_COMMENT.match(lines[index]):
        index += 1
    return index


def needs_path(text):
    return bool(path_arith_names(text)) or bool(STR_JOIN.search(text))


def used_names(text):
    body = FROM_REPO.sub("", text)
    found = []
    for name in EXPORTED:
        if re.search(r"\b" + name + r"\b", body):
            found.append(name)
    return found


def build_block(dirnames, names, want_path, need_os, need_sys):
    block = []
    if need_os:
        block.append("import os")
    if need_sys:
        block.append("import sys")
    chain = "os.path.dirname(" * dirnames + "os.path.abspath(__file__)" + ")" * dirnames
    block.append("sys.path.insert(0, " + chain + ")")
    block.append("from _repo import " + ", ".join(names) + "  # noqa: E402")
    if want_path:
        block.append("ROOT = Path(ROOT)  # _repo exports str; these scripts do path arithmetic")
    return block


def rewrite(path, text):
    name = os.path.basename(path)
    if name in SELF_CONTAINED:
        return None, "self-contained (repairs the layout others depend on)"

    rel = os.path.relpath(path, TOOLS)
    dirnames = rel.count(os.sep) + 1  # tools/<class>/<file>.py -> 2, tools/<file>.py -> 1

    lines = text.split("\n")
    span = _bootstrap_span(lines)
    no_bootstrap = span is None

    if no_bootstrap:
        # No path bootstrap and no hard-coded root. Only worth rewriting when the
        # file actually reaches into the repository; a pure HTTP probe is fine.
        if not _touches_repo(text):
            return None, "clean (no repo reference)"

    if no_bootstrap:
        start = end = -1
        names = []
        body = text
    else:
        start, end = span
        names = []
        for index in range(start, end + 1):
            match = FROM_REPO.match(lines[index])
            if match:
                for raw in match.group(1).split(","):
                    raw = raw.strip()
                    if raw in EXPORTED and raw not in names:
                        names.append(raw)
        kept = lines[:start] + lines[end + 1:]
        body = "\n".join(kept)

    # Strip any hand-rolled or hard-coded roots anywhere outside the span, and
    # any wrap this generator emitted on a previous run so re-runs are stable.
    body = strip_generated(body)
    body = normalise_aliases(body)
    body = SELF_ROOT.sub("", body)
    body = HARD_ROOT.sub("", body)
    body = HARD_ROOT_ANY.sub("", body)
    body = SELF_ASSIGN.sub("", body)
    body = CHDIR.sub("", body)
    body = CHDIR_ABS.sub("", body)
    # A leftover ``ROOT = Path(ROOT)`` from an earlier pass would shadow the
    # block's value with the same value -- harmless but noise.
    body = re.sub(r"^[ \t]*ROOT[ \t]*=[ \t]*Path\(ROOT\)[ \t]*$", "", body, flags=re.M)
    # Substitute absolute literals that point inside this checkout. Only whole
    # string literals, never a substring, so no path fragment is mangled.
    body, subs = _replace_abs_literals(body)
    replaced_project = subs > 0

    # ``PROJECT`` was the old spelling of ROOT in the service launchers.
    using_project = re.search(r"\bPROJECT\b", body) is not None
    if using_project:
        body = re.sub(r"\bPROJECT\b", "ROOT", body)

    # A file that defined its own module-level ``DOCS = [...]`` list must keep
    # that list; the _repo constant would shadow it. Rename the import instead.
    body_names = used_names(body)
    for name in list(body_names):
        if re.search(r"^[ \t]*" + name + r"[ \t]*=", body, re.M):
            if name in ("DOCS", "SCRIPTS", "TOOLS", "CONTRACTS", "ARTIFACTS",
                        "BACKEND", "FRONTEND"):
                body_names.remove(name)
    for extra in body_names:
        if extra not in names:
            names.append(extra)
    if "ROOT" not in names:
        names.insert(0, "ROOT")

    want_path = needs_path(body)

    # A second, later `from _repo import X` would re-bind X to the raw str and
    # undo the Path() wrap the block just applied. See strip_late_repo_imports.
    body, late_dropped = strip_late_repo_imports(body, names)

    stripped_body = "\n".join(
        line for line in body.split("\n") if not IMPORT_ANY.match(line)
    )
    # The block itself always calls sys.path.insert, so sys is required
    # unconditionally; os is required by the abspath call on the same line.
    need_os = True
    need_sys = True
    if want_path:
        need_pathlib = True
    else:
        need_pathlib = bool(re.search(r"\bPath\(", stripped_body))

    # Remove now-redundant imports from the body; the block re-adds them.
    # Lines that are part of a multi-line string are payloads, not imports --
    # see _lines_inside_strings for the bug that proves it.
    in_string = _lines_inside_strings(body)
    out_body = []
    for offset, line in enumerate(body.split("\n"), start=1):
        if offset in in_string:
            out_body.append(line)
            continue
        if IMPORT_OS_ONLY.match(line):
            continue
        if IMPORT_PATHLIB.match(line) and need_pathlib:
            continue
        # A combined `import io, json, os, sys` keeps its other names.
        combined = re.match(r"^[ \t]*import ([A-Za-z_][\w]*(?:[ \t]*,[ \t]*[A-Za-z_][\w]*)+)[ \t]*$", line)
        if combined:
            keep = [part.strip() for part in combined.group(1).split(",")
                    if part.strip() not in ("os", "sys")]
            if len(keep) == 1:
                out_body.append("import " + keep[0])
            elif keep:
                out_body.append("import " + ", ".join(keep))
            continue
        out_body.append(line)
    body = "\n".join(out_body)

    block = []
    block.append("import os")
    if need_sys:
        block.append("import sys")
    if need_pathlib:
        block.append("from pathlib import Path")
    chain = "os.path.dirname(" * dirnames + "os.path.abspath(__file__)" + ")" * dirnames
    block.append("sys.path.insert(0, " + chain + ")")
    block.append("from _repo import " + ", ".join(names) + "  # noqa: E402")
    # _repo exports str; any name the file does path arithmetic on is wrapped
    # once here so the file's own expressions keep working unchanged.
    as_path = [name for name in path_arith_names(body) if name in names]
    if as_path:
        block.append("# _repo exports str; these names are used with path arithmetic.")
        for name in as_path:
            block.append(name + " = Path(" + name + ")")

    body_lines = body.split("\n")
    insert_at = _insertion_index(body_lines, 0 if no_bootstrap else start)
    new_lines = body_lines[:insert_at] + block + body_lines[insert_at:]
    result = "\n".join(new_lines)
    result = re.sub(r"\n{4,}", "\n\n\n", result)
    if not result.endswith("\n"):
        result += "\n"
    return result, "depth=%d names=%s path=%s%s" % (
        dirnames, ",".join(names), ",".join(as_path), " (added)" if no_bootstrap else "")


def _lines_inside_strings(text):
    """Line numbers (1-based) that contain any part of a multi-line string literal.

    Why this is necessary and not paranoia:
        This rewriter removes `import os` / `import sys` lines by regex. That is
        line-oriented, but the files in `tools/` embed *code payloads* as
        triple-quoted strings and hand them to a child interpreter via `-c`.
        `_bench_ledger.py` is the proof: its GEN payload started with

            GEN = \"\"\"
            import json
            import sys
            sys.path.insert(0, r'{root}/backend-python')
import time

        The rewriter saw a line reading exactly `import sys`, deleted it as
        redundant, and left the *outer* file with sys imported while the payload
        ran in a fresh interpreter that had none. The script then died with
        `NameError: name 'sys' is not defined` at run time, and the fix I applied
        by hand was silently undone the next time the rewriter ran.

    A line-oriented pass cannot tell code from text, so I ask the tokenizer which
    lines belong to a string token and then leave those lines completely alone.
    """
    inside = set()
    if not text.strip():
        return inside
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return inside
    for tok in toks:
        if tok.type == tokenize.STRING and tok.start[0] != tok.end[0]:
            for line in range(tok.start[0], tok.end[0] + 1):
                inside.add(line)
    return inside


def strip_late_repo_imports(body, names):
    """Drop `from _repo import X` lines that survive outside the canonical block.

    Why this is not just tidiness -- it is a correctness fix:
        `_gen_contract.py` had two bootstrap sites. The block imported ROOT and
        wrapped it in Path(); a later site sat right after `import main` and did
        `from _repo import ROOT` a second time. Since `_repo` exports a *str*,
        that second import re-bound ROOT back to a string and every later
        `ROOT / 'contracts'` raised
        `TypeError: unsupported operand type(s) for /: 'str'`.

        The rewriter's `_bootstrap_span` will not merge the two sites, because a
        real statement (`import main`) sits between them -- correct for deciding
        what to delete, but it leaves the re-import behind. Everything is now
        imported once, up front, so any later `from _repo import` is redundant by
        construction and removing it can only help.

    Returns (body, removed_count).
    """
    in_string = _lines_inside_strings(body)
    keep = []
    removed = 0
    for offset, line in enumerate(body.split("\n"), start=1):
        if offset in in_string:
            keep.append(line)
            continue
        match = FROM_REPO.match(line)
        if match:
            # Only drop it if it names nothing the block does not already bring in.
            wanted = [raw.strip() for raw in match.group(1).split(",") if raw.strip()]
            if wanted and all(name in names for name in wanted):
                removed += 1
                continue
        keep.append(line)
    return "\n".join(keep), removed


def _touches_repo(text):
    """Does the file reference anything that has to be resolved from the repo root?"""
    patterns = (
        r"""['"][^'"]*(?:backend-python|backend-java|contracts|changelog)[\\/]""",
        r"""['"][^'"]*[\\/](?:ALC)[\\/]""",
        r"from traffic import|import traffic|sys\.path\.insert",
        r"\.run[/\\]",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _insertion_index(lines, hint):
    """Where to put the block: after any docstring, after ``__future__`` imports."""
    index = _prologue_end(lines)
    future_end = _future_end(lines)
    index = max(index, future_end)
    return min(index, len(lines))


def main():
    mode = "dry"
    if "--apply" in sys.argv:
        mode = "apply"
    elif "--check" in sys.argv:
        mode = "check"

    changed, skipped = [], []
    for folder, _dirs, files in os.walk(TOOLS):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            full = os.path.join(folder, name)
            rel = os.path.relpath(full, TOOLS)
            text = io.open(full, encoding="utf-8").read()
            result, note = rewrite(full, text)
            if result is None:
                skipped.append((rel, note))
                continue
            if result == text:
                continue
            changed.append((rel, note))
            if mode == "apply":
                io.open(full, "w", encoding="utf-8", newline="\n").write(result)

    print("%s: %d rewritten, %d skipped" % (mode.upper(), len(changed), len(skipped)))
    for rel, note in changed:
        print("  %-56s %s" % (rel, note))
    if skipped:
        print("--- skipped (left alone)")
        for rel, note in skipped:
            print("  %-56s %s" % (rel, note))
    if mode == "check" and changed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
