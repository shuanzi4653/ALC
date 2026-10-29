# -*- coding: utf-8 -*-
"""W-20 第 2 步：给命令面板加 import 与 per-section hint（脚本版，避免 shell 引号）。"""
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'frontend' / 'src' / 'components' / 'traffic' / 'CommandPalette.vue'
text = PATH.read_text(encoding='utf-8')

anchor = "import {computed,nextTick,ref,watch} from 'vue'"
if anchor not in text:
    raise SystemExit('vue import 锚点不存在')
addition = (anchor + "\n"
            "// 0.11.4（W-20）：与导航读**同一个** HIDDEN_SECTIONS。\n"
            "// 只在一处过滤，就会出现『导航里没了、Ctrl+K 里还在』的第二份目录。\n"
            "import {HIDDEN_SECTIONS} from '../../traffic/runtime.js'")
text = text.replace(anchor, addition, 1)

old = """  for(const group of props.groups){
    for(const sub of group.subs||[])out.push({
      kind:'section',key:sub.key,group:'跳转',
      label:sub.label,meta:`${group.no} ${group.label} · ${group.subtitle}`,
    })
  }"""
new = """  for(const group of props.groups){
    for(const sub of group.subs||[]){
      if(HIDDEN_SECTIONS.has(sub.key))continue
      out.push({
        kind:'section',key:sub.key,group:'跳转',
        label:sub.label,
        // 用 sub.hint（一句一页），不再让四个子页共用分组副标
        meta:`${group.no} ${group.label} · ${sub.hint||group.subtitle}`,
      })
    }
  }"""
if old not in text:
    raise SystemExit('items 锚点不存在')
text = text.replace(old, new, 1)

PATH.write_text(text, encoding='utf-8')
print('CommandPalette ok')
