"""Apply the canonical bootstrap to every tools script and verify each result compiles.

This is the driver that makes the repair reviewable: it rewrites in memory, runs
``compile()`` on the result, and only writes the file when the rewrite parses.
Any file whose result fails to compile is reported and left untouched, so a
bug in the rewriter can never leave the tree in a worse state than it found it.

It also chains the stdlib-import restore, because that step must see the *final*
text: a rewrite can drop ``import io`` in one place and add a use in another, and
restoring imports against the pre-rewrite text would miss it. Running the chain
in this order also makes the whole repair idempotent -- a second pass over an
already-repaired tree changes nothing.

    _apply_bootstrap_fix.py            # dry run + compile check
    _apply_bootstrap_fix.py --apply    # write
"""


import io
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, TOOLS  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _normalise_all_bootstraps as N  # noqa: E402
import _restore_imports as R  # noqa: E402


def main():
    apply = "--apply" in sys.argv
    written, unchanged, failed, skipped = [], [], [], []

    for folder, _dirs, files in os.walk(TOOLS):
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            full = os.path.join(folder, name)
            rel = os.path.relpath(full, TOOLS)
            text = io.open(full, encoding="utf-8").read()
            result, note = N.rewrite(full, text)
            if result is None:
                skipped.append((rel, note))
                continue
            # Restore stdlib imports against the rewritten text, so a module the
            # rewrite dropped is seen as missing.
            need = R.missing(result)
            if need:
                restored = R.insert(result, need)
                if restored is not None:
                    result = restored
                    note += " +import " + ",".join(need)
            if result == text:
                unchanged.append(rel)
                continue
            try:
                compile(result, full, "exec")
            except SyntaxError as exc:
                failed.append((rel, "line %s: %s" % (exc.lineno, exc.msg)))
                continue
            written.append((rel, note))
            if apply:
                io.open(full, "w", encoding="utf-8", newline="\n").write(result)

    print("APPLY" if apply else "DRY")
    print("  rewritten  : %d" % len(written))
    print("  unchanged  : %d" % len(unchanged))
    print("  skipped    : %d" % len(skipped))
    print("  COMPILE FAIL: %d" % len(failed))
    for rel, note in failed:
        print("    !! %-54s %s" % (rel, note))
    for rel, note in skipped:
        print("    -- %-54s %s" % (rel, note))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
