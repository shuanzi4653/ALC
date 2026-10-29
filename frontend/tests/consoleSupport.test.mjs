import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {SOURCE_BADGES,sourceBadge,caliberBlocks,weatherDataTypeLabel,legalFrameworkText,
  GLOSSARY,glossaryGroups,glossaryLookup,
  DENSITY_TIERS,densityTier,densityPolicy,
  replayMinuteOf,replayMarks,replaySlice,replayBuckets,receiptText,
  timelineIntel,airspaceIntel,drillTarget,drillable,DRILL_TARGETS,SECTION_NAMES,sectionName,
  navCoverageGap,radarRuleBlock} from '../src/traffic/runtime.js'

// 运行台的四项配套（0.9.26 / P1-1 · P1-3 · P1-5 · P1-6 · P2-2 · P2-3 · P2-4 · P2-6）。
//
// 这一批的共同风险是**它们都不产生新数字**，所以错了不会让任何既有断言变红：
//
//   ① 角标写一个不存在的键 → `sourceBadge` 静默回落到「数据不可用」，页面看起来
//      只是"这一类没有来源"，而不是"我写错了"；
//   ② 免责声明若在页面里**另写一遍**，它就会与后端 `rules.enforcementNote` 慢慢分叉，
//      而分叉之后没有任何判据会发现两处口径不同；
//   ③ 缺值若回落成 `0` 或 `''`，"没有数据"会读成"数据是零"（M67）；
//   ④ 回放的桶边界若写成闭区间，端点那一条会在两处算出两个分段数；
//   ⑤ 下钻目标若指向一个不存在的分节，点击就是**静默无反应**。
//
// 下面每条断言都对着上面五条之一。

// 夹具必须照抄**真实载荷的形状**，否则它测的只是"前端想象的后端"。
//
// 第十轮实测就栽在这上面：`radarRuleBlock` 读的是 `radarAvoidance.rule`，而后端
// `service._radar_rule_block()` 是 `**_radar_rule_block()` 展开进 `radarAvoidance` 的，
// 阈值**平铺在顶层**。旧夹具写的正是 `{rule:{...}}` —— 前端想象的那一份 —— 于是
// 「算法机理」页的判据栏整整一轮印着"本计划未发布分级规则"，而计划每一轮都发布了。
// 下面两个夹具各司其职：`PLAN` 用**真实形状**，`LEGACY_PLAN` 保留嵌套形状以证明兼容。
const PLAN={
  baseTime:'2026-09-14T10:00:00Z',scenario:'live',seed:42,planRevision:3,
  version:'0.9.26-beta',fingerprint:'0123456789abcdef',
  stats:{noAltitudeStacking:true},
  radarAvoidance:{mode:'virtual',sweepSlots:49,sweepStrideMinutes:10,
    tiers:'two-tier',bandFloorDbz:15,convectiveDbz:35,strongDbz:45,coreInsetM:9000,penetrationM:250},
  weatherSnapshot:{dataType:'MODEL_ESTIMATE',provider:'open-meteo',validAt:'2026-09-14T10:00:00Z'},
}

// 旧形状（`rule` 子对象）：只作为**兼容性证据**存在，不代表现在的后端。
const LEGACY_PLAN={...PLAN,
  radarAvoidance:{mode:'virtual',sweepSlots:49,sweepStrideMinutes:10,
    rule:{tiers:'two-tier',bandFloorDbz:15,convectiveDbz:35,strongDbz:45,coreInsetM:9000,penetrationM:250}},
}

// `staticAirspace` **只在 `/traffic/network` 上发**，会话载荷里没有它。
// 见 `service.static_airspace()` 的 docstring：「Shipped once with ``GET /traffic/network``
// rather than inside the weather frame」。把它塞进 `PLAN` 就又把两条通道混成一条了。
const NETWORK={
  staticAirspace:{
    rules:{catalogVersion:'northeast-fixed-airspace-v1',dataRetrievedAt:'2026-09-16',
      legalFramework:{instrument:'《无人驾驶航空器飞行管理暂行条例》',clause:'第十九条'},
      disclaimer:'本目录不是航行情报，不构成飞行许可。',
      enforcementNote:'固定管制区与气象派生风险区是两套东西。'},
    status:{sites:12,withGeometry:9,prohibited:4,approvalRequired:5,registered:3},
    zones:[{id:'z1'}]},
}

// ---- 分级规则：读错路径不许再静默弃权 --------------------------------------
//
// 这一条是第十轮实测缺陷的**回归判据**。它的价值不在于"算得对"，而在于
// **它用的是真实载荷形状** —— 换成旧夹具（`{rule:{...}}`），下面这条断言会照样绿。

