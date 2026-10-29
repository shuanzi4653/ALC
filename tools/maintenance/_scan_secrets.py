"""Scan for plaintext credentials. Exit 0 clean / 1 findings / 2 cannot measure.

Why this exists
---------------
2026-10-13: the cloud deployment shipped `config/application.yml` at mode 644 with
the real DeepSeek key inside, and the deployment doc printed the Nginx Basic Auth
password in the clear. Neither was noticed, because nothing ever looked: a plaintext
credential does not break a build, a test, or a smoke run. It is silent. Only an
unconditional judgement that fails loudly will catch it.

Two severities, because "a PEM header in a test fixture" is not a leaked key
--------------------------------------------------------------------------------
    SECRET  a real credential value. Counts toward the exit code.
    MARKER  the *shape* of one (e.g. `-----BEGIN ... PRIVATE KEY-----` used as a
            literal in code that strips it). Printed for visibility, never fatal.

Reporting the marker class as fatal is how a scanner gets switched off, and a
scanner that has been switched off is worse than none: the file still looks guarded.

Self-test, in both directions
-----------------------------
Before reporting, the tool plants two temp files inside the scanned root:
    a canary   that MUST be caught   -> proves the patterns still bite
    a negative that must NOT be caught -> proves they are not over-broad
The negative uses the exact forms this repository legitimately contains
(env-var placeholders, a curl call with no credentials). If either assertion
fails the tool exits 2, so a silent loss of teeth cannot be read as "clean".

Output is deliberately boring
-----------------------------
An earlier shell-loop scan of these same files printed labels that did not match
the strings actually searched, so "which string did I look for" was unrecoverable
from the output. This tool never routes its own patterns through a shell, escapes
non-ASCII on request, and can write a machine-readable report so that every
conclusion can be re-derived from numbers rather than from prose.

The report masks every matched value (`sk-2***REDACTED(35)***`). The first version
wrote the matched line verbatim, which meant running the scanner created a plaintext
copy of the very credential it had just found -- at a path that looks harmless.

    python _scan_secrets.py                      scan repo, print findings
    python _scan_secrets.py --json <path>        also write a report file
    python _scan_secrets.py --ascii              escape non-ASCII in output
    python _scan_secrets.py --no-canary          skip self-test (result UNVERIFIED)
"""

import argparse
import hashlib
import json
import os
import platform
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from _repo import ROOT  # noqa: E402

VERSION = '1.0'

SKIP_DIRS = {'.git', 'node_modules', '.venv', 'venv', '__pycache__',
             '.pytest_cache', 'dist', 'build', 'target', '.mypy_cache',
             '.idea', 'artifacts'}
# `.htpasswd` holds apr1 hashes (not plaintext); the Fernet key, the secrets DB and
# PEM files are intentional credential stores, and the first three are gitignored.
SKIP_FILE_PATTERNS = (
    re.compile(r'\.htpasswd'),
    re.compile(r'alc_secret\.key$'),
    re.compile(r'secrets\.db'),
    re.compile(r'\.pem$'),
    re.compile(r'\.jks$'),
    re.compile(r'\.keystore$'),
)
SKIP_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.woff', '.woff2', '.ttf',
            '.eot', '.mp4', '.zip', '.gz', '.tar', '.jar', '.class', '.db',
            '.mv.db', '.lock'}

