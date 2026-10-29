"""Survey the exact damaged shapes across tools/*.py before repairing anything."""
import os
import re
from collections import Counter, defaultdict

BASE = r'C:\Users\12921\Desktop\ALC\tools'
files = sorted(
    os.path.join(dp, f)
    for dp, _, fs in os.walk(BASE)
    for f in fs
    if f.endswith('.py')
)

shapes = Counter()
examples = defaultdict(list)
report = []

for path in files:
    name = os.path.basename(path)
    if name == '_repo.py':
        continue
    text = open(path, encoding='utf-8', errors='replace').read()
    lines = text.split('\n')
    rel = os.path.relpath(path, BASE)

    head = '\n'.join(lines[:40])
    tags = []

    if re.search(r'\bROOT\s*=\s*Path\(\s*ROOT\s*\)', text):
        tags.append('A: ROOT自引用')
    if re.search(r'from _repo import', text) and not re.search(
            r'sys\.path\.insert\(0,\s*os\.path\.dirname\(os\.path\.dirname', text):
        tags.append('B: import _repo 但没先把 tools/ 加进 sys.path')
    has_repo_import = 'import _repo' in text or 'from _repo import' in text
    if not has_repo_import and re.search(r'\bROOT\s*=', text):
        tags.append('C: 自算 ROOT')
    if re.search(r'backend-python[\\/]+backend-python', text):
        tags.append('D: 双 backend 路径')
    # bootstrap placed after a project import
    m = re.search(r'^from _repo import', text, re.M)
    if m and re.search(r'^from traffic import', text[m.start():], re.M):
        tags.append('E: bootstrap 在 traffic import 之后')
    if re.search(r'^\s*ROOT\s*=\s*Path\(__file__\)', text, re.M):
        tags.append('F: ROOT=Path(__file__) 未上溯')
    if re.search(r"chdir\(|os\.chdir", text):
        tags.append('G: 用 chdir')

    if tags:
        for t in tags:
            shapes[t] += 1
            if len(examples[t]) < 6:
                examples[t].append(rel)
        report.append((rel, tags))

print(f'tools 下共 {len(files)} 个 py；有病征的 {len(report)} 个')
print()
for key in sorted(shapes):
    print(f'{key:<44} {shapes[key]:>4}')
print()
for key in sorted(examples):
    print(f'--- {key}')
    for e in examples[key]:
        print('   ', e)
print()
print('=== 逐文件病征 ===')
for rel, tags in report:
    print(f'{rel:<52} {", ".join(t[0] for t in tags)}')
