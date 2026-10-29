// 0.11.23 · D-1：「处置台 → 查看航班」报错的回归网。
//
// 现场：点「查看航班」之后抛 `Cannot read properties of undefined (reading 'length')`，
// 紧接着地图报 `container must be a String or HTMLElement`，屏幕上就是"地图显示错误"。
//
// 根因不是地图：0.11.11 为减包把 `points` 从 `flights` 挪到了 `mapFlights`，
// 全量轨迹改成单班补取；而下游有五处写的是 `selected?.points.length` ——
// `?.` 只保护 `selected` 本身，不保护 `.points`。组件渲染抛错之后地图容器的
// ref 根本没挂上，MapLibre 拿到的就是 undefined。
//
// 这个文件钉两件事：① 取轨迹的函数永远给数组；② 源码里不许再有裸的 `.points.length`。
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import test from 'node:test'

import {trajectoryOf} from '../src/traffic/runtime.js'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')

/** 剥掉 HTML 注释与行注释：注释里写着"这里原来是 `selected?.points.length`"，
 *  扫全文会把**解释这个坑**当成"坑还在"。 */
function code(source) {
  return source
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<style[\s\S]*?<\/style>/g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/^\s*\*.*$/gm, '')
}

test('trajectoryOf：拿不到轨迹时给空数组，不是 undefined', () => {
  assert.deepEqual(trajectoryOf(undefined), [])
  assert.deepEqual(trajectoryOf(null), [])
  assert.deepEqual(trajectoryOf({}), [])
  assert.deepEqual(trajectoryOf({points: null}), [])
  // 形状不对也算"没有轨迹"：字符串有 length，会骗过调用方的 `.length` 判据
  assert.deepEqual(trajectoryOf({points: 'abc'}), [])
  const pts = [[126.5, 45.7, 0, 0], [126.6, 45.6, 100, 30]]
  assert.equal(trajectoryOf({points: pts}), pts, '有轨迹时必须原样返回同一个数组（不复制）')
})

test('D-1：源码里不许再有裸的 selected?.points.length', () => {
  for (const [name, file] of [
    ['TrafficWorkbench.vue', '../src/components/TrafficWorkbench.vue'],
    ['CityTrafficMap.vue', '../src/components/CityTrafficMap.vue'],
  ]) {
    const src = code(read(file))
    // `?.` 只保护它左边那一层，`selected?.points.length` 仍然会在 points 缺失时抛
    assert.ok(!/selected\?\.points\.length/.test(src),
      `${name} 又写了 selected?.points.length：points 缺失时抛 TypeError，整棵树渲染中断`)
    // 允许带短路判据的写法（那不是"裸的"）：`Array.isArray(p)&&p.length` 与
    // `!Array.isArray(p)||p.length` 两种短路的正确性都成立，其余一律不放过
    const guarded = src
      .replace(/Array\.isArray\(([\w.$?]+)\)\s*&&\s*\1\.length/g, 'GUARDED')
      .replace(/!Array\.isArray\(([\w.$?]+)\)\s*\|\|\s*\1\.length/g, 'GUARDED')
      .replace(/trajectoryOf\([^)]*\)\.length/g, 'GUARDED')
    assert.ok(!/[a-zA-Z_]\.points\.length/.test(guarded),
      `${name} 还有裸的 xxx.points.length：改用 trajectoryOf(...)`)
  }
})

test('D-1：选中班次时，轨迹要能从地图行兜底', () => {
  const workbench = read('../src/components/TrafficWorkbench.vue')
  // 兜底链：全量轨迹 → 地图行（6 点）→ 空数组。少了中间这层，"刚点选"那一帧没有轨迹，
  // 地图上会闪一下"没有航线"；少了最后一层，就是这次的事故。
  assert.match(workbench, /const merged=extra\?\{\.\.\.row,\.\.\.extra\}:row/,
    'selected 的合并逻辑变了，兜底要重新核对')
  assert.match(workbench, /mapFlights\|\|\[\]\)\.find\(r=>r\.id===row\.id\)/,
    '没有从 mapFlights 取六点轨迹 —— 补取回来之前地图是空的')
  assert.match(workbench, /return \{\.\.\.merged,points:\[\]\}/,
    '没有兜底空数组：调用方判 .length 会抛')
})
