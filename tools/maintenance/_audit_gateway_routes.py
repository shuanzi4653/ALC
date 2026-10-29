"""Assert every `/api/...` path a client can issue has a handler in the Java gateway.

Why this exists
---------------
The browser never talks to the Python service. It talks to the Java gateway on
8085, and the gateway forwards a *hand-curated* set of paths to Python on 8600.
That whitelist lives in `DecisionController.java` as path patterns such as
`/traffic/{resource:network|session|weather|operations}`.

The failure mode this audit targets is silent and one-directional: adding an
endpoint on the Python side and calling it from the frontend works perfectly in
isolation, and fails in the assembled system -- because nobody added the middle
leg. Spring then falls through to its default error response, which carries no
body the frontend's `requestJson` recognises, so the catch block reports a
generic network error (or, in a component that only renders on a thrown
exception, reports nothing at all).

That is exactly what happened with `POST /api/traffic/weather/mode`: the switch
button flashed its busy label and then went quiet, because the gateway matched
no handler for a two-segment resource. Reading the Python route table and seeing
the endpoint present is *not* evidence that the button works -- the middle leg
is what was missing. This audit closes that gap statically.

Widened 2026-10-15, for the third instance of the same class
------------------------------------------------------------
The two earlier escapes were *unrouted paths*. The third was a call site the
audit **could not see**, which is a different hole and needs a different fix.

`frontend/src/traffic/radarRelay.js` issues

    requestJson(relay.postTo || '/api/traffic/radar/tiles', { method: 'POST', ... })

so the path arrives from the **server payload** (`payload.radar.relay.postTo`,
built by `backend-python/traffic/cma_tiles.py::relay_instructions`). The old scan
required the *first argument* to be a string literal, so neither of its two
regexes matched. Measured consequence on the live deployment:

  * the audit printed `frontend /api calls: 15`, `unmatched calls: 0`, exit 0;
  * the relay's own status line read 「实测雷达瓦片已取到但后端未接受：请求失败
    （HTTP 404）」 -- the browser really had fetched the tiles (19:00 slot, both
    tiles 200, after correctly walking back past two 404 slots);
  * the POST came back as a Spring default error,
    `{"status":404,"error":"Not Found","path":"/api/traffic/radar/tiles"}`;
  * `backend-python/main.py` has `@app.post('/traffic/radar/tiles')` all along.

Net symptom: 实测雷达回波一直不可用 -- reported as 「一直提示雷达回波不可用」,
and attributed to the tile source for as long as the audit stayed green.

What it checks now
------------------
For every call to `requestJson(...)` / `postAction(...)`, collect **every
`/api/...` string literal in the call's argument list** (not just a literal first
argument), take the HTTP method from `method: '...'` in the same argument list
(`postAction` defaults to POST, `requestJson` to GET), and fail if no mapping of
**that method** matches.

Three ways a call can fail to be verified, all fatal, all printed:

  * `unmatched`    -- no mapping of that method matches the path
  * `undecidable`  -- a pattern style this audit does not understand
  * `unverified`   -- a request call whose arguments contain no `/api` literal at
                      all, i.e. a path that is statically invisible

`unverified` is what keeps the third escape closed. It stays 0 in this codebase
because of two rules worth stating, since breaking either re-opens the hole:

  1. **A server-supplied path must appear as a literal fallback at the call site**
     -- `relay.postTo || '/api/traffic/radar/tiles'`. Without the fallback the
     path exists only in the payload and no static scan can reach it.
  2. **The request layer itself may re-dispatch its own parameter**
     (`frontend/src/api.js`: `requestJson(path, ...)` inside `postAction`). That
     file is excluded from the `unverified` count -- its callers carry the
     literals and *are* scanned -- but its literals are still scanned.

It deliberately does *not* try to be a full Spring path matcher. It handles the
construct actually used in this codebase -- literal segments plus
`{name:alternative|alternative}` regex alternation -- and reports anything it
cannot decide as UNRESOLVED rather than guessing, so a new pattern style shows
up as a finding instead of a false pass.

Run:  python tools/maintenance/_audit_gateway_routes.py
      python tools/maintenance/_audit_gateway_routes.py --self-test
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from _repo import ROOT  # noqa: E402

FRONTEND = os.path.join(ROOT, 'frontend', 'src')
JAVA_CONTROLLERS = os.path.join(ROOT, 'backend-java', 'src', 'main', 'java')

# The request layer re-dispatches its own first parameter; see rule 2 in the
# module docstring. Recorded as a path relative to ROOT with forward slashes.
HELPER_MODULE = 'frontend/src/api.js'

# `requestJson(...)` / `postAction(...)`
_CALL_RE = re.compile(r'(?P<name>requestJson|postAction)\s*\(')
# `function requestJson(path, ...)` -- a definition, not a call. It must be
# excluded explicitly: its first argument is a formal parameter, so it would be
# counted as an unverified call site and a permanently-red audit is no audit.
_DEF_RE = re.compile(r'(?:async\s+)?function\s+(?P<name>requestJson|postAction)\s*\(')
# Every `/api/...` literal inside an argument list, one alternative per quote
# style. They cannot share one character class: a template literal legitimately
# contains `'` and `"` inside its `${...}` holes, and `TrafficWorkbench.vue`
# issues exactly that shape --
#   requestJson(`/api/traffic/weather?...&minute=${t}${city?'&cityId='+encodeURIComponent(city):''}`)
# A single `[^'"`]*` class stops at that inner `'`, fails its own backreference,
# and reports the call as having no literal at all -- a *false* blind spot, which
# is worse than no check because it accuses working code.
_PATH_LITERAL_RE = re.compile(
    r"""(?:`(/api/[^`]*)`|'(/api/[^']*)'|"(/api/[^"]*)")""")
_METHOD_RE = re.compile(r"""\bmethod\s*:\s*['"](\w+)['"]""")

# `@GetMapping("/x")`, `@PostMapping("/y")`, `@RequestMapping("/api")` above a
# class or method.
_MAPPING_RE = re.compile(
    r"""@(Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*(?:value\s*=\s*)?"([^"]*)\"""")

_CLASS_RE = re.compile(r"@RequestMapping\s*\(\s*\"([^\"]*)\"\s*\)\s*public\s+class")

ALL_METHODS = {'GET', 'POST', 'PUT', 'DELETE', 'PATCH'}


def _iter_files(root, suffix):
    for base, _dirs, names in os.walk(root):
        for name in names:
            if name.endswith(suffix):
                yield os.path.join(base, name)


def _argument_list(text, open_index):
    """The substring between `(` at open_index and its matching `)`.

    Strings, template literals, and comments are skipped so that a paren inside
    any of them cannot unbalance the count. Returns None when the call is not
    closed in what we were given -- the caller reports that rather than guessing.
    """
    depth = 0
    index = open_index
    quote = None
    while index < len(text):
        char = text[index]
        if quote:
            if char == '\\':
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in '\'"`':
            quote = char
            index += 1
            continue
        if char == '/' and index + 1 < len(text) and text[index + 1] == '/':
            newline = text.find('\n', index)
            if newline < 0:
                return None
            index = newline + 1
            continue
        if char == '/' and index + 1 < len(text) and text[index + 1] == '*':
            end = text.find('*/', index + 2)
            if end < 0:
                return None
            index = end + 2
            continue
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                return text[open_index + 1:index]
        index += 1
    return None


