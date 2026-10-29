"""Check that the numbers in ``changelog/ISSUES.md`` still add up.

Why this exists
---------------
The appendix of ``ISSUES.md`` ("附：问题类型分布") makes three *mechanical*
claims about itself:

1. the number of archived entries (``### ISS-...`` headings),
2. the sum of the 「数量」 column of the distribution table,
3. the difference between those two -- and it even writes the **arithmetic**
   out in full, term by term, so a reader can check it by hand.

Nothing computed any of them. Prose numbers are the one thing every gate in
this repository is blind to: the link checker reads paths, the toolchain gate
reads imports, the test suites read code. So an entry could be added to the
table and the totals left behind -- or, worse, a term could be duplicated in
the written expression -- and **every check would still pass, because a
sentence is not an input to anything**.

That is not hypothetical. On 2026-10-03 the expression read
``16+10+...+1 +1`` while the table had 16 rows summing to 94: the written
arithmetic evaluated to **95** and its own stated total said **94**. The two
disagreeing numbers sat one line apart, in bold, and nothing noticed.

So this check recomputes all three, and it recomputes the *expression* too --
a written sum is a claim like any other, and the only reason to write the
terms out is so that someone (now: something) can add them up.

Two more of the same species are checked here, because they fail the same way:

* the **M-series** calls itself continuous, which is a claim about this file
  and therefore checkable in it; and
* the same two numbers are **restated in other documents** (the root
  ``README.md`` front page *and* tree, ``changelog/README.md``'s index *and*
  tree, the project memory). A restated number has no way of staying true
  except being recomputed -- run against the 2026-10-03 tree it found stale
  restatements sitting in three files, none of which any gate had ever read.
  A later run found two more *inside the declared patterns' own files*: the
  shape that is not written down is the one that drifts.
* the **tool-chain gate's own audit count**. The changelog restates it once
  ("工具链闸门 **N 项全 ok**"), and on 2026-10-15 that sentence said **16** while
  the gate ran **15** -- the round had written the number three times and read it
  none of them, so the wrong value survived to the end of the round. It is
  measured by *executing* the gate module, so adding an audit to the tuple cannot
  leave this reading stale.

    _verify_issue_counts.py              check the real file
    _verify_issue_counts.py --self-test  negative control: prove it can fail

Read-only. Exit 0 clean, 1 on any mismatch, 2 when the file cannot be parsed
(a check that cannot see its input must not report success -- M60).
"""

import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402

ISSUES = os.path.join(ROOT, 'changelog', 'ISSUES.md')

ENTRY_RE = re.compile(r'^### (ISS-[0-9]+(?:\.[0-9]+)*-[0-9]+(?:\.[0-9]+)*)', re.M)
TABLE_HEAD = '附：问题类型分布'
# A distribution row: | 类别 | 数量 | 典型编号 |  -- the count may be bolded.
ROW_RE = re.compile(r'^\|\s*(?P<name>[^|]+?)\s*\|\s*\*{0,2}(?P<count>\d+)\*{0,2}\s*\|')
ENTRY_CLAIM_RE = re.compile(r'档案条目数[^=]*=\s*\*{0,2}(\d+)\*{0,2}')
SUM_CLAIM_RE = re.compile(r'「数量」列合计\*{0,2}\s*=\s*\*{0,2}(\d+)\*{0,2}')
TERMS_RE = re.compile(r'「数量」列合计\*{0,2}\s*=\s*\*{0,2}\d+\*{0,2}\s*[（(]([^）)]*)[）)]')
# Pinned to the definition ("差额 = ..."), because the word also appears in prose.
DIFF_CLAIM_RE = re.compile(r'差额\s*\*{0,2}(\d+)\*{0,2}\s*=')
# Per-round notes: "条目数 83 → 84" / "列合计 89 → 91".
STEP_ENTRY_RE = re.compile(r'条目数\s*\*{0,2}(\d+)\s*→\s*(\d+)\*{0,2}')
STEP_SUM_RE = re.compile(r'列合计\s*\*{0,2}(\d+)\s*→\s*(\d+)\*{0,2}')

# A problem is one of two things, and they must not share an exit code:
#
#   BLIND     the check could not see the thing it is supposed to check
#             (the heading moved, a claim was reworded) -- M60: this is
#             "could not measure", and reporting it as "the numbers disagree"
#             would be a lie about what was found.
#   mismatch  both numbers were read, and they do not agree.
#
# Both sides of this distinction use the same constant, so a blind problem
# cannot be introduced without the classifier noticing it.
BLIND = 'CANNOT MEASURE: '

