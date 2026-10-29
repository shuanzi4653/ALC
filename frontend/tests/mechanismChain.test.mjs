// 算法机理（0.9.26 / AL-5）—— 一条「算法必须说得出过程」的契约。
//
// 背景（工程表述）：这个系统一直能说出**结果**（多少班改航、多少班关闭、风险区画在
// 哪里），却没有任何一处说出**过程**：判据是哪一条、几何是哪一块、时间窗是哪一段。
// 三者其实都在计划载荷的班次记录里（`routeBasis` / `routeBasisFromMinute` /
// `detourMinutes` / `crossingZones` / `staticAirspace`），只是从来没有并排摆出来。
//
// 这一组判据钉住四件事：
//   1. **不重算**。三要素只做投影与措辞：成因走 `routeBasisNote` 这一个出口，绕行量
//      直接用班次自己的 `detourMinutes`。同一现象有两个出口就是下一次"同一件事两个
//      说法"（M51 / M59）。
//   2. **缺什么说什么**。没有成因的班次不进普查的分子，单列 `unevaluated`；
//      `routeBasisFromMinute` 为 `null` 时写「全时段」，**不写第 0 分钟** ——
//      `Number(null) === 0`，而 0 分钟是一个真实的分钟（M30）。
//   3. **不编造阈值**。分级规则从载荷读，缺失时唯一正确的呈现是不写数；`Number(null)`
//      是 0，所以"字段没发布"绝不能读成"发布了一个 0 dBZ 的阈值"。
//   4. **只命名真正在跑的东西**。几何构造的名字按通道换说法：把实测通道也写成"逐帧
//      扫掠取并集"就是捏造一个不存在的采样过程。
//
// 最后一段读源码做静态断言：`.vue` 的模板求值 `node --test` 够不着，而构建不跑模板
// 求值，所以「分节真的挂上去了」只能从源码读 —— 同 `algorithmIdentity.test.mjs` 与
// `planChannelContract.test.mjs`。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  MECHANISM_ELEMENTS, BASIS_MACHINERY, routeBasisNames, WEATHER_ROUTE_BASES,
  radarRuleBlock, routeBasisCensus, mechanismChain, mechanismPickerRows, SECTION_NAMES,
} from '../src/traffic/runtime.js'

const here = dirname(fileURLToPath(import.meta.url))
const console_ = await readFile(join(here, '..', 'src', 'components', 'OperationsConsole.vue'), 'utf8')
const view = await readFile(join(here, '..', 'src', 'components', 'TrafficWorkbench.vue'), 'utf8')

/** 载荷里的分级规则。数值与后端 `service._radar_rule_block()` 发出的一致。 */
const RULE = {
  tiers: 'CONVECTIVE_AND_STRONG', bandFloorDbz: 15, convectiveDbz: 35,
  strongDbz: 45, coreInsetM: 9000, penetrationM: 250,
}
const plan = (overrides = {}) => ({
  status: 'READY', version: 'city-traffic-1.3', fingerprint: 'a1b2c3d4e5f60718',
  planRevision: 4, weatherMode: 'virtual',
  radarAvoidance: { included: true, mode: 'virtual', sweepSlots: 49, sweepStrideMinutes: 10, rule: { ...RULE } },
  ...overrides,
})

const flight = (overrides = {}) => ({
  id: 'CAR-0001', name: '沈阳 → 长春', routeBasis: 'RADAR_FIELD', routeBasisFromMinute: 20,
  detourMinutes: 7.4, distanceKm: 412.5, delayMinutes: 0,
  departureMinute: 60, arrivalMinute: 120,
  crossingZones: ['CZ-1', 'CZ-2'], staticAirspace: { crossings: [{}, {}] },
  ...overrides,
})

// ------------------------------------------------------------------ 分级规则

test('分级规则从载荷读，载荷没有时返回 null 而不是一组默认值', () => {
  assert.equal(radarRuleBlock(null), null)
  assert.equal(radarRuleBlock({}), null)
  assert.equal(radarRuleBlock({ status: 'READY' }), null)
  // 有雷达避让记录、但没有规则块：同样是"未发布"。
  assert.equal(radarRuleBlock({ radarAvoidance: { included: false } }), null)
  assert.equal(radarRuleBlock({ radarAvoidance: { rule: null } }), null)
  assert.equal(radarRuleBlock({ radarAvoidance: { rule: 'CONVECTIVE_AND_STRONG' } }), null)
})

