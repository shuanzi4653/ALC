# -*- coding: utf-8 -*-
"""0.11.5 第 2 批（W-26 / W-25b / W-33）。

W-26：明细表必须是"改判的那 20 条"，不是"前 20 条"；并删掉那句与走廊剖面打架的旧话。
W-25b：把已经算出来的 B 组结论搬到处置台 —— 让首页的 21 条禁飞有下文。
W-33：导航里「处置台」与「预警中心」两个词并排，只隔一条竖线。改成一个。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / 'backend-python' / 'traffic' / 'v2.py'
CF = ROOT / 'frontend' / 'src' / 'components' / 'traffic' / 'CounterfactualPanel.vue'
OPS = ROOT / 'frontend' / 'src' / 'components' / 'OperationsConsole.vue'
RUNTIME = ROOT / 'frontend' / 'src' / 'traffic' / 'runtime.js'

text = V2.read_text(encoding='utf-8')

# ============================================================
# W-26 ①：收集"观测已达禁飞级"的走廊（供 W-25b 的卡片用）
# ============================================================
old = """    exposure_a = exposure_b = 0
    cancelled = delayed = rerouted = 0"""
new = """    exposure_a = exposure_b = 0
    cancelled = delayed = rerouted = 0
    # 观测已达禁飞级的走廊集合。W-25b 的「本案例判据」卡要用它，
    # 否则处置台只能自己再算一遍 —— 那又会变成两个来源。
    ban_corridors: set = set()"""
if old not in text:
    raise SystemExit('W-26 累加变量锚点不存在')
text = text.replace(old, new, 1)

old = """        current_obs_ban = _nearest_observation_level(route, field_payload) == 'BAN'"""
new = """        current_obs_ban = _nearest_observation_level(route, field_payload) == 'BAN'
        if current_obs_ban:
            ban_corridors.add(route['id'])"""
if old not in text:
    raise SystemExit('W-26 current_obs_ban 锚点不存在')
text = text.replace(old, new, 1)

# ============================================================
# W-26 ②：明细表按"真改判优先"排序，0→0 的行改叫"留痕未改判"
# ============================================================
old = """        records.append({'flightId': flight.get('id'), 'corridorId': route['id'],
                        'p': p_unsafe, 'ruleLevel': rule_level, 'fusedLevel': fused,
                        'obsBan': obs_ban, 'changed': changed,
                        'confidence': round(confidence, 4), 'note': fused_note})"""
new = """        # 0.11.5（W-26）：`changed` 为假的那些行不是"改判"，是"看过但没改"。
        # 原来它们也叫"低置信转人工复核"，和上面"改判 3048"并排就变成
        # "AI 把 3016 架次救回来了，明细却全是 0→0"——两句话单看都对，并排就是反逻辑。
        records.append({'flightId': flight.get('id'), 'corridorId': route['id'],
                        'p': p_unsafe, 'ruleLevel': rule_level, 'fusedLevel': fused,
                        'obsBan': obs_ban, 'changed': changed,
                        'confidence': round(confidence, 4),
                        'note': fused_note if changed else '低置信 · 留痕未改判'})"""
if old not in text:
    raise SystemExit('W-26 records 锚点不存在')
text = text.replace(old, new, 1)

old = """        'sample': records[:20],"""
new = """        # 0.11.5（W-26）：**先挑真改判的，再补留痕的**。
        # 按原顺序切前 20 条时，前 20 恰好全是 p≈0.31 / conf≈0.39 的低置信样本，
        # 于是"改判 3048"下面挂着一张"规则/融合后全是 0/0"的表 —— 现场最容易被点破。
        'sample': (
            sorted([r for r in records if r['changed']], key=lambda r: -r['p'])
            + [r for r in records if not r['changed']]
        )[:20],
        # W-25b：把结论搬给处置台。数字全部来自同一轮计算，不新增任何一次求值。
        'casePanels': ({
            'caseLabel': (traffic_cases.describe(case_id) or {}).get('label'),
            'corridorsAtBan': len(ban_corridors),
            'flightsHandled': cancelled + delayed + rerouted,
            'rerouted': rerouted,
            'delayed': delayed,
            'delayMinutes': delay_minutes,
            'exposureA': exposure_a,
            'exposureB': exposure_b,
        } if case_id else None),"""
if old not in text:
    raise SystemExit('W-26 sample 锚点不存在')
text = text.replace(old, new, 1)

# ============================================================
# W-26 ③：删掉与走廊剖面打架的旧话
# ============================================================
old = """        'note': '反事实重放：同一份运行计划与同一份气象快照，只改裁决规则；'
                '延期后的风险未重算（本版本没有逐时概率），因此延期不会被判成降险手段。'"""
new = """        'note': '反事实重放：同一份运行计划与同一份气象快照，只改裁决规则。'
                '本快照只重放一次裁决 —— 延期之后的风险不再重算，因此"延期"永远不被记成降险手段'
                '（走廊剖面里的 0–6 h 曲线是概率外推，与这里的单次裁决不是同一件事）。'"""
if old not in text:
    raise SystemExit('W-26 note 锚点不存在')
text = text.replace(old, new, 1)

V2.write_text(text, encoding='utf-8')
print('W-26/25b 后端完成')

# ============================================================
# W-26 前端：明细表标题与分段说明
# ============================================================
cf = CF.read_text(encoding='utf-8')
old = """      <b>改判明细（最多 20 条）</b>"""
new = """      <b>改判明细（最多 20 条 · 真改判优先）</b>
      <small class="cf-sample-note">前段是档位真的变了的班次；后段「低置信 · 留痕未改判」是看过但没动的，
        它们不计入上面的改判架次 —— 两段不可合并读。</small>"""
if old not in cf:
    raise SystemExit('W-26 表头锚点不存在')
cf = cf.replace(old, new, 1)
cf = cf.replace('.cf-sample table', """.cf-sample-note{display:block;margin:2px 0 8px;color:var(--alc-text-dim);font-size:12px;line-height:1.5}
.cf-sample table""", 1)
CF.write_text(cf, encoding='utf-8')
print('W-26 前端完成')

# ============================================================
# W-25b 前端：处置台顶部的「本案例判据」卡
# ============================================================
ops = OPS.read_text(encoding='utf-8')
anchor = '<template v-else-if="view===\'alerts\'">'
if anchor not in ops:
    raise SystemExit('W-25b alerts 视图锚点不存在')
card = """<template v-else-if="view==='alerts'">
      <!-- 0.11.5（W-25b）：首页说"21 条走廊观测已达禁飞级"，这一页原来一句都不提，
           反而写"停止放行全部与天气无关"。两张屏放一起就是自证"判据没进调度"。
           现在把**已经算出来的** B 组结论搬上来：改判架次、绕飞/延误、暴露变化，
           全部来自同一次 `counterfactual(case)` 计算，页面不再出现第二种口径。 -->
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
          这是**判据层**的结论：观测已越过禁飞阈值，按观测档应当处置 {{ casePanels.flightsHandled }} 班。
          <b>下方是实时推演的事件，与这段判据不同源</b> —— 本案例只回放观测，不重跑调度。
        </p>
      </section>
      """
if card.count('**') :
    raise SystemExit('卡片文案里不能有 markdown（W-27 的判据会红）')
ops = ops.replace(anchor, card, 1)

# 卡片所需的 casePanels：从反事实接口按 case 取一次
old_state = "const caseMode=isCaseMode()"
new_state = """const caseMode=isCaseMode()
// W-25b：只在案例模式下取一次。这不是"再算一遍"——`counterfactual` 本身就有缓存，
// 而且它与反事实页读的是同一个 URL，所以两个页面的数字不可能不同。
const casePanels=ref(null)
const activeCaseId=(()=>{try{return new URLSearchParams(window.location.search).get('case')||''}catch(_){return ''}})()
watch(()=>[caseMode,activeCaseId,session.value?.status],async()=>{
  if(!caseMode||!activeCaseId||session.value?.status!=='READY'){casePanels.value=null;return}
  try{
    const value=await requestJson(`/api/traffic/v2/counterfactual?seed=${session.value.seed||42}&scenario=${session.value.scenario||'live'}&policy=balanced&case=${encodeURIComponent(activeCaseId)}`,{timeoutMs:30000})
    casePanels.value=value?.casePanels||null
  }catch(_){casePanels.value=null}
},{immediate:true})"""
if old_state not in ops:
    raise SystemExit('W-25b caseMode 锚点不存在')
ops = ops.replace(old_state, new_state, 1)

# 卡片样式
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

# ============================================================
# W-33：导航里不再同时出现「处置台」与「预警中心」
# ============================================================
rt = RUNTIME.read_text(encoding='utf-8')
old = "  home:'运行首页',overview:'运行总览',briefing:'民航情报',schedule:'调度台账',\n  alerts:'预警中心',weather:'气象监测'"
new = ("  home:'运行首页',overview:'运行总览',briefing:'民航情报',schedule:'调度台账',\n"
       "  // 0.11.5（W-33）：这一页的标题本来就是「事件处置台」，而导航里它曾经叫「预警中心」、\n"
       "  // 入口又叫「处置台」—— 三个词说的是同一个地方，读者要在脑子里做一次映射。\n"
       "  // 现在全站统一叫「事件处置台」：入口、tab、页面标题同一个词。\n"
       "  alerts:'事件处置台',weather:'气象监测'")
if old not in rt:
    raise SystemExit('W-33 SECTION_NAMES 锚点不存在')
rt = rt.replace(old, new, 1)

old = """  alerts: '处置台',
"""
if old not in rt:
    raise SystemExit('W-33 ENTRY_LABELS 锚点不存在')
rt = rt.replace(old, '', 1)
RTEXT = rt
RUNTIME.write_text(rt, encoding='utf-8')
print('W-33 完成：入口与页面统一叫「事件处置台」')