# Numbers that are counted in `ISSUES.md` and then *restated* in other documents.
# Each entry is (path, regex, measurements) -- the regex's capture groups map
# positionally onto the measurements they must equal.
#
# Declared, not discovered. A general rule ("any number within 20 chars of 条")
# would fire on the dated revision tables, where every historical reading is
# legitimately different from today's -- and per M63 the first unavoidable false
# positive is where a check stops being read at all. The whole point of listing
# them is that a restated number has no other way of staying true.
#
# Note that README.md and changelog/README.md each appear **twice**: a front-page
# sentence and a tree/index line state the same count, written at different times.
# On 2026-10-03 both were found stale by hand (84, two revisions behind) while the
# declared patterns passed -- the uncovered restatement is the one that drifts.
RESTATED = (
    ('README.md',
     r'问题档案（(\d+) 条，含 M1–M(\d+) 方法论）',
     ('entries', 'max_m')),
    ('README.md',
     r'问题档案（(\d+) 条）',
     ('entries',)),
    ('changelog/README.md',
     r'(\d+) 条缺陷的症状 / 根因 / 修法，含 M1–M(\d+) 排查方法论',
     ('entries', 'max_m')),
    ('changelog/README.md',
     r'含根因与修法，(\d+) 条）',
     ('entries',)),
    ('.workbuddy/memory/MEMORY.md',
     r'M1–M(\d+) 全表见',
     ('max_m',)),
    # The ADR count and the cross-decision methodology count are restated in the
    # same two front-page/index documents, in the same sentence shape as the
    # entry count. They drift the same way for the same reason (M63: a shape that
    # is not declared is the one that drifts), so they are declared here too.
    ('README.md',
     r'、技术决策记录（(\d+) 条 ADR \+ (\d+) 条跨决策方法论）',
     ('adrs', 'd_methods')),
    ('README.md',
     r'DECISIONS\.md\s+技术决策记录（(\d+) 条 ADR \+ (\d+) 条跨决策方法论）',
     ('adrs', 'd_methods')),
    ('changelog/README.md',
     r'技术决策记录 ADR（(\d+) 条 \+ (\d+) 条跨决策方法论）',
     ('adrs', 'd_methods')),
    ('changelog/README.md',
     r'\| (\d+) 条 ADR，每条都写了',
     ('adrs',)),
    # The tool-chain gate's audit count, written **once** in README's current-baseline
    # table. 2026-10-17 从 CHANGELOG 的 0.9.34 行移到这里，理由不是"换个地方更顺"：
    # 那一行是**历史记录**（"当时闸门 19 项"），让历史行跟着源码走，
    # 等于每加一条审计就去改一次历史 —— 那不是巡检，那是把历史改写成当前值，
    # 而改写之后"当时到底几项"就再也查不到了。
    # README 那张表是**当前基线**，跟随源码才是它的语义；改在这里，
    # 加审计时该改的地方与"该改"这件事本身就一致。
    ('README.md',
     r'`AUDITS`\s*\*\*(\d+)\s*项\*\*',
     ('gate_audits',)),
)

MEASURE_LABEL = {'entries': '条数', 'max_m': 'M 编号上界',
                 'adrs': 'ADR 条数', 'd_methods': '跨决策方法论条数',
                 'gate_audits': '工具链闸门审计项数'}

_CN_DIGITS = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
              '六': 6, '七': 7, '八': 8, '九': 9}


def _cn2int(text):
    """Parse a Chinese numeral up to 999 (the form the docs actually use).

    The cross-decision table's intro writes its count in Chinese ("三十三条").
    Reading it means the count is measured from the document like every other
    number here, instead of being a second hand-maintained copy (M66 / M67 ㉛).
    """
    total = 0
    section = 0
    for ch in text:
        if ch in _CN_DIGITS:
            section = _CN_DIGITS[ch]
        elif ch == '十':
            section = (section or 1) * 10
            total += section
            section = 0
        elif ch == '百':
            section = (section or 1) * 100
            total += section
            section = 0
        else:
            raise ValueError('unparseable Chinese numeral %r' % text)
    return total + section


