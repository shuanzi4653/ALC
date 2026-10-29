# -*- coding: utf-8 -*-
"""0.11.5 第 2 批 · 修正（自查发现两处新的自相矛盾）。

发现 1：`casePanels.corridorsAtBan` = **36**，而首页 KPI 写 **21**。
  36 是"被航班飞到的、观测达禁飞级的走廊"；21 是"全部 53 条里 verdict 判不可飞的"。
  两个数**都对**，但放在同一屏就是第二次 P0-A。处置台这张卡的任务是"给首页那 21 条
  一个下文"，所以它必须用**首页那个数**。改法：后端不产出走廊数（免得出现第三个来源），
  前端从 `overview` 的 `kpis[high]` 取 —— 那本来就是首页显示的那个字段。

发现 2：明细表前 20 行全是 `changed=True`，但"规则 / 融合后"仍显示 `0 / 0`。
  因为 `changed` 含 `obsBan`（观测档改判），而 `fusedLevel` 只反映概率+规则的融合。
  于是"改判 3048"下面挂着 20 行 `0 / 0` —— 报告的 P0-D 原样还在。
  改法：records 增加 `effectiveLevel`（观测禁飞 → 2），表格显示它，并在依据列标"观测档"。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / 'backend-python' / 'traffic' / 'v2.py'
OPS = ROOT / 'frontend' / 'src' / 'components' / 'OperationsConsole.vue'
CF = ROOT / 'frontend' / 'src' / 'components' / 'traffic' / 'CounterfactualPanel.vue'

text = V2.read_text(encoding='utf-8')

# ---- 1) records 增加 effectiveLevel ----
old = """                        'confidence': round(confidence, 4),
                        'note': fused_note if changed else '低置信 · 留痕未改判'})"""
new = """                        'confidence': round(confidence, 4),
                        # 0.11.5：**真正生效的档位**。`fusedLevel` 只融合了概率与规则，
                        # 而观测档改判走的是另一条分支（`obsBan`）。表格如果只显示
                        # `fusedLevel`，"改判 3048"下面就会挂 20 行 `0 / 0` ——
                        # 读者看到"什么都没改"，而事实是"改成了禁飞，凭的是观测"。
                        'effectiveLevel': 2 if obs_ban else fused,
                        'note': fused_note if changed else '低置信 · 留痕未改判'})"""
if old not in text:
    raise SystemExit('records 锚点不存在')
text = text.replace(old, new, 1)

# ---- 2) casePanels 不再产出走廊数（第三来源） ----
old = """            'corridorsAtBan': len(ban_corridors),"""
new = """            # 走廊数**不在这里算**：首页的 21 来自 `overview.kpis[high]`，
            # 而这里能算出的"被飞到的禁飞走廊"是 36 —— 两个数都对，但并排就是矛盾。
            # 卡片的任务是给首页那 21 条一个下文，所以它用首页那个数（由前端填）。"""
if old not in text:
    raise SystemExit('corridorsAtBan 锚点不存在')
text = text.replace(old, new, 1)

V2.write_text(text, encoding='utf-8')
print('后端：effectiveLevel 已加，corridorsAtBan 已移除')

# ---- 3) 前端：卡片走廊数从 overview 取 ----
ops = OPS.read_text(encoding='utf-8')
old = """  try{
    const value=await requestJson(`/api/traffic/v2/counterfactual?seed=${session.value.seed||42}&scenario=${session.value.scenario||'live'}&policy=balanced&case=${encodeURIComponent(activeCaseId)}`,{timeoutMs:45000})
    casePanels.value=value?.casePanels||null
  }catch(_){casePanels.value=null}"""
new = """  try{
    // 两个请求同发：走廊数必须与首页**同一个字段**（`overview.kpis[high]`），
    // 不能在这里另算一遍 —— 另算出来的 36 与首页的 21 并排就是新的自相矛盾。
    const query=`seed=${session.value.seed||42}&scenario=${session.value.scenario||'live'}&case=${encodeURIComponent(activeCaseId)}`
    const [cf,ov]=await Promise.all([
      requestJson(`/api/traffic/v2/counterfactual?${query}&policy=balanced`,{timeoutMs:45000}),
      requestJson(`/api/traffic/v2/overview?${query}`,{timeoutMs:30000}),
    ])
    const panels=cf?.casePanels
    const high=(ov?.kpis||[]).find(k=>k.key==='high')?.value
    casePanels.value=panels?{...panels,corridorsAtBan:typeof high==='number'?high:null}:null
  }catch(_){casePanels.value=null}"""
if old not in ops:
    raise SystemExit('casePanels 请求锚点不存在')
ops = ops.replace(old, new, 1)

# 走廊数可能是 null（overview 没算完）——不能印 "null 条"
ops = ops.replace(
    "<div><small>观测已达禁飞级</small><b>{{ casePanels.corridorsAtBan }} 条走廊</b></div>",
    "<div><small>观测已达禁飞级</small><b>{{ casePanels.corridorsAtBan == null ? '—' : casePanels.corridorsAtBan + ' 条走廊' }}</b></div>", 1)
OPS.write_text(ops, encoding='utf-8')
print('前端：走廊数改从 overview 取')

# ---- 4) 明细表：显示 effectiveLevel + 依据 ----
cf = CF.read_text(encoding='utf-8')
old = """        <thead><tr><th>航班</th><th>走廊</th><th>不可飞概率</th><th>置信度</th><th>规则</th><th>融合后</th><th>理由</th></tr></thead>"""
new = """        <thead><tr><th>航班</th><th>走廊</th><th>不可飞概率</th><th>置信度</th><th>规则</th><th>生效后</th><th>依据</th><th>理由</th></tr></thead>"""
if old not in cf:
    raise SystemExit('表头锚点不存在')
cf = cf.replace(old, new, 1)

old = """            <td class="alc-num">{{ r.ruleLevel }}</td>
            <td class="alc-num" :class="r.fusedLevel>r.ruleLevel?'strict':''">{{ r.fusedLevel }}</td>
            <td class="note">{{ r.note }}</td>"""
new = """            <td class="alc-num">{{ r.ruleLevel }}</td>
            <!-- 0.11.5：显示**生效后**的档位，而不是只融合了概率的 fusedLevel。
                 观测档改判时 fused 仍是 0，于是"改判 3048"下面挂 20 行 0/0。 -->
            <td class="alc-num" :class="(r.effectiveLevel??r.fusedLevel)>r.ruleLevel?'strict':''">{{ r.effectiveLevel??r.fusedLevel }}</td>
            <td class="note">{{ r.obsBan ? '观测档' : (r.fusedLevel !== r.ruleLevel ? '概率档' : '—') }}</td>
            <td class="note">{{ r.note }}</td>"""
if old not in cf:
    raise SystemExit('表格行锚点不存在')
cf = cf.replace(old, new, 1)
CF.write_text(cf, encoding='utf-8')
print('前端：明细表显示生效档位与依据')
