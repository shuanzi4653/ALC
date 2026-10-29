// 静态契约检查：CityTrafficMap.vue 的图层必须真的被创建、且禁飞区画在雷达之上。
//
// 为什么需要这条检查（0.9.14 实测教训）：
//   一次改动后，`vite build` 通过、单元测试全绿，但地图上既看不到雷达回波也看不到
//   禁飞区。原因是 SSR 渲染不跑 WebGL，`map.addLayer()` 从不在测试里执行；而 .vue 的
//   模板/脚本里的图层名写错、顺序写反、参数被覆盖，构建都不会失败。
//   于是"图层存在"这件事必须**从源码静态地**断言，这是唯一能在无浏览器环境里抓到的
//   层面。
//
// 这条检查断言三件事，每一条都对应一个真实发生过的缺陷：
//   1. 每个语义图层都有对应的 `map.addLayer({id:'...'})`（缺了就是"数据有、图没有"）；
//   2. 每个图层引用的 source 都在 `sourceLayers()` 里被 `addSource` 过
//      （缺了 MapLibre 会静默不画，报错只在控制台）；
//   3. 禁飞区描边图层在 radar 图层**之后**添加 —— 用户报告"气象与雷达不要合并，
//      不然我看不到禁飞区了"；顺序写反就会让回波盖住法定边界。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const source = await readFile(join(here, '..', 'src', 'components', 'CityTrafficMap.vue'), 'utf8')

