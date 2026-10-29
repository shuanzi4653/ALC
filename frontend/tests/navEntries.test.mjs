/**
 * W-21b（0.11.4）：导航入口 13 → 8 的判据。
 *
 * 这一组钉的是**折叠本身**，不是折叠后的某个字面量：
 *   · 入口总数 = 8（多一个就说明有人绕过了入口层直接挂视图）
 *   · 每个视图**恰好**属于一个入口（重复归属会让高亮和 tab 条各说各话）
 *   · 合并入口必须有自己的名字，单视图入口必须没有
 *   · 被折叠的视图仍然能从入口里反查到（`entryOf` 双向闭环）
 *
 * 反面对照：把 `navEntryCount` 的目标值改成 6，这一组必须整体变红 ——
 * 一条不会红的判据，只说明它没有被跑到。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  NAV_GROUPS, SECTION_NAMES, ENTRY_LABELS, HIDDEN_SECTIONS,
  navEntryCount, entryOf, entryTabs, groupOfSection,
} from '../src/traffic/runtime.js'

const ENTRIES = NAV_GROUPS.flatMap((group) => group.subs.map((sub) => ({ ...sub, group })))

test('导航入口是 8 个（W-21b 的目标），而视图仍是 14 个', () => {
  assert.equal(navEntryCount(), 8,
    `入口数变成 ${navEntryCount()}：新增页面必须挂进已有入口或明确新增一个入口，不允许回到"一页一个按钮"`)
  assert.equal(Object.keys(SECTION_NAMES).length, 14, '视图总数不该被改（折叠的是导航，不是功能）')
})

test('每个视图恰好属于一个入口，且入口的锚点必须在自己的 members 里', () => {
  const seen = new Map()
  for (const entry of ENTRIES) {
    assert.ok(entry.members.length >= 1, `${entry.key} 没有任何成员视图`)
    assert.ok(entry.members.includes(entry.key),
      `${entry.key} 的锚点不在 members 里 —— 点它会打不开`)
    for (const member of entry.members) {
      assert.ok(member in SECTION_NAMES, `${member} 不是一个已声明的分节`)
      assert.ok(!seen.has(member),
        `${member} 同时属于 ${seen.get(member)} 与 ${entry.key}：高亮与 tab 条会各说各话`)
      seen.set(member, entry.key)
    }
  }
  assert.equal(seen.size, Object.keys(SECTION_NAMES).length, '有视图没有归属任何入口')
})

test('合并入口有自己的名字，单视图入口没有', () => {
  for (const entry of ENTRIES) {
    const hasOwnName = Object.values(ENTRY_LABELS).includes(entry.label)
    if (entry.merged) {
      // 0.11.5（W-33）：合并入口的名字有两种合法来源 ——
      //   ① `ENTRY_LABELS` 里另起一个上位词（检验结论 / 复盘对照）；
      //   ② 就是锚点视图名（事件处置台）：第一个 tab 与入口同名是导航的常规做法，
      //      "你现在在这一层"比"再想一个词"更省读者的力气。
      // 真正要防的是**第三种词**：既不在 SECTION_NAMES 也不在 ENTRY_LABELS 的名字，
      // 那会让同一个地方出现三个叫法。
      assert.ok(hasOwnName || entry.label === SECTION_NAMES[entry.key],
        `${entry.key} 的入口名来历不明：${entry.label}`)
      // 入口名不得与它自己 members 里**其它**视图重名，否则导航上一行出现两个同样的词
      for (const member of entry.members) {
        if (member === entry.key) continue
        assert.ok(entry.label !== SECTION_NAMES[member],
          `${entry.key} 的入口名与成员 ${member} 重名：${entry.label}`)
      }
    } else {
      assert.ok(!hasOwnName, `${entry.key} 是单视图入口，不该有独立入口名`)
      assert.equal(entry.label, SECTION_NAMES[entry.key])
    }
  }
})

test('折叠掉的视图仍然能反查到入口（双向闭环）', () => {
  // 下钻（drillTarget）给的是**视图** key：落到 schedule 时导航必须亮起「处置台」，
  // 并且 tab 条要停在「调度台账」。这条闭环断了，表现是"点下钻之后导航整排熄灭"。
  for (const key of Object.keys(SECTION_NAMES)) {
    const entry = entryOf(key)
    assert.ok(entry, `${key} 反查不到入口`)
    // `entryOf` 只回入口本身（不带 group），所以组要另外查 ——
    // 让 `entryOf` 顺便挂一个 group 引用会让"入口"与"分组"两套身份混在一个对象上。
    const owner = NAV_GROUPS.find((group) => group.subs.includes(entry))
    assert.ok(owner, `${entry.key} 找不到所属分组`)
    assert.equal(groupOfSection(key), owner.key,
      `${key} 的分组与它所属入口的分组不一致`)
  }
  assert.equal(entryOf('schedule').key, 'alerts')
  assert.equal(entryOf('assistant').key, 'alerts')
  // 0.11.22：台账与复盘对照并入推演，入口只剩「日志」（history）。
  assert.equal(entryOf('ledger').key, 'history')
  assert.equal(entryOf('reference').key, 'card')
})

test('tab 条：三个合并入口的视图数正确，且隐藏视图与锚点都不出现', () => {
  const labels = (key) => entryTabs(key).map((tab) => tab.label)
  // W-33：'预警中心' → '事件处置台'（入口名与页面同名）
  // 0.11.10：锚点视图不再进 tab 条 —— 否则「处置」下面并排两个同名按钮。
  // 判据从"含锚点"改为"不含锚点"，语义更强：任何入口的 tab 条里，
  // 都不许出现与入口同名的项（那正是重复按钮的成因）。
  assert.deepEqual(labels('alerts'), ['调度台账', '大模型取证'])
  assert.deepEqual(labels('card'), ['口径与来源'])
  // 0.11.22：`counterfactual` 入口已不存在 —— 它和 `ledger` 都挂到「日志」下面，
  // 且都在 `HIDDEN_SECTIONS` 里，所以日志入口的 tab 条应当是空的（单视图外观）。
  assert.deepEqual(labels('history'), [])
  assert.ok(HIDDEN_SECTIONS.has('counterfactual') && HIDDEN_SECTIONS.has('ledger'),
    '复盘对照与分歧台账必须仍能被过滤掉，否则导航里会冒出两个只剩深链的页')
  for (const key of ['alerts', 'card', 'history']) {
    const entry = entryOf(key)
    assert.ok(!labels(key).includes(entry.label),
      `${key} 的 tab 条里又出现了与入口同名的项（${entry.label}）`)
  }
  // 单视图入口没有 tab 条 —— 有一行空 tab 比没有更让人困惑
  assert.deepEqual(labels('home'), [])
  assert.deepEqual(labels('profile'), [])
  // mechanism 挂在「检验结论」下，但它是"可达但不并排"，不该出现在 tab 里
  assert.ok(HIDDEN_SECTIONS.has('mechanism'))
  assert.ok(!labels('card').includes(SECTION_NAMES.mechanism),
    '算法机理不该出现在「检验结论」的 tab 条里')
})