test('规则块逐字段取值，字段没发布时是 null —— 不是 0', () => {
  const full = radarRuleBlock(plan())
  assert.deepEqual(full, { tiers: 'CONVECTIVE_AND_STRONG', ...RULE })

  // `Number(null)` 是 0，`Number('')` 也是 0。若先转换再判真假，这里会得到
  // 「擦入深度上限 0 m」——一句读起来像一个严格规则、其实是"没有发布"的话。
  const partial = radarRuleBlock(plan({
    radarAvoidance: { rule: { convectiveDbz: 35, penetrationM: null, coreInsetM: '' } },
  }))
  assert.equal(partial.convectiveDbz, 35)
  assert.equal(partial.penetrationM, null)
  assert.equal(partial.coreInsetM, null)
  assert.equal(partial.strongDbz, null)
})

// ------------------------------------------------------------------ 成因普查

const FLEET = [
  flight({ id: 'F-FIELD-1' }),
  flight({ id: 'F-FIELD-2', detourMinutes: 2.0 }),
  flight({ id: 'F-FIELD-3', detourMinutes: 0 }),
  flight({ id: 'F-CORE-1', routeBasis: 'RADAR_CORE', routeBasisFromMinute: 33 }),
  flight({ id: 'F-ZONE-1', routeBasis: 'STATIC_AIRSPACE', routeBasisFromMinute: null, detourMinutes: 3 }),
  flight({ id: 'F-CLEAR-1', routeBasis: 'CLEAR', routeBasisFromMinute: null, detourMinutes: 0 }),
  // 未被受理：没有 `routeBasis`。它不能并进 `CLEAR`。
  { id: 'F-CLOSED-1', status: 'CLOSED', reason: 'STATIC_AIRSPACE_BLOCKED' },
  { id: 'F-CLOSED-2', status: 'CLOSED', reason: 'NO_GEOMETRIC_PATH', detourMinutes: 5 },
]

test('普查按判据分组，分母写全，未进入判定的单列', () => {
  const census = routeBasisCensus(FLEET)
  assert.equal(census.total, FLEET.length)
  assert.equal(census.unevaluated, 2, '两个闭班次没有成因，必须单列')
  const sum = census.rows.reduce((total, row) => total + row.total, 0)
  assert.equal(sum + census.unevaluated, census.total, '分组合计 + 未判定 必须等于分母')
  assert.deepEqual(census.rows.map(row => row.key), ['RADAR_FIELD', 'RADAR_CORE', 'STATIC_AIRSPACE', 'CLEAR'])
})

test('气象成因排在前，且"气象"的成员资格与 WEATHER_ROUTE_BASES 同源', () => {
  const census = routeBasisCensus(FLEET)
  const flags = census.rows.map(row => row.weather)
  assert.deepEqual(flags, [true, true, false, false], '两条回波判据是气象，固定管制区与直飞不是')
  // 排序：气象在前，其次班次数。若哪天把排序改成按字母，这条会红。
  assert.ok(flags.indexOf(true) < flags.indexOf(false))
  for (const row of census.rows) {
    assert.equal(row.weather, WEATHER_ROUTE_BASES.includes(row.key))
    assert.equal(row.name, routeBasisNames[row.key])
    assert.ok(row.construction, `${row.key} 必须说得出它的几何构造`)
  }
})

test('每条判据的样本有上限，且绕行/等待分别计数', () => {
  const many = Array.from({ length: 40 }, (_value, index) =>
    flight({ id: `F-${index}`, detourMinutes: index % 2 ? 5 : 0, delayMinutes: index % 4 ? 0 : 9 }))
  const census = routeBasisCensus(many)
  const row = census.rows.find(item => item.key === 'RADAR_FIELD')
  assert.equal(row.total, 40)
  assert.equal(row.detoured, 20)
  assert.equal(row.delayed, 10)
  assert.ok(row.sampleIds.length <= 4, '样本是入口的样本，不是全体')
  assert.equal(census.unevaluated, 0)
  // 空输入不炸，且行数为 0。
  assert.deepEqual(routeBasisCensus(null), { total: 0, unevaluated: 0, rows: [] })
})

// -------------------------------------------------------------- 三要素因果链

test('没有班次时返回 null；三要素的顺序与标签只有一处定义', () => {
  assert.equal(mechanismChain(null, plan()), null)
  assert.equal(mechanismChain(undefined, plan()), null)
  assert.equal(mechanismChain('CAR-1', plan()), null)
  assert.deepEqual(MECHANISM_ELEMENTS.map(element => element.key), ['criterion', 'geometry', 'window'])
  assert.deepEqual(MECHANISM_ELEMENTS.map(element => element.label), ['气象判据', '几何', '时间窗'])
})

