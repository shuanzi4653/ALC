"""补一个闸门：Vue 组件里把 **prop 当 ref 用**（`propName.value`）的结构性缺陷。

为什么需要它：`_audit_unbound_names.py` 是 Python AST 扫描，管不到 `.js/.vue`；
而 `propName.value` 这种写法**语法完全合法**，构建会过、lint 也未必报，只有在浏览器
跑到那一行时才抛 `ReferenceError: xxx is not defined`。
0.11.13 就是靠这条抓到 `OperationsConsole.vue` 里的 `session.value` ——
案例回放的判据面板因此从来没加载出来过。

判据：
  · 从 `defineProps({...})` 里取键名；
  · 在 `<script>` 体内找 `键.value`（排除注释行与字符串里的）；
  · 若同名标识符在 `<script>` 里另有 `const/let/var` 定义，则**不算**（那是局部 ref）；
  · 模板 `<template>` 里不查 —— 模板作用域里 prop 是直接可见的，`.value` 也不会写。

用法：
    python tools/maintenance/_audit_vue_prop_refs.py            # 扫全仓
    python tools/maintenance/_audit_vue_prop_refs.py --self-test  # 负向自检（必须先红）
退出码：0 干净 / 1 有发现 / 2 无法测量
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'frontend' / 'src'

PROPS_BLOCK = re.compile(r'defineProps\s*(?:<[^>]*>)?\s*\(\s*\{', re.S)
# 键名两种写法：`foo:Type` 与 `foo:{type:...}`
PROP_KEY = re.compile(r'([A-Za-z_$][\w$]*)\s*:\s*[A-Za-z_$]')
LOCAL_DEF = re.compile(r'\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=')


def strip_comments(text: str) -> str:
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    text = re.sub(r'(?m)^\s*//.*$', '', text)
    return text


def props_of(script: str) -> set[str]:
    match = PROPS_BLOCK.search(script)
    if not match:
        return set()
    # 从头开始做花括号配平，取出整块
    start = match.end() - 1
    depth = 0
    for index in range(start, len(script)):
        char = script[index]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                block = script[start:index + 1]
                return set(PROP_KEY.findall(block))
    return set()


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    raw = path.read_text(encoding='utf-8', errors='replace')
    script_match = re.search(r'<script[^>]*>(.*?)</script>', raw, re.S)
    if not script_match:
        return []
    body = strip_comments(script_match.group(1))
    props = props_of(body)
    if not props:
        return []
    locals_ = set(LOCAL_DEF.findall(body))
    findings = []
    for name in sorted(props - locals_):
        for hit in re.finditer(r'\b%s\s*\.\s*value\b' % re.escape(name), body):
            line = body.count('\n', 0, hit.start()) + 1
            findings.append((line, name, body.splitlines()[line - 1].strip()[:120]))
    return findings


def self_test() -> int:
    """负向自检：喂一个"有缺陷"的假文件，**必须先红**。"""
    import tempfile

    bad = """<script setup>
const props = defineProps({ session: Object })
const shown = computed(() => session.value?.status)
</script>
"""
    good = """<script setup>
const props = defineProps({ session: Object })
const shown = computed(() => props.session?.status)
const other = ref(1)
console.log(other.value)
</script>
"""
    with tempfile.TemporaryDirectory() as tmp:
        dir_ = Path(tmp)
        (dir_ / 'Bad.vue').write_text(bad, encoding='utf-8')
        (dir_ / 'Good.vue').write_text(good, encoding='utf-8')
        bad_hits = scan_file(dir_ / 'Bad.vue')
        good_hits = scan_file(dir_ / 'Good.vue')
    if not bad_hits:
        print('自检失败：有缺陷的样本没被抓到 —— 这条审计没有牙齿')
        return 2
    if good_hits:
        print('自检失败：正确写法被误报 —— %s' % good_hits)
        return 2
    print('自检通过：缺陷样本 1 条被抓到，正确样本 0 条')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    files = sorted(SRC.rglob('*.vue'))
    if not files:
        print('找不到 .vue 文件：%s（目录结构变了？）' % SRC)
        return 2
    total = 0
    for path in files:
        hits = scan_file(path)
        for line, name, code in hits:
            total += 1
            print('%s:%d  prop `%s` 被当 ref 用 → %s'
                  % (path.relative_to(ROOT), line, name, code))
    if total:
        print('\n共 %d 处：prop 不是 ref，`prop.value` 会在运行时抛 ReferenceError' % total)
        return 1
    print('prop-ref 审计 -- ok（%d 个 .vue）' % len(files))
    return 0


if __name__ == '__main__':
    sys.exit(main())
