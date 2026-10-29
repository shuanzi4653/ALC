"""Independent disclosure sweep over everything that could leave this machine.

Why this exists
---------------
The project is a **derivative creative work about meteorology** submitted to a
competition, and the submission rules require the materials to be anonymised and
free of credentials, private keys and personal identifiers. "I checked" is not
evidence, and a spot check is not a sweep: the failure mode is a single leaked
token in one of several hundred files, which nobody finds by reading.

So this walks the **tracked** tree (that is what a submission package is built
from) and reports findings by category, with the file and line. It never prints
the matched secret value itself -- only its shape and location -- so the audit
output is safe to paste into a report.

Two kinds of finding, deliberately separated:

* **BLOCK** -- would actually leak a credential or identity. These must be zero
  before packaging.
* **WARN** -- a path or phrase that merely *looks* sensitive (e.g. a mention of
  a key file in a `.gitignore`, or a home-directory path in an example config).
  These are expected in some places and must be reviewed, not blindly deleted.

The distinction matters: flagging everything as a leak trains the reader to
ignore the report, which is the same as having no report.

Every pattern in :data:`PATTERNS` was tightened against a **measured** false
positive rather than a guessed one, and the reason is recorded next to the
pattern. The initial run produced five BLOCK items and all five were false: a
Vue local counter being pre-incremented (a `token=` assignment whose "value"
was the `++` operator), and a pair of long benchmark floats matched by the
ID-card shape (a run of eighteen digits, the last of which happened to be the
tail of the decimal). A leak detector that cries wolf on arithmetic is worse
than useless -- it is actively misleading -- so the fix is always to sharpen the
*evidence the pattern demands*, never to suppress the category.

The invariants themselves live in ``tests/test_audit_disclosure.py`` rather than
as prose, because a pattern that is described in a comment can silently regress
while a pattern that is asserted cannot. Note also that this docstring must not
spell out the offending literals: it is scanned by this very script, so quoting
a false-positive number here would re-create the false positive.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402

# Directory names that are gitignored and therefore never packaged. Matched as
# **path segments**, not as prefixes.
#
# This distinction was a real defect in the first version of this file: matching
# on `'.venv' + os.sep` as a prefix missed `backend-python/.venv`, because that
# relative path starts with `backend-python`, not with `.venv`. The walk descended
# into the virtualenv and reported **84 BLOCK findings, every one of them inside a
# third-party library** -- `numpy`'s test fixtures contain ID-card-shaped literals,
# `cryptography`'s source contains the PEM header constant. A report that is 100%
# false positives is worse than no report, because the next reader learns to
# ignore it.
IGNORED_DIRS = frozenset({
    '.run', '.git', '.venv', 'node_modules', '__pycache__', 'target', 'dist',
    'backups', 'backup', 'archive', '.pytest_cache', '.mypy_cache', '.idea',
    '.vscode', 'build', '.audit',
})

SKIP_EXT = {
    '.png', '.jpg', '.jpeg', '.gif', '.ico', '.webp', '.pdf', '.zip',
    '.jar', '.class', '.db', '.sqlite3', '.woff', '.woff2', '.ttf', '.eot',
    '.mp4', '.mov', '.pbf', '.mvt', '.bin',
}

# Nothing here tries to decide "is this value a secret or a variable name?", and
# that is a deliberate conclusion rather than an omission. **Twenty-one designs were
# measured** (eight inside the expression, the rest as a classifier) and every one
# failed, which is strong evidence the question is not answerable from the token.
#
# The two fixture pairs that break it are worth stating plainly, because each looks
# like it should be easy:
#
# * ``api_key=Ab12Cd34Ef56Gh78`` (a secret) and ``password: correcthorsebatt`` (a
#   name) differ only in case pattern, which a hand-written name violates anyway.
# * ``password: hunter2hunter2`` (a secret) and ``token: has-password`` (a key name
#   in shell prefix form) are *the same shape*: lowercase words joined by a digit
#   and a hyphen. No lexical rule separates them; one is a passphrase and one is a
#   shell variable, and only context says which.
#
# A rule that guesses would either drop real secrets -- the worst outcome for this
# script -- or report the safest files in the tree, which is how a report gets
# ignored. So the sweep does what it can defend: it **detects the shape and states
# the shape**, and the ``WARN`` bucket plus the printed match shape are what carry
# the remainder to a human. `_verify_secrets.py` in this same directory does the
# complementary job for the known-configured paths.
#
# What *is* excluded is narrower and decidable: a value that is a **bare identifier
# in value position** -- `api_key = configured_key`. That is the spelling safe code
# actually uses, and an identifier is never a generated secret, so classifying it
# away cannot hide a leak.

# A run of identifier characters, which is what a value or a key name looks like.
# Used by :func:`_value_of`; see there for why the value is located by taking the
# trailing run rather than by splitting on the separator.
VALUE_RUN = re.compile(r'[A-Za-z0-9_\-]+')

# The one label whose match needs the value classifier applied. Held as a constant
# so the scan loop and the pattern list cannot drift apart -- a rename of the label
# would otherwise silently disable the classifier instead of failing.
KEY_FIELD_LABEL = '疑似填值的密钥字段'

# The phone label needs a *different* exclusion, because an 11-digit run starting
# with `1[3-9]` has two legitimate meanings that no regular expression can tell
# apart: a mobile number and an arbitrary numeric identifier. Measured on real
# project data, `"referencePoint": "OpenStreetMap node/13814825170"` is exactly
# phone-shaped, and OSM node ids are common enough in provenance blocks that
# reporting them would make the phone category noise.
#
# The decidable half is the **qualified identifier**: when the run sits in
# `referencePoint` / `node/` / `id` / `station` / `*Id` context it is naming an
# entity, not identifying a person. Unqualified is still reported, so a bare
# number in prose is a finding -- that is the case worth a human's attention.
PHONE_LABEL = '手机号'
# Words that mark a numeric run as an entity reference rather than a phone number.
# `node/…` and `…Id`/`…ID` are the two spellings actually present in the tree.
ID_QUALIFIERS = re.compile(
    r'(?i)(?:^|[^a-z0-9])('
    r"referencePoint|node|way|relation|ref|id|uid|gid|sid|hash|sha|checksum"
    # The optional run after the word is what closes a *quoted* key in JSON:
    # `"referencePoint": "node/…"`. The first version of this class omitted the
    # double quote, so it matched the bare `node/…` spelling but **not** the
    # quoted `"id": 138…` one -- a hole found by testing the JSON spelling rather
    # than only the spelling that happened to appear in the tree.
    r')\s*["\']?\s*[:/=#]?\s*["\']?\s*$'
)
# Trailing form: `13814825170_m2`, `13814825170Id`. Anchored with **no leading
# space permitted**, and that is the whole point: allowing whitespace here made
# `x 13812345678 y` an identifier on the strength of its trailing ` y`, which is
# how a real number in a sentence gets excused. A unit suffix is glued to its
# number; a following prose word is separated by a space.
ID_TRAILING = re.compile(r'(?i)^(?:_?(?:id|ids|m2|km2|ha|ms|us|ns))(?!\w)')


def _value_of(match):
    """The value part of a key-field match.

    The key name is matched by the pattern but not captured, so the value is taken
    as **the last run of identifier characters in the match**. Splitting on the
    ``:`` is the obvious alternative and is wrong: the separator is optional in the
    pattern (shell prefix forms, ``=`` forms with no colon), so a match such as
    ``MVNW_PASSWORD:+has-password`` puts the key name and the value in one run and
    splitting would inspect the *name* instead of the value.

    Taking the trailing run needs no separator at all: ``:``, ``+``, ``(`` and the
    quotes all sit outside the class, so the final run *is* the value.
    """
    tail = VALUE_RUN.findall(match.group(0))
    return tail[-1] if tail else ''


def reports_as_secret(match, label):
    """Whether ``match`` from ``label`` is a finding worth reporting.

    The scan loop's decision, exposed so the tests exercise **the same path the
    scanner takes** rather than a re-implementation. Two earlier rounds of tests
    called ``pattern.search`` directly and therefore asserted a different thing from
    what the audit does -- they passed while the scanner was wrong and failed once
    it was right. A test that re-implements the thing under test measures itself.

    The one exclusion: a value that is a **bare identifier reached through an
    explicit separator** -- ``api_key: configured_key``. Two conditions, and both
    are needed:

    * ``separator_in_prefix`` -- the text before the value contains ``:`` or ``=``.
      Without this, a shell prefix form such as ``MVNW_PASSWORD:+has-password``
      matches *starting at the key name*, and an unguarded identifier check would
      classify that name and drop the line. (The line is a reference, so dropping it
      is right here -- but it must follow from "a separator was seen", not from
      inspecting whatever happened to sit at the front.)
    * ``_is_identifier`` -- the value really is an identifier, optionally dotted.
    """
    if label == KEY_FIELD_LABEL:
        text = match.group(0)
        value = _value_of(match)
        if value:
            prefix = text[:text.rfind(value)]
            separator_in_prefix = ':' in prefix or '=' in prefix
            if separator_in_prefix and _is_identifier(value):
                return False
    return True


def _is_identifier(value):
    """True when ``value`` is a single bare identifier, optionally dotted.

    Deliberately minimal, and it must stay minimal. ``str.isidentifier()`` alone is
    **not** the test: it accepts ``hunter2hunter2``, ``Ab12Cd34Ef56Gh78`` and
    ``eyJhbGciOiJIUzI1NiJ9``, because a Python identifier may contain digits after
    the first character. Measured: with the bare ``isidentifier`` check, seven of the
    eight real secrets in the fixtures were classified as references and stopped
    being reported -- a rule intended to excuse variable names silently disabling
    the detection it was guarding.

    A name that a developer writes to hold a secret is **a word**, not a run of
    digits and capitals: it is lowercase or SCREAMING_CASE, and each dotted part is
    too. `configured_key`, `config.api.key` and `INTERNAL_TOKEN` all qualify;
    `hunter2hunter2` and `Ab12Cd34Ef56Gh78` do not, because real key material is
    mixed case by construction.

    The known, unavoidable residue is a value that is *both* -- a lowercase
    passphrase like `correcthorsebatt`. It is reported, and
    `test_a_passphrase_shaped_like_an_identifier_is_a_known_gap` records that
    boundary on purpose. This is a bounded false positive, chosen over the
    unbounded false negative that any looser rule produced.
    """
    if not value:
        return False
    for part in value.split('.'):
        if not part.isidentifier():
            return False
        if not (part.islower() or part.isupper()):
            return False
    return True


def reports_as_identifier(match, line):
    """True when a phone-shaped run is really a *numeric identifier*.

    The one thing the ``手机号`` pattern cannot decide for itself: an 11-digit run
    beginning ``1[3-9]`` is a mobile number **and** an ordinary integer, and the
    two are the same string. Measured on this tree, the whole ambiguity is
    qualified references -- ``"referencePoint": "OpenStreetMap node/13814825170"``
    -- so the exclusion is scoped to exactly that evidence rather than to a
    heuristic about the number itself.

    Two positive pieces of evidence, either one sufficient:

    * **A label to the left** naming an entity or a digest (``node/``, ``id``,
      ``referencePoint``, ``hash``, ``sha``). See :data:`ID_QUALIFIERS`.
    * **A unit or suffix to the right** (``_m2``, ``Id``). See
      :data:`ID_TRAILING`.

    Both require positive evidence, and neither fires on ``联系电话：138…`` or a
    bare run in prose -- those stay reported, because they are the case a human
    actually needs to see. Same reasoning as :func:`reports_as_secret`: **a
    vetoing rule must be positive evidence for the excused case, never merely the
    absence of evidence for the real one** -- an absence-based veto silently
    disables the detection it was meant to refine, which is the failure that cost
    twenty-one designs in the key-field classifier.
    """
    if ID_QUALIFIERS.search(line[:match.start()]):
        return True
    if ID_TRAILING.match(line[match.end():]):
        return True
    return False


# (label, compiled pattern, severity). Patterns are written to match the *shape*
# of a real credential, not a bare keyword: `apikey` alone appears legitimately
# in documentation about how the gateway authenticates, and flagging it would be
# a false positive on nearly every config file in the tree.
PATTERNS = (
    # A 32-hex or 40-hex run is the shape of an API key / commit SHA. The git
    # SHA case is why this is WARN and not BLOCK: `changelog/` legitimately
    # quotes full commit hashes.
    ('长十六进制串（可能是密钥/哈希）', re.compile(r'\b[0-9a-fA-F]{32,}\b'), 'WARN'),
    # DeepSeek / OpenAI style keys carry a recognisable vendor prefix.
    ('sk- 开头的 API Key', re.compile(r'\bsk-[A-Za-z0-9_-]{16,}'), 'BLOCK'),
    # A populated `key: value` where the value is not an obvious placeholder.
    #
    # Three measured false positives shaped this pattern, each fixed by demanding
    # more evidence rather than by widening the benign filter:
    #
    # 1. `const token=++weatherGeneration` -- a Vue counter being pre-incremented.
    #    The `=` branch requires an alphanumeric immediately after it, so `++`,
    #    `--`, `=>` and `===` are excluded while `key=abc123` still matches. (The
    #    `:` branch needs no such guard: `token: abc123…` is already unambiguous.)
    # 2. A JSON-quoted spelling (`"token": "…"`) was missed entirely, because the
    #    word-boundary assertion does not hold between a quote and a letter. The
    #    optional `["\']?` on both sides of the key name closed a genuine hole --
    #    config files written in JSON are the common case for this project.
    # 3. That widening then matched `"api_key": configured_key` -- a *variable
    #    reference*. The pattern now captures the value and defers that judgement
    #    to :func:`_is_reference`; see :data:`REFERENCE_TAIL` for why the split is
    #    at "extract the value" rather than inside the expression.
    ('疑似填值的密钥字段',
     re.compile(r'(?i)(?:api[_-]?key|apikey|secret|token|password|passwd|pwd)["\']?'
                r'\s*(?::|=(?=[A-Za-z0-9]))\s*'
                r'["\']?(?!\s*$|""|\'\'|null|None|true|false|YOUR|<|\$\{|#|placeholder|CHANGE)'
                r'[A-Za-z0-9/+=_\-]{12,}'),
     'BLOCK'),
    # A PEM header alone is not a key: `QweatherJwtService.java` *strips* the header
    # before base64-decoding its configured key file, which is the opposite of
    # leaking one, and a line-based pattern flagged it. The real thing is a header
    # followed by key material, which spans lines -- hence the whole-file scan and
    # the separate `WARN` for a bare header.
    ('PEM 私钥头（仅字符串常量，需人工确认）',
     re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'), 'WARN'),
    ('绝对用户路径（含用户名）',
     re.compile(r'(?i)\b[A-Z]:[\\/]+Users[\\/]+[A-Za-z0-9_.\-]+'), 'WARN'),
    # A mainland mobile number. Two measured false-positive classes made this
    # pattern narrower than the textbook one:
    #
    # 1. **A substring of a hex digest.** `data/stations/*.json` carries a
    #    `rawSha256` of each NOAA source file, and six hex digits happen to be
    #    decimal, so a run such as `...c711eff13086136094c45a...` contains
    #    `13086136094` -- a well-formed mobile number, inside a checksum. The
    #    digit guard cannot see this: every neighbour is a hex digit, which *is*
    #    a word character, so `(?<!\d)` holds. The fix is the `(?<![0-9a-fA-F])`
    #    on the left and the matching guard on the right: a real phone number is
    #    never preceded or followed by a hex letter, and a digest match always is
    #    at least as often as not.
    # 2. **A numeric identifier.** An OpenStreetMap node id is an arbitrary
    #    11-digit integer, so `node/13814825170` in a provenance block is
    #    indistinguishable from a phone number *by shape alone* -- no expression
    #    separates them, because they are the same string. That case is resolved
    #    in code by :func:`reports_as_identifier`, which reads the surrounding
    #    label: a qualified reference (`node/…`, `*Id`, `referencePoint`) names an
    #    entity, an unqualified run in prose may identify a person and is kept.
    #
    # Both were false positives on real project data, not invented cases, and an
    # 11-digit identifier is common enough (OSM ids, timestamps to the second) that
    # leaving the second unguarded would have the report crying wolf on provenance.
    ('手机号',
     # Left: not a hex letter (digest body), not the tail of a dotted decimal.
     # Right: same. Both guards together are what kill the checksum class; the
     # identifier class needs the label and is handled in the scan loop.
     re.compile(r'(?<![0-9a-fA-F])(?<!\d\.)1[3-9]\d{9}(?![0-9a-fA-F])(?![\d.])'),
     'WARN'),
    # An 18-char ID number. A bare `\d{17}[\dXx]` is **not** enough evidence of
    # an identity: measured false positives were long benchmark floats -- runs of
    # eighteen digits that were merely the tail of a decimal value. A real ID card
    # is a **standalone token**, so the guards on the decimal separator exclude a
    # match that is the continuation of a longer number, while still admitting a
    # bare ID number on its own and one labelled inline. Kept at BLOCK because a
    # true positive here is the worst possible leak, and the guards below are what
    # keep that BLOCK meaningful instead of noisy.
    ('身份证号', re.compile(r'(?<![\d.])\d{17}[\dXx](?![\d.])'), 'BLOCK'),
    ('邮箱地址', re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'), 'WARN'),
    ('内网 IP', re.compile(r'\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b'), 'WARN'),
)

# Lines that are *about* the pattern rather than an instance of it. A `.gitignore`
# entry for `*.key`, or a comment explaining that keys must not be committed, is
# the opposite of a leak; the sweep must not report it.
BENIGN_LINE = re.compile(
    r'(?i)(gitignore|忽略|不得|禁止|不进|不要|materials? must|never|placeholder|'
    r'示例|模板|example|dummy|redact|脱敏|占位|YOUR_|<your|xxxx|\*\*\*)'
)

# A POSIX shell parameter expansion, e.g. `${MVNW_PASSWORD:+has-password}`.
#
# Measured on `backend-java/mvnw` (upstream Maven Wrapper code, not this project's):
# the line is a *test for whether a variable is set*, and `has-password` is the
# literal substituted when it is -- the value being compared, not a secret. The next
# line clears the variable outright. There is no credential on either line.
#
# This is checked as a whole-line property rather than added to `BENIGN_LINE`
# because the two mean different things: `BENIGN_LINE` marks a line that *mentions*
# a secret, while this marks a line that *cannot contain one* -- the construct is a
# reference by definition, whatever the variable is named.
SHELL_EXPANSION = re.compile(r'\$\{[A-Za-z_][A-Za-z0-9_]*(?::[-+=?][^{}]*)?\}')

MAX_BYTES = 4 * 1024 * 1024  # do not try to regex a stray binary blob

# Files that necessarily *contain* one example of each forbidden shape, because
# their job is to assert that the shapes above are detected. `test_audit_
# disclosure.py` holds a fake ID number, a fake API key and a fake password as
# literal arguments to ``assert pattern.search(...)``.
#
# It would be tempting to make the fixtures un-matchable by assembling them from
# fragments at runtime. That is worse: a fixture that does not look like the thing
# it tests no longer proves the pattern works, and this file's entire value is
# that it does. So the file is exempted explicitly and by name, which keeps the
# exemption visible and reviewable -- rather than inferred from a heuristic that
# the next real leak could also satisfy.
SELF_TEST_FILES = frozenset({
    'tools/harness/_audit_disclosure.py',
    'backend-python/tests/test_audit_disclosure.py',
})

# A real PEM private key: header, then base64 key material. Matched over the whole
# file because the two parts are on different lines. `{40,}` on the body is the
# discriminator -- a bare header is a code constant, a header plus a long base64
# run is a key.
PEM_KEY_BODY = re.compile(
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\r\n]+[A-Za-z0-9+/=\r\n]{40,}')


def _gitignored(paths):
    """Which of ``paths`` git would refuse to add, per ``git check-ignore``.

    A credential in a gitignored file is **contained**: it will not be committed
    and a submission package built from the tracked tree will not carry it. That
    is materially different from a credential in a tracked file, and collapsing
    the two produces a report where the one real leak is indistinguishable from
    a dozen harmless ones -- the failure mode this whole script exists to avoid.

    Returns a set of absolute paths. Empty when git is unavailable, in which case
    everything is treated as tracked (the conservative direction: an unverifiable
    ignore rule must not be assumed to work).
    """
    paths = list(paths)
    if not paths:
        return set()
    # **Relative** paths are required. `git check-ignore` matches its input against
    # the ignore patterns as written (which are repo-relative), so an absolute
    # `C:\...\config/application.yml` matches nothing even though the rule exists --
    # silently returning "not ignored" for every real secret, which is the worst
    # possible failure for this function. The first version did exactly that and
    # reported `0 个文件被 gitignore 覆盖` while three gitignored secret files were
    # in the findings.
    relative = {}
    for path in paths:
        try:
            relative[str(Path(path).resolve().relative_to(Path(ROOT).resolve())).replace(os.sep, '/')] = path
        except ValueError:
            continue
    if not relative:
        return set()
    # Paths are passed as **arguments**, not on stdin.
    #
    # `git check-ignore --stdin` reads its list from stdin, and inside this sandbox
    # the child process's stdin does not carry the data: measured `returncode == 1`
    # with empty stdout on a list that the shell had just confirmed matched. Passing
    # arguments avoids the pipe entirely. The list is chunked because a few hundred
    # paths exceed the Windows command-line limit, and each chunk is one process.
    ignored = set()
    chunk_size = 100
    entries = list(relative)
    for start in range(0, len(entries), chunk_size):
        chunk = entries[start:start + chunk_size]
        try:
            result = subprocess.run(
                ['git', 'check-ignore', *chunk],
                cwd=str(ROOT), capture_output=True, text=True,
                encoding='utf-8', errors='replace')
        except OSError:
            return set()
        if result.returncode not in (0, 1):
            return set()
        for line in result.stdout.splitlines():
            name = line.strip()
            if name in relative:
                ignored.add(Path(relative[name]).resolve())
    return ignored


def tracked_files():
    """Files in the tree, minus the gitignored build/run directories.

    Deliberately a filesystem walk rather than ``git ls-files``: the submission
    package is built by copying the working tree, so a file that is present but
    accidentally un-ignored is exactly the case worth catching, and ``git
    ls-files`` would hide it.

    Pruning is by **directory name at any depth**, so `backend-python/.venv` is
    skipped as well as a top-level `.venv`. See :data:`IGNORED_DIRS`.
    """
    for root, dirs, names in os.walk(ROOT):
        dirs[:] = [directory for directory in dirs
                   if directory not in IGNORED_DIRS
                   and not directory.startswith('.git')]
        for name in names:
            if Path(name).suffix.lower() in SKIP_EXT:
                continue
            yield Path(root) / name


def main():
    findings = []
    scanned = 0
    skipped_self_test = 0
    visited = []
    for path in tracked_files():
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        scanned += 1
        rel = os.path.relpath(path, ROOT)
        # The sweep and its own test file are reported as counted-but-exempt so
        # the exemption appears in the output instead of being a silent hole. See
        # :data:`SELF_TEST_FILES`.
        if rel.replace(os.sep, '/') in SELF_TEST_FILES:
            skipped_self_test += 1
            continue
        visited.append(path)

        # PEM keys are matched against the **whole file**, not line by line: the
        # header and the base64 body are on separate lines, so a per-line scan can
        # only ever see the header -- which is a constant that appears in code that
        # *consumes* PEM files as well as in leaked ones.
        if PEM_KEY_BODY.search(text):
            findings.append(['BLOCK', 'PEM 私钥（含密钥体）', rel, 1,
                             '-----BEGIN … KEY----- + base64 body', path])

        for lineno, line in enumerate(text.splitlines(), 1):
            if BENIGN_LINE.search(line):
                continue
            for label, pattern, severity in PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                # A shell parameter expansion is a reference by construction, so no
                # key-field finding inside one can be a credential. Checked here
                # rather than in the pattern because it is a property of the *line*,
                # not of the match. See :data:`SHELL_EXPANSION`.
                if label == KEY_FIELD_LABEL and SHELL_EXPANSION.search(line):
                    continue
                # The pattern recognises the *shape* of an assignment; deciding
                # whether the value is a reference is a token question and is done
                # here. See :func:`reports_as_secret` -- the tests call the same
                # function, so they cannot drift from this loop.
                if not reports_as_secret(match, label):
                    continue
                # A phone-shaped run may be a numeric identifier instead. Same
                # arrangement: the pattern sees the shape, the label decides. See
                # :func:`reports_as_identifier`.
                if label == PHONE_LABEL and reports_as_identifier(match, line):
                    continue
                found = match.group(0)
                # Report the shape, never the value: a leaked key printed to
                # stdout has leaked again, this time into the audit log.
                shape = found if len(found) <= 12 else found[:6] + '…' + found[-3:]
                findings.append([severity, label, rel, lineno, shape, path])

    ignored = _gitignored(visited)
    for finding in findings:
        # A gitignored file cannot reach the repository or a tracked-tree package,
        # so its contents are downgraded from BLOCK to WARN. The finding is still
        # reported -- the rule must be seen to be doing the containing -- but it no
        # longer competes with a genuine leak for the reader's attention.
        if finding[5].resolve() in ignored and finding[0] == 'BLOCK':
            finding[0] = 'WARN(已忽略)'

    findings.sort(key=lambda item: (not item[0].startswith('BLOCK'), item[2], item[3]))
    blocks = [item for item in findings if item[0] == 'BLOCK']
    warns = [item for item in findings if item[0] != 'BLOCK']

    # The skipped-directory list is generated from IGNORED_DIRS rather than
    # written out by hand: a hand-written list drifts the moment someone adds an
    # entry, and a header that names fewer directories than were actually
    # skipped makes the count below look wrong (walked into on 2026-10-10 --
    # __pycache__ and .pytest_cache had been pruned for several rounds while the
    # header still advertised the original seven).
    print(f'扫描文件 {scanned} 个（按目录名跳过 {len(IGNORED_DIRS)} 项：'
          f'{" ".join(sorted(IGNORED_DIRS))}，以及任何 .git* 目录）')
    if skipped_self_test:
        print(f'其中 {skipped_self_test} 个为检测器自身及其自测文件（必须包含样张，已豁免）')
    print(f'BLOCK {len(blocks)} 条 · WARN {len(warns)} 条'
          f'（其中 {len(ignored)} 个文件被 gitignore 覆盖，其内容降级为 WARN(已忽略)）')
    print()
    for severity, label, rel, lineno, shape, _path in findings:
        print(f'[{severity}] {rel}:{lineno}  {label}  -> {shape}')
    print()
    if blocks:
        print('结论：存在阻断项，打包前必须处理。')
    else:
        print('结论：未发现会实际泄露凭据或身份信息的阻断项（WARN 需人工复核）。')
    return 1 if blocks else 0


if __name__ == '__main__':
    raise SystemExit(main())
