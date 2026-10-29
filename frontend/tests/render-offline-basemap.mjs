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
const notice = /city-map-offline-note/
for (const channel of ['online', 'pending']) {
  check(!badge.test(rendered[channel]), `${channel} 渲染出了离线徽标`)
  check(!notice.test(rendered[channel]), `${channel} 渲染出了离线说明带`)
}
check(badge.test(rendered.offline), 'offline 未渲染离线徽标')
check(notice.test(rendered.offline), 'offline 未渲染离线说明带')
out.push(`badge   online=${badge.test(rendered.online)} pending=${badge.test(rendered.pending)} offline=${badge.test(rendered.offline)}`)
out.push(`notice  online=${notice.test(rendered.online)} pending=${notice.test(rendered.pending)} offline=${notice.test(rendered.offline)}`)

const distinct = new Set(channels.map((c) => rendered[c])).size
check(distinct === 3, `三态渲染只有 ${distinct} 种结果，initialBasemapChannel 没被采纳`)
out.push(`三态渲染互异: ${distinct === 3}`)

for (const phrase of ['低精度', '自动切回']) {
  check(rendered.offline.includes(phrase), `离线说明缺少 "${phrase}"`)
}
out.push(`说明含 低精度/自动切回: ${rendered.offline.includes('低精度') && rendered.offline.includes('自动切回')}`)

check(!/离线底图/.test(rendered.pending), 'pending 渲染出了"离线底图"字样')
check(!/已载入/.test(rendered.pending), 'pending 声称已载入')
out.push(`pending 文本干净: ${!/离线底图|已载入/.test(rendered.pending)}`)

// The status line itself must disagree between online and offline -- the badge is an
// extra marker, not the only difference, so a stale mapStatus would still be caught.
//
// Match on the class *list* rather than on `class="city-map-status`: Vue emits the
// dynamic bindings first, so the offline case serialises as
// `class="offline city-map-status"`. Anchoring on the static name only worked for
// the two states with no extra class, which is precisely the shape of a test that
// passes for the wrong reason.
function statusText(html) {
  const match = html.match(/<div class="([^"]*\bcity-map-status\b[^"]*)"[^>]*>([\s\S]*?)<\/div>/)
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
if (failed) process.exitCode = 1
