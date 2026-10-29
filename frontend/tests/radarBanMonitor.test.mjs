// 静态契约检查：右上角的越界监视必须**同时**数固定管制区与雷达内核。
//
// 为什么需要这条检查（用户 2026-10-01 第 3 条第 4 项）：
//   地图把雷达 ≥45 dBZ 内核画成红色、图例写「禁止进入」，而右上角写着
//   「本视图内 0 架位于禁入区」——两个结论同屏矛盾。监视条当时的判据只读
//   `flight.staticAirspace.crossings`（法定管制区），对气象派生的风险区一个字都没有。
//
//   这个缺陷**不会**被任何一层已有的检查抓到：`vite build` 通过、单元测试全绿
//   （`radarCoreIntrusionAt` 本身是对的，只是没人调用它）、运行时也不报错 ——
//   它只是一句话没说出口。而 .vue 的模板/脚本 `node --test` 够不着，所以"接线"
//   这件事只能在源码层静态断言。这与 mapLayerContracts 是同一条理由：
//   "图层存在"和"计数存在"都是无浏览器环境里抓不到的层面。
//
// 断言的每一条都对应一个具体失效方式：
//   1. 计数不接线 —— 地图红着、计数器还是 0（就是本次报的那个）；
//   2. 判据用了错的几何 —— 用经纬度的内核去比米制的航迹位置，永远不命中；
//   3. 只计数不染色 —— 操作员知道"有 3 架"，但看不出是哪 3 架；
//   4. 降级掉回旧文案 —— 监视条又变回只说固定管制区。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const source = await readFile(join(here, '..', 'src', 'components', 'CityTrafficMap.vue'), 'utf8')

test('监视条同时数固定管制区与雷达内核', () => {
  // 告警条的标题用合并总数，而不是只数 `intrusions`。
  assert.match(source, /v-if="intrusionTotal" class="city-map-intrusion"/,
    '告警条必须用固定管制区 + 雷达内核的合并总数')
  assert.match(source, /v-for="row in radarIntrusions\.slice\(0,4\)"/,
    '告警条必须列出雷达内核越界的班次')
  assert.match(source, /class="city-map-zone-monitor"/)
  // 空闲监视条的显示条件必须带上雷达内核，否则"没有固定管制区越界"会把雷达那一层
  // 一起藏起来 —— 用户看到的就是"雷达红着，右上角什么都没说"。
  assert.match(source, /v-else-if="showFixedZones\|\|radarBanList\.length"/,
    '监视条必须由固定管制区或雷达内核任一存在时显示')
})

test('雷达内核的判据接在渲染循环里，用的是本帧几何与同一分钟位置', () => {
  // 本帧内核，且已转换到与航迹相同的坐标空间。
  assert.match(source, /const radarBanList=computed\(\(\)=>radarBanSurfaces\(props\.weather\?\.radar,localGeometry\)\)/,
    '内核几何必须每帧转成米制（localGeometry），否则与航迹不同空间')
  assert.match(source, /const ban=state==='AIRBORNE'&&bans\.length\?radarCoreIntrusionAt\(p,bans\):null/,
    '判据必须用插值后的位置 p 与本帧内核 bans')
  // 发布必须走同一套"只在集合变化时写 ref"的纪律：这个函数在 WebGL 帧回调里跑。
  assert.match(source, /syncRadarIntrusions\(radarHits\)/, '内核越界必须被发布到监视条')
  assert.match(source, /function syncRadarIntrusions\(rows\)\{[\s\S]{0,400}?if\(key===radarIntrusionKey\)return/,
    'syncRadarIntrusions 必须先比较键再写 ref')
})

test('进入雷达内核的载具也要被染红', () => {
  // 只加计数不加染色，等于告诉操作员"红色区域里的飞机没问题"；只染色不加计数，
  // 就是本次报的缺陷。两件事必须由同一份判据同时决定。
  assert.match(source, /alert\.level===ZONE_INTRUSION\.PROHIBITED\|\|ban\?INTRUSION_TINT\.PROHIBITED:tint\.base/,
    '雷达内核越界必须与法定禁入区一样把载具染红')
})

test('旧的"只数固定管制区"的接线已经不存在', () => {
  // 负向验证：上面几条断言都可以在"保留了旧接线、又另外加了一条新接线"的情况下通过，
  // 而那种状态下监视条会有两个各自为政的数字。这一条钉住旧的那一个已经走掉。
  assert.ok(!/本视图内 \{\{intrusions\.length\}\} 架载具位于固定禁入区内/.test(source),
    '告警条不应再只数 intrusions')
  assert.ok(!/v-else-if="showFixedZones" class="city-map-zone-monitor"/.test(source),
    '监视条不应再只由 showFixedZones 决定')
  assert.ok(!/固定管制区越界监视：本视图内 0 架位于禁入区/.test(source),
    '监视条的文案必须说明比对范围包含哪几层')
})

test('雷达内核的措辞不冒充官方空域管制', () => {
  // 与 zoneIntrusionLabels 同一条纪律：气象派生风险区不是管制命令。地图上可以画红，
  // 但说到它时必须带来源前缀（"雷达……内核"），不能说成"禁飞区"。
  const monitor = source.match(/class="city-map-zone-monitor">[\s\S]*?<\/div>/)
  assert.ok(monitor, '未找到监视条模板')
  assert.match(monitor[0], /雷达禁止进入内核/, '监视条必须点名雷达内核这一层')
  assert.ok(!/禁飞区/.test(monitor[0]), '不得把气象派生风险区写成禁飞区')
  const emoji = /\p{Extended_Pictographic}/u
  for (const chunk of source.match(/▲[^<]{0,40}/g) || []) {
    assert.ok(!emoji.test(chunk), `不得使用 emoji：${chunk}`)
  }
})
