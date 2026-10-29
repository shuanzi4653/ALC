# -*- coding: utf-8 -*-
"""W-20（0.11.4）：让命令面板的目录**从路由生成**，而不是手写的第二份。

复测报告的两条证据：
  ① Ctrl+K 里 4 个复盘页副标完全相同（都是分组副标"用 AI 和不用，差多少"）；
  ② 「算法机理」在导航里已删，命令面板第 12 项还在。
两条都是"同一个目录写了两份"的症状。

改法：
  · `SECTION_HINTS` 给出每个分节**自己**的一句话；
  · `NAV_GROUPS.subs[].hint` 带上它，面板优先用 hint、没有才退回分组副标；
  · `HIDDEN_SECTIONS` 上移到 runtime.js 导出 —— 导航与面板读同一个常量。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'frontend' / 'src' / 'traffic' / 'runtime.js'
PALETTE = ROOT / 'frontend' / 'src' / 'components' / 'traffic' / 'CommandPalette.vue'
WORKBENCH = ROOT / 'frontend' / 'src' / 'components' / 'TrafficWorkbench.vue'

# ---------- 1) runtime.js：hint 表 + NAV_GROUPS 带上 hint + HIDDEN_SECTIONS ----------
text = RUNTIME.read_text(encoding='utf-8')

old = """export const NAV_GROUPS = Object.freeze(NAV_SPEC.map(group => Object.freeze({
  ...group,
  subs: Object.freeze(group.subs.map(key => Object.freeze({ key, label: sectionName(key) }))),
})))"""
new = """/**
 * 每个分节**自己**的一句话（0.11.4 / W-20）。
 *
 * 之前命令面板用的是**分组**副标，于是「复盘」组下四个子页显示同一句话
 * （"用 AI 和不用，差多少"）—— 一眼就能看出这份目录是手写的、而且没跟上。
 * 这里一句一页，判据是：把这句话念给没看过系统的人听，他能判断该不该点它。
 */
export const SECTION_HINTS = Object.freeze({
  home: '一屏结论：现在哪片天不能飞',
  overview: '按城市与走廊铺开的全域态势',
  weather: '逐站观测、派生风险区与数据来源',
  profile: '沿走廊逐公里的不可飞概率剖面',
  briefing: '放行许可、气象情报与管制边界',
  alerts: '预警事件的成因分布与处置状态',
  assistant: '大模型的证据检索与判定留痕',
  schedule: '逐班次的申请、计划与实际',
  card: '三个目标的 TS / AUC / 提前量对照',
  mechanism: '历史版本 0.10.1 的判据模型（非当前在跑的）',
  counterfactual: '同一份计划，AI 与规则各自处置了什么',
  ledger: '人与系统判定不一致的逐条记录',
  history: '运行日志与按帧回放',
  reference: '口径、阈值与每一条数据的来源',
})

/**
 * 不在导航里出现的分节（0.11.4 / W-20）。
 *
 * 「算法机理」没有下线 —— 它从「检验 · 模型卡」页脚的"历史版本 0.10.1"仍可进入。
 * 它不进导航的理由是**并排会互相拆台**：模型卡说 AUC 0.95 / TS 0.49，机理页说
 * "学的是判据、42 样本待填"，读者只会记住后者。
 *
 * 这个常量必须被**导航与命令面板同时读取**：只在一处过滤，就会出现"导航里没了、
 * Ctrl+K 里还在"（复测报告就是这么发现的）。
 */
export const HIDDEN_SECTIONS = Object.freeze(new Set(['mechanism']))

