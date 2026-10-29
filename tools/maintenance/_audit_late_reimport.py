"""List tools/*.py where a LATER `from _repo import ...` re-binds a name that an
EARLIER site already Path-wrapped, undoing the wrap.

Why this exists:
    `_gen_contract.py` had two bootstrap sites. Site 1 wrapped ROOT in Path()
    correctly. Site 2 sat right after `import main` and re-imported ROOT from
    _repo, which is a *str*, so any later `ROOT / 'x'` raised
    `TypeError: unsupported operand type(s) for /: 'str'`.

    `_bootstrap_span` refuses to merge sites when a real statement sits between
    them (`import main` here), which is the right conservative call for the
    rewriter -- but it means the rewriter needs a second pass to notice that a
    later `from _repo import X` invalidates an earlier `X = Path(X)`.

Detection: for each file, find every `from _repo import` line and every
`NAME = Path(NAME)` line. Report when a `from _repo import NAME` appears after a
`NAME = Path(NAME)` for the same NAME.
"""
import os
import sys
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from _repo import ROOT  # noqa: E402
ROOT = Path(ROOT)
import io
import re

SKIP_DIRS = {'__pycache__'}
IMPORT_RE = re.compile(r'^\s*from\s+_repo\s+import\s+(.+?)\s*(?:#.*)?$', re.M)
WRAP_RE = re.compile(r'^([A-Za-z_][\w]*)\s*=\s*Path\(\1\)\s*$', re.M)


def iter_files():
    for base, dirs, names in os.walk(TOOLS):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in sorted(names):
            if name.endswith('.py'):
                yield os.path.join(base, name)


def line_of(text, pos):
    return text.count('\n', 0, pos) + 1


def main():
    rows = []
    for path in iter_files():
        try:
            text = io.open(path, encoding='utf-8').read()
        except (OSError, UnicodeDecodeError):
            continue
        wraps = {}          # name -> (line, pos)
        for m in WRAP_RE.finditer(text):
            wraps[m.group(1)] = (line_of(text, m.start()), m.start())
        if not wraps:
            continue
        for m in IMPORT_RE.finditer(text):
            pos = m.start()
            line = line_of(text, pos)
            names = [n.strip() for n in m.group(1).split(',')]
            for n in names:
                if n in wraps and wraps[n][1] < pos:
                    rows.append((os.path.relpath(path, TOOLS), n, wraps[n][0], line))
    print('files with a late re-import undoing a Path wrap:', len(rows))
    print()
    for rel, name, wrap_line, imp_line in rows:
        print('%-46s %-10s wrap@L%-4d reimport@L%d' % (rel, name, wrap_line, imp_line))


if __name__ == '__main__':
    main()