test('有成因的班次三要素齐全，且判据复用成因的唯一显示口径', () => {
  const chain = mechanismChain(flight(), plan())
  assert.equal(chain.ok, true)
  assert.deepEqual(chain.missing, [])
  assert.deepEqual(chain.steps.map(step => step.key), ['criterion', 'geometry', 'window'])
  assert.deepEqual(chain.steps.map(step => step.label), ['气象判据', '几何', '时间窗'])

  const [criterion, geometry, window] = chain.steps
  assert.equal(criterion.headline, '雷达 ≥35 dBZ 场')
  // 成因行必须**就是** `routeBasisNote` 的输出，不是另写一遍的近似句。
  assert.ok(criterion.lines[0].includes('成因：雷达 ≥35 dBZ 场'), criterion.lines[0])
  assert.ok(criterion.lines[0].includes('T+00:20:00'), '成因分钟必须出现在判据行里')
  // 阈值来自载荷，并写出与它同源的那条间隔标准。
  assert.ok(criterion.lines.some(line => line.includes('≥35 dBZ') && line.includes('250 m')),
    JSON.stringify(criterion.lines))
  assert.equal(geometry.headline.startsWith('回波外场几何'), true)
  assert.ok(geometry.lines.some(line => line.includes('绕行增时 7')), JSON.stringify(geometry.lines))
  assert.ok(geometry.lines.some(line => line.includes('412.5 km')))
  assert.ok(geometry.lines.some(line => line.includes('已预约 2 个交叉区')))
  assert.ok(geometry.lines.some(line => line.includes('固定管制区穿越记录 2 条')))
  assert.ok(window.headline.includes('T+01:00:00'), window.headline)
  assert.ok(window.headline.includes('本班次自身窗口'), '时间窗讲的是这一班自己的窗口，不是"现在"')
})

test('成因没有分钟时写「全时段」，绝不写成第 0 分钟', () => {
  // 这一对是**鉴别性**的：两个输入的差别只有 `routeBasisFromMinute` 一项，
  // 而 `Number(null)` 与 `Number(0)` 都是 0 —— 写法不对时两句会一模一样。
  const noMinute = mechanismChain(flight({ routeBasis: 'STATIC_AIRSPACE', routeBasisFromMinute: null }), plan())
  const zeroMinute = mechanismChain(flight({ routeBasis: 'RADAR_FIELD', routeBasisFromMinute: 0 }), plan())
  const criterionOf = chain => chain.steps.find(step => step.key === 'criterion').lines[0]

  assert.ok(criterionOf(noMinute).includes('全时段'), criterionOf(noMinute))
  assert.ok(!criterionOf(noMinute).includes('T+00:00:00'), '`null` 不是第 0 分钟')
  assert.ok(criterionOf(zeroMinute).includes('T+00:00:00'), '0 是一个真实的分钟，必须照写')
  assert.ok(!criterionOf(zeroMinute).includes('全时段'))

  // 同理，`''` 与 `undefined` 也不能读成 0。
  for (const blank of ['', undefined]) {
    const chain = mechanismChain(flight({ routeBasis: 'BOUNDARY', routeBasisFromMinute: blank }), plan())
    assert.ok(criterionOf(chain).includes('全时段'), `routeBasisFromMinute=${JSON.stringify(blank)}`)
  }
  const window = mechanismChain(flight({ routeBasis: 'BOUNDARY', routeBasisFromMinute: null }), plan())
    .steps.find(step => step.key === 'window')
  assert.ok(window.lines[0].includes('没有起始分钟'), window.lines[0])
})

test('几何构造按通道换说法：实测通道不得出现"分箱 / 采样时次"', () => {
  const virtual = mechanismChain(flight(), plan({ weatherMode: 'virtual' }))
  const measured = mechanismChain(flight(), plan({ weatherMode: 'measured' }))
  const geometryOf = chain => chain.steps.find(step => step.key === 'geometry').headline
  const windowOf = chain => chain.steps.find(step => step.key === 'window').lines[0]

  assert.ok(geometryOf(virtual).includes('按 10 分钟分箱取并集'))
  assert.ok(geometryOf(virtual).includes('49 个采样时次'))
  // 实测通道只有一次观测，根本没有"点"这个量。给它写采样点数就是捏造一个不存在的
  // 采样过程 —— 与 0.9.21「两条通道混用」是同一类错。
  assert.ok(geometryOf(measured).includes('单时刻观测'), geometryOf(measured))
  assert.ok(!geometryOf(measured).includes('分箱'))
  assert.ok(!geometryOf(measured).includes('采样时次'))
  assert.ok(windowOf(virtual).includes('分箱'))
  assert.ok(windowOf(measured).includes('不外推为预报'))

  // 与气象无关的两条判据不该被缀上通道说明：那会描述一件没有发生的事。
  for (const key of ['CLEAR', 'STATIC_AIRSPACE', 'BOUNDARY']) {
    const chain = mechanismChain(flight({ routeBasis: key, routeBasisFromMinute: null }), plan())
    const headline = geometryOf(chain)
    assert.ok(!headline.includes('分箱'), `${key} 不该讲通道`)
    assert.ok(!headline.includes('单时刻观测'), `${key} 不该讲通道`)
  }
})

