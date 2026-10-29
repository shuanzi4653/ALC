"""Normalise and verify the delivered TianChuang launcher folder.

Exit 0 clean / 1 findings / 2 cannot measure -- same trichotomy as
`_scan_secrets.py`, and for the same reason: a checker that silently stopped
matching exits 0 *identically* to "clean".

Why this exists
---------------
The folder `TianChuang/` is handed to someone else as-is. Three of its
properties cannot be seen by reading the files:

  1. `.bat` must be pure ASCII with CRLF. `cmd.exe` parses a .bat byte-by-byte
     using the *console* code page (936 on a Simplified-Chinese Windows), so a
     stray Chinese character or an LF-only line produces
     "'xist' is not recognized as an internal or external command" -- a failure
     that looks like a broken script, not an encoding problem.
     The `Write` tool always emits LF+UTF-8, so this can only be fixed by a
     byte-level pass after writing.

  2. `.ps1` containing non-ASCII must be UTF-8 *with* BOM (the repo already
     enforces this for `scripts/*.ps1`). Without the BOM, Windows PowerShell 5.1
     reads the file as ANSI and every Chinese string becomes mojibake.

  3. The launcher must not touch anything local. This is the actual requirement
     -- "one double-click and the browser opens the cloud project" -- and it is
     invisible in review: a single leftover `127.0.0.1` or a `C:\\...` path
     silently makes the folder work only on the machine that built it.

Cross-reference, not self-reference
-----------------------------------
M75 discipline: a judgement that only compares the deliverable against itself
cannot answer "is this deliverable right". The launcher's single most important
fact is *where the cloud is*, so that value is checked against two artifacts
outside the folder:

    config/nginx/domains.site        -> the PUBLIC entry (server_name + 443-ssl)
    config/nginx/AIC-tianchuang.site -> the INNER listen port (must NOT be used)
    docs/<deployment doc>            -> the address the operator is told to use

2026-10-14 correction -- the referent had gone stale. Until the domain switch the
inner site block WAS the public entry, so reading its `listen` was right. After
the switch the inner block listens on 127.0.0.1 only; taking its port as "the
address the recipient should use" would bless a launcher pointed at a port that
is closed to the public -- i.e. the check would certify a dead address. The
referent is now the public entry, and the inner port is used for a NEGATIVE
check (the launcher must not use it).

If the folder and the cloud config disagree, one of them is stale, and the tool
says so instead of passing.

    python _normalise_launcher_folder.py --folder TianChuang          fix + verify
    python _normalise_launcher_folder.py --folder TianChuang --check  verify only
"""

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from _repo import ROOT  # noqa: E402

SITE_CONF = os.path.join(ROOT, 'config', 'nginx', 'AIC-tianchuang.site')
DOMAINS_CONF = os.path.join(ROOT, 'config', 'nginx', 'domains.site')
DOC_NAME = '云端部署与运维说明.md'

# 三项目共用的 domains 文件里，AIC 段的边界标记（不猜块边界）
SEG_BEGIN = '# ============================== 天窗智巡 AIC =============================='
SEG_END = '# ============================== 冰雪文旅 ICE_Travel =============================='

# The folder ships exactly these files. Anything else is a finding, which
# is how a stray credential file would be caught before it is handed over.
EXPECTED_FILES = ['启动天窗智巡.bat', '在桌面创建快捷方式.bat', 'launcher.ps1', 'readme.txt']

# Nothing local. Checked against the .ps1 body as a hard judgement, because this
# is the requirement that cannot be verified by looking at the launcher working.
FORBIDDEN_LOCAL = [
    '127.0.0.1', 'localhost', '.venv', 'node_modules',
    'backend-python', 'backend-java', 'frontend', '.run',
    'C:\\', 'C:/',
]


def read_bytes(path):
    with open(path, 'rb') as handle:
        return handle.read()


