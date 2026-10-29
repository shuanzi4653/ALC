// 0.9.26（Beta）第十一轮：诊断方案余下条目的判据。
//
// 这一批判据有一条共同的自律，写在这里而不是散在各处：
// **凡是能写「负向对照」的地方就写一条**（§八 M58 / §十 ⑫）。
// 一条只会变绿的判据，在它该报错时会和"什么都没发现"长得一模一样。
//
// 第二条自律来自 M63：**描述判据的文字也在判据的输入里**。所以下面凡是断言文案的
// 地方，都同时断言一个**结构**事实；只钉字符串的判据会在文案改写时无声失效。
import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {MAP_LAYERS,EVENT_TONES,EVENT_COLORS,eventTone,eventColor,alertEventLayer,
  SEVERITY_CLASSES,SEVERITY_RING_M,severityClass,observationReading,observationPoints,
  severityBands,OBSERVATION_COLUMNS,observationRows,sortObservationRows,observationCsv,
  observationImpact,batchClearanceRows,AI_MARKS,aiMark,verdictMark,aiCoverage,
  RADAR_BANDS,radarTierStats,IMPACT_BASES,weatherImpact,weatherEvolution,
  DISPOSAL_FLOW,DISPOSAL_STATE_KEYS,disposalStateLabel,DISPOSAL_ACTIONS,disposalAction,
  disposalNextActions,replayWeatherFrame,groupAlerts} from '../src/traffic/runtime.js'

// ---- 夹具：照抄真实载荷的形状（§十六）----------------------------------------
// 走廊几何来自 `/traffic/network`（经纬度），班次来自 `/traffic/session`。
// 一个"看起来合理"的夹具是零成本自欺，所以这里逐键对齐后端字段名。
const NETWORK = {
  cities: [
    {id: 'shenyang', name: '沈阳', coordinate: [123.43, 41.8]},
    {id: 'dalian', name: '大连', coordinate: [121.61, 38.91]},
    // 故意不给坐标：用来证明"取不到坐标的点会被跳过，而不是落到 (0,0)"。
    {id: 'no-coord', name: '缺坐标市'},
  ],
  routes: [{
    id: 'CAR-shenyang-dalian', name: '沈阳 ↔ 大连', fromCity: 'shenyang', toCity: 'dalian',
    referencePath: [[123.43, 41.8], [122.5, 40.3], [121.61, 38.91]],
  }],
}
const FLIGHT = (over = {}) => ({
  id: 'CAR-shenyang-dalian-1', routeId: 'CAR-shenyang-dalian', mode: 'CAR',
  fromCity: 'shenyang', toCity: 'dalian', status: 'SCHEDULED', reason: 'CLEAR',
  delayMinutes: 0, detourMinutes: 0, departureMinute: 30, arrivalMinute: 90,
  routeBasis: 'CLEAR',
  atcClearance: {callsign: 'CA123', route: '沈阳 → 大连', limit: '按已声明高度层',
    assignedLevelAglM: 300, status: 'CHECKED', weatherBasis: '本班无气象影响',
    ctot: {from: '2026-01-01T01:00:00Z', validityMinutes: 15}},
  ...over,
})
// 一个气象成因的停止放行事件 + 一个非气象成因的改航事件。
// `departureMinute` **逐班给不同的值**：全部同值会让"风险优先"与"时间序"两个排序
// 恰好重合，于是那条判据无论实现对不对都会变绿（一次真实的负向对照失败）。
const FLIGHTS = [
  FLIGHT({id: 'a', status: 'CLOSED', reason: 'WEATHER_BLOCKED',
    routeBasis: 'RADAR_FIELD', detourMinutes: 6, departureMinute: 30, requestedDepartureMinute: 30}),
  FLIGHT({id: 'b', status: 'CLOSED', reason: 'WEATHER_BLOCKED',
    routeBasis: 'RADAR_CORE', detourMinutes: 4, departureMinute: 40, requestedDepartureMinute: 40}),
  FLIGHT({id: 'c', reason: 'CLEAR', routeBasis: 'BOUNDARY', detourMinutes: 3, delayMinutes: 8,
    departureMinute: 90, requestedDepartureMinute: 90}),
  FLIGHT({id: 'd', reason: 'CLEAR', routeBasis: 'CLEAR',
    departureMinute: 5, requestedDepartureMinute: 5}),
]
// 观测：真实字段名（weather_sources.py）。open-meteo 的能见度**只在 hourly 里**。
const OBSERVATION = (over = {}) => ({
  cityId: 'shenyang', cityName: '沈阳', validAt: '2026-01-01T00:00:00Z',
  temperatureC: 12.4, windSpeed10mMps: 4.2, windDirection10mDeg: 210,
  windGusts10mMps: 7.1, precipitationMm: 0.0, weatherCode: 3,
  hourly: {visibility: [9000, 8000]},
  ...over,
})
const WEATHER = (over = {}) => ({
  minute: 30, provider: 'OPEN_METEO', dataType: 'MODEL_ESTIMATE', available: true,
  cells: [], winds: [], observations: [OBSERVATION()],
  radar: {available: true, mode: 'measured', summary: {bands: {}},
    regions: [{kind: 'RADAR', slot: '2026-01-01T00:00:00Z',
      bands: {STRATIFORM: {components: 3, areaKm2: 120.5},
        CONVECTIVE: {components: 2, areaKm2: 40.2},
        STRONG: {components: 1, areaKm2: 8.4}}}]},
  ...over,
})

