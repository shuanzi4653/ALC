// 计划与地图必须来自同一个气象通道 —— 这条契约的两半，一半是纯逻辑，一半是源码静态断言。
//
// 用户 2026-09-30 的报告（附截图）：「这里不是就有飞机在禁飞区吗？怎么没有实现绕行？
// 全局的绕飞似乎都不可控」。链路每一段都是对的：计划按**实测**回波建（禁止内核为空、
// 场强纬度上界够不到吉林），地图画的是**虚拟**回波（整片盖住吉林）。两个通道，一块屏。
//
// 后端把通道并进了会话键，所以切通道＝换计划 —— 但**前提是真的重新请求**。这一条检查
// 钉住两件前端必须做的事：
//   1. 切换通道要重建计划，而不能只换一帧（否则"地图变了、计划没变"是默认状态）；
//   2. 计划与地图通道不一致时，画面上必须出现一句说明（否则同一个误解会从另一条路回来）。
//
// 第 2 条的判据放在 runtime.js，因为 .vue 的私有函数 `node --test` 够不着；这里只对
// 「组件确实把它渲染出来了」做静态断言，与 mapLayerContracts.test.mjs 同样的理由 ——
// 构建不跑模板求值，所以"存在"必须从源码读。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  WEATHER_MODE_MEASURED, WEATHER_MODE_VIRTUAL, planChannelMismatch,
  clearanceLines, metarLines, metarOrder, sigmetRows, sigmetThresholdNote, observationVisibilityM,
} from '../src/traffic/runtime.js'

const here = dirname(fileURLToPath(import.meta.url))
const view = await readFile(join(here, '..', 'src', 'components', 'TrafficWorkbench.vue'), 'utf8')

// ---------------------------------------------------------------- 判据本身

test('两个通道一致时不出声', () => {
  for (const mode of [WEATHER_MODE_MEASURED, WEATHER_MODE_VIRTUAL]) {
    assert.equal(planChannelMismatch(mode, mode), '')
  }
})

test('计划与地图通道不一致时必须说出是哪两个通道', () => {
  const mismatch = planChannelMismatch(WEATHER_MODE_MEASURED, WEATHER_MODE_VIRTUAL)
  assert.notEqual(mismatch, '')
  assert.match(mismatch, /实测/)
  assert.match(mismatch, /虚拟/)
  // 「不是算法失效」这句是这句话存在的理由：上次操作员看到红区里的飞机，怀疑的是
  // 整套绕飞能力。不含这句，告警就退回成一条没有解释的红字。
  assert.match(mismatch, /不是算法失效/)
  assert.match(mismatch, /重新调度/)
})

test('反方向同样出声，且不共用同一句话', () => {
  const forward = planChannelMismatch(WEATHER_MODE_MEASURED, WEATHER_MODE_VIRTUAL)
  const backward = planChannelMismatch(WEATHER_MODE_VIRTUAL, WEATHER_MODE_MEASURED)
  assert.notEqual(backward, '')
  assert.notEqual(backward, forward)
})

test('不知道计划用的哪个通道时不猜，也不报警', () => {
  // 缺 `weatherMode` 的旧计划确实存在（磁盘上的历史文件）。用默认值硬判成"实测"，
  // 会在切到虚拟的第一秒凭空造出一条告警，而那条告警的依据是猜的。
  for (const value of [undefined, null, '']) {
    assert.equal(planChannelMismatch(value, WEATHER_MODE_VIRTUAL), '')
  }
})

test('返回的永远是字符串，不是 undefined', () => {
  for (const plan of [undefined, null, 'measured', 'virtual', 'junk']) {
    for (const live of [undefined, null, 'measured', 'virtual']) {
      assert.equal(typeof planChannelMismatch(plan, live), 'string', `${plan}/${live}`)
    }
  }
})

// ------------------------------------------------- 组件：切换必须重建计划

test('切换气象通道会重建计划，而不只是换一帧', () => {
  const body = /async function onWeatherModeChange\([\s\S]*?\n\}/.exec(view)
  assert.ok(body, 'TrafficWorkbench.vue 里找不到 onWeatherModeChange')
  assert.match(body[0], /generate\(\)/,
    '切换通道没有重建计划：地图换了、计划没换，正是 2026-09-30 报的那个现象')
  assert.match(body[0], /loadWeatherMode\(\)/,
    '切换后必须重新读取控制器状态，否则按钮文案与真实通道可能不一致')
})

test('通道不一致的告警确实被渲染出来，而不是只算好了放着', () => {
  assert.match(view, /planChannelMismatch\(session\.value\?\.weatherMode,weatherMode\.value\)/,
    '组件没有按「计划的通道 vs 地图的通道」计算告警')
  assert.match(view, /\{\{channelMismatch\}\}/,
    '算了告警却没有渲染，等于没有')
  assert.match(view, /v-if="[^"]*channelMismatch/,
    '告警缺少显示条件')
})

