// Opt-in render check for the offline-basemap UI in CityTrafficMap.vue.
//
// Why a render check and not just a unit test: the channel logic in runtime.js can
// be perfect while the .vue template still shows nothing. `vite build` does not
// catch that -- it bundles, it does not evaluate the template -- and this panel's
// offline branch is behind a live map, so reaching it by hand would mean physically
// disconnecting the machine.
//
// The component accepts `initialBasemapChannel` for exactly this reason. An earlier
// draft rendered three times without setting it and asserted against three identical
// HTML strings -- a vacuous PASS that the differential assertions below are designed
// to catch. If the prop stops being honoured, the three renders collapse to one and
// this check fails instead of passing on a technicality.
//
// What this CANNOT prove: canvas/WebGL rendering, layer z-order, or the CSS
// `.city-map-shell:has(...)` rule that keeps the notice strip from overlapping the
// radar badge -- SSR runs no layout. Those need a real browser.
//
// Run: node tests/render-offline-basemap.mjs
import { createServer } from 'vite'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { writeFile } from 'node:fs/promises'

const server = await createServer({
  server: { middlewareMode: true },
  appType: 'custom',
  logLevel: 'error',
})
const mod = await server.ssrLoadModule('/src/components/CityTrafficMap.vue')
await server.close()
const MapView = mod.default

const out = []
let failed = false
const fail = (message) => { out.push('FAIL: ' + message); failed = true }
const check = (condition, message) => { if (!condition) fail(message); return condition }

const base = { network: { cities: [], administrativeBoundaries: null }, flights: [], minute: 0, city: '' }

async function render(channel) {
  const app = createSSRApp(MapView, { ...base, initialBasemapChannel: channel })
  const warnings = []
  app.config.warnHandler = (message) => warnings.push(message)
  return { html: await renderToString(app), warnings }
}

const channels = ['online', 'pending', 'offline']
const rendered = {}
for (const channel of channels) {
  const { html, warnings } = await render(channel)
  rendered[channel] = html
  // A prop-type violation would silently fall back to the default and make the
  // offline case indistinguishable from pending; surface it rather than guess.
  if (warnings.length) fail(`initialBasemapChannel=${channel} 触发 Vue 警告: ${warnings[0]}`)
  out.push(`[${channel}] ${html.length} chars`)
}

out.push('')
const badge = /class="[^"]*\bbadge\b[^"]*"/
// 离线态的第二标识**不是**"说明带"，而是「重试在线底图」按钮。
// 这里原来断言 `city-map-offline-note` —— 那个类名全仓只有本文件里出现过，
// CityTrafficMap.vue 从未实现过它。测试是照着设计意图写的、从没对着实现跑过，
// 加上它一直没被 `npm test` 收集，于是"写错的断言"活了半个多月没人发现。
const retry = /重试在线底图/
for (const channel of ['online', 'pending']) {
  check(!badge.test(rendered[channel]), `${channel} 渲染出了离线徽标`)
  check(!retry.test(rendered[channel]), `${channel} 渲染出了重试按钮`)
}
check(badge.test(rendered.offline), 'offline 未渲染离线徽标')
check(retry.test(rendered.offline), 'offline 未渲染「重试在线底图」按钮')
out.push(`badge   online=${badge.test(rendered.online)} pending=${badge.test(rendered.pending)} offline=${badge.test(rendered.offline)}`)
out.push(`retry   online=${retry.test(rendered.online)} pending=${retry.test(rendered.pending)} offline=${retry.test(rendered.offline)}`)

const distinct = new Set(channels.map((c) => rendered[c])).size
check(distinct === 3, `三态渲染只有 ${distinct} 种结果，initialBasemapChannel 没被采纳`)
out.push(`三态渲染互异: ${distinct === 3}`)

check(!/离线底图/.test(rendered.pending), 'pending 渲染出了"离线底图"字样')
check(!/已载入/.test(rendered.pending), 'pending 声称已载入')
out.push(`pending 文本干净: ${!/离线底图|已载入/.test(rendered.pending)}`)

// The status line itself must disagree between online and offline -- the badge is an
// extra marker, not the only difference, so a stale mapStatus would still be caught.
//
// Match on the class *list* rather than on a fixed prefix: Vue emits the dynamic
// bindings first, so the offline case serialises as
// `class="city-map-info-status offline"`. The class is `city-map-info-status`
// (not `city-map-status` — that name never existed in the template, so this
// extractor returned null for all three channels and every assertion below it
// was reporting on nothing).
function statusText(html) {
  const match = html.match(/<div class="([^"]*\bcity-map-info-status\b[^"]*)"[^>]*>([\s\S]*?)<\/div>/)
  if (!match) return null
  return match[2].replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim()
}
const onlineStatus = statusText(rendered.online)
const pendingStatus = statusText(rendered.pending)
const offlineStatus = statusText(rendered.offline)
out.push(`status  online="${onlineStatus}"`)
out.push(`status pending="${pendingStatus}"`)
out.push(`status offline="${offlineStatus}"`)
if (offlineStatus === null || onlineStatus === null || pendingStatus === null) {
  // A null means the extractor did not find the node, which makes every assertion
  // below meaningless. Print the head so the failure is diagnosable.
  for (const channel of channels) {
    if (statusText(rendered[channel]) === null) {
      out.push(`  ${channel} html head: ` + JSON.stringify(rendered[channel].slice(0, 220)))
    }
  }
}
check(Boolean(onlineStatus) && Boolean(offlineStatus) && Boolean(pendingStatus), '某个通道的状态条文案为空')
check(offlineStatus !== onlineStatus, '在线与离线的状态条文案相同')
check(/离线底图/.test(offlineStatus), '离线状态条未说明是离线底图')
check(!/离线/.test(pendingStatus), 'pending 状态条出现了"离线"')
check(offlineStatus !== pendingStatus, '离线与 pending 的状态条文案相同')

out.push('')
out.push(failed ? 'RESULT: FAIL' : 'RESULT: PASS')
const text = out.join('\n')
console.log(text)
await writeFile('../.run/_render_offline.txt', text + '\n')

// 必须显式给退出码：这是"脚本式"用例，没有 test() 调用，node --test 只看进程
// 退出码。以前它既没退出码、名字又不匹配收集规则 —— 两条都缺，所以它从加进仓库
// 那天起就既没跑过、也不可能失败（"绿"的是没跑，不是通过）。
process.exit(failed ? 1 : 0)
if (failed) process.exitCode = 1