def calls_in(text):
    """[(path, method, line)], [unverified-reason] for one file's source text.

    Split out from the file walk so the self-test can drive it with literal
    source instead of having to write fixtures to disk.
    """
    found, unverified = [], []
    definitions = {match.start('name') for match in _DEF_RE.finditer(text)}
    for call in _CALL_RE.finditer(text):
        if call.start('name') in definitions:
            continue
        line = text[:call.start()].count('\n') + 1
        arguments = _argument_list(text, call.end() - 1)
        if arguments is None:
            unverified.append((line, 'argument list could not be parsed'))
            continue
        method = _METHOD_RE.search(arguments)
        if method:
            method = method.group(1).upper()
        else:
            method = 'POST' if call.group('name') == 'postAction' else 'GET'
        literals = list(_PATH_LITERAL_RE.finditer(arguments))
        if not literals:
            unverified.append((line, 'no /api literal in the arguments'))
            continue
        for literal in literals:
            # Exactly one of the three alternatives matched.
            raw = literal.group(1) or literal.group(2) or literal.group(3)
            # Fold here, not in the caller: every consumer wants a path it can
            # compare against a mapping, and two of them must not disagree.
            found.append((_normalise_frontend_path(raw), method, line))
    return found, unverified


def frontend_paths():
    """[(path, method, source-file, line)], [(source-file, line, reason)].

    The unverified list is filtered by HELPER_MODULE here rather than in
    `calls_in`, because the module-level exclusion is a statement about *usages*
    of the request layer, not about the text of one file.
    """
    found, unverified = [], []
    for path in _iter_files(FRONTEND, ('.vue', '.js', '.mjs')):
        with open(path, encoding='utf-8', errors='replace') as handle:
            text = handle.read()
        rel = os.path.relpath(path, ROOT).replace('\\', '/')
        calls, blind = calls_in(text)
        for raw, method, line in calls:
            found.append((raw, method, rel, line))
        if rel == HELPER_MODULE:
            continue
        for line, reason in blind:
            unverified.append((rel, line, reason))
    return found, unverified


