import test from 'node:test'
import assert from 'node:assert/strict'
import { DESTS, ROUTES, windLine, buildRouteSeries, buildWeatherSeries, buildRiskSeries, buildOperationPoint,
  planSafeRoute, segmentHitsPolygon } from '../src/map/layerRenderers.js'
import { normalizeLayers } from '../src/composables/useMapLayers.js'
import { levelStyle } from '../src/utils.js'

const CENTER = [121.61, 38.91]
const ALL_ON = { wind: true, precipitation: true, thunder: true, risk: true, routes: true }
const layer = (kind, data, status = 'READY') => ({ kind, data, status, runId: 'r1', regionId: 'zone', revision: 2,
  expiresAt: '2030-01-01T00:00:00Z' })
const weatherLayers = [
  layer('WIND', { windDeg: 90, windSpeed: 5, points: [{ name: '沈阳', lon: 123.4, lat: 41.8, windDeg: 90, windSpeed: 5 }] }),
  layer('PRECIPITATION', { value: 2, cells: [{ name: '辽中南', lon: 123.1, lat: 41.4, value: 2 }] }),
  layer('THUNDER_PROBABILITY', { value: .3, cells: [{ name: '吉林中部', lon: 125.8, lat: 43.7, value: .3 }] })]
const find = values => kind => values.find(item => item.kind === kind)
const polygon = { type: 'Polygon', coordinates: [[[120, 38], [122, 38], [122, 40], [120, 40], [120, 38]]] }

test('图层关闭时对应 series 完全不生成', () => {
  assert.deepEqual(buildRouteSeries(CENTER, '#2e8b57', false), [])
  assert.deepEqual(buildRiskSeries({ center: CENTER, layer: layer('RISK_AREA', null, 'NO_DATA'), level: 'BAN', style: levelStyle('BAN'), enabled: true }), [])
  assert.deepEqual(buildWeatherSeries({ center: CENTER, findLayer: find(weatherLayers), enabled: { wind: false, precipitation: false, thunder: false } }), [])
})

test('风向校验、静风和四个基准方向正确', () => {
  assert.equal(windLine(CENTER, null, 5), null)
  assert.equal(windLine(CENTER, -1, 5), null)
  assert.equal(windLine(CENTER, 360, 5), null)
  assert.equal(windLine(CENTER, 90, -1), null)
  assert.equal(windLine(CENTER, 0, 0).length, 1)
  assert(windLine(CENTER, 0, 5)[1][1] < CENTER[1], '北风吹向南')
  assert(windLine(CENTER, 90, 5)[1][0] < CENTER[0], '东风吹向西')
  assert(windLine(CENTER, 180, 5)[1][1] > CENTER[1], '南风吹向北')
  assert(windLine(CENTER, 270, 5)[1][0] > CENTER[0], '西风吹向东')
})

test('NO_DATA/EXPIRED 不从快照回退绘制', () => {
  const values = [layer('WIND', {}, 'NO_DATA'), layer('PRECIPITATION', { value: null }, 'NO_DATA'),
    layer('THUNDER_PROBABILITY', { value: .9 }, 'EXPIRED')]
  assert.deepEqual(buildWeatherSeries({ center: CENTER, findLayer: find(values), enabled: ALL_ON }), [])
})

test('降水和雷暴采用不同区域单体，不再与风或航线共用线型', () => {
  const values = [
    layer('PRECIPITATION', { value: 2, cells: [{ name: '辽中南', lon: 123, lat: 41, value: 2 }] }),
    layer('THUNDER_PROBABILITY', { value: .4, cells: [{ name: '吉林中部', lon: 126, lat: 44, value: .4 }] })]
  const series = buildWeatherSeries({ center: CENTER, findLayer: find(values), enabled: ALL_ON })
  assert.deepEqual(series.map(item => item.id), ['precipitation-areas', 'precipitation-stations', 'thunder-areas', 'thunder-stations'])
  assert.equal(series[1].symbol, 'circle')
  assert.equal(series[3].symbol, 'diamond')
  assert.notDeepEqual(series[1].data[0].value.slice(0, 2), series[3].data[0].value.slice(0, 2))
})