test('the radar rule block reads the flat shape the backend actually publishes',()=>{
  const flat=radarRuleBlock(PLAN)
  assert.ok(flat,'真实载荷（阈值平铺）必须读出规则块')
  assert.equal(flat.tiers,'two-tier')
  assert.equal(flat.bandFloorDbz,15)
  assert.equal(flat.convectiveDbz,35)
  assert.equal(flat.strongDbz,45)
  assert.equal(flat.coreInsetM,9000)
  assert.equal(flat.penetrationM,250)
  // 顶层优先：两种形状同时出现时以真实形状为准。
  const both=radarRuleBlock({...PLAN,radarAvoidance:{...PLAN.radarAvoidance,
    rule:{tiers:'legacy',bandFloorDbz:99}}})
  assert.equal(both.bandFloorDbz,15,'顶层必须覆盖 rule 子对象')
  // 兼容旧形状（夹具/旧载荷）。
  assert.equal(radarRuleBlock(LEGACY_PLAN).penetrationM,250)
  // 确实没有阈值时才弃权 —— 而"确实没有"与"路径读错"从此可区分。
  assert.equal(radarRuleBlock({radarAvoidance:{mode:'virtual'}}),null)
  assert.equal(radarRuleBlock(null),null)
  assert.equal(radarRuleBlock({radarAvoidance:null}),null)
})

test('a threshold of zero is a value, a missing threshold is not zero',()=>{
  // `Number(null)===0` 的老坑：把"没发布"读成"发布了一个 0 dBZ 的阈值"，
  // 界面就会印出「无回波 < 0 dBZ」这种看着精确、实则凭空捏造的读数。
  const only=radarRuleBlock({radarAvoidance:{tiers:'two-tier',convectiveDbz:35}})
  assert.equal(only.convectiveDbz,35)
  assert.equal(only.bandFloorDbz,null,'未发布的阈值必须是 null，不是 0')
  // 一个真值为 0 的阈值仍然是"发布了"。
  const zero=radarRuleBlock({radarAvoidance:{tiers:'two-tier',bandFloorDbz:0}})
  assert.ok(zero,'0 是真值，不能当成缺失')
  assert.equal(zero.bandFloorDbz,0)
})

// ---- P1-5 来源角标：写错的键必须能被测出来 --------------------------------

test('every badge key an operator reads is one the map actually defines',()=>{
  // `sourceBadge` 对未知键**有意**回落到 ABSENT（页面宁可说"不可用"也不崩）。
  // 代价是拼错的键不会报错 —— 所以这里反向钉住：本节会用到的键都在表里。
  for(const key of ['SIM','PUBLIC','DERIVED','OFFICIAL','MANUAL','ABSENT']){
    assert.ok(SOURCE_BADGES[key],`SOURCE_BADGES 缺少 ${key}`)
    assert.equal(sourceBadge(key).key,key)
  }
  assert.equal(sourceBadge('NOPE').key,'ABSENT','未知键必须回落到 ABSENT 而不是抛错')
  assert.equal(sourceBadge(undefined).key,'ABSENT')
})

test('a block that cannot be sourced still exists, and says absent rather than zero',()=>{
  // 计划与气象都缺失（构建中 / 来源失败）。块**不消失** —— 一页"没有任何来源说明"
  // 会被读成"没有问题"，而那是比"显示不可用"更坏的读法。
  const blocks=caliberBlocks(null,null,null)
  assert.equal(blocks.length,7)
  for(const block of blocks){
    assert.ok(block.title&&block.intro,'块必须有标题与导语')
    assert.ok(block.boundary&&block.boundary.length>10,'块必须说清"它不意味着什么"')
    assert.ok(block.rows.length,'块不能空')
    assert.ok(SOURCE_BADGES[block.source.key],'块的角标必须来自来源表')
  }
  const weather=blocks.find(b=>b.key==='weather')
  assert.equal(weather.source.key,'ABSENT')
  const radar=blocks.find(b=>b.key==='radar')
  // **不能是 `0 dBZ` 或空串**：那是两种不同的谎。
  assert.ok(radar.rows.every(r=>r.value==='absent'),'计划缺失时雷达口径必须逐行为 absent')
})