def java_mappings():
    """[{method}, full_pattern, file] resolved against class-level prefixes."""
    mappings = []
    for path in _iter_files(JAVA_CONTROLLERS, '.java'):
        with open(path, encoding='utf-8', errors='replace') as handle:
            text = handle.read()
        class_match = _CLASS_RE.search(text)
        prefix = class_match.group(1) if class_match else ''
        rel = os.path.relpath(path, ROOT).replace('\\', '/')
        for kind, pattern in _MAPPING_RE.findall(text):
            if not pattern.startswith('/'):
                continue
            # A class-level @RequestMapping is the prefix, already captured.
            if class_match and pattern == prefix:
                continue
            full = (prefix + pattern).replace('//', '/')
            methods = ALL_METHODS if kind == 'Request' else {kind.upper()}
            mappings.append((methods, full, rel))
    return mappings


def _pattern_matches(pattern, path):
    """Decide whether one Spring pattern can match path.

    Returns True / False / None (None = we do not understand the construct).
    """
    if '{' not in pattern:
        return pattern.rstrip('/') == path.rstrip('/')
    segments = pattern.split('/')
    parts = path.split('/')
    if len(segments) != len(parts):
        return False
    for seg, part in zip(segments, parts):
        match = re.fullmatch(r'\{([^{}]*)\}', seg)
        if not match:
            if seg != part:
                return False
            continue
        inner = match.group(1)
        if ':' in inner:
            _name, _, alternatives = inner.partition(':')
            # Alternation is `a|b|c`; anything more exotic we refuse to judge.
            if not re.fullmatch(r'[A-Za-z0-9_|.\-]+', alternatives):
                return None
            if part not in alternatives.split('|'):
                return False
        # A bare `{name}` accepts any single segment.
    return True


def _normalise_frontend_path(raw):
    """Fold template-literal interpolations to a single path segment."""
    folded = re.sub(r'\$\{[^}]*\}', 'X', raw)
    return folded.split('?')[0]


def _judge(calls, mappings):
    """Split resolved calls into (unmatched, undecidable, ok)."""
    unmatched, undecidable, ok = [], [], []
    for raw, method, src, line in calls:
        path = _normalise_frontend_path(raw)
        same_method = [_pattern_matches(pattern, path)
                       for methods, pattern, _f in mappings if method in methods]
        if any(verdict is True for verdict in same_method):
            ok.append((path, method, src, line))
            continue
        if any(verdict is None for verdict in same_method):
            undecidable.append((path, method, src, line))
            continue
        # Distinguish "no such path" from "path exists but not for this verb":
        # the second one is a mapping to *widen*, the first is a mapping to *add*,
        # and the two send you to different files.
        other = [pattern for methods, pattern, _f in mappings
                 if method not in methods and _pattern_matches(pattern, path) is True]
        unmatched.append((path, method, src, line, other))
    return unmatched, undecidable, ok


def main():
    calls, unverified = frontend_paths()
    mappings = java_mappings()
    if not calls:
        print('no frontend /api calls found -- detector is inert')
        return 1
    if not mappings:
        print('no Java mappings found -- cannot verify the gateway')
        return 1

    unmatched, undecidable, _ok = _judge(calls, mappings)

    print('frontend /api calls: %d' % len(calls))
    print('java mappings: %d' % len(mappings))
    print('unmatched calls: %d' % len(unmatched))
    print('undecidable calls: %d' % len(undecidable))
    print('unverified call sites: %d' % len(unverified))
    for path, method, src, line, other in unmatched:
        hint = '  (the path is routed for %s)' % ', '.join(sorted(
            {m for pattern in other for m in ALL_METHODS})) if other else ''
        print('  DEAD  %-6s %s  (%s:%s)%s' % (method, path, src, line, hint))
    for path, method, src, line in undecidable:
        print('  ???   %-6s %s  (%s:%s)' % (method, path, src, line))
    for src, line, reason in unverified:
        print('  BLIND %s  (%s:%s)' % (reason, src, line))
    return 1 if (unmatched or undecidable or unverified) else 0


