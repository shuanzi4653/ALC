// 算法身份（0.9.26 / AL-4）—— 一条「算法必须说得出自己是谁」的契约。
//
// 背景（工程表述）：这个系统算得出曲率受限的云团轮廓、同源分层的风险区、凸包精确剪枝
// 与单一运动源，但界面上从来没有一处说出「本轮计划的结论出自哪一份算法」。界面能读出
// 航迹、关闭数与风险区，却读不出这些结论由谁产出 —— 于是算法只能存在于文档里，而文档
// 不是运行时的一部分。
//
// 这一组判据钉住三件事：
//   1. 指纹是**内容**摘要（`traffic/*.py` 的字节），不是版本号摘要：改产品版本号不改
//      指纹，改任一算法文件才改。这正是这句话可以被外部核对的原因。
//   2. 三项任缺其一（未就绪 / 旧载荷 / 字段非法）→ 返回空串**弃权**。不编造占位符，
//      也不显示半截指纹 —— 一个读起来像证据的假字符串，比不出声更坏。
//   3. 标识挂在常显区，且确实被渲染出来（源码静态断言）。`.vue` 的模板求值 `node --test`
//      够不着，而构建不跑模板求值，所以「存在」只能从源码读 —— 同 planChannelContract.test.mjs。
//
// 另一条被这条测试顺带守住的规矩（P0-4）：业务主界面上不得再出现「随机种子 / 种子」——
// 种子是复现参数而不是业务参数，它已移入只读的「工程信息 · 复现参数」折叠区。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { shortFingerprint, algorithmIdentity, algorithmIdentityTitle } from '../src/traffic/runtime.js'

const here = dirname(fileURLToPath(import.meta.url))
const view = await readFile(join(here, '..', 'src', 'components', 'TrafficWorkbench.vue'), 'utf8')

// 真实载荷里的指纹是 `service.py::_fingerprint()` 的 SHA256 前 16 位（十六进制、小写）。
const FP = 'a1b2c3d4e5f60718'
const READY = {
  status: 'READY', version: 'city-traffic-1.3', fingerprint: FP, planRevision: 4, seed: 42,
}
/** 外层模板块。贪婪匹配到最后一个 `</template>`，即 SFC 的根模板。 */
const template = /<template>([\s\S]*)<\/template>/.exec(view)?.[1] ?? ''

// ------------------------------------------------------------ 指纹：只声明完整的

test('指纹只显示前 8 位', () => {
  assert.equal(shortFingerprint(FP), 'a1b2c3d4')
  assert.equal(shortFingerprint(FP).length, 8)
})

test('非十六进制、非字符串、空值一律弃权', () => {
  for (const value of [undefined, null, 42, {}, [], '', '   ']) {
    assert.equal(shortFingerprint(value), '', `不应该对 ${JSON.stringify(value)} 出声`)
  }
  // 十六进制字母表之外的字符：'z'、分隔符、前缀写法都不算指纹。
  for (const value of ['a1b2c3d4e5f6071z', 'a1b2-c3d4', '0xa1b2c3d4e5f60718']) {
    assert.equal(shortFingerprint(value), '', `不应该接受 ${value}`)
  }
})

test('首尾空白被容忍，内部空白不被容忍', () => {
  // 载荷经过 JSON 与模板，边上可能带上空白；那是传输噪声，不该让整条身份消失。
  assert.equal(shortFingerprint('  a1b2c3d4e5f60718  '), 'a1b2c3d4')
  assert.equal(shortFingerprint('\ta1b2c3d4\n'), 'a1b2c3d4')
  // 但指纹中间的空格是另一回事：那是格式错误，不是噪声。
  assert.equal(shortFingerprint('a1b2 c3d4'), '')
})

test('不足 8 位不算指纹：半截值看着像指纹，会让人以为已经核对过', () => {
  for (const value of ['a', 'abcd', 'a1b2c3d']) {
    assert.equal(shortFingerprint(value), '', `${value} 只有 ${value.length} 位，必须弃权`)
  }
  // 恰好在边界上的 8 位是完整的，可以显示。
  assert.equal(shortFingerprint('a1b2c3d4'), 'a1b2c3d4')
})

test('请求长度被夹在 8—16 位之间，且不显示超出实际长度的半截值', () => {
  assert.equal(shortFingerprint(FP, 16), FP)
  assert.equal(shortFingerprint(FP, 12), 'a1b2c3d4e5f6')
  // 要 4 位 → 夹到 8 位（显示下限）；要 99 位 → 夹到 16 位（不等于凭空补长）。
  assert.equal(shortFingerprint(FP, 4), 'a1b2c3d4')
  assert.equal(shortFingerprint(FP, 99).length, 16)
  // 长度参数是坏值时回落到默认 8 位，而不是返回空串或 NaN 位。
  for (const bad of [undefined, null, NaN, 'x', 0]) {
    assert.equal(shortFingerprint(FP, bad).length, 8, `长度参数 ${JSON.stringify(bad)}`)
  }
  // 实际只有 8 位却要 16 位：不补长，也不截成 0 位，直接弃权。
  assert.equal(shortFingerprint('a1b2c3d4', 16), '')
})

