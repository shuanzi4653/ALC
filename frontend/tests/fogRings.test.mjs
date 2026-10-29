/**
 * 雾区影响圈判据（0.11.8）。
 *
 * 为什么补这一份：0.11.7 的 B 方案上线时，`paintFogCircles` 被补丁写到了
 * `</script>` **之后** —— 函数不在模块里、每次重画抛 ReferenceError，而
 * 构建绿、435 条测试绿。**这段几何当时一条判据都没有**，所以谁都没发现。
 *
 * 判据分三类：
 *   ① 形状：24 个外点 + 闭合、经纬度顺序正确（MapLibre 是 [lon, lat]）；
 *   ② 口径：半径必须与 `config/rules-v1.json` 的阈值档位**对应**，不是魔法数；
 *   ③ 缺席：没有 lat/lon 的站不画、"能见度良好"的站不画 —— 不许把 `undefined`
 *      画成一个圈，也不许把 CLEAR 画成雾。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  FOG_RING_KM, FOG_SIGN_KM, FOG_SIGN_NOTE, fogRing, fogFeatureCollection, fogRingLayers,
} from '../src/traffic/runtime.js'

const RULES = JSON.parse(
  readFileSync(new URL('../../config/rules-v1.json', import.meta.url), 'utf8'))

/**
 * 找出"能见度"那一档阈值。
 *
 * 注意：`rules-v1.json` 里阈值的**标识写在值里**（`{"key":"visibilityM", ...}`），
 * 不是属性名 —— 所以不能只测 key 的名字，要测 `key/metric/id/label` 任一字段的
 * **值**。第一版就是照着属性名找的，于是判据自己先红了一次。
 */
function findVisibilityRule(node) {
  if (!node || typeof node !== 'object') return null
  if (!Array.isArray(node) && Number.isFinite(node.banValue) && Number.isFinite(node.warnValue)) {
    const id = [node.key, node.metric, node.id, node.label].filter(v => typeof v === 'string').join(' ')
    if (/visib|能见度/i.test(id)) return node
  }
  for (const value of Object.values(node)) {
    const hit = findVisibilityRule(value)
    if (hit) return hit
  }
  return null
}

test('半径与 rules-v1 的档位阈值对应，不是魔法数', () => {
  const rule = findVisibilityRule(RULES)
  assert.ok(rule, 'rules-v1.json 里找不到能见度阈值 —— 判据要跟着配置改')
  const { banValue: ban, warnValue: warn } = rule
  // 两档半径必须是两个**不同**的值，且 BAN 更小（越差的范围越靠近站）
  assert.ok(FOG_RING_KM.BAN < FOG_RING_KM.CAUTION,
    'BAN 档的圈必须比 CAUTION 档小，否则地图上"更严重"反而看起来更大')
  // 半径必须是"由阈值派生"的量级：ban 1 km 对应个位数公里
  assert.ok(FOG_RING_KM.BAN >= ban / 1000 && FOG_RING_KM.BAN <= ban / 1000 + 6,
    `BAN 半径 ${FOG_RING_KM.BAN} km 与阈值 ${ban} m 不在同一量级`)
  assert.ok(FOG_RING_KM.CAUTION >= warn / 1000 && FOG_RING_KM.CAUTION <= warn / 1000 + 8,
    `CAUTION 半径 ${FOG_RING_KM.CAUTION} km 与阈值 ${warn} m 不在同一量级`)
})

test('一个圈是闭合多边形，坐标是 [lon, lat]', () => {
  const ring = fogRing(41.6398, 123.4833, 6)
  assert.equal(ring.length, 25, '24 个外点 + 1 个闭合点')
  assert.deepEqual(ring[0], ring[ring.length - 1], '首尾必须相同（GeoJSON 要求闭合）')
  for (const [lon, lat] of ring) {
    assert.ok(lon > 120 && lon < 127, `经度越界：${lon}`)
    assert.ok(lat > 38 && lat < 47, `纬度越界：${lat}`)
  }
})