test('风险区同时消费 Polygon 与 MultiPolygon，只有 BAN 使用禁入', () => {
  const multi = { type: 'MultiPolygon', coordinates: [polygon.coordinates, [[[124, 42], [125, 42], [125, 43], [124, 43], [124, 42]]]] }
  const risk = { ...layer('RISK_AREA', { level: 'BAN' }), geometry: multi }
  const ban = buildRiskSeries({ center: CENTER, layer: risk, level: 'BAN', style: levelStyle('BAN'), enabled: true })
  const danger = buildRiskSeries({ center: CENTER, layer: risk, level: 'DANGER', style: levelStyle('DANGER'), enabled: true })
  assert.equal(ban.length, 2)
  assert.equal(ban[0].data.length, 2)
  assert.match(ban[1].data[0].label, /禁飞/)
  assert.doesNotMatch(danger[1].data[0].label, /禁飞/)
})

test('图层身份、版本和过期时间在发布前校验', () => {
  const identity = { runId: 'r1', regionId: 'zone', revision: 2 }
  const now = Date.parse('2029-01-01T00:00:00Z')
  const result = normalizeLayers([
    layer('WIND', { windDeg: 0, windSpeed: 1 }),
    { ...layer('PRECIPITATION', { value: 1 }), runId: 'old' },
    { ...layer('THUNDER_PROBABILITY', { value: .2 }), expiresAt: '2028-01-01T00:00:00Z' }
  ], identity, now)
  assert.deepEqual(result.map(item => [item.kind, item.status]), [['WIND', 'READY'], ['THUNDER_PROBABILITY', 'EXPIRED']])
})

test('series id 稳定且作业点缺字段使用占位', () => {
  assert.deepEqual(buildRouteSeries(CENTER, '#2e8b57', true, layer('RISK_AREA',{assessmentStatus:'VALID',areas:[]})).map(s => s.id), ['routes', 'route-points', 'closed-routes'])
  assert.deepEqual(buildWeatherSeries({ center: CENTER, findLayer: find(weatherLayers), enabled: ALL_ON }).map(s => s.id),
    ['wind-field', 'precipitation-areas', 'precipitation-stations', 'thunder-areas', 'thunder-stations'])
  const point = buildOperationPoint({ center: CENTER, region: '演示区', levelLabel: '不可判定', color: '#6f95c4' })
  assert.match(point.label.formatter, /SFI --/)
  assert.match(point.label.formatter, /现象未知/)
})

test('危险航线绕行后不穿越限制区，额外一小时以上关闭', () => {
  const area = { polygon: [[1,-.1],[2,-.1],[2,.1],[1,.1],[1,-.1]] }
  const detour = planSafeRoute([0,0],[3,0],[area],120)
  assert.equal(detour.status, 'DETOUR')
  assert(detour.coords.length > 2)
  for (let i = 1; i < detour.coords.length; i++) assert.equal(segmentHitsPolygon(detour.coords[i-1], detour.coords[i], area.polygon), false)
  const closed = planSafeRoute([0,0],[3,0],[area],5)
  assert.equal(closed.status, 'CLOSED')
})

test('绕行航线以多段折线完整连接起点、拐点和终点', () => {
  const risk = layer('RISK_AREA', { areas: [{ name: '限制区', zoneType: 'BAN', polygon: [[122.0,39.8],[122.6,39.8],[122.6,40.6],[122.0,40.6],[122.0,39.8]] }] })
  const routes = buildRouteSeries(CENTER, '#2e8b57', true, risk)[0]
  assert.equal(routes.polyline, true)
  const diverted = routes.data.find(route => route.name.includes('绕行'))
  assert(diverted, '至少一条路线应触发绕行')
  assert.deepEqual(diverted.coords[0], DESTS.find(point => point.name === '大连').coord)
  assert.deepEqual(diverted.coords.at(-1), DESTS.find(point => point.name === '沈阳').coord)
})

test('航线限定东北城市并采用城市间骨干走廊', () => {
  assert.equal(DESTS.length, 10)
  assert.equal(ROUTES.length, 9)
  assert(ROUTES.every(([from, to]) => from !== to))
})
