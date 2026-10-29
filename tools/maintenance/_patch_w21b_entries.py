# -*- coding: utf-8 -*-
"""W-21b：导航入口 13 → 8（0.11.4）。

**不改 `activeSection` 的语义**：它仍然是被渲染的那个视图（schedule / assistant / ...）。
改的只是"入口"这一层 —— 几个相关视图共用一个入口，页面内用一条 tab 条切换。

为什么这样最省风险：下钻（`drillTarget`）、事件联动、`SECTION_CAN_DO`、全部测试
都按 `activeSection` 说话。入口只是导航的展示层，它一改，那些逻辑一行都不用动。

合并依据是**它们回答同一个问题**：
  · 处置台     —— 这一批事件该怎么做、谁在什么时候飞、AI 在里面说了什么
  · 检验结论   —— 模型准不准，以及这些指标与口径的依据
  · 复盘对照   —— 同一次运行，AI 与人各自判了什么、留下什么痕迹
"""
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'frontend' / 'src' / 'traffic' / 'runtime.js'
text = PATH.read_text(encoding='utf-8')

old_spec = """const NAV_SPEC = [
  { key: 'situation', no: 1, label: '态势', subtitle: '未来 6 小时，哪片天不能飞',
    subs: ['home', 'overview', 'weather'] },
  { key: 'corridor', no: 2, label: '走廊', subtitle: '这条走廊几点能飞，凭什么',
    subs: ['profile', 'briefing'] },
  { key: 'dispatch', no: 3, label: '处置', subtitle: 'AI 与规则谁说了算',
    subs: ['alerts', 'assistant', 'schedule'] },
  { key: 'verify', no: 4, label: '检验', subtitle: '模型准不准，比基线强多少',
    subs: ['card', 'mechanism'] },
  { key: 'review', no: 5, label: '复盘', subtitle: '用 AI 和不用，差多少',
    subs: ['counterfactual', 'ledger', 'history', 'reference'] },
]"""

new_spec = """/**
 * 导航规格（0.11.4 / W-21b）。`subs` 的一项 = **一个入口**：
 *
 *   { key: 'alerts', members: ['alerts','schedule','assistant'] }
 *
 * `key` 是入口的**锚点视图**（点它时先打开这个）；`members` 是它包含的全部视图，
 * 页面内用一条 tab 条切换。`members` 省略 = 只有自己。
 *
 * 这样 `activeSection` 仍然只表示"现在渲染哪个视图"，而"入口"是展示层。
 * 反过来做（把 13 个视图真的删成 8 个）会把每个视图的判据、口径、下钻全重写一遍 ——
 * 那是重写，不是收拢。
 */
const NAV_SPEC = [
  { key: 'situation', no: 1, label: '态势', subtitle: '未来 6 小时，哪片天不能飞',
    subs: ['home', 'overview', 'weather'] },
  { key: 'corridor', no: 2, label: '走廊', subtitle: '这条走廊几点能飞，凭什么',
    subs: ['profile', 'briefing'] },
  { key: 'dispatch', no: 3, label: '处置', subtitle: 'AI 与规则谁说了算',
    subs: [{ key: 'alerts', label: '处置台', hint: '一批事件该怎么做、谁在什么时候飞',
              members: ['alerts', 'schedule', 'assistant'] }] },
  { key: 'verify', no: 4, label: '检验', subtitle: '模型准不准，比基线强多少',
    subs: [{ key: 'card', label: '检验结论', hint: '三个目标的指标，以及这些口径的依据',
              members: ['card', 'reference'] }] },
  { key: 'review', no: 5, label: '复盘', subtitle: '用 AI 和不用，差多少',
    subs: [{ key: 'counterfactual', label: '复盘对照', hint: 'AI 与各判了什么、留下什么痕迹',
              members: ['counterfactual', 'ledger', 'history'] }] },
]"""
if old_spec not in text:
    raise SystemExit('NAV_SPEC 锚点不存在')
text = text.replace(old_spec, new_spec, 1)

