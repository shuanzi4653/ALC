import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { radarRelaySlots, radarRelayReady } from '../src/traffic/runtime.js'
import { relayRadarTiles, bytesToBase64 } from '../src/traffic/radarRelay.js'

// 中继这条路只有两条判据是真正关键的，其余都是伴随项：
//   1. **时次字面值必须是北京时**，与跑它的机器在哪个时区无关。搞错了不会报错，
//      只会稳定地取到另一个时次的图 —— 而"取到了"和"取对了"长得一模一样。
//   2. **拿到的字节必须正好是服务端说的那些字节**。少一行像元的图位置正确、
//      内容错误，比没有图危险，所以长度不符要当"这一档没有"，不能当"差一点也算"。
// 这两条都不依赖 DOM，所以放在 runtime.js / radarRelay.js 里，在这里直接断言。

// requestJson 在非 GET 路径上读 document.cookie（工作区身份随每个请求出去）。
// 纯 Node 里没有 document —— 不补这一笔，POST 会在读 cookie 处抛 ReferenceError，
// 被 relayRadarTiles 的 catch 收成 POST_FAILED，看起来像"后端拒收"。
globalThis.document = { cookie: '' }

const TILE_BYTES = 256 * 256 * 2

function instructions(overrides = {}) {
  return {
    needed: true,
    tileBase: 'https://image.data.cma.cn/api/service/tiles/radar',
    grid: [[0, 0], [1, 0]],
    zoom: 3,
    cadenceMinutes: 6,
    maxLookbackSteps: 4,
    slotTimezoneOffsetMinutes: 480,
    tileBytes: TILE_BYTES,
    postTo: '/api/traffic/radar/tiles',
    ...overrides,
  }
}

/** 最小可用响应替身：同时满足取瓦片（ok + arrayBuffer）与 POST（json + headers）。 */
function response({ ok = true, status = 200, bytes = TILE_BYTES, payload = {} } = {}) {
  return {
    ok,
    status,
    headers: { get: () => 'application/json' },
    arrayBuffer: async () => new ArrayBuffer(bytes),
    json: async () => payload,
  }
}

/** 按 URL 分派的 fetch 替身。记录每次调用（含 options），供"有没有乱带头"之类断言。
 *
 * 必须同时挂到 `globalThis.fetch`：取瓦片走的是显式传进来的 `fetchImpl`，而回传
 * 那一跳走的是 `requestJson` 内部的**全局** fetch。只替换前者，POST 会打到相对
 * 路径上、报成"无法连接服务"—— 看起来像后端不在，其实只是替身没盖住那一跳。
 */
function stubFetch(routes) {
  const calls = []
  const impl = async (url, options) => {
    calls.push({ url, options })
    return routes(url, options)
  }
  impl.calls = calls
  globalThis.fetch = impl
  return impl
}

// ── 一、时次口径 ────────────────────────────────────────────────────────────

test('路径里的时间字面值是北京时，不是 UTC', () => {
  // 07:24Z 就是北京 15:24。用 UTC 拼路径正是本轮在服务端踩过的坑：
  // 每次都取到 8 小时前的那一帧。
  const [newest] = radarRelaySlots(Date.UTC(2026, 9, 15, 7, 24), 480, 6, 1)
  assert.equal(newest.path, '20261015/15/24')
  assert.equal(newest.label, '2026-10-15 15:24')
  // iso 是**绝对时刻**，必须回到 07:24Z，否则后端的"未来时次"校验会误判。
  assert.equal(newest.iso, '2026-10-15T07:24:00.000Z')
})

test('提前一分钟按 6 分钟栅格向下取整，字面值仍然对齐', () => {
  for (const minute of [25, 29, 30]) {
    const [newest] = radarRelaySlots(Date.UTC(2026, 9, 15, 7, minute, 59), 480, 6, 1)
    assert.equal(newest.path, `20261015/15/${minute <= 29 ? '24' : '30'}`, `minute=${minute}`)
  }
})