test('大小写十六进制都接受，按原文返回', () => {
  // 后端 hexdigest 是小写；这里不强行改写大小写，保证与工程信息区里的原文可逐字比对。
  assert.equal(shortFingerprint('A1B2C3D4E5F60718'), 'A1B2C3D4')
})

// ------------------------------------------------------------ 身份标签：就绪才出声

test('就绪的计划才有算法身份', () => {
  const label = algorithmIdentity(READY)
  assert.match(label, /city-traffic-1\.3/)
  assert.match(label, /a1b2c3d4/)
})

test('未就绪一律弃权，而不是显示一个空壳身份', () => {
  // 轮询到 BUILDING 的那一秒、或拿不到计划时，界面上不能出现"算法 未知"这种东西。
  for (const status of ['BUILDING', 'FAILED', 'READY ', 'ready', '', undefined, null]) {
    assert.equal(algorithmIdentity({ ...READY, status }), '', `status=${JSON.stringify(status)}`)
  }
  for (const session of [undefined, null]) {
    assert.equal(algorithmIdentity(session), '')
  }
})

test('三项里缺任何一项都不出声', () => {
  assert.equal(algorithmIdentity({ ...READY, version: undefined }), '')
  assert.equal(algorithmIdentity({ ...READY, version: '' }), '')
  assert.equal(algorithmIdentity({ ...READY, version: '   ' }), '')
  assert.equal(algorithmIdentity({ ...READY, version: 1.3 }), '', '版本号必须是字符串')
  assert.equal(algorithmIdentity({ ...READY, fingerprint: undefined }), '')
  assert.equal(algorithmIdentity({ ...READY, fingerprint: 'a1b2' }), '', '短指纹弃权')
})

test('算法身份报的是数据契约版本，不是产品版本号', () => {
  // NAMING §7 的口径：`city-traffic-*` 是内部数据契约版本。把 0.9.26 写进这里，会让
  // "改产品版本号不改算法指纹"那句话自相矛盾。
  const label = algorithmIdentity(READY)
  assert.doesNotMatch(label, /0\.9\./)
  assert.doesNotMatch(label, /beta/i)
})

test('导航栏只给前 8 位，完整值留给工程信息区', () => {
  const label = algorithmIdentity(READY)
  assert.match(label, /a1b2c3d4/)
  assert.doesNotMatch(label, new RegExp(FP), '导航栏不该出现完整指纹')
})

// ------------------------------------------------------------ 悬停说明：把规矩说全

test('说明里写清指纹是什么、怎么用', () => {
  const note = algorithmIdentityTitle(READY)
  assert.match(note, /SHA256/, '必须自述指纹的算法，否则这个值无法被外部重算')
  assert.match(note, /改动任一算法文件即改变/)
  assert.match(note, /改动产品版本号不会改变/)
  assert.match(note, /逐字节相同/, '必须给出"怎么用"这一半')
  // 复现三要素要齐：指纹 + 数据快照编号 + 气象通道。
  assert.match(note, /数据快照编号/)
  assert.match(note, /气象通道/)
  assert.match(note, /计划修订 r4/)
})

test('修订号缺失时明说缺失，不写成 r0', () => {
  // `Number(null)` 与 `Number('')` 都是 0 —— 直接转数会把"没给"读成"给了 r0"，
  // 那就是凭空造值。0 本身是合法修订号，所以只对"无值"弃权。
  for (const bad of [undefined, null, '', '   ', 'removed', NaN, {}]) {
    assert.match(algorithmIdentityTitle({ ...READY, planRevision: bad }), /计划修订未声明/,
      `planRevision=${JSON.stringify(bad)} 不该被读成一个数字`)
  }
  assert.match(algorithmIdentityTitle({ ...READY, planRevision: 0 }), /计划修订 r0/)
  assert.match(algorithmIdentityTitle({ ...READY, planRevision: '7' }), /计划修订 r7/)
})

test('没有身份就没有说明，而不是一段没有主语的解释', () => {
  assert.equal(algorithmIdentityTitle(undefined), '')
  assert.equal(algorithmIdentityTitle({ ...READY, status: 'BUILDING' }), '')
  assert.equal(algorithmIdentityTitle({ ...READY, fingerprint: null }), '')
})

// ------------------------------------------------- 组件：标识必须真的被渲染出来

