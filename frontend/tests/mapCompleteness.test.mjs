// 地图完整性护栏（2026-11-10 用户硬要求："南海地区，地图完整！校验，这个不许出问题"）
//
// 三件事必须同时成立，任何一条被删都会让中国地图变"残图"：
//   ① 底图 35 个要素全部绘制 —— 34 个省级单元 + 南海诸岛界线（adchar=JD，name 为空）；
//   ② 省级单元一律**实线**，不许给台湾/西藏画虚线、也不许标"未通航"；
//   ③ 全国层必须有南海诸岛小图（inset），且小图经纬范围覆盖到曾母暗沙（约北纬 4°）。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..')
const read = (p) => readFileSync(join(root, p), 'utf8')

const china = JSON.parse(read('src/assets/china.json'))
const features = china.features || []

function flatten(node, out = []) {
  if (Array.isArray(node) && node.length && typeof node[0] === 'number') out.push(node)
  else if (Array.isArray(node)) node.forEach((child) => flatten(child, out))
  return out
}

test('底图包含全部 34 个省级单元（含台湾、西藏、港澳）', () => {
  const names = new Set(features.map((f) => (f.properties || {}).name).filter(Boolean))
  for (const name of ['台湾省', '西藏自治区', '香港特别行政区', '澳门特别行政区']) {
    assert.ok(names.has(name), `底图缺少 ${name}，中国地图不完整`)
  }
  assert.equal(names.size, 34, `省级单元应为 34 个，实际 ${names.size}`)
})

test('底图包含南海诸岛界线（adchar=JD），且一直画到北纬 5° 以南', () => {
  const boundary = features.find((f) => (f.properties || {}).adchar === 'JD')
  assert.ok(boundary, '底图缺少南海诸岛界线，南海会变成空白')
  const points = flatten(boundary.geometry.coordinates)
  const minLat = Math.min(...points.map((p) => p[1]))
  const minLon = Math.min(...points.map((p) => p[0]))
  const maxLon = Math.max(...points.map((p) => p[0]))
  assert.ok(minLat <= 5, `界线最南到北纬 ${minLat.toFixed(2)}°，没覆盖到曾母暗沙`),
  assert.ok(minLon >= 105 && maxLon <= 125, `界线经度 ${minLon}–${maxLon} 超出南海范围`)
})

// 地图拆成 NationPanel（外壳）+ NationMap（渲染）之后，护栏要两个文件一起读：
// 只看外壳会漏掉真正画图的那份，等于护栏自己先把门打开了。
const mapSource = () => read('src/components/traffic/NationPanel.vue') + '\n' + read('src/components/traffic/NationMap.vue')

test('省级单元一律实线：面板里不许给省界加虚线', () => {
  const source = mapSource()
  // 省界必须实线。但有两处虚线是有意的：① 选中班次的未飞行段（已飞实线/未飞虚线）；
  // ② 绕飞航段（琥珀虚线，V1.0.3 起）。所以只查**行政区渲染那一小段**。
  const shapeAt = source.indexOf('v-for="shape in shapes"')
  assert.ok(shapeAt > 0, '找不到行政区渲染段，护栏失效')
  const adminPart = source.slice(Math.max(0, shapeAt - 400), shapeAt + 800)
  assert.ok(!/stroke-dasharray/.test(adminPart), '行政区画图段出现了 stroke-dasharray —— 省界被画成虚线了')
  assert.ok(!/未纳入（不通航）|未通航/.test(source), '仍在单独标注"未通航"省份')
  // 判定按渲染层算：NationPanel 里的 border.excludedCities 是"边境退出通航"的数据，
  // 不是给省界套特殊样式，所以这一条只查画图的那个文件。
  const renderer = read('src/components/traffic/NationMap.vue')
  assert.ok(!/excluded/.test(renderer), '渲染层仍保留 excluded 特殊样式分支')
})

test('全国层有南海诸岛小图，且经纬范围覆盖南海', () => {
  const source = mapSource()
  assert.ok(/INSET=\{x:/.test(source), '缺少南海诸岛小图（inset）定义')
  assert.ok(/insetShapes/.test(source), '缺少小图要素计算')
  assert.ok(/level==='nation'/.test(source), '小图应在全国层显示')
  const inset = source.match(/INSET=\{x:\s*[\d.]+,\s*y:\s*[\d.]+,\s*w:\s*[\d.]+,\s*h:\s*[\d.]+,\s*lon0:\s*([\d.]+),\s*lon1:\s*([\d.]+),\s*lat0:\s*([\d.]+),\s*lat1:\s*([\d.]+)\}/)
  assert.ok(inset, 'INSET 常量格式变了，护栏需要同步更新')
  const [, lon0, lon1, lat0, lat1] = inset.map(Number)
  assert.ok(lon0 <= 110 && lon1 >= 121, `小图经度 ${lon0}–${lon1} 没盖住南海主区`)
  assert.ok(lat0 <= 5 && lat1 >= 22, `小图纬度 ${lat0}–${lat1} 没盖住南海主区`)
})
