# -*- coding: utf-8 -*-
"""W-03b：把「算法机理」从导航里收起来（一次性补丁）。

做三件事：
  1. `TrafficWorkbench` 的二级导航只渲染 `visibleSubs(group)`；
  2. 加 `HIDDEN_SECTIONS`（mechanism）；
  3. 让 OperationsConsole 的 `open-section` 事件切分节。
"""
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'frontend' / 'src' / 'components' / 'TrafficWorkbench.vue'
text = PATH.read_text(encoding='utf-8')

old_nav = ('<button v-for="sub in group.subs" :key="sub.key" :data-section="sub.key" '
           'v-show="group.key===activeGroup?.key" :class="{active:activeSection===sub.key}" '
           '@click="activeSection=sub.key">{{ sub.label }}</button>')
new_nav = ('<button v-for="sub in visibleSubs(group)" :key="sub.key" :data-section="sub.key" '
           'v-show="group.key===activeGroup?.key" :class="{active:activeSection===sub.key}" '
           '@click="activeSection=sub.key">{{ sub.label }}</button>')
if old_nav not in text:
    raise SystemExit('导航锚点不存在')

old_anchor = 'const paletteOpen=ref(false)'
new_anchor = '''// W-03b（0.11.3）：导航里不再单列「算法机理」。
// 它没有下线：从「检验 → 模型卡」页脚的"历史版本 0.10.1"仍可进入。
// 收起来的理由是与模型卡**并排会互相拆台** —— 一页说 AUC 0.95 / TS 0.49，
// 另一页说"学的是判据、42 样本待填"，读者只会记住后者。
const HIDDEN_SECTIONS=new Set(['mechanism'])
const visibleSubs=group=>(group.subs||[]).filter(sub=>!HIDDEN_SECTIONS.has(sub.key))
const paletteOpen=ref(false)'''
if old_anchor not in text:
    raise SystemExit('paletteOpen 锚点不存在')
text = text.replace(old_anchor, new_anchor, 1)

old_listener = '@ai-reviewed="onAiReviewed"/>'
new_listener = '@ai-reviewed="onAiReviewed" @open-section="activeSection=$event"/>'
if old_listener not in text:
    raise SystemExit('OperationsConsole 锚点不存在')
text = text.replace(old_listener, new_listener, 1)

PATH.write_text(text, encoding='utf-8')
print('patched TrafficWorkbench.vue')
