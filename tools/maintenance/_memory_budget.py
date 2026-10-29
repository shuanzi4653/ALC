"""Report per-section character cost of .workbuddy/memory/MEMORY.md.

Eyeballing Chinese character counts is unreliable -- a line that "looks short" can
be 90 chars because CJK glyphs and the backtick-quoted identifiers both count. This
prints the real numbers per section and per bullet, so a trim decision is made on
measurement instead of impression.

    _memory_budget.py                # per-section totals
    _memory_budget.py --bullets      # per-section totals plus every bullet's cost
"""

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from _repo import ROOT  # noqa: E402
# The cap is *read*, never restated. This file used to hardcode 3000 while the
# real cap was already 6000 -- a second copy of a number whose whole job is to
# be agreed on. `_write_memory.CURATED_LIMIT` is the single source.
from _write_memory import CURATED_LIMIT as LIMIT  # noqa: E402

PATH = os.path.join(ROOT, '.workbuddy', 'memory', 'MEMORY.md')


def main():
    show_bullets = '--bullets' in sys.argv
    with io.open(PATH, encoding='utf-8') as handle:
        text = handle.read()
    total = len(text)
    print('total %d chars, limit %d, over by %d'
          % (total, LIMIT, max(0, total - LIMIT)))
    print()

    section = '(preamble)'
    counts = {section: 0}
    bullets = []
    for line in text.splitlines(True):
        if line.startswith('## '):
            section = line.strip()
            counts[section] = 0
        counts[section] += len(line)
        if show_bullets and line.strip():
            bullets.append((section, len(line), line.strip()[:64]))

    for name, size in sorted(counts.items(), key=lambda kv: -kv[1]):
        print('%6d  %s' % (size, name))

    if show_bullets:
        print()
        print('bullets over 100 chars (the trim candidates):')
        for section, size, preview in sorted(bullets, key=lambda b: -b[1]):
            if size > 100:
                print('%6d  %-38s %s' % (size, section[:38], preview))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
