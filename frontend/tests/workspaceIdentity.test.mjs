// 工作区身份（2026-10-14 拆登录门）。
//
// 这一组测的是**契约的形状**，不是界面长什么样：
//   - 串必须落在后端接受的形状里（Python `workspace.py::PATTERN`、
//     Java `WorkspaceContext.PATTERN`，同一个正则）。写错了不会报错，
//     只会静默落进「未标识」命名空间 —— 那就等于和所有人撞在一起。
//   - 读回来的值必须**校验**而不是采信：一个被改坏/被截断的存量值不能直接
//     当身份用（后端是 reject-not-repair，前端若 repair-or-trust 就成了两套语义）。
//   - 身份必须同时出现在 HTTP 头与 WebSocket 查询参数上，且**是同一个串**。
//
// 说明：`node --test` 每跑一个文件是一个独立进程，文件内的用例共享模块状态，
// 所以要换「存量值」时必须先清掉模块内缓存（`__resetCacheForTests`）。

import test from 'node:test'
import assert from 'node:assert/strict'
import {
  workspaceId, workspaceLabel, resetWorkspace, __resetCacheForTests,
} from '../src/workspace.js'
import { requestJson, dashboardSocketUrl } from '../src/api.js'

// 后端两侧同一份：`^[A-Za-z0-9_-]{6,64}$`
const BACKEND_PATTERN = /^[A-Za-z0-9_-]{6,64}$/

/** 装一个可控的 localStorage。返回 setItem 的写入记录，方便断言"落盘了"。 */
function stubStorage(initial) {
  const map = new Map(initial === undefined ? [] : [['alc_ws', initial]])
  const writes = []
  globalThis.localStorage = {
    getItem: key => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => { writes.push([key, value]); map.set(key, value) },
    removeItem: key => { map.delete(key) },
    clear: () => { map.clear() },
  }
  return { writes, map }
}

function dropStorage() {
  // 不留痕迹：后面若有别的用例只靠 `typeof` 判断，会误以为处在浏览器里。
  delete globalThis.localStorage
}

test('工作区串落在后端接受的形状里，且同一会话内稳定', () => {
  __resetCacheForTests()
  const first = workspaceId()
  assert.match(first, BACKEND_PATTERN, `后端会拒掉的形状：${first}`)
  assert.equal(workspaceId(), first, '同一浏览器同一会话内必须稳定，否则每次都换命名空间')
  assert.equal(workspaceLabel(), first.slice(0, 8))
})

test('存量的不合规值被拒绝并换成新串，而不是照抄去用', () => {
  __resetCacheForTests()
  // 三种真实会出现的坏值：太短、带路径分隔符、超长。
  for (const bad of ['ab', '../../etc/passwd', 'x'.repeat(65)]) {
    const { writes } = stubStorage(bad)
    __resetCacheForTests()
    const id = workspaceId()
    assert.match(id, BACKEND_PATTERN, `坏值 ${bad} 应被拒绝`)
    assert.notEqual(id, bad)
    assert.deepEqual(writes, [['alc_ws', id]], '新串必须写回，否则刷新后又变一个身份')
  }
  dropStorage()
})

test('合规的存量值被沿用——刷新页面不能换工作区', () => {
  __resetCacheForTests()
  const kept = 'a1b2c3d4e5f60718293a4b5c'
  stubStorage(kept)
  __resetCacheForTests()
  assert.equal(workspaceId(), kept)
  dropStorage()
})

test('重置给出一个不同的合规串（旧数据仍在服务端，只是换了命名空间）', () => {
  __resetCacheForTests()
  stubStorage()
  const before = workspaceId()
  const after = resetWorkspace()
  assert.match(after, BACKEND_PATTERN)
  assert.notEqual(after, before)
  assert.equal(workspaceId(), after, '重置之后所有读取都必须拿到新串')
  dropStorage()
})

test('每个 HTTP 请求都带上工作区头（含只读端点）', async () => {
  __resetCacheForTests()
  stubStorage()
  const original = globalThis.fetch
  let seen = null
  try {
    globalThis.fetch = async (_path, init) => {
      seen = init?.headers
      return new Response(JSON.stringify({ version: 1, runSequence: 1 }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }
    // 故意用 GET：只在写路径带身份会让"读"退回全局那一份，而那正是要避免的。
    await requestJson('/api/dashboard')
    assert.ok(seen, 'requestJson 必须把 headers 交给 fetch')
    assert.equal(seen.get('X-ALC-Workspace'), workspaceId())
  } finally {
    globalThis.fetch = original
    dropStorage()
  }
})

test('WebSocket 握手 URL 用同一个串走查询参数（握手发不出自定义头）', () => {
  __resetCacheForTests()
  stubStorage()
  const id = workspaceId()
  const url = dashboardSocketUrl('example.test', true)
  assert.ok(url.startsWith('wss://example.test/ws/dashboard?'), url)
  assert.equal(new URL(url).searchParams.get('ws'), id)
  // 非 https 一律 ws，不要因为探针在 http 上就拼出 wss。
  assert.ok(dashboardSocketUrl('example.test', false).startsWith('ws://example.test/'))
  dropStorage()
})