test('the airspace block reads the catalogue off the network payload, not the plan',()=>{
  // 第十轮实测缺陷之二：`staticAirspace` 只在 `/traffic/network` 上发，而这里原来
  // 读的是会话载荷。屏幕上那两块如实写着「未取得」—— **读错来源与来源真的没有，
  // 在界面上长得一模一样**，所以只有"把网络载荷传进来后必须读出真值"这条判据有牙齿。
  const fromNetwork=caliberBlocks(PLAN,null,NETWORK)
  const airspace=fromNetwork.find(b=>b.key==='airspace')
  assert.equal(airspace.source.key,'OFFICIAL')
  assert.equal(airspace.rows.find(r=>r.label==='登记站点').value,'12 处')
  assert.equal(airspace.rows.find(r=>r.label==='已有几何').value,'9 处')
  assert.equal(airspace.rows.find(r=>r.label==='禁止进入 / 需审批').value,'4 / 5 处')
  assert.equal(airspace.rows.find(r=>r.label==='法规依据').value,
    '《无人驾驶航空器飞行管理暂行条例》 · 第十九条')
  assert.equal(airspace.rows.find(r=>r.label==='目录版本 / 取回时刻').value,
    'northeast-fixed-airspace-v1 · 2026-09-16')
  // 会话载荷里即使放了同名键，也**不以它为准** —— 否则两条通道又会悄悄合流。
  const polluted={...PLAN,staticAirspace:{rules:{disclaimer:'伪造'}}}
  assert.equal(caliberBlocks(polluted,null,NETWORK).find(b=>b.key==='airspace')
    .rows.find(r=>r.label==='发布方声明').value,'本目录不是航行情报，不构成飞行许可。')
  // 网络载荷缺席时才写 absent（源不发布 → 弃权，M67）。
  const bare=caliberBlocks(PLAN,null,null).find(b=>b.key==='airspace')
  assert.equal(bare.rows.find(r=>r.label==='登记站点').value,'absent')
})

test('the airspace boundary quotes the catalogue instead of restating it',()=>{
  // 「免责声明收敛」的全部意义在这里：界面上**引用**后端那句唯一的声明，而不是
  // 第三处重写一遍。重写的那一刻起，两处就开始分叉，而分叉没有判据能发现。
  const airspace=caliberBlocks(PLAN,null,NETWORK).find(b=>b.key==='airspace')
  assert.equal(airspace.boundary,NETWORK.staticAirspace.rules.enforcementNote)
  const disclaimer=airspace.rows.find(r=>r.label==='发布方声明')
  assert.equal(disclaimer.value,NETWORK.staticAirspace.rules.disclaimer)
  // 后端没有那句声明时，落回本页写定的兜底句 —— 而**不是**印出字面量 `absent`。
  // （`text(x) || fallback` 永远不会执行兜底：`text()` 取不到值时返回真值 `'absent'`。）
  const fallback=caliberBlocks(PLAN,null,{staticAirspace:{rules:{}}}).find(b=>b.key==='airspace')
  assert.notEqual(fallback.boundary,'absent')
  assert.ok(fallback.boundary.length>10)
})

test('a structured legal framework never renders as [object Object]',()=>{
  assert.equal(legalFrameworkText({instrument:'X 法',clause:'第十九条'}),'X 法 · 第十九条')
  assert.equal(legalFrameworkText({instrument:'X 法'}),'X 法')
  assert.equal(legalFrameworkText('  Y 法  '),'Y 法')
  assert.equal(legalFrameworkText(null),'absent')
  assert.equal(legalFrameworkText({}),'absent')
  // 数据类型同理：未标注就写"来源未标注"，**不猜**成"估算"。
  assert.equal(weatherDataTypeLabel('MODEL_ESTIMATE'),'公开模型估算')
  assert.equal(weatherDataTypeLabel('SOMETHING_NEW'),'absent')
  assert.equal(weatherDataTypeLabel(null),'absent')
})

// ---- P1-6 术语 -------------------------------------------------------------

test('the glossary loses no term when it is grouped',()=>{
  const groups=glossaryGroups()
  const counted=groups.reduce((sum,group)=>sum+group.terms.length,0)
  assert.equal(counted,GLOSSARY.length,'分组不能丢词或重复计入')
  assert.ok(groups.length>=4,'至少四组')
  for(const entry of GLOSSARY){
    assert.ok(entry.term&&entry.plain&&entry.full,`${entry.term} 缺释义`)
    // 「同一件事两句话」——两句话必须真的是两句。写成一样就等于这一项没做。
    assert.notEqual(entry.plain,entry.full,`${entry.term} 的通俗与专业释义相同`)
  }
})

test('looking up a term that does not exist returns nothing, not a made-up answer',()=>{
  assert.equal(glossaryLookup('dBZ').term,'dBZ')
  assert.equal(glossaryLookup('  dbz  ').term,'dBZ','大小写与空白不敏感')
  assert.equal(glossaryLookup('量子纠缠'),null)
  assert.equal(glossaryLookup(''),null)
})

// ---- P2-4 三档信息密度 ------------------------------------------------------

