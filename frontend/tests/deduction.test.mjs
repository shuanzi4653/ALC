// 推演页与双击航线的**源码契约**（0.11.22）。
//
// 为什么用源码断言而不是点地图：3D 场景里用坐标命中小飞机器物在 headless 里不稳定，
// 命中失败会得到"看起来没接线"的假结论。这里钉的是**接线本身**——
// 少了任何一段，这个功能就是静默失效（点了没反应、构建不报错、测试也不会红）。
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const MAP = read('../src/components/CityTrafficMap.vue')
const WORKBENCH = read('../src/components/TrafficWorkbench.vue')
const DEDUCE = read('../src/components/traffic/DeductionPanel.vue')
const CORRIDOR = read('../src/components/traffic/CorridorPanel.vue')
const CONSOLE = read('../src/components/OperationsConsole.vue')
const RUNTIME = read('../src/traffic/runtime.js')

test('双击航线：地图要发 open-corridor，并且带起降对', () => {
  assert.match(MAP, /map\.on\('dblclick'/, '地图没有 dblclick 监听 —— 双击不会触发任何事')
  assert.match(MAP, /emit\('open-corridor',\{from:/, 'open-corridor 没带 from/to，走廊页无从反查')
  // 单击语义不能被双击改掉：原本 select-flight 是"看一眼这架"，改成跳页会毁掉它
  assert.match(MAP, /emit\('select-flight'/, '单击选中航班被覆盖了')
})

test('open-corridor 两种入参都要处理（字符串=走廊 id，对象=起降对）', () => {
  const fn = WORKBENCH.match(/function onOpenCorridor\(payload\)\{[\s\S]*?\n\}/)
  assert.ok(fn, 'onOpenCorridor 签名变了（应接一个 payload 而不是 routeId）')
  assert.match(fn[0], /typeof payload==='string'/, '没有区分字符串 —— 对象会被当成走廊 id 用')
  assert.match(fn[0], /corridorPair\.value=/, '起降对没有落到 corridorPair')
  assert.match(fn[0], /activeSection\.value='profile'/, '没有切到走廊页')
})

test('走廊页接住起降对并选中该走廊', () => {
  assert.match(CORRIDOR, /focusPair:\{type:Object/, 'CorridorPanel 没有 focusPair prop')
  assert.match(CORRIDOR, /props\.focusPair/, 'focusPair 没有被 watch —— 传进来也不会选中')
  assert.match(CONSOLE, /:focus-pair="corridorPair"/, 'OperationsConsole 没把 corridorPair 传下去')
})

test('推演页七个模块都要在（少一个就是"算法链断了一节"）', () => {
  // 0.11.23（S-1）：标题改成"这一步在算什么"，而不是"这一块叫什么"——
  // 因为页面现在是**按步骤走**的，标题要能单独成句（"数据 → 插值 → 概率 → 判据"）。
  for (const [no, title] of [['1', '数据'], ['2', '插值'], ['3', '概率'],
    ['4', '判据'], ['5', '裁决'], ['6', '对照'], ['7', '七帧']]) {
    assert.ok(DEDUCE.includes(`data-step="${no}"`), `缺第 ${no} 步`)
    assert.ok(DEDUCE.includes(`>${title}<`), `第 ${no} 步的标题不是「${title}」`)
  }
  // 图不能是装饰：每步至少要有一条 SVG 或表格
  const svgs = (DEDUCE.match(/<svg/g) || []).length
  assert.ok(svgs >= 4, `图太少（${svgs} 张）—— 这一页的要求是"有图有真相"`)
  assert.ok(DEDUCE.includes('<table class="ded-table">'), '判据表没了')
})

test('S-1：推进是"一步一步"的，不是七块一次铺满', () => {
  // 步骤条必须存在，且能点回任意一步
  assert.match(DEDUCE, /data-ded-track/, '没有步骤条')
  assert.match(DEDUCE, /data-step-goto/, '步骤条上的步骤不可点回')
  // 每一步都要受 `show(n)` 控制；不写就等于"一次全展开"，退回旧形态且不会报错
  for (const no of ['1', '2', '3', '4', '5', '6', '7']) {
    const article = new RegExp(`<article class="ded-step" data-step="${no}"[^>]*v-show="show\\(${no}\\)"`)
    assert.match(DEDUCE, article, `第 ${no} 步没有受 v-show="show(${no})" 控制`)
  }
  // 走过的步骤要折成一行结论：没有摘要，折起来就成了一片空白
  for (const no of ['1', '2', '3', '4', '5', '6', '7']) {
    assert.ok(DEDUCE.includes(`summaries[${no}]`), `第 ${no} 步没有折叠摘要`)
  }
  // 「本步输入 / 本步输出」是这版的话术落点：每步都要写出来
  const io = (DEDUCE.match(/本步输入/g) || []).length
  assert.ok(io >= 6, `只有 ${io} 步写了「本步输入」——"把数据写出来"是这一轮的要求`)
  assert.match(DEDUCE, /data-step-next/, '没有「下一步」按钮')
})

test('S-1：换走廊 / 拖时间轴＝重新推演，必须回到第 1 步', () => {
  // 停在原来的第 5 步，读者会以为那是新走廊的裁决 —— 这是静默的错，不会报错
  assert.match(DEDUCE, /watch\(picked,restart\)/, '换走廊没有回到第 1 步')
  assert.match(DEDUCE, /watch\(\(\)=>props\.minute,restart\)/, '拖时间轴没有回到第 1 步')
})

test('推演页的数字一律来自接口，不在前端重算', () => {
  // 权重、期望损失、合成概率都必须是后端字段
  for (const field of ['deduction', 'midpointProbs', "decision.losses", 'stations']) {
    assert.ok(DEDUCE.includes(field), `没有读后端字段 ${field} —— 前端重算等于把算法复制第二份`)
  }
  assert.ok(!/Math\.pow\(/.test(DEDUCE), '前端出现了幂运算：疑似在重算 1/d² 权重')
})

test('导航：推演是第 4 组，日志是第 5 组，复盘对照不再出现', () => {
  assert.match(RUNTIME, /no: 4, label: '推演'/, '第 4 组没有改名推演')
  assert.match(RUNTIME, /no: 5, label: '日志'/, '第 5 组没有收成日志')
  assert.match(RUNTIME, /HIDDEN_SECTIONS[^\n]*counterfactual/, '复盘对照没有进隐藏集')
  assert.match(RUNTIME, /HIDDEN_SECTIONS[^\n]*ledger/, '分歧台账没有进隐藏集')
  assert.ok(!/label: '复盘'/.test(RUNTIME), '导航里还留着「复盘」分组')
})
