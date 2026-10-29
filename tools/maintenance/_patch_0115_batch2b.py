# -*- coding: utf-8 -*-
"""0.11.5 第 2 批 · 续（W-25b 前端 + W-33）。W-26 与 W-25b 后端已在上一步落盘。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / 'frontend' / 'src' / 'components' / 'OperationsConsole.vue'
RUNTIME = ROOT / 'frontend' / 'src' / 'traffic' / 'runtime.js'

ops = OPS.read_text(encoding='utf-8')
anchor = """  <template v-if="view==='alerts'">"""
if anchor not in ops:
    raise SystemExit('W-25b alerts 锚点仍不存在')

card = """  <template v-if="view==='alerts'">
      <!-- 0.11.5（W-25b）：首页说"21 条走廊观测已达禁飞级"，而这一页原来一句都不提，
           反而写"停止放行全部与天气无关"——两张屏放一起就是自证"判据没进调度"。
           现在把**已经算出来的** B 组结论搬上来：走廊数、涉及班次、应当怎么处置、
           暴露变化，全部来自同一次 `counterfactual(case)`，页面不再出现第二种口径。 -->
      <section class="case-panels" v-if="casePanels" data-case-panels>
        <header>
          <b>本案例判据</b>
          <span>{{ casePanels.caseLabel || '历史回放' }}</span>
          <small>数据来自「复盘对照 · 反事实」的同一次计算</small>
        </header>
        <div class="case-panels-grid">
          <div><small>观测已达禁飞级</small><b>{{ casePanels.corridorsAtBan }} 条走廊</b></div>
          <div><small>涉及班次</small><b>{{ casePanels.flightsHandled }} 班</b></div>
          <div><small>按观测档应当</small><b>改航 {{ casePanels.rerouted }} · 延误 {{ casePanels.delayed }}</b></div>
          <div><small>暴露变化</small><b>{{ casePanels.exposureA }} → {{ casePanels.exposureB }} 架次</b></div>
        </div>
        <p class="case-panels-foot">
          这是判据层的结论：观测已越过禁飞阈值，按观测档应当处置 {{ casePanels.flightsHandled }} 班。
          <b>下方是实时推演的事件，与这段判据不同源</b> —— 本案例只回放观测，不重跑调度。
        </p>
      </section>
      """
ops = ops.replace(anchor, card, 1)

old_state = "const caseMode=isCaseMode()"
new_state = """const caseMode=isCaseMode()
// W-25b：案例模式下取一次「本案例判据」。这不是"再算一遍" ——
// `counterfactual` 与反事实页读的是同一个 URL、同一份计划，所以两页的数字不可能不同。
const casePanels=ref(null)
const activeCaseId=(()=>{try{return new URLSearchParams(window.location.search).get('case')||''}catch(_){return ''}})()
watch(()=>[caseMode,activeCaseId,session.value?.status],async()=>{
  if(!caseMode||!activeCaseId||session.value?.status!=='READY'){casePanels.value=null;return}
  try{
    const value=await requestJson(`/api/traffic/v2/counterfactual?seed=${session.value.seed||42}&scenario=${session.value.scenario||'live'}&policy=balanced&case=${encodeURIComponent(activeCaseId)}`,{timeoutMs:45000})
    casePanels.value=value?.casePanels||null
  }catch(_){casePanels.value=null}
},{immediate:true})"""
if old_state not in ops:
    raise SystemExit('W-25b caseMode 锚点不存在')
ops = ops.replace(old_state, new_state, 1)

css_anchor = '.inline-link{'
if css_anchor not in ops:
    raise SystemExit('W-25b 样式锚点不存在')
ops = ops.replace(css_anchor, """.case-panels{margin:0 0 14px;padding:12px 14px;border:1px solid rgba(194,65,12,.42);
  border-radius:8px;background:rgba(194,65,12,.06)}
.case-panels header{display:flex;align-items:baseline;gap:10px;margin-bottom:8px}
.case-panels header b{font-size:13px;color:#F0B27A}
.case-panels header span{font-size:12px;color:var(--alc-text)}
.case-panels header small{margin-left:auto;font-size:11px;color:var(--alc-text-dim)}
.case-panels-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.case-panels-grid div{display:flex;flex-direction:column;gap:2px}
.case-panels-grid small{font-size:11px;color:var(--alc-text-dim)}
.case-panels-grid b{font-size:14px;color:var(--alc-text);font-variant-numeric:tabular-nums}
.case-panels-foot{margin:10px 0 0;font-size:12px;color:var(--alc-text-dim);line-height:1.6}
.case-panels-foot b{color:#F0B27A}
"""+css_anchor, 1)
OPS.write_text(ops, encoding='utf-8')
print('W-25b 前端完成')

# ---- W-33 ----
rt = RUNTIME.read_text(encoding='utf-8')
old = """  home:'运行首页',overview:'运行总览',briefing:'民航情报',schedule:'调度台账',
  alerts:'预警中心',weather:'气象监测'"""
new = """  home:'运行首页',overview:'运行总览',briefing:'民航情报',schedule:'调度台账',
  // 0.11.5（W-33）：这一页的标题本来就是「事件处置台」，而导航里它曾经叫「预警中心」，
  // 入口又叫「处置台」—— 三个词指同一个地方，读者要在脑子里做一次映射。
  // 现在入口、tab、页面标题统一叫「事件处置台」。
  alerts:'事件处置台',weather:'气象监测'"""
if old not in rt:
    raise SystemExit('W-33 SECTION_NAMES 锚点不存在')
rt = rt.replace(old, new, 1)

old = "  alerts: '处置台',\n"
if old not in rt:
    raise SystemExit('W-33 ENTRY_LABELS 锚点不存在')
rt = rt.replace(old, '', 1)
RUNTIME.write_text(rt, encoding='utf-8')
print('W-33 完成')
