# -*- coding: utf-8 -*-
"""0.11.5 第 1 批（W-25a / W-32 / W-29 / W-30）：四张小工单一次做完。

全部是"改文案 / 删第二来源 / 加选择器 / 改 3 行"，零架构风险。
W-27（markdown 归零 + 扫描面扩展）单独一步，因为它要动扫描器本身。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / 'frontend' / 'src' / 'components' / 'OperationsConsole.vue'
CORR = ROOT / 'frontend' / 'src' / 'components' / 'traffic' / 'CorridorPanel.vue'
RUNTIME = ROOT / 'frontend' / 'src' / 'traffic' / 'runtime.js'
STYLE = ROOT / 'frontend' / 'src' / 'style.css'
V2 = ROOT / 'backend-python' / 'traffic' / 'v2.py'

# ============================================================
# W-25a：处置台把那句"与天气无关"改成范围声明
# ============================================================
text = OPS.read_text(encoding='utf-8')
old = """        当前窗口内的 {{alertGroups.total}} 个事件里没有气象成因的：停止放行 {{alertGroups.closedFlights}} 班全部来自排程越界（超出推演时段），与天气无关。切到「排程冲突」可查看这些事件。"""
new = """        <!-- 0.11.5（W-25a）：原来这三句连写，读者听到的是"21 条禁飞不关天气的事"。
             同一个事实换一种说法：这是**范围声明**（本案例不重跑调度），不是一个否定。
             另外"切到「排程冲突」"指的那个 tab 全站不存在 —— "排程冲突"是卡片上的
             二分类标签，不是入口。这里换成一个真的能点的跳转。 -->
        本案例只回放观测与判据，<b>不重跑调度</b>。下方 {{alertGroups.closedFlights}} 班的停止放行来自实时推演（超出规划视界），与本次回放的气象无关 ——
        要看气象进入决策后的差别，<button type="button" class="inline-link" data-go-counterfactual @click="emit('open-section','counterfactual')">见「复盘对照 » 反事实」</button>。"""
if old not in text:
    raise SystemExit('W-25a 文案锚点不存在')
text = text.replace(old, new, 1)

# 内联链接样式
anchor_css = '.cause-tag.weather'
if anchor_css in text:
    text = text.replace(anchor_css, """.inline-link{padding:0;border:0;background:none;color:#6fb3ff;font:inherit;
  text-decoration:underline;cursor:pointer}