test('an unknown density tier falls back to the fullest one',()=>{
  assert.deepEqual(DENSITY_TIERS.map(t=>t.key),['duty','command','demo'])
  const keys=DENSITY_TIERS.map(t=>t.key)
  assert.equal(new Set(keys).size,keys.length,'档位键唯一')
  for(const tier of DENSITY_TIERS)assert.equal(densityTier(tier.key).key,tier.key)
  // 回落方向是**宁多不少**：少给值班员一个原始字段，比多给演示者一行数字代价高。
  assert.equal(densityTier('nope').key,'duty')
  assert.deepEqual(densityPolicy(undefined),densityPolicy('duty'))
})

test('the demo tier is defined by two switch positions, not by a name',()=>{
  // 演示档的两条定义特征：术语释义默认展开、工程参数隐藏。改掉任何一条，
  // 「演示模式」这个词就与它实际做的事脱钩了。
  const demo=densityPolicy('demo')
  assert.equal(demo.glossary,true)
  assert.equal(demo.engineering,false)
  assert.equal(densityPolicy('duty').engineering,true)
  assert.equal(densityPolicy('command').raw,false)
  // 任何一档都不允许把内容真正拿掉后再声称"只是折叠"—— ledger 在两档里都要在。
  assert.equal(densityPolicy('duty').ledger,true)
  assert.equal(densityPolicy('command').ledger,true)
})

// ---- P2-6 演示模式 · 2026-10-17 收缩移除 ------------------------------------
//
// 这一节原有两条用例：`demoAdvance` 到末端回卷、`demoStart` 的副本语义。
// 它们守的两个导出（DEMO_SETUP / demoStart / demoAdvance）已随「演示模式」按钮
// 一起移除 —— 按钮与「信息密度」下拉框做的是同一件事的两半，两个入口会让
// "我现在是哪一档"取决于用户先进了哪个门。
//
// **没有删除的是「演示」这一档本身**（见上一节的 densityPolicy('demo')）：
// 收缩的是那个按钮，不是档位。留一条注释而不是整段删掉，是因为"为什么这里曾经
// 有两条 demo 用例"是后来者最可能重新踩的坑。

// ---- P2-3 复盘回放 ---------------------------------------------------------

const JOURNAL=[
  {id:'1',minute:12,kind:'MANUAL',at:'2026-09-14T10:12:00Z'},
  {id:'2',minute:60,kind:'SYSTEM',at:'2026-09-14T11:00:00Z'},
  {id:'3',minute:null,kind:'SOURCE',at:'2026-09-14T10:30:00Z'},
  {id:'4',minute:180,kind:'MANUAL',at:'2026-09-14T13:00:00Z'},
]

test('a record without a minute is not pinned to any one moment',()=>{
  // 气象通道切换影响的是**整段时间**。把它钉在某一分钟上，读者会以为"只有那一刻切了"。
  const marks=replayMarks(JOURNAL)
  assert.deepEqual(marks.marks.map(m=>m.minute),[12,60,180])
  assert.equal(marks.always.length,1)
  assert.equal(marks.always[0].id,'3')
  assert.equal(marks.count,JOURNAL.length)
  assert.deepEqual(marks.marks[1].kinds,['SYSTEM'])
})

test('the three-way split accounts for every stamped row exactly once',()=>{
  // 不变式：已发生 + 就在这一刻 + 还没发生 == 带分钟的条目总数。
  // 只断言"每个数看着合理"是测不出漏算的。
  for(const minute of [0,12,59,60,180,480]){
    const slice=replaySlice(JOURNAL,minute)
    const stamped=JOURNAL.filter(r=>replayMinuteOf(r)!==null).length
    assert.equal(slice.total,stamped,`minute=${minute}`)
    assert.equal(slice.past.length+slice.here.length+slice.upcoming.length,stamped)
    assert.equal(slice.always.length,1,'没有分钟的条目任何时候都在视野里')
  }
  const atSixty=replaySlice(JOURNAL,60)
  assert.deepEqual(atSixty.here.map(r=>r.id),['2'],'恰好落在这一刻的单独一格')
  assert.deepEqual(atSixty.upcoming.map(r=>r.id),['4'])
})

test('bucket boundaries are left-closed, so a minute belongs to exactly one bucket',()=>{
  // 端点归属含糊会让同一份日志在两处读出两个分段计数 —— 界面上表现为"数字对不上"。
  const {buckets}=replayBuckets(JOURNAL,{span:480,step:60})
  assert.equal(buckets.length,8)
  assert.equal(buckets[0].from,0)
  assert.equal(buckets[0].to,60)
  const counted=buckets.reduce((sum,b)=>sum+b.count,0)
  assert.equal(counted,JOURNAL.filter(r=>replayMinuteOf(r)!==null).length)
  // minute=60 必须落在第 1 桶（[60,120)），不是第 0 桶（[0,60)）。
  assert.deepEqual(buckets[1].rows.map(r=>r.id),['2'])
  assert.equal(buckets[0].count,1)
  assert.equal(buckets[3].count,1)
})

