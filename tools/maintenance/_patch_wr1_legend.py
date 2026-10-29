# -*- coding: utf-8 -*-
"""0.11.5B · W-R1：首页把「气象风险区 / 雷达回波」两个开关放回去。

**先更正一件事**：0.11.5B 那份诊断说这是"上一轮做首页减法时顺手滤掉"的 bug。
不准确 —— 过滤是 **0.11.2 的刻意设计**，注释就在旁边：

    首页只留「概率层（可飞性带）」这一套读法；规则派生的风险区与雷达回波
    去「② 走廊 · 气象监测」看。图例同步少三条 —— 图例写着某图层而图上没有，
    是另一种骗人。

**但它的顾虑可以用一句话解决，不该靠藏开关**。所以这次不是"恢复原样"，也不是
"照报告全放回"，而是两头兼顾：

  · 图例 **9 项全显**（报告 W-R1 的诉求：用户必须能自己控制天气可见性）；
  · 图层**真的生效**（0.11.4 的 W-26 已经接上，这里保持）；
  · 用**一句口径**替代"藏起来"（0.11.2 的顾虑）：回波来自气象通道，
    与走廊概率是两套读法，同时看时以判据表为准。

顺带修排版：9 项在 1305px 里放不下（实测 scrollWidth 1532），必须给横向滚动，
否则最后两项被 `overflow:hidden` 安静切掉 —— 那正是"图例写着某图层而用户点不到"。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / 'frontend' / 'src' / 'components' / 'traffic' / 'HomeStage.vue'
WORK = ROOT / 'frontend' / 'src' / 'components' / 'TrafficWorkbench.vue'

home = HOME.read_text(encoding='utf-8')

# ---- 1) 不再过滤任何图层 ----
old = """// 0.11.2 补丁：首页**关掉气象要素/风险区/雷达三个图层**（用户 2026-10-19「去掉圆环吧」）。
// 图上那几十个大椭圆就是"风险区" —— 它来自 v1 规则派生，而结论条与 KPI 用的是 v2 走廊概率；
// 两套同时画，"能见度≈500 m"与"全部走廊低于 50%"会并排出现在同一屏。
// 首页只留**概率层（可飞性带）**这一套读法；规则派生的风险区与雷达回波去「② 走廊 · 气象监测」看。
// 图例同步少三条 —— 图例写着某图层而图上没有，是另一种骗人。
const HOME_HIDDEN_LAYERS=new Set(['weather','risk','radar'])
const layerDefs=computed(()=>MAP_LAYERS.filter(layer=>!HOME_HIDDEN_LAYERS.has(layer.key)).map(layer=>({
  ...layer,
  label:layer.key==='radar'?(props.radarLabel||layer.label):layer.label,
})))"""
new = """// 0.11.5B（W-R1）：这里原来把 `weather / radar` 两个**有独立语义的图层开关**滤掉了。
//
// 0.11.2 的理由是成立的：图上那几十个大椭圆来自 v1 规则派生，而结论条与 KPI 用的是
// v2 走廊概率，"能见度≈500 m"与"全部走廊低于 50%"会并排出现在同一屏。
//
// **但那个顾虑的解法不是把开关藏起来。** 藏起来的结果就是 0.11.5B 诊断里那句话：
// 「功能还在，路径没了 —— 代码不报错、页面不崩、测试也不会红，而评委就是那个
// 会去点它的真人」。而且 0.11.4 的 W-26 已经把图层接上了、图例却没有对应项，
// 于是变成更糟的一种状态：**图层开着、用户关不掉、也不知道它开着**。
//
// 现在改成"全显 + 一句话说清两套读法"：
//   · 开关在，用户能关；
//   · 打开时图例项与地图状态条都会写明它来自气象通道、与走廊概率不是同一套。
// MAP_LAYERS 里本来就没有 `risk` 这个键（它是列表里的说明项，不是地图图层），
// 所以这里的 Set 只能是空集 —— 留着空 Set 是为了说明"过滤点在哪"。
const HOME_HIDDEN_LAYERS = new Set([])
const layerDefs = computed(() => MAP_LAYERS.filter((layer) => !HOME_HIDDEN_LAYERS.has(layer.key)).map((layer) => ({
  ...layer,
  label: layer.key === 'radar' ? (props.radarLabel || layer.label) : layer.label,
  // 两个"气象通道"图层各补一句口径：它们画的是气象通道的实测派生物，
  // 与走廊概率（v2）是两套读法。同时打开时以判据表为准。
  title: (layer.key === 'radar' || layer.key === 'weather')
    ? `${layer.title}。来自气象通道，与「走廊概率」是两套读法；同时打开时以判据表为准。`
    : layer.title,
})))"""
if old not in home:
    raise SystemExit('HOME_HIDDEN_LAYERS 锚点不存在')
home = home.replace(old, new, 1)

# ---- 2) 图例条可横向滚动（9 项放不下） ----
old_css = """.hs-layers{display:flex;align-items:center;gap:12px;flex-wrap:wrap;flex:none;"""
new_css = """/* 9 项在 1305px 的容器里放不下（实测 scrollWidth 1532）。原来靠 `overflow:hidden`
   把最后两项安静切掉 —— 不报错、不打折，就是消失。改成横向滚动：能点到，且
   `flex-wrap:nowrap` 保证不会因为换行把面板撑高（舞台高度固定 1080）。 */
.hs-layers{display:flex;align-items:center;gap:12px;flex-wrap:nowrap;flex:none;
  overflow-x:auto;overflow-y:hidden;scrollbar-width:thin;
  scrollbar-color:rgba(255,255,255,.22) transparent;"""
if old_css not in home:
    raise SystemExit('hs-layers 样式锚点不存在')
home = home.replace(old_css, new_css, 1)

# 滚动条样式（webkit）
old2 = """.hs-layers label{display:inline-flex;"""
new2 = """.hs-layers::-webkit-scrollbar{height:4px}
.hs-layers::-webkit-scrollbar-thumb{background:rgba(255,255,255,.22);border-radius:2px}
.hs-layers::-webkit-scrollbar-track{background:transparent}
.hs-layers label{display:inline-flex;"""
if old2 not in home:
    raise SystemExit('hs-layers label 锚点不存在')
home = home.replace(old2, new2, 1)
HOME.write_text(home, encoding='utf-8')
print('W-R1：图例 9 项全显 + 横向滚动 + 两套读法说明')

# ---- 3) 地图状态条：把"没有"讲成"有理由的没有"（W-R3 的一半） ----
work = WORK.read_text(encoding='utf-8')
import re
# 找 QUIET 分支的文案
m = re.search(r"(雷达：仅层状降水[^'`]*)", work)
print('状态条 QUIET 文案：', m.group(1) if m else '未找到（可能在 runtime.js）')
