import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {lowVisibilityRegions,lowVisibilitySurfaces,lowVisibilityState,lowVisibilitySummaryText,
        lowVisibilityRuleBlock,LOW_VISIBILITY_STATE} from '../src/traffic/runtime.js'

// 低能见度（雾）图层的**消费侧**契约。
//
// 这条通道的地图存在理由是一个屏幕现象：用户报「有几个标黄的路径不知道原因关闭」。
// 成因是能见度 <1000 m 的站在站心生成了一个 6 km 禁止内核，而 `city_pads(city)[0]`
// 就是城区代表中心 —— 内核必然包住枢纽，该城每一班都被拒；而屏幕上那 6 km 圆盘被
// 并进同一片暖色，在三省全域视图上只有十几像素。所以这一层的判据全部围绕一件事：
// **它必须能被看见，而且必须说清它是哪一档、多少米。**

const FRAME = {
  available: true,
  cautionVisibilityM: 5000, banVisibilityM: 1000,
  cautionRadiusM: 12000, banRadiusM: 6000,
  hardTier: 'BAN', softTier: 'CAUTION', padExemptTier: 'CAUTION',
  thresholdSource: 'config/rules-v1.json::visibilityM',
  regions: [
    {id: 'FOG-2-09', cityId: '2-09', cityName: '延边州', tier: 'BAN', visibilityM: 600,
     ban: {type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
     caution: {type: 'Polygon', coordinates: [[[0, 0], [2, 0], [2, 2], [0, 0]]]},
     derivedFrom: {provider: 'OPEN_METEO', dataType: 'MODEL_ESTIMATE'}},
    {id: 'FOG-1-07', cityId: '1-07', cityName: '锦州', tier: 'CAUTION', visibilityM: 2640,
     ban: null,
     caution: {type: 'Polygon', coordinates: [[[3, 3], [4, 3], [4, 4], [3, 3]]]},
     derivedFrom: {provider: 'OPEN_METEO', dataType: 'MODEL_ESTIMATE'}},
  ],
}

test('不可用时不给任何几何 —— 过期或凭空造出来的雾区绝不许留在图上', () => {
  for (const block of [undefined, null, {}, {available: false, regions: [FRAME.regions[0]]}]) {
    assert.deepEqual(lowVisibilitySurfaces({lowVisibility: block}), [])
    assert.equal(lowVisibilityState({lowVisibility: block}), LOW_VISIBILITY_STATE.DOWN)
  }
})

test('「读到了、没有站低于阈值」与「没读到」必须是两个状态', () => {
  // 两者在一张空地图上长得一模一样，而下一步动作相反：一个继续放行，一个去查数据源。
  const quiet = lowVisibilityState({lowVisibility: {...FRAME, regions: []}})
  const down = lowVisibilityState({lowVisibility: {available: false, regions: []}})
  assert.equal(quiet, LOW_VISIBILITY_STATE.QUIET)
  assert.equal(down, LOW_VISIBILITY_STATE.DOWN)
  assert.notEqual(quiet, down)
  assert.match(lowVisibilitySummaryText({lowVisibility: {...FRAME, regions: []}}), /没有站点低于/)
  assert.match(lowVisibilitySummaryText({lowVisibility: {available: false, regions: [], error: '抓取失败'}}), /抓不到|不可用/)
})

test('两档都摊平出来，且 BAN 排在 CAUTION 之前（深灰不许被自己的外环盖住）', () => {
  const surfaces = lowVisibilitySurfaces({lowVisibility: FRAME})
  assert.equal(surfaces.length, 3)
  assert.equal(surfaces[0].tier, 'BAN')
  assert.equal(surfaces[0].cityId, '2-09')
  assert.equal(surfaces[0].visibilityM, 600)
  assert.deepEqual(surfaces.slice(1).map(s => s.tier), ['CAUTION', 'CAUTION'])
})

test('缺读数的城不生成几何 —— 不许把"没发布"读成"能见度 0 m"', () => {
  // `Number(null) === 0` 是同一个坑的前端形态：0 m 是最严重的禁飞，
  // 一次缺测就会被读成一次全网最坏天气。
  const block = {...FRAME, regions: [
    {...FRAME.regions[0], visibilityM: null},
    {...FRAME.regions[1], visibilityM: undefined},
  ]}
  assert.deepEqual(lowVisibilitySurfaces({lowVisibility: block}), [])
  assert.deepEqual(lowVisibilityRegions({lowVisibility: block}), [])
})

test('规则数字读自载荷，不在前端另写一份', () => {
  const block = lowVisibilityRuleBlock({lowVisibilityAvoidance: {
    included: true, cities: 4, padExemptFlights: 680,
    cautionVisibilityM: 4321, banVisibilityM: 987,
    cautionRadiusM: 12000, banRadiusM: 6000,
    hardTier: 'BAN', softTier: 'CAUTION', padExemptTier: 'CAUTION',
    thresholdSource: 'config/rules-v1.json::visibilityM'}})
  assert.equal(block.cautionVisibilityM, 4321)
  assert.equal(block.banVisibilityM, 987)
  assert.equal(block.padExemptFlights, 680)
  // 摘要里出现的必须是载荷给的那个数，不是这里写死的 5000/1000。
  const text = lowVisibilitySummaryText({lowVisibility: {...FRAME, cautionVisibilityM: 4321}})
  assert.match(text, /4321/)
  assert.doesNotMatch(text, /5000/)
})

test('没有发布规则数字时返回 null，而不是一组看起来像规则的默认值', () => {
  // 一个看起来像规则的默认值会让人以为已经核对过 —— `radarRuleBlock` 为此付过代价：
  // 它曾经读一个在任何分支上都不存在的键，于是恒返回 null，而调用方的弃权分支长期印着假话。
  assert.equal(lowVisibilityRuleBlock({}), null)
  assert.equal(lowVisibilityRuleBlock({radarAvoidance: FRAME}), null)
  assert.equal(lowVisibilityRuleBlock(null), null)
})

test('出处来自载荷，载荷没给就是 null —— 前端不许自己写一个来源名', () => {
  // 来源是后端拥有的事实。前端写一份常量就等于同一件事有两份副本：后端换成和风、
  // 或降级成 degraded 时，界面上会继续印着旧的来源名，而两份副本各自被钉过，
  // 谁也不会报警（M79）。缺值时给 null 而不是默认值 —— 一个看起来像出处的默认值
  // 会让"没读到出处"和"出处就是它"长得一样。
  const surfaces = lowVisibilitySurfaces({lowVisibility: FRAME})
  assert.equal(surfaces[0].derivedFrom.provider, 'OPEN_METEO')
  assert.equal(surfaces[0].derivedFrom.dataType, 'MODEL_ESTIMATE')
  const bare = lowVisibilitySurfaces({lowVisibility: {...FRAME, regions: [
    {...FRAME.regions[0], derivedFrom: undefined}]}})
  assert.equal(bare.length, 2)
  assert.equal(bare[0].derivedFrom, null)
  // 换个来源，界面必须跟着变（常量写法在这里会当场露馅）。
  const swapped = lowVisibilitySurfaces({lowVisibility: {...FRAME, regions: [
    {...FRAME.regions[0], derivedFrom: {provider: 'QWEATHER', dataType: 'MODEL_ESTIMATE'}}]}})
  assert.equal(swapped[0].derivedFrom.provider, 'QWEATHER')
})

test('摘要必须说出"范围是近似值、不是实测雾区边界"', () => {
  // 一次站点读数只给一个点，给不了范围。圆是本系统画的，不说这句话，读者会把
  // 它当成一条实测边界 —— 而那正是本项目禁止"从一个点造边界"的那件事。
  const text = lowVisibilitySummaryText({lowVisibility: FRAME})
  assert.match(text, /近似/)
  assert.match(text, /不是实测雾区边界/)
  assert.match(text, /延边州/)
  assert.match(text, /600/)
})

// 绘制顺序是两条**屏幕主张**的承载者，而它们都不是测试能通过"看几何"发现的：
//
//   ① 深灰不许被自己的外环盖住 —— 一座城两档都有时，先画的会被后画的覆盖，
//      于是"低于禁飞阈值"这个更严重的信息会被"偏低"吃掉。⇒ BAN 必须后画。
//   ② 近似范围不许盖住实测回波 —— 灰是"站点读数派生、非实测边界"，雷达是实测。
//      粗糙的盖住精确的，屏幕上就会把"猜的"读成"量的"（M25）。
//
// 判据落在**源码里的 addLayer 顺序**上。它是结构判据、不是像素判据：能抓住
// "顺序被调换"，抓不住"顺序对但图层不可见"（后者需要截图，见 §十二）。
test('图层顺序：深灰在浅灰之上，实测回波又在这两者之上', () => {
  const source = readFileSync(new URL('../src/components/CityTrafficMap.vue', import.meta.url), 'utf8')
  const order = [...source.matchAll(/map\.addLayer\(\{id:'([^']+)'/g)].map(m => m[1])
  const at = id => {
    const index = order.indexOf(id)
    assert.notEqual(index, -1, `图层 ${id} 不存在了（被删或被改名）`)
    return index
  }
  // ① 雾的两档：BAN 后画（在 CAUTION 之上）
  assert.ok(at('fog-ban-fill') > at('fog-caution-fill'), '深灰必须在浅灰之后添加')
  assert.ok(at('fog-ban-outline') > at('fog-caution-outline'), '深灰描边必须在浅灰描边之后添加')
  // ② 雾整体在暖色风险区之上（它是用来解释那一片的），在雷达回波之下（不许盖住实测）
  assert.ok(at('fog-caution-fill') > at('weather-risk-outline'), '雾区应在暖色风险区之上')
  assert.ok(at('radar-halo') > at('fog-ban-outline'), '实测回波必须在雾区之上')
})
