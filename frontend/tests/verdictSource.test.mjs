/**
 * 0.11.5 第 1 批判据（W-25a / W-32）。
 *
 * 三条都是"会红"的那种：
 *   · `verdictTone` 映射错了 → 21 条不可飞走廊会染成"留观"色；
 *   · 走廊列表如果又用 `riskLabel(row.pMax)` → 前端第二份档位算法回来了；
 *   · 处置台如果又写"与天气无关" → 首页 21 条禁飞被同一屏否定（0.11.4 的 P0-A）。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { verdictTone, riskLabel } from '../src/traffic/runtime.js'

const PANEL = readFileSync(new URL('../src/components/traffic/CorridorPanel.vue', import.meta.url), 'utf8')
const OPS_RAW = readFileSync(new URL('../src/components/OperationsConsole.vue', import.meta.url), 'utf8')
// 判据只扫**模板段**：注释里会出现"与天气无关"/"排程冲突"这些词（正是解释为什么删掉它们），
// 把注释也算进判据，就变成"谁写注释谁红"。
const OPS = OPS_RAW.slice(OPS_RAW.indexOf('<template>'), OPS_RAW.lastIndexOf('</template>'))
  // 模板段里的 `<!-- -->` 注释同样不算渲染内容（它们正是解释"为什么删掉那句话"）。
  .replace(/<!--[\s\S]*?-->/g, '')

test('档位色只认后端的 verdict 三个值', () => {
  assert.equal(verdictTone('不可飞'), 'danger')
  assert.equal(verdictTone('需谨慎'), 'watch')
  assert.equal(verdictTone('可飞'), 'ok')
  // 未知/缺失必须是 unknown，不能"默认可飞"——那会把没算过的走廊染成安全色
  assert.equal(verdictTone(undefined), 'unknown')
  assert.equal(verdictTone(''), 'unknown')
})

test('走廊列表不得在前端重算档位（第二份算法）', () => {
  // 0.11.4 的实测症状：剖面头写「31% · 不可飞」，左侧列表同一走廊写「31% · 留观」。
  // 根因是列表用 riskLabel(row.pMax) 按概率重算了一遍，而后端 verdict 含观测档。
  assert.ok(!/riskLabel\s*\(\s*row\.pMax\s*\)/.test(PANEL),
    '走廊列表又用 riskLabel(row.pMax) 算档位了 —— 观测档判的「不可飞」会显示成「留观」')
  assert.ok(/row\.verdict/.test(PANEL), '列表必须渲染后端 verdict')
  assert.ok(!/tone-'\s*\+\s*riskTone\(row\.pMax\)/.test(PANEL),
    '列表的颜色也不能按 pMax 算，要和 verdict 同源')
})

test('处置台的案例边界不得否定首页的判据', () => {
  // 0.11.4 的 P0-A：首页「21 条走廊观测已达禁飞级」正下方写「停止放行全部来自
  // 排程越界，与天气无关」。同一个事实，但它读起来是否定前一屏的结论。
  // 用**渲染文案的原句**做锚点，不用行号也不用字符窗口：
  // 这一段的句式是固定的（"…与天气无关。切到「排程冲突」可查看这些事件。"），
  // 一旦有人把这句话加回去，判据必须红。
  assert.ok(!OPS.includes('与天气无关。切到「排程冲突」'),
    '处置台又写回了那句否定式文案（"与天气无关。切到「排程冲突」"）')
  assert.ok(OPS.includes('本案例只回放观测与判据'),
    '必须保留范围声明：本案例只回放观测与判据')
  assert.ok(OPS.includes('<b>不重跑调度</b>'), '范围声明必须明确写出「不重跑调度」')
  assert.ok(!/切到「排程冲突」/.test(OPS), '不得指向不存在的 tab')
  // 0.11.26：出口的落点从隐藏页 `counterfactual` 改成「推演」（`card`）。
  // 0.11.22 起反事实并进推演第 6 步、退出导航，0.11.24 又把台账并成第 8 步；
  // 再指 `counterfactual` 等于把读者送到一个导航上不存在的页面。
  // 判据守的是"给得出出口"，落点跟着信息架构走。
  assert.ok(/open-section','card'/.test(OPS),
    '必须给出「那天气去哪了」的出口：一个真的能跳到推演第 6 步（对照）的控件')
  assert.ok(!/open-section','counterfactual'/.test(OPS),
    '不得再指向已退出导航的反事实页')
})

test('前端不许把「没有数字」显示成 0（沿用既有纪律，防止这次改回）', () => {
  // `riskLabel` 的存在本身没错（它服务概率列表），但它的文档必须说明它只吃概率。
  assert.equal(typeof riskLabel, 'function')
  assert.equal(riskLabel(0.31), '留观', '概率 31% 的语义档是「留观」——这是概率口径，不是判定口径')
})

// ── V1.1.2：同一个裁决只能有一个来源 ────────────────────────────────────────
//
// 1.1.1 的实测症状：推演页板头「无论绕飞还是停飞都写直飞放行」，判据段「4/4 通过」
// 与左侧「暂不放行」并排。根因是取证链路少传三个输入（模型概率、绕飞封禁、虚拟气象），
// 而板头又读取证接口的裁决 —— 两套路径各算一次，谁也不知道对方算出了什么。
const deduce = readFileSync(new URL('../src/components/traffic/NationDeduce.vue', import.meta.url), 'utf8')
const nationPanel = readFileSync(new URL('../src/components/traffic/NationPanel.vue', import.meta.url), 'utf8')
const corridorBrowser = readFileSync(new URL('../src/components/traffic/CorridorBrowser.vue', import.meta.url), 'utf8')

test('推演板头裁决只读列表侧，不读取证数据', () => {
  assert.ok(deduce.includes('{{ flight.decisionLabel }}'),
    '板头应读 props.flight.decisionLabel（含模型门槛与绕飞封禁）')
  assert.ok(!deduce.includes('data?.flight?.decisionLabel'),
    '不得再用 data.flight.decisionLabel 兜底 —— 那是取证链路的裁决')
  assert.ok(deduce.includes('裁决：<b :class="tone">{{ flight.decisionLabel }}</b>'),
    '第 3 段的裁决行同样要跟列表同源')
})

test('取证请求必须带 virtual，否则虚拟气象下两侧必然分叉', () => {
  assert.ok(deduce.includes("props.virtual?'&virtual=1'"), '推演板取证缺 virtual')
  assert.ok(nationPanel.includes("virtualWx.value?'&virtual=1'"), '取证页缺 virtual')
})

test('走廊页缺字段时不兜底成「直飞放行」', () => {
  assert.ok(!corridorBrowser.includes("'直飞放行'"),
    "兜底值不得是「直飞放行」：缺字段会被读成“可以直接飞”")
  assert.ok(corridorBrowser.includes("'未判定'"), '缺字段应显式写「未判定」')
})

test('后端取证链路与 /nation/flights 同参：模型概率 + 绕飞封禁 + 虚拟', () => {
  const py = readFileSync(new URL('../../backend-python/traffic/nation.py', import.meta.url), 'utf8')
  const start = py.indexOf('def _evidence_locked')
  const body = py.slice(start, py.indexOf('def evidence(', start))
  assert.ok(start > 0 && body.length > 0, '找不到 _evidence_locked')
  assert.ok(body.includes('_model_probs()'), '取证未传模型概率（MODEL_HOLD 门槛失效）')
  assert.ok(body.includes('blocked_ids=blocked_ids'), '取证未传绕飞封禁（无小绕的走廊会被判成可飞）')
  assert.ok(body.includes('_virtual_'), '取证不认虚拟气象')
})

test('模型概率缺失时判据仍出 ABSENT 行，不静默少一条', () => {
  const py = readFileSync(new URL('../../backend-python/traffic/nation.py', import.meta.url), 'utf8')
  const start = py.indexOf("if flight.get('pModel') is not None:")
  assert.ok(start > 0, '找不到模型判据分支')
  const tail = py.slice(start, start + 1800)
  assert.ok(tail.includes("'source': 'ABSENT'"),
    '缺少 ABSENT 兜底行：判据会少一条，页脚就会出现「4/4 通过」')
})