test('半径随纬度正确缩放：6 km 的圈南北跨约 0.108 度', () => {
  const ring = fogRing(41.6398, 123.4833, 6)
  const lats = ring.map(([, lat]) => lat)
  const lons = ring.map(([lon]) => lon)
  const dLat = Math.max(...lats) - Math.min(...lats)
  const dLon = Math.max(...lons) - Math.min(...lons)
  // 6 km / 111.32 km per deg ≈ 0.0539 deg 半径 → 直径 0.1078
  assert.ok(Math.abs(dLat - 0.1078) < 0.004, `南北直径 ${dLat.toFixed(4)} 度，期望 ≈ 0.1078`)
  // 高纬度上经度的度数值要更大（同样 6 km 对应更多经度）
  assert.ok(dLon > dLat, `41.6°N 上经度跨度应大于纬度跨度（${dLon.toFixed(4)} vs ${dLat.toFixed(4)}）`)
})

test('只有实测且达到某一档的站才画圈', () => {
  const stations = [
    { station: 'ZYTX', visM: 997.8, visLevel: 'BAN', lat: 41.6398, lon: 123.4833 },
    { station: 'ZYTL', visM: 2800.3, visLevel: 'CAUTION', lat: 38.9657, lon: 121.5386 },
    { station: 'ZYHB', visM: 1593, visLevel: 'CAUTION', lat: 45.6234, lon: 126.25 },
    { station: 'CLEAR', visM: 20000, visLevel: 'CLEAR', lat: 43, lon: 125 },
  ]
  const fc = fogFeatureCollection(stations)
  assert.equal(fc.type, 'FeatureCollection')
  assert.equal(fc.features.length, 3, 'CLEAR 的站不画 —— 那是能见度良好的地方')
  const ban = fc.features.filter(f => f.properties.level === 'BAN')
  assert.equal(ban.length, 1)
  assert.equal(ban[0].properties.station, 'ZYTX')
  assert.match(ban[0].properties.title, /非实测雾区边界/,
    'tooltip 必须写明"圈是影响范围示意，不是实测雾区边界"')
})

test('没有经纬度的站不画（缺席不是 0）', () => {
  const fc = fogFeatureCollection([
    { station: 'NOCOORD', visM: 800, visLevel: 'BAN' },
    { station: 'NULLLAT', visM: 800, visLevel: 'BAN', lat: null, lon: 123 },
  ])
  assert.equal(fc.features.length, 0,
    '缺坐标的站不能画在 (0,0)，也不能当成"没有雾"——它只是没坐标')
})

test('入参不是数组时返回空集合，不抛错', () => {
  for (const bad of [null, undefined, {}, 'x', 42]) {
    const fc = fogFeatureCollection(bad)
    assert.equal(fc.type, 'FeatureCollection')
    assert.equal(fc.features.length, 0)
  }
})

// ---- 渲染层 ---------------------------------------------------------------
//
// 这一段是 0.11.9 加的，起因是线上反馈"地图上看不到雾区"。我第一版把它判成
// "图层没建起来"（以为 `line-dasharray` 不吃数据驱动），**判错了**：MapLibre 26 的
// property-type 是 `cross-faded-data-driven`，数据驱动是允许的。
// 真正的原因是**对比度**：`#4A5568` 的深灰压在近黑底图（`#102536`）上，
// WCAG 对比度只有 2.1:1，而全域视图下 6 km 的圈只有十几像素宽 —— 等于没画。
//
// 所以这里的判据不是"我读代码觉得对"，而是两条可算数：
//   ① 分档写法（filter + 常量 dasharray，属于可读性口径，附规格表事实）；
//   ② **描边与底色的对比度 ≥ 3:1**，用 WCAG 相对亮度算，旧配色会红。
const MAP_VUE = readFileSync(
  new URL('../src/components/CityTrafficMap.vue', import.meta.url), 'utf8')

const BASEMAP_BG = '#102536' // `.city-map-shell` 的底色，也是深色底图的下限

function luminance(hex) {
  const value = hex.replace('#', '')
  const channels = [0, 2, 4].map(i => parseInt(value.slice(i, i + 2), 16) / 255)
    .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
}