# ---------------------------------------------------------------------------
# Self-test. The widening above is only worth anything if it can *both* stay
# green on the real tree *and* catch the shape it was widened for, so both
# halves are pinned here -- a scanner that sees nothing is green everywhere.
# ---------------------------------------------------------------------------
def self_test():
    failures = []

    def check(label, got, want):
        if got != want:
            failures.append('%s: got %r, want %r' % (label, got, want))

    # --- 抓取：三种必须被看见的字面量位置 + 一种必须被排除的定义 -------------
    check('quoted first argument',
          calls_in("await requestJson('/api/a')")[0],
          [('/api/a', 'GET', 1)])
    check('template literal',
          calls_in("await requestJson(`/api/b?x=${y}`)")[0],
          [('/api/b', 'GET', 1)])
    # 本轮回归的那个形状：路径来自服务端载荷，字面量落在 `||` 右边。
    check('literal after server-supplied path',
          calls_in("await requestJson(relay.postTo || '/api/c', { method: 'POST' })")[0],
          [('/api/c', 'POST', 1)])
    check('postAction defaults to POST',
          calls_in("await postAction('/api/d', { a: 1 })")[0],
          [('/api/d', 'POST', 1)])
    # 定义不是调用点；把它算成"看不见的调用"会让闸门永远红。
    check('definition excluded',
          calls_in('export async function requestJson(path, options = {}) {')[0],
          [])

    # 模板串的 `${}` 洞里带引号（TrafficWorkbench.vue:319 的形状）。这条是写本
    # 审计时**真被绊到**的：用单字符类 `[^'"`]*` 收字符，会停在内层那个 `'`
    # 上、自己的反向引用失配，于是整条调用被误判成"参数里没有字面量" ——
    # 一个把好代码指认成坏代码的**假盲区**，比不检查更贵。
    check('template literal with quotes inside the holes',
          calls_in("await requestJson(`/api/g?m=${t}${c?'&k='+encodeURIComponent(c):''}`)")[0],
          [('/api/g', 'GET', 1)])

    # --- 盲区：没有字面量的调用必须被**报出来**，而不是静默跳过 ------------
    blind = calls_in("await requestJson(url, { method: 'POST' })")[1]
    check('unverified is reported', len(blind), 1)

    # --- 参数列表解析：字符串/注释里的括号不得破坏配对 ----------------------
    check('paren inside a string does not unbalance',
          calls_in("await requestJson('/api/e', { note: ')' })")[0],
          [('/api/e', 'GET', 1)])
    check('paren inside a comment does not unbalance',
          calls_in("await requestJson('/api/f', { // )\n  a: 1 })")[0],
          [('/api/f', 'GET', 1)])

    # --- 匹配：本轮缺的那一腿必须**判成 DEAD** ------------------------------
    check('radar/tiles does not match the command|explain whitelist',
          _pattern_matches('/api/traffic/{resource:command|explain}',
                           '/api/traffic/radar/tiles'),
          False)
    check('radar/tiles matches its own explicit mapping',
          _pattern_matches('/api/traffic/radar/tiles',
                           '/api/traffic/radar/tiles'),
          True)
    check('a non-whitelisted action is rejected',
          _pattern_matches('/api/traffic/{resource:command|explain}',
                           '/api/traffic/teleport'),
          False)
    check('a whitelisted action is accepted',
          _pattern_matches('/api/traffic/{resource:command|explain}',
                           '/api/traffic/command'),
          True)

    # --- 方法感知：同路径不同动词不得互相顶替 ------------------------------
    unmatched, _und, _ok = _judge(
        [('/api/traffic/weather/mode', 'POST', 'x.vue', 1)],
        [({'GET'}, '/api/traffic/weather/mode', 'C.java')])
    check('a GET-only mapping does not satisfy a POST call', len(unmatched), 1)

    if failures:
        print('self-test FAILED:')
        for line in failures:
            print('  - %s' % line)
        return 1
    print('self-test PASSED -- 14 controls (6 extraction, 1 blind-spot, '
          '2 argument parsing, 4 pattern, 1 method)')
    return 0


if __name__ == '__main__':
    sys.exit(self_test() if '--self-test' in sys.argv[1:] else main())