# (name, severity, regex)
PATTERNS = [
    ('deepseek-key', 'secret', re.compile(r'sk-[0-9a-fA-F]{32}')),
    ('yml-api-key-literal', 'secret',
     re.compile(r'api-key\s*:\s*"\s*sk-[A-Za-z0-9]')),
    ('basic-auth-assign', 'secret',
     re.compile(r'BASIC_AUTH_PASS\s*=\s*[A-Za-z0-9+/=]{12,}')),
    ('curl-basic-auth-literal', 'secret',
     re.compile(r'-u\s+[A-Za-z0-9._-]{2,}:[A-Za-z0-9+/=_@.#-]{12,}')),
    ('aws-style-key', 'secret', re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
    ('private-key-block', 'marker', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    ('curl-with-password-flag', 'marker',
     re.compile(r'\b(curl|wget)\b[^\n]{0,120}\s(--password|-p)\s')),
    ('basic-auth-flag', 'marker', re.compile(r'\bauth_basic\b|\bauth_basic_user_file\b')),
]

OWN_FILE = os.path.abspath(__file__)
CANARY_NAME = '.canary-secret-scan.tmp'
NEGATIVE_NAME = '.canary-secret-scan-negative.tmp'

# Built at runtime: this file must not contain a string its own patterns catch.
CANARY_BODY = 'canary = "' + 'sk-' + ('0123456789abcdef' * 2) + '"\n'
NEGATIVE_BODY = (
    'deepseek:\n'
    '  api-key: "${DEEPSEEK_API_KEY:}"\n'
    'curl -s -o /dev/null -m 10 http://127.0.0.1:28081/healthz\n'
    'EnvironmentFile=-/opt/apps/AIC-tianchuang/.env.secrets\n'
    'ALC_BASIC_AUTH="$(cat /dev/null)"\n'
)


def esc(text, ascii_only):
    if not ascii_only:
        return text
    return text.encode('ascii', 'backslashreplace').decode('ascii')


def iter_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if os.path.splitext(name)[1].lower() in SKIP_EXT:
                continue
            if any(p.search(name) for p in SKIP_FILE_PATTERNS):
                continue
            path = os.path.join(dirpath, name)
            if os.path.abspath(path) == OWN_FILE:
                continue           # never report the scanner's own pattern table
            yield path


def scan_text(text):
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 4000:
            continue
        for name, severity, rx in PATTERNS:
            if rx.search(line):
                yield lineno, line, name, severity, rx


def mask_line(line, matched_rx):
    """Replace credential *values* with recognisable stubs.

    A report *about* leaked secrets must not itself become a store of them. The
    first version wrote the matched line verbatim into its JSON report, so running
    the scanner created the very artifact it exists to prevent -- at a path
    (`.run/reports/`) that looks harmless.

    The second version stubbed only the detector's own match, and the detectors are
    deliberately narrow: `yml-api-key-literal` stops at the first character after
    `sk-`, so `api-key: "sk-2***REDACTED(14)***467af...` left 31 of 35 characters
    of a live key on screen. Hence the generic pass below, which masks value-shaped
    runs regardless of what the pattern chose to match.

    Order matters: the specific stub first, then key=value idioms, then any long
    opaque run.
    """
    text = line.strip()
    if matched_rx is not None:
        text = matched_rx.sub(
            lambda m: m.group(0)[:4] + '***REDACTED(%d)***' % len(m.group(0)), text)
    text = re.sub(r'sk-[A-Za-z0-9_-]{8,}',
                  lambda m: m.group(0)[:4] + '***', text)
    text = re.sub(
        r'(?i)((?:api[-_]?key|apikey|password|passwd|secret|token|authorization)'
        r'\s*[:=]\s*"?)([^\s"]{6,})',
        lambda m: m.group(1) + '<redacted:%d>' % len(m.group(2)), text)
    text = re.sub(r'[A-Za-z0-9+/=_-]{28,}',
                  lambda m: '<redacted:%d>' % len(m.group(0)), text)
    return text[:200]


def scan_tree(root):
    findings = []
    for path in iter_files(root):
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as handle:
                text = handle.read()
        except OSError:
            continue
        for lineno, line, name, severity, rx in scan_text(text):
            findings.append({
                'path': os.path.relpath(path, root),
                'line': lineno,
                'pattern': name,
                'severity': severity,
                'excerpt': mask_line(line, rx),
            })
    return findings


def self_test(root):
    """Both directions. Returns (ok, list-of-messages)."""
    messages = []
    canary = os.path.join(root, CANARY_NAME)
    negative = os.path.join(root, NEGATIVE_NAME)
    try:
        with open(canary, 'w', encoding='utf-8') as handle:
            handle.write(CANARY_BODY)
        with open(negative, 'w', encoding='utf-8') as handle:
            handle.write(NEGATIVE_BODY)
        hits = scan_tree(root)

        caught = [h for h in hits if h['path'] == CANARY_NAME]
        if not caught:
            return False, ['canary NOT detected -- patterns or walk stopped matching; '
                           'a "clean" report from this run would be a lie']
        names = sorted({h['pattern'] for h in caught})
        if names != ['deepseek-key']:
            return False, ['canary matched %s; expected exactly deepseek-key' % names]
        messages.append('canary caught by deepseek-key (patterns are live)')

        false_pos = [h for h in hits if h['path'] == NEGATIVE_NAME]
        if false_pos:
            return False, ['negative control WAS flagged by %s -- patterns are '
                           'over-broad and would fail on the forms this repo '
                           'legitimately uses' % sorted({h['pattern'] for h in false_pos})]
        messages.append('negative control (placeholders, credential-free curl) '
                        'correctly not flagged')
        return True, messages
    finally:
        for path in (canary, negative):
            try:
                os.remove(path)
            except OSError:
                pass


def file_digest(path):
    try:
        with open(path, 'rb') as handle:
            return hashlib.sha256(handle.read()).hexdigest()[:16]
    except OSError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--root', default=ROOT)
    parser.add_argument('--json', dest='json_path', default=None)
    parser.add_argument('--ascii', action='store_true')
    parser.add_argument('--no-canary', action='store_true')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print('FAIL: not a directory: %s' % args.root)
        return 2

    verified = not args.no_canary
    messages = []
    if verified:
        ok, messages = self_test(root)
        if not args.quiet:
            for message in messages:
                print('%s self-test: %s' % ('OK  ' if ok else 'FAIL', esc(message, args.ascii)))
        if not ok:
            print('EXIT 2 -- cannot measure. This is NOT a clean result.')
            return 2
    elif not args.quiet:
        print('WARN self-test skipped (--no-canary) -- result is UNVERIFIED')

    findings = scan_tree(root)
    secrets = [f for f in findings if f['severity'] == 'secret']
    markers = [f for f in findings if f['severity'] == 'marker']

    if not args.quiet:
        for finding in findings:
            print('%s:%d: [%s/%s] %s' % (esc(finding['path'], args.ascii),
                                         finding['line'], finding['severity'],
                                         finding['pattern'],
                                         esc(finding['excerpt'], args.ascii)))

    report = {
        'tool': '_scan_secrets.py',
        'toolVersion': VERSION,
        'python': platform.python_version(),
        'root': root,
        'selfTestVerified': verified,
        'selfTestNotes': messages,
        'patterns': [{'name': n, 'severity': s} for n, s, _ in PATTERNS],
        'counts': {'filesScanned': sum(1 for _ in iter_files(root)),
                   'secrets': len(secrets), 'markers': len(markers)},
        'secrets': secrets,
        'markers': markers,
    }
    if args.json_path:
        report['counts']['filesScanned'] = report['counts']['filesScanned']
        with open(args.json_path, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        if not args.quiet:
            print('report written: %s (sha256[:16]=%s)'
                  % (args.json_path, file_digest(args.json_path)))

    print('SUMMARY secrets=%d markers=%d files=%d selfTestVerified=%s'
          % (len(secrets), len(markers), report['counts']['filesScanned'], verified))
    return 1 if secrets else 0


if __name__ == '__main__':
    raise SystemExit(main())
