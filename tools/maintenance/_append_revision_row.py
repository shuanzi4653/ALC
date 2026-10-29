"""向 `changelog/*.md` 的「文档修订记录」表追加一行。

**为什么需要它**：修订记录的每一行都可能长达数千字符（整段变更摘要写成一行）。
用文本替换去插入这种行，`old_string` 要精确复制上一条**极长**的行尾，
一旦有一个字符不对就失败，而且失败信息很难读。
这里只做**结构性**插入：找到小节标题 → 找到紧随其后的表格 → 在表格最后一行之后插入。

用法：
    python tools/maintenance/_append_revision_row.py \
        --file changelog/ISSUES.md \
        --section "## 文档修订记录" \
        --row-file .run/row_issues.md

    # 只检查会插到哪里，不写回
    ... --check
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def insert_row(lines: list[str], section: str, row: str) -> int:
    """把 `row` 插到 `section` 下方表格的最后一行之后，返回插入位置。"""
    header = None
    for index, line in enumerate(lines):
        if line.strip() == section.strip():
            header = index
            break
    if header is None:
        raise SystemExit(f'未找到小节标题：{section}')

    # 跳过标题与其后的空行，找到表格首行
    cursor = header + 1
    while cursor < len(lines) and not lines[cursor].startswith('|'):
        if lines[cursor].strip() and not lines[cursor].startswith('#'):
            # 标题与表格之间出现了非空非表格内容 —— 多半说明认错了位置
            pass
        cursor += 1
    if cursor >= len(lines):
        raise SystemExit('小节之后没有找到表格')

    # 走到表格末行
    end = cursor
    while end + 1 < len(lines) and lines[end + 1].startswith('|'):
        end += 1

    lines.insert(end + 1, row.rstrip('\n'))
    return end + 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', required=True, help='目标文件（相对仓库根）')
    parser.add_argument('--section', required=True, help='小节标题，如 "## 文档修订记录"')
    parser.add_argument('--row-file', required=True, help='含单行 Markdown 表格行的文件')
    parser.add_argument('--check', action='store_true', help='只报告插入位置，不写回')
    args = parser.parse_args()

    target = ROOT / args.file
    row = (ROOT / args.row_file).read_text(encoding='utf-8').strip()
    if '\n' in row:
        raise SystemExit('row-file 必须是**单行**；多行会让表格断裂')
    if not row.startswith('|') or not row.endswith('|'):
        raise SystemExit('row-file 必须以 | 开头并以 | 结尾')

    lines = target.read_text(encoding='utf-8').split('\n')
    before = len(lines)
    position = insert_row(lines, args.section, row)
    print(f'{args.file}  第 {position + 1} 行（1-based） 行数 {before} → {len(lines)}')
    print('新行前 12 字符:', row[:12], '…', '|  长度', len(row))

    if args.check:
        print('（--check 模式，未写回）')
        return 0

    target.write_text('\n'.join(lines), encoding='utf-8')
    print('已写回')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
