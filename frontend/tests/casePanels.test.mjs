/**
 * 0.11.5 第 2 批判据（W-26 / W-25b / W-33）。
 *
 * 这三条的共同点：**都是"两处说法打架"**，而且都能用静态断言钉住，
 * 不需要截图。
 *   · W-26：明细表切前 20 条 vs "改判 3048"；
 *   · W-25b：首页 21 条禁飞 vs 处置台气象成因 0；
 *   · W-33：导航里"处置台"与"预警中心"并排。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { SECTION_NAMES, ENTRY_LABELS, entryOf, entryTabs, navEntryCount } from '../src/traffic/runtime.js'

const OPS = readFileSync(new URL('../src/components/OperationsConsole.vue', import.meta.url), 'utf8')
  .slice(0,
    readFileSync(new URL('../src/components/OperationsConsole.vue', import.meta.url), 'utf8').lastIndexOf('</template>'))
  .replace(/<!--[\s\S]*?-->/g, '')
const V2 = readFileSync(new URL('../../backend-python/traffic/v2.py', import.meta.url), 'utf8')
const PANEL = readFileSync(new URL('../src/components/traffic/CounterfactualPanel.vue', import.meta.url), 'utf8')

test('W-25b：处置台必须显示「本案例判据」，且数字来自接口不写死', () => {
  assert.ok(OPS.includes('data-case-panels'), '处置台缺 [data-case-panels] 卡片')
  assert.ok(OPS.includes('本案例判据'), '卡片标题必须明写「本案例判据」')
  // 四个数字必须绑在 casePanels 上：写死数字是最难发现的一类错（它永远自洽）
  for (const field of ['corridorsAtBan', 'flightsHandled', 'rerouted', 'delayed', 'exposureA', 'exposureB']) {
    assert.ok(OPS.includes('casePanels.' + field), `卡片没有引用 casePanels.${field}（可能写死了）`)
  }
  // 卡片与下方实时事件必须声明"不同源"，否则又变成"气象没有进调度"的自证
  assert.ok(OPS.includes('与这段判据不同源'), '卡片必须声明与下方实时事件不同源')
})

test('W-25b：后端必须用同一次计算产出 casePanels（不新增求值）', () => {
  assert.ok(V2.includes("'casePanels'"), 'counterfactual 没有返回 casePanels')
  // 0.11.5 修正：**不许在这里算走廊数**。counterfactual 能算出"被飞到的禁飞走廊 36"，
  // 而首页写的是"verdict 判不可飞 21"——两个数都对，并排就是第二次 P0-A。
  // 所以卡片用首页那个字段（前端从 overview 取），这里连变量都不留。
  assert.ok(!V2.includes('ban_corridors'), 'counterfactual 又自己算了一遍走廊数（第三来源）')
  assert.ok(/corridorsAtBan/.test(OPS), '卡片仍在引用 corridorsAtBan（应由 overview 填充）')
  // 防空转：casePanels 只在有 case 时返回（实时模式不该出现"本案例判据"）
  assert.ok(/if case_id else None/.test(V2), 'casePanels 必须按 case 有无决定是否返回')
})

test('W-26：明细表必须是「真改判优先」，0→0 的行不许叫改判', () => {
  // 按原顺序切前 20 条时，前 20 恰好全是低置信样本 → 与"改判 3048"打架
  assert.ok(/sorted\(\[r for r in records if r\['changed'\]\]/.test(V2),
    'sample 没有按 changed 优先排序')
  assert.ok(V2.includes("'低置信 · 留痕未改判'"),
    '0→0 的行必须改叫「留痕未改判」，不能与真改判共用一句理由')
  // 那句与走廊剖面打架的旧话必须删掉
  assert.ok(!V2.includes('延期后的风险未重算（本版本没有逐时概率）'),
    '旧句「本版本没有逐时概率」与走廊剖面的 0–6 h 曲线矛盾，必须改')
  assert.ok(PANEL.includes('真改判优先'), '表头必须说明取样规则')
  assert.ok(PANEL.includes('两段不可合并读'), '两段混读会重新造成"改判 3048 但明细 0/0"')
})

test('W-33：导航里不许同时出现「处置台」与「预警中心」', () => {
  const alertsEntry = entryOf('alerts')
  assert.equal(alertsEntry.key, 'alerts')
  assert.equal(SECTION_NAMES.alerts, '事件处置台',
    '这一页的标题本来就是「事件处置台」，导航里必须同名')
  assert.equal(alertsEntry.label, '事件处置台', '入口名必须与页面同名')
  // 全站只留两个「上位词」入口名（检验结论 / 复盘对照）
  // 0.11.22：复盘对照并入推演 ⇒ 只剩一个上位词入口名。
  assert.deepEqual(Object.keys(ENTRY_LABELS).sort(), ['card'])
  // 入口名不得与它自己成员的视图名重复
  const tabLabels = entryTabs('alerts').map((t) => t.label)
  // 0.11.10：tab 条里**不许再出现与入口同名的项**。原来这里断言 tabLabels[0]
  // 就是「事件处置台」，于是界面上并排渲染出两个同名按钮（入口 + 首个 tab）。
  // 名字一致是对的，同一个名字渲染两遍不是。
  assert.ok(!tabLabels.includes('事件处置台'), 'tab 条里重复出现入口名')
  assert.equal(new Set(tabLabels).size, tabLabels.length, 'tab 条里出现重复词')
  // 入口总数不变
  assert.equal(navEntryCount(), 8)
})