test('载荷没有分级规则时，判据行不引用任何阈值', () => {
  const bare = { status: 'READY', version: 'city-traffic-1.3', fingerprint: 'a1b2c3d4e5f60718' }
  for (const key of ['RADAR_CORE', 'RADAR_FIELD']) {
    const chain = mechanismChain(flight({ routeBasis: key, routeBasisFromMinute: 5 }), bare)
    const criterion = chain.steps.find(step => step.key === 'criterion')
    assert.ok(criterion.lines.some(line => line.includes('未发布分级规则')), JSON.stringify(criterion.lines))
    assert.ok(!criterion.lines.some(line => line.includes('判据阈值')), '没有规则就不该有阈值句')
  }
})

test('判据说走廊被挡、航程却没有变长时，两句都照实说', () => {
  const chain = mechanismChain(flight({ routeBasis: 'RADAR_FIELD', detourMinutes: 0 }), plan())
  const geometry = chain.steps.find(step => step.key === 'geometry')
  assert.ok(geometry.lines.some(line => line.includes('航线长度未增加')), JSON.stringify(geometry.lines))
  assert.ok(!geometry.lines.some(line => line.includes('绕行增时')), '没变长就不能写"绕过了"')

  // 绕行量没声明时同样不许编一个 0。
  const blank = mechanismChain(flight({ detourMinutes: null }), plan())
  assert.ok(blank.steps.find(step => step.key === 'geometry').lines.some(line => line.includes('航程变化未声明')))
})

test('没有成因的班次逐项报缺席，且不从不完整的记录里倒推成因', () => {
  const closed = mechanismChain({ id: 'F-CLOSED-1', status: 'CLOSED', reason: 'STATIC_AIRSPACE_BLOCKED' }, plan())
  assert.equal(closed.ok, false)
  assert.deepEqual(closed.missing, ['criterion', 'geometry', 'window'])
  assert.equal(closed.basisKey, '')
  for (const step of closed.steps) {
    assert.equal(step.headline, '', `${step.key} 没有内容就不该有标题行`)
    assert.ok(step.absent && step.absent.length > 10, `${step.key} 必须写出缺席的原因`)
  }

  // 有绕行量、没有成因：只能报量，不能倒推。缺了成因就配一个"疑似气象"正是本项目
  // 最忌讳的那类写法 —— 把推测写成判据。
  const detoured = mechanismChain({ id: 'F-CLOSED-2', status: 'CLOSED', detourMinutes: 5, distanceKm: 180 }, plan())
  assert.deepEqual(detoured.missing, ['criterion', 'window'], '有绕行量时几何还有话可说')
  const geometry = detoured.steps.find(step => step.key === 'geometry')
  assert.ok(geometry.absent.includes('倒推出一个成因'), geometry.absent)
  assert.equal(geometry.headline, '', '没有成因就没有"这块几何是怎么来的"可讲')
  assert.ok(geometry.lines.some(line => line.includes('180 km')), '量还是照报')
  // 判据行不得凭空出现任何一条成因的名字。
  const criterion = detoured.steps.find(step => step.key === 'criterion')
  for (const name of Object.values(routeBasisNames)) {
    assert.ok(!criterion.absent.includes(name), `缺席说明里不该出现成因名「${name}」`)
  }
})

test('每条判据都有对应的几何构造，键集与成因表逐项对齐', () => {
  assert.deepEqual(Object.keys(BASIS_MACHINERY).sort(), Object.keys(routeBasisNames).sort())
  for (const [key, entry] of Object.entries(BASIS_MACHINERY)) {
    assert.ok(entry.construction && entry.detail, `${key} 的两句话缺一不可`)
    // 说明文字里不得写进制数字：阈值只有一个出处（载荷），说明文字没有闸门。
    assert.ok(!/\d/.test(entry.construction), `${key} 的构造名里不该出现数字`)
    assert.ok(!/\d/.test(entry.detail), `${key} 的说明里不该出现数字`)
  }
})

// ------------------------------------------------------------------ 选择条