test('从最新到最旧，每档退回一个发布节奏', () => {
  const slots = radarRelaySlots(Date.UTC(2026, 9, 15, 7, 24), 480, 6, 4)
  assert.deepEqual(slots.map(s => s.path), [
    '20261015/15/24', '20261015/15/18', '20261015/15/12', '20261015/15/06',
  ])
  // 跨小时要能正确回退到上一小时，而不是变成 15:-6 之类。
  const wide = radarRelaySlots(Date.UTC(2026, 9, 15, 7, 24), 480, 6, 26)
  assert.equal(wide[25].path, '20261015/12/54')
  assert.equal(wide[25].label, '2026-10-15 12:54')
})

test('时次字面值不随机器时区改变 —— 本机在 UTC+8，测试不能只在这台机器上成立', () => {
  const entry = new URL('../src/traffic/runtime.js', import.meta.url).href
  const script = `
    import { radarRelaySlots } from ${JSON.stringify(entry)}
    const [s] = radarRelaySlots(Date.UTC(2026, 9, 15, 7, 24), 480, 6, 1)
    process.stdout.write(s.path + '|' + s.iso)
  `
  const seen = new Set()
  for (const tz of ['Asia/Shanghai', 'America/New_York', 'UTC', 'Pacific/Kiritimati']) {
    const out = execFileSync(process.execPath, ['--input-type=module', '-e', script], {
      env: { ...process.env, TZ: tz },
      encoding: 'utf8',
    })
    seen.add(out.trim())
    assert.equal(out.trim(), '20261015/15/24|2026-10-15T07:24:00.000Z', `TZ=${tz}`)
  }
  assert.equal(seen.size, 1)
})

test('取图说明不完整时不要发起中继（会白跑一轮网络）', () => {
  assert.equal(radarRelayReady(instructions()), true)
  assert.equal(radarRelayReady(undefined), false)
  assert.equal(radarRelayReady(null), false)
  assert.equal(radarRelayReady({}), false)
  // needed:false 是"服务端已经取到了"，不是"指令缺失"——两种都不该触发中继。
  assert.equal(radarRelayReady(instructions({ needed: false })), false)
  assert.equal(radarRelayReady(instructions({ needed: undefined })), false)
  assert.equal(radarRelayReady(instructions({ tileBase: '' })), false)
  assert.equal(radarRelayReady(instructions({ grid: [] })), false)
  assert.equal(radarRelayReady(instructions({ grid: null })), false)
  assert.equal(radarRelayReady(instructions({ zoom: '3' })), false)
})

// ── 二、中继一轮 ────────────────────────────────────────────────────────────

test('最新一档没发布时退回上一档，且回传的时次就是真正取到的那一刻', async () => {
  const relay = instructions()
  const newestPath = radarRelaySlots(Date.UTC(2026, 9, 15, 7, 24), 480, 6, 1)[0].path
  const fetchImpl = stubFetch((url) => {
    if (url.includes('/tiles/')) {
      // 404 在源站不带 CORS 头，浏览器给的是 TypeError 而不是 res.ok=false。
      if (url.includes(`/${newestPath}/`)) throw new TypeError('Failed to fetch')
      return response()
    }
    return response({ payload: { ttlSeconds: 600, slot: 'ok' } })
  })
  const result = await relayRadarTiles(relay, { fetchImpl, nowMs: Date.UTC(2026, 9, 15, 7, 24) })
  assert.equal(result.ok, true)
  assert.equal(result.slot, '2026-10-15 15:18')
  const post = fetchImpl.calls.at(-1)
  assert.equal(post.url, '/api/traffic/radar/tiles')
  const body = JSON.parse(post.options.body)
  assert.equal(body.slot, '2026-10-15T07:18:00.000Z')
  assert.equal(body.zoom, 3)
  assert.deepEqual(body.tiles.map(t => [t.x, t.y]), [[0, 0], [1, 0]])
})

