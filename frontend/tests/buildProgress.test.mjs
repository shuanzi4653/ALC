import test from 'node:test'
import assert from 'node:assert/strict'
import {buildProgressView} from '../src/traffic/runtime.js'

// 用户报的「进度条不动了」的判据。
//
// 屏幕现象：构建遮罩里的进度条跳回 0 并停住，旁边写着"正在计算运行计划"。
// 成因：后端在"同时在算的计划 ≥ 2 份"时返回 `{status:'BUSY', message:…}` ——
// **整份载荷没有 `progress` 字段** —— 而前端没有 `BUSY` 这一支，
// `Number(undefined)` → `NaN` → 兜底 0。
//
// 所以这里钉的不是"数字对不对"，而是**两件事必须渲染得不一样**：
//   「没有数字」（后端还没给）与「数字就是 0」（刚提交、确实 0%）。

test('BUSY：不许退成 0% —— 那是把"还没开始算"演成"已经开始了"', () => {
  // 后端的真实载荷形状（已实测复现）：只有 status 与 message 两个键。
  const view = buildProgressView({status: 'BUSY', message: '已有模拟计划正在计算，请稍后重试'})
  assert.equal(view.percent, null)
  assert.notEqual(view.percent, 0)
  // 后端已经写出了原因，前端不该另编一句更含糊的。
  assert.equal(view.stage, '已有模拟计划正在计算，请稍后重试')
  assert.equal(view.queued, '已有模拟计划正在计算，请稍后重试')
  assert.equal(view.status, 'BUSY')
})

test('反面对照：`progress: 0` 必须仍然是 0，不许一起变成 null', () => {
  // 这是双向的坑。把 0 也当成"没有数字"，会让"刚提交"看起来像"卡住了" ——
  // 只是换一个方向骗人。两个状态在载荷里长得像（都缺东西），处置必须相反。
  const view = buildProgressView({status: 'BUILDING', progress: 0, stage: '准备气象快照与空域目录'})
  assert.equal(view.percent, 0)
  assert.equal(view.queued, '')
  assert.equal(view.stage, '准备气象快照与空域目录')
})

test('`progress: null` 与 `progress: undefined` 都读成"没有数字"，不读成 0', () => {
  // `Number(null) === 0` 是同一个坑的后端/载荷形态（M16）：null 一旦被当成 0，
  // "没发布进度"就会被印成"完成了 0%"，而那是两个完全不同的下一步动作。
  for (const value of [null, undefined]) {
    assert.equal(buildProgressView({status: 'BUILDING', progress: value}).percent, null)
  }
  // 字符串形式也得挡住：载荷里出现过 `"10"` 这种形态时不能变成 NaN 再兜底 0。
  assert.equal(buildProgressView({status: 'BUILDING', progress: ''}).percent, null)
  assert.equal(buildProgressView({status: 'BUILDING', progress: 'NaN'}).percent, null)
})

test('正常构建：取整并夹到 0—100，阶段句原样透传', () => {
  assert.equal(buildProgressView({status: 'BUILDING', progress: 32.6, stage: '逐班次规划航路与间隔'}).percent, 33)
  assert.equal(buildProgressView({status: 'BUILDING', progress: 140}).percent, 100)
  assert.equal(buildProgressView({status: 'BUILDING', progress: -5}).percent, 0)
  assert.equal(buildProgressView({status: 'READY', progress: 100, stage: '逐班次规划航路与间隔'}).percent, 100)
})

test('没有 stage 时给兜底句，但兜底句不许在 BUSY 时抢镜', () => {
  // 这两种兜底句说的是"正在提交/正在计算"。它们**都含着"这件事正在为你算"**，
  // 所以在后端说 BUSY 时必须让位 —— 否则又把"排队"说成了"在算"。
  assert.equal(buildProgressView({status: 'BUILDING'}).stage, '正在计算运行计划')
  assert.equal(buildProgressView(null).stage, '正在提交调度请求')
  assert.equal(buildProgressView(null).percent, null)
  assert.equal(buildProgressView({status: 'BUSY', stage: '逐班次规划航路与间隔'}).stage,
    '已有模拟计划正在计算，当前请求正在排队')
})

test('怪输入不抛异常（构建遮罩是首屏路径上的东西）', () => {
  for (const bad of [undefined, null, 0, '', [], 'BUILDING', {status: 7, progress: {}, stage: 9}]) {
    const view = buildProgressView(bad)
    assert.equal(typeof view.stage, 'string')
    assert.ok(view.stage.length > 0)
    assert.ok(view.percent === null || typeof view.percent === 'number')
    assert.equal(typeof view.queued, 'string')
  }
})
