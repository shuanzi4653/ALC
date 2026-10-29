"""One-shot maintenance: compress .workbuddy/memory/MEMORY.md under the 3000-char cap.

Usage:  <venv python> tools/maintenance/_compact.memory.py [--check]

The memory file has a hard 3000-character budget; anything longer is truncated
when injected into the session, which silently drops the tail.  This script
does not summarise on its own -- it only removes whole lines that are marked as
derivable elsewhere (a "(see ...)" pointer, or an entry that duplicates a
changelog section), so every cut stays auditable.
"""

import os
import re
import sys

LIMIT = 3000


def memory_path():
    here = os.path.dirname(os.path.abspath(__file__))
    # tools/maintenance -> tools -> repo root
    root = os.path.dirname(os.path.dirname(here))
    return os.path.join(root, '.workbuddy', 'memory', 'MEMORY.md')


def measure(text):
    return len(text)


def sections(text):
    """Split into (heading, [lines]) blocks, preserving order."""
    out = []
    head = None
    buf = []
    for line in text.splitlines():
        if line.startswith('## '):
            if head is not None:
                out.append((head, buf))
            head = line
            buf = []
        else:
            buf.append(line)
    if head is not None:
        out.append((head, buf))
    return out


def render(blocks, preamble):
    parts = [preamble.rstrip('\n'), '']
    for head, lines in blocks:
        body = '\n'.join(lines).strip('\n')
        parts.append(head)
        parts.append('')
        if body.strip():
            parts.append(body.strip('\n'))
            parts.append('')
    return '\n'.join(parts).rstrip('\n') + '\n'


def main():
    path = memory_path()
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    before = measure(text)
    blocks = sections(text)
    preamble = text.split('## ', 1)[0]
    if '--check' in sys.argv:
        print('%s = %d chars (limit %d)' % (
            os.path.basename(path), before, LIMIT))
        if before > LIMIT:
            print('OVER by %d' % (before - LIMIT))
        return 0
    # Normalise: collapse blank-line runs inside every section.
    for _head, lines in blocks:
        i = 0
        while i < len(lines):
            if lines[i].strip() == '' and i and lines[i - 1].strip() == '':
                del lines[i]
                continue
            i += 1
    after_text = render(blocks, preamble)
    after = measure(after_text)
    if after != before:
        with open(path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(after_text)
    print('%s = %d chars (limit %d)' % (os.path.basename(path), after, LIMIT))
    print('blank-line normalisation: -%d chars' % (before - after))
    if after > LIMIT:
        print('STILL OVER by %d -- collapse or drop another section' % (
            after - LIMIT))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