// ---- P2-2 处置回执 ---------------------------------------------------------

test('a receipt lists all five facts, and names the one that is missing',()=>{
  const full=receiptText({eventKey:'r1:WEATHER_BLOCKED:true',name:'受气象影响',
    action:'HANDLED',actionLabel:'标记已处置',actor:'值班员甲',detail:'已通知塔台',
    at:'2026-09-14T10:30:00Z',minute:30},{sessionId:'abcdef0123456789'})
  for(const label of ['对象：','时刻：','动作：','人物：','明细：','计划：'])assert.ok(full.includes(label),label)
  assert.ok(full.includes('T+30 分'))
  assert.ok(full.includes('abcdef012345'))
  // 缺项**写出来**而不是省略 —— 交班时少了时刻的回执，读的人不会发现少了。
  const thin=receiptText({eventKey:'x',action:'HANDLED'})
  assert.ok(thin.includes('人物：absent'))
  assert.ok(thin.includes('明细：absent'))
  assert.equal(receiptText(null),'')
})

// ---- P1-1 情报补维 ---------------------------------------------------------

test('timeline intel counts only operations that carry a minute',()=>{
  const rows=timelineIntel(PLAN,null,JOURNAL)
  const ops=rows.find(r=>r.key==='ops')
  assert.equal(ops.value,'2 次 · 最早 T+12 分','通道切换不计入时刻')
  const sweep=rows.find(r=>r.key==='sweep')
  assert.equal(sweep.value,'480 分钟（49 点 × 10 分）')
  const scene=rows.find(r=>r.key==='scene')
  assert.equal(scene.value,PLAN.baseTime)
  // 没有雷达几何时窗口写 absent，而不是 0 分钟。
  const bare=timelineIntel({baseTime:'x'},null,null).find(r=>r.key==='sweep')
  assert.equal(bare.value,'absent')
  assert.equal(bare.source.key,'ABSENT')
})

test('airspace intel keeps registered count separate from drawn count',()=>{
  const rows=airspaceIntel(PLAN,[{fromPad:'A',toPad:'B',staticAirspace:{zones:1,prohibited:1}},
    {fromPad:'A',toPad:'B',staticAirspace:{zones:0,prohibited:0}}],{cells:[{},{}]},NETWORK)
  const official=rows.find(r=>r.key==='official')
  assert.equal(official.value,'登记 12 处 · 有几何 9 处','差额就是"未取得公开定量范围"，不能被合成一个数')
  assert.equal(rows.find(r=>r.key==='derived').value,'2 个')
  assert.equal(rows.find(r=>r.key==='pads').value,'2 个')
  assert.equal(rows.find(r=>r.key==='corridors').value,'1 条')
  assert.equal(rows.find(r=>r.key==='crossings').value,'1 班（其中触及禁入 1 班）')
  // 空域目录随 `network` 下发；不传就是"源不发布"，**不是**"目录为空"。
  assert.equal(rows.find(r=>r.key==='catalog').value,NETWORK.staticAirspace.rules.catalogVersion)
  assert.equal(airspaceIntel(PLAN,[],null,null).find(r=>r.key==='catalog').value,'absent')
  // 没有班次穿越 vs 没有班次，是两件事。
  assert.equal(airspaceIntel(PLAN,null,null,NETWORK).find(r=>r.key==='crossings').value,'absent')
  assert.equal(airspaceIntel(PLAN,[],null,NETWORK).find(r=>r.key==='crossings').value,'0 班')
})

// ---- P1-3 结论下钻 ---------------------------------------------------------

