import test from 'node:test'
import assert from 'node:assert/strict'
import {metarLines,supplementCoverageNote,supplementObservationRows,modelSpreadRows}
  from '../src/traffic/runtime.js'

// 免费补充气象源（0.9.35（Beta））的渲染判据。
//
// 为什么这一组必须存在
// --------------------
// 这两条通道的形状和主链路**不一样**，而三种"不一样"都会静默出错：
//
//   ① **`6+` 是下限**：METAR 的能见度 `6+` 表示"大于 6 英里"。渲染成一个精确数
//      （9656 m / 9.7 km）会让读者把"至少"读成"正好"；渲染成 `//`（缺测）又会让
//      一条**报了**的要素看起来像没报 —— 三种状态必须是三句话。
//   ② **覆盖不到 ≠ 那里没有天气**：33 个地级行政区里只有一部分附近有机场站。
//      不把缺席的城市点名，空白就会被读成"这一片天气很好"。
//   ③ **单侧有值不给差值**：两个模型只有一个回答了，差值报 `0` 会被读成
//      "两个模型完全一致"（缺值 ≠ 零，与后端 `multi_model_spread()` 同一条纪律）。
//
// 夹具照抄后端 `_metar_observation()` / `multi_model_spread()` 的**真实字段名**
// （`windSpeed10mMps` / `visibilityM` / `visibilityIsLowerBound` / `stationDistanceKm`），
// 不写前端想象中的形状。

const METAR_PAYLOAD = {
  available: true,
  provider: 'AVIATION_WEATHER_CENTER',
  dataType: 'STATION_OBSERVATION_METAR',
  coverage: {
    requestedCities: 33, returnedCities: 2, stationsSeen: 23,
    citiesWithoutNearbyStation: ['MOHE', 'HLBE'], radiusKm: 150,
    routeCoverage: 'AIRPORT_POINT_OBSERVATIONS_ONLY',
  },
  qualityFlags: ['STATION_OBSERVATION_NOT_AREA_FIELD', 'NOT_A_RADAR_ECHO_DO_NOT_CONVERT_TO_DBZ'],
  observations: [
    {
      cityId: 'SY', cityName: '沈阳', stationId: 'ZYTX', stationDistanceKm: 12.4,
      validAt: '2026-10-17T12:30:00Z', temperatureC: 21, windSpeed10mMps: 6.2,
      windGusts10mMps: null, windDirection10mDeg: 200, weatherCode: null,
      conditionClass: null, visibilityM: null, visibilityIsLowerBound: true,
      rawText: 'METAR ZYTX 171230Z 20006MPS 9999 21/12 Q1013 NOSIG',
    },
    {
      cityId: 'DL', cityName: '大连', stationId: 'ZYTL', stationDistanceKm: 9.1,
      validAt: '2026-10-17T12:30:00Z', temperatureC: 19, windSpeed10mMps: 8.7,
      windGusts10mMps: 17, windDirection10mDeg: 130, weatherCode: '-SHRA',
      conditionClass: null, visibilityM: 6003, visibilityIsLowerBound: false,
      rawText: 'METAR ZYTL 171230Z 13009G17MPS 6000 -SHRA FEW009 BKN020 19/19 Q1012',
    },
  ],
}

const SPREAD_PAYLOAD = {
  available: true,
  provider: 'OPEN_METEO_MULTI_MODEL',
  models: ['GFS', 'ICON'],
  qualityFlags: ['MODEL_DISAGREEMENT_IS_UNCERTAINTY_NOT_ERROR', 'NOT_A_SECOND_OBSERVATION'],
  rows: [
    {cityId: 'SY', cityName: '沈阳',
     models: {GFS: {temperatureC: 19.9, windSpeed10mMps: 5.1}, ICON: {temperatureC: 16.8, windSpeed10mMps: 7.4}},
     temperatureSpreadC: 3.1, windSpreadMps: 2.3},
    // ICON 没返回这一条 —— 单侧有值。
    {cityId: 'DL', cityName: '大连',
     models: {GFS: {temperatureC: 18.2, windSpeed10mMps: 6.0}, ICON: {temperatureC: null, windSpeed10mMps: null}},
     temperatureSpreadC: null, windSpreadMps: null},
  ],
}

