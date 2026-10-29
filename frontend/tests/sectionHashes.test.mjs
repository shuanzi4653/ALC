import test from 'node:test'
import assert from 'node:assert/strict'
import {
  SECTION_NAMES, SECTION_HASHES, HIDDEN_SECTIONS, sectionHash, sectionFromHash,
} from '../src/traffic/runtime.js'

// 0.11.18（F-1）。这一组钉的是**地址能不能回到页面**，而不是"hash 长什么样"。
//
// 复测报告 N-1 的实测：13 个页面只产出 9 个不同 hash；直接打开 `#/corridor/profile`、
// 刷新、手动改 hash 三种进入方式全部停在运行首页。根因不是读入口（那个 0.11.17 已经
// 改成读 `location.hash` 了），而是**映射表的键名与 section 名对不上**：
//
//   SECTION_HASHES 里写的是 intel / model / caliber / divergence
//   而真实 section 名是        briefing / card / reference / ledger
//
// `sectionHash()` 是 `SECTION_HASHES[section] || SECTION_HASHES.home` ——
// 查不到就**静默回落到首页**。所以那四页点进去，地址栏写的是 `#/situation/home`，
// 而 `sectionFromHash('#/corridor/intel')` 会返回 `'intel'` 这个不存在的 section。
//
// 判据写成"双向闭合"：每个可导航 section 都能映射出唯一 hash，且每个 hash 都能
// 读回同一个 section。只查一个方向的话，"键对了但 path 撞车"仍然会过。

/** 可导航的 section：`SECTION_NAMES` 去掉隐藏页。 */
const NAVIGABLE = Object.keys(SECTION_NAMES).filter(key => !HIDDEN_SECTIONS.has(key))

test('可导航页恰好 11 个，且每个都有 hash（少一个就静默变首页）', () => {
  // 0.11.22：13 → 11，因为复盘对照与分歧台账并入推演（进 HIDDEN_SECTIONS）。
  // 判据本身没变：每一个**可导航**页都必须有 hash，否则深链静默回首页。
  assert.equal(NAVIGABLE.length, 11, `可导航页数量变了：${NAVIGABLE.join(' / ')}`)
  for (const key of NAVIGABLE) {
    assert.ok(
      SECTION_HASHES[key],
      `${key} 不在 SECTION_HASHES 里 —— sectionHash('${key}') 会静默回落到首页`,
    )
  }
})

test('11 个 hash 互不相同（同 hash 的两个页面无法各自深链接）', () => {
  const hashes = NAVIGABLE.map(key => SECTION_HASHES[key])
  assert.equal(new Set(hashes).size, hashes.length,
    `有重复 hash：${hashes.filter((h, i) => hashes.indexOf(h) !== i).join(' / ')}`)
})

test('每个 hash 都能读回同一个 section（写生效、读也要生效）', () => {
  for (const key of NAVIGABLE) {
    const hash = sectionHash(key)
    assert.equal(sectionFromHash(hash), key, `${hash} 读回来不是 ${key}`)
  }
})

test('映射表里不许有 section 名以外的键（拼错的键就是死键）', () => {
  for (const key of Object.keys(SECTION_HASHES)) {
    assert.ok(
      SECTION_NAMES[key],
      `SECTION_HASHES 里有 '${key}'，但 SECTION_NAMES 没有这个 section —— `
      + '它永远映射不到任何页面，而对应页面会回落到首页',
    )
  }
})

test('未知 hash 一律回落 home（不抛异常、不留空白页）', () => {
  for (const bad of ['#/nope', '#/review/compare', '#/weather/monitor', '#', '#/', '']) {
    assert.equal(sectionFromHash(bad), 'home', `${bad} 没有回落到 home`)
  }
})
