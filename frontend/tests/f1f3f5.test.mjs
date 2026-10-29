/**
 * 0.11.7 · F-1 / F-3 / F-5 判据。
 *
 * 这一组守的是三件**已经把人和评委都骗过一次**的事：
 *   · F-1：函数写好了但没有入口（`setOperatorRole` 0 个调用方 → 按钮焊死）；
 *   · F-3：探针自曝"没接线"（`llm probe not wired` / `store dir not exposed`）；
 *   · F-5：字段叫 `slim: true` 却带着 46% 的 points（**字段在撒谎**）。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const MAIN = readFileSync(new URL('../../backend-python/main.py', import.meta.url), 'utf8')
const OPS = readFileSync(new URL('../../backend-python/traffic/operators.py', import.meta.url), 'utf8')
const API = readFileSync(new URL('../src/api.js', import.meta.url), 'utf8')
const WORK = readFileSync(new URL('../src/components/TrafficWorkbench.vue', import.meta.url), 'utf8')
const VERSION = readFileSync(new URL('../../VERSION', import.meta.url), 'utf8').trim()

test('F-1：身份切换器必须有真实的调用方（不只是定义）', () => {
  // 上一轮的错就在这里：`setOperatorRole` 写在 api.js 里，全站 0 个调用。
  assert.ok(API.includes('export function setOperatorRole'), 'api.js 应有 setOperatorRole')
  const callers = (WORK.match(/setOperatorRole\(/g) || []).length
  assert.ok(callers >= 1, '`setOperatorRole()` 没有任何调用方 —— 这个开关又会被焊死')
  // 下拉框必须有后端枚举的三个值，且缺一个就会让某个动作永远做不到
  for (const role of ['observer', 'duty', 'admin']) {
    assert.ok(WORK.includes(`value="${role}"`), `操作员下拉缺少 ${role}`)
  }
  assert.ok(WORK.includes('data-operator-switch'), '设置面板里没有身份切换控件')
})

test('F-1：切回实测不需要权限（安全侧永远可恢复）', () => {
  // 原来进出都要 admin —— 用 admin 切到虚拟态之后，普通用户再也切不回来，单向门。
  assert.ok(OPS.includes("'weather-mode-to-virtual': 'admin'"), '进虚拟态必须是 admin')
  assert.ok(OPS.includes("'weather-mode-to-measured': 'observer'"),
    '回实测态必须任何人可做 —— 否则就是单向门')
  assert.ok(/weather-mode-to-virtual' if str\(req\.mode\)/.test(MAIN)
    || MAIN.includes("'weather-mode-to-virtual' if"), 'main.py 没有按方向选 action')
  // 错误消息要把修复路径写进去（"请求头 duty" 对用户是天书）
  assert.ok(OPS.includes('设置 → 操作员角色'), '拒绝消息没有告诉用户去哪里改')
})

test('F-3：探针不许自曝"没接线"', () => {
  // ⚠️ 断言要**精确到"返回值"**，不能扫全文：这两个词现在出现在解释性注释里
  // （"原来这里回 llm probe not wired"），扫全文会假红 —— 今天第三次踩这个。
  assert.ok(!/'detail': 'llm probe not wired'/.test(MAIN), '/health 又在自曝 llm probe not wired')
  assert.ok(!/'detail': 'store dir not exposed'/.test(MAIN), '/health 又在自曝 store dir not exposed')
  // 真接线：计划库读 service.STORE，LLM 读 agent_tools.LAST_CALL
  assert.ok(/getattr\(_svc, 'STORE'/.test(MAIN), 'planStore 没读真实的 service.STORE')
  assert.ok(MAIN.includes('agent_tools') && MAIN.includes('LAST_CALL'),
    'LLM 探针没读真实的调用记录')
})

test('F-3：版本号与 VERSION 一致', () => {
  // 两种合法形态：预发布 `0.11.x-beta`、正式版 `1.0.0`（V1.0.0 起）。
  assert.match(VERSION, /^\d+\.\d+\.\d+(-beta)?$/, `VERSION 格式不对：${VERSION}`)
  assert.ok(!/^0\.\d+\.\d+-beta$/.test(VERSION) || !VERSION.startsWith('0.11.4'),
    '版本号退回了早期的 0.11.4')
  // /health 读的是 VERSION 文件，所以这里只需保证文件本身是对的
  assert.ok(MAIN.includes("_read_version()"), 'health 没有从 VERSION 读版本')
})

test('F-5：分页列表的 items 不再带 points', () => {
  // `slim: true` 的语义是"精简版"。带 8 点航迹的列表行不是精简版 —— 字段在撒谎。
  assert.ok(/_slim_row\(flight, with_points=False\)/.test(MAIN),
    '/flights 的 items 仍带 points')
  assert.ok(MAIN.includes('with_points'), '_slim_row 没有 with_points 参数')
  // 但 session 的首屏行**必须**带（地图要画航迹），所以默认值要是 True
  assert.ok(/def _slim_row\(flight, max_points=SLIM_MAX_POINTS, with_points=True\)/.test(MAIN),
    '_slim_row 默认必须带 points —— 否则首屏地图没有航迹')
})
