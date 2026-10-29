import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _repo import ROOT  # noqa: E402
import re
d = os.path.join(ROOT, 'frontend', 'src')
rows = []
for root, _, files in os.walk(d):
    for f in files:
        if not f.endswith('.vue'):
            continue
        p = os.path.join(root, f)
        t = open(p, encoding='utf-8').read()
        for m in re.finditer(r'grid-template-columns\s*:\s*([^;}]+)', t):
            v = m.group(1).strip()
            risky = []
            if 'auto-fit' in v or 'auto-fill' in v:
                risky.append('AUTOFIT')
            if '1fr' in v and 'minmax(0' not in v:
                risky.append('BARE-1FR')
            if risky:
                rows.append((f, ','.join(risky), v[:130]))
rows.sort()
for f, tag, v in rows:
    print(f'{tag:<18} {f:<34} {v}')
print()
print('total', len(rows))
