import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'

// 地图上的"飞行汽车"三条硬要求（用户 2026-11-11 提出）：
//   ① 省名不显示；② 会动、会消失；③ 点它给出航线与起终点。
// 这些是渲染行为，单测只能盯结构，真正的验证在 .run/check102.mjs。
const read = (p) => readFileSync(new URL(`../src/${p}`, import.meta.url), 'utf8')

const map = read('components/traffic/NationMap.vue')
const panel = read('components/traffic/NationPanel.vue')

// V1.0.5：三维组件已删除。这条断言不是"少测一个文件"，
// 而是把"这一层不再有三维"钉死 —— 材料里已经按"不用三维"写了。
test('三维视图已下线（组件不存在）', () => {
  assert.throws(() => read('components/traffic/NationGlobe.vue'), /ENOENT|no such file/i,
    'NationGlobe.vue 应已删除；要加回来必须先改材料口径')
})

test('地图不再渲染省名（这是用户点名要去掉的东西）', () => {
  assert.ok(!/provinceLabels/.test(map), '省名计算还在')
  assert.ok(!/class="prov"/.test(map), '省名 text 还在')
  assert.ok(!/\.nmap \.prov\{/.test(map), '省名样式还在')
  // 城市名仍保留：它是下钻层的阅读骨架，只在全国层不显示
  assert.ok(/\.nmap \.city\{/.test(map), '城市名被误删了')
})

test('飞行汽车按本地连续时刻外推，而不是整分钟跳一格', () => {
  assert.ok(/frameMinute:\{type:Number/.test(map), '缺 frameMinute prop')
  assert.ok(/const advanceMin=computed/.test(map), '缺 advanceMin')
  // V1.0.4：推进量的基准从"请求的分钟"改成"数据自己的分钟"（dataMinute）。
  // 拿请求分钟当基准时，分钟一翻、新快照还在路上，adv 就归零 → 飞机倒退一分钟再弹回。
  assert.ok(/dataMinute:\{type:Number/.test(map), '缺 dataMinute prop')
  assert.ok(/props\.dataMinute/.test(map), '推进量没有以数据自身的分钟为基准')
  // 位置沿**这条走廊自己的折线**取点（按顶点均分，与后端同一条规则），
  // 不再用"航向 + 速度"直线外推：那是飞机漂出走廊、再被快照拉回来的根因。
  assert.ok(/function pointAt/.test(map), '缺参数化取点 pointAt')
  assert.ok(/pointAt\(path,p\)/.test(map), '位置没有沿走廊折线取点')
  assert.ok(/function headingAt/.test(map), '机头角度没有取自折线当前段')
  // 进站淡出、离站淡入
  assert.ok(/p>=\.985/.test(map), '缺进站淡出')
  assert.ok(/f\.fade/.test(map), 'fade 没接到模板')
})

test('面板有一个常驻 rAF 时钟，播放才推进、暂停对齐', () => {
  assert.ok(/requestAnimationFrame/.test(panel), '缺 rAF')
  assert.ok(/function startClock/.test(panel), '缺 startClock')
  assert.ok(/if\(clockRaf\) cancelAnimationFrame/.test(panel), '卸载时没有取消 rAF')
  // 暂停时必须把连续时刻拉回整数，否则下一帧会跳
  assert.ok(/Math\.abs\(frameMinute\.value-minute\.value\)/.test(panel), '暂停后没有对齐')
})

test('点选班次要画出航线与起终点', () => {
  assert.ok(/const pickedLine=computed/.test(map), '缺 pickedLine')
  assert.ok(/const pickedMarks=computed/.test(map), '缺 pickedMarks')
  // 已飞实线 / 未飞虚线：用 pathLength 归一化后拿 dasharray 截断
  assert.ok(/pathLength="100"/.test(map), '航线没有 pathLength 归一化')
  assert.ok(/pick-done/.test(map) && /pick-rest/.test(map), '缺已飞/未飞两层')
  // 起终点同名（州内接驳）时只标一个点，否则两个一样的名字会叠在一起
  assert.ok(/f\.fromName===f\.toName/.test(map), '没有处理起终点同名')
})

test('点选即聚焦，且画布尺寸变化后要重算', () => {
  assert.ok(/function focusPts/.test(map), '缺 focusPts')
  assert.ok(/focusPts\(pickedLine\.value\.pts\)/.test(map), '选中后没有聚焦')
  // 详情卡一张开会把画布压矮；不重算 pan 的话整幅图会飞出画布
  assert.ok(/const changed=VIEW\.w!==/.test(map), '画布尺寸变化没被感知')
})

test('放大时标记物保持屏幕尺寸（否则地名会比版图还大）', () => {
  assert.ok(/const inv=computed\(\(\)=>1\/zoom\.value\)/.test(map), '缺反向缩放因子')
  // V1.0.4：城市名走"胶囊底 + 无描边字"，字号来自 tagBox，仍按 inv 反向缩放
  assert.ok(/node\.tag\.fs\*inv/.test(map), '城市名字号没有反向缩放')
  assert.ok(/scale\(\$\{inv\}\)/.test(map), '起终点组没有反向缩放')
})

test('三维已下线：选中航线只在二维画一次', () => {
  // 原判据是"三维也要画选中航线，且全国层不画"。三维删掉后，
  // 它的意思是"不要再出现第二套绘制逻辑"——二维的 pickedLine 是唯一来源。
  const src = read('components/traffic/NationMap.vue')
  assert.match(src, /const pickedLine=computed/, '二维必须保留选中航线')
  assert.ok(!/picked-line/.test(src) || /nmap-pick-line/.test(src),
    '选中航线只应有一套图层命名')
})