const lineOf = (lines, label) => lines.find(line => line.label === label)?.value

// ---- ① 能见度的三种状态是三句话 ---------------------------------------------

test('能见度「仅报下限」既不是缺测也不是精确值', () => {
  const bound = metarLines(METAR_PAYLOAD.observations[0])
  assert.equal(lineOf(bound, '能见度'), '仅报下限（>6 mi）')
  // 它**不能**退化成缺测的 `//`：那会让"报了、只是只报下限"看起来像"没报"。
  assert.notEqual(lineOf(bound, '能见度'), '//')
  assert.notEqual(lineOf(bound, '能见度'), '0 km')

  const exact = metarLines(METAR_PAYLOAD.observations[1])
  assert.equal(lineOf(exact, '能见度'), '6.0 km')

  // 真缺测仍然写 `//` —— 三档不许塌成两档。
  assert.equal(lineOf(metarLines({cityName: 'X'}), '能见度'), '//')
})

// ---- ② 覆盖：缺席要按原因点名 ----------------------------------------------

test('覆盖口径点名缺席城市，并声明这不是面上的气象场', () => {
  const note = supplementCoverageNote(METAR_PAYLOAD)
  assert.match(note, /2\/33 个城市有邻近机场站/)
  assert.match(note, /半径 150 km/)
  assert.match(note, /无邻近站 2 个：MOHE、HLBE/)
  assert.match(note, /不是面上的气象场/)
})

test('通道不可用时说出原因，而不是说「没有天气」', () => {
  assert.equal(supplementCoverageNote({available: false, errorCode: 'ConnectTimeout'}),
    '补充通道不可用（ConnectTimeout）')
  // 连 errorCode 都没有时也不许沉默。
  assert.equal(supplementCoverageNote(null), '补充通道不可用')
  // 取到了但一个站都没有：仍要说清"0 个"，不能留空。
  assert.match(supplementCoverageNote({available: true, coverage: {requestedCities: 33, returnedCities: 0}}),
    /0\/33 个城市有邻近机场站/)
})

// ---- ③ 行结构与排序复用既有实现 --------------------------------------------

test('报文行复用 metarLines 的读法，坏天气在前，原始报文保留', () => {
  const rows = supplementObservationRows(METAR_PAYLOAD)
  assert.equal(rows.length, 2)
  // 大连能见度 6.0 km < 沈阳（只报下限 ⇒ 视作 Infinity，排后面）。
  assert.deepEqual(rows.map(row => row.stationId), ['ZYTL', 'ZYTX'])
  assert.equal(rows[0].stationDistanceKm, '9 km')
  assert.equal(rows[0].rawText, METAR_PAYLOAD.observations[1].rawText)
  // 复用而不是另写一套：行数与 `metarLines` 完全一致（6 行）。
  assert.equal(rows[0].lines.length, metarLines(METAR_PAYLOAD.observations[1]).length)
  // 空载荷不能炸，也不能假装有一行。
  assert.deepEqual(supplementObservationRows(null), [])
})

test('双模型差值：单侧有值不给 0.0', () => {
  const rows = modelSpreadRows(SPREAD_PAYLOAD)
  assert.equal(rows[0].temperatureText, '3.1 ℃')
  assert.equal(rows[0].windText, '2.3 m/s')
  assert.equal(rows[0].models, 'GFS / ICON')
  // 关键：`null` 不能渲染成 `0.0 ℃`（那是"两个模型完全一致"）。
  assert.equal(rows[1].temperatureText, '仅一侧有值，不给差值')
  assert.equal(rows[1].windText, '仅一侧有值，不给差值')
  assert.deepEqual(modelSpreadRows({rows: []}), [])
})
