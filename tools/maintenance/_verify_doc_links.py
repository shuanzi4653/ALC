"""Verify every repo-relative path referenced by the changelog docs exists.

Read-only repository maintenance check. Writes nothing.
Reports both dead links and the files that hold the references.

    _verify_doc_links.py              check the real docs
    _verify_doc_links.py --self-test  negative control: prove it can fail

Exit codes follow the house rule (M60): 0 clean, 1 findings, 2 the checker
could not see its input. Historically this script only printed and always
exited 0 -- which meant that *anything* reading its exit status, rather than
its stdout, was blind to every dead link it reported. It was also not part of
`_gate_toolchain.py` at all until 2026-10-15, when a round of documentation
edits left **8 dead links** in place with the routine gate green; the two facts
are the same defect seen from two sides, and M85 ("a criterion's reach is what
it recognises, and a shortfall in reach never reports itself") is the general
form.
"""

import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT, artifact  # noqa: E402
import io
import re


DOCS = [
    "README.md",
    "changelog/README.md",
    "changelog/CHANGELOG.md",
    "changelog/ISSUES.md",
    "changelog/DECISIONS.md",
    "changelog/evidence/INDEX.md",
    # 0.11.1（Beta）新增的两份。它们**必须**进这张表：这两份文档的每一处相对链接
    # 都指向别的文档或工具，而本闸门此前只扫 `changelog/` 与根 `README.md` ——
    # 也就是说 `docs/` 下全部 40 余份文档的链接**从来没有被读过**。
    # 全量并入 `docs/*.md` 会立刻翻出一批历史死链（改名留下的），那是另一件事；
    # 这里先把本轮新增的两份纳入射程，并把"docs/ 未全量纳管"如实记为遗留。
    "docs/0.11.1-更新方案.md",
    "docs/DATA_CARD-v2-metar.md",
]

# Inline-code tokens that are prose or expired artifacts, not live repo paths.
# Keep this list short and justified; it exists so the check stays a real guard
# rather than being ignored wholesale once it has one unavoidable false positive.
IGNORE = {
    "360/n",  # angle arithmetic in prose, e.g. "smooth circle is about 360/n"
    "backend-java/target/tianchuang-server-0.11.0.jar",  # 0.11 artifact, rebuilt since
    "docs/evaluation-v1.6/",  # planned directory, not created yet
    # Runtime scratch directory: gitignored, so it is *never* present in a clean
    # checkout and its absence says nothing about whether the doc is stale. Docs
    # legitimately name it (it is where the plan cache and self-check report live).
    # A directory that is absent-by-design must not be reported as a dead link.
    ".run/traffic/",
    # Same class again, and it needs its own entry rather than being covered by
    # `.run/traffic/`: `tools/harness/_start_services.py` writes this file on
    # launch, so it is absent whenever the services are not running -- which is
    # the normal state of the working tree, not evidence that the doc is stale.
    # The sentence naming it describes where `launchedAt` is recorded.
    ".run/processes.json",
    # Same class as `.run/traffic/`, and it needs its own entry for a specific
    # reason: the screenshot driver *used to* live in `.run/` and the docs name that
    # old path on purpose -- ISS-0.9.25-06 is the record of moving it out. Excusing
    # the historical name does not excuse a stale link: the live target
    # `tools/probes/_shot_screens.py` is still referenced and is still checked.
    ".run/shot_home.py",
    # An inline-code *fragment*, not a repo-relative path: the docs describe the
    # Windows venv's internal layout ("venv 的 `Scripts/python.exe` 是个 launcher").
    # The repo-relative form the check actually resolves,
    # `backend-python/.venv/Scripts/python.exe`, is alive.
    "Scripts/python.exe",
    # A basetemp left behind by one full-suite run and deleted on purpose; its only
    # mention is the cleanup table row that records the removal. Absent by design,
    # like `.run/traffic/`.
    "backend-python/.pytest_tmp_full/",
    # An IANA **time zone identifier**, not a path -- and the *only* spelling of it.
    # Same shape as the `360/n` entry above (`Region/City` contains the one character
    # the checker treats as a directory separator), but the fix cannot be "rewrite
    # the doc": `Asia/Shanghai` is a factual name, so any rewrite would either cite a
    # zone that does not exist or turn a checkable fact into prose. It appears in the
    # 0.9.32 records, where the timezone is the reason the upstream value (wind 360)
    # was accepted as measured rather than inferred -- i.e. it is part of the evidence.
    "Asia/Shanghai",
}

