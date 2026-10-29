"""Find `NAME = os.path.dirname(...)` lines that walk *above* the repo root.

Why this is its own class of damage
-----------------------------------
When the dev scripts lived at the repository root, a file in
``tools/recon/foo.py`` needed to climb two levels to reach the root and wrote
``ROOT = os.path.dirname(os.path.dirname(ROOT))`` -- with the inner ROOT coming
from a *different* bootstrap. After the move, `_repo.ROOT` already IS the repo
root, so climbing again yields ``C:\\Users\\12921`` and every path built from it
is wrong. The failure is a FileNotFoundError pointing at a directory that looks
plausible, which is why it survived.

`_normalise_all_bootstraps.py` did not catch this: its SELF_ROOT pattern matches
`dirname(os.path.abspath(__file__))`, i.e. climbing from the *file*, not from the
imported ROOT.

Detection: any line of the form ``X = os.path.dirname(...ROOT...)`` or
``X = ROOT.parent`` / ``ROOT.parents[n]`` where X is an _repo name.
"""
import io
import os
import re
import sys
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from _repo import ROOT  # noqa: E402

NAMES = ('ROOT', 'BACKEND', 'FRONTEND', 'SCRIPTS', 'DOCS', 'CONTRACTS',
         'ARTIFACTS', 'TOOLS')

CLIMB_DIRNAME = re.compile(
    r'^[ \t]*([A-Za-z_][\w]*)[ \t]*=[ \t]*os\.path\.dirname\([^)\n]*\b(?:' +
    '|'.join(NAMES) + r')\b[^)\n]*\)[ \t]*$', re.M)

CLIMB_ATTR = re.compile(
    r'^[ \t]*([A-Za-z_][\w]*)[ \t]*=[ \t]*(?:' + '|'.join(NAMES) +
    r')\.parents?\[?\d*\]?[ \t]*$', re.M)


def iter_files():
    for base, dirs, names in os.walk(TOOLS):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for name in sorted(names):
            if name.endswith('.py'):
                yield os.path.join(base, name)


def in_string_lines(text):
    inside = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.STRING and tok.start[0] != tok.end[0]:
                inside.update(range(tok.start[0], tok.end[0] + 1))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return inside


def main():
    rows = []
    for path in iter_files():
        try:
            text = io.open(path, encoding='utf-8').read()
        except (OSError, UnicodeDecodeError):
            continue
        skip = in_string_lines(text)
        for pattern, label in ((CLIMB_DIRNAME, 'dirname'), (CLIMB_ATTR, 'parent')):
            for m in pattern.finditer(text):
                line = text.count('\n', 0, m.start()) + 1
                if line in skip:
                    continue
                rows.append((os.path.relpath(path, TOOLS), line, label, m.group(0).strip()))
    print('suspect climbs above the repo root:', len(rows))
    print()
    for rel, line, label, src in rows:
        print('%-46s L%-4d %-8s %s' % (rel, line, label, src))


if __name__ == '__main__':
    main()