# ---- NAV_GROUPS：subs 支持对象写法，并补 members / label / hint ----
old_groups = """export const NAV_GROUPS = Object.freeze(NAV_SPEC.map(group => Object.freeze({
  ...group,
  subs: Object.freeze(group.subs.map(key => Object.freeze({
    key, label: sectionName(key), hint: SECTION_HINTS[key] || group.subtitle,
  }))),
})))"""
new_groups = """export const NAV_GROUPS = Object.freeze(NAV_SPEC.map(group => Object.freeze({
  ...group,
  subs: Object.freeze(group.subs.map(entry => {
    const spec = typeof entry === 'string' ? { key: entry } : entry
    const members = Object.freeze(spec.members ? [...spec.members] : [spec.key])
    return Object.freeze({
      key: spec.key,
      // 入口标签优先用入口自己的（"处置台"），否则就是锚点视图的名字
      label: spec.label || sectionName(spec.key),
      hint: spec.hint || SECTION_HINTS[spec.key] || group.subtitle,
      members,
      // 单视图入口没有 tab 条；多视图才有
      merged: members.length > 1,
    })
  })),
})))

/** 一个视图属于哪个**入口**（返回入口对象，找不到返回 null）。 */
export function entryOf(sectionKey) {
  for (const group of NAV_GROUPS) {
    for (const entry of group.subs) {
      if (entry.members.includes(sectionKey)) return entry
    }
  }
  return null
}

/** 入口里的 tab 列表：`[{key,label,active}]`。单视图入口返回空数组。 */
export function entryTabs(sectionKey) {
  const entry = entryOf(sectionKey)
  if (!entry || !entry.merged) return []
  return entry.members.map(key => ({ key, label: sectionName(key) }))
}

/** 导航入口总数（W-21b 的目标是 8；这条会被测试钉住）。 */
export function navEntryCount() {
  return NAV_GROUPS.reduce((total, group) => total + group.subs.length, 0)
}"""
if old_groups not in text:
    raise SystemExit('NAV_GROUPS 锚点不存在')
text = text.replace(old_groups, new_groups, 1)

# ---- groupOfSection：按 members 匹配（视图 → 组） ----
old_gof = """export function groupOfSection(key) {
  const group = NAV_GROUPS.find(g => g.subs.some(sub => sub.key === key))
  return group ? group.key : ''
}"""
new_gof = """export function groupOfSection(key) {
  const group = NAV_GROUPS.find(g => g.subs.some(sub => sub.members.includes(key)))
  return group ? group.key : ''
}"""
if old_gof not in text:
    raise SystemExit('groupOfSection 锚点不存在')
text = text.replace(old_gof, new_gof, 1)

# ---- navCoverageGap：按 members 展开比对（14 个视图都要挂在某入口下） ----
old_gap = """export function navCoverageGap() {
  const declared = new Set(Object.keys(SECTION_NAMES))
  const grouped = new Set(NAV_GROUPS.flatMap(g => g.subs.map(s => s.key)))
  const missing = [...declared].filter(k => !grouped.has(k))
  const extra = [...grouped].filter(k => !declared.has(k))
  return missing.length || extra.length ? { missing, extra } : null
}"""
new_gap = """export function navCoverageGap() {
  const declared = new Set(Object.keys(SECTION_NAMES))
  // W-21b：入口是"折叠"过的，所以要**展开 members** 再比 ——
  // 只看 `subs[].key` 的话，被并进「处置台」的 schedule/assistant 会被算成"没归组"，
  // 而它们其实好端端地挂在入口里。这条闸门一旦按入口 key 比，就会误报三个缺口。
  const grouped = new Set(NAV_GROUPS.flatMap(g => g.subs.flatMap(s => s.members)))
  const missing = [...declared].filter(k => !grouped.has(k))
  const extra = [...grouped].filter(k => !declared.has(k))
  return missing.length || extra.length ? { missing, extra } : null
}"""
if old_gap not in text:
    raise SystemExit('navCoverageGap 锚点不存在')
text = text.replace(old_gap, new_gap, 1)

PATH.write_text(text, encoding='utf-8')
print('runtime.js：入口层已加（8 入口 / 14 视图）')
