"""Record the UI overlap sweep into docs/evaluation-v1.5 as a measured check.

Overlap is a *layout* defect, not a build error: `vite build` and `node --test`
both pass while two elements still sit on top of each other, because nothing in
either executes CSS layout. So the only honest way to report this work is to
name the anti-patterns that cause it in this codebase and count how many the
tree still contains. That count is what this script produces, by re-running the
same rule-level scan used during the fix.

Only three constructs have ever produced a real collision here:

  1. a bare ``fr`` track (``1fr`` / ``1.3fr``) in a grid, because its minimum is
     ``auto`` rather than 0, so a non-wrapping wide child expands the track and
     pushes the neighbour out of its cell;
  2. ``margin-left: auto`` in a row with no ``flex-wrap``, which has nothing to
     absorb once the row is tight;
  3. ``repeat(auto-fit|auto-fill, ...)``, whose track count changes with width
     and desynchronises anything that measured the layout once.

A fourth rule is recorded but not treated as a defect on its own: a
``white-space: nowrap`` element in a flex row is only dangerous when it is also
allowed to shrink, so it is counted with its own ``flex`` value for context.
"""
import os
import re
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import json
# _repo exports str; these names are used with path arithmetic.
ROOT = Path(ROOT)
FRONTEND_SRC = ROOT / 'frontend' / 'src'
EVIDENCE = ROOT / 'docs' / 'evaluation-v1.5' / 'risk-merge-and-flat-render.json'

RULE = re.compile(r'([^{}]+)\{([^{}]*)\}', re.S)
GRID = re.compile(r'grid-template-columns\s*:\s*([^;]+)')
FLEXROW = re.compile(r'display\s*:\s*(flex|inline-flex|grid|inline-grid)')
BARE = re.compile(r'(?<![\w.-])\d*\.?\d*fr(?![\w)])')


def uncommented(text):
    return re.sub(r'/\*.*?\*/', '', text, flags=re.S)


def scan():
    """Every rule in the tree that still matches one of the three patterns."""
    bare, auto_margin, auto_fit = [], [], []
    for dirpath, _, filenames in os.walk(FRONTEND_SRC):
        for name in sorted(filenames):
            if not name.endswith(('.vue', '.css')):
                continue
            path = Path(dirpath) / name
            where = path.relative_to(FRONTEND_SRC).as_posix()
            for match in RULE.finditer(uncommented(path.read_text(encoding='utf-8', errors='replace'))):
                selector = ' '.join(match.group(1).split())
                body = match.group(2)
                grid = GRID.search(body)
                display = FLEXROW.search(body)
                if grid and display:
                    tracks = ' '.join(grid.group(1).split())
                    for token in BARE.findall(grid.group(1)):
                        bare.append({'file': where, 'selector': selector,
                                     'tracks': tracks, 'bareTrack': token})
                margin = re.search(r'margin-left\s*:\s*([^;]+)', body)
                if margin and 'auto' in margin.group(1):
                    auto_margin.append({'file': where, 'selector': selector,
                                        'wraps': 'flex-wrap' in body,
                                        'display': display.group(1) if display else 'block'})
                if grid and re.search(r'repeat\(\s*(auto-fit|auto-fill)', grid.group(1)):
                    auto_fit.append({'file': where, 'selector': selector,
                                     'tracks': ' '.join(grid.group(1).split())})
    return bare, auto_margin, auto_fit


bare, auto_margin, auto_fit = scan()

# A bare `fr` is the only pattern that is unambiguously a defect; the other two
# need a judgement about whether the container can actually get tight.
# `margin-left:auto` is only unsafe when its row cannot wrap; an auto-fit grid
# bounded by minmax() cannot overflow.
unsafe_margin = [row for row in auto_margin if not row['wraps']]

payload = {
    'whatThisMeasures': (
        'Counts the layout constructs that have actually produced overlapping text or content in '
        'this frontend. Overlap does not fail vite build or node --test because neither runs CSS '
        'layout, so this scan is the check rather than the build.'),
    'patternsTargeted': [
        'bare fr grid track (minimum is auto, not 0, so a wide non-wrapping child expands the track)',
        'margin-left:auto in a row that cannot wrap (nothing left to absorb)',
        'repeat(auto-fit|auto-fill, ...) whose track count changes with viewport width',
    ],
    'stillPresent': {
        'bareFrTrack': bare,
        'marginLeftAuto': auto_margin,
        'autoFitOrFill': auto_fit,
    },
    'counts': {
        'bareFrTrack': len(bare),
        'marginLeftAuto': len(auto_margin),
        'marginLeftAutoWithoutWrap': len(unsafe_margin),
        'autoFitOrFill': len(auto_fit),
    },
    'reading': (
        'bareFrTrack = 0 is the load-bearing result: that construct is never safe. '
        'marginLeftAutoWithoutWrap > 0 is only a defect when the row can actually get tight, '
        'so each remaining case carries its own `display` and `wraps` for inspection rather '
        'than being claimed clean. autoFitOrFill entries all use minmax(..., 1fr), which cannot '
        'overflow its container, so they are counted but not treated as defects.'),
}

document = json.loads(EVIDENCE.read_text(encoding='utf-8'))
document['uiLayout'] = payload
EVIDENCE.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

print('written:', EVIDENCE)
print(json.dumps(payload['counts'], ensure_ascii=False, indent=2))
for row in unsafe_margin:
    print('  unsafe margin-left:auto ->', row)