// =============================================================================
// P0-2：运行事件图层
// =============================================================================
test('地图事件图层与预警中心是**同一次求值**的两个投影', () => {
  const layer = alertEventLayer(FLIGHTS, NETWORK)
  const groups = groupAlerts(FLIGHTS)
  assert.equal(layer.total, groups.total, '事件总数必须与预警中心相等')
  assert.equal(layer.weatherEvents, groups.weatherEvents)
  assert.equal(layer.nonWeatherEvents, groups.nonWeatherEvents)
  assert.equal(layer.closedFlights, groups.closedFlights)
  assert.equal(layer.closedEvents, groups.rows.filter(row => row.closed).length,
    '地图上的"红色事件 N"必须等于预警中心里 closed 的行数')
})

test('走廊几何取自网络载荷，取不到时跳过并计数 —— 不用直线顶替', () => {
  const good = alertEventLayer(FLIGHTS, NETWORK)
  assert.ok(good.shown > 0, '至少有一条事件应能连上走廊')
  for (const feature of good.lines.features) {
    assert.equal(feature.geometry.type, 'LineString')
    assert.ok(feature.geometry.coordinates.length >= 2)
    assert.deepEqual(feature.geometry.coordinates[0], [123.43, 41.8])
  }
  // 负向对照：把网络里的路由删掉，就必须一条都不画，并且**说出来**。
  const stripped = alertEventLayer(FLIGHTS, {cities: NETWORK.cities, routes: []})
  assert.equal(stripped.lines.features.length, 0)
  assert.equal(stripped.nodes.features.length, 0)
  assert.equal(stripped.missingCorridor, stripped.total, '取不到的条数必须等于事件总数')
  assert.match(stripped.note, /取不到走廊几何/,
    '缺席必须在说明里出现 —— 静默跳过就是一条假通过')
})

test('事件色调：停止放行压过成因色（次序不可颠倒）', () => {
  assert.equal(eventTone({closed: true, weather: true}), EVENT_TONES.CLOSED)
  assert.equal(eventTone({closed: true, weather: false}), EVENT_TONES.CLOSED)
  assert.equal(eventTone({closed: false, weather: true}), EVENT_TONES.WEATHER)
  assert.equal(eventTone({closed: false, weather: false}), EVENT_TONES.OTHER)
  // 负向对照：把次序反过来（先判 weather），因气象停飞的事件就会丢掉红色。
  const wrong = row => (row.weather ? EVENT_TONES.WEATHER : (row.closed ? EVENT_TONES.CLOSED : EVENT_TONES.OTHER))
  assert.notEqual(wrong({closed: true, weather: true}), eventTone({closed: true, weather: true}))
  assert.equal(eventColor({closed: true, weather: true}), EVENT_COLORS.alert)
})

