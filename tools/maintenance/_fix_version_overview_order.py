"""把 `changelog/CHANGELOG.md` §版本总览 的表格行按版本号重新排序。

为什么需要它：版本总览的每一行都极长（数千字符），靠文本匹配去"交换两行"
既读不清也容易改错。这里只按行号与行首模式定位，不动行内容。

发现的缺陷（0.9.24 定稿时）：0.9.23 行被插到了 0.9.22 行**之前**，
表格于是不再按版本号递增 —— 这与 `docs/NAMING.md` §7 的
「改版本号时要复核对照表」是同一类问题：表格的**顺序**也是一种对照。

用法：
    backend-python/.venv/Scripts/python.exe tools/maintenance/_fix_version_overview_order.py --check
    backend-python/.venv/Scripts/python.exe tools/maintenance/_fix_version_overview_order.py --write
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHANGELOG = ROOT / 'changelog' / 'CHANGELOG.md'

# 表格行：| **0.9.24（Beta）** | ... |
ROW = re.compile(r'^\| \*\*0\.9\.(\d+)（Beta）\*\*')


def _load() -> list[str]:
    return CHANGELOG.read_text(encoding='utf-8').split('\n')


def _span(lines: list[str]) -> tuple[int, int]:
    """版本总览的表格行区间 [start, end)。"""
    start = None
    for index, line in enumerate(lines):
        if ROW.match(line):
            start = index
            break
    if start is None:
        raise SystemExit('未找到版本总览的表格行')
    end = start
    while end < len(lines) and ROW.match(lines[end]):
        end += 1
    return start, end


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='写回文件')
    parser.add_argument('--check', action='store_true', help='只检查、不写回（默认行为）')
    args = parser.parse_args()

    lines = _load()
    start, end = _span(lines)
    rows = lines[start:end]

    versions = [int(ROW.match(row).group(1)) for row in rows]  # type: ignore[union-attr]
    print(f'表格行区间  : [{start}, {end})  共 {len(rows)} 行')
    print(f'当前顺序    : {versions}')

    expected = sorted(versions)
    if versions == expected:
        print('顺序已正确（按版本号递增），无需改动')
        return 0

    # 逐行搬运，保持原文不变
    order = sorted(range(len(rows)), key=lambda i: versions[i])
    lines[start:end] = [rows[i] for i in order]

    moved = [f'0.9.{versions[i]}' for i in order if i != order.index(i)]
    print(f'排序后      : {[versions[i] for i in order]}')
    print(f'受影响的行  : {sorted(set(moved))}')

    if args.write:
        CHANGELOG.write_text('\n'.join(lines), encoding='utf-8')
        print('已写回 changelog/CHANGELOG.md')
    else:
        print('（--check 模式，未写回）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