test('every KPI that can be drilled actually lands on a section that exists',()=>{
  // 下钻目标写错一个字母，点击就是**静默无反应** —— 构建不会报错、页面不会提示。
  //
  // 这一条同时钉住**分节表本身**：写死一份期望清单，再要求它逐字等于唯一来源。
  // 只写 `Object.keys(SECTION_NAMES)` 是测不出"少了一个分节"的 —— 少一项之后
  // 剩下的仍然自洽。写死清单则会在删掉一个分节时立刻变红。
  const SECTIONS=Object.keys(SECTION_NAMES)
  assert.deepEqual(SECTIONS,
    ['home','overview','briefing','schedule','alerts','weather','mechanism','reference','assistant','history',
     'profile','card','counterfactual','ledger'],
    '分节清单变了：新增/删除分节必须同时改这里、drillTarget 的落点、NAV_GROUPS 的归组、与 docs/NAMING.md §1')
  // 0.11.1（Beta）新增四项（手册 §10）：走廊剖面 / 模型卡 / 反事实对照 / 分歧台账。
  // 这里改成"清单 + 归组同时验"：只改清单不归组，那四页永远不会出现在导航上，
  // 而"少了一个入口"不会让任何既有判据变红。`navCoverageGap()` 就是这条网。
  assert.equal(navCoverageGap(), null,
    '每个分节都必须挂在 NAV_GROUPS 的某一组下，否则那个页面永远打不开')
  // 0.11.4（W-21a）：`alerts` 是结论条主按钮的落点（「处置这 N 条 →」）。
  // 它不是 KPI 格，但同样必须落到存在的分节 —— 主按钮指错，点击就是无声无息。
  const KPIS=['accepted','detour','delay','weather','risk','sweep','ai','alerts']
  // `model` **不是** KPI 格：它是首页 KPI 条下面那条「成效对照」入口
  // （`HomeStage.vue::hs-model-links`，0.10.1（Beta）新增）。它同样必须落到存在的分节，
  // 但把它混进 KPIS 会让"哪几格是 KPI"失去唯一定义 —— 首页一屏将来会多出第三个列表，
  // 然后"哪些能下钻"就再也说不清了。所以两类分开列、并集对齐唯一来源。
  const ENTRY_LINKS=['model']
  for(const key of [...KPIS,...ENTRY_LINKS]){
    assert.ok(drillable(key),`KPI ${key} 应当可下钻`)
    const target=drillTarget(key)
    assert.ok(SECTIONS.includes(target.section),`${key} 指向了不存在的分节 ${target.section}`)
    assert.ok(target.hint.length>6,`${key} 必须说明再点一次会看到什么`)
  }
  // 上面那份清单是**写死的**，所以它会在新增一格时立刻变红；这一条则保证两边的
  // 集合相等 —— 写死清单只防"少写了"，不防"多写了却没人测"。
  assert.deepEqual([...KPIS,...ENTRY_LINKS].sort(),Object.keys(DRILL_TARGETS).sort(),
    '可下钻的入口清单变了：每一格都必须在这里被覆盖，否则"点了没反应"不会被任何判据发现')
  assert.equal(drillable('不存在的指标'),false)
  assert.equal(drillTarget('不存在的指标').section,'overview','未知指标回落总览，而不是无反应')
  // 落点的显示名也要能查出来：下钻提示里写的是中文名，查不到就会印出"未命名分节"。
  for(const key of SECTIONS)assert.notEqual(sectionName(key),'未命名分节',`${key} 缺少显示名`)
  assert.equal(sectionName('nope'),'未命名分节')
})

// ---- 三次点击的**路径**（§十七②） -------------------------------------------
//
// 上面那条判据只钉住"落点分节存在" —— 那等于只验入口不验路径。分节存在、而里面那句
// 承诺找不到，症状与"下钻根本没生效"完全同形；而这条验收写的恰恰是"三次点击到达原始
// 依据"。所以下面把第 2、3 次点击也钉住：落地页的**那一段**模板里必须有承诺对应的
// 标题与锚点。
//
// 「那一段」的取法是这条判据的关键。在整份文件里搜 `data-alert-key` 会通过 —— 它
// 也可能出现在别的分节里，于是一个"把气象态势放进预警中心"的错位不会被发现。
// 所以先把控制台模板按分节切成段，再只在目标那一段里找。切段还有一个坑：
// `view==='history'` 在脚本里也出现过一次（`loadJournal` 的触发条件），从整份文件
// `indexOf` 会切到脚本里去 —— 所以只取 `<template>` 块。
const CONSOLE_SRC=readFileSync(new URL('../src/components/OperationsConsole.vue',import.meta.url),'utf8')
const WORKBENCH_SRC=readFileSync(new URL('../src/components/TrafficWorkbench.vue',import.meta.url),'utf8')
const HOME_SRC=readFileSync(new URL('../src/components/traffic/HomeStage.vue',import.meta.url),'utf8')
// 0.11.2：首屏的"四个带基线的数字"搬进了 `SituationBrief.vue`（手册 §3.2 L2）。
// 下钻这件事仍然必须在**首屏**上可点，所以判据读的是"首屏那两块源码"的并集，
// 而不是死盯某一个文件 —— 否则搬一次家，判据就静默失效了。
const BRIEF_SRC=readFileSync(new URL('../src/components/traffic/SituationBrief.vue',import.meta.url),'utf8')
const HOME_SCREEN_SRC=HOME_SRC+BRIEF_SRC
// 这两个 SFC **在磁盘上是 CRLF**，所以切片标记只能用 `\n<template>` 这种"左侧带换行、
// 右侧不带"的写法。写成 `\n<template>\n` 在 LF 上没问题，在 CRLF 上 `indexOf` 直接
// 返回 -1 —— 那时 `slice(-1, …)` 切出的是一段垃圾，于是**每一个**分节的切片都是 null，
// 报出来的却是"这个分节没渲染"。判据坏掉的声音必须与"东西真的没做"不一样。
const CONSOLE_TPL=CONSOLE_SRC.slice(CONSOLE_SRC.indexOf('\n<template>'),
  CONSOLE_SRC.indexOf('\n</template>'))