// =============================================================================
// P0-2 ①：观测等级点与分区等级色带
// =============================================================================
test('观测分档与 observationTone 同源，不另判一次', () => {
  assert.equal(severityClass(OBSERVATION({hourly: {visibility: [3000]}})).key, 'SEVERE')
  assert.equal(severityClass(OBSERVATION({windSpeed10mMps: 13, hourly: {visibility: [9000]}})).key, 'CAUTION')
  assert.equal(severityClass(OBSERVATION()).key, 'NOMINAL')
  assert.equal(SEVERITY_CLASSES.length, 4)
})

test('缺坐标的观测被跳过并计数 —— 不是落到 (0,0)', () => {
  const points = observationPoints(
    WEATHER({observations: [OBSERVATION(), OBSERVATION({cityId: 'no-coord'})]}), NETWORK)
  assert.equal(points.total, 1)
  assert.equal(points.missingLocation, 1)
  for (const feature of points.features) {
    assert.notDeepEqual(feature.geometry.coordinates, [0, 0])
  }
  assert.match(points.note, /点值不是面值/, '必须说清这是点值')
})

test('分区等级色带：差天气在前，等级内按能见度升序', () => {
  const bands = severityBands(WEATHER({observations: [
    OBSERVATION({cityId: 'dalian', cityName: '大连', hourly: {visibility: [9000]}}),
    OBSERVATION({cityId: 'shenyang', cityName: '沈阳', hourly: {visibility: [2000]}}),
  ]}), NETWORK)
  assert.deepEqual(bands.rows.map(row => row.label), ['沈阳', '大连'])
  assert.equal(bands.counts.SEVERE, 1)
})

test('观测读数缺要素写 absent，不写空字符串', () => {
  const reading = observationReading({cityId: 'x', cityName: 'X'})
  assert.match(reading, /气温 absent/)
  assert.match(reading, /阵风 absent/)
  assert.match(reading, /能见度 absent/)
  assert.doesNotMatch(reading, /undefined|NaN/)
})

// =============================================================================
// P1-1 a：可排序表格
// =============================================================================
test('表格排序：缺值在两个方向上都排最后', () => {
  const rows = observationRows(WEATHER({observations: [
    OBSERVATION({cityId: 'a', cityName: 'A', windSpeed10mMps: 9}),
    OBSERVATION({cityId: 'b', cityName: 'B', windSpeed10mMps: null}),
    OBSERVATION({cityId: 'c', cityName: 'C', windSpeed10mMps: 3}),
  ]}))
  assert.deepEqual(sortObservationRows(rows, 'windSpeed', 'asc').map(r => r.station), ['C', 'A', 'B'])
  assert.deepEqual(sortObservationRows(rows, 'windSpeed', 'desc').map(r => r.station), ['A', 'C', 'B'],
    '降序时"未报出"也必须最后 —— 它既不是最大也不是最小')
  // 负向对照：朴素的数值比较会把 null 读成 0，升序时它排到最前。
  const naive = [...rows].sort((a, b) => Number(a.windSpeed) - Number(b.windSpeed))
  assert.notDeepEqual(naive.map(r => r.station), sortObservationRows(rows, 'windSpeed', 'asc').map(r => r.station))
})

test('表格列覆盖要求的八个要素，且能导出 CSV', () => {
  assert.deepEqual(OBSERVATION_COLUMNS.map(column => column.key),
    ['station', 'temperatureC', 'windSpeed', 'gust', 'visibilityM', 'precipitationMm', 'phenomenon', 'level'])
  const rows = observationRows(WEATHER())
  assert.equal(rows.length, 1)
  assert.equal(rows[0].visibilityM, 9000, '能见度必须走 hourly.visibility，与判定同源')
  assert.equal(rows[0].gust, 7.1)
  const csv = observationCsv(rows)
  assert.equal(csv.split('\n').length, 2)
  assert.match(csv, /沈阳/)
  assert.match(csv, /正常/)
})

