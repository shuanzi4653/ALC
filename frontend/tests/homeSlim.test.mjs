/**
 * 0.11.5 · W-28 判据：首页减法第一步。
 *
 * **为什么不用"叶子节点 908 → <300"当判据**：报告自己给了两档数据 ——
 * 1680 宽 908、1366 宽 99。同一页面换宽度差 9.17 倍，说明它量的是渲染结果
 * 而不是信息结构。拿它当判据，"改成 1366"就能假通过，而评委用他们自己的屏幕。
 *
 * 这里钉的是**结构**：哪几块还在、哪几块已经不在、解释性文字有没有从卡面收走。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

/**
 * 判据只读**会渲染的部分**。
 *
 * 这一步是踩出来的：删掉一块之后，注释里必然写着"这里原来有一个「气象情报」块，
 * 删掉的理由是……" —— 扫全文就会把**解释为什么删**当成"它还在"。
 * 剥三样：HTML 注释、`<style>` 段、`//` 行注释。
 */
function renderable(source) {
  return source
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<style[\s\S]*?<\/style>/g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

const HOME = renderable(readFileSync(new URL('../src/components/traffic/HomeStage.vue', import.meta.url), 'utf8'))
const BRIEF = renderable(readFileSync(new URL('../src/components/traffic/SituationBrief.vue', import.meta.url), 'utf8'))
const WORK = readFileSync(new URL('../src/components/TrafficWorkbench.vue', import.meta.url), 'utf8')

test('W-28：首页不再有「气象情报」块（它在气象监测页有一整页）', () => {
  assert.ok(!HOME.includes('气象情报'),
    '首页又出现「气象情报」：它与右栏「放行许可」并排，读者要在两个不相干的话题之间来回切')
  // 两个分支都要删干净：只删 v-if 会留下一个孤立的 v-else，构建直接报
  // "v-else/v-else-if has no adjacent v-if" —— 这一步就是踩出来的。
  assert.ok(!HOME.includes('data-case-weather'), 'v-else 分支还在（会与 v-if 成对缺失）')
  // 0.11.24（W-1）：`fam-wx` 这个类名**被重新启用了**，但装的是另一件东西 ——
  // 用户 2026-10-27 明确要求"右下角做一个滚动的各城市气象"。它与当年删掉的
  // 「气象情报」的区别，是这一条判据现在守的东西：
  //   · 不解释判据、不带 METAR 报文（旧的那块在解释"为什么这条走廊被关"）；
  //   · 只有天气现象 / 气温 / 风，且明写"不参与走廊判据"。
  // 所以判据从"类名不许出现"改成"内容不许回到解释判据"。
  assert.ok(!HOME.includes('METAR 报文'), '旧的气象情报内容回来了')
  assert.ok(/不参与走廊判据/.test(HOME), '城市气象条必须自报"不参与判据"，否则读者会拿它解释关停')
})

test('W-28：KPI 的第二行基线说明不再占版面', () => {
  // 收进 title 之后，卡面只剩"数字 + 标签"两行
  assert.ok(!BRIEF.includes('brief-kpi-base'),
    'KPI 卡又长出第二行基线：它回答的是"这个数怎么来的"，不是"我该点哪"')
  assert.ok(/<span class="sr-only">/.test(BRIEF),
    '基线必须仍可被读屏拿到（删掉而不是收起来，是无障碍倒退）')
  assert.ok(/directionNote\(kpi\) \|\| '无基线'/.test(BRIEF), '基线文字要挂在 title 上')
})

test('W-28：图例默认收起，且展开时不推挤地图', () => {
  assert.ok(/<details class="traffic-legend">/.test(WORK), '图例没有收进 details')
  assert.ok(/\.traffic-legend span\{position:absolute/.test(WORK),
    '展开的图例必须浮起来：推挤会把下面的地图在展开瞬间缩放一次')
  // 旧的常驻整行必须删掉，否则两套图例并存
  assert.ok(!WORK.includes('traffic-legend-hint'), '旧的一整行图例还在')
})

test('W-28：首页面板不超过三块（地图 / 放行许可 / 城市气象）', () => {
  // 这是结构判据，与视口宽度无关：`<section class="hs-panel` 的出现次数。
  // 0.11.24（W-1）：上限从 2 提到 3，因为用户要"数据多一点"，右栏下半原本空着；
  // 第三块是**只读的城市气象条**，不新增任何需要解释的概念。
  const panels = HOME.match(/<section class="hs-panel/g) || []
  assert.ok(panels.length <= 3,
    `首页面板数 ${panels.length}：第四块开始就一定是"解释自己为什么存在"的那一块`)
  assert.ok(HOME.includes('data-city-weather'), '第三块应该是城市气象条（带 data-city-weather 钩子）')
})