test('告警带一个能直接修复它的按钮', () => {
  const block = /traffic-channel-warning[\s\S]*?<\/div>/.exec(view)
  assert.ok(block, '找不到告警块')
  assert.match(block[0], /@click="generate"/, '告警必须能一键按当前通道重建计划')
})

// --- 2026-10-01 第 3 条：民航式放行许可的呈现 ---------------------------------
// 许可结构由后端 _clearance_record 组装；这里钉住的是**呈现**。判据是"一个没看过
// 本系统的人能否照着它复诵"，因此缺要素时必须明说缺哪个，而不是填一个像样的默认值。
// （clearanceLines 已在文件顶部的 import 中引入 —— 这里不再单独 import 一次。）

test('a clearance reads as a recitable list in a fixed order',()=>{
  const rows=clearanceLines({
    callsign:'CAR-1-01-1-05-0-0',limit:'东北三省低空协同运行边界',route:'CITY-1-01 — CITY-1-05',
    assignedLevelAglM:500,ctot:{from:'2026-09-14T10:00:00Z',until:'2026-09-14T10:15:00Z',validityMinutes:15},
    weatherBasis:'实测气象通道（公开观测）；原时隙走廊已清，按申请时刻放行',
  })
  assert.deepEqual(rows.map(r=>r.label),
    ['呼号','放行界限','航路','指派高度层','离场时隙 CTOT','气象判据'],
    '要素顺序即复诵顺序，不得随数据有无而改变')
  assert.match(rows[3].value,/500 m AGL/)
  assert.match(rows[4].value,/15 分钟/)
  assert.match(rows[5].value,/实测气象通道/)
})

test('a clearance states a missing element instead of inventing one',()=>{
  // 没有指派高度层时写"未指派高度层"。写 0 m 会被读成"许可在 0 米飞行"，
  // 那是把缺失伪装成一个值 —— 这条断言是这一节的全部意义。
  const rows=clearanceLines({callsign:'X',route:'A — B',assignedLevelAglM:null,ctot:null})
  const level=rows.find(r=>r.label==='指派高度层')
  assert.match(level.value,/未指派高度层/)
  assert.doesNotMatch(level.value,/0 m/)
  const slot=rows.find(r=>r.label==='离场时隙 CTOT')
  assert.match(slot.value,/未取得时隙/)
  // 没有气象判据时必须说出来 —— 气象是本系统的主导约束，缺了它许可不完整。
  const basis=rows.find(r=>r.label==='气象判据')
  assert.match(basis.value,/未声明气象判据/)
  // 没有许可对象时返回空数组，而不是一行"—"占位。
  assert.deepEqual(clearanceLines(null),[])
  assert.deepEqual(clearanceLines(undefined),[])
})

// --- 民航式气象情报（METAR / SIGMET 式）-------------------------------------
// 用户 2026-10-01 第 3 条：「本项目可以尽可能贴近民航飞行的管理系统」。
// 这组判据钉住的是**不能撒谎的那几件事**，不是排版。

test('能见度只按判定用的那一套取法读取', () => {
  // 后端 _first_visibility：先标量 visibilityM，再 hourly.visibility 的第一个非空值。
  // 面板必须逐字一致 —— 否则会出现"面板报 10 km、风险引擎按 5 km 划内核"。
  assert.equal(observationVisibilityM({ visibilityM: 800 }), 800)
  assert.equal(observationVisibilityM({ hourly: { visibility: [null, 5000, 9000] } }), 5000)
  // 标量存在时优先于 hourly，和后端的分支顺序一致。
  assert.equal(observationVisibilityM({ visibilityM: 200, hourly: { visibility: [5000] } }), 200)
  assert.ok(Number.isNaN(observationVisibilityM({})))
  assert.ok(Number.isNaN(observationVisibilityM({ hourly: { visibility: [null] } })))
})

test('观测报文把"未报出"与"报出零值"分开', () => {
  // 能见度 0 米意味着垂直能见度为零（机场关闭），而未报出能见度是"不知道"。
  // 两者在报文里必须是不同的字符串。
  const missing = metarLines({ cityName: '沈阳', windSpeed10mMps: 3, windDirection10mDeg: 200 })
  assert.equal(missing.find(r => r.label === '能见度').value, '//')
  const zero = metarLines({ cityName: '沈阳', visibilityM: 0 })
  assert.equal(zero.find(r => r.label === '能见度').value, '0.0 km')
  // 气温同理：0 ℃ 是有效读数，不能因为 `0` 是 falsy 就报成缺报。
  const freezing = metarLines({ cityName: '哈尔滨', temperatureC: 0 })
  assert.equal(freezing.find(r => r.label === '气温').value, '0 ℃')
})

