"""Append a work-log entry to its OWN dated file -- never to a shared one.

Why this exists
---------------
The project memory lives in ``.workbuddy/memory/``. Two things went wrong when
entries were appended into a single long-lived file, and the user asked for both
to stop:

1. **Overwrite.** A hand-written ``Write`` to ``MEMORY.md`` replaces the whole
   file. That is how the curated notes file was truncated twice -- and neither
   truncation was noticed until the injected copy came back short, because a
   memory file has no test that would fail when its own tail disappears.
2. **Mixing.** A day's log, the curated long-term notes, and one-off ad-hoc notes
   all ended up in the same file, so nobody could tell which lines were durable
   findings and which were a scratch note for a single afternoon.

The layout this enforces
------------------------
    .workbuddy/memory/
      MEMORY.md                  curated notes. Pointer index only, hard 50000 cap.
      YYYY-MM-DD.md              that day's log. Append-only, one file per day.
      notes/YYYY-MM-DD-<slot>.md ad-hoc notes, one file per *topic*, never merged.

The cap started at 3000, moved to 6000 on 2026-09-18, to 20000 on 2026-10-02, and
to 50000 on 2026-10-12 -- all four at the user's request. The causes are worth
keeping, because the third raise is the one that reads as a contradiction:

* 3000 -> 6000: the file had drifted to ~3260 chars -- over the old cap, but
  entirely in the pointer-index style the cap exists to protect (eight topic
  sections, one line per finding, all depth pushed into ``notes/``). Trimming
  would have deleted findings rather than prose, so the ceiling moved instead.
* 6000 -> 20000: the file sat at **exactly 6000/6000, zero headroom**, and a
  legitimate new finding had nowhere to go. A cap that is hit *exactly* is not
  protecting anything: it forces the next author to either drop a finding or
  quietly trim someone else's, which is precisely the loss this module exists to
  prevent.
* 20000 -> 50000: the file reached ~19600 and the trimming cost had turned into
  the problem. Every finding now lands as a one-line pointer into ``notes/``, and
  those pointers are **cross-references between findings** -- compressing one to
  fit deletes the link that lets the next reader find the depth. At this size the
  index *is* the artifact, so the ceiling moved again.

Note what did *not* change across all four raises: the file is still a pointer
index, and depth still belongs in ``notes/``. Raising the cap is not permission
to inline evidence -- a 50000-char file that restates what ``notes/`` already
holds is a worse index than a 19000-char one, because the reader has to skim
prose to find the pointers. Hitting 50000 means "open a ``notes/`` topic file",
exactly as before.

Every writer takes a **path** and opens it in append mode. Nothing here can
overwrite: ``append`` is the only write this module performs, and the target of a
``slot`` is a fresh file that fails rather than clobbers if the slot already
exists for that day.

The log is append-only; the slot files are one-shot. That asymmetry is deliberate:
a log entry is continuous with what came before, while a slot file is a titled
document, and silently appending to a titled document is how two unrelated topics
end up sharing a heading.

    _write_memory.py --log "<text>"              append to today's log
    _write_memory.py --log-file <path>           append the contents of a file
    _write_memory.py --slot <name> --text "<t>"  create notes/<date>-<name>.md
    _write_memory.py --slot <name> --file <path>
    _write_memory.py --list                      show the current layout
    _write_memory.py --check                     enforce the rules, non-zero if bad
"""

import datetime
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from _repo import ROOT  # noqa: E402

MEMORY = os.path.join(ROOT, '.workbuddy', 'memory')
NOTES = os.path.join(MEMORY, 'notes')
CURATED = os.path.join(MEMORY, 'MEMORY.md')
CURATED_LIMIT = 50000  # 3000 -> 6000 (2026-09-18) -> 20000 (2026-10-02) -> 50000 (2026-10-12)

