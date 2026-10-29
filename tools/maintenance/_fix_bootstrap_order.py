"""Fix the bootstrap ordering in scripts whose first import was a multi-line `from`.

Repository maintenance script.

The root-reference rewrite inserts its bootstrap lines after the last top-level
`import`/`from` line. When the file's first statement was a multi-line
parenthesised import, the bootstrap landed inside the parentheses:

    import sys
    from traffic.weather import (A, B,      <- opened
    import os as _os                        <- inserted inside
    from _repo import ROOT

The bootstrap must run before any `from traffic...` import anyway, because those
imports need `backend-python` on sys.path. So the correct shape is: standard
library imports, then bootstrap, then project imports.

This finds the malformed block, closes the interrupted import, and relocates the
bootstrap above it.

Run with --apply to write. Default is a dry run.

Note: tools/maintenance/_fix_doubled_backend_paths.py runs first and unwraps the
common case; this handles what it does not.
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)

BREAK = re.compile(
    r"^(from [A-Za-z_][A-Za-z0-9_.]* import \([^)\n]*,\s*# noqa: E402)\n"
    r"(import os as _os\nimport sys as _sys\n"
    r"_sys\.path\.insert\(0, os\.path\.dirname\(_os\.path\.abspath\(__file__\)\)\)\n"
    r"from _repo import [^\n]*\n)"
    r"\n"
    r"([^\n]*\))\n",
    re.MULTILINE,
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

            match = BREAK.search(text)
            if not match:
                continue

            first_line = match.group(1).rstrip()
            bootstrap = match.group(2).rstrip()
            tail = match.group(3).strip()

            # Rebuild: bootstrap first, then the import closed properly.
            replacement = bootstrap + "\n\n" + first_line + "\n" + tail
            new = text[: match.start()] + replacement + text[match.end():]

            # Put BACKEND on the path right after the bootstrap, since the
            # project imports below need it.
            if "sys.path.insert(0, BACKEND)" not in new:
                new = new.replace(
                    bootstrap,
                    bootstrap + "\n\nsys.path.insert(0, BACKEND)",
                    1,
                )
            new = re.sub(r"\n{3,}", "\n\n", new)

            hits.append(os.path.relpath(full, os.path.dirname(TOOLS)))
            if apply:
                io.open(full, "w", encoding="utf-8", newline="\n").write(new)

    print(("APPLIED" if apply else "DRY RUN") + ": " + str(len(hits)) + " files")
    for item in hits:
        print("  " + item)


if __name__ == "__main__":
    main()