test('能见度以米存储、以公里报出，不做千米混读', () => {
  assert.equal(metarLines({ cityName: '长春', visibilityM: 10000 }).find(r => r.label === '能见度').value, '10 km')
  assert.equal(metarLines({ cityName: '长春', visibilityM: 800 }).find(r => r.label === '能见度').value, '0.8 km')
  // hourly 支线的读数同样报成公里。
  assert.equal(metarLines({ cityName: '长春', hourly: { visibility: [19600] } }).find(r => r.label === '能见度').value, '20 km')
})

test('风速报文补齐三位风向与两位风速', () => {
  const rows = metarLines({ cityName: '大连', windSpeed10mMps: 5.4, windDirection10mDeg: 70 })
  // 07005MPS：70° 补到三位，5.4 取整到 5 再补到两位（报文不保留小数）。
  assert.match(rows.find(r => r.label === '风向风速').value, /^07005MPS$/)
  // 静风是报文里的既有写法，不是兜底。
  const calm = metarLines({ cityName: '大连', windSpeed10mMps: 0, windDirection10mDeg: 0 })
  assert.equal(calm.find(r => r.label === '风向风速').value, '00000MPS')
  // 风速缺报时才写 //。
  assert.equal(metarLines({ cityName: '大连' }).find(r => r.label === '风向风速').value, '//')
})

test('观测报文按严重程度排序，且同分时顺序稳定', () => {
  const ordered = metarOrder([
    { cityName: '良', visibilityM: 20000, windSpeed10mMps: 2 },
    { cityName: '差', visibilityM: 500, windSpeed10mMps: 9 },
    { cityName: '中', visibilityM: 8000, windSpeed10mMps: 4 },
  ])
  assert.deepEqual(ordered.map(o => o.cityName), ['差', '中', '良'])
  // 能见度相同时风速大者在前。
  const tie = metarOrder([
    { cityName: 'A', visibilityM: 5000, windSpeed10mMps: 3 },
    { cityName: 'B', visibilityM: 5000, windSpeed10mMps: 12 },
  ])
  assert.deepEqual(tie.map(o => o.cityName), ['B', 'A'])
  // 全同分时按站名收尾 —— 否则翻页时表格会跳动。
  const names = ['乙', '甲']
  const stable = metarOrder([
    { cityName: '乙', visibilityM: 5000, windSpeed10mMps: 3 },
    { cityName: '甲', visibilityM: 5000, windSpeed10mMps: 3 },
  ])
  assert.deepEqual(stable.map(o => o.cityName), names.slice().sort((a, b) => a.localeCompare(b)))
})

test('危险天气情报自称系统派生，不冒充官方 SIGMET', () => {
  const report = sigmetRows({
    cells: [{ id: 'LIVE-210100', kind: 'STORM', memberCount: 1, source: 'OPEN_METEO_DERIVED_RISK' }],
    extremeThresholds: { gustMps: 17, visibilityM: 1000, hourlyRainMm: 8, coreRadiusM: 6000 },
  })
  // 报头必须写明是系统派生。冒充真实气象中心识别码会凭空生成"官方已发布"的声明。
  assert.match(report.heading, /系统派生/)
  assert.match(report.note, /不是任何气象中心发布的 SIGMET/)
  assert.doesNotMatch(report.heading, /WSSS|ZSHA|ZBBB/)
  assert.equal(report.entries[0].kind, '雷暴')
  assert.equal(report.entries[0].status, 'ACTIVE')
})

test('危险天气情报的阈值来自数据面而不是写死在文案里', () => {
  // 写死数字的文案会在有人调整阈值后继续宣称旧值。这里改一个阈值，文案必须跟着变。
  const a = sigmetThresholdNote({ gustMps: 17, visibilityM: 1000, hourlyRainMm: 8, coreRadiusM: 6000 })
  assert.match(a, /阵风 ≥ 17 m\/s/)
  assert.match(a, /能见度 < 1 km/)
  assert.match(a, /小时雨量 ≥ 8 mm/)
  assert.match(a, /内核半径 6 km/)
  const b = sigmetThresholdNote({ gustMps: 25, visibilityM: 500, hourlyRainMm: 20, coreRadiusM: 9000 })
  assert.match(b, /阵风 ≥ 25 m\/s/)
  assert.doesNotMatch(b, /17/)
  assert.equal(sigmetThresholdNote(null), '')
})

test('无风险区时危险天气情报报 NIL 而不是空标题', () => {
  const report = sigmetRows({ cells: [] })
  assert.match(report.heading, /NIL/)
  assert.deepEqual(report.entries, [])
})

test('合并出来的风险区必须写明成员', () => {
  const report = sigmetRows({
    cells: [{ id: 'MERGED-1', kind: 'RAIN', memberCount: 3, sources: ['210100::a', '220100::b', '230100::c'], source: 'X' }],
  })
  assert.equal(report.entries[0].status, 'MERGED')
  assert.match(report.entries[0].body, /3 个单体合并/)
  assert.match(report.entries[0].body, /210100/)
})
