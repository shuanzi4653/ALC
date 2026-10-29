import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {dispositionSummary} from '../src/traffic/runtime.js'

// K-4（0.11.27）：用户 2026-10-27 指着首屏问——
// 「最上面的框里面的数据；复核与触发停飞、平均提前量数字；右下方的放行率、
//   时隙重排、改航绕飞、停止放行。这些数据应该是同步且公用的，请检查，
//   避免出现同一页面的数据不同这种情况。」
//
// 两组数各自都对，但它们是**两个域**：
//   上 = 走廊级判据（三站 METAR，本帧计数）
//   下 = 班次级处置（本场景计划，含管制区/时隙/边界等非气象成因）
// 要防的不是数字错，而是它们被并排读成同一次求值 —— 所以每一处都要能自证口径。

const BRIEF = readFileSync(new URL('../src/components/traffic/SituationBrief.vue', import.meta.url), 'utf8')
const HOME = readFileSync(new URL('../src/components/traffic/HomeStage.vue', import.meta.url), 'utf8')

// ---------------------------------------------------------------------------
// 一、页脚的「停止放行」必须自带气象成因
// ---------------------------------------------------------------------------
test('停止放行后面必须跟气象成因', () => {
  const text = dispositionSummary({accepted:6906, closed:854, detours:18, groundHolds:3674, closedByWeather:0})
  assert.match(text, /停止放行 854（气象 0）/,
    '只写"停止放行 854"，与顶部的「已触发停飞判据 0 条」并排就是自相矛盾')
  // 其余三项保持原样：这是同一个函数、同一份 stats，不新造数。
  assert.match(text, /放行率 89%/)
  assert.match(text, /时隙重排 3674/)
  assert.match(text, /改航绕飞 18/)
})

test('气象成因非零时如实写出，不做概括', () => {
  const text = dispositionSummary({accepted:900, closed:100, detours:0, groundHolds:0, closedByWeather:37})
  assert.match(text, /停止放行 100（气象 37）/)
})

test('没有关闭时不写"（气象 0）"', () => {
  // 0 班时再补一句"其中气象 0 班"是两遍同一件事，而且会让一行小字变得读不下去。
  const text = dispositionSummary({accepted:7760, closed:0, detours:0, groundHolds:3638, closedByWeather:0})
  assert.match(text, /停止放行 0/)
  assert.doesNotMatch(text, /停止放行 0（/)
  assert.doesNotMatch(text, /气象/)
})

test('stats 缺 closedByWeather 时不许写成 NaN', () => {
  // 旧载荷（缓存里的计划、离线归档）没有这个键。`Number(undefined)` 是 NaN，
  // 直接拼进句子就是「停止放行 12（气象 NaN）」—— 与 M-类"把缺失当 0"同类。
  const text = dispositionSummary({accepted:100, closed:12, detours:0, groundHolds:0})
  assert.match(text, /停止放行 12（气象 0）/)
  assert.doesNotMatch(text, /NaN/)
})

// ---------------------------------------------------------------------------
// 二、首屏三格：离线的那一格必须自报"离线"
// ---------------------------------------------------------------------------
test('平均提前量按后端 scope 打「离线」角标，不在前端判断', () => {
  assert.match(BRIEF, /kpi\.scope\s*===\s*'offline'/,
    '角标必须读后端给的 scope，前端自己判断就等于第二套口径')
  assert.match(BRIEF, /class="brief-kpi-scope"[^>]*>离线</,
    '角标文字必须落在卡面上，不能只进 title')
})

test('首屏必须写清"两组数分别求值"及其分母', () => {
  assert.match(BRIEF, /data-brief-scope/, '分工说明没渲染出来')
  assert.match(BRIEF, /planStats/, '分工说明要用本场景的 stats 才算得出分母')
  assert.match(BRIEF, /全量 \$\{s\.flights\} 班/, '必须写分母（全量），否则抽样/全量分不清')
  assert.match(BRIEF, /停止放行 \$\{closed\} 班（气象 \$\{weather\}）/, '必须写出停止放行里的气象成因')
})

test('计划身份变了要立刻重取走廊判据', () => {
  // 同情景重算（换通道 / 按重新调度 / 跨工作区共享）时 `planScenario` 一个字都没变，
  // 只按情景 watch 会让上面三格停在旧帧，而页脚已经是新计划 —— 又回到"同一页两组数"。
  assert.match(BRIEF, /watch\(\(\)\s*=>\s*props\.planId/, '没有监听 planId')
})

test('首页把整份 plan.stats 传给结论条', () => {
  assert.match(HOME, /:plan-stats="plan\?\.stats\|\|null"/)
  // 页脚那组数的分母必须写出来：854 / 7760 与右栏的"抽样 / 7760"才接得上。
  assert.match(HOME, /本轮处置（延迟优先 · 全量 \{\{ planFleet \}\} 班）/)
})

// ---------------------------------------------------------------------------
// 四、地图上的事件徽标：范围必须写在字面上
// ---------------------------------------------------------------------------
test('选了城市之后，地图事件徽标要说明自己是"本城"', () => {
  // 徽标数的是 `scoped`（按机型开关与城市过滤过），页脚那组是全量。
  // 两处都叫"停止放行"、数字却不同 —— 范围不写出来，读者只能判它算错。
  const MAP = readFileSync(new URL('../src/components/CityTrafficMap.vue', import.meta.url), 'utf8')
  assert.match(MAP, /const scope=props\.city\?'本城':''/,
    '城市筛选生效时，徽标必须自报"本城"，否则与页脚的全量数无法区分')
  assert.match(MAP, /short:`\$\{scope\}运行事件/)
})

// ---------------------------------------------------------------------------
// 三、时间轴上限：同一份计划只能有一个终点
// ---------------------------------------------------------------------------
test('首页与工作台的时间轴上限同源', () => {
  // 0.11.26 撤掉时间闸门后计划可以越过 480 分钟（实测 787）。工作台改了，
  // 首页漏改 —— 同一份计划，首页滑块标 T+08:00、工作台标 T+13:07：
  // 首页拖到底也画不出 07:00 之后落地的班次，它们永远挂在空中。
  const WORKBENCH = readFileSync(new URL('../src/components/TrafficWorkbench.vue', import.meta.url), 'utf8')
  assert.match(HOME, /props\.plan\?\.timelineMinutes/, '首页没读计划自报的时间轴上限')
  assert.match(WORKBENCH, /session\.value\?\.timelineMinutes/, '工作台没读计划自报的时间轴上限')
  // 案例窗口优先：回放案例的时长与实时计划无关，不能被 timelineMinutes 顶掉。
  assert.match(HOME, /caseMeta\(\)[\s\S]{0,120}durationMinutes/,
    '案例窗口必须仍然优先，否则雾案例会被实时上限拉长')
})
