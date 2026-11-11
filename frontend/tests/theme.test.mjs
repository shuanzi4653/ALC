import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {MAP_PALETTE, theme, applyTheme} from '../src/theme.js'

// 深浅色（2026-11-11）。
//
// 这里钉的不是"好不好看"，而是**两套主题必须齐**：
// 少一个键，切到浅色时那块就退回 maplibre 默认色（通常是黑），
// 表现是"三维里一片黑"，而且没有报错。所以键集必须逐个对齐。
const read = p => readFileSync(new URL(p, import.meta.url), 'utf8')

test('两个调色板的键完全一致', () => {
  const dark = Object.keys(MAP_PALETTE.dark).sort()
  const light = Object.keys(MAP_PALETTE.light).sort()
  assert.deepEqual(light, dark, '少一个键，切主题时那一层会退回默认色')
  for (const key of dark) {
    for (const mode of ['dark', 'light']) {
      const value = MAP_PALETTE[mode][key]
      assert.ok(value !== undefined && value !== '', `${mode}.${key} 不能为空`)
    }
  }
})

test('深浅两套的底色必须真的不同', () => {
  assert.notEqual(MAP_PALETTE.dark.background, MAP_PALETTE.light.background)
  assert.notEqual(MAP_PALETTE.dark.land, MAP_PALETTE.light.land)
  assert.notEqual(MAP_PALETTE.dark.node, MAP_PALETTE.light.node)
})

test('无 DOM 时切换主题不抛错，且状态仍然可读', () => {
  const before = theme.value
  assert.doesNotThrow(() => applyTheme('light'))
  assert.equal(theme.value, 'light')
  applyTheme('dark')
  assert.equal(theme.value, 'dark')
  applyTheme(before)
})

test('非法值回落到深色，不会把界面切到"空白主题"', () => {
  applyTheme('blue')
  assert.equal(theme.value, 'dark')
})

test('main.js 在挂载前先落主题（否则会闪一帧深色）', () => {
  const main = read('../src/main.js')
  const initAt = main.indexOf('initTheme()')
  const mountAt = main.indexOf('createApp(App).mount')
  assert.ok(initAt > 0 && mountAt > initAt, 'initTheme 必须在 mount 之前调用')
})

test('覆盖层按 data-theme 生效，且地图变量有两个版本', () => {
  const css = read('../src/theme-light.css')
  assert.match(css, /html\[data-theme="light"\]/, '浅色覆盖必须挂在 data-theme 上')
  const base = read('../src/style.css')
  for (const key of ['--map-land', '--map-line', '--map-node', '--map-corridor', '--map-bg-1']) {
    assert.ok(base.includes(key), `style.css 缺少 ${key}`)
    assert.ok(css.includes(key), `theme-light.css 缺少 ${key} 的浅色值`)
  }
})

test('三维只改 paint、不重建样式（重建会丢相机）', () => {
  const globe = read('../src/components/traffic/NationGlobe.vue')
  assert.match(globe, /function applyPalette/, '必须有调色板应用函数')
  assert.match(globe, /setPaintProperty/, '主题切换应走 setPaintProperty')
  assert.match(globe, /addEventListener\('alc-theme'/, '要监听主题切换事件')
  assert.ok(!/alc-theme[\s\S]{0,200}setStyle\(/.test(globe), '不要在主题切换时 setStyle')
})
