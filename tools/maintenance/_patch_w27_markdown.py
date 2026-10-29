# -*- coding: utf-8 -*-
"""0.11.5 · W-27：markdown 归零 + **扫描面扩展到 .js**

两件事：
  1. 把 `runtime.js` 里 20 处文案字段的 `**x**` 换成 `<b>x</b>`
     （模板用 `{{}}` 直渲这些字段，所以星号会原样显示给用户）；
  2. 把 `_scan_markdown_leak.py` 的射程从「.vue 的 <template>」扩到
     **「.js 里去掉注释后的字符串字面量」** —— 病因是扫描器的射程，不是那 20 个字面量。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'frontend' / 'src' / 'traffic' / 'runtime.js'
SCANNER = ROOT / 'tools' / 'maintenance' / '_scan_markdown_leak.py'

# ---------- 1) runtime.js 的 20 处 ----------
text = RUNTIME.read_text(encoding='utf-8')
lines = text.split('\n')
bold = re.compile(r'\*\*([^*\n]{1,40})\*\*')
changed = 0
for index, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('/*'):
        continue
    if not bold.search(line):
        continue
    if not any('\u4e00' <= ch <= '\u9fff' for ch in line):
        continue
    new_line = bold.sub(lambda m: '<b>%s</b>' % m.group(1), line)
    if new_line != line:
        lines[index] = new_line
        changed += bold.findall(line).__len__()
RUNTIME.write_text('\n'.join(lines), encoding='utf-8')
print('runtime.js 替换 %d 处 ** → <b>' % changed)

# 反引号（同一批字段里的 `code`）：只处理含中文且非注释的行，且成对
text = RUNTIME.read_text(encoding='utf-8')
lines = text.split('\n')
tick = re.compile(r'`([^`\n]{1,30})`')
tick_changed = 0
for index, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('/*'):
        continue
    # 只在这些行长里做：模板渲染的文案字段（boundary/note/full/definition/source）
    if not re.match(r'\s*(boundary|note|full|definition|source)\s*:', line):
        continue
    if not any('\u4e00' <= ch <= '\u9fff' for ch in line):
        continue
    if '`' not in line:
        continue
    new_line = tick.sub(lambda m: '<code>%s</code>' % m.group(1), line)
    if new_line != line:
        lines[index] = new_line
        tick_changed += 1
RUNTIME.write_text('\n'.join(lines), encoding='utf-8')
print('runtime.js 替换 %d 行反引号 → <code>' % tick_changed)

# ---------- 2) 扫描器扩面 ----------
scanner = SCANNER.read_text(encoding='utf-8')
print('扫描器原长度', len(scanner))