test('CSV 转义：含逗号与引号的站名不得把列冲散', () => {
  const rows = observationRows(WEATHER())
  rows[0].station = 'A,"B"'
  const csv = observationCsv(rows)
  const body = csv.split('\n')[1]
  assert.ok(body.startsWith('"A,""B"""'), `第一列没有被完整引起来：${body.slice(0, 20)}`)
  // 负向对照：不转义时那个逗号会把一行冲成九段，而表头只有八列。
  const head = csv.split('\n')[0].split(',').length
  assert.ok(body.split(',').length > head,
    '朴素按逗号切分的段数必须多于表头列数 —— 这条判据是"转义真的发生了"的回执')
})

// =============================================================================
// P1-1 b / c：影响面与批量许可
// =============================================================================
test('观测影响面接上走廊与班次，并给出处置次序（不是新政策）', () => {
  const impact = observationImpact(
    WEATHER({observations: [OBSERVATION({hourly: {visibility: [2000]}})]}), FLIGHTS, NETWORK)
  assert.equal(impact.length, 1)
  assert.deepEqual(impact[0].corridors, ['沈阳 ↔ 大连'])
  assert.equal(impact[0].flightCount, FLIGHTS.filter(f => [f.fromCity, f.toCity].includes('shenyang')).length)
  assert.equal(impact[0].level, 'SEVERE')
  assert.match(impact[0].advice, /先按已声明高度层与时隙重排/)
  // 正常站不进影响面 —— 一张"全是正常"的影响面等于没说。
  const quiet = observationImpact(WEATHER(), FLIGHTS, NETWORK)
  assert.equal(quiet.length, 0)
})

test('批量许可：缺高度层写"未指派"而不是 0 米', () => {
  const rows = batchClearanceRows([
    FLIGHT({id: 'x', atcClearance: {callsign: 'CX1', route: 'A → B', status: 'CHECKED'}}),
  ])
  assert.equal(rows.rows[0].level, '未指派高度层')
  assert.equal(rows.rows[0].ctot, '未取得时隙')
  assert.equal(rows.total, 1)
})

test('批量许可按风险优先：停止放行在改航之前，改航在普通之前', () => {
  const rows = batchClearanceRows(FLIGHTS, {sort: 'risk'}).rows.map(row => row.id)
  assert.ok(rows.indexOf('a') < rows.indexOf('c'))
  assert.ok(rows.indexOf('c') < rows.indexOf('d'))
  // 同一批换成时间序，顺序必须真的不同（否则"风险优先"这个词没有牙齿）。
  const byTime = batchClearanceRows(FLIGHTS, {sort: 'time'}).rows.map(row => row.id)
  assert.notDeepEqual(rows, byTime)
})

test('没有放行许可时批量表说明原因，而不是给一张空表', () => {
  const empty = batchClearanceRows([])
  assert.equal(empty.total, 0)
  assert.match(empty.note, /尚未写出任何放行许可/)
})

// =============================================================================
// P1-2：AI 结论标记与覆盖率
// =============================================================================
test('默认标记是"未经 AI 研判"，不是空白', () => {
  assert.equal(aiMark(null).key, 'NOT_REVIEWED')
  assert.equal(aiMark(undefined).key, 'NOT_REVIEWED')
  assert.ok(aiMark(null).label.length > 0)
  assert.equal(verdictMark('a', {}).key, 'NOT_REVIEWED')
  // 负向对照：把默认实现成空标签，界面就会"两个字都没有"，读起来像忘了标。
  assert.notEqual(aiMark(null).label.trim(), '')
})