export const NAV_GROUPS = Object.freeze(NAV_SPEC.map(group => Object.freeze({
  ...group,
  subs: Object.freeze(group.subs.map(key => Object.freeze({
    key, label: sectionName(key), hint: SECTION_HINTS[key] || group.subtitle,
  }))),
})))"""
if old not in text:
    raise SystemExit('NAV_GROUPS 锚点不存在')
text = text.replace(old, new, 1)

# 导出可见子页的辅助函数（导航与面板共用，避免各写一份过滤）
text = text.replace(
    "/** 分组的默认子视图（第一个）。 */",
    """/** 某个分组里**导航与面板都该显示**的子页（0.11.4 / W-20）。 */
export function visibleSubs(group) {
  if (!group) return []
  return (group.subs || []).filter(sub => !HIDDEN_SECTIONS.has(sub.key))
}

/** 分组的默认子视图（第一个）。 */""", 1)

RUNTIME.write_text(text, encoding='utf-8')
print('runtime.js patched')

# ---------- 2) CommandPalette：meta 用 hint，并过滤隐藏分节 ----------
text = PALETTE.read_text(encoding='utf-8')
old = """  for(const group of props.groups){
    for(const sub of group.subs||[])out.push({
      kind:'section',key:sub.key,group:'跳转',
      label:sub.label,meta:`${group.no} ${group.label} · ${group.subtitle}`,
    })
  }"""
new = """  for(const group of props.groups){
    // 0.11.4（W-20）：① 用 sub.hint（一句一页），不再四个子页共用分组副标；
    // ② 与导航读**同一个** HIDDEN_SECTIONS —— 只在导航里过滤，就会出现
    // "导航里没了、Ctrl+K 里还在"这种第二份目录，而它一定不同步。
    for(const sub of group.subs||[]){
      if(HIDDEN_SECTIONS.has(sub.key))continue
      out.push({
        kind:'section',key:sub.key,group:'跳转',
        label:sub.label,meta:`${group.no} ${group.label} · ${sub.hint||group.subtitle}`,
      })
    }
  }"""
if old not in text:
    raise SystemExit('面板 items 锚点不存在')
text = text.replace(old, new, 1)

import re
m = re.search(r"import \{([^}]*)\} from '\.\./\.\./traffic/runtime\.js'", text)
if not m:
    raise SystemExit('面板 runtime import 不存在')
if 'HIDDEN_SECTIONS' not in m.group(1):
    text = text.replace(m.group(0),
                        "import {HIDDEN_SECTIONS,%s} from '../../traffic/runtime.js'" % m.group(1), 1)
PALETTE.write_text(text, encoding='utf-8')
print('CommandPalette patched')

# ---------- 3) TrafficWorkbench：本地 HIDDEN_SECTIONS 改为 import ----------
text = WORKBENCH.read_text(encoding='utf-8')
old = """// W-03b（0.11.3）：导航里不再单列「算法机理」。
// 它没有下线：从「检验 → 模型卡」页脚的"历史版本 0.10.1"仍可进入。
// 收起来的理由是与模型卡**并排会互相拆台** —— 一页说 AUC 0.95 / TS 0.49，
// 另一页说"学的是判据、42 样本待填"，读者只会记住后者。
const HIDDEN_SECTIONS=new Set(['mechanism'])
const visibleSubs=group=>(group.subs||[]).filter(sub=>!HIDDEN_SECTIONS.has(sub.key))
"""
new = """// W-03b / W-20（0.11.4）：`HIDDEN_SECTIONS` 与 `visibleSubs` 已上移到 runtime.js。
// 放在这里等于让导航与命令面板各有一份过滤逻辑 —— 实测就是这样出现了
// "导航里没了、Ctrl+K 里还在"。现在两处读同一个导出。
"""
if old not in text:
    raise SystemExit('WORKBENCH HIDDEN 锚点不存在')
text = text.replace(old, new, 1)
text = text.replace("SECTION_NAMES,DENSITY_TIERS,NAV_GROUPS",
                    "SECTION_NAMES,DENSITY_TIERS,NAV_GROUPS,visibleSubs", 1)
WORKBENCH.write_text(text, encoding='utf-8')
print('TrafficWorkbench patched')