test('选择条按判据收窄、可搜索，气象成因排在前面', () => {
  const rows = mechanismPickerRows(FLEET, { basis: 'RADAR_FIELD' })
  assert.deepEqual(rows.rows.map(item => item.id), ['F-FIELD-1', 'F-FIELD-2', 'F-FIELD-3'])
  assert.equal(rows.matched, 3)

  const all = mechanismPickerRows(FLEET)
  assert.equal(all.matched, 6, '没有成因的两班不进选择条')
  // **气象成因必须整体排在非气象成因之前**（组内才比绕行量）。这里量的是那条边界：
  // 前 k 行全是气象、第 k 行之后一个气象都没有。
  const weatherRows = all.rows.filter(item => WEATHER_ROUTE_BASES.includes(item.routeBasis))
  assert.equal(weatherRows.length, 4)
  assert.ok(all.rows.slice(0, 4).every(item => WEATHER_ROUTE_BASES.includes(item.routeBasis)),
    `前 4 行应全是气象成因：${all.rows.map(item => item.routeBasis).join(',')}`)
  assert.ok(!all.rows.slice(4).some(item => WEATHER_ROUTE_BASES.includes(item.routeBasis)),
    '非气象成因不得越过气象成因往前排')
  // 组内按绕行量降序：非气象那两条里，绕了 3 分钟的排在没绕的前面。
  assert.deepEqual(all.rows.slice(4).map(item => item.routeBasis), ['STATIC_AIRSPACE', 'CLEAR'])

  const searched = mechanismPickerRows(FLEET, { query: 'f-core' })
  assert.deepEqual(searched.rows.map(item => item.id), ['F-CORE-1'])
  assert.equal(mechanismPickerRows(FLEET, { query: '不存在' }).matched, 0)

  const capped = mechanismPickerRows(FLEET, { limit: 2 })
  assert.equal(capped.rows.length, 2)
  assert.equal(capped.matched, 6)
})

// ------------------------------------------------- 静态断言：分节真的挂上去了

test('「算法机理」进了导航，并且落在 OperationsConsole 的分支上', () => {
  // 导航名在 0.9.26 第十轮收敛到**唯一来源**（`runtime.js::SECTION_NAMES`）：
  // 工作台、下钻落点提示、文档模块表三处说的是同一件事。所以判据是两半 ——
  // ① 唯一来源里有这一项；② 工作台真的引用它，而不是又写了一份。
  // 只断言 ① 会漏掉"工作台自己另写一份"；只断言 ② 会漏掉"表里没有这一项"。
  assert.equal(SECTION_NAMES.mechanism, '算法机理', '唯一来源里必须有这一项')
  assert.match(view, /const sections=SECTION_NAMES/, '工作台必须引用唯一来源，不能自带副本')
  assert.ok(console_.includes("view==='mechanism'"), 'OperationsConsole 必须有对应分支')
  // 挂载条件不得把新分节排除掉（`v-if="!['home','overview','schedule']..."`）。
  const guard = /OperationsConsole\s+v-if="!\[([^\]]*)\]/.exec(view)
  assert.ok(guard, '找不到 OperationsConsole 的挂载条件')
  assert.ok(!guard[1].includes('mechanism'), `挂载条件排除了 mechanism：${guard[1]}`)
})

test('三要素由数据驱动渲染，标签不在模板里再写一遍', () => {
  assert.ok(console_.includes('step.label'), '标签必须来自 MECHANISM_ELEMENTS')
  assert.ok(console_.includes('data-mechanism-step="step.key"'), '每一步都要有可探测的钩子')
  for (const hook of ['data-mechanism-rule', 'data-mechanism-census', 'data-mechanism-chain', 'data-mechanism-detail']) {
    assert.ok(console_.includes(hook), `缺少 ${hook}`)
  }
  // 三个组装/读数函数都必须真的被调用，否则分节会渲染成空白。
  for (const call of ['radarRuleBlock(props.session)', 'routeBasisCensus(props.flights)', 'mechanismChain(']) {
    assert.ok(console_.includes(call), `OperationsConsole 没有调用 ${call}`)
  }
})

test('新分节的文案里不得出现面向评审/教师的措辞', () => {
  // 项目内不得出现"我该向评审/老师说明什么"这类叙述 —— 这是一个完整的程序，
  // 不是一份答辩稿。判据是关键词，不是语气。
  const forbidden = ['评审', '评委', '老师', '答辩', '评分', '打分', '参赛作品', '交付给']
  const added = console_.slice(console_.indexOf('算法机理（0.9.26 / AL-5）'))
  for (const word of forbidden) {
    assert.ok(!added.includes(word), `算法机理分节里出现了「${word}」`)
  }
})
