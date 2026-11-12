// 雷达图例与贴图的护栏（V1.0.7）
//
// 这一套守的是本次"回波显示"改造里最容易悄悄漂掉的三件事：
//   ① 图例的「颜色 ↔ dBZ」必须与后端色板**同一份**（原来手抄 13 块，30/35/40/45
//      四个标签分别印在 34/38/42/46 的颜色上 —— 35 那块实际已经越过绕飞线）；
//   ② 省界只许描一遍（两层重合几何会让无回波区的线叠到 α0.77、有回波区只有一层）；
//   ③ 贴图不许挂 :key / echo-in（换帧时回波整体消失 260ms）。
//
// 基准是后端 `weather/radar_public.py`：这里直接解析它，不在前端另存一份"期望值"。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..')
const read = (p) => readFileSync(join(root, p), 'utf8')

const map = read('src/components/traffic/NationMap.vue')
const radarPy = readFileSync(join(root, '..', 'backend-python', 'weather', 'radar_public.py'), 'utf8')
const dbzPy = readFileSync(join(root, '..', 'backend-python', 'weather', 'dbz.py'), 'utf8')

/** 从 radar_public.py 里取出 NEXRAD_LUT 的 (断点, 颜色) 序列。 */
function backendLut() {
  const block = radarPy.slice(radarPy.indexOf('NEXRAD_LUT'), radarPy.indexOf('_lock = threading.Lock()'))
  const rows = []
  const re = /\(\s*([\d.]+),\s*\((\d+),\s*(\d+),\s*(\d+),\s*\d+\)\)/g
  let m
  while ((m = re.exec(block))) {
    rows.push({ dbz: Number(m[1]), color: `#${[m[2], m[3], m[4]].map((v) => Number(v).toString(16).padStart(2, '0')).join('')}` })
  }
  return rows
}

/** 从 radar_public.py 里取出可达 dBZ 集合（COLOUR_TO_DBZ 的值）。 */
function reachableDbz() {
  const block = radarPy.slice(radarPy.indexOf('COLOUR_TO_DBZ'), radarPy.indexOf('REACHABLE_DBZ'))
  const values = new Set()
  const re = /\(\s*\d+,\s*\d+,\s*\d+\):\s*([\d.]+)/g
  let m
  while ((m = re.exec(block))) values.add(Number(m[1]))
  return [...values].sort((a, b) => a - b)
}

/** 用后端的规则推出图例（与 nexrad_scale() 同构）。 */
function derivedScale() {
  const lut = backendLut()
  const reachable = reachableDbz()
  const kept = lut.filter((row, i) => {
    const ceiling = i + 1 < lut.length ? lut[i + 1].dbz : Infinity
    return reachable.some((v) => v >= row.dbz && v < ceiling)
  })
  return kept.map((row, i) => ({ dbz: row.dbz, until: i + 1 < kept.length ? kept[i + 1].dbz : null, color: row.color }))
}

function fallbackScale() {
  const block = map.slice(map.indexOf('const FALLBACK_SCALE'), map.indexOf('// WCAG 相对亮度'))
  const rows = []
  const re = /\{dbz:([\d.]+),until:([\d.]+|null),color:'(#[0-9a-f]{6})'\}/g
  let m
  while ((m = re.exec(block))) rows.push({ dbz: Number(m[1]), until: m[2] === 'null' ? null : Number(m[2]), color: m[3] })
  return rows
}

test('图例兜底色阶与后端 nexrad_scale() 逐条一致', () => {
  const expected = derivedScale()
  assert.deepEqual(fallbackScale(), expected,
    '前端兜底表与后端色阶不一致：改色板/改可达集合时必须同批改，否则图例会把 35 印在别的颜色上')
})

test('图例是 12 条，且不含结构性不可达的 10 与 65', () => {
  const rows = fallbackScale()
  assert.equal(rows.length, 12)
  const values = rows.map((r) => r.dbz)
  assert.ok(!values.includes(10), '10 dBZ 档不可达（反查下限是 15）')
  assert.ok(!values.includes(65), '65 dBZ 档不可达（65–74 同色白，代表值取 70）')
  assert.equal(rows[rows.length - 2].until, 70, '60 那格应覆盖到 70')
})

test('图例渲染由载荷驱动，不是写死的 13 个 span', () => {
  assert.match(map, /v-for="s in radarScale"/)
  assert.match(map, /:style="\{background:s\.color\}"/)
  assert.ok(!/scale-step" style="background:#/.test(map), ' 模板里还留着写死的色块')
})

test('图例不宣称自己是基数据', () => {
  assert.ok(!map.includes('0.5° 基数据'), 'dBZ 是图片颜色反算出来的，不是 0.5° 基数据')
  assert.match(map, /图像反演（估）/, '必须标"图像反演（估）· 非观测"')
  assert.match(map, /模拟回波（演示包）/, '虚拟气象要单独一套说法')
})

test('图例阈值取自载荷 thresholdsDbz，不另存一份', () => {
  assert.match(map, /thresholdsDbz/)
  assert.match(map, /r\.virtual/)
})

test('省界只描一遍：基础层 stroke:none', () => {
  const base = map.slice(map.indexOf('<!-- 1 行政区底色'), map.indexOf('<!-- 2 雷达'))
  assert.match(base, /stroke: 'none'/, '基础层必须只填充不描边')
  const strokes = map.match(/var\(--map-line\)/g) || []
  assert.equal(strokes.length, 1, `--map-line 只该被描边层引用，实际 ${strokes.length} 处`)
})

test('贴图不挂 :key、不挂 echo-in（换帧空窗 260ms）', () => {
  const start = map.indexOf('<image v-if="radarImage"')
  assert.ok(start > 0, '找不到贴图层')
  const tag = map.slice(start, map.indexOf('/>', start) + 2)
  assert.ok(!/:key=/.test(tag), '贴图不该按帧换 key：同一 URI 会被反复解码')
  assert.ok(!/echo-in/.test(tag), '贴图不该淡入：旧图先销毁 = 回波消失 0.26s')
})

test('贴图只在全国层用（其余层级回退矢量环）', () => {
  const computed = map.slice(map.indexOf('const radarImage=computed'), map.indexOf('// —— 回波环 ——'))
  assert.match(computed, /imageScope/)
  assert.match(computed, /level\.value!=='nation'/)
})

test('图例不再挡住左上角的航线显示面板', () => {
  assert.match(map, /\.nmap-radar-scale\{position:absolute;right:14px/)
})

test('图例数值来自 payload，不与 dbz.py 的阈值各说各话', () => {
  // dbz.py 是唯一来源：这里只断言它仍然是 15/35/45，避免"改了常量但文档还是旧值"
  assert.match(dbzPy, /ECHO_FLOOR_DBZ = 15\.0/)
  assert.match(dbzPy, /CONVECTIVE_DBZ = 35\.0/)
  assert.match(dbzPy, /STRONG_DBZ = 45\.0/)
})