test('未知结局原样退回"未经研判"，不猜、也不假装成功', () => {
  assert.equal(aiMark('SOMETHING_NEW').key, 'NOT_REVIEWED')
  assert.equal(aiMark('ACCEPTED').key, 'ADOPTED')
  assert.equal(aiMark('VETOED').key, 'VETOED')
  assert.equal(aiMark('UNAVAILABLE').key, 'DEGRADED')
  assert.equal(aiMark('NOT_CONFIGURED').key, 'RULE_ONLY')
  // 每一档的 tone 都必须能被 toneFitsFamily 接受（状态色，两族共存）。
  for (const mark of Object.values(AI_MARKS)) {
    assert.ok(['muted', 'cyan', 'warn'].includes(mark.tone), `${mark.key} 的 tone 不在允许集合里`)
  }
})

test('覆盖率的分母是全部班次，未研判数能被数出来', () => {
  const coverage = aiCoverage(FLIGHTS, {a: 'ACCEPTED', z: 'VETOED'})
  assert.equal(coverage.total, FLIGHTS.length)
  assert.equal(coverage.reviewed, 1, '只有真的在清单里的 id 才算数')
  assert.equal(coverage.uncovered, FLIGHTS.length - 1)
  assert.equal(coverage.vetoed, 0)
  assert.equal(aiCoverage([], {}).ratio, 0)
})

// =============================================================================
// P1-4：分档统计 / 影响面 / 时间演变
// =============================================================================
test('分档统计三态分明：本帧无回波 / 值非法 / 本帧未发布', () => {
  const stats = radarTierStats(WEATHER(), null)
  assert.equal(stats.source, 'regions')
  assert.deepEqual(stats.rows.map(row => row.state), ['PRESENT', 'PRESENT', 'PRESENT'])
  assert.equal(stats.rows[2].areaKm2, 8.4)
  assert.equal(stats.hazardAreaKm2, 48.6)
  const empty = radarTierStats(WEATHER({radar: {available: true, mode: 'measured',
    regions: [{kind: 'RADAR', bands: {STRATIFORM: {components: 1, areaKm2: 10},
      CONVECTIVE: {components: 0, areaKm2: 0}, STRONG: {components: 0, areaKm2: 0}}}]}}), null)
  assert.equal(empty.rows[1].state, 'EMPTY')
  assert.notEqual(empty.rows[1].state, 'ABSENT', '"量出来是 0"与"没有这个东西"必须不同')
  const absent = radarTierStats(WEATHER({radar: {available: true, mode: 'virtual', regions: []}}), null)
  assert.deepEqual(absent.rows.map(row => row.state), ['ABSENT', 'ABSENT', 'ABSENT'])
  assert.equal(absent.totalAreaKm2, 0)
  assert.match(absent.note, /不是"面积 0"/)
})

test('虚拟通道的避让几何不得被三档并集顶替（ADR-44）', () => {
  const virtual = radarTierStats(WEATHER(), {radarAvoidance: {mode: 'virtual', included: true,
    sweepSlots: 8, sweepStrideMinutes: 60, areaKm2: 500.0}})
  assert.equal(virtual.avoidance.mode, 'virtual')
  assert.equal(virtual.avoidance.perTier, false)
  assert.equal(virtual.avoidance.unionKm2, 500)
  assert.equal(virtual.avoidance.coreKm2, null, '虚拟通道没有"某一帧的三档"这回事')
  // 负向对照：把并集塞进 coreKm2，屏幕上就会出现一个没人能核对的"内核面积"。
  const wrong = {...virtual.avoidance, coreKm2: virtual.avoidance.unionKm2}
  assert.notEqual(wrong.coreKm2, virtual.avoidance.coreKm2)
})

test('气象影响面按已写定的成因归因，不按几何相交', () => {
  const impact = weatherImpact({}, FLIGHTS, NETWORK)
  assert.equal(impact.weatherFlights, 2)
  assert.equal(impact.otherFlights, 1)
  const radarField = impact.rows.find(row => row.basis === 'RADAR_FIELD')
  assert.equal(radarField.count, 1)
  assert.deepEqual(radarField.corridors, ['沈阳 ↔ 大连'])
  assert.equal(radarField.weather, true)
  const boundary = impact.rows.find(row => row.basis === 'BOUNDARY')
  assert.equal(boundary.weather, false, '作业区边界不是气象成因 —— 这正是 42 班那次错账')
  // 六条：0.9.27 加入 `LOW_VISIBILITY`。这个数字是**契约的宽度**，不是凑数：
  // 它一改，说明有一条新的成因可以被归因了，而界面必须能显示它。
  assert.equal(IMPACT_BASES.length, 6)
  assert.ok(IMPACT_BASES.includes('LOW_VISIBILITY'))
})

