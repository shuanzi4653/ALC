"""统计本机 traces 的 token 消耗（全量 + ALC 项目）。

口径（必须写在报告里，否则数字会被误读）：
  · 数据源 = `C:\\Users\\12921\\.workbuddy\\traces\\<id>\\trace_*.json` 里的 `trace.modelInfo`
    （`totalInputTokens` / `totalOutputTokens` / `totalCachedTokens` / `callCount`）；
  · 只统计**还留在这台机器上的** trace —— 清理过的会话不在其中，所以是**下界**；
  · 「ALC」按**文件全文是否出现 `Desktop/ALC` 或 `Desktop\\ALC`** 判定：
    会漏掉一两句问答里没提路径的会话，也可能把别的项目里顺口提到 ALC 的会话算进来；
  · `totalInputTokens` 含缓存命中；真正按"未命中缓存"计费的是 `totalInputTokens - totalCachedTokens`。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(r'C:\Users\12921\.workbuddy\traces')
ALC_MARKERS = ('Desktop/ALC', 'Desktop\\ALC')


def read_meta(path: pathlib.Path) -> dict | None:
    # **必须读全文**：`modelInfo` 在 `trace` 块里，但 ALC 路径只出现在后面的 `spans` 里。
    # 第一版只读前 60 KB，结果 612 个文件报"读不到 modelInfo"（其实是早期版本**没记** token，
    # `totalTokens: 0`），而 ALC 只认出 9 个（路径在 60 KB 之外）。两个错都出在"只读头部"。
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    head = text
    match = re.search(r'"modelInfo"\s*:\s*\{[^{}]*\}', head)
    if not match:
        return None
    block = match.group(0)

    def grab(key: str) -> int:
        hit = re.search(r'"%s"\s*:\s*(\d+)' % key, block)
        return int(hit.group(1)) if hit else 0

    return {
        'in': grab('totalInputTokens'),
        'out': grab('totalOutputTokens'),
        'cached': grab('totalCachedTokens'),
        'calls': grab('callCount'),
        'has_alc': any(m in head for m in ALC_MARKERS),
    }


def main() -> int:
    files = sorted(ROOT.rglob('trace_*.json'))
    if not files:
        print('找不到 trace 文件', file=sys.stderr)
        return 2
    total = {'in': 0, 'out': 0, 'cached': 0, 'calls': 0, 'n': 0}
    alc = {'in': 0, 'out': 0, 'cached': 0, 'calls': 0, 'n': 0}
    skipped = 0
    for index, path in enumerate(files, 1):
        meta = read_meta(path)
        if meta is None:
            skipped += 1
            continue
        bucket = alc if meta['has_alc'] else total
        for key in ('in', 'out', 'cached', 'calls'):
            bucket[key] += meta[key]
            if bucket is alc:
                total[key] += meta[key]
        bucket['n'] += 1
        if bucket is alc:
            total['n'] += 1
        if index % 500 == 0:
            print('  …%d/%d' % (index, len(files)), flush=True)

    def show(name: str, b: dict) -> None:
        billed = b['in'] - b['cached']
        print('%-10s trace %4d  calls %5d  in %13s  out %10s  cached %13s' %
              (name, b['n'], b['calls'], format(b['in'], ','), format(b['out'], ','),
               format(b['cached'], ',')))
        print('%-10s                             合计 %13s   计费输入 %10s'
              % ('', format(b['in'] + b['out'], ','), format(billed, ',')))

    print('trace 文件总数 %d（读不到 modelInfo 的 %d）\n' % (len(files), skipped))
    show('全量', total)
    print()
    show('其中 ALC', alc)
    if total['in'] + total['out']:
        share = (alc['in'] + alc['out']) / (total['in'] + total['out']) * 100
        print('\nALC 占本机总 token 的 %.1f%%' % share)
    return 0


if __name__ == '__main__':
    sys.exit(main())
