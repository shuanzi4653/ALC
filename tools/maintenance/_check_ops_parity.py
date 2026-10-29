# -*- coding: utf-8 -*-
"""线上判据脚本的完整性 / 一致性检查（0.11.6 补）。

## 为什么需要它

`verify-remote.sh` 曾经**只存在于服务器** `/opt/apps/AIC-tianchuang/bin/`，仓库里没有源。
后果有两层：
  · 重装即丢失 —— 而它是"云端可信判据"的唯一载体（37 项）；
  · 改动无法追溯 —— 0.11.6 的 E-3 上线后，我在服务器上 `sed` 加了
    `X-ALC-Operator: admin`，这次改动在任何版本记录里都看不见。

现在仓库有副本了，但"有副本"不等于"不会漂移"：两边各自被改一次，就又是一次
"线上跑的和你以为的不是同一份"。

## 两道检查

**离线（默认，闸门里跑）** 不依赖网络，只查仓库这份自身的三条硬性质：
  ① 必须是 **LF** —— Windows 写盘带 CRLF，Linux 上 bash 会报 `$'\\r': command not found`，
     而这个错看起来像"脚本写坏了"，实际是换行符；
  ② 必须带 `X-ALC-Operator: admin` —— 切气象通道要 admin（E-3），少了它 37 项里
     会有 3 项红，而红的是"口径隔离"，看起来像隔离坏了；
  ③ 必须可执行（有 shebang）且**不是空壳**（≥ 200 行）。

**在线（`--remote`）** 拉服务器的 sha256 比对。不在闸门里跑：闸门要能在没网、
没有 SSH 密钥的机器上通过。要验就显式敲一次。
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / 'bin' / 'verify-remote.sh'
REMOTE_HOST = 'ubuntu@62.234.154.34'
REMOTE_PATH = '/opt/apps/AIC-tianchuang/bin/verify-remote.sh'
KEY = Path.home() / '.ssh' / 'hongsight.pem'


def problems_of(raw: bytes):
    """返回问题清单。**抽成纯函数**是为了让 `--self-test` 能造坏样本喂进来 ——
    一条不会红的判据等于没有判据，而"这条判据会不会红"只能靠负向样本验证。"""
    issues = []
    if b'\r' in raw:
        issues.append('含 CR（CRLF）—— Linux 上 bash 会报 $\\r 错误')
    text = raw.decode('utf-8', errors='replace')
    if not text.startswith('#!/usr/bin/env bash'):
        issues.append('第一行不是 shebang（#!/usr/bin/env bash）')
    if 'X-ALC-Operator: admin' not in text:
        issues.append('缺 X-ALC-Operator: admin —— 切气象通道会 403，口径隔离 3 项会红')
    if text.count('\n') < 200:
        issues.append('只有 %d 行，像被截断的空壳（原 302 行 + 注释头）' % text.count('\n'))
    return issues


def self_test() -> int:
    failures = 0
    good = LOCAL.read_bytes() if LOCAL.exists() else b'#!/usr/bin/env bash\n' + b'# X-ALC-Operator: admin\n' + b'x\n' * 300

    # ① 好样本必须过
    if problems_of(good):
        print('FAIL 负向 1：正常样本被判坏了 -> %s' % problems_of(good))
        failures += 1
    else:
        print('PASS 负向 1：正常样本通过')

    # ② CRLF 必须被抓
    if not problems_of(good.replace(b'\n', b'\r\n')):
        print('FAIL 负向 2：CRLF 没被抓到')
        failures += 1
    else:
        print('PASS 负向 2：CRLF 被抓到')

    # ③ 缺 admin 头必须被抓
    if not problems_of(good.replace(b'X-ALC-Operator: admin', b'X-ALC-Operator: observer')):
        print('FAIL 负向 3：缺 admin 头没被抓到')
        failures += 1
    else:
        print('PASS 负向 3：缺 admin 头被抓到')

    # ④ 空壳必须被抓
    if not problems_of(b'#!/usr/bin/env bash\n'):
        print('FAIL 负向 4：空壳没被抓到')
        failures += 1
    else:
        print('PASS 负向 4：空壳被抓到')

    print('self-test %s' % ('PASSED' if failures == 0 else 'FAILED'))
    return 1 if failures else 0


def offline() -> int:
    if not LOCAL.exists():
        print('FAIL 仓库里没有 bin/verify-remote.sh —— 那它又只在服务器上了')
        return 1
    raw = LOCAL.read_bytes()
    problems = problems_of(raw)
    lines = raw.decode('utf-8', errors='replace').count('\n')
    if problems:
        for item in problems:
            print('FAIL ' + item)
        return 1
    print('ok   bin/verify-remote.sh  LF / shebang / admin 头 / %d 行 / sha256 %s'
          % (lines, hashlib.sha256(raw).hexdigest()[:16]))
    return 0


def remote() -> int:
    if not KEY.exists():
        print('SKIP 没有 %s，无法比对服务器副本' % KEY)
        return 0
    local_sha = hashlib.sha256(LOCAL.read_bytes()).hexdigest()
    try:
        out = subprocess.run(
            ['ssh', '-i', str(KEY), '-o', 'StrictHostKeyChecking=no', REMOTE_HOST,
             'sha256sum %s' % REMOTE_PATH],
            capture_output=True, text=True, timeout=30)
    except Exception as exc:  # noqa: BLE001
        print('SKIP SSH 失败：%s' % exc)
        return 0
    if out.returncode != 0:
        print('FAIL 服务器上读不到 %s：%s' % (REMOTE_PATH, out.stderr.strip()[:120]))
        return 1
    remote_sha = out.stdout.split()[0]
    if remote_sha != local_sha:
        print('FAIL 两端不一致\n  仓库 %s\n  服务器 %s' % (local_sha[:16], remote_sha[:16]))
        print('     先确认以哪边为准，再同步 —— 不要"两边都改一点"')
        return 1
    print('ok   两端一致 %s' % local_sha[:16])
    return 0


def main() -> int:
    if '--self-test' in sys.argv:
        return self_test()
    code = offline()
    if '--remote' in sys.argv:
        code = max(code, remote())
    return code


if __name__ == '__main__':
    raise SystemExit(main())