function contrastRatio(a, b) {
  const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m)
  return (x + 0.05) / (y + 0.05)
}

test('描边与深色底图的对比度 ≥ 3:1（0.11.7 的深灰只有 2.1:1，等于没画）', () => {
  const lines = fogRingLayers().filter(l => l.type === 'line')
  assert.equal(lines.length, 2, '两档描边')
  for (const line of lines) {
    const color = line.paint['line-color']
    assert.match(color, /^#[0-9A-Fa-f]{6}$/, `${line.id} 的描边必须是纯色常量，才能算对比度`)
    const ratio = contrastRatio(color, BASEMAP_BG)
    assert.ok(ratio >= 3,
      `${line.id} 的 ${color} 对 ${BASEMAP_BG} 只有 ${ratio.toFixed(2)}:1，深色底图上会看不见`)
  }
  // **判据自己必须有牙齿**：0.11.7 用的那个深灰，按同一套算法必须不达标。
  assert.ok(contrastRatio('#4A5568', BASEMAP_BG) < 3,
    '旧配色居然达标了 —— 说明这个阈值选得没有意义，判据要重写')
})

test('分档用 filter + 常量 dasharray（可读性口径，不是框架限制）', () => {
  const layers = fogRingLayers()
  assert.equal(layers.length, 3, '面 1 层 + 描边 2 层（BAN / CAUTION）')
  for (const line of layers.filter(l => l.type === 'line')) {
    assert.ok(Array.isArray(line.filter), `${line.id} 缺少 filter`)
    assert.ok(Array.isArray(line.paint['line-dasharray'])
      && line.paint['line-dasharray'].every(v => typeof v === 'number'),
    `${line.id} 的 dasharray 应是常量数组（合成一条 ['case',…] 时改一处要看三处）`)
  }
})

test('MapLibre 规格表：line-dasharray 允许数据驱动（所以别拿它当"抛错"的理由）', async () => {
  let latest
  try {
    ;({ latest } = await import('@maplibre/maplibre-gl-style-spec'))
  } catch (_) {
    console.log('SKIP 没有 style-spec —— 无法测量，不是"通过"')
    return
  }
  const type = latest.paint_line['line-dasharray']['property-type']
  // 记这条是为了**防止以后有人再用"会抛错"来解释代码写法**：它不会抛。
  // 顺带记一个量具盲区：`validateStyleMin` 对数据驱动的 dasharray 返回 0 错误，
  // 也就是"官方校验通过"并不能证明运行时不抛 —— 那次误判就是被它放过导致的。
  assert.match(type, /data-driven/,
    `规格表变成 ${type} 了，注释与判据都要跟着改`)
})

test('雾区画圈函数仍在模块内，且被重画链调用', () => {
  const close = MAP_VUE.indexOf('</script>')
  const definition = MAP_VUE.indexOf('function paintFogCircles(')
  assert.ok(definition > 0, 'paintFogCircles 不见了')
  assert.ok(definition < close,
    'paintFogCircles 定义在 </script> 之后（不在模块里）—— 调用时必然 ReferenceError')
  assert.match(MAP_VUE, /paintFogCircles\(\);map\.triggerRepaint\(\)/,
    'paintFogCircles 没有接进 rebuild 的重画链')
})

// ---- 0.11.11（G-1）：雾天案例页要真的画得出来 ------------------------------
// 0.11.10 的现场：徽标写"实测 4 站 · 最低 998 m"、KPI 写 18 条禁飞，地图上一个像素
// 都没有 —— 因为圈按判据阈值（6/12 km）画，落在东北三省全域视图里只有 7–13 px。
// 这是**尺度**问题，不是数据问题，所以修法是把"画多大"与"判据多严"拆成两个常量。
test('G-1：示意半径与判据阈值是两个常量，不许合并', () => {
  assert.deepEqual(FOG_SIGN_KM, { BAN: 60, CAUTION: 36 })
  assert.ok(FOG_SIGN_KM.BAN > FOG_RING_KM.BAN && FOG_SIGN_KM.CAUTION > FOG_RING_KM.CAUTION,
    '示意半径必须严格大于判据阈值 —— 相等就等于又回到"看不见"')
  // 判据阈值仍来自规则文件（这一条把"画多大"与"算多严"钉开）
  const rule = findVisibilityRule(RULES)
  assert.ok(rule, 'rules-v1.json 里找不到能见度阈值')
  // 阈值是 1 000 m，判据半径 6 km —— 它**不是**阈值的等比结果，而是"站点半径 + 扩散"的
  // 工程取值；所以这里只断言量级（与既有那条判据同口径），不把两者写成等式。
  assert.ok(FOG_RING_KM.BAN >= rule.banValue / 1000 && FOG_RING_KM.BAN <= rule.banValue / 1000 + 6,
    'BAN 判据半径与规则阈值不在同一量级')
})

test('G-1：圈的几何用示意半径，圆心与两行标签随几何一起给出', () => {
  const fc = fogFeatureCollection([
    { station: 'ZYTX', visM: 997.8, visLevel: 'BAN', lat: 41.6398, lon: 123.4833 },
    { station: 'ZYHB', visM: 1593.3, visLevel: 'CAUTION', lat: 45.6234, lon: 126.25 },
    { station: 'ZYCC', visM: 9999, visLevel: 'CLEAR', lat: 43.9962, lon: 125.6853 },
  ])
  assert.equal(fc.features.length, 2, 'CLEAR 的站不该画圈')
  const ban = fc.features.find((f) => f.properties.level === 'BAN')
  const north = Math.max(...ban.geometry.coordinates[0].map((c) => c[1]))
  const south = Math.min(...ban.geometry.coordinates[0].map((c) => c[1]))
  // 60 km 半径 → 直径 120 km ≈ 1.078 度（实测：40 km 的圈在全域视图下与城市装饰光环同尺寸，
  // 被整片盖住 —— 放大到 60 km 才让它的边跑到光环之外）
  assert.ok(Math.abs((north - south) - 1.078) < 0.04,
    `BAN 圈南北直径 ${(north - south).toFixed(4)} 度，期望 ≈1.078（60 km 半径）`)
  assert.deepEqual(ban.properties.center, [123.4833, 41.6398])
  assert.equal(ban.properties.label, 'ZYTX · 998 m')
  assert.match(ban.properties.tier, /不可飞/)
})

test('G-1：图层说明必须写出「不是实测雾区边界」', () => {
  assert.ok(FOG_SIGN_NOTE.includes('不是实测雾区边界'),
    '这句话是这一页的诚实底线：圈是示意，不是观测面')
  assert.match(FOG_SIGN_NOTE, /60 \/ 36 km/)
})

test('G-1：中心标签走 HTML 覆盖层，且随地图移动重投影', () => {
  assert.match(MAP_VUE, /class="city-map-fog-labels"/, '标签容器不在模板里')
  // 0.11.26 起 `move` 上挂的是**两个**重投影（雾标签 + 走廊带标签），所以这里
  // 不能再钉 `map.on('move',syncFogLabels)` 这一个字面形态 —— 判据要钉的是
  // 「move 事件里调到了 syncFogLabels」，不是它排第几。
  const moveBinding = MAP_VUE.match(/map\.on\('move',\s*\(\)\s*=>\s*\{([^}]*)\}/)
  assert.ok(moveBinding, '拖动地图后标签不重投影 —— 会停在旧位置，比没有标签更误导')
  assert.match(moveBinding[1], /syncFogLabels\(\)/,
    '拖动地图后标签不重投影 —— 会停在旧位置，比没有标签更误导')
  // 这个 style 没有配 glyphs，MapLibre 的 symbol 文字层不会渲染、也不报错。
  const layerTypes = fogRingLayers().map((l) => l.type)
  assert.ok(!layerTypes.includes('symbol'),
    '雾圈不许用 symbol 层出文字：没有 glyphs 时它会安静地什么都不画')
})