test('时间演变：实测通道对"逐时回波序列"明确弃权，不画平线', () => {
  const measured = weatherEvolution({radarAvoidance: {mode: 'measured', included: true,
    slot: '2026-01-01T00:00:00Z', slotAgeMinutes: 12}}, FLIGHTS)
  assert.equal(measured.evolution.state, 'SINGLE_OBSERVATION')
  assert.match(measured.evolution.note, /不提供逐时回波序列/)
  const virtual = weatherEvolution({radarAvoidance: {mode: 'virtual', included: true,
    sweepSlots: 8, sweepStrideMinutes: 60, slot: 'S', slotTo: 'E'}}, FLIGHTS)
  assert.equal(virtual.evolution.state, 'PER_SLOT')
  assert.equal(virtual.evolution.slots, 8)
  const none = weatherEvolution({radarAvoidance: {included: false, reason: 'NO_CONVECTIVE_ECHO'}}, FLIGHTS)
  assert.equal(none.evolution.state, 'NOT_INCLUDED')
  // 弃权产物必须与"有内容"可区分（M67）。
  assert.notEqual(measured.evolution.note, virtual.evolution.note)
})

test('时间演变的运行结果轴按班次起降分钟分桶，四桶之和等于总班数', () => {
  const evolution = weatherEvolution({}, FLIGHTS, {step: 60, span: 480})
  assert.equal(evolution.bucketCount, 8)
  const sum = evolution.buckets.reduce((total, row) => total + row.departures, 0)
  assert.equal(sum, FLIGHTS.filter(f => Number.isFinite(f.departureMinute)).length)
  assert.ok(evolution.peak && evolution.peak.detoured > 0)
  // 负向对照：桶宽不覆盖跨度时和必然对不上 —— 这条判据是真的在数。
  const short = weatherEvolution({}, FLIGHTS, {step: 60, span: 60})
  assert.notEqual(short.buckets.reduce((t, r) => t + r.departures, 0), sum)
})

// =============================================================================
// P0-3：四态状态机与一键处置
// =============================================================================
test('处置状态机是四态以上，且「待确认」不是一条可写的记录', () => {
  for (const key of ['PENDING', 'ACKNOWLEDGED', 'IN_PROGRESS', 'HANDLED', 'REVIEWED']) {
    assert.ok(DISPOSAL_STATE_KEYS.includes(key), `缺少状态 ${key}`)
  }
  assert.equal(disposalStateLabel('IN_PROGRESS'), '处置中')
  assert.equal(disposalStateLabel('REVIEWED'), '已复核')
  assert.equal(disposalStateLabel('NOPE'), 'absent')
})

test('做不到的动作必须显式说"本系统不支持"，不得假装成功', () => {
  const delay = disposalAction('DELAY')
  const detour = disposalAction('DETOUR')
  const suspend = disposalAction('SUSPEND')
  assert.equal(delay.supported, false)
  assert.equal(detour.supported, false)
  assert.equal(suspend.supported, true)
  for (const action of [delay, detour]) {
    assert.ok(action.why && action.why.length > 10,
      `${action.key} 声明了不支持，就必须说清为什么不支持 —— 只回一句"不支持"和报错长得一样`)
  }
  // 负向对照：把它们标成 supported=true，界面上就会发一个注定失败的请求，
  // 再把 404 渲染成"已处置"。
  assert.notEqual(delay.supported, true)
})