/** 所有 addLayer 的 id，按**出现顺序**返回 —— 顺序本身就是被测对象。 */
function layerIdsInOrder(text) {
  const ids = []
  for (const match of text.matchAll(/map\.addLayer\(\{id:'([^']+)'/g)) ids.push(match[1])
  return ids
}

/** 所有 addSource 的 source 名。
 *
 * 两种写法都要认：字面量 `map.addSource('x',{...})`，以及批量注册
 * `for(const id of ['a','b',...])map.addSource(id,{...})`。
 * 只认第一种会让这条检查**误报**成"图层引用了未注册的 source"——本检查写好时正是
 * 这样：`operation-mask` 其实是注册过的，只是写在 for 循环的数组里。检查一个"存在性"
 * 问题却用只能匹配一种写法的正则，会把它本该放行的用例判成失败。
 */
function sourceIds(text) {
  const ids = new Set()
  for (const match of text.matchAll(/map\.addSource\('([^']+)'/g)) ids.add(match[1])
  for (const match of text.matchAll(/for\s*\(\s*const\s+\w+\s+of\s*\[([^\]]+)\]\s*\)\s*map\.addSource\(/g)) {
    for (const name of match[1].matchAll(/'([^']+)'/g)) ids.add(name[1])
  }
  return ids
}

/** 每个图层的 source 引用。 */
function layerSources(text) {
  const pairs = []
  for (const match of text.matchAll(/map\.addLayer\(\{id:'([^']+)'[^}]*?source:'([^']+)'/g)) {
    pairs.push({ layer: match[1], source: match[2] })
  }
  return pairs
}

const layers = layerIdsInOrder(source)
const sources = sourceIds(source)

test('雷达回波的每个语义图层都已创建', () => {
  // 危险回波（READY）与层状降水（QUIET）两态都必须有可画的图层。0.9.14 之前 QUIET
  // 只有一条 1.4px 虚线，实测覆盖操作框 0.57%，用户报告"完全看不到回波"。
  for (const id of ['radar-halo', 'radar-footprint', 'radar-outline',
                    'radar-watch-fill', 'radar-watch-outline']) {
    assert.ok(layers.includes(id), `缺少雷达图层 ${id}`)
  }
})

test('禁飞区（固定管制区）的填充与描边都已创建', () => {
  for (const id of ['fixed-zone-footprint', 'fixed-zone-outline', 'fixed-zone-halo',
                    'fixed-zone-refs', 'fixed-zone-labels']) {
    assert.ok(layers.includes(id), `缺少固定管制区图层 ${id}`)
  }
})

test('每个图层的 source 都在 sourceLayers() 里注册过', () => {
  // MapLibre 对未注册的 source 是**静默**失败的：不画、不抛、构建也过。所以这条
  // 检查必须存在，否则"图层写了但引用了不存在的 source"永远测不出来。
  for (const { layer, source: src } of layerSources(source)) {
    assert.ok(sources.has(src), `图层 ${layer} 引用了未注册的 source ${src}`)
  }
})

test('禁飞区描边画在雷达回波之后，回波不会盖住法定边界', () => {
  const firstRadar = layers.findIndex(id => id.startsWith('radar-'))
  const fixedOutline = layers.indexOf('fixed-zone-outline')
  assert.ok(firstRadar >= 0, '没有找到任何 radar- 图层')
  assert.ok(fixedOutline >= 0, '没有找到 fixed-zone-outline 图层')
  // 数组下标越大越晚添加 = 画得越靠上。
  assert.ok(fixedOutline > layers.lastIndexOf('radar-outline'),
    'fixed-zone-outline 必须在所有 radar 图层之后添加，否则回波会盖住禁飞区边界')
})

test('层状降水（QUIET）有填充而不是纯描边，否则"有雨但无危险"读起来像"没有雷达"', () => {
  // 这是 0.9.14 那次报告的直接修法：给 watch 一层淡填充。断言 fill 图层存在，
  // 且它的 opacity 明显低于危险回波 —— 不能因为"要看得见"就把可飞越的雨画成禁区。
  //
  // 数值从常量块读，而不是要求图层里写死字面量：图层的 paint 引用
  // `RADAR_COLORS.watchFillOpacity`，把常量与引用分开断言，才不会因为"改成了常量"
  // 就把一个正确的实现判成失败。
  assert.ok(layers.includes('radar-watch-fill'), '层状降水没有填充图层')
  assert.match(source, /id:'radar-watch-fill'[\s\S]{0,220}?RADAR_COLORS\.watchFillOpacity/,
    'radar-watch-fill 没有引用 RADAR_COLORS.watchFillOpacity')

  const colors = source.match(/const RADAR_COLORS=\{([\s\S]*?)\n\}/)
  assert.ok(colors, '没有找到 RADAR_COLORS')
  const watchOpacity = Number(colors[1].match(/watchFillOpacity:([\d.]+)/)[1])
  const dangerOpacity = Number(colors[1].match(/fillOpacity:([\d.]+)/)[1])
  assert.ok(watchOpacity > 0.08, `层状降水填充 ${watchOpacity} 太淡，仍会看不见`)
  assert.ok(watchOpacity < dangerOpacity,
    `层状降水填充 ${watchOpacity} 不得达到危险回波 ${dangerOpacity} 的强度：可飞越的雨不是禁区`)
})

// ---------------------------------------------------------------------------
// 坐标空间契约。0.9.16 的根因：**数据一直在画，画在了看不见的地方**。
//
// 后端对气象载荷用了两套序列化约定：模型气象 cells 是 AEQD 投影米（要转换），
// 而雷达 regions/watch 与固定管制区经 `geojson()` 已是 EPSG:4326 经纬度（不能转换）。
// 前端 `geographicGeometry()` 无条件把输入当米，于是雷达那一路被二次投影 —— 一个
// 黑龙江尺度的多边形被坍缩成 (126.0016, 45.0005) 处约 2e-6 度的点（2026-09-23 实测）。
// 这解释了为什么 0.9.15 修完图层顺序、填充不透明度之后用户依然"看不到回波"。
//
// 这条检查只做静态断言，因为构建与单测都跑不到 WebGL：图层画在哪，只有源码能证明。
// ---------------------------------------------------------------------------
test('雷达回波几何直通，不得再被当作投影米二次投影', () => {
  const drawRadar = source.match(/function drawRadar\(\)\{([\s\S]*?)\n\}/)
  assert.ok(drawRadar, '没有找到 drawRadar 函数体')
  assert.match(drawRadar[1], /radarFeatureGeometry\(surface\)/,
    'drawRadar 必须经 radarFeatureGeometry 取雷达几何')
  // 断言"写法族"而不是某一种写法：只要 drawRadar 内还出现 geographicGeometry，
  // 无论是 (surface.geometry) 还是别的参数形式，都是同一类缺陷。
  assert.doesNotMatch(drawRadar[1], /geographicGeometry\(/,
    'drawRadar 内不得调用 geographicGeometry：雷达几何已是经纬度，再投影会坍缩成一个点')
})

test('层状降水（QUIET）也会画出来，闸门不得只放行 READY', () => {
  // 2026-09-24 实测第二个根因：载荷 regions=0、watch=206.9 km²，radarState 判 QUIET，
  // 而 drawRadar 的闸门写的是 `!==READY 就清空` —— 层状降水填充图层**永远拿不到数据**，
  // 徽标却写着「已标出范围」。东北秋季多数时候就是这种层状降水帧，所以"气象不显示"
  // 在大部分时间是这一个原因。闸门只能挡 DOWN（和过期帧）。
  const drawRadar = source.match(/function drawRadar\(\)\{([\s\S]*?)\n\}/)
  assert.ok(drawRadar, '没有找到 drawRadar 函数体')
  // 0.11.16（K-8）：闸门从「=== DOWN」改成 `radarUnavailable(radar)` —— 因为状态枚举里
  // 多了 PENDING，逐个比较 DOWN 会漏掉它（`radar.regions` 会是 null 而炸掉）。
  // 这条判据守的东西没变：**QUIET 必须能画**。它现在由两半共同保证：
  //   ① 这里 —— drawRadar 用的守卫必须是 `radarUnavailable`（其语义是"非 READY/QUIET"）；
  //   ② radarLayer.test.mjs —— `radarUnavailable(watchOnlyFrame) === false`（语义那一半）。
  // 只改这一处而不加 ②，会把判据变成"函数名对了就行"（M85：判据的射程 = 它认得的写法）。
  assert.match(drawRadar[1], /radarUnavailable\(radar\)/,
    'drawRadar 的清空条件必须是 radarUnavailable（非 READY/QUIET）：QUIET 同样要画')
  assert.doesNotMatch(drawRadar[1], /!==RADAR_STATE\.READY/,
    'drawRadar 不得用 !==READY 做闸门，否则层状降水永远画不出来')
  // 徽标与图层必须对得上：QUIET 徽标写着「已标出范围」，图层却一个几何都不画，
  // 等于界面在撒谎。这条把两半钉在一起。
  // 只断言"存在这句承诺"，不绑定它的具体分支写法（分支形态会随实现变化）。
  // 这条判据原来断言的是**注释里引用的旧文案**（"仅层状降水（可飞越，已标出范围）"）：
  // 0.11.5B 已把徽标改成「（15–35 dBZ，可飞越）」，而那段引用的注释还在，于是判据
  // 一直是绿的 —— 它守的其实是"注释里有这行字"。改成钉真文案。
  assert.match(source, /仅层状降水/, 'QUIET 徽标必须说明本帧只有层状降水')
  assert.doesNotMatch(source, /已标出范围/,
    '徽标不得承诺"已标出范围"：那是结果，不是本帧事实')
})

test('"没有回波"与"有雨但无害"不得共用一句徽标', () => {
  // 2026-09-24 实测：全国拼图 echoFraction 0.78%，但作业区内 components=0（回波全部
  // 落在边界外）。此时徽标仍写「仅层降水…已标出范围」—— 对一个盯着空地图的人说
  // "我给你标出来了"，是最糟的一句。徽标必须区分这两种 QUIET。
  assert.match(source, /本作业区当前无回波/,
    'QUIET 且无 watch 时必须另有文案，不能沿用「已标出范围」')
  // 且分支必须由"是否真的有可画几何"驱动，而不是写死。
  // 判据钉的是"分支由 drawn 驱动"，不是"`drawn?` 之间不许有换行"。
  // 0.11.5B（W-R3）把这一支的文案写长之后换行了，原正则 `\(drawn\?` 因此假红 ——
  // 格式不是契约，条件才是。
  assert.match(source, /RADAR_STATE\.QUIET\?\(drawn\s*\?/,
    'QUIET 徽标分支必须由实际可画的几何数量决定')
})

test('模型气象单元仍走投影米转换，上一条不得被"全都不转换"地修掉', () => {
  // 反向守卫：只禁止雷达那一路。cells 在投影米里，不转换同样画错（会落到几内亚湾）。
  assert.match(source, /geographicGeometry\(geometry\)/,
    '模型气象单元仍须经 geographicGeometry 从投影米转为经纬度')
})

test('固定管制区填充足够可见，但不与气象派生风险区的暖色混淆', () => {
  const block = source.match(/const FIXED_ZONE_COLORS=\{([\s\S]*?)\n\}/)
  assert.ok(block, '没有找到 FIXED_ZONE_COLORS')
  const footprint = Number(block[1].match(/footprint:([\d.]+)/)[1])
  const strict = Number(block[1].match(/footprintStrict:([\d.]+)/)[1])
  // 下限的来历改过一次，两次都有实测：
  //   · 0.9.14：0.11 的填充在 6.96% 面积上只贡献平均不透明度 0.011，用户看不到 → 抬到 0.24；
  //   · 0.11.12：逐层关图实测（`_probe_layer_weights.py`）发现 0.24 的**填充本身就是画面主体**
  //     —— 关掉固定管制区，地图区变 60 460 px，是航迹（27 558）的 2.2 倍、雾圈（3 106）的 19 倍。
  //     于是压到 0.18，并靠**描边（2.4 px）与晕圈（6 px/10%）**保住边界可读。
  // 所以这条判据守的是"还看得见轮廓"，不是"填充够浓"。
  // 两档分开守，因为它们的语义不同：
  //   · `PROHIBITED` 要"这块地不能用"的实心警告 → 必须够浓；
  //   · `APPROVAL_REQUIRED` 只需要知道边界在哪 → 靠描边，填充只是暗示。
  // 0.11.12 之前两档都浓，默认视图（几乎全是 APPROVAL_REQUIRED）成了一片色块
  // （逐层实测 60 460 px，是航迹的 2.2 倍）。所以普通档的下限只守"不是 0"。
  assert.ok(strict >= 0.2, `禁飞档填充 ${strict} 太淡，PROHIBITED 必须实心可辨`)
  assert.ok(footprint >= 0.04, `普通档填充 ${footprint} 已接近 0，边界将只剩描边一条线`)
  assert.ok(footprint < strict, `普通档 ${footprint} 不得与禁飞档 ${strict} 一样浓`)
  // 但仍须明显弱于气象派生风险区（0.26/0.46）——两类陈述不能画成一样。
  const riskBlock = source.match(/const RISK_COLORS=\{([\s\S]*?)\n\}/)
  assert.ok(riskBlock, '没有找到 RISK_COLORS')
  const riskFill = Number(riskBlock[1].match(/fillOpacity:([\d.]+)/)[1])
  assert.ok(footprint < riskFill,
    `固定管制区填充 ${footprint} 不得达到气象派生风险区 ${riskFill} 的强度`)
})

// ---------------------------------------------------------------------------
// 缩放门契约。用户报「每个城市都被黄色圈圈住了」，屏幕上每座城市周围糊着一圈琥珀。
//
// 那一轮（2026-10-15）只修了**事件节点**那一半：把 event-nodes / event-halo /
// event-node-labels 的 minzoom 从 5.5 提到 7.2，并留下一条长注释解释 5.5 为什么"改了
// 等于没改"（默认视图实测 z≈6.6，比门还高一级）。
//
// 但**设施点那一半没有动**：`pad-points` / `pad-labels` 当时既没有 minzoom 也没有
// maxzoom，于是 456 个起降节点 + 456 条标签在整个三省视图上铺开 —— 而 `city_pads()`
// 给每座城市生成的那一圈节点彼此只隔 1—2 km，在默认视图的 ≈1124 m/px 上是同一个像素。
// 屏幕上剩下的那半个症状就是它。2026-10-16 补齐，并把"**两半必须同时受门**"写成判据：
// 否则下一次只改一半时，没有任何东西会红（这正是它第一次能留下来的原因）。
// ---------------------------------------------------------------------------

/** 一个 `map.addLayer({...})` 调用的原文，切到下一条 addLayer 之前。 */
function layerBlock(layerId) {
  const at = source.indexOf(`id:'${layerId}'`)
  assert.ok(at >= 0, `找不到图层 ${layerId} 的声明`)
  const next = source.indexOf('map.addLayer(', at + 1)
  return source.slice(at, next < 0 ? source.length : next)
}

/** 默认（三省全域）视图的实测级数：ScaleControl 读数 100 km = 89 px ⇒ ≈1124 m/px
 *  ⇒ 156543·cos(45°)/2^z = 1124 ⇒ z ≈ 6.6。写在这里而不是让每条判据各猜一个下限。 */
const PROVINCE_VIEW_ZOOM = 6.6

test('默认三省视图不得被起降设施点与事件节点铺满（四类图层都要有真正的门）', () => {
  // 两类内容、各两个图层：点与它的标签必须同进同出 —— 只有点没有字的门，或反过来，
  // 都会留下一半症状（"只有环没有字"的节点读不出意思，反之亦然）。
  for (const id of ['pad-points', 'pad-labels', 'event-halo', 'event-nodes', 'event-node-labels']) {
    const match = layerBlock(id).match(/minzoom:([\d.]+)/)
    assert.ok(match, `${id} 没有 minzoom：设施点/事件节点会在默认视图上铺成"每座城市一圈琥珀"`)
    const zoom = Number(match[1])
    assert.ok(zoom > PROVINCE_VIEW_ZOOM,
      `${id} 的 minzoom ${zoom} 不高于默认视图 ${PROVINCE_VIEW_ZOOM}，在这块屏上等于没有门`)
  }
})

test('城市骨架点在任何缩放级别都必须可见（上一条不得被"全都加门"地修掉）', () => {
  // 反向判据，缺了它天平会朝"什么都藏起来"漂移：把 cities-points 也加上门，
  // 屏幕上确实再没有黄色圆点了，代价是全域视图连"网里有哪几座城市"都看不出来。
  for (const id of ['cities-points', 'cities-labels']) {
    assert.doesNotMatch(layerBlock(id), /minzoom:/,
      `${id} 不得加 minzoom：36 座城市是全网骨架，全域视图必须看得见`)
  }
})