test('组件把算法身份渲染在「复现参数」折叠区（0.11.3 起不再常显于导航栏）', () => {
  // 判据是"这两个函数**确实被引入**"，而不是"它们在 import 列表的末尾"。
  // 后者是一条会随无关改动变红的脆弱断言：0.9.26 的第十轮往同一个 import 里
  // 追加了密度档与演示模式的函数，末尾就不再是这两个名字了 —— 而那种**红**
  // 与被测行为无关，只会教人把断言改松。
  const imports = /import \{([^}]*)\} from '\.\.\/traffic\/runtime\.js'/.exec(view)?.[1] ?? ''
  assert.ok(imports, '找不到运行时的 import 行')
  for (const name of ['algorithmIdentity', 'algorithmIdentityTitle']) {
    assert.match(imports, new RegExp(`(^|,)\\s*${name}\\s*(,|$)`), `组件没有引入 ${name}`)
  }
  assert.match(view, /algorithmIdentity\(session\.value\)/,
    '组件没有按当前计划计算算法身份')
  // C-1：位置从导航栏改到「工程信息 · 复现参数」。判据仍是"确实被渲染出来"，
  // 只是落点跟着产品决策一起搬 —— 断言留在旧位置，就是一条假的回归红灯。
  const repro = /<details class="traffic-repro"[\s\S]*?<\/details>/.exec(template)?.[0] ?? ''
  assert.ok(repro, '找不到复现参数折叠区')
  assert.match(repro, /data-algorithm-identity/, '标识没有挂进复现参数折叠区')
  assert.match(repro, /\{\{algorithmIdentityLabel(\|\|[^}]*)?\}\}/, '算了身份却没有渲染，等于没有')
  assert.match(repro, /:title="algorithmIdentityNote"/, '缺少悬停说明')
  // 反向判据：它**不许**再出现在导航栏常显区 —— 两处各说一次，改一处漏一处。
  const nav = /<nav class="operations-nav"[\s\S]*?<\/nav>/.exec(template)?.[0] ?? ''
  assert.doesNotMatch(nav, /data-algorithm-identity/,
    '算法标识又回到导航栏了 —— 工程字段不进主界面（C-1）')
})

test('复现参数默认折叠，工程密度档下默认展开（C-1 之后的可达性判据）', () => {
  // 旧契约是"标识常显"，新落点是一个 <details>。折叠区最容易出的错是
  // "必须先点一下"变成"默认状态下不存在"，所以这里钉住它的开合由密度档决定。
  // 工程档必须默认展开：需要看指纹的人，恰恰是在排障。
  const repro = /<details class="traffic-repro"[^>]*>/.exec(template)?.[0] ?? ''
  assert.ok(repro, '找不到复现参数折叠区')
  assert.match(repro, /:open="densityPolicy\(density\)\.engineering"/,
    '复现参数的开合必须挂在密度档上：工程档默认展开，其余默认收起')
})

test('算法标识在模板里只出现一次', () => {
  assert.equal((template.match(/data-algorithm-identity/g) || []).length, 1)
})

// ------------------------------------------------- 复现参数：退出业务视图（P0-4）

test('业务主界面上不再出现种子', () => {
  assert.doesNotMatch(template, /种子/,
    '种子已移出业务视图：模板里不该再有这两个字')
  const toolbar = /<section class="traffic-toolbar"[\s\S]*?<\/section>/.exec(template)?.[0] ?? ''
  assert.ok(toolbar, '找不到运行设置区')
  assert.doesNotMatch(toolbar, /<input/, '运行设置区里不该还有可编辑输入框')
})

test('复现参数以只读折叠区留在运行设置里', () => {
  const toolbar = /<section class="traffic-toolbar"[\s\S]*?<\/section>/.exec(template)?.[0] ?? ''
  // 属性列表允许追加，但 `class` 与 `data-repro-params` 这一对必须原样在。
  // 0.9.26 第十轮给它加了 `:open`（密度档「值班员」默认展开）—— 那是**默认开合**
  // 的变化，不是"它还在不在"的变化，所以断言在这里放宽，同时下面另加一条钉住
  // "它仍然是可以折叠的 details"。放松一条而不同时加一条，就是把判据改没了。
  assert.match(toolbar, /<details class="traffic-repro" data-repro-params[^>]*>/, '缺少折叠区')
  assert.match(toolbar, /<summary>工程信息 · 复现参数<\/summary>/)
  // 五个要素齐：数据快照编号 + 计划标识 + 计划修订 + 算法版本 + 算法指纹 + 气象通道。
  for (const label of ['数据快照编号', '计划标识', '计划修订', '算法版本', '算法指纹', '气象通道']) {
    assert.match(toolbar, new RegExp(`<dt>${label}</dt>`), `复现区缺少「${label}」`)
  }
  // 只读：整块里不能有可编辑控件。
  assert.doesNotMatch(toolbar, /<input/,
    '复现区必须是只读的，不能又变成第二个业务输入口')
  // 默认开合必须受**密度档**控制。演示模式声称"隐藏工程参数"，靠的就是这一句；
  // 少了它，「隐藏工程参数」只是说明文字里的一句话，屏幕上什么都没有发生。
  assert.match(toolbar, /:open="densityPolicy\(density\)\.engineering"/,
    '复现区的默认开合要由密度档决定（演示档收起 / 值班档展开）')
  // 复现规则要写在块里，否则这五项只是五个孤立的值。
  assert.match(toolbar, /逐字节相同的运行计划/)
})
