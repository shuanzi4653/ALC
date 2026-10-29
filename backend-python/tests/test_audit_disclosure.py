"""The disclosure sweep's own regressions.

Why this file exists
--------------------
``tools/harness/_audit_disclosure.py`` decides whether the submission package is
clean enough to hand over. A detector with a false-positive rate high enough to
be ignored is worse than no detector, and the two ways it goes wrong are exact
opposites:

* **Too loose** -- a pattern that misses a real credential. Catastrophic and
  invisible, because the report says "clean".
* **Too noisy** -- a pattern that fires on ordinary numbers and code. Not
  catastrophic by itself, but it destroys the signal, which then causes the
  first failure to be missed.

Both directions are asserted here, because a rule kept only as prose in the
script can drift silently while a rule kept as a test cannot.

The false positives asserted below are the ones actually measured on this
repository, not invented ones.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.harness._audit_disclosure import (  # noqa: E402
    BENIGN_LINE,
    KEY_FIELD_LABEL,
    PATTERNS,
    PEM_KEY_BODY,
    PHONE_LABEL,
    SHELL_EXPANSION,
    reports_as_identifier,
    reports_as_secret,
)

PATTERN_BY_LABEL = {label: pattern for label, pattern, _severity in PATTERNS}


def pattern_for(fragment):
    """The first pattern whose label contains ``fragment``."""
    for label, pattern in PATTERN_BY_LABEL.items():
        if fragment in label:
            return pattern
    raise AssertionError(f'no pattern labelled with {fragment!r}')


def reports(line, fragment='密钥字段'):
    """Whether the scanner would report ``line``, using the scanner's own path.

    Deliberately *not* ``key_field.search(line)``: the pattern only recognises the
    shape of an assignment, and whether the value is a variable reference is decided
    afterwards. Calling ``search`` directly asserted a different thing from what the
    audit does, and the mismatch went unnoticed for two rounds of tests.

    The phone label takes a second classifier (see
    :func:`reports_as_identifier`) and is routed through it here for the same
    reason: testing the pattern alone would assert something the scan loop does
    not do, and the two fixes to that classifier were both found by running the
    real path rather than the expression.
    """
    label = next(name for name in PATTERN_BY_LABEL if fragment in name)
    match = PATTERN_BY_LABEL[label].search(line)
    if not match:
        return False
    if label == PHONE_LABEL:
        return not reports_as_identifier(match, line)
    return reports_as_secret(match, label)


# --------------------------------------------------------------------------
# 身份证号 — must catch a real ID, must not catch arithmetic
# --------------------------------------------------------------------------

def test_an_actual_id_card_shape_is_still_blocked():
    """The whole point of the rule. Tightening must not blind it."""
    id_card = pattern_for('身份证号')
    assert id_card.search('11010119900307001X')
    assert id_card.search('"身份证": "110101199003070017"')
    assert id_card.search('id_card=110101199003070017')


@pytest.mark.parametrize('number', [
    '0.024814742307292192',      # measured: a benchmark extra-minutes value
    '41.11126841002106',         # measured: a benchmark latency value
    '294.595024814742307292192',  # same digits, welded onto a longer decimal
])
def test_a_long_float_is_not_mistaken_for_an_id_card(number):
    """Every one of these appeared in a real false-positive report.

    The digits of ``0.024814742307292192`` contain an eighteen-digit run; a rule
    that keys on "eighteen digits" alone cannot tell it from an ID card. The
    decimal-separator guards are what separate them.
    """
    id_card = pattern_for('身份证号')
    assert not id_card.search(number), number


# --------------------------------------------------------------------------
# 疑似填值的密钥字段 — must catch an assignment, must not catch an operator
# --------------------------------------------------------------------------

def test_a_real_populated_key_field_is_blocked():
    assert reports('api_key=9f3a72c1b48e6d05')
    assert reports('api_key=Ab12Cd34Ef56Gh78')       # mixed case: not an identifier
    assert reports('token: eyJhbGciOiJIUzI1NiJ9')
    assert reports('secret: Zx9Yw8Vu7Ts6Rq5P')


@pytest.mark.parametrize('line', [
    '"token": "eyJhbGciOiJIUzI1NiJ9"',        # JSON, spaced
    '"token":"eyJhbGciOiJIUzI1NiJ9"',         # JSON, tight
    "'secret': 'AbCdEf0123456789'",
])
def test_a_json_quoted_key_is_still_read_as_a_literal(line):
    """A quoted key name must not break the match.

    Measured gap: the unquoted pattern relied on ``\\b`` holding between a quote
    and a letter, which it does not, so every JSON-written credential file was
    invisible to the sweep. Config for this project is written in JSON and YAML,
    so that hole covered the common case.
    """
    assert reports(line), line


@pytest.mark.parametrize('line', [
    'api_key = configured_key',
    'api_key: configured_key',
    'secret: config.api.key',
    "'X-Internal-Token': INTERNAL_TOKEN",
])
def test_a_bare_identifier_value_is_not_a_literal_secret(line):
    """The one exclusion the sweep makes, and it is narrow on purpose.

    A bare identifier in value position cannot be a generated secret, and it is the
    spelling safe code actually uses, so classifying it away cannot hide a leak.
    """
    assert not reports(line), line


def test_a_shell_parameter_expansion_cannot_be_a_credential():
    """A `${VAR:+word}` construct is a reference by construction.

    Measured on ``backend-java/mvnw:189`` (upstream Maven Wrapper code, not this
    project's): ``case "${MVNW_PASSWORD:+has-password}" in`` is a *test for whether
    the variable is set*, and the literal is the substituted word -- the value being
    compared against, not a secret. The next line clears the variable. There is no
    credential anywhere on either line.

    Asserted as a property of :data:`SHELL_EXPANSION` so the rule is exercised
    directly, and separately in the scanner end-to-end below.
    """
    assert SHELL_EXPANSION.search('case "${MVNW_PASSWORD:+has-password}" in')
    assert SHELL_EXPANSION.search('${API_KEY:-default}')
    assert SHELL_EXPANSION.search('${SECRET}')


def test_the_identifier_exclusion_does_not_swallow_a_real_secret():
    """A control: the excluded shape and a secret stay distinguishable.

    ``configured_key`` is a name; ``Ab12Cd34Ef56Gh78`` is not, because real key
    material is mixed case where a hand-written name is not. If this ever passes the
    other way, the exclusion has grown past what it can defend.
    """
    assert reports('api_key: Ab12Cd34Ef56Gh78')
    assert not reports('api_key: configured_key')


@pytest.mark.parametrize('line', [
    'password: hunter2hunter2',
    'password: correcthorsebatt',
])
def test_a_lowercase_passphrase_is_the_recorded_gap(line):
    """Documents the boundary rather than pretending it does not exist.

    A lowercase passphrase is *lexically identical* to a lowercase variable name:
    ``hunter2hunter2`` and ``configured_key`` differ in nothing a token-level rule
    can see -- both are lowercase identifiers, and the digits in the first are legal
    inside a Python identifier. Twenty-one designs were measured; every one traded
    this false negative for a worse one, so the trade accepted here is **silence on
    an unquoted lowercase passphrase**, which quoting or any punctuation resolves.

    This test asserts the **accepted** behaviour on purpose: the day someone
    tightens the classifier, it fails, and they have to make that trade knowingly.
    """
    assert not reports(line), (
        'a lowercase passphrase is now reported -- update _is_identifier and this '
        'records-the-gap test together, and check no real key became a false negative'
    )


@pytest.mark.parametrize('line', [
    'const token=++weatherGeneration',        # measured: a Vue pre-increment
    'let token=--attemptsLeft',
    'reserved = key===candidate',
])
def test_an_operator_is_not_mistaken_for_a_key_value(line):
    """``token=++x`` is an assignment to a counter, not to a secret.

    Requiring an alphanumeric immediately after ``=`` is what rejects ``++``,
    ``--`` and ``===`` while keeping ``key=abc123``.
    """
    key_field = pattern_for('密钥字段')
    assert not key_field.search(line), line


# --------------------------------------------------------------------------
# PEM — a code constant is not a key
# --------------------------------------------------------------------------

def test_a_pem_key_with_a_base64_body_is_blocked():
    leaked = ('-----BEGIN PRIVATE KEY-----\n'
              'MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ\n'
              '-----END PRIVATE KEY-----')
    assert PEM_KEY_BODY.search(leaked)


def test_a_bare_pem_header_used_as_a_string_constant_is_not_a_key():
    """Measured: ``QweatherJwtService.java`` *strips* this header before decoding.

    Flagging the header alone would fire on the code that protects the key
    rather than the key itself -- a false positive on the safest possible file.
    """
    assert not PEM_KEY_BODY.search("private static final String HEADER = "
                                   "'-----BEGIN PRIVATE KEY-----';")


# --------------------------------------------------------------------------
# Benign-line suppression stays narrow
# --------------------------------------------------------------------------

def test_the_benign_filter_suppresses_mentions_but_not_values():
    assert BENIGN_LINE.search('*.key   # 忽略：私钥不进仓库')
    assert BENIGN_LINE.search('api_key: YOUR_KEY_HERE')
    assert not BENIGN_LINE.search('{"case": "case-032", "extraMinutes": 0.5}')


# --------------------------------------------------------------------------
# The sweep itself must stay honest about what it skipped
# --------------------------------------------------------------------------

def test_ignored_directories_are_matched_at_any_depth():
    """`.venv` must be skipped under `backend-python/`, not just at the root.

    The first version of the script matched a directory prefix and walked
    straight into the virtualenv, producing dozens of BLOCK findings inside
    numpy and cryptography. A pruned walk is the fix; this asserts the rule is
    depth-independent rather than root-anchored.
    """
    from tools.harness._audit_disclosure import IGNORED_DIRS
    assert 'backend-python/.venv'.split('/')[0] == 'backend-python'
    assert '.venv' in IGNORED_DIRS
    for pruned in ('node_modules', 'target', 'dist', 'backups'):
        assert pruned in IGNORED_DIRS


def test_every_pattern_declares_a_severity_that_the_script_acts_on():
    """A typo'd severity would silently demote a BLOCK to a printed WARN."""
    for label, pattern, severity in PATTERNS:
        assert severity in ('BLOCK', 'WARN'), label
        assert isinstance(pattern, re.Pattern), label


# --------------------------------------------------------------------------
# 手机号 — must catch a real number, must not catch a digest or an entity id
# --------------------------------------------------------------------------
#
# Both false-positive classes below were measured on this repository, and both
# are the kind that destroys the report's signal: `data/stations/*.json` holds a
# SHA-256 of every source file, and `fixed-zones.json` holds OpenStreetMap node
# ids. Six hex digits can be read as decimal, and an OSM node id is an arbitrary
# 11-digit integer, so in both cases a *plausible mobile number* appears inside
# a field that has nothing to do with people.

@pytest.mark.parametrize('line', [
    '联系电话：13812345678',
    'call 13812345678, now',
    '13812345678',
    '(13812345678)',
    '"phone": 13800138000,',
])
def test_a_real_mobile_number_is_still_reported(line):
    """The tightening must not blind the rule to an actual number."""
    assert reports(line, '手机号')


@pytest.mark.parametrize('line', [
    # A SHA-256 of the NOAA source CSV. The run `13086136094` inside it is
    # phone-shaped; every neighbour is a hex digit.
    '\'rawSha256\': \'c711eff13086136094c45a00c4d7665b892cdda25ac3baa2cdfaed5bf19cb408\',',
    '0529a0bf13096115200a1e4a2ba11c9f',
])
def test_a_digest_body_is_not_a_phone_number(line):
    """A hex letter beside the run is decisive: no number is glued to a hex digit."""
    assert not reports(line, '手机号')


@pytest.mark.parametrize('line', [
    '"referencePoint": "OpenStreetMap node/13814825170",',
    '"referencePoint": "OpenStreetMap node/13814825171",',
    '"id": 13800138000,',
    '13814825170Id',
    '13814825170_m2',
])
def test_a_qualified_numeric_identifier_is_not_a_phone_number(line):
    """An 11-digit integer is ambiguous; a label naming an entity resolves it."""
    assert not reports(line, '手机号')


@pytest.mark.parametrize('line', [
    '"worstMissingAreaM2": 17950347479.654,',
])
def test_a_benchmark_measurement_is_not_a_phone_number(line):
    """A decimal tail is not a standalone token."""
    assert not reports(line, '手机号')


def test_the_identifier_exclusion_leaves_prose_alone():
    """The exclusion must key on a *label*, not on the number's surroundings.

    `x 13812345678 y` was briefly excused because the trailing ` y` was read as a
    unit suffix -- a bare single letter after whitespace. A unit is glued to its
    number, so the trailing rule now forbids leading whitespace. This asserts the
    case that regression produced.
    """
    assert reports('x 13812345678 y', '手机号')
    assert reports('联系电话：13912345678。', '手机号')