# A slot name becomes part of a filename, so it is restricted to the characters
# that cannot escape the notes directory or confuse a shell. Anything else is a
# caller bug worth failing on rather than sanitising silently -- a name that got
# quietly rewritten is a name the next run will not find.
SLOT = re.compile(r'^[a-z0-9][a-z0-9-]{0,48}$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def today():
    """Today's date in the project's own timezone.

    ``date.today()`` reads the process clock; the log filenames are written by a
    human in local time, so an entry created just after midnight UTC must not
    land in yesterday's file.
    """
    return datetime.datetime.now().strftime('%Y-%m-%d')


def log_paths():
    """Every dated log file, oldest first."""
    if not os.path.isdir(MEMORY):
        return []
    names = [n for n in os.listdir(MEMORY)
             if n.endswith('.md') and DATE.match(n[:-3])]
    return [os.path.join(MEMORY, n) for n in sorted(names)]


def note_paths():
    if not os.path.isdir(NOTES):
        return []
    return [os.path.join(NOTES, n) for n in sorted(os.listdir(NOTES))
            if n.endswith('.md')]


def append_to(path, text):
    """The only write in this module: append, never truncate."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'a', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
    return len(text)


def write_slot(date, slot, text):
    """Create ``notes/<date>-<slot>.md``. Refuses to clobber an existing one."""
    # The date is already part of the filename, so a slot that *starts* with a
    # date produces ``2026-10-02-2026-10-02-<topic>.md`` (walked into once).
    # Strip it when it is today's -- that is unambiguous and clearly what the
    # caller meant -- but refuse a *different* date, because then the caller is
    # trying to file today's note under another day and the filename would lie.
    leading = re.match(r'^(\d{4}-\d{2}-\d{2})-(.+)$', slot)
    if leading:
        if leading.group(1) != date:
            raise SystemExit(
                'slot %r starts with %s but today is %s -- the date is added '
                'automatically; drop it from --slot, or set the date '
                'explicitly. Nothing was written.' % (slot, leading.group(1), date))
        slot = leading.group(2)
    if not SLOT.match(slot):
        raise SystemExit(
            'slot name %r is not a safe filename stem '
            '(lowercase letters, digits and dashes only)' % slot)
    if not DATE.match(date):
        raise SystemExit('date %r is not YYYY-MM-DD' % date)
    path = os.path.join(NOTES, '%s-%s.md' % (date, slot))
    if os.path.exists(path):
        # Appending here is the failure mode this module exists to prevent: two
        # unrelated topics would share one heading. Tell the caller to pick a new
        # name, and do not guess one -- a guessed name is not findable later.
        raise SystemExit(
            'slot already exists: %s\n'
            'Pick a different --slot, or read it and decide explicitly. '
            'Nothing was written.' % os.path.relpath(path, ROOT))
    os.makedirs(NOTES, exist_ok=True)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text if text.endswith('\n') else text + '\n')
    return path


def read_text(args, flag, text_flag):
    """Take the body from a file when one is given, else from a literal string.

    Multi-line text with Chinese punctuation and backticks cannot survive a shell
    round-trip on this host (the shim re-splits it), which is why a file form
    exists at all. Callers that already have the text in a variable should use
    ``--log`` and pass it through a file.
    """
    if flag in args:
        path = args[args.index(flag) + 1]
        with io.open(path, encoding='utf-8') as handle:
            return handle.read()
    if text_flag in args:
        return args[args.index(text_flag) + 1]
    raise SystemExit('nothing to write: pass %s or %s' % (flag, text_flag))


def check():
    """Enforce the layout rules. Returns a list of problems, empty when clean."""
    problems = []
    if not os.path.isdir(MEMORY):
        return ['memory directory is missing: %s' % MEMORY]
    if os.path.isdir(NOTES):
        for path in note_paths():
            stem = os.path.basename(path)[:-3]
            # Two legal shapes, both one-topic-per-file:
            #   <date>-<slot>.md   an ad-hoc note, dated at creation
            #   <slot>.md          a standing topic doc kept current in place
            parts = stem.split('-', 3)
            slot = parts[3] if (len(parts) >= 4 and DATE.match('-'.join(parts[:3]))) else stem
            if not SLOT.match(slot):
                problems.append('%s has a malformed name (want <slot>.md or '
                                '<date>-<slot>.md, lowercase/digits/dashes)' %
                                os.path.relpath(path, ROOT))
    if os.path.isfile(CURATED):
        size = len(io.open(CURATED, encoding='utf-8').read())
        if size > CURATED_LIMIT:
            problems.append('MEMORY.md is %d chars, over the %d cap' %
                            (size, CURATED_LIMIT))
    # A log file must never *be* the curated file: a dated log growing past the
    # cap is fine, but a log with curated content in it means the two got mixed.
    for path in log_paths():
        head = io.open(path, encoding='utf-8').read(4000)
        if head.count('## ') > 40:
            problems.append('%s looks like a merged document (%d headings in the '
                            'first 4000 chars)' %
                            (os.path.relpath(path, ROOT), head.count('## ')))
    return problems


def list_layout():
    print('memory directory : %s' % os.path.relpath(MEMORY, ROOT))
    curated = os.path.relpath(CURATED, ROOT)
    if os.path.isfile(CURATED):
        print('  %-42s %6d chars' % (curated,
                                     len(io.open(CURATED, encoding='utf-8').read())))
    else:
        print('  %-42s (absent)' % curated)
    for path in log_paths():
        print('  %-42s %6d chars' % (os.path.relpath(path, ROOT),
                                     len(io.open(path, encoding='utf-8').read())))
    notes = note_paths()
    if notes:
        print('  notes/')
        for path in notes:
            print('    %-40s %6d chars' % (os.path.basename(path),
                                           len(io.open(path, encoding='utf-8').read())))
    else:
        print('  notes/  (empty -- ad-hoc topics go here, one file each)')


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__.strip())
        return 0
    if '--list' in args:
        list_layout()
        return 0
    if '--check' in args:
        problems = check()
        if problems:
            for problem in problems:
                print('FAIL %s' % problem)
            return 1
        print('memory layout ok')
        return 0
    if '--slot' in args:
        slot = args[args.index('--slot') + 1]
        body = read_text(args, '--file', '--text')
        path = write_slot(today(), slot, body)
        print('wrote %s (%d chars)' % (os.path.relpath(path, ROOT), len(body)))
        return 0
    if '--log' in args or '--log-file' in args:
        text = read_text(args, '--log-file', '--log')
        if not text.startswith('\n'):
            text = '\n\n' + text
        path = os.path.join(MEMORY, today() + '.md')
        count = append_to(path, text)
        print('appended %d chars to %s' % (count, os.path.relpath(path, ROOT)))
        return 0
    raise SystemExit('no action requested; see --help')


if __name__ == '__main__':
    raise SystemExit(main())
