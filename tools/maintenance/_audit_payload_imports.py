"""Find payload strings inside tools/*.py that use a stdlib module they never import.

Why this is a separate class of bug from the bootstrap damage:
    A tool like `_bench_ledger.py` spawns a child interpreter with
        GEN = "import json; sys.path.insert(0, ...); ..."
        subprocess.run([PY, '-c', GEN])
    The child is a *fresh interpreter*. It has no `sys` unless the payload
    imports it. The outer file imports sys perfectly well, so every static
    check I have (compile, bootstrap audit, missing-import scan over the real
    module) passes while the script still dies at runtime.

    The bootstrap repair could never have caught this: the offending text sits
    inside a string literal, which is exactly the place a normaliser must NOT
    rewrite.

Detection strategy:
    For each string literal with a *code* flavour (the concatenated parts of
    ImplicitConcatenation, or any payload passed to `-c`), tokenise it with the
    real tokenizer and record module references `mod.attr`. If a referenced
    module is one the payload never binds (no `import mod`, no `import mod as x`,
    no `from mod import`), report it.

    I use the tokenizer rather than a regex because a regex over a code string
    trips over the string's own nested string literals -- e.g. GEN contains
    r'{out}' and r'{root}' inside r'...' parts, and those false-positive as
    attribute access unless tokens are respected.
"""
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from _repo import ROOT  # noqa: E402
import string
import io
import re
import tokenize

STDLIB = {
    'os', 'sys', 'io', 'json', 're', 'math', 'time', 'random', 'subprocess',
    'pathlib', 'hashlib', 'shutil', 'tempfile', 'collections', 'itertools',
    'functools', 'datetime', 'csv', 'glob', 'textwrap', 'typing', 'unittest',
    'sqlite3', 'struct', 'base64', 'gzip', 'zipfile', 'argparse', 'logging',
}

SKIP_DIRS = {'__pycache__'}


def iter_files():
    for base, dirs, names in os.walk(TOOLS):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in sorted(names):
            if name.endswith('.py'):
                yield os.path.join(base, name)


def bound_in(payload):
    """Module names the payload itself binds, by any import form."""
    bound = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(payload).readline):
            pass
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    # Regex is safer than tokens for import forms here and has no nested-string
    # hazard because import statements cannot appear inside a payload string.
    for m in re.finditer(r'^\s*import\s+([A-Za-z_][\w]*(?:\s*,\s*[A-Za-z_][\w]*)*)', payload, re.M):
        for part in m.group(1).split(','):
            part = part.strip()
            if ' as ' in part:
                part = part.split(' as ')[0].strip()
            if part:
                bound.add(part.split('.')[0])
    for m in re.finditer(r'^\s*from\s+([A-Za-z_][\w]*)\s+import\b', payload, re.M):
        bound.add(m.group(1))
    return bound


def referenced_in(payload):
    """Module names used as `mod.attr` in the payload, token-accurately."""
    used = set()
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(payload).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return used
    for i, tok in enumerate(toks[:-1]):
        if tok.type == tokenize.NAME and toks[i + 1].string == '.':
            if tok.string in STDLIB:
                used.add(tok.string)
    return used


def payload_parts(text):
    """Return (label, payload) for every code-flavoured string in `text`.

    Two shapes matter in this repo:
      1. A multi-line triple-quoted assignment: `GEN = \"\"\"...\"\"\"`
      2. A value passed to `-c`: `subprocess.run([PY, '-c', EXPR])`
    For (1) I also splice in adjacent single-quoted parts separated by newlines,
    because the repo writes payloads as
        GEN = \"\"\"
        import json
        ...
        \"\"\".format(...)
    and as implicit concatenation across lines.
    """
    out = []
    for m in re.finditer(r'^([A-Za-z_][\w]*)\s*=\s*(?:r|f|rf|fr)?(?:"""|\'\'\')', text, re.M):
        var = m.group(1)
        rest = text[m.end():]
        for closer in ('"""', "'''"):
            end = rest.find(closer)
            if end != -1:
                body = rest[:end]
                # Only treat it as a payload if it looks like runnable code.
                if re.search(r'^\s*(import|from|def|for|while|if|print|try)\b', body, re.M):
                    out.append((var, body))
                rest = ''
                break
    return out


def main():
    findings = []
    scanned = 0
    payloads = 0
    for path in iter_files():
        try:
            text = io.open(path, encoding='utf-8').read()
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        for var, body in payload_parts(text):
            payloads += 1
            used = referenced_in(body) & STDLIB
            bound = bound_in(body)
            missing = sorted(used - bound)
            if missing:
                rel = os.path.relpath(path, TOOLS)
                findings.append((rel, var, missing))
    print('scanned files :', scanned)
    print('payloads found:', payloads)
    print('findings      :', len(findings))
    # A detector that finds nothing because it looked at nothing is a false
    # negative wearing a pass. The earlier version of this script printed a
    # hardcoded 'n/a' here and would have reported findings: 0 forever.
    if payloads == 0:
        print()
        print('WARNING: no payload strings matched -- the detector is inert,')
        print('         not clean. Fix payload_parts() before trusting a zero.')
        return findings
    print()
    for rel, var, missing in findings:
        print('%-46s %-12s missing: %s' % (rel, var, ', '.join(missing)))
    return findings


if __name__ == '__main__':
    main()