def code_only(text):
    """Drop whole-line comments, keep everything else.

    A judgement about what a script *does* must not be answered by what it
    *says*. The first version searched the raw body for `chcp` and flagged
    `launcher.ps1 -- because a comment there explains why chcp is NOT used.
    That is the dangerous direction of a false positive: an exemption stated in
    prose would look like a violation, and the natural reaction is to delete
    the check.

    Only full-line comments are dropped (`^\\s*#`). Stripping trailing comments
    would need a real tokenizer, and getting it wrong there could hide live code
    behind a `#` inside a string -- the opposite, also bad, direction.
    """
    return '\n'.join(line for line in text.splitlines()
                     if not line.lstrip().startswith('#'))


def self_test():
    """Both directions for the comment exemption.

    Returns (ok, messages). If the exemption is ever widened (e.g. to trailing
    comments) this fires, because 'the check stopped biting' and 'the check
    found nothing' must not look the same.
    """
    messages = []
    cases = [
        ('chcp 65001 > $null', True, 'real invocation in code'),
        ('    chcp.com 65001', True, 'real invocation, indented'),
        ('# 不要在这里写 chcp', False, 'the word only appears in a comment'),
        ('    # chcp 65001', False, 'commented-out invocation'),
    ]
    for text, expected, why in cases:
        got = 'chcp' in code_only(text)
        if got != expected:
            return False, ['chcp detector is %s on %r (%s); expected found=%s'
                           % ('over-broad' if got else 'dead', text, why, expected)]
    messages.append('chcp detector: bites live invocations, ignores comments (4/4)')
    return True, messages


def p(*parts):
    return os.path.join(*parts)


def check_bytes(path, ascii_only, want_bom):
    """Byte-level facts: encoding, BOM, line endings."""
    raw = read_bytes(path)
    problems = []
    has_bom = raw[:3] == b'\xef\xbb\xbf'
    if want_bom and not has_bom:
        problems.append('missing UTF-8 BOM')
    if (not want_bom) and has_bom:
        problems.append('has a BOM but must not')
    if ascii_only:
        bad = sum(1 for b in raw if b > 127)
        if bad:
            problems.append('%d non-ASCII byte(s) -- cmd.exe would mojibake this' % bad)
    lf_only = raw.count(b'\n') - raw.count(b'\r\n')
    if lf_only:
        problems.append('%d LF-only line ending(s)' % lf_only)
    return problems, raw


def normalise(path, ascii_only, want_bom):
    """Rewrite line endings (and BOM) to the required form. Returns True if changed."""
    raw = read_bytes(path)
    if ascii_only:
        text = raw.decode('ascii', errors='strict')
    else:
        text = raw.decode('utf-8-sig')
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')
    data = text.encode('ascii' if ascii_only else 'utf-8')
    if want_bom:
        data = b'\xef\xbb\xbf' + data
    if data == raw:
        return False
    with open(path, 'wb') as handle:
        handle.write(data)
    return True


