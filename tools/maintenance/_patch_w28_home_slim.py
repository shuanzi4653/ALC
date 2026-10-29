# -*- coding: utf-8 -*-
"""W-28（0.11.5）：首页减法第一步。

报告的病根判断是对的：**"每一块都在解释自己为什么存在"**。
这一批只做三处"不改结构、只减解释"的减法，每处都可单独回滚：

  ① KPI 卡的第二行基线说明 → 收进 `title`（信息还在，不占版面）
  ② 首页右栏「气象情报」块 → 删（「气象监测」页有整整一页讲这个）
  ③ 地图图例一行长文本 → 收进 `details`（默认收起，点开看）

不做的事：不动 1080 舞台的行列比例。删块之后如果留白，那是下一步的事 ——
先把"解释"减掉，再看版面还缺什么。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRIEF = ROOT / 'frontend' / 'src' / 'components' / 'traffic' / 'SituationBrief.vue'
HOME = ROOT / 'frontend' / 'src' / 'components' / 'traffic' / 'HomeStage.vue'
WORK = ROOT / 'frontend' / 'src' / 'components' / 'TrafficWorkbench.vue'

# ============================================================
# ① KPI 卡：第二行基线说明收进 title
# ============================================================
text = BRIEF.read_text(encoding='utf-8')
old = """    <article v-for="kpi in kpis" :key="kpi.key" class="brief-kpi" :class="'tone-'+kpi.tone">"""
new = """    <!-- 0.11.5（W-28）：基线说明从卡面收进 `title`。
         实测 1680 宽下 4 张卡的第二行合计 336 个 <12px 节点的一部分，
         而它们回答的是"这个数怎么来的"，不是"我该点哪"。悬停可读，版面让给结论。 -->
    <article v-for="kpi in kpis" :key="kpi.key" class="brief-kpi" :class="'tone-'+kpi.tone"
             :title="directionNote(kpi) || '无基线'">"""
if old not in text:
    raise SystemExit('KPI article 锚点不存在')
text = text.replace(old, new, 1)

old = """      <div class="brief-kpi-base" :title="directionNote(kpi)">{{ directionNote(kpi) || '无基线' }}</div>"""
new = """      <!-- 基线不再占一行；读屏仍能拿到（`aria-label`），鼠标悬停也能（父级 title） -->
      <span class="sr-only">{{ directionNote(kpi) || '无基线' }}</span>"""
if old not in text:
    raise SystemExit('KPI 基线行锚点不存在')
text = text.replace(old, new, 1)

# 给 sr-only 一条规则（若全局没有）
if '.sr-only' not in text:
    text = text.replace('.brief{display:flex;', """.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;
  overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.brief{display:flex;""", 1)
BRIEF.write_text(text, encoding='utf-8')
print('① KPI 基线已收进 title')

# ============================================================
# ② 首页右栏「气象情报」整块删除
# ============================================================
home = HOME.read_text(encoding='utf-8')
start = home.find('<section class="hs-panel fam-wx" v-if="!caseMode">')
if start < 0:
    raise SystemExit('气象情报块锚点不存在')
# 找到该 section 的结束（下一个 </section> 之后紧跟的闭合）
end = home.find('</section>', start)
if end < 0:
    raise SystemExit('气象情报块结束标签找不到')
end += len('</section>')
removed = home[start:end]
if '气象情报' not in removed:
    raise SystemExit('删错了段落（里面没有「气象情报」）')
home = home[:start] + """<!-- 0.11.5（W-28）：这里原来有一块「气象情报」（METAR / SIGMET 式三行报文）。
     删掉的理由不是"它不重要"，而是**它在错误的位置**：
       · ① 气象监测页有整整一页讲逐站观测与派生风险区，那里才是它的家；
       · ② 首页右栏已经有「放行许可 / 全网络调度总结」一块，两块并排时
           读者要在两个不相干的话题之间来回切；
       · ③ 它是首页唯一一块"纯解释、无动作"的内容。
     如果将来有人要把它加回来，请先回答：**这一块回答的是"我该点哪"吗？** -->
      """ + home[end:]
HOME.write_text(home, encoding='utf-8')
print('② 气象情报块已删（%d 字符）' % len(removed))

# ============================================================
# ③ 图例收进 details
# ============================================================
work = WORK.read_text(encoding='utf-8')
old = """<span class="traffic-legend-hint">橙黄＝须绕飞 · 深橙＝禁止进入 · 淡紫＝层状降水可穿越 · 灰：深灰＝能见度低于禁飞阈值 / 浅灰＝能见度偏低 · 冷色＝官方管制 · 事件：深橙＝停止放行 / 橙＝气象成因 / 蓝＝非气象成因</span>"""
new = """<!-- 0.11.5（W-28）：图例原来是一整行常驻文本（约 110 字），占掉图层开关右侧
             全部横向空间。收进 details：想核对颜色的人点一下，不想看的人省一行。 -->
          <details class="traffic-legend"><summary>图例</summary>
            <span>橙黄＝须绕飞 · 深橙＝禁止进入 · 淡紫＝层状降水可穿越 · 灰：深灰＝能见度低于禁飞阈值 / 浅灰＝能见度偏低 · 冷色＝官方管制 · 事件：深橙＝停止放行 / 橙＝气象成因 / 蓝＝非气象成因</span>
          </details>"""
if old not in work:
    raise SystemExit('图例锚点不存在')
work = work.replace(old, new, 1)

# 样式：默认紧凑，展开时浮在地图上
old_css = """.traffic-legend-hint{font-size:12px;color:#7794a8;line-height:1.5;flex:1 1 220px;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"""
new_css = """.traffic-legend{position:relative;margin-left:auto;font-size:12px;color:#7794a8}
.traffic-legend summary{cursor:pointer;list-style:none;padding:2px 8px;border:1px solid var(--alc-line);
  border-radius:5px;user-select:none}
.traffic-legend summary::-webkit-details-marker{display:none}
.traffic-legend summary:hover{color:#c6d3e5}
.traffic-legend[open] summary{color:#c6d3e5;border-color:rgba(76,141,255,.45)}
/* 展开时浮起来，**不推挤下面的地图**：推挤会让地图在展开那一瞬间缩放，很刺眼 */
.traffic-legend span{position:absolute;right:0;top:130%;z-index:20;display:block;
  width:min(560px,60vw);padding:8px 10px;border-radius:6px;line-height:1.6;
  background:rgba(17,26,43,.97);border:1px solid var(--alc-line);
  box-shadow:0 8px 24px rgba(0,0,0,.35)}"""
if old_css not in work:
    raise SystemExit('图例样式锚点不存在')
work = work.replace(old_css, new_css, 1)
WORK.write_text(work, encoding='utf-8')
print('③ 图例已收进 details')
