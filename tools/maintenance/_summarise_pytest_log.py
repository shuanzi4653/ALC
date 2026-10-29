"""从 `tools/runners/_run_pytest.py -q -q` 的日志里**数出**通过 / 跳过 / 失败。

**为什么需要它**：那个 runner 用 `-q -q`（甚至 `-q -q -q`），
**不打印 pytest 的汇总行**，所以日志里没有 "N passed" 可抄。
历史上几轮都是"按 `--collect-only` 与套件自身的计数对齐"——
也就是说数字是**数出来的**，而"数"如果靠人眼点数就会错。

这个脚本把"数"变成可复现的：逐行扫描进度标记
（`.` 通过、`s` 跳过、`F` 失败、`E` 错误、`x` xfail、`X` xpass），
并把总数与 `--collect-only` 的采集数**交叉核对** —— 两者不一致就报错，
因为那说明日志被截断或进度行格式变了，此时**任何数字都不能引用**。

用法：
    python tools/maintenance/_summarise_pytest_log.py .run/gate_pytest_final_0924.txt
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / 'backend-python' / '.venv' / 'Scripts' / 'python.exe'

MARKERS = {'.': 'passed', 's': 'skipped', 'F': 'failed', 'E': 'error', 'x': 'xfail', 'X': 'xpass'}
# 进度行形如 `....s...F..   [ 58%]`，或末尾没有百分比
PROGRESS = re.compile(r'^([.sFExX]+)(?:\s+\[\s*\d+%\])?\s*$')


def count_marks(text: str) -> dict[str, int]:
    tally = {name: 0 for name in MARKERS.values()}
    for line in text.split('\n'):
        match = PROGRESS.match(line.strip())
        if not match:
            continue
        for char in match.group(1):
            tally[MARKERS[char]] += 1
    return tally


def collected_count() -> int:
    out = subprocess.run(
        [str(PYTHON), '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider'],
        cwd=ROOT / 'backend-python', capture_output=True, text=True, encoding='utf-8', errors='replace',
    ).stdout
    match = re.search(r'(\d+) tests? collected', out)
    if not match:
        raise SystemExit('未能从 --collect-only 解析出采集数')
    return int(match.group(1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', help='runner 写出的日志文件')
    parser.add_argument('--expect', type=int, default=None, help='期望总数（默认用 --collect-only 的实际值）')
    args = parser.parse_args()

    text = (ROOT / args.log).read_text(encoding='utf-8', errors='replace')
    tally = count_marks(text)
    counted = sum(tally.values())
    collected = collected_count()
    expected = args.expect if args.expect is not None else collected

    print(f'日志          : {args.log}')
    for name, value in tally.items():
        if value:
            print(f'  {name:<8}: {value}')
    print(f'数出的用例数  : {counted}')
    print(f'采集到的用例数: {collected}')
    print(f'交叉核对      : {"一致" if counted == collected else "不一致 —— 日志可能被截断，数字不可引用"}')

    if counted != collected:
        return 1

    verdict = 'RC 0' if tally['failed'] == 0 and tally['error'] == 0 else '有失败'
    print(f'结论          : {collected} collected / {tally["passed"]} passed / '
          f'{tally["skipped"]} skipped / {tally["failed"]} failed（{verdict}）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