test('下一步动作按状态推进，已复核之后不再给动作', () => {
  // 0.11.3（W-06）改了契约：不再返回 `supported:false` 的动作。
  // DELAY / DETOUR 的 supported 仍是 false（上一条钉着），它们因此不出现在"下一步"里 ——
  // 页面上那两个「（不支持）」灰按钮正是这个缺口的报信人，删掉它比留着更诚实。
  assert.deepEqual(disposalNextActions('PENDING').map(a => a.key), ['SUSPEND'])
  assert.deepEqual(disposalNextActions('ACKNOWLEDGED').map(a => a.key), ['SUSPEND'])
  assert.deepEqual(disposalNextActions('IN_PROGRESS').map(a => a.key), ['HANDLED'])
  assert.deepEqual(disposalNextActions('HANDLED').map(a => a.key), ['REVIEWED'])
  assert.deepEqual(disposalNextActions('REVIEWED'), [])
  assert.equal(DISPOSAL_FLOW.length, DISPOSAL_STATE_KEYS.length)
})

// =============================================================================
// P2-3：回放带当时气象帧
// =============================================================================
test('回放气象帧：对不上就说对不上，不把当前帧冒充成当时的帧', () => {
  const aligned = replayWeatherFrame(WEATHER({minute: 120}), 120)
  assert.equal(aligned.state, 'ALIGNED')
  assert.equal(aligned.tiers.strong, 8.4)
  const off = replayWeatherFrame(WEATHER({minute: 480}), 120)
  assert.equal(off.state, 'MISALIGNED')
  assert.match(off.note, /请勿把它读成回放时刻的天气/)
  // 负向对照：把状态判据去掉（永远 ALIGNED），两帧就长得一样了。
  assert.notEqual(off.state, aligned.state)
  assert.equal(replayWeatherFrame(null, 120).state, 'ABSENT')
  // 帧不可用时不得报出 0 面积假装"晴朗"。
  assert.equal(replayWeatherFrame(WEATHER({radar: {available: false, regions: []}}), 30).tiers.strong, null)
})

// =============================================================================
// 图层清单：三处副本收成一处的**回执**
// =============================================================================
test('图层清单九条齐全，且每条都带两个色标类名', () => {
  // 0.9.27 加入 `fog`（低能见度／雾）。它与 `weather` 相邻不是排版：两条都是站点点观测
  // 派生的风险区，而它们**必须可以分别开关** —— 用户要的正是"把雾和正常雷达回波区分开"，
  // 而"必须先关掉气象风险区才看得到雾"就不算区分。
  assert.deepEqual(MAP_LAYERS.map(layer => layer.key),
    ['car', 'delivery', 'weather', 'fog', 'wind', 'radar', 'zones', 'events', 'observations'])
  for (const layer of MAP_LAYERS) {
    assert.ok(layer.label && layer.title, `${layer.key} 缺文案`)
    assert.ok(layer.dot && layer.rowDot, `${layer.key} 缺色标类名`)
  }
  assert.ok(SEVERITY_RING_M > 0)
})

test('工作台的开关表必须与清单逐键对齐 —— 少一个键就是"这个图层切不动"', () => {
  const source = readFileSync(new URL('../src/components/TrafficWorkbench.vue', import.meta.url), 'utf8')
  const literal = source.match(/const layerRefs\s*=\s*\{([\s\S]*?)\}/)
  assert.ok(literal, '工作台里找不到 layerRefs 开关表')
  const keys = [...literal[1].matchAll(/([A-Za-z][A-Za-z0-9]*)\s*:/g)].map(match => match[1])
  assert.deepEqual([...keys].sort(), MAP_LAYERS.map(layer => layer.key).sort(),
    '开关表与 MAP_LAYERS 的键不一致 —— 清单加了图层而开关没加，症状是"切不动"而不是报错')
})

test('首页不再保存第二份图层清单，只从唯一来源渲染', () => {
  const source = readFileSync(new URL('../src/components/traffic/HomeStage.vue', import.meta.url), 'utf8')
  assert.match(source, /MAP_LAYERS/, '首页必须从唯一来源读图层清单')
  assert.doesNotMatch(source, /dot:\s*'d-/, '首页里还留着第二份色标清单 —— 两处会分叉')
})
