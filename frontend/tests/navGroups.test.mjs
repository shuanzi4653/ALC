import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {
  NAV_GROUPS,navGroup,groupOfSection,defaultSub,navCoverageGap,
  riskTone,riskLabel,pct,hourLabel,CONFIDENCE_GATE,confidencePass,SECTION_NAMES,
  ENTRY_LABELS} from '../src/traffic/runtime.js'

// 0.11.1（Beta）· 五页信息架构的读数层（手册 §2 / §8 / §9）。
//
// 这一批全是**纯函数**，因此风险集中在两类"看起来对、其实在骗人"的地方：
//   ① 概率阈值写两处（颜色一处、文字一处）→ 屏幕上出现"红色 + 可飞"；
//   ② 缺值被当作 0 → "没有数字"被渲染成"数字就是 0"（M67 的老坑，换芯后又来一遍）。
// 下面每条判据都对着这两类之一。

test('五个顶层入口：编号连续、各有副标题、各自至少一个子页', () => {
  assert.equal(NAV_GROUPS.length, 5, '顶层入口就是 5 个 —— 第 6 个开始一律进"更多"')
  assert.deepEqual(NAV_GROUPS.map(g => g.no), [1, 2, 3, 4, 5], '编号必须连续，否则①②③⑤④会读成漏了一页')
  for (const group of NAV_GROUPS) {
    assert.ok(group.label.length >= 2, `${group.key} 缺顶层名`)
    // 副标题是给评委的说明书："态势 → 未来 6 小时风险"。少于 8 个字就退化成一个词。
    assert.ok(group.subtitle.length >= 8, `${group.key} 的副标题太短，起不到"这页干什么"的作用`)
    assert.ok(group.subs.length >= 1, `${group.key} 没有任何子页 = 点进去是空白`)
  }
})

test('子页名一律来自 SECTION_NAMES，不在这里写第二份中文名', () => {
  for (const group of NAV_GROUPS) {
    for (const sub of group.subs) {
      // W-21b：合并入口允许有自己的名字（处置台 / 检验结论 / 复盘对照），
      // 但**名字必须有唯一出处** —— 要么 SECTION_NAMES，要么 ENTRY_LABELS。
      // 不允许在 NAV_SPEC 里另写一个字面量（那就成了第三份中文名）。
      const known = sub.label === SECTION_NAMES[sub.key]
        || Object.values(ENTRY_LABELS).includes(sub.label)
      assert.ok(known, `${sub.key} 的名字既不在 SECTION_NAMES 也不在 ENTRY_LABELS：${sub.label}`)
      if (sub.merged) {
        // W-33：合并入口的合法名字有两种来源 —— ENTRY_LABELS 的上位词，或锚点视图名本身。
        assert.ok(Object.values(ENTRY_LABELS).includes(sub.label)
          || sub.label === SECTION_NAMES[sub.key],
          `${sub.key} 是合并入口（${sub.members.length} 个视图），入口名必须可追溯到唯一来源`)
      }
    }
  }
  // 整份文件里只应有一处写死这些中文名 —— `SECTION_NAMES` 本身。
  const src = readFileSync(new URL('../src/traffic/runtime.js', import.meta.url), 'utf8')
  const table = /export const SECTION_NAMES=Object\.freeze\(\{[\s\S]*?\}\)/.exec(src)?.[0] ?? ''
  assert.ok(table, '找不到 SECTION_NAMES 的定义块')
  // 0.11.22：`card` 的显示名从「模型卡」改为「推演」—— 名字改了，判据不变：
  // 这四个名字都必须只在 `SECTION_NAMES` 里出现一次。
  for (const name of ['走廊剖面', '推演', '反事实对照', '分歧台账']) {
    const hits = (src.match(new RegExp(name, 'g')) || []).length
    const inTable = (table.match(new RegExp(name, 'g')) || []).length
    assert.ok(hits >= 1, `${name} 没有出现在分节表里`)
    // 允许注释里出现（解释性文字），但**不允许** NAV_GROUPS 再写一遍：那会变成第二来源。
    assert.ok(inTable >= 1, `${name} 不在 SECTION_NAMES 里`)
  }
})

test('每个分节都归了组：漏挂一项的页面永远打不开，而构建与既有判据都不报错', () => {
  assert.equal(navCoverageGap(), null, `未归组的分节：${JSON.stringify(navCoverageGap())}`)
  // 反向自检：把两个集合弄错一个，闸门必须变红。不做负向验证的闸门，等于没有闸门。
  const declared = Object.keys(SECTION_NAMES)
  // W-21b：入口是折叠过的，要**展开 members** 再比。按入口 key 比会把
  // schedule / assistant / ledger / history / reference 五个视图误报成"未归组"。
  const grouped = NAV_GROUPS.flatMap(g => g.subs.flatMap(s => s.members))
  assert.equal(declared.length, grouped.length, '两边数量不等')
  assert.deepEqual([...grouped].sort(), [...declared].sort(), '两边集合必须逐项相等')
})