def _read(rel, files):
    """Read a restated-claim document, honouring an override map (self-test)."""
    if files is not None and rel in files:
        return files[rel]
    return io.open(os.path.join(ROOT, rel.replace('/', os.sep)),
                   encoding='utf-8').read()


def appendix(text):
    """The appendix slice: the distribution table *and* its running commentary.

    Scope matters here. ``## 文档修订记录`` records the same two numbers for every
    earlier round, so a search over the whole file finds a *historical* trail
    ending at an old value (82 / 91) and reports it as a stale total -- a
    false positive that would have retired this check on day one. The trail
    that must end at the live totals is the one inside the appendix.
    """
    head = text.find(TABLE_HEAD)
    if head < 0:
        return None, None
    nxt = re.search(r'^## ', text[head:], re.M)
    return head, text[head:nxt.start() + head if nxt else len(text)]


def table_rows(section):
    """Every ``| 类别 | 数量 |`` row of the distribution table, in order."""
    rows = []
    for line in section.splitlines():
        if not line.startswith('|'):
            continue
        match = ROW_RE.match(line)
        if not match:
            continue
        name = match.group('name').strip()
        if name in ('类别', '---') or set(name) <= set('-: '):
            continue
        rows.append((name, int(match.group('count'))))
    return rows


def expression_total(text):
    """Add up the terms the document writes out, ignoring Markdown bold.

    Returns ``None`` when no expression is present, so the caller can tell
    "absent" from "sums to zero" -- the same distinction ``routeBasisNote``
    had to make when ``Number(null) === 0`` turned "no minute" into T+00:00.
    """
    match = TERMS_RE.search(text)
    if not match:
        return None
    body = match.group(1).replace('**', '')
    # The expression ends at an optional "= N" tail; keep only the terms.
    body = body.split('＝')[0].split('=')[0]
    terms = [int(t) for t in re.findall(r'\d+', body)]
    if not terms:
        return None
    return sum(terms)


