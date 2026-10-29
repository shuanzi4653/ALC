/**
 * 0.11.5 · W-31 判据：首屏载荷分层。
 *
 * 这一组守的不是"体积数字"（那个只能在线上量），而是**分层的两条纪律**：
 *   ① 白名单，不是黑名单 —— 新字段默认不进 slim，否则"某个字段悄悄变大"没人发现；
 *   ② 前端必须**先知道自己在读裁剪过的数据**（`slim` 标记 + 按需补取），
 *      否则"字段缺失"会被演成"这条班次本来就没有许可信息"。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const MAIN = readFileSync(new URL('../../backend-python/main.py', import.meta.url), 'utf8')
const WORK = readFileSync(new URL('../src/components/TrafficWorkbench.vue', import.meta.url), 'utf8')
const BRIEF = readFileSync(new URL('../src/components/traffic/SituationBrief.vue', import.meta.url), 'utf8')

test('W-31：session 用白名单裁剪，且航迹抽稀保留首末点', () => {
  assert.ok(MAIN.includes('SLIM_FLIGHT_FIELDS'), '缺少白名单常量（黑名单会让新字段默认进首屏）')
  assert.ok(MAIN.includes('SLIM_MAX_POINTS'), '缺少抽稀上限')
  assert.ok(MAIN.includes('fields: str = Query('), 'session 没有 fields 参数')
  // 首末点必保：时间戳随点保留，`atTime()` 的插值精度才不受抽稀影响
  assert.ok(/picked\[-1\] = points\[-1\]/.test(MAIN), '抽稀后必须显式保住最后一个点')
  // 裁剪不能改缓存里那一份
  assert.ok(/\{\*\*payload, 'flights': slim/.test(MAIN),
    '裁剪必须返回新对象（原地改会污染缓存，下一次请求拿到的是被裁过的计划）')
})

test('W-31：被裁剪的行必须自带 slim 标记', () => {
  assert.ok(/row\['slim'\] = True/.test(MAIN), 'slim 行没有标记，前端无法判断要不要补取')
  // 标记放在**行上**而不是全局：前端只需要问"这一行被裁过吗"
  assert.ok(/SLIM_FLIGHT_FIELDS/.test(MAIN))
})

test('W-31：前端首屏请求 slim，且只在被裁过时补取', () => {
  assert.ok(/fields=slim/.test(WORK), '首屏没有请求 slim')
  assert.ok(WORK.includes('ensureFullFlight'), '缺少单班补取')
  assert.ok(WORK.includes('/api/traffic/flight/'), '补取没有走单班接口')
  // 关键：补取的触发条件是 `row.slim`，不是"字段看起来空" —— 后者会把
  // "这条班次真的没有许可"也当成"没取到"，然后无限重取。
  assert.ok(/if\(!row\|\|!row\.slim\)return/.test(WORK), '补取条件必须是 slim 标记')
  // 补取结果不能写回 flights 数组（那是派生列表，写进去等于两个概念混在一个对象上）
  assert.ok(WORK.includes('fullFlights'), '补取结果没有单独存放')
})

test('W-31：首屏不许出现「作废」', () => {
  // 复测报告 P1-3：`BUILDING` 期间首屏写着「结论已作废」—— 那是把一次
  // 正常的重算演成一次故障。换成"正在重算（约 40 秒）"。
  assert.ok(!BRIEF.includes('结论已作废'), '首屏又出现「作废」二字')
  assert.ok(BRIEF.includes('正在按当前情景重算'), '必须说明在重算、多久、之后会自动替换')
})

test('W-31：Java 的 422 必须透出缺的是哪个参数', () => {
  const JAVA = readFileSync(
    new URL('../../backend-java/src/main/java/com/tianchuang/service/PythonClient.java', import.meta.url), 'utf8')
  // 原来一律用"决策请求被拒绝，请检查输入、时次或记录是否存在"，
  // 于是缺 `sessionId` 被读成"case 参数没落地"—— 一句含糊的消息让人去查不存在的 bug。
  assert.ok(JAVA.includes('detail.isArray()'), '422 的 detail 数组没有被解析')
  assert.ok(JAVA.includes('"loc"'), '没有取 loc（缺的是哪个参数）')
})
