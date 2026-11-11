import {ref} from 'vue'

// 深浅色（2026-11-11）。
//
// 原来全站只有深色一套，而且颜色是散在各组件里的字面量。这里不搞"再写一套组件"，
// 只做两件事：
//   ① 一个 `data-theme` 开关 + 一组设计令牌（style.css 的 --alc-* 与 --map-*）；
//   ② 一份 `theme-light.css` 覆盖层，把深色字面量按"面 / 线 / 字"三类统一改掉。
//
// 为什么要单独存 localStorage 而不是跟系统：答辩现场投影仪普遍偏亮，
// 讲解人需要能一键切浅色，而不受这台机器系统设置影响。
const KEY = 'alc.theme'

export const theme = ref('dark')

function read() {
  try {
    return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark'
  } catch (_) {
    return 'dark'
  }
}

export function applyTheme(next) {
  theme.value = next === 'light' ? 'light' : 'dark'
  if (typeof document === 'undefined') return
  // data-theme 挂在 <html>：CSS 覆盖面最大，地图 SVG 里的 var() 也能取到
  document.documentElement.dataset.theme = theme.value
  // 告诉 maplibre 那套样式（颜色写在 JS 里，CSS 管不到）
  window.dispatchEvent(new CustomEvent('alc-theme', {detail: theme.value}))
  try {
    localStorage.setItem(KEY, theme.value)
  } catch (_) {}
}

export function toggleTheme() {
  applyTheme(theme.value === 'light' ? 'dark' : 'light')
}

export function initTheme() {
  applyTheme(read())
}

/** 地图调色板：maplibre 的 paint 只能吃具体颜色，取不到 CSS 变量，所以在这里给两份。 */
export const MAP_PALETTE = {
  dark: {
    background: '#04101a',
    land: '#0b1d2a',
    landOpacity: 0.88,
    provinceLine: 'rgba(126,176,214,.62)',
    boundaryLine: 'rgba(200,232,255,.75)',
    node: '#eaf6ff',
    nodeDim: 'rgba(214,236,255,.62)',
    nodeStroke: 'rgba(8,20,32,.85)',
    capitalRing: 'rgba(186,218,255,.42)',
    corridor: 'rgba(126,206,255,.66)',
    corridorBlocked: 'rgba(226,92,74,.75)',
    detour: 'rgba(255,206,90,.95)',
    towerFace: 'rgba(150,210,245,.85)',
    label: '#cbdfef',
  },
  light: {
    background: '#e8eff7',
    land: '#ffffff',
    landOpacity: 0.92,
    provinceLine: 'rgba(84,124,166,.62)',
    boundaryLine: 'rgba(40,90,130,.8)',
    node: '#16384f',
    nodeDim: 'rgba(38,76,104,.6)',
    nodeStroke: 'rgba(255,255,255,.9)',
    capitalRing: 'rgba(60,110,150,.5)',
    corridor: 'rgba(30,110,170,.6)',
    corridorBlocked: 'rgba(200,60,40,.75)',
    detour: 'rgba(196,132,10,.95)',
    towerFace: 'rgba(120,160,195,.7)',
    label: '#1f3f57',
  },
}

export function mapPalette() {
  return MAP_PALETTE[theme.value] || MAP_PALETTE.dark
}