test('对第三方源只搬字节：不带头、不带 Cookie、不缓存', async () => {
  const fetchImpl = stubFetch((url) => (url.includes('/tiles/') ? response()
    : response({ payload: { ttlSeconds: 600 } })))
  await relayRadarTiles(instructions(), { fetchImpl, nowMs: Date.UTC(2026, 9, 15, 7, 24) })
  const tileCalls = fetchImpl.calls.filter(c => c.url.includes('/tiles/'))
  assert.equal(tileCalls.length, 2)
  for (const call of tileCalls) {
    assert.deepEqual(call.options, { mode: 'cors', credentials: 'omit', cache: 'no-store' })
    // 路径里只有 x/y/zoom/时次，没有任何工作区标识或我们的自有头。
    assert.doesNotMatch(call.url, /X-ALC-Workspace|workspace=/i)
  }
})

test('长度不符的瓦片当作"这一档没有"，绝不将就回传', async () => {
  // 少一个字节就少一行像元：图的位置是对的、内容是错的。这比没有图危险，
  // 所以长度不符必须落到"这一档不可用"，而不是"差一点也传上去"。
  let served = 0
  const fetchImpl = stubFetch((url) => {
    if (!url.includes('/tiles/')) return response({ payload: {} })
    served += 1
    return response({ bytes: TILE_BYTES - 2 })
  })
  const result = await relayRadarTiles(instructions({ maxLookbackSteps: 3 }), {
    fetchImpl, nowMs: Date.UTC(2026, 9, 15, 7, 24),
  })
  assert.equal(result.ok, false)
  assert.equal(result.reason, 'NO_SLOT_AVAILABLE')
  assert.equal(result.tried, 3)
  assert.equal(served, 3)
  // 一次 POST 都不该发出去。
  assert.equal(fetchImpl.calls.filter(c => !c.url.includes('/tiles/')).length, 0)
})

test('每一档都取不到时如实说"本机也没取到"，而不是抛出去', async () => {
  const fetchImpl = stubFetch(() => { throw new TypeError('Failed to fetch') })
  const result = await relayRadarTiles(instructions({ maxLookbackSteps: 5 }), {
    fetchImpl, nowMs: Date.UTC(2026, 9, 15, 7, 24),
  })
  assert.deepEqual(result, { ok: false, reason: 'NO_SLOT_AVAILABLE', tried: 5 })
})

test('取到字节但后端不收 —— 与"这一档没发布"必须分开报', async () => {
  // 这两种失败在界面上长得一样（都是"没图"），但排查方向完全相反：
  // 一个是等下一档，一个是后端校验或故障。混成一句就等于没有信息。
  const fetchImpl = stubFetch((url) => (url.includes('/tiles/')
    ? response()
    : response({ ok: false, status: 422, payload: { message: 'tile length mismatch' } })))
  const result = await relayRadarTiles(instructions(), { fetchImpl, nowMs: Date.UTC(2026, 9, 15, 7, 24) })
  assert.equal(result.ok, false)
  assert.equal(result.reason, 'POST_FAILED')
  assert.match(result.message, /tile length mismatch/)
  assert.equal(result.slot, '2026-10-15 15:24')
})

test('没有取图说明就不动手', async () => {
  const fetchImpl = stubFetch(() => { throw new Error('不该被调用') })
  const result = await relayRadarTiles(instructions({ needed: false }), { fetchImpl })
  assert.deepEqual(result, { ok: false, reason: 'NO_INSTRUCTIONS' })
  assert.equal(fetchImpl.calls.length, 0)
})

test('说明里的候选档数决定回溯范围，缺省时退回 12 档', async () => {
  const fetchImpl = stubFetch(() => { throw new TypeError('Failed to fetch') })
  const given = await relayRadarTiles(instructions({ maxLookbackSteps: 2 }), { fetchImpl })
  assert.equal(given.tried, 2)
  const fallback = await relayRadarTiles(instructions({ maxLookbackSteps: undefined }), { fetchImpl })
  assert.equal(fallback.tried, 12)
})

// ── 三、字节搬运 ────────────────────────────────────────────────────────────

test('base64 分块编码，大数组不爆栈且可逆', () => {
  const bytes = new Uint8Array(TILE_BYTES)
  for (let i = 0; i < bytes.length; i += 1) bytes[i] = i % 251
  const encoded = bytesToBase64(bytes)
  const decoded = Buffer.from(encoded, 'base64')
  assert.equal(decoded.length, TILE_BYTES)
  assert.equal(decoded[0], 0)
  assert.equal(decoded[251], 0)
  assert.equal(decoded[250], 250)
})