# Prefix exemptions. Same justification shape as the entries above, but stated once
# for a whole class rather than one entry per file, because the class itself is the
# reason. Keep the reason attached or this becomes an unexplained gate-ectomy.
IGNORE_PREFIXES = {
    # `.run/` is gitignored runtime scratch: it is **absent by design in a clean
    # checkout**, so citing it says nothing about staleness. Twelve rounds of docs
    # cite it for one of exactly two purposes:
    #   1. historical narrative naming an artifact's then-location
    #      (e.g. `.run/shot_home.py`, now `tools/probes/_shot_screens.py` -- the very
    #      record ISS-0.9.25-06 exists to keep);
    #   2. the "output" column of an evidence table (`pytest-0926.out`, `gate-*.out`,
    #      `command_order_negative.py` ...), which documents *where a past run's raw
    #      output went*, not a path a reader is expected to open now.
    # The live tools formerly in `.run/` that this project depends on every release
    # were **moved out** rather than excused: `_shot_screens.py` -> `tools/probes/`,
    # and `_make_zip.py` / `_diff_pack.py` / `_zip_smoke.py` / `_verify_zip.py` ->
    # `tools/maintenance/`. So excusing the prefix does not excuse a stale *live* link;
    # there is no longer any live tool whose correct home is `.run/`.
    #
    # Scope note: this is a prefix on a directory that is gitignored *and* routinely
    # emptied, so its absence cannot distinguish a fresh citation from a stale one --
    # which is exactly the condition under which a link check has nothing to say.
    ".run/",
}

# Only treat these as repo paths; skip URLs, anchors, and inline code that is not a path.
LINK_RE = re.compile(r"\]\(([^)]+)\)")
CODE_RE = re.compile(r"`([A-Za-z0-9_./-]+/[A-Za-z0-9_./-]+)`")

# Inline code that contains a slash but is an expression, not a path. `//` and a
# bare `a/b` arithmetic form are the two shapes that recur in these documents;
# without this the check reports them as dead links and stops being trustworthy.
# Deliberately narrow: it must not excuse a real path that has gone stale.
EXPRESSION_RE = re.compile(r"(^//|[^/\w]//|\b[a-z_]+//\d|^[a-z_]+(/[a-z_]+)+$)")


def classify(rel, text):
    """Return ``(alive, dead)`` for one document's text.

    Extracted from the module body so the self-test can feed it a **mutated
    copy** and read the difference, instead of exercising a second, drifting
    implementation of the same rules (M29/M58: a check whose failure branch is
    never run is indistinguishable from one that always passes).
    """
    alive = 0
    dead = []
    candidates = set()
    for match in LINK_RE.finditer(text):
        candidates.add(match.group(1))
    for match in CODE_RE.finditer(text):
        token = match.group(1)
        if token.startswith("{"):
            continue
        if EXPRESSION_RE.search(token):
            continue
        candidates.add(token)
    for token in sorted(candidates):
        if token.startswith(("http://", "https://", "#", "mailto:")):
            continue
        clean = token.split("#")[0].strip()
        if not clean or "<" in clean or clean in IGNORE:
            continue
        if any(clean.startswith(p) for p in IGNORE_PREFIXES):
            continue
        # A real repo path has a path-ish segment; guards against inline code that
        # merely contains slashes, such as a list of minute marks "0/60/120".
        head = clean.split("/")[0]
        if not head or head[0].isdigit():
            continue
        if "." not in os.path.basename(clean.rstrip("/")) and "/" not in clean.rstrip("/"):
            continue
        # **两种口径都要试**（0.9.26（Beta） 第十轮修）。
        #
        # 本检查器的口径原本是"仓库根相对"，而 Markdown 的 `](...)` 是**文件相对**的。
        # 两者在根级文档里恰好重合（`README.md` 写 `docs/x.md` 两边都对），
        # 于是一直没人发现 —— 直到第十轮在 `changelog/README.md` 里写下第一条跨目录
        # 链接：渲染器正确的 `../docs/evaluation-algorithm/algorithm-contrast.md`
        # 被判 dead，而渲染器错误的 `docs/evaluation-algorithm/...` 反而通过。
        # 也就是说，**这个检查器当时唯一能接受的写法，是浏览器里点不开的那种**。
        #
        # 修法是两种都试、任一存在即算活。这个方向是安全的：它只会**增加**判活，
        # 不可能把一条真的失效的链接放过 —— 真失效的定义就是"两种口径都找不到"。
        # 反过来（只保留一种）就会继续要求作者写渲染不出来的链接。
        repo_rooted = os.path.join(ROOT, clean.replace("/", os.sep))
        file_rooted = os.path.normpath(
            os.path.join(ROOT, os.path.dirname(rel.replace("/", os.sep)),
                         clean.replace("/", os.sep)))
        if os.path.exists(repo_rooted) or os.path.exists(file_rooted):
            alive += 1
        else:
            dead.append((rel, clean))
    return alive, dead