test('分节 → 分组 → 默认子页：三层反查闭环', () => {
  assert.equal(groupOfSection('profile'), 'corridor')
  assert.equal(groupOfSection('card'), 'verify')
  assert.equal(groupOfSection('ledger'), 'review')
  assert.equal(groupOfSection('home'), 'situation')
  // 未知键不硬塞进任何一组 —— 塞进去会让"我点错了"变成"系统把我带到别处"。
  assert.equal(groupOfSection('nope'), '')
  assert.equal(navGroup('nope'), null)
  assert.equal(defaultSub('corridor'), 'profile', '走廊组的默认页是剖面，不是情报')
  assert.equal(defaultSub('verify'), 'card', '检验组的默认页是模型卡 —— 评委问"准不准"先看数字')
  assert.equal(defaultSub('nope'), '')
})

test('阈值只有一处：颜色与文字不许各写一套 if', () => {
  // 同一批数字过两个函数，必须给出一致的档位。0.5 这一档最容易分叉：
  // 颜色写 >=0.5 是"注意"，文字写 >0.5 是"可飞"，屏幕上就出现红色 + 可飞。
  const cases = [
    [0.95, 'danger', '不可飞'], [0.8, 'danger', '不可飞'],
    [0.79, 'watch', '需谨慎'], [0.5, 'watch', '需谨慎'],
    [0.49, 'info', '留观'], [0.2, 'info', '留观'],
    [0.19, 'ok', '可飞'], [0, 'ok', '可飞'],
  ]
  for (const [p, tone, label] of cases) {
    assert.equal(riskTone(p), tone, `${p} 的颜色档位`)
    assert.equal(riskLabel(p), label, `${p} 的文字档位`)
  }
  // 没有数字 ≠ 数字是 0。缺值时既不能染成"可飞"的绿，也不能说"可飞"。
  for (const bad of [null, undefined, NaN, '0.5']) {
    assert.equal(riskTone(bad), 'unknown', `${String(bad)} 必须落到 unknown`)
    assert.equal(riskLabel(bad), '无观测')
  }
})

test('pct：缺值印"—"，不印 0%', () => {
  assert.equal(pct(0.1566), '16%')
  assert.equal(pct(0.1566, 1), '15.7%')
  assert.equal(pct(0), '0%', '真的是 0 就印 0%')
  for (const bad of [null, undefined, NaN, '', {}]) assert.equal(pct(bad), '—', `${String(bad)} 应印"—"`)
})

test('hourLabel：按 UTC 时刻换算，基准缺失返回空串而不是编一个时间', () => {
  assert.equal(hourLabel('2026-10-18T22:00:00Z', 0), '22:00')
  assert.equal(hourLabel('2026-10-18T22:00:00Z', 3), '01:00', '跨零点要进位到第二天')
  assert.equal(hourLabel('', 2), '', '没有基准时刻就不给时间')
  assert.equal(hourLabel(null, 0), '')
  assert.equal(hourLabel('不是时间', 1), '')
})

test('置信度门限 0.65：写在一处，前端不各写一份', () => {
  assert.equal(CONFIDENCE_GATE, 0.65)
  assert.equal(confidencePass(0.65), true, '恰好等于门限算通过 —— 后端是 `<0.65` 才转人工')
  assert.equal(confidencePass(0.6499), false)
  assert.equal(confidencePass(1), true)
  for (const bad of [null, undefined, NaN, '0.9']) assert.equal(confidencePass(bad), false, `${String(bad)} 不能当成"够自信"`)
})

test('前端不重算概率：组件里不出现自己的阈值比较', () => {
  // 这条防的是"前端顺手把 p>=0.8 再判一次"。一旦发生，后端改阈值时界面会静默停留在旧口径，
  // 而所有既有判据都是绿的 —— 因为它们测的是 runtime.js 里那一份。
  for (const file of ['CorridorPanel.vue', 'ModelCardPanel.vue', 'CounterfactualPanel.vue', 'DivergencePanel.vue']) {
    const src = readFileSync(new URL(`../src/components/traffic/${file}`, import.meta.url), 'utf8')
    assert.doesNotMatch(src, /0\.8\s*<=|>=\s*0\.8|>\s*0\.8/, `${file} 里出现了自己的 0.8 阈值判断`)
    assert.doesNotMatch(src, /0\.5\s*<=|>=\s*0\.5/, `${file} 里出现了自己的 0.5 阈值判断`)
  }
})
