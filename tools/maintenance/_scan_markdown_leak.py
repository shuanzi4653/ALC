# -*- coding: utf-8 -*-
"""全站 Markdown 泄漏扫描（0.11.5 / W-27 扩面版）。

**为什么要扩面**：0.11.4 的版本只扫 `.vue` 的 `<template>` 段，于是它报「0 处」，
而「口径与来源」页上明明白白有 18 个 `**` —— 那些文案存在 `runtime.js` 的
`boundary` / `note` / `full` 字段里，模板用 `{{}}` 直渲。**扫描器的射程决定了
它能看见什么；射程之外的 0 处是假 0。**

现在扫两个面：
  1. `.vue` 的 `<template>` 段（排除 `<!-- -->`）
  2. `.js` 里**去掉注释之后的代码行**（注释里的 `**加粗**` 是写给人看的，不算泄漏）

判据：合计 0 处。

`--self-test` 做两条**负向验证**：
  · 把 `**x**` 放进注释 —— 必须**不**报（注释不渲染）
  · 把 `**x**` 放进字符串 —— 必须报（它会渲染）
一条不会红的判据等于没有判据，所以负向用例是这条脚本的一部分。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'frontend' / 'src'

HTML_COMMENT = re.compile(r'<!--.*?-->', re.S)
BOLD = re.compile(r'\*\*([^*<>{}]{1,40})\*\*')
BACKTICK = re.compile(r'`([^`<>{}]{1,60})`')
HAS_CJK = re.compile(r'[\u4e00-\u9fff]')


def template_of(text: str) -> str:
    start = text.find('<template>')
    end = text.rfind('</template>')
    if start < 0 or end < 0:
        return ''
    return text[start + len('<template>'):end]


def strip_comments_js(text: str) -> str:
    """去掉 JS 注释，保留字符串。

    不是完整的词法器，但足够回答"这一行会不会渲染"。两条保守规则：
      · 块注释 `/* ... */` 用状态机吃掉（JSDoc 的 `**` 大量存在，必须排除）；
      · 行注释只吃"前面不是 `:` 或引号"的 `//` —— 这样 `https://` 与 `'//'` 不会被误吃。
    宁可漏报注释，也不要把注释误算成泄漏。
    """
    out = []
    in_block = False
    for line in text.split('\n'):
        stripped = line.strip()
        if in_block:
            if '*/' in stripped:
                in_block = False
            out.append('')
            continue
        if stripped.startswith('/*'):
            if '*/' not in stripped:
                in_block = True
            out.append('')
            continue
        if stripped.startswith('//'):
            out.append('')
            continue
        code = re.sub(r"(?<![:'\"])//.*$", '', line)
        out.append(code)
    return '\n'.join(out)


def scan_vue(path: Path) -> list[tuple[str, int, str]]:
    body = HTML_COMMENT.sub('', template_of(path.read_text(encoding='utf-8')))
    hits = []
    for pattern in (BOLD, BACKTICK):
        for match in pattern.finditer(body):
            line = body[:match.start()].count('\n') + 1
            hits.append((path.name, line, match.group(0)))
    return hits


def scan_js(path: Path) -> list[tuple[str, int, str]]:
    """`.js` 只扫 `**`，**不扫反引号**。

    理由：JS 里反引号是模板字符串的**定界符**，一个正则无法区分"作为文案的反引号"
    与"包住整段 HTML 的定界符"。硬扫的结果是 11 条全部误报（跨行配对）。而 `**`
    在 JS 里极其罕见（除注释），可以精确扫。
    取舍写在 docstring 里，而不是让它静默漏掉：**反引号若真要泄漏，只可能出现在
    `.vue` 的 template 段，那一面已经扫了。**
    """
    body = strip_comments_js(path.read_text(encoding='utf-8'))
    hits = []
    for match in BOLD.finditer(body):
        # 只报含中文的：英文的 `**` 多半是正则或运算符
        if not HAS_CJK.search(match.group(1)):
            continue
        line = body[:match.start()].count('\n') + 1
        hits.append((path.name, line, match.group(0)))
    return hits


def collect() -> tuple[list, list]:
    vue_hits, js_hits = [], []
    for path in sorted(ROOT.rglob('*.vue')):
        vue_hits.extend(scan_vue(path))
    for path in sorted(ROOT.rglob('*.js')):
        if 'node_modules' in path.parts:
            continue
        js_hits.extend(scan_js(path))
    return vue_hits, js_hits


def self_test() -> int:
    """负向验证：注释不报、字符串要报。"""
    failures = 0

    # ① 注释里的 **x** 不该被报
    sample_comment = """// 这条**注释**里有加粗
/* 块注释里的**加粗**
   还有 **另一处** */
const a = 1
"""
    if BOLD.search(strip_comments_js(sample_comment)):
        print('FAIL  负向 1：注释里的 ** 被误报')
        failures += 1
    else:
        print('PASS  负向 1：注释里的 ** 正确跳过')

    # ② 字符串里的 **x** 必须被报
    sample_string = """const s = '气象是**输入**，不是结论。'
"""
    if not BOLD.search(strip_comments_js(sample_string)):
        print('FAIL  负向 2：字符串里的 ** 没被抓到（扫描面失效）')
        failures += 1
    else:
        print('PASS  负向 2：字符串里的 ** 被抓到')

    # ③ 真扫描面必须能看见 .js
    vue_hits, js_hits = collect()

    print('\n== .vue 模板（%d 处）' % len(vue_hits))
    for name, line, text in vue_hits:
        print('  %-34s ~%s  %s' % (name, line, text[:48]))
    print('\n== .js 字符串（%d 处）' % len(js_hits))
    for name, line, text in js_hits:
        print('  %-34s ~%s  %s' % (name, line, text[:48]))

    total = len(vue_hits) + len(js_hits)
    print('\n合计 %d 处' % total)
    return 1 if failures else (1 if total else 0)


def main() -> int:
    if '--self-test' in sys.argv:
        return self_test()

    vue_hits, js_hits = collect()
    print('== .vue 模板（%d 处）' % len(vue_hits))
    for name, line, text in vue_hits:
        print('  %-34s ~%s  %s' % (name, line, text[:48]))
    print('\n== .js 字符串（%d 处）' % len(js_hits))
    for name, line, text in js_hits:
        print('  %-34s ~%s  %s' % (name, line, text[:48]))
    total = len(vue_hits) + len(js_hits)
    print('\n合计 %d 处' % total)
    return 1 if total else 0


if __name__ == '__main__':
    raise SystemExit(main())
