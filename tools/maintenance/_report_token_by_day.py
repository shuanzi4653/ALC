"""按**日期**统计 token 消耗 —— 用户说「今天用了 1e」，而按"是否含 ALC 路径"筛选只得 2.76 亿。

两个口径的差别在哪：
  · 「含 ALC 路径」= 这一轮**碰过这个项目的文件**；
  · 「今天用了多少」= 今天**所有**调用，含那些没触发工具、没出现路径的纯问答轮次。
    后者才是账单口径 —— 而它恰好被前一种筛选整批漏掉（纯问答的 span 里没有文件路径）。

所以这个脚本不筛项目，只按 `trace.startedAt` 的本地日期分组。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import defaultdict

ROOT = pathlib.Path(r'C:\Users\12921\.workbuddy\traces')


def read_meta(path: pathlib.Path) -> dict | None:
    try:
        with path.open('r', encoding='utf-8', errors='replace') as fh:
            head = fh.read(120000)
    except OSError:
        return None
    started = re.search(r'"startedAt"\s*:\s*"([^"]+)"', head)
    match = re.search(r'"modelInfo"\s*:\s*\{[^{}]*\}', head)
    if not started:
        return None
    meta = {'startedAt': started.group(1), 'in': 0, 'out': 0, 'cached': 0, 'calls': 0}
    if not match:
        return meta
    block = match.group(0)
    for key, field in (('in', 'totalInputTokens'), ('out', 'totalOutputTokens'),
                       ('cached', 'totalCachedTokens'), ('calls', 'callCount')):
        hit = re.search(r'"%s"\s*:\s*(\d+)' % field, block)
        meta[key] = int(hit.group(1)) if hit else 0
    return meta


def main() -> int:
    files = sorted(ROOT.rglob('trace_*.json'))
    per_day = defaultdict(lambda: {'trace': 0, 'with_token': 0, 'in': 0, 'out': 0, 'cached': 0, 'calls': 0})
    for path in files:
        meta = read_meta(path)
        if not meta:
            continue
        # startedAt 是 ISO8601 UTC；转本地日期（+08:00）
        try:
            import datetime as dt
            stamp = dt.datetime.fromisoformat(meta['startedAt'].replace('Z', '+00:00'))
            day = (stamp + dt.timedelta(hours=8)).date().isoformat()
        except ValueError:
            continue
        bucket = per_day[day]
        bucket['trace'] += 1
        if meta['calls'] or meta['in']:
            bucket['with_token'] += 1
        for key in ('in', 'out', 'cached', 'calls'):
            bucket[key] += meta[key]

    print('%-12s %5s %5s %14s %10s %12s %7s' %
          ('日期', 'trace', '有记录', 'input', 'output', 'cached', '调用'))
    total = {'in': 0, 'out': 0}
    for day in sorted(per_day):
        b = per_day[day]
        total['in'] += b['in']
        total['out'] += b['out']
        print('%-12s %5d %5d %14s %10s %12s %7d' %
              (day, b['trace'], b['with_token'], format(b['in'], ','),
               format(b['out'], ','), format(b['cached'], ','), b['calls']))
    print('%-12s %5s %5s %14s %10s' % ('合计', '', '', format(total['in'], ','),
                                       format(total['out'], ',')))
    print('grand total = %s tokens' % format(total['in'] + total['out'], ','))
    return 0


if __name__ == '__main__':
    sys.exit(main())