def parse_check(path):
    """Ask the PowerShell parser. Returns (ok, detail)."""
    script = (
        "$t=$null;$e=$null;"
        "[System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$t,[ref]$e)|Out-Null;"
        "if($e.Count -gt 0){$e|ForEach-Object{$_.Extent.StartLineNumber.ToString()+':'+$_.ErrorId};exit 1};"
        "exit 0" % path.replace("'", "''")
    )
    for exe in ('powershell.exe', 'pwsh.exe'):
        try:
            done = subprocess.run([exe, '-NoProfile', '-Command', script],
                                  capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0:
            return True, 'parsed by %s' % exe
        return False, (done.stdout or '').strip() or 'parse errors'
    return False, 'no PowerShell interpreter found (cannot verify)'


def _strip_comments(text):
    return '\n'.join(l for l in text.splitlines() if not l.lstrip().startswith('#'))


def inner_listen_port():
    """内层站点块的监听端口 —— 只用于**负向**判据（交付物不许指向它）。"""
    if not os.path.isfile(SITE_CONF):
        return None
    text = _strip_comments(open(SITE_CONF, encoding='utf-8', errors='ignore').read())
    ports = re.findall(r'^\s*listen\s+(?:\[::\]:)?(\d+)', text, re.M)
    return ports[0] if ports else None


def public_entry():
    """公网入口 (host, port) —— 从共用 domains 文件的 AIC 段读，别猜。

    取 443 那条 listen（它带 ssl）；server_name 即主机名。
    段内还会有 `listen 80`（http→https 的 301 块），所以不能取“第一条 listen”。
    """
    if not os.path.isfile(DOMAINS_CONF):
        return None
    s = open(DOMAINS_CONF, encoding='utf-8', errors='ignore').read()
    if SEG_BEGIN not in s or SEG_END not in s:
        return None
    seg = s[s.index(SEG_BEGIN):s.index(SEG_END, s.index(SEG_BEGIN))]
    seg = _strip_comments(seg)
    hosts = re.findall(r'^\s*server_name\s+([^;\s]+)\s*;', seg, re.M)
    if not hosts:
        return None
    listens = re.findall(r'^\s*listen\s+([^;]+);', seg, re.M)
    port = None
    for item in listens:
        m = re.search(r'(\d{2,5})', item)
        if m and 'ssl' in item:
            port = m.group(1)
            break
    if port is None and listens:
        m = re.search(r'(\d{2,5})', listens[0])
        port = m.group(1) if m else None
    if port is None:
        return None
    return hosts[0], port


def doc_search(host, port):
    """文档里有没有这个地址。公网 https 入口写成 `https://host/`（无显式端口），
    所以两种写法都认 —— 只认 `host:port` 会把正确文档判成"不一致"。"""
    docs = os.path.join(ROOT, 'docs')
    if not os.path.isdir(docs):
        return None
    forms = ('%s:%s' % (host, port), 'https://%s/' % host, 'http://%s:443/' % host)
    for name in sorted(os.listdir(docs)):
        if name == DOC_NAME or name.endswith(DOC_NAME):
            text = open(p(docs, name), encoding='utf-8', errors='ignore').read()
            if any(f in text for f in forms):
                return name
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--folder', default=p(ROOT, 'TianChuang'))
    parser.add_argument('--check', action='store_true', help='verify only, do not rewrite')
    args = parser.parse_args()

    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        print('FAIL: not a directory: %s' % args.folder)
        return 2

    findings = []
    notes = []

    # ---- 0. prove the judgements still have teeth --------------------------
    ok, messages = self_test()
    for message in messages:
        print('OK   self-test: %s' % message)
    if not ok:
        for message in messages:
            print('FAIL self-test: %s' % message)
        print('EXIT 2 -- cannot measure. This is NOT a clean result.')
        return 2

    # ---- 1. inventory ------------------------------------------------------
    present = sorted(os.listdir(folder))
    for name in present:
        if name not in EXPECTED_FILES:
            findings.append('unexpected file in the delivery folder: %s' % name)
    for name in EXPECTED_FILES:
        if name not in present:
            findings.append('missing expected file: %s' % name)

    # ---- 2. byte-level normalise + re-verify -------------------------------
    plan = [
        ('启动天窗智巡.bat', True, False, 'pure ASCII + CRLF, no BOM'),
        ('在桌面创建快捷方式.bat', True, False, 'pure ASCII + CRLF, no BOM'),
        ('launcher.ps1', False, True, 'UTF-8 with BOM + CRLF'),
        ('readme.txt', False, True, 'UTF-8 with BOM + CRLF'),
    ]
    for name, ascii_only, want_bom, why in plan:
        path = p(folder, name)
        if not os.path.isfile(path):
            continue
        if not args.check:
            try:
                changed = normalise(path, ascii_only, want_bom)
            except UnicodeDecodeError as exc:
                findings.append('%s: cannot normalise -- %s' % (name, exc))
                continue
            if changed:
                notes.append('%s: rewritten to %s' % (name, why))
        # re-read from disk: "fixed it" is not evidence that it is fixed
        problems, raw = check_bytes(path, ascii_only, want_bom)
        for problem in problems:
            findings.append('%s: %s' % (name, problem))
        notes.append('%s: %d bytes; %s OK' % (name, len(raw), why))

    # ---- 3. the launcher must not reach for anything local -----------------
    launcher = p(folder, 'launcher.ps1')
    body = ''
    if os.path.isfile(launcher):
        raw_body = open(launcher, encoding='utf-8-sig', errors='ignore').read()
        body = code_only(raw_body)
        for needle in FORBIDDEN_LOCAL:
            if needle in body:
                findings.append('launcher.ps1 references something local: %r' % needle)
        if 'chcp' in body:
            findings.append('launcher.ps1 sets chcp; repo convention is to leave '
                            'the console code page alone')

    # ---- 4. cross-reference: is this folder pointed at the real cloud? -----
    pub = public_entry()
    inner = inner_listen_port()
    if pub is None:
        findings.append('cannot read the public entry (server_name + 443 ssl) from '
                        'config/nginx/domains.site -- the snapshot is absent or the AIC '
                        'segment / its boundary markers moved')
    else:
        pub_host, pub_port = pub
        notes.append('public entry per config/nginx/domains.site: %s:%s' % (pub_host, pub_port))
        m_port = re.search(r"\$SitePort\s*=\s*'?(\d+)'?", body)
        if not m_port:
            findings.append('launcher.ps1 has no $SitePort assignment')
        elif m_port.group(1) != pub_port:
            findings.append('PORT MISMATCH: launcher says %s, public entry is %s'
                            % (m_port.group(1), pub_port))
        else:
            notes.append('port %s matches the public entry' % pub_port)
        # 负向判据：交付物**不许**指向内层监听端口（它只绑回环，收件人够不着）
        if inner and m_port and m_port.group(1) == inner:
            findings.append('launcher points at %s, which is the INNER listen port '
                            '(loopback only) -- a recipient could never reach it'
                            % inner)
        m_host = re.search(r"\$SiteHost\s*=\s*'([^']+)'", body)
        if not m_host:
            findings.append('launcher.ps1 has no $SiteHost assignment')
        elif m_host.group(1) != pub_host:
            findings.append('HOST MISMATCH: launcher says %s, public entry is %s'
                            % (m_host.group(1), pub_host))
        else:
            where = doc_search(pub_host, pub_port)
            if where:
                notes.append('host %s:%s is documented in docs/%s'
                             % (pub_host, pub_port, where))
            else:
                findings.append('host %s:%s does not appear in docs/%s -- '
                                'the launcher and the operator doc disagree'
                                % (pub_host, pub_port, DOC_NAME))

            # Within the package: the address the recipient is *told* must be the
            # address the launcher uses. Two copies of one fact that are each
            # edited independently is how a hand-off ships a dead address.
            readme = p(folder, 'readme.txt')
            if os.path.isfile(readme):
                text = open(readme, encoding='utf-8-sig', errors='ignore').read()
                forms = ['%s:%s' % (pub_host, pub_port), 'https://%s/' % pub_host]
                if any(f in text for f in forms):
                    notes.append('readme.txt documents the same entry address')
                else:
                    findings.append('readme.txt does not mention the entry address '
                                    '(%s) -- the package documents a different '
                                    'address than it uses' % ' or '.join(forms))

    # ---- 5. parse check ----------------------------------------------------
    if os.path.isfile(launcher):
        ok, detail = parse_check(launcher)
        if ok:
            notes.append('launcher.ps1: %s' % detail)
        else:
            findings.append('launcher.ps1 failed the PowerShell parser: %s' % detail)

    # ---- report ------------------------------------------------------------
    for note in notes:
        print('OK   %s' % note)
    for finding in findings:
        print('FAIL %s' % finding)
    print('SUMMARY folder=%s files=%d findings=%d mode=%s'
          % (os.path.basename(folder), len(present), len(findings),
             'check-only' if args.check else 'normalise+verify'))
    return 1 if findings else 0


if __name__ == '__main__':
    raise SystemExit(main())