def read_docs():
    """``{rel: text}`` plus the list of documents that could not be read."""
    texts, missing = {}, []
    for rel in DOCS:
        full = os.path.join(ROOT, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            missing.append(rel)
            continue
        texts[rel] = io.open(full, encoding="utf-8").read()
    return texts, missing


def check(texts):
    alive = 0
    dead = []
    for rel in DOCS:
        if rel not in texts:
            continue
        a, d = classify(rel, texts[rel])
        alive += a
        dead.extend(d)
    return alive, dead


def self_test():
    """Prove the check can fail -- and that its exemptions are not the reason. (M29/M58)

    Each mutation is built from the **live** documents rather than quoted from a
    previous run, so changing the docs cannot break the control instead of the
    check (the trap `_verify_issue_counts.py --self-test` paid once already).
    """
    texts, missing = read_docs()
    if missing:
        print('self-test needs every declared doc, missing: %s' % ', '.join(missing))
        return 2

    alive, dead = check(texts)
    if dead:
        print('self-test needs a clean baseline, but the real docs report:')
        for rel, token in dead:
            print('  DEAD %s -> %s' % (rel, token))
        return 1
    print('self-test baseline clean: %d resolved / 0 dead over %d documents'
          % (alive, len(DOCS)))

    host = DOCS[0]

    def with_token(token):
        """Insert an inline-code token into the host doc, if that is a change."""
        if token in texts[host]:
            return None
        return dict(texts, **{host: texts[host] + '\n\n检查用：`%s`\n' % token})

    def ignore_entry_that_would_otherwise_be_reported():
        """An ``IGNORE`` entry that is both absent from the host doc **and** would be
        reported if the exemption list were empty.

        Derived rather than hand-picked: a hard-coded token stops being a control
        the moment the host document happens to start mentioning it (the mutation
        then changes nothing, and "BROKEN" reads exactly like a real red).
        """
        saved = set(IGNORE)
        try:
            for token in sorted(saved):
                if token in texts[host]:
                    continue
                IGNORE.clear()
                try:
                    _, probe = classify(host, texts[host] + '\n\n检查用：`%s`\n' % token)
                finally:
                    IGNORE.update(saved)
                if any(clean == token for _, clean in probe):
                    return token
        finally:
            IGNORE.clear()
            IGNORE.update(saved)
        return None

    failures = 0

    def case(label, token, expect_dead, why):
        nonlocal failures
        mutated = with_token(token)
        if mutated is None:
            print('  BROKEN %s: %r is already in %s, the mutation changes nothing'
                  % (label, token, host))
            failures += 1
            return
        _, found = check(mutated)
        named = [t for _, t in found]
        if expect_dead:
            # The needle must be *absent* from the repo, or the mutation would be
            # testing the filesystem rather than the checker's recognition.
            if os.path.exists(os.path.join(ROOT, token.replace('/', os.sep))):
                print('  BROKEN %s: %r exists, so it cannot stand in for a dead link'
                      % (label, token))
                failures += 1
                return
            if token in named and len(found) == len(dead) + 1:
                print('  ok  %s -> reported (%s)' % (label, token))
            else:
                print('  MISS %s: expected exactly one new dead link naming %r, '
                      'got %r' % (label, token, found))
                failures += 1
        else:
            if named == [t for _, t in dead]:
                print('  ok  %s -> not reported (%s) -- %s' % (label, token, why))
            else:
                print('  MISS %s: %r was reported as dead (%r) -- %s'
                      % (label, token, found, why))
                failures += 1

    # ① 真的死链必须报出来。
    case('a genuinely dead link', 'docs/__self_test__/missing.md', True,
         'the baseline case the check exists for')
    # ② 豁免前缀只吃它自己那一层：`.run/` 下不存在的路径**不该**报。
    case('a token under an exempted prefix', '.run/__self_test__/missing.md', False,
         'absent-by-design directories must not be reported (M74)')
    # ③ 表达式形状的 inline code 不是路径。
    case('an expression-shaped token', 'alpha/beta', False,
         'non-path inline code must not be reported')
    # ④ IGNORE 名单**在起作用**：取一条既不在本文档里、又**在没有豁免时会报出来**
    #    的声明条目，断言它没有被报。后半个条件才是这条对照的牙齿 ——
    #    它同时证明了"豁免名单是承重的"，而不只是"它没惹麻烦"。
    token = ignore_entry_that_would_otherwise_be_reported()
    if token is None:
        print('  BROKEN a declared IGNORE entry: no entry is both absent from %s and '
              'reportable without the exemption' % host)
        failures += 1
    else:
        case('a declared IGNORE entry', token, False,
             'a declared exemption is honoured (and it is load-bearing)')

    if failures:
        print('self-test FAILED: %d case(s) did not fire' % failures)
        return 1
    print('self-test PASSED: 1 must-report + 3 must-not-report mutations, all caught')
    return 0


def main():
    if '--self-test' in sys.argv:
        return self_test()
    texts, missing = read_docs()
    if missing:
        # A document that cannot be read is "could not measure", not "clean" (M60).
        for rel in missing:
            print('UNMEASURABLE missing doc: %s' % rel)
        return 2
    alive, dead = check(texts)
    print('resolved ok:', alive)
    print('dead links:', len(dead))
    for rel, token in dead:
        print('  DEAD', rel, '->', token)
    return 1 if dead else 0


if __name__ == '__main__':
    sys.exit(main())