.inline-link:hover{color:#a6d0ff}
"""+anchor_css, 1)
OPS.write_text(text, encoding='utf-8')
print('W-25a 完成：范围声明 + 真跳转')

# ============================================================
# W-32：走廊列表删掉前端那份档位算法
# ============================================================
text = RUNTIME.read_text(encoding='utf-8')
addition = '''/**
 * 后端 `verdict` → 语气色（0.11.5 / W-32）。
 *
 * 走廊列表原来用 `riskTone(row.pMax)` 在前端**重算了一遍档位**，于是
 * 一条"观测档判不可飞、但概率只有 31%"的走廊在列表里显示成"留观"，
 * 而同一页的剖面头写"不可飞"——**同一件事两个来源**，正是项目纪律禁止的那种。
 *
 * 档位只有后端一个来源；前端只负责把三个档映射成颜色。
 */
export function verdictTone(verdict) {
  if (verdict === '不可飞') return 'danger'
  if (verdict === '需谨慎') return 'watch'
  if (verdict === '可飞') return 'ok'
  return 'unknown'
}

/** 概率 → 风险语义色。**与阈值写在一处**，界面不再各写一套 if。 */'''
old_anchor = '/** 概率 → 风险语义色。**与阈值写在一处**，界面不再各写一套 if。 */'
if old_anchor not in text:
    raise SystemExit('W-32 runtime 锚点不存在')
text = text.replace(old_anchor, addition, 1)
RUNTIME.write_text(text, encoding='utf-8')

text = CORR.read_text(encoding='utf-8')
pairs = [
    ("import {pct,riskLabel,riskTone,hourLabel} from '../../traffic/runtime.js'",
     "import {pct,riskTone,verdictTone,hourLabel} from '../../traffic/runtime.js'"),
    ("""<button v-for="row in rows" :key="row.corridorId" class="corr-row" :class="['tone-'+riskTone(row.pMax),{active:row.corridorId===selected}]" @click="selected=row.corridorId">""",
     """<button v-for="row in rows" :key="row.corridorId" class="corr-row" :class="['tone-'+verdictTone(row.verdict),{active:row.corridorId===selected}]" @click="selected=row.corridorId">"""),
    ("<span class=\"corr-row-verdict\">{{ riskLabel(row.pMax) }}</span>",
     "<span class=\"corr-row-verdict\">{{ row.verdict }}</span>"),
]
for old_s, new_s in pairs:
    if old_s not in text:
        raise SystemExit('W-32 CorridorPanel 锚点不存在：' + old_s[:50])
    text = text.replace(old_s, new_s, 1)
CORR.write_text(text, encoding='utf-8')
print('W-32 完成：档位只认后端 verdict')

# ============================================================
# W-29：投影 clamp 补上 SVG <text>
# ============================================================
text = STYLE.read_text(encoding='utf-8')
anchor = """html[data-projection="on"] :where(h1, h2, h3, h4, h5, h6, b, strong) {
  font-size: clamp(20px, 1em, 40px) !important;
}"""
addition = anchor + """

/* 0.11.5（W-29）：上面那两条漏了 **SVG 文本**。
 * `<text font-size="9">起点 / 地面</text>` 这类是 SVG 元素，不在 HTML 标签选择器里，
 * 于是投影档最小字号卡在 9px（实测 46 → 1 个 <12px 节点，剩下那 1 个就是它）。
 * SVG 的 `font-size` 同样接受 CSS 与 `clamp()`，`1em` 取父级字号，行为一致。
 */
html[data-projection="on"] svg text {
  font-size: clamp(16px, 1em, 18px) !important;
}"""
if anchor not in text:
    raise SystemExit('W-29 style 锚点不存在')
text = text.replace(anchor, addition, 1)
STYLE.write_text(text, encoding='utf-8')
print('W-29 完成：SVG 文本纳入下限')

# ============================================================
# W-30：消融只改 B 组，A 组恒定
# ============================================================
text = V2.read_text(encoding='utf-8')
old = """        obs_ban = use_obs and _nearest_observation_level(route, field_payload) == 'BAN'
        ban_hit = obs_ban or (use_prob and p_unsafe >= 0.8)"""
new = """        # 0.11.5（W-30）：**A 组必须恒定**。A 组代表"现行做法"（只看当前观测、
        # 按人工值班逻辑处置），它是尺子；尺子不能跟着被测对象一起变。
        #
        # 原来的写法让 `use_obs/use_prob` 同时作用在两组上：
        #   `ablate=obs` 时 A 组的暴露也被清零 ⇒ 四组里有两组显示"0 → 0"，
        #   看起来像"观测档没用"，实际是"对照组跟着一起被关掉了"。
        current_obs_ban = _nearest_observation_level(route, field_payload) == 'BAN'
        current_ban = current_obs_ban or p_unsafe >= 0.8          # A 组：恒定
        obs_ban = use_obs and current_obs_ban                     # B 组：被消融影响
        ban_hit = obs_ban or (use_prob and p_unsafe >= 0.8)"""
if old not in text:
    raise SystemExit('W-30 obs_ban 锚点不存在')
text = text.replace(old, new, 1)

old_a = """        # A 组：规则怎么说就怎么飞（规则判可飞 = 放行）
        if rule_level < 2 and ban_hit:
            exposure_a += 1"""
new_a = """        # A 组：规则怎么说就怎么飞（规则判可飞 = 放行）。用 `current_ban` 而非 `ban_hit`
        # —— 消融实验只能关掉 B 组的某一层，不能把这一组也关掉（见上）。
        if rule_level < 2 and current_ban:
            exposure_a += 1"""
if old_a not in text:
    raise SystemExit('W-30 exposure_a 锚点不存在')
text = text.replace(old_a, new_a, 1)
V2.write_text(text, encoding='utf-8')
print('W-30 完成：A 组恒定，消融只作用于 B 组')