// ── 四、顺序：建计划之前必须先中继（顺序是判据，不是偏好）────────────────────
//
// 计划取帧与地图取帧是两条路：地图在中继成功**之后**才取，计划在构建时取。此前的顺序是
// "建计划 → 取气象 → 中继"，于是计划永远拿到"服务器直取"，而在云端出口上那是整站 403
// —— 计划里没有雷达几何，地图随后画出一片回波（2026-10-15 线上：操作台上 12 架载具停在
// 禁入区内核里、没有任何绕行，而字段、状态码、键全都合法）。
//
// 这条读源码断言：`generate()` 在请求 `/api/traffic/session` 之前**await** 了预检。
// `.vue` 的函数体在 `node --test` 里跑不到，构建也不跑它 —— 顺序只能这样钉。
const WORKBENCH_SRC = readFileSync(
  new URL('../src/components/TrafficWorkbench.vue', import.meta.url), 'utf8')

test('建计划之前先中继：请求会话前必须 await 预检', () => {
  const start = WORKBENCH_SRC.indexOf('async function generate()')
  assert.ok(start > 0, '找不到 generate()')
  const body = WORKBENCH_SRC.slice(start)
  const preflight = body.indexOf('await preflightRadar()')
  const sessionRequest = body.indexOf('/api/traffic/session')
  assert.ok(preflight > 0, 'generate() 里没有 await 预检')
  assert.ok(sessionRequest > 0, 'generate() 里找不到会话请求')
  assert.ok(preflight < sessionRequest,
    '预检排在会话请求之后：计划会拿到"服务器直取"，而这在云端是 403')

  const preStart = WORKBENCH_SRC.indexOf('async function preflightRadar()')
  assert.ok(preStart > 0, '找不到 preflightRadar()')
  const pre = WORKBENCH_SRC.slice(preStart, start)
  assert.ok(pre.includes('maybeRelayRadar('), '预检只取了气象帧，没有发起中继')
  assert.ok(pre.includes('radar.relay') || pre.includes('maybeRelayRadar(value)'),
    '预检没有把服务端下发的取图说明交给中继')
})

test('中继状态条的主语只有一个来源（模板里的 <b>实测雷达</b>）', () => {
  // 原先两边都写：模板印 `<b>实测雷达</b>`，而 detail 又写「实测雷达由本机浏览器代取…」,
  // 于是屏幕上是一句读起来像结巴的话 ——「实测雷达实测雷达由本机浏览器代取：19:30（北京时）」。
  //
  // 判据取"**detail 里不得出现主语**"这一族，而不是钉死改后的那一句字面量：钉字面量的话，
  // 下一个人换一句新文案、照样重复一遍主语，判据仍然全绿（M85：判据的射程由它认得的写法决定）。
  // 0.11.4（W-26）：形态从「固定在左下角的一条注脚」改成「顶栏里的胶囊」——
  // 原来 `position:fixed;left:14px;bottom:46px` 会在滚动时压住首页底部工具栏。
  // 契约随之变化：主语在胶囊正文（`雷达 22:54`），全文进 `title`。
  // 判据仍钉住**唯一来源**这件事：胶囊正文只写一次主语，detail 里不得再重复。
  assert.match(WORKBENCH_SRC, /class="relay-pill"[\s\S]{0,320}radarRelay\.status/,
    '中继状态条必须存在，且是顶栏胶囊形态（data-radar-relay 仍在）')
  assert.match(WORKBENCH_SRC, /:title="'实测雷达' \+ radarRelay\.detail"/,
    '全文必须挂在 title 上（数据来源仍可核对，只是不再压住版面）')
  const details = [...WORKBENCH_SRC.matchAll(/radarRelay\.value=\{[^}]*detail:(`[^`]*`|'[^']*')/g)]
    .map((m) => m[1])
  assert.ok(details.length >= 3,
    `只扫到 ${details.length} 条中继文案，扫描面可能已经失效（新写法逃出了这条判据）`)
  for (const text of details) {
    assert.doesNotMatch(text, /实测雷达/, `中继文案不得重复主语：${text}`)
  }
})
