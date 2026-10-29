/**
 * 0.11.6 · E-3 判据：操作级授权。
 *
 * **这一层不是认证** —— 它没有密码、没有会话、没有签名，`X-ALC-Operator` 是自报的。
 * 所以判据守的不是"安全"，而是三件比安全更容易做错的事：
 *   ① **默认值必须是最小权限**（不带头 = 观察员），否则任何脚本自动获得写权限；
 *   ② **真正被调用的那个端点必须装门** —— 上一版把门装在 `operations/dispose` 上，
 *      而前端调的是 `v2/decision`，等于门装在没人走的墙上；
 *   ③ **拒绝要说清缺什么**，而不是一句"无权限"。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const OPS = readFileSync(new URL('../../backend-python/traffic/operators.py', import.meta.url), 'utf8')
const MAIN = readFileSync(new URL('../../backend-python/main.py', import.meta.url), 'utf8')
const V2 = readFileSync(new URL('../../backend-python/traffic/v2.py', import.meta.url), 'utf8')
const API = readFileSync(new URL('../src/api.js', import.meta.url), 'utf8')
const JAVA = readFileSync(
  new URL('../../backend-java/src/main/java/com/tianchuang/service/PythonClient.java', import.meta.url), 'utf8')

test('E-3：三个角色，默认必须是最小权限', () => {
  assert.match(OPS, /ROLE_LEVEL = \{'observer': 1, 'duty': 2, 'admin': 3\}/,
    '角色等级表缺失或被重排（重排会让历史 journal 的含义变化）')
  // 不带头 -> observer，这是整套设计的支点
  assert.match(OPS, /if not raw:\s*\n\s*return Identity\(role='observer'/,
    '「不带头 = 观察员」这条必须显式写在代码里，不能靠 dict 默认值碰运气')
  // 头给了但不认识 -> 仍然观察员，但标 invalid（不静默降级）
  assert.ok(/return Identity\(role='observer', raw=raw, valid=False\)/.test(OPS),
    '未知身份头没有标记 invalid —— 那样 403 的文案只能说"无权限"，说不出"你发的值不认识"')
})

test('E-3：真正被调用的写端点装了门', () => {
  // 前端实际调 `/api/traffic/v2/decision`（CorridorPanel 的否决/采纳），
  // 不是 `operations/dispose`。这一条就是在守"门要装在有人走的墙上"。
  const block = MAIN.slice(MAIN.indexOf("@app.post('/traffic/v2/decision')"),
                          MAIN.indexOf("@app.post('/traffic/v2/decision')") + 700)
  assert.ok(block.includes("_require(request, 'dispose')"),
    '`v2/decision` 没有角色检查 —— 任何人都还能写决策记录')
  // 其余写端点也要有
  for (const marker of ["@app.post('/traffic/command')", "@app.post('/traffic/operations/note')",
                        "@app.post('/traffic/weather/mode')"]) {
    const at = MAIN.indexOf(marker)
    assert.ok(at > 0, `找不到 ${marker}`)
    // 窗口要够宽：F-1 之后 `weather_mode_set` 的 docstring 变长了，400 字符切不到
    // `_require`。判据的窗口是按"函数有多长"猜的，而函数会长大 —— 所以放宽。
    const segment = MAIN.slice(at, at + 900)
    assert.ok(segment.includes('_require(request'), `${marker} 没有角色检查`)
  }
})

test('E-3：journal 记角色，且只增不改', () => {
  assert.ok(/'role': payload\.get\('role'\)/.test(V2), 'record_decision 没有记录 role')
  // 原有字段必须都还在（DivergencePanel 在读）
  for (const field of ["'at'", "'corridorId'", "'flightId'", "'ruleLevel'", "'p'",
                       "'confidence'", "'verdict'", "'operator'", "'rolledBack'"]) {
    assert.ok(V2.includes(field), `journal 原有字段 ${field} 被改了 —— 只增不改`)
  }
})

test('E-3：身份头从浏览器一路到 Python', () => {
  assert.ok(API.includes('X-ALC-Operator'), '前端没有发身份头')
  assert.ok(/operatorRole\(\).*duty/s.test(API) || API.includes("return 'duty'"),
    '前端默认身份不是 duty —— 现场第一次点否决会 403')
  // Java 必须在**唯一出口** builder() 里透传（六个方法各自加，迟早漏一个）
  assert.ok(JAVA.includes('OperatorContext.current()'), 'Java 没有透传身份头')
  assert.ok(/private HttpRequest\.Builder builder\(/.test(JAVA), 'builder() 是唯一出口，不该在别处加头')
})

test('E-3：拒绝消息要说清"缺什么角色"', () => {
  assert.ok(/def deny_message/.test(OPS), '缺少拒绝文案的构造')
  assert.ok(/需要%s及以上/.test(OPS), '拒绝文案没有说明需要什么角色')
  assert.ok(/可选项|observer \/ duty \/ admin/.test(OPS), '未知值时要告诉用户有哪些可选值')
})
