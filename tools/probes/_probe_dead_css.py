"""Report which `style.css` class selectors no live code still binds as a class.

Why this exists
---------------
0.9.27 removed the legacy ECharts dashboard (15 unreachable files). Its styles did
**not** go with it: `frontend/src/style.css` is imported globally by `main.js`, so
`vite build` and every test stayed green while 58 class selectors described
components that no longer exist. A global stylesheet is *always* "in use" -- one
`import` line is enough -- so it can never become vestigial on its own. That is
M82: deleting a component is not deleting its styles.

The first version of this check (throwaway, in `.run/`) matched the class names as
**substrings of the whole source**, so `.panel` was "found in use" because of the
identifier `panelEl`, and `.stage` because of `HomeStage`. That error runs in the
dangerous direction: a false "still used" keeps dead CSS forever, and its output
("19 classes appear in live code") reads as *more* reassuring than the truth.
A false "unused", by contrast, deletes live styles and is immediately visible.

So references are looked for **only in class-binding contexts**:

  1. ``class="a b c"``                     static class attribute
  2. ``:class="..."``                      string literals *and* object keys
  3. ``classList.add|remove|toggle|contains('x')``
  4. ``frontend/index.html``               the HTML entry, which is *not* a
                                           component -- any scan of `src/**`
                                           alone is blind to it

(A class reached only through string concatenation cannot be seen statically. The
tool prints those prefixes separately rather than pretending it covered them.)

Verdict granularity is the **selector**, not the token: a selector matches only if
*every* class token in it is on an element, so if any one token is never bound as a
class, that selector can never match and its rule is dead.

    _probe_dead_css.py            report
    _probe_dead_css.py --check    exit 1 if the sheet still holds dead rules

Read-only. Exit 0 clean, 1 on findings, 2 when the sheet cannot be read (a check
that cannot see its input must not report success -- M60).
"""

import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402

SHEET = os.path.join(ROOT, 'frontend', 'src', 'style.css')
SRC = os.path.join(ROOT, 'frontend', 'src')
ENTRY = os.path.join(ROOT, 'frontend', 'index.html')

CLASS_ATTR = re.compile(r"""\bclass\s*=\s*(?:"([^"]*)"|'([^']*)')""")
BIND_ATTR = re.compile(r""":class\s*=\s*(?:"([^"]*)"|'([^']*)')""")
LITERAL = re.compile(r"""['"]([^'"]+)['"]""")
OBJ_KEY = re.compile(r"""(?:^|[{,\s])([A-Za-z_$][\w$-]*)\s*:""")
CLASS_LIST = re.compile(r"""classList\.\w+\(\s*['"]([^'"]+)['"]""")
DYN_CONCAT = re.compile(r"""['"`]([A-Za-z][\w-]*-)['"`]\s*\+""")
DYN_TEMPLATE = re.compile(r"""['"`]([A-Za-z][\w-]*-)\$\{""")

TOKEN = re.compile(r'[A-Za-z0-9_-]+')


def _live_files():
    files = [ENTRY]
    for base, _dirs, names in os.walk(SRC):
        for name in names:
            if name.endswith(('.vue', '.js', '.mjs')):
                files.append(os.path.join(base, name))
    return files


def bound_names():
    """Every token any live file binds as a class, plus the dynamic prefixes."""
    names, dynamic = set(), set()
    for path in _live_files():
        try:
            text = io.open(path, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        for match in CLASS_ATTR.finditer(text):
            raw = match.group(1) if match.group(1) is not None else match.group(2)
            names.update(t for t in raw.split() if TOKEN.fullmatch(t))
        for match in BIND_ATTR.finditer(text):
            raw = match.group(1) if match.group(1) is not None else match.group(2)
            names.update(LITERAL.findall(raw))
            names.update(OBJ_KEY.findall(raw))
        names.update(CLASS_LIST.findall(text))
        dynamic.update(m.group(1) + '*' for m in DYN_CONCAT.finditer(text))
        dynamic.update(m.group(1) + '*' for m in DYN_TEMPLATE.finditer(text))
    return names, dynamic


def selectors(sheet):
    """Every comma-separated selector in the sheet, comments stripped."""
    body = re.sub(r'/\*.*?\*/', '', sheet, flags=re.S)
    out = []
    for match in re.finditer(r'(?:^|})([^{}]+)\{', body, flags=re.M):
        for part in match.group(1).split(','):
            part = part.strip()
            if part:
                out.append(part)
    return out


def dead_selectors(sheet, names):
    """`[(selector, missing_tokens)]` -- a rule is dead if ANY token is unbound.

    Split out from `main` so the negative control below exercises *this* logic and
    not a copy of it (M66: a second copy is the defect class, not the fix).
    """
    dead = []
    for part in selectors(sheet):
        tokens = set(re.findall(r'\.([A-Za-z0-9_-]+)', part))
        if not tokens:
            continue  # pure element/pseudo selector: not a class rule
        missing = tokens - names
        if missing:
            dead.append((part, sorted(missing)))
    return dead


# A synthetic sheet for the negative control. It must contain one selector that is
# genuinely alive in this tree and one that cannot be, so the control proves both
# directions: no false positive on a live class, no false negative on a dead one.
# `hs-btn` is bound by `HomeStage.vue`; `ghost-class` is bound by nothing.
CONTROL = '.hs-btn{color:#fff}\n.ghost-class{padding:0}\n.ghost-class .inner{display:block}\n'


def self_test(names):
    dead = dead_selectors(CONTROL, names)
    hits = {part for part, _ in dead}
    ok = True
    if any(p == '.hs-btn' for p in hits):
        print('  FAIL the control flagged .hs-btn, which HomeStage.vue really binds')
        ok = False
    if '.ghost-class' not in hits or '.ghost-class .inner' not in hits:
        print('  FAIL the control missed a class nothing binds: %r' % sorted(hits))
        ok = False
    if ok:
        print('  ok  control sheet -> %d/%d selectors flagged, live class spared'
              % (len(hits), 3))
    return 0 if ok else 1


def main(argv):
    if not os.path.isfile(SHEET):
        print('CANNOT MEASURE: %s does not exist' % SHEET)
        return 2
    try:
        sheet = io.open(SHEET, encoding='utf-8').read()
    except OSError as exc:
        print('CANNOT MEASURE: cannot read %s (%s)' % (SHEET, exc))
        return 2

    names, dynamic = bound_names()

    if '--self-test' in argv:
        if not names:
            print('CANNOT MEASURE: no class bindings found at all -- the control '
                  'would pass for the wrong reason')
            return 2
        return self_test(names)

    sel = selectors(sheet)
    dead = dead_selectors(sheet, names)

    print('style.css 选择器 %d 条 | 类 token %d 个 | 其中被判死 %d 条'
          % (len(sel), len(names), len(dead)))
    for part, missing in dead:
        print('  DEAD  %s   （从未绑定的类：%s）'
              % (part, ', '.join('.' + m for m in missing)))
    if dynamic:
        print('\n以下前缀疑似动态拼接，静态查不到，需人工核对：')
        print('  ' + ' '.join(sorted(dynamic)))

    if dead:
        print('\nDEAD CSS %d 条' % len(dead))
        return 1 if '--check' in argv else 0
    print('\nDEAD CSS 0 条 —— 全局样式表里的每条类规则都还有活代码在绑定')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