const WORKBENCH_TPL=WORKBENCH_SRC.slice(WORKBENCH_SRC.indexOf('\n<template>'),
  WORKBENCH_SRC.indexOf('\n</template>'))
assert.ok(CONSOLE_TPL.length>1000&&WORKBENCH_TPL.length>1000,
  '两个 SFC 的 <template> 切片取失败 —— 后面的每一条断言都会退化成"永远找不到"')

/** 去掉 HTML 注释。注释里写着锚点名，会让下面每一条 includes 变成"测注释"（M63）。 */
const stripComments=text=>text.replace(/<!--[\s\S]*?-->/g,'')

/** 控制台里**某一个分节**的模板切片：从它的分支起点切到下一个分支起点。 */
function consoleSection(section){
  const marker=`view==='${section}'`
  const at=CONSOLE_TPL.indexOf(marker)
  if(at<0)return null
  const rest=CONSOLE_TPL.slice(at+marker.length)
  const next=rest.search(/view===\s*'/)
  // **不按 `</template>` 截断**：分节正文里到处是内联 `<template v-if="…">`，取第一个
  // `</template>` 会把切片砍在正文中间 —— 报出来的是"这一节里没有那个锚点"，而锚点
  // 其实就在后面。只有最后一个分节没有下一个分支标记，才回落到根闭合标签。
  const close=CONSOLE_TPL.lastIndexOf('\n</template>')-(at+marker.length)
  const end=next>=0?next:(close>0?close:rest.length)
  return stripComments(rest.slice(0,end))
}

// 工作台里那两段**按起止标记**切，不按行切：台账恰好压在一行里，而总览跨了十几行
// （`.traffic-main` / 班次剖面 / 决策板 / 推演条各占一行）。按行切的话，总览只切到
// 第一行，`.traffic-detail` 就落到了切片之外 —— 那会让这条判据对着一个切片长度报错，
// 而不是对着"第 3 次点击能不能落地"报错。
const WORKBENCH_RANGES={
  overview:['class="traffic-main"','class="traffic-table-panel"'],
  schedule:['class="traffic-table-panel"','</template>'],
}

/** 某一节在页面上实际渲染的那一段模板。台账/总览在工作台里，其余在控制台里。 */
function landing(section){
  const range=WORKBENCH_RANGES[section]
  if(range){
    const at=WORKBENCH_TPL.indexOf(range[0])
    if(at<0)return null
    const end=WORKBENCH_TPL.indexOf(range[1],at)
    return stripComments(WORKBENCH_TPL.slice(at,end<0?WORKBENCH_TPL.length:end))
  }
  return consoleSection(section)
}

// 每一格的「第 2 次点击落在哪」与「第 3 次点击落在哪」。表里的键是 `DRILL_TARGETS`
// 里出现过的落点分节；键取自**提示语描述的那两下点击**，不是从实现里抄的类名。
// 台账那一格特意写明白：点一行会**切到总览并选中该班次**，所以第 3 次落在总览的
// 班次剖面里 —— 不写清楚就会去台账行里找放行许可，永远找不到。
//
// 锚点写的是**模板里的属性值**（`class="x"` 的 x、`data-x`），不是 CSS 选择器。
// 写成 `.traffic-detail` 这种带点的形式会永远找不到 —— 而"永远找不到"的判据在失败
// 时长得像"这一条真的没做"，正是本项目反复记下的那类假阴性（§十八⑫）。
const EVIDENCE_STEPS={
  schedule:{second:['traffic-table-panel'],third:['traffic-detail','traffic-clearance'],thirdSection:'overview'},
  briefing:{second:['data-batch-clearance'],third:['data-detour-row']},
  alerts:{second:['data-alert-key'],third:['data-disposal-action']},
  weather:{second:['data-weather-situation'],third:['data-weather-bands']},
  mechanism:{second:['data-mechanism-census'],third:['data-mechanism-detail','data-mechanism-step']},
  assistant:{second:['data-ai-mark-row'],third:['data-ai-coverage']},
}

test('三次点击的路径在页面上真的存在，而不只是一张写着"落点分节"的表',()=>{
  // 第 1 次点击：首屏那一格必须**真的可点**，并且带着自己的键发出去。
  assert.match(HOME_SCREEN_SRC,/data-kpi-drill/,'首屏 KPI 的数值必须是一个可点的控件，而不是一段文字')
  assert.match(HOME_SCREEN_SRC,/data-drill-key/,'发出的键必须是这一格自己的键，否则点哪一格都去同一页')
  assert.match(HOME_SRC,/emit\('drill'/,'首屏要把"去哪一页"交给父组件，不能自己硬跳')

  for(const [key,target] of Object.entries(DRILL_TARGETS)){
    const steps=EVIDENCE_STEPS[target.section]
    assert.ok(steps,`下钻目标 ${key} 落到 ${target.section}，但这一节没有定义"第 2、3 次`
      +'点击落在哪" —— 新增分节必须同时补这张表')

    // 第 2 次点击：目标分节的那一段模板必须存在，且带有承诺的落点。
    const second=landing(target.section)
    assert.ok(second,`${key} 指向 ${target.section}，但页面上没有渲染这一段：点击会静默无反应`)
    for(const anchor of steps.second){
      assert.ok(second.includes(anchor),
        `${key} → ${target.section}：承诺的落点 ${anchor} 不在这一段里（在别的分节里同样算走不通）`)
    }

    // 第 3 次点击：选中之后那一段自身要带出原始依据。
    const thirdSection=steps.thirdSection||target.section
    const third=landing(thirdSection)
    assert.ok(third,`${key} 的第 3 次点击落在 ${thirdSection}，但页面上没有这一段`)
    for(const anchor of steps.third){
      assert.ok(third.includes(anchor),
        `${key} 的第 3 次点击落到 ${thirdSection}，但那里的原始依据 ${anchor} 不存在`)
    }

    // 提示语里用「」引出的**每一个**标题，都必须是落地页上真实存在的标题。
    // 一个「」都没有说明这段提示没写出"再点一次会看到什么"。
    const quoted=[...target.hint.matchAll(/「([^」]+)」/g)].map(match=>match[1])
    assert.ok(quoted.length,`${key} 的提示语必须用「」写出"再点一次会看到什么"的具体标题`)
    for(const title of quoted){
      assert.ok(second.includes(title),
        `${key} → ${target.section}：提示语承诺的「${title}」在这一段里找不到 —— 那是承诺落空`)
    }
  }
})

test('下钻路径表随分节清单一起更新：少一个落点就必须变红',()=>{
  // 负向对照（M29）：把一格从表里拿掉，上面的检查**必须**没有覆盖到它 —— 也就是
  // 说，`EVIDENCE_STEPS` 必须覆盖每一个落点分节。表齐全时这条为真；一旦有人新增
  // 一格下钻却忘了补表，它会立刻变红，而不是让那一格静默地不被检查。
  const lands=[...new Set(Object.values(DRILL_TARGETS).map(target=>target.section))]
  for(const section of lands){
    assert.ok(EVIDENCE_STEPS[section],
      `落点分节 ${section} 没有在 EVIDENCE_STEPS 里定义第 2/3 次点击 —— 那一格的下钻路径等于没验`)
  }
})

// ---- 数字型验收要配数字型判据（§十七①） -----------------------------------
//
// 计划里给情报页写下的验收原话是「情报页在任何场景都不出现整页空；**至少有 5 个
// 可独立核对的内容块**」。前半句极容易满足 —— 有一块就算"不空" —— 而"5 个"这个
// 数字从来没有被任何判据量过。所以这里逐块点名。
//
// 点名的意义不只是计数：**没有锚点的块无法被任何东西引用**（判据定位不到它、
// 截图脚本指认不了它、文档也链不过去）。所以"有没有锚点"就是"能不能被独立核对"的
// 最小条件，而不是一种实现风格。
const BRIEFING_BLOCKS=[
  'data-batch-clearance',
  'data-detour-block',
  'data-observation-table',
  'data-observation-impact',
  'data-intel-timeline',
  'data-intel-airspace',
]

test('情报页承诺的「至少 5 个可独立核对的内容块」，逐块点名数得出来',()=>{
  assert.ok(BRIEFING_BLOCKS.length>=5,
    '这份清单本身就是那条承诺的展开：少于 5 条说明承诺被悄悄改小了')
  const briefing=landing('briefing')
  assert.ok(briefing,'取不到情报页的模板切片 —— 后面的断言会退化成"永远找不到"')
  const missing=BRIEFING_BLOCKS.filter(anchor=>!briefing.includes(anchor))
  assert.deepEqual(missing,[],`情报页承诺的内容块少了：${missing.join(', ')}`)
})
