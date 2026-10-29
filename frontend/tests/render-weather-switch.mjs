// Opt-in render check for the weather-channel switch.
//
// The unit tests cover the pure helpers in runtime.js, but they cannot prove the
// .vue file actually renders two buttons with the right disabled state. A template
// typo can survive `vite build` (it only bundles) and still produce an empty or
// malformed control. So: transform the SFC through Vite's own SSR pipeline and
// render it to HTML in both modes.
//
// Run: node tests/render-weather-switch.mjs
import { createServer } from 'vite'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'

const server = await createServer({
  server: { middlewareMode: true },
  appType: 'custom',
  logLevel: 'error',
})

const mod = await server.ssrLoadModule('/src/components/traffic/WeatherSourceSwitch.vue')
await server.close()

const Switch = mod.default
const results = []
for (const mode of ['measured', 'virtual']) {
  const status = mode === 'virtual'
    ? { mode, framesServed: { virtualFrames: 5 }, virtualNotice: { statement: '本帧为程序生成的模拟对流回波，不是观测数据。几何形态与强度分档仿照主流气象雷达产品，仅用于演示与重现。' } }
    : { mode, framesServed: { measuredFrames: 9 }, available: true }
  const app = createSSRApp(Switch, { mode, status, compact: false })
  app.config.warnHandler = () => {}
  results.push({ mode, html: await renderToString(app) })
}

const out = []
for (const { mode, html } of results) {
  out.push(`--- ${mode} ---`)
  const buttons = [...html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)]
  out.push(`buttons: ${buttons.length}`)
  for (const [, attrs, body] of buttons) {
    const label = body.replace(/<[^>]*>/g, '').trim()
    out.push(`  label="${label}" disabled=${/\bdisabled\b/.test(attrs)}`)
  }
  out.push(`caption 气象通道: ${html.includes('气象通道')}`)
  out.push(`virtual warn strip: ${html.includes('不是观测数据')}`)
  out.push(`virtual class on root: ${/class="[^"]*weather-switch[^"]*virtual/.test(html)}`)
  if (buttons.length !== 2) { out.push('FAIL: expected exactly 2 mode buttons'); process.exitCode = 1 }
}

const measured = results.find(r => r.mode === 'measured')
const virtual = results.find(r => r.mode === 'virtual')
const enabledCount = html => [...html.html.matchAll(/<button\b([^>]*)>/g)].filter(([, a]) => !/\bdisabled\b/.test(a)).length
if (enabledCount(measured) !== 1) { out.push(`FAIL: measured should offer exactly 1 enabled button, got ${enabledCount(measured)}`); process.exitCode = 1 }
if (enabledCount(virtual) !== 1) { out.push(`FAIL: virtual should offer exactly 1 enabled button, got ${enabledCount(virtual)}`); process.exitCode = 1 }
if (measured.html.includes('不是观测数据')) { out.push('FAIL: measured must not show the synthetic warning'); process.exitCode = 1 }
if (!virtual.html.includes('不是观测数据')) { out.push('FAIL: virtual must show the synthetic warning'); process.exitCode = 1 }

out.push(process.exitCode ? 'RESULT: FAIL' : 'RESULT: PASS')
const text = out.join('\n')
console.log(text)
const { writeFile } = await import('node:fs/promises')
await writeFile('../.run/_render_check.txt', text + '\n')