def _gate_audit_count():
    """How many audits the tool-chain gate actually runs, or ``None``.

    Executed rather than text-scraped: the number of entries in the gate's
    ``AUDITS`` tuple is the fact, and reading it from the source by pattern would
    be a second copy of the same fact -- the defect class this script exists to
    find (M66 / M67 ㉛). `_gate_toolchain` only calls ``main()`` under
    ``__main__``, and this script is itself launched *as a child process by that
    gate*, so importing it cannot recurse into it.
    """
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '_gate_toolchain.py')
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location('_alc_gate_toolchain', path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    audits = getattr(module, 'AUDITS', None)
    return len(audits) if audits else None


def analyse(text, files=None):
    """Return ``(problems, facts)``. ``problems`` empty means the file agrees."""
    problems = []
    facts = {}

    entries = ENTRY_RE.findall(text)
    facts['entries'] = len(entries)
    if len(set(entries)) != len(entries):
        dupes = sorted({e for e in entries if entries.count(e) > 1})
        problems.append('duplicate entry headings: %s' % ', '.join(dupes))

    head, section = appendix(text)
    if head is None:
        return [BLIND + 'cannot find the distribution table heading %r' % TABLE_HEAD], facts

    rows = table_rows(section)
    if not rows:
        return [BLIND + 'distribution table has no data rows'], facts
    facts['rows'] = len(rows)
    counted = sum(count for _, count in rows)
    facts['table_sum'] = counted

    claim = ENTRY_CLAIM_RE.search(section)
    if not claim:
        problems.append(BLIND + 'no 档案条目数 claim found in the appendix')
    else:
        stated = int(claim.group(1))
        facts['stated_entries'] = stated
        if stated != facts['entries']:
            problems.append('档案条目数 says %d, but %d ### ISS- headings exist'
                            % (stated, facts['entries']))

    claim = SUM_CLAIM_RE.search(section)
    if not claim:
        problems.append(BLIND + 'no 「数量」列合计 claim found in the appendix')
    else:
        stated = int(claim.group(1))
        facts['stated_sum'] = stated
        if stated != counted:
            problems.append('「数量」列合计 says %d, the %d table rows sum to %d'
                            % (stated, len(rows), counted))

    total = expression_total(section)
    facts['expression_sum'] = total
    if total is None:
        problems.append(BLIND + 'the 合计 claim writes no arithmetic expression to check')
    elif total != counted:
        problems.append('the written expression sums to %d, the table sums to %d'
                        % (total, counted))

    claim = DIFF_CLAIM_RE.search(section)
    if not claim:
        problems.append(BLIND + 'no 差额 claim found in the appendix')
    else:
        stated = int(claim.group(1))
        facts['stated_diff'] = stated
        if stated != counted - facts['entries']:
            problems.append('差额 says %d, but 合计 - 条目 = %d - %d = %d'
                            % (stated, counted, facts['entries'],
                               counted - facts['entries']))

    # The per-round trail must *end* where the totals do, or the last round
    # silently desynchronises from the summary it was supposed to update.
    steps = STEP_ENTRY_RE.findall(section)
    if not steps:
        problems.append(BLIND + 'no per-round 条目数 trail found in the appendix')
    elif int(steps[-1][1]) != facts['entries']:
        problems.append('the last 条目数 step ends at %s, the file has %d headings'
                        % (steps[-1][1], facts['entries']))
    steps = STEP_SUM_RE.findall(section)
    if not steps:
        problems.append(BLIND + 'no per-round 「数量」列合计 trail found in the appendix')
    elif int(steps[-1][1]) != counted:
        problems.append('the last 列合计 step ends at %s, the table sums to %d'
                        % (steps[-1][1], counted))

    # The M-series calls itself "continuous" (M-numbering rule). That is a claim
    # about this file, so it is checkable here rather than by eye.
    ms = [int(m.group(1)) for m in re.finditer(r'^### M(\d+)', text, re.M)]
    if not ms:
        problems.append(BLIND + 'no M-series entries found')
    else:
        facts['max_m'] = max(ms)
        facts['m_count'] = len(ms)
        if min(ms) != 1:
            problems.append('the M-series starts at M%d, not M1' % min(ms))
        gaps = [n for n in range(1, max(ms) + 1) if n not in ms]
        if gaps:
            problems.append('the M-series has gaps: %s'
                            % ', '.join('M%d' % n for n in gaps))
        if len(ms) != max(ms):
            problems.append('the M-series has %d entries but reaches M%d '
                            '(a number is written twice)' % (len(ms), max(ms)))

    # The two counts restated from DECISIONS.md: measured by counting the real
    # headings there, never by trusting the restatement (M66: a written number is
    # a claim; only the object itself can answer it).
    decisions_text = _read('changelog/DECISIONS.md', files)
    facts['adrs'] = len(set(re.findall(r'^#{2,3} (ADR-\d+)', decisions_text, re.M)))
    cross = re.search(r'以下\*\*[一二三四五六七八九十百]+条\*\*', decisions_text)
    facts['d_methods'] = None
    if cross:
        words = cross.group(0)
        digits = re.search(r'\d+', words)
        if digits:
            facts['d_methods'] = int(digits.group(0))
        else:
            numeral = re.search(r'\*\*([一二三四五六七八九十百]+)条\*\*', words).group(1)
            facts['d_methods'] = _cn2int(numeral)

    # The gate's audit count, measured from the gate itself. `None` must be a
    # *blind* problem rather than silence: "I could not measure it" and "it
    # agrees" are different reports, and only one of them is about the document
    # (M60). Without this the restatement below would simply be skipped.
    facts['gate_audits'] = _gate_audit_count()
    if facts['gate_audits'] is None:
        problems.append(BLIND + 'cannot measure the tool-chain gate audit count '
                                '(tools/maintenance/_gate_toolchain.py unreadable '
                                'or has no AUDITS tuple)')

    # Numbers restated in other documents: same defect class, different file.
    for rel, pattern, expected in RESTATED:
        try:
            doc = _read(rel, files)
        except OSError as exc:
            problems.append(BLIND + 'cannot read %s (%s)' % (rel, exc))
            continue
        hits = re.findall(pattern, doc)
        if len(hits) != 1:
            problems.append(BLIND + '%s: expected exactly one restatement of %r, '
                            'found %d -- the sentence was reworded or duplicated'
                            % (rel, expected, len(hits)))
            continue
        captured = hits[0] if isinstance(hits[0], tuple) else (hits[0],)
        for want, got in zip(expected, captured):
            actual = facts.get(want)
            if actual is None:
                continue
            if int(got) != actual:
                problems.append('%s restates %s as %s, measured %d'
                                % (rel, MEASURE_LABEL.get(want, want), got, actual))
    return problems, facts


def self_test():
    """Negative control: every check must be able to fail on a mutated copy.

    M29/M58: a check whose failure branch is never exercised is indistinguishable
    from a check that always passes. Each mutation below is one the real file
    has actually contained or could contain.
    """
    text = io.open(ISSUES, encoding='utf-8').read()
    problems, facts = analyse(text)
    if problems:
        print('self-test needs a clean input, but the real file reports:')
        for problem in problems:
            print('  FAIL %s' % problem)
        return 1
    print('self-test baseline clean: entries=%d table_sum=%d rows=%d '
          'expression=%d diff=%d'
          % (facts['entries'], facts['table_sum'], facts['rows'],
             facts['expression_sum'], facts['stated_diff']))

    # Every mutation below is **found in the file**, never quoted from it.
    #
    # The first version quoted today's numbers ("= **97**", "M1–M67"), so every
    # round that changed a count broke the **control** instead of the check --
    # and a broken control prints "BROKEN … matched nothing", the same red the
    # reader is supposed to act on. That is M63 with the roles swapped: the text
    # describing *what to mutate* is itself part of what has to stay current.
    # Deriving the needle from the live file removes the class rather than paying
    # it again next round.
    head, section = appendix(text)

    def splice(body_text, at, width, piece):
        return body_text[:at] + piece + body_text[at + width:]

    def mutate(pattern, build, where=None):
        hay = text if where is None else where
        match = re.search(pattern, hay, re.M)
        if not match:
            return None
        start = match.start() if where is None else head + match.start()
        return splice(text, start, len(match.group(0)), build(match))

    def bump(delta):
        def build(match):
            return match.group(1) + str(int(match.group(2)) + delta) + match.group(3)
        return build

    def drop_one_entry():
        """Neutralise the **last** archived heading, wherever it is."""
        hits = list(re.finditer(r'^### (ISS-[\d.]+-\d+)', text, re.M))
        if not hits:
            return None
        last = hits[-1]
        # Deliberately NOT a shape ENTRY_RE accepts: replacing a heading with
        # another `ISS-0000-00` would leave the count unchanged and the control
        # would report "no mismatch" -- i.e. it would look like the check failed
        # to catch something, when in fact the mutation never removed an entry.
        return splice(text, last.start(1), len(last.group(1)), 'ISS-XXXX')

    cases = [
        # The exact defect this script was written after: one extra term, with
        # the stated total left where it was. The needle is derived from the
        # written sum's own tail rather than assuming the last term is `+1`:
        # 2026-10-17 the appendix started ending in `+**2** ＝ 150` (a category
        # went from 1 to 2), and the old `\+1\s*＝` needle matched nothing --
        # so the **control** broke while the check was fine, which prints the
        # same red the reader is supposed to act on. Anchor on the claim's own
        # parentheses and append `+1` before the `＝`.
        ('an extra "+1" term in the written expression',
         lambda: mutate(r'(「数量」列合计[^（(]*[（(])([^）)]*?)＝\s*(\d+)',
                        lambda m: m.group(1) + m.group(2) + '+1 ＝ ' + m.group(3),
                        section),
         'expression'),
        # A row bumped without touching the totals.
        ('a table row incremented by hand',
         lambda: mutate(r'(\| 几何/空间 \|\s*\*{0,2})(\d+)(\*{0,2} \|)', bump(1), section),
         'table row'),
        # The summary left behind after a new entry is added.
        ('a stated total left behind',
         lambda: mutate(r'(「数量」列合计\*{0,2}\s*=\s*\*{0,2})(\d+)(\*{0,2})',
                        bump(-1), section),
         '列合计'),
        # Deleting an entry heading without updating the count.
        ('an entry heading removed', drop_one_entry, '条目数'),
    ]
    failures = 0
    for label, mutate_once, needle in cases:
        mutated = mutate_once()
        if mutated is None:
            print('  BROKEN %s: the mutation matched nothing' % label)
            failures += 1
            continue
        found, _ = analyse(mutated)
        hit = [p for p in found if needle in p and not p.startswith(BLIND)]
        if hit:
            print('  ok  %s -> %s' % (label, hit[0]))
        else:
            print('  MISS %s: no mismatch problem mentions %r (got %r)'
                  % (label, needle, found))
            failures += 1

    # And the other direction: a reworded claim must be reported as "could not
    # measure" (exit 2), never as "the numbers disagree" (exit 1). Telling the
    # reader the totals are wrong when the truth is that the claim was not found
    # is exactly the substitution M60 exists to prevent.
    reworded = mutate(r'「数量」列合计\*{0,2}\s*=\s*\*{0,2}\d+\*{0,2}',
                      lambda m: '列合计为若干', section)
    if reworded is None:
        print('  BROKEN a reworded claim: the mutation matched nothing')
        failures += 1
    else:
        found, _ = analyse(reworded)
        misread = [p for p in found if not p.startswith(BLIND)]
        if found and not misread:
            print('  ok  a reworded claim -> %d blind, 0 mismatch (exit 2)'
                  % len(found))
        else:
            print('  MISS a reworded claim: expected only blind problems, got %r'
                  % found)
            failures += 1

    # Numbers restated in *other* documents fail differently (the file has to be
    # read at all), so they get their own controls -- one per restated number,
    # from the list that produced them.
    # Numbers restated in *other* documents fail differently (the file has to be
    # read at all), so they get their own controls -- one per declared
    # restatement, generated from the same list that produces the checks. A
    # hand-written control here would be a second copy of one fact, and a second
    # copy is the defect class this whole script exists to find (M66 / M67 ㉛).
    for index, (rel, pattern, expected) in enumerate(RESTATED, start=1):
        want = MEASURE_LABEL.get(expected[0], expected[0])
        label = '%s #%d (%s) left behind' % (rel, index, want)
        try:
            original = _read(rel, None)
        except OSError as exc:
            print('  BROKEN %s: cannot read %s (%s)' % (label, rel, exc))
            failures += 1
            continue
        match = re.search(pattern, original)
        if not match:
            print('  BROKEN %s: %r matched nothing in %s' % (label, pattern, rel))
            failures += 1
            continue
        mutated = splice(original, match.start(1), len(match.group(1)),
                         str(int(match.group(1)) - 1))
        found, _ = analyse(text, {rel: mutated})
        hit = [p for p in found if want in p and not p.startswith(BLIND)]
        if hit:
            print('  ok  %s -> %s' % (label, hit[0]))
        else:
            print('  MISS %s: expected a mismatch mentioning %r, got %r'
                  % (label, want, found))
            failures += 1

    # A restatement that no longer matches its declared shape is a blind spot,
    # not a mismatch -- the same distinction, for the same reason.
    rel, pattern = RESTATED[0][0], RESTATED[0][1]
    try:
        original = _read(rel, None)
    except OSError as exc:
        print('  BROKEN a reworded restatement: cannot read %s (%s)' % (rel, exc))
        failures += 1
    else:
        match = re.search(pattern, original)
        mutated = None if match is None else splice(
            original, match.start(1), len(match.group(1)), '若干')
        if mutated is None:
            print('  BROKEN a reworded restatement: the mutation matched nothing')
            failures += 1
        else:
            found, _ = analyse(text, {rel: mutated})
            misread = [p for p in found if not p.startswith(BLIND)]
            if found and not misread:
                print('  ok  a reworded restatement -> %d blind, 0 mismatch (exit 2)'
                      % len(found))
            else:
                print('  MISS a reworded restatement: expected only blind '
                      'problems, got %r' % found)
                failures += 1

    if failures:
        print('self-test FAILED: %d case(s) did not fire' % failures)
        return 1
    print('self-test PASSED: %d in-file mutations + %d restatement mutations '
          '+ 2 blind-spot cases, all caught' % (len(cases), len(RESTATED)))
    return 0


def main():
    if '--self-test' in sys.argv:
        return self_test()
    text = io.open(ISSUES, encoding='utf-8').read()
    problems, facts = analyse(text)
    blind = [p for p in problems if p.startswith(BLIND)]
    # Exit 2 before exit 1: "I could not see it" is a different report from
    # "I saw it and it disagrees", and only one of them is about the document.
    if blind:
        for problem in blind:
            print('UNMEASURABLE %s' % problem[len(BLIND):])
        return 2
    if problems:
        for problem in problems:
            print('FAIL %s' % problem)
        return 1
    print('entries %d | table rows %d | 合计 %d | expression %d | 差额 %d -- ok'
          % (facts['entries'], facts['rows'], facts['table_sum'],
             facts['expression_sum'], facts['stated_diff']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
