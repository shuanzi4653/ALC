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
  navEntryCount, entryOf, entryTabs, groupOfSection, sectionFromHash, SECTION_HASHES,
} from '../src/traffic/runtime.js'

const ENTRIES = NAV_GROUPS.flatMap((group) => group.subs.map((sub) => ({ ...sub, group })))

test('导航入口是 7 个（V1.0.5 合并后），而视图是 11 个', () => {
  // V1.0.5：8 → 7、15 → 14（两处都是合并）；V1.1.0 下线 mechanism → 13。
  //   · 「运行情报」并入「气象监测」（同一屏两张表，没必要两个入口）；
  //   · 走廊组只剩「走廊剖面」（运行情报搬走后它本来就只有一项）。
  // 保留这条断言的意义：以后每加一页，必须想清楚它挂哪个入口，
  // 而不是顺手再加一个左侧按钮。
  assert.equal(navEntryCount(), 7,
    `入口数变成 ${navEntryCount()}：新增页面必须挂进已有入口或明确新增一个入口，不允许回到"一页一个按钮"`)
  assert.equal(Object.keys(SECTION_NAMES).length, 11,
    '视图总数：V1.1.0 下线 mechanism（13）；V1.1.1 下线 counterfactual 与 ledger（11）')
})

test('被删掉的分节必须留旧 hash 映射，否则老链接会静默跳首页', () => {
  // 这是 V1.0.5 删 briefing 时踩到的坑：`sectionFromHash` 查不到就回落 `home`，
  // 表现为"别人给的链接打开是首页"，比 404 更像页面坏了。
  const legacy = sectionFromHash('#/corridor/briefing')
  assert.equal(legacy, 'weather', '旧地址应落到气象监测，而不是首页')
  assert.ok(!('briefing' in SECTION_NAMES), 'briefing 已并入 weather，不该还留在分节表里')
})

test('并入推演的两个页与 0.10.1 历史页：旧链接都必须落到 card，而不是首页', () => {
  // 这条是 V1.1.1 的教训。V1.1.0 删了 mechanism 的分节，却**没有**登记旧 hash，
  // 于是 `#/model/mechanism` 实测落到 `#/situation/home` —— 用户以为页面坏了；
  // 而 `#/compare/counterfactual`（反事实）当时连分节都还在，独立页照样打开，
  // 等于"声明并入了推演、实际给它留了两个入口"，两个入口还各有一套取数。
  //
  // 判据写成"等于 card"，不是"不等于 home"：落到 weather 或 reference 同样是错的，
  // 只是错得不那么显眼。
  for (const legacyHash of ['#/compare/counterfactual', '#/compare/ledger', '#/model/mechanism']) {
    assert.equal(sectionFromHash(legacyHash), 'card', `${legacyHash} 必须落到推演页`)
  }
  // 反向：这三个 hash 不许再出现在 SECTION_HASHES 里 —— 一旦有人加回去，
  // 独立页就会复活，而 sectionFromHash 会先命中 SECTION_HASHES 那个分支。
  for (const dead of ['compare/counterfactual', 'compare/ledger', 'model/mechanism']) {
    assert.ok(!Object.values(SECTION_HASHES).includes(dead), `${dead} 又出现在路由表里了`)
  }
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
  // V1.1.1：`ledger` / `counterfactual` 已不是分节（并入推演的 ⑦⑧ 段），
  // 不再有"藏在日志组下面、只能深链打开"的入口 —— 旧链接由 LEGACY_SECTION_HASHES 接走。
  assert.equal(entryOf('ledger'), null, 'ledger 不再是分节，不该还能反查到入口')
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
  // V1.1.1：日志入口下只剩 history 一个视图 → tab 条为空（单视图外观）。
  assert.deepEqual(labels('history'), [])
  // 反过来钉住"它们真的没了"：这两个 key 既不在分节表、也不在导航里。
  // 只断言"不在 HIDDEN 里"是不够的 —— 全删之后 HIDDEN 里当然也没有。
  assert.ok(!('counterfactual' in SECTION_NAMES), 'counterfactual 已并入推演 ⑦ 段，不该还是分节')
  assert.ok(!('ledger' in SECTION_NAMES), 'ledger 已并入推演 ⑧ 段，不该还是分节')
  assert.ok(!NAV_GROUPS.some((g) => g.subs.some((s) => s.members.includes('counterfactual'))),
    'counterfactual 又出现在导航的 members 里')
  for (const key of ['alerts', 'card', 'history']) {
    const entry = entryOf(key)
    assert.ok(!labels(key).includes(entry.label),
      `${key} 的 tab 条里又出现了与入口同名的项（${entry.label}）`)
  }
  // 单视图入口没有 tab 条 —— 有一行空 tab 比没有更让人困惑
  assert.deepEqual(labels('home'), [])
  assert.deepEqual(labels('profile'), [])
  // V1.1.0：mechanism 整页下线；V1.1.1：counterfactual 与 ledger 随之下线。
  // 三者都不是分节，所以 `SECTION_NAMES.mechanism` 本身就是 undefined ——
  // tab 条不可能含它。真正要守的是"没有残留的中文名冒充分节名"。
  assert.ok(!('mechanism' in SECTION_NAMES), 'mechanism 已下线，不该还是分节')
  assert.ok(!labels('card').some((l) => /算法机理/.test(l)),
    '算法机理不该出现在「推演」的 tab 条里')
})
