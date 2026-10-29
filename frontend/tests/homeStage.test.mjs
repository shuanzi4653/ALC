import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {stageKpis,weatherCorridorStory,avoidanceAbsentReason,clearanceReport,briefingTicker,observationTone,metarSummaryText,scrollCycle,scrollWrap,scrollTarget,stageScale,representativeFlightId,dispatchSummaryRows,clearanceStatusName,detourMinutesShort,WEATHER_CLOSURE_REASONS,stageBox,STAGE_H,STAGE_MIN_W,STAGE_MAX_W,wallClockText,relativeClock,buildNote,BUILD_NOTES,tickerTone,toneFitsFamily} from '../src/traffic/runtime.js'

// 用户 2026-10-02：「贴近民航的东西在哪呢…整个这个专业性和显示上感觉还差强人意」，
// 并要求「记得要抓重点，展示我们项目基于气象确定航道的亮点」。
//
// 这一组钉的是首屏数字的**口径**，而不是像素。首屏最容易出的错不是样式，是
// 「同一屏两个数」和「把未声明说成 0」。

// ---------------------------------------------------------------------------
// 一、KPI 口径：气象关闭只能数气象造成的关闭
// ---------------------------------------------------------------------------
test('气象关闭不计入非气象原因的关闭',()=>{
  const flights=[
    {id:'A',status:'CLOSED',reason:'WEATHER_BLOCKED'},
    {id:'B',status:'CLOSED',reason:'WEATHER_UNAVAILABLE'},
    {id:'C',status:'CLOSED',reason:'FINAL_WEATHER_OR_BOUNDARY_CHECK_FAILED'},
    // 下面三条**不是**气象造成的。把它们算进来，"气象关闭"这个数字就变成了
    // "所有关闭"的另一个名字 —— 一个恒等于分母的指标（M46）。
    {id:'D',status:'CLOSED',reason:'NO_GEOMETRIC_PATH'},
    {id:'E',status:'CLOSED',reason:'STATIC_AIRSPACE_BLOCKED'},
    {id:'F',status:'CLOSED',reason:'MANUAL_SUSPEND'},
    {id:'G',status:'ACCEPTED',reason:'CLEAR'},
  ]
  const kpis=stageKpis(flights,{cells:[]},null)
  const byKey=Object.fromEntries(kpis.map(k=>[k.key,k]))
  assert.equal(byKey.weather.value,3,'只有三条是气象原因')
  assert.equal(byKey.accepted.value,1,'受理 = 总数 7 − 关闭 6')
  assert.equal(byKey.weather.note,'因气象不予放行')
  assert.ok(WEATHER_CLOSURE_REASONS.has('WEATHER_BLOCKED'))
  assert.ok(!WEATHER_CLOSURE_REASONS.has('NO_GEOMETRIC_PATH'))
})

test('KPI 在空计划与缺字段时不抛异常',()=>{
  for(const input of [undefined,null,[],{}]){
    const kpis=stageKpis(input,undefined,undefined)
    assert.equal(kpis.length,7)
    assert.equal(kpis.find(k=>k.key==='accepted').value,0)
    assert.equal(kpis.find(k=>k.key==='weather').value,0)
    assert.equal(kpis.find(k=>k.key==='ai').value,0)
  }
})

// 第十一轮新增的第七格（P1-2 ②）。它的**要点是 0 必须自述**：
// 「本会话尚未研判」是一个每次打开都成立的真实结论，把它渲染成空白会被读成"忘了标"。
test('AI 覆盖格：0 要自己说清为什么是 0，且不与"已研判"同形',()=>{
  const none=stageKpis([{id:'a'},{id:'b'}],{},null).find(k=>k.key==='ai')
  assert.equal(none.value,0)
  // 0.11.1（Beta）换芯后这句必须改（M95）：原来的落点是"规则引擎直接产出"，
  // 而那句话的完整形态是「…不依赖外部模型」—— 概率模型已经进了裁决链，
  // 这句话既过时、又方向相反地自伤（手册 §6 第一条）。现在钉的是：
  // ① 说清"尚未手动研判"这个 0 的来由；② 说清两层（规则可一票否决、模型只能更严）；
  // ③ 指向**记录在哪看**；④ 旧口径不许回来。
  // 0.11.26：落点改名 —— 0.11.24 起「分歧台账」并入「推演」第 8 步「复核」，
  // 导航上已经没有"分歧台账"这四个字。判据守的是"必须指得出地方"，
  // 不是"必须叫旧名字"，否则一次改名就会被迫把测试改成不测东西。
  assert.match(none.note,/尚未手动发起逐班研判/)
  assert.match(none.note,/概率模型/)
  assert.match(none.note,/只能更严/)
  assert.match(none.note,/推演 · 第 8 步 复核/)
  assert.doesNotMatch(none.note,/不依赖外部模型/, '旧口径不许留在文案里')
  assert.equal(none.tone,'muted')
  const some=stageKpis([{id:'a'},{id:'b'}],{},null,{reviewed:1,vetoed:0}).find(k=>k.key==='ai')
  assert.equal(some.value,1)
  assert.match(some.note,/共 2 班/)
  assert.notEqual(some.note,none.note,'"一次都没研判"与"研判过一班"不能是同一句话')
  assert.equal(some.tone,'cyan')
  const vetoed=stageKpis([{id:'a'}],{},null,{reviewed:1,vetoed:1}).find(k=>k.key==='ai')
  assert.match(vetoed.note,/整条否决/)
  assert.equal(stageKpis([],{},null).find(k=>k.key==='ai').note,'尚无班次可供研判')
})

test('没有避让几何时 KPI 说的是"缺失"，而不是一个确凿的 0',()=>{
  const none=stageKpis([],{},null).find(k=>k.key==='sweep')
  assert.equal(none.value,0)
  // 实测通道没有"采样点"这个量 —— 它是**一次观测**。改用"点"作单位，
  // 屏幕上就会出现"避让采样 0 点"，读起来是"采样没跑"。
  assert.equal(none.unit,'次观测','实测通道量的是一次观测，不是采样点')
  assert.equal(none.note,'无避让几何声明','缺失必须说成缺失，不能报成一个确凿的 0')
  const declared=stageKpis([],{},{
    radarAvoidance:{included:false,mode:'virtual',reason:'VIRTUAL_FRAME_NOT_SYNTHETIC'},
  }).find(k=>k.key==='sweep')
  assert.equal(declared.unit,'点','虚拟通道才有点数')
  assert.equal(declared.note,avoidanceAbsentReason('VIRTUAL_FRAME_NOT_SYNTHETIC'),
    '取帧没走生成器是机制故障，不能退成"没有采样"那句含糊话')
  assert.notEqual(declared.note,avoidanceAbsentReason('RADAR_UNAVAILABLE'),
    '虚拟通道取错了源与实测通道取不到帧是两件事，下一步动作也不同')
})

test('虚拟通道的晴朗帧同样不许被读成机制失效',()=>{
  // 2026-10-15 之前虚拟通道把任何空扫掠都报成 `RADAR_UNAVAILABLE`，于是"按通道写死"
  // 恰好成立；原因拆开之后"本窗口真没有对流回波"在两条通道上都可达，这条钉住它。
  const clearSky=stageKpis([],{},{
    radarAvoidance:{included:false,mode:'virtual',reason:'NO_CONVECTIVE_ECHO',sweepSlots:0},
  }).find(k=>k.key==='sweep')
  assert.equal(clearSky.value,0,'虚拟通道量的仍是采样点，空就是 0')
  assert.ok(clearSky.note.includes('≥35 dBZ'),'要说清是"判过了、本窗口没有回波"')
  assert.notEqual(clearSky.note,'本帧无可用采样','"没有采样"与"没有回波"是两件事')
})

test('晴朗帧与"机制没跑"在 KPI 上不得说同一句话',()=>{
  const radar=extra=>({radarAvoidance:Object.assign(
    {included:false,mode:'measured'},extra)})
  const clearSky=stageKpis([],{},radar({reason:'NO_CONVECTIVE_ECHO',
    detail:'回波帧已取到并逐级判定：本帧没有 ≥35 dBZ 回波…'})).find(k=>k.key==='sweep')
  const absent=stageKpis([],{},radar({reason:'RADAR_UNAVAILABLE'})).find(k=>k.key==='sweep')
  assert.notEqual(clearSky.note,absent.note,'两种缺席必须有两句话')
  assert.ok(clearSky.note.includes('≥35 dBZ'),'晴朗帧要说清是"判过了、本帧没有回波"')
  assert.equal(clearSky.value,1,'判据确实执行过一次观测')
  assert.equal(absent.value,0,'机制没跑才是 0')
  // 方向负向对照：若把晴朗帧退回"没纳入"那句通用话，上面第一条不等号必须抓住。
  assert.notEqual(clearSky.note,avoidanceAbsentReason('RADAR_UNAVAILABLE'))
  assert.notEqual(clearSky.note,avoidanceAbsentReason(null))
})

// ---------------------------------------------------------------------------
// 二、「基于气象确定航道」的叙事块
// ---------------------------------------------------------------------------
test('虚拟通道报出采样点数与步长',()=>{
  const story=weatherCorridorStory({
    radarAvoidance:{included:true,mode:'virtual',sweepSlots:49,sweepStrideMinutes:10,
      tiers:'CONVECTIVE_AND_STRONG',slot:'2026-10-01T00:00:00Z',slotTo:'2026-10-01T08:00:00Z',
      note:'模拟回波随推演时间轴平移…'},
  },{cells:[{id:'c1'},{id:'c2'}]})
  assert.equal(story.included,true)
  assert.equal(story.virtual,true)
  const rows=Object.fromEntries(story.rows.map(r=>[r.label,r.value]))
  assert.equal(rows['避让采样'],'49 个采样点 × 每 10 分钟')
  assert.ok(rows['判定档位'].includes('45 dBZ'))
  assert.equal(story.cells,2)
  assert.ok(story.headline.includes('随时间平移'))
})

test('实测通道报观测时刻与年龄，且不得声称"逐点扫掠"',()=>{
  const story=weatherCorridorStory({
    radarAvoidance:{included:true,mode:'measured',slot:'2026-10-01T00:00:00Z',
      slotAgeMinutes:12.5,areaKm2:1234.5,tiers:'CONVECTIVE_AND_STRONG',note:'单时刻实测观测…'},
  },{cells:[]})
  assert.equal(story.virtual,false)
  const text=story.rows.map(r=>`${r.label}=${r.value}`).join(' ')
  // 实测通道只有一个观测时刻。若这里出现"采样点"，就是把一个不存在的采样过程
  // 说成发生了 —— 与 0.9.21 的"通道混用"是同一类错误。
  assert.ok(!text.includes('采样点'),'实测通道不得声称逐点扫掠')
  assert.ok(text.includes('距今 12.5 分钟'))
  assert.ok(text.includes('1234.5 km²'))
  assert.ok(text.includes('不外推为预报'))
})

test('未纳入避让几何时给出人话原因，且不留空话',()=>{
  const story=weatherCorridorStory({
    radarAvoidance:{included:false,mode:'virtual',reason:'CHANNEL_CHANGED_DURING_BUILD'},
  },{})
  assert.equal(story.included,false)
  assert.ok(story.detail.includes('通道被切换'))
  assert.ok(!story.headline.includes('避让 0'))
})

test('每一个已知的缺失原因都有人话，未知原因原样透出',()=>{
  for(const reason of ['SCENARIO_DOES_NOT_DECLARE_WEATHER','RADAR_UNAVAILABLE',
                       'CHANNEL_CHANGED_DURING_BUILD','VIRTUAL_FRAME_NOT_SYNTHETIC',
                       'VIRTUAL_FRAME_UNAVAILABLE']){
    const text=avoidanceAbsentReason(reason)
    assert.ok(text&&text!==reason,'已知原因必须翻译成人话，不能把编码直接给用户看')
    assert.ok(!text.includes('_'),'不该把 SCREAMING_CASE 编码漏到界面上')
  }
  assert.equal(avoidanceAbsentReason('SOMETHING_NEW'),'SOMETHING_NEW','未知原因原样透出，不猜')
})

// ---------------------------------------------------------------------------
// 三、放行许可的报文体
// ---------------------------------------------------------------------------
test('报文体缺高度层写"未指派"而不是 0 米',()=>{
  const lines=clearanceReport({callsign:'FL-001',limit:'本场管制地带',route:'A — B'})
  const text=lines.join('\n')
  assert.ok(text.includes('CLR FL-001'))
  assert.ok(text.includes('未指派高度层'))
  assert.ok(!/0 m AGL/.test(text),'0 m AGL 会被读成"许可在 0 米高度飞行"')
  assert.ok(text.includes('未取得时隙'))
  assert.ok(text.includes('未声明气象判据'))
})

test('报文体带时隙有效窗与气象判据',()=>{
  const lines=clearanceReport({callsign:'FL-002',limit:'L',route:'R',assignedLevelAglM:120,
    ctot:{from:'2026-10-01T00:10:00Z',until:'2026-10-01T00:25:00Z',validityMinutes:15},
    weatherBasis:'虚拟气象通道；按回波避让改航，航程增加约 6 分钟',status:'CLEARED'})
  const text=lines.join('\n')
  assert.ok(/LVL\s+120 m AGL/.test(text))
  assert.ok(text.includes('有效 15 分钟'))
  assert.ok(text.includes('按回波避让改航'))
  // 这一条原来断言的是 `ST   CLEARED`（裸枚举）。改成中文名不是为了让测试变绿：
  // 报文体里其它要素本来就是中文（「未声明放行界限」「未指派高度层」「未取得时隙」
  // 「未声明气象判据」），只有状态一行印英文，读起来是"这一行不是给你念的"。
  // 断言的**意图**没变 —— 仍然是"ST 行在，且写的是这一班的状态"。
  assert.ok(/^  ST   \S/m.test(text),'报文体缺 ST 行')
  assert.ok(text.includes('ST   净空已检查'))
  assert.ok(!text.includes('CLEARED'),'报文体不该出现裸枚举')
  assert.equal(clearanceReport(null).length,0)
})

// ---------------------------------------------------------------------------
// 四、动态滚动条目
// ---------------------------------------------------------------------------
test('滚动条目把情报、观测与改航摊成同一种形状',()=>{
  const weather={
    cells:[{id:'WSIM-1',kind:'STORM',memberCount:2,sources:['a::x','b::y'],
      source:'OPEN_METEO_DERIVED_RISK',areaKm2:10}],
    observations:[{cityName:'沈阳',cityId:'SY',windMps:5,windDeg:200,tempC:12,
      visibilityM:8000,weatherCode:3,validAt:'2026-10-01T00:00:00Z'}],
  }
  const flights=[{id:'FL-9',name:'班次九',detourMinutes:4.5,distanceKm:88,fromPad:'P1',toPad:'P2',
    routeBasis:'RADAR_FIELD',routeBasisFromMinute:12,
    atcClearance:{weatherBasis:'按回波避让改航'}},
    {id:'FL-10',name:'直飞',detourMinutes:0,routeBasis:'CLEAR'},
    // 负向对照（2026-10-03）：长度更大、但成因不是气象的班次**不是**改航。
    // 实测通道里 42 班就是这个形状，它们曾被记成"受气象影响改航"。
    {id:'FL-11',name:'被边界逼弯',detourMinutes:7,routeBasis:'BOUNDARY'}]
  const items=briefingTicker(weather,flights)
  const kinds=new Set(items.map(i=>i.kind))
  assert.ok(kinds.has('SIGMET'))
  assert.ok(kinds.has('观测'))
  assert.ok(kinds.has('改航'))
  assert.equal(items.filter(i=>i.kind==='改航').length,1,'只有气象类成因的班次是改航')
  for(const item of items){
    for(const field of ['id','kind','tone','title','meta','body','foot']){
      assert.ok(field in item,`条目缺 ${field}：${JSON.stringify(item)}`)
    }
  }
})

test('滚动条目在无气象无班次时返回空数组而不是抛异常',()=>{
  for(const [w,f] of [[undefined,undefined],[null,[]],[{},[{}]],['x',null]]){
    const items=briefingTicker(w,f)
    assert.ok(Array.isArray(items))
  }
})

test('观测严重度与排序键同源，缺要素写 //',()=>{
  assert.equal(observationTone({visibilityM:3000}),'alert')
  assert.equal(observationTone({visibilityM:9000,windMps:14}),'warn')
  assert.equal(observationTone({visibilityM:9000,windMps:3}),'normal')
  assert.equal(observationTone({}),'normal','缺要素不等于恶劣天气')
  const text=metarSummaryText({})
  assert.ok(text.includes('//'),'缺要素必须写 //')
  assert.ok(!text.includes('0 km'),'不得把缺报写成能见度 0')
})

// ---------------------------------------------------------------------------
// 五、循环滚动的纯数学
// ---------------------------------------------------------------------------
test('cycle = 条数 × 行高；不合法输入退回 0',()=>{
  assert.equal(scrollCycle(5,44),220)
  assert.equal(scrollCycle(0,44),0)
  assert.equal(scrollCycle(5,0),0)
  assert.equal(scrollCycle(-3,44),0)
  assert.equal(scrollCycle(undefined,44),0)
})

test('scrollWrap 把位移收敛到 [0,cycle)',()=>{
  assert.equal(scrollWrap(0,220),0)
  assert.equal(scrollWrap(220,220),0)
  assert.equal(scrollWrap(230,220),10)
  assert.equal(scrollWrap(-10,220),210)
  assert.equal(scrollWrap(5,0),0)
})

test('scrollTarget 不提前取模 —— 跨圈那一帧必须走到 cycle 才归位',()=>{
  // offset=215，向下走一行 → 220。若这里返回 0，动画会从 215 **倒扫**回 0，
  // 屏幕上就是"列表倒着滚了一整圈"（见 ScrollList 顶部注释）。
  assert.equal(scrollTarget(215,5,220),220)
  assert.equal(scrollTarget(220,44,220),264)
  // 归位是动画**之后**的独立一步，由调用方显式做。
  assert.equal(scrollWrap(scrollTarget(220,44,220),220),44)
  // 向上跨圈同理：从 0 往回走一行 → -44，而不是 176。
  assert.equal(scrollTarget(0,-44,220),-44)
  assert.equal(scrollWrap(scrollTarget(0,-44,220),220),176)
})

// ---------------------------------------------------------------------------
// 六、大屏舞台缩放：结构上不可能裁切
// ---------------------------------------------------------------------------
const STAGE=[1920,1080]

test('舞台缩放后两个方向都不大于容器 —— 否则会被 overflow:hidden 裁掉',()=>{
  // 覆盖"宽受限 / 高受限 / 恰好等宽 / 极端扁"四种情形。判据是**两个方向都成立**，
  // 只看其中一个方向的话，`Math.max` 那种写法也能通过 —— 那正是当初算错时用过的。
  const cases=[[1920,1080],[1600,900],[1672,951],[3840,1000],[1000,3840],[1921,1081],[1,1]]
  for(const [w,h] of cases){
    const s=stageScale(w,h,STAGE[0],STAGE[1])
    assert.ok(s>0,`${w}x${h} 应给出正比例`)
    assert.ok(STAGE[0]*s<=w+1e-6,`${w}x${h}: 舞台宽 ${STAGE[0]*s} 溢出容器 ${w}`)
    assert.ok(STAGE[1]*s<=h+1e-6,`${w}x${h}: 舞台高 ${STAGE[1]*s} 溢出容器 ${h}`)
  }
})

test('缩放取 min：至少有一个方向被填满（不是无谓缩小）',()=>{
  // 另一半判据。只断言"不溢出"的话，返回 0.01 也能通过 —— 那是一个永远放得下、
  // 也永远看不清的舞台。等比填满意味着**至少一维**贴边。
  for(const [w,h] of [[1920,1080],[1600,900],[1672,951],[3840,1000],[1000,3840]]){
    const s=stageScale(w,h,STAGE[0],STAGE[1])
    const touchesW=Math.abs(STAGE[0]*s-w)<1e-6
    const touchesH=Math.abs(STAGE[1]*s-h)<1e-6
    assert.ok(touchesW||touchesH,`${w}x${h}: 两个方向都没贴边 → 舞台被无谓地缩小了`)
  }
})

test('拿不到容器尺寸时返回 0，而不是拿 1 冒充一个合适的比例',()=>{
  // 容器尚未布局（clientWidth=0）是正常的一瞬。返回 1 会让舞台按 1:1 画出去，
  // 在 1672 宽的窗口里直接溢出 248 px。0 表示"还没量到"，屏幕上是空的，
  // 下一帧 ResizeObserver 就会纠正 —— 与"悄悄裁掉一条边"相比，这是可恢复的失败。
  for(const [w,h] of [[0,900],[1600,0],[0,0],[-1,900],[NaN,900],[undefined,900],[null,900]]){
    assert.equal(stageScale(w,h,STAGE[0],STAGE[1]),0,`${w}x${h} 应返回 0`)
  }
  assert.equal(stageScale(1600,900,0,1080),0,'舞台自身尺寸非法时同样返回 0')
})

test('负向对照：把 min 换成 max 必须被"不溢出"判据抓住',()=>{
  // 没有这一条，上面两条断言只是在描述当前实现，而不是在检验一个性质。
  //
  // 这一条**先写错过一次**：原来断言的是"max 在高这一维溢出"，而 1672×951 恰好
  // 是高比例更大（951/1080 > 1672/1920），于是 max 在高度上刚好贴边、只在宽度上
  // 溢出 —— 判据针对了一维，现象却落在另一维。被检验的性质是"**至少有一维**溢出"，
  // 因为 max 必然让某一维按 1:1 或更大画出去，而容器不可能同时容纳两者。
  const wrong=(w,h,sw,sh)=>Math.max(w/sw,h/sh)
  for(const [w,h] of [[1672,951],[1920,900],[1600,1080],[3840,1000],[1000,3840]]){
    const bad=wrong(w,h,STAGE[0],STAGE[1])
    const overW=STAGE[0]*bad>w+1e-6
    const overH=STAGE[1]*bad>h+1e-6
    assert.ok(overW||overH,`${w}x${h}: max 竟然两个方向都没溢出，负向对照失效`)
    // 而正确实现两维都不溢出（与上面的正向判据同源）。
    const good=stageScale(w,h,STAGE[0],STAGE[1])
    assert.ok(STAGE[0]*good<=w+1e-6&&STAGE[1]*good<=h+1e-6,`${w}x${h}: 正确实现溢出`)
  }
})

// ---------------------------------------------------------------------------
// 七、「最有代表性的一班」的挑选顺序
// ---------------------------------------------------------------------------
// 这一组不是在测"选得对不对"，而是把**顺序**钉住。顺序就是口径：它决定
// `representativeFlightId()` 返回谁。放进 .vue 里就只能靠肉眼核对，所以它住在
// runtime.js。
//
// **2026-10-03 起界面不再自动调用它。** 用户的要求是「首页进入时不要自动选择某一个
// 航班进行追踪和显示细节，显示总的调度总结即可」—— `selectedId` 是"值班员正在看
// 哪一班"，只能由值班员自己写。这一组断言因此**不再描述首屏的样子**，它守的是
// 这个函数自己的契约（将来要显式调用它时，顺序必须还是这个顺序）；
// 首屏默认状态由下面第八节守。
test('默认选中优先取改航幅度最大的班次',()=>{
  const flights=[
    {id:'A',delayMinutes:40,detourMinutes:0},
    {id:'B',delayMinutes:5,detourMinutes:7},
    {id:'C',delayMinutes:2,detourMinutes:12.5},
  ]
  // 改航是气象直接造成的，比"延误"更贴合首屏要讲的"基于气象确定航道"。
  assert.equal(representativeFlightId(flights),'C')
})

test('没有改航班次时退到延误最大的班次',()=>{
  const flights=[
    {id:'A',delayMinutes:3,detourMinutes:0},
    {id:'B',delayMinutes:25,detourMinutes:0},
    {id:'C',delayMinutes:9,detourMinutes:0},
  ]
  assert.equal(representativeFlightId(flights),'B')
})

test('既无改航也无延误时取第一个未关闭的班次',()=>{
  const flights=[
    {id:'A',status:'CLOSED',delayMinutes:0,detourMinutes:0},
    {id:'B',status:'ACCEPTED',delayMinutes:0,detourMinutes:0},
  ]
  // A 排在前面但已关闭：关闭的班次单独出现在首屏会被读成"当前运行状态"。
  assert.equal(representativeFlightId(flights),'B')
})

test('全部关闭时仍返回一个 id，而不是空串',()=>{
  // 宁可展示"为什么这一班不放行"，也不要留一块空面板 —— 空面板会把
  // "系统没话说"和"系统在等你点一下"混成同一件事。
  const flights=[{id:'A',status:'CLOSED'},{id:'B',status:'CLOSED'}]
  assert.equal(representativeFlightId(flights),'A')
})

test('空输入与缺 id 的条目返回空串，不抛异常',()=>{
  assert.equal(representativeFlightId([]),'')
  assert.equal(representativeFlightId(null),'')
  assert.equal(representativeFlightId(undefined),'')
  // 没有 id 的条目不能被选中 —— 选中一个事后 `find` 不到的 id，界面上就是
  // "选了但什么都不显示"，比不选更难查。
  assert.equal(representativeFlightId([{delayMinutes:99},{detourMinutes:99}]),'')
  assert.equal(representativeFlightId([{detourMinutes:99},{id:'Z',detourMinutes:1}]),'Z')
})

test('负向对照：把比较方向反过来，顺序判据必须被抓住',()=>{
  // 没有这一条，上面的断言只是在描述"当前实现返回了 C"。
  // 性质是：**返回的那个班次，在其所属档位里数值最大**。把排序方向反过来就违反它。
  const flights=[{id:'A',detourMinutes:1},{id:'B',detourMinutes:9},{id:'C',detourMinutes:4}]
  const chosen=representativeFlightId(flights)
  const pick=flights.find(f=>f.id===chosen)
  assert.ok(flights.every(f=>f.detourMinutes<=pick.detourMinutes),'选出的不是改航幅度最大的')
  // 反向（幅度最小的）必须得到**另一个**班次，否则说明这个判据对方向不敏感。
  const reversed=flights.slice().sort((a,b)=>a.detourMinutes-b.detourMinutes)[0]
  assert.equal(reversed.id,'A')
  assert.notEqual(reversed.id,chosen,'反过来排竟然得到同一个结果，判据对方向不敏感')
})

// ---------------------------------------------------------------------------
// 七·补、未选中班次时右栏说的是「总的」（用户 2026-10-03）
// ---------------------------------------------------------------------------
// 与第七节合起来读：第七节撤掉了"程序代选班次"，这一节保证撤掉之后首屏**仍然有
// 内容**。没有这一节，取消自动选中就等于把右栏首块留成一块占位文案 —— 那是用
// 一个更小的缺陷去换一个更大的缺陷。
//
// 口径的硬要求只有一条：**四态之和 = 总班数**。它是分布与四个独立计数的区别所在。
const summaryFlights=[
  {id:'A',mode:'CAR',status:'SCHEDULED',departureMinute:10,arrivalMinute:40},
  {id:'B',mode:'CAR',status:'SCHEDULED',scheduledMinute:5,departureMinute:30,arrivalMinute:60},
  {id:'C',mode:'DELIVERY',status:'SCHEDULED',departureMinute:0,arrivalMinute:20},
  {id:'D',mode:'DELIVERY',status:'CLOSED',departureMinute:0,arrivalMinute:20},
]

test('未选中班次时的总结是四态分布，且四态之和等于总班数',()=>{
  // t=25：A 在空（10..40）、B 未起飞（计划 5，放行 30）、C 已到达（≥20）、D 已关闭
  const s=dispatchSummaryRows(summaryFlights,25)
  const by=Object.fromEntries(s.rows.map(r=>[r.key,r.value]))
  assert.equal(by.airborne,1,'A 应在空')
  assert.equal(by.pending,1,'B 应未起飞')
  assert.equal(by.arrived,1,'C 应已到达')
  assert.equal(by.closed,1,'D 应已关闭')
  assert.equal(s.total,4)
  assert.equal(s.rows.reduce((n,r)=>n+r.value,0),summaryFlights.length,
    '四态之和必须等于总班数 —— 少算一格在屏幕上就是"凭空少了几班"')
})

test('「未起飞」合并了待执行与等待放行，但注脚里说出拆分',()=>{
  // 合并是为了版面，不是为了少说：HOLD（该走了还没拿到放行）与 PENDING（还没到点）
  // 是两种处境，藏起来就等于让值班员自己去猜。
  const s=dispatchSummaryRows([
    {id:'H',mode:'CAR',status:'SCHEDULED',scheduledMinute:0,departureMinute:10,arrivalMinute:40},
    {id:'P',mode:'CAR',status:'SCHEDULED',scheduledMinute:20,departureMinute:30,arrivalMinute:50},
  ],5)
  const row=s.rows.find(r=>r.key==='pending')
  assert.equal(row.value,2)
  assert.ok(row.note.includes('等待放行 1 班'),'拆分必须留在注脚里')
})

test('「在空」按机种拆分，机种之和等于在空总数',()=>{
  const s=dispatchSummaryRows([
    {id:'A',mode:'CAR',status:'SCHEDULED',departureMinute:0,arrivalMinute:60},
    {id:'B',mode:'DELIVERY',status:'SCHEDULED',departureMinute:0,arrivalMinute:60},
    {id:'C',mode:'DELIVERY',status:'SCHEDULED',departureMinute:0,arrivalMinute:60},
  ],30)
  const row=s.rows.find(r=>r.key==='airborne')
  assert.equal(row.value,3)
  assert.equal(s.airborne.CAR,1)
  assert.equal(s.airborne.DELIVERY,2)
  assert.equal(s.airborne.CAR+s.airborne.DELIVERY,row.value)
  assert.ok(row.note.includes('飞行汽车 1')&&row.note.includes('配送无人机 2'))
})

test('空输入与缺字段不抛异常，四态全为 0',()=>{
  for(const input of [null,undefined,[],{}]){
    const s=dispatchSummaryRows(input,60)
    assert.equal(s.total,0)
    assert.equal(s.rows.length,4)
    assert.equal(s.rows.reduce((n,r)=>n+r.value,0),0)
  }
})

test('每一行的配色都与它的族自洽',()=>{
  // 同一条不变式也在别处守着 KPI 条（TONE_FAMILY）：一块"班次"的数字不许用
  // "气象"的颜色，否则屏幕在教读者一个错的分类。
  for(const r of dispatchSummaryRows(summaryFlights,25).rows){
    assert.ok(toneFitsFamily(r.family,r.tone),`${r.key} 的 tone=${r.tone} 不属于 ${r.family} 族`)
  }
})

test('注脚必须同时挡住两处误读：全网络 + 地图标签会精简',()=>{
  // ① 分布**不受**导航栏所选运行区域影响（区域只筛地图与台账）；
  // ② 地图上的载具标签按可用空间精简过，所以"在空 N 架"与"图上几个标签"不是
  //    同一个量 —— 不写这句，两个数一对照就成了"地图少画了"。
  const s=dispatchSummaryRows(summaryFlights,25)
  assert.ok(s.note.includes('全网络'),'必须写明是全网络口径')
  assert.ok(s.note.includes('精简'),'必须写明地图标签会精简')
  assert.ok(s.note.includes('不与「在空」相等'),'必须明确否定"标签数＝在空数"')
})

// ---------------------------------------------------------------------------
// 八、净空状态的命名
// ---------------------------------------------------------------------------
// 同一个字段此前在四处写成四种样子（含报文体里的裸枚举），这一组把它钉成一种。
test('放行报文里不出现裸枚举',()=>{
  const lines=clearanceReport({callsign:'CAR-1',route:'R1',limit:'L1',
    assignedLevelAglM:120,ctot:null,weatherBasis:'实测',status:'SIMULATION_ASSUMPTION_UNVERIFIED'})
  const text=lines.join('\n')
  assert.ok(!text.includes('SIMULATION_ASSUMPTION_UNVERIFIED'),
    '报文体是给人照着念的，不能出现机器枚举名')
  assert.ok(text.includes('地形/建筑净空待验证'),'应换成与其它界面一致的中文名')
})

test('未声明与未知状态都不被折算成"已检查"',()=>{
  // 这一条针对的是方向：未知取值必须**保持不可读成"已验证"**。
  // 把 unknown 映射成"净空已检查"就是把"未验证"写成"已通过"。
  assert.equal(clearanceStatusName(''),'未声明净空状态')
  assert.equal(clearanceStatusName(null),'未声明净空状态')
  assert.equal(clearanceStatusName(undefined),'未声明净空状态')
  assert.equal(clearanceStatusName('SOME_FUTURE_STATUS'),'SOME_FUTURE_STATUS')
  assert.notEqual(clearanceStatusName('SOME_FUTURE_STATUS'),'净空已检查')
  assert.equal(clearanceStatusName('CLEARED'),'净空已检查')
  // 负向对照：未知取值不能与已检查撞名
  assert.notEqual(clearanceStatusName('SOME_FUTURE_STATUS'),clearanceStatusName('CLEARED'))
})

// ---------------------------------------------------------------------------
// 九、亚分钟改航的写法
// ---------------------------------------------------------------------------
// 列表的收录判据是 `detourMinutes > 0.01`，而 `Math.round(0.44)` 是 0 —— 于是同一行
// 一边说"这班按回波改航了"、一边说"+0 分"。实测 2026-10-02：21 个改航班次里 14 个
// `round()` 为 0，也就是说一屏里三分之二的行都在自相矛盾。
test('亚分钟改航不写成 +0 分',()=>{
  assert.equal(detourMinutesShort(0.44),'<1 分')
  assert.equal(detourMinutesShort(0.01),'<1 分')
  assert.equal(detourMinutesShort(0.499),'<1 分')
  // 到 0.5 就该进位成 1 分，不能一直挂着"<1"
  assert.equal(detourMinutesShort(0.5),'1 分')
  assert.equal(detourMinutesShort(0.65),'1 分')
  assert.equal(detourMinutesShort(12.4),'12 分')
  // 负向对照：判据说它 > 0，显示就不许写 0
  assert.notEqual(detourMinutesShort(0.44),'0 分')
  assert.ok(!detourMinutesShort(0.44).includes('0 分'))
})

test('改航条目的 meta 用亚分钟口径，且不出现 +0 分',()=>{
  const flights=[{id:'A',detourMinutes:0.44,routeBasis:'RADAR_FIELD',routeBasisFromMinute:3},
    {id:'B',detourMinutes:0.02,routeBasis:'RADAR_FIELD',routeBasisFromMinute:9},
    {id:'C',detourMinutes:3,routeBasis:'RADAR_CORE',routeBasisFromMinute:20}]
  const items=briefingTicker({},flights).filter(i=>i.kind==='改航')
  assert.equal(items.length,3)
  for(const item of items){
    assert.ok(!item.meta.includes('+0 分'),`${item.id} 写成了 ${item.meta}`)
  }
  const byId=Object.fromEntries(items.map(i=>[i.id,i.meta]))
  assert.equal(byId['FL-A'],'+<1 分')
  assert.equal(byId['FL-C'],'+3 分')
})

// ---------------------------------------------------------------------------
// 十、改航班次按改航量降序
// ---------------------------------------------------------------------------
// 这张榜是"气象怎么推移了航路"的证据，多花时间的必须排前面。原先按班次在数组里的
// 自然顺序（≈城市顺序）排，于是 35 条里排在前面的经常全是"<1 分"的班次 —— 一张
// 证据榜看起来像什么也没发生。
test('改航班次按改航量降序，不按输入顺序',()=>{
  const flights=[{id:'小',detourMinutes:0.2,routeBasis:'RADAR_FIELD'},
    {id:'大',detourMinutes:9,routeBasis:'RADAR_CORE'},
    {id:'中',detourMinutes:1.2,routeBasis:'RADAR_FIELD'}]
  const items=briefingTicker({},flights).filter(i=>i.kind==='改航')
  assert.deepEqual(items.map(i=>i.id),['FL-大','FL-中','FL-小'])
  // 负向对照：若实现只是原样保留输入顺序，这里必须不同 —— 否则判据对"有没有排序"不敏感
  assert.notDeepEqual(items.map(i=>i.id),flights.map(f=>'FL-'+f.id))
  // 第二档负向对照（2026-10-03 改成按成因判成员资格之后）：**长度不是成员资格**。
  // 一个 detourMinutes 很大、成因却是作业区边界的班次不得进这张榜 —— 它若进来了，
  // 这张"气象怎么推移了航路"的证据榜就开始记非气象的账。
  const boundary=briefingTicker({},[{id:'B',detourMinutes:99,routeBasis:'BOUNDARY'}])
    .filter(i=>i.kind==='改航')
  assert.equal(boundary.length,0)
  // 第三档：没有成因字段的老计划（本字段发布之前缓存的计划）也不得被算进来。
  const withZero=briefingTicker({},[{id:'Z',detourMinutes:0}]).filter(i=>i.kind==='改航')
  assert.equal(withZero.length,0)
})

// ---------------------------------------------------------------------------
// 十一、空回波帧 ≠ 机制没纳入
// ---------------------------------------------------------------------------
// 「帧取到了、逐级判过了，只是本帧没有 ≥35 dBZ 回波」是**一次晴朗**（气象被读进来
// 并且判它不影响航路）；「避让几何没被纳入」是**机制没跑**。两者在屏幕上曾经共用同一
// 句"本次构建未纳入回波避让几何"，于是一次好天气被读成一次机制失效 —— 而这两个结论
// 的下一步动作完全相反。
test('空回波帧说的是"本帧无对流回波"，不是"未纳入避让几何"',()=>{
  const plan={radarAvoidance:{included:false,mode:'measured',reason:'NO_CONVECTIVE_ECHO',
    detail:'回波帧已取到并逐级判定：本帧没有 ≥35 dBZ 回波，所有航路按直线走廊放行。',
    slot:'2026-10-02T04:18:00Z',slotAgeMinutes:5.6,areaKm2:0,coreAreaKm2:0,
    cautionAreaKm2:0,watchAreaKm2:1905.1,tiers:'CONVECTIVE_AND_STRONG'}}
  const story=weatherCorridorStory(plan,{cells:[]})
  assert.ok(story.silentRadar===true)
  assert.ok(story.headline.includes('无 ≥35 dBZ 回波'),story.headline)
  assert.ok(!story.headline.includes('未纳入'),'晴朗帧不能被写成机制未纳入')
  // 说明文字用后端带回来的 `detail`，前端不自己再写第二句同样的话（同一句话两个来源
  // 就是下一处不一致的入口）。
  assert.equal(story.detail,'回波帧已取到并逐级判定：本帧没有 ≥35 dBZ 回波，所有航路按直线走廊放行。')
  // 负向对照：换一个缺失原因，标题必须变 —— 否则两种状态共用一句话，判据对原因不敏感
  const other=weatherCorridorStory({radarAvoidance:{included:false,mode:'measured',
    reason:'RADAR_UNAVAILABLE'}},{})
  assert.notEqual(other.headline,story.headline)
  assert.ok(other.headline.includes('未纳入'))
  assert.ok(other.silentRadar!==true)
})

test('回波分级面积只报真取到的三档，虚拟通道不拿并集顶替',()=>{
  const measured={radarAvoidance:{included:true,mode:'measured',tiers:'CONVECTIVE_AND_STRONG',
    slot:'2026-10-02T04:24:00Z',slotAgeMinutes:0,areaKm2:122164.2,
    coreAreaKm2:61164.6,cautionAreaKm2:60999.6,watchAreaKm2:146635.2}}
  const rows=weatherCorridorStory(measured,{}).rows
  const tier=rows.find(r=>r.label==='回波分级面积')
  assert.ok(tier,'实测通道应给出分级面积')
  for(const label of ['禁止进入内核','须绕飞场','层状降水（可穿越）']){
    assert.ok(tier.value.includes(label),`缺 ${label}：${tier.value}`)
  }
  assert.ok(tier.value.includes('61164.6')&&tier.value.includes('60999.6'))
  assert.ok(tier.value.includes('146635.2'))
  // 虚拟通道的几何是沿时间轴逐帧取并集的结果，没有"某一帧的三档"可报：
  // 整行不许出现，更不许拿并集面积冒充其中一档。
  const virtual={radarAvoidance:{included:true,mode:'virtual',tiers:'CONVECTIVE_AND_STRONG',
    sweepSlots:17,sweepStrideMinutes:30,slot:'2026-09-14T10:00:00Z',
    slotTo:'2026-09-14T18:00:00Z'}}
  const virtualRows=weatherCorridorStory(virtual,{}).rows
  assert.equal(virtualRows.find(r=>r.label==='回波分级面积'),undefined)
})

// ---------------------------------------------------------------------------
// 七、舞台尺寸：宽度交给容器（用户 2026-10-02 第 3 条）
// ---------------------------------------------------------------------------
// 用户原话：「界面太空，左右两侧有大量空白…把整体左移，这样右侧空白还能显示
// 一些内容」。把 16:9 的舞台塞进更宽的容器，等比缩放的必然结果是左右各留一条
// 黑边 —— 那是算式分配出来的空白，不是内容要的。
const STAGE_RATIOS=[[1920,1080],[1672,951],[1082,547],[2560,1080],[3440,1440],[1280,1024]]

test('宽容器下舞台横向铺满，不留黑边',()=>{
  for(const [w,h] of STAGE_RATIOS){
    const box=stageBox(w,h)
    assert.ok(box.scale>0,`${w}x${h} 应给出正比例`)
    const drawnW=box.width*box.scale,drawnH=box.height*box.scale
    assert.ok(drawnW<=w+1e-6&&drawnH<=h+1e-6,`${w}x${h}: ${drawnW}x${drawnH} 溢出容器`)
    // 长宽比落在上下界之间时，两维都必须贴边 —— 少贴一维就是一条黑边。
    //
    // 容差 1 px 而不是 1e-6：舞台宽度是**整数**（画布上画不出 0.4 px），所以
    // `1080 × 容器比例` 取整之后，绘制宽度与容器最多差半个像素（实测 0.16 px）。
    // 判据要卡的是"有没有一条黑边"，不是浮点精度 —— 用 1e-6 会把这种舍入
    // 判成失败，而它和"留了 110 px 黑边"完全是两件事。
    const ideal=Math.round((w/h)*STAGE_H)
    if(ideal>STAGE_MIN_W&&ideal<STAGE_MAX_W){
      assert.ok(Math.abs(drawnW-w)<1,`${w}x${h}: 横向还留着 ${(w-drawnW).toFixed(1)} px 空白`)
      assert.ok(Math.abs(drawnH-h)<1,`${w}x${h}: 纵向还留着 ${(h-drawnH).toFixed(1)} px 空白`)
    }
  }
})

test('两端夹取：过窄与过宽都不许把版面拉变形',()=>{
  // 极窄（4:3）：宽度夹到 1660，宁可纵向留白，也不把三栏挤到读不出来。
  const narrow=stageBox(1280,1024)
  assert.equal(narrow.width,STAGE_MIN_W)
  assert.ok(narrow.height*narrow.scale<=1024+1e-6)
  // 极宽（32:9）：宽度夹到 2560，超出部分回到"居中 + 留白"，也不把地图拉成横带。
  const ultra=stageBox(5120,1440)
  assert.equal(ultra.width,STAGE_MAX_W)
  assert.ok(ultra.width*ultra.scale<=5120+1e-6)
})

test('负向对照：固定的 1920 宽在宽容器上必然留下黑边',()=>{
  // 没有这一条，上面那些断言只是在描述当前实现。这里检验的是**性质**：
  // "宽度固定"这个做法在非 16:9 的容器上一定留白，而 stageBox 不留。
  const w=1082,h=547
  const legacy=stageScale(w,h,1920,1080)
  const legacyBlank=w-1920*legacy
  assert.ok(legacyBlank>20,`固定 1920 宽的旧写法应当留下可观的横向空白，实测 ${legacyBlank.toFixed(1)} px`)
  const box=stageBox(w,h)
  const newBlank=w-box.width*box.scale
  assert.ok(newBlank<1,`stageBox 不该留下横向空白，实测 ${newBlank.toFixed(3)} px`)
  assert.ok(legacyBlank-newBlank>100,'新算式必须比旧算法用掉上百像素的宽度，而不是十几像素')
})

test('量不到容器尺寸时返回全零，而不是拿 1920 冒充一个合适的舞台',()=>{
  for(const [w,h] of [[0,900],[1600,0],[0,0],[-1,900],[NaN,900],[undefined,900],[null,900]]){
    const box=stageBox(w,h)
    assert.equal(box.scale,0,`${w}x${h} 应给出 0 比例`)
    assert.equal(box.width,0)
  }
})

// ---------------------------------------------------------------------------
// 八、实时钟与推演钟是两条时间轴（用户 2026-10-02 第 3 条）
// ---------------------------------------------------------------------------
test('实时钟按本机时间格式化，非法输入写 — 而不是 00:00:00',()=>{
  assert.equal(wallClockText(new Date(2026,9,2,9,7,4)),'09:07:04')
  assert.equal(wallClockText(new Date(2026,9,2,9,7,4),{withSeconds:false}),'09:07')
  assert.equal(wallClockText(new Date(2026,9,2,23,59,59)),'23:59:59')
  // 「没拿到时间」与「时间是零点」是两件事，不能都画成 00:00:00。
  for(const bad of [null,undefined,'2026-10-02',new Date('nope'),NaN,0]){
    assert.equal(wallClockText(bad),'—',`${String(bad)} 应写 —`)
  }
})

test('实时钟与推演钟格式上不会互相冒充',()=>{
  const wall=wallClockText(new Date(2026,9,2,10,0,0))
  const sim=relativeClock(60)
  assert.equal(sim,'T+01:00:00')
  assert.ok(/^T\+/.test(sim)&&!/^T\+/.test(wall),'推演时刻必须带 T+ 前缀，不能被读成本机时间')
})

// ---------------------------------------------------------------------------
// 九、加载时的轮换文字（用户 2026-10-02 第 4 条）
// ---------------------------------------------------------------------------
test('轮换文字按已用秒数换句，并且循环回第一句',()=>{
  assert.equal(buildNote(0),BUILD_NOTES[0])
  assert.equal(buildNote(3.9),BUILD_NOTES[0])
  assert.equal(buildNote(4),BUILD_NOTES[1])
  assert.equal(buildNote(4*BUILD_NOTES.length),BUILD_NOTES[0],'走满一轮必须回到第一句')
  // 秒数**不**参与文案内容，只决定轮到哪一句。
  assert.equal(buildNote(4),buildNote(4+4*BUILD_NOTES.length))
})

test('轮换文字不许假装成进度',()=>{
  for(const text of BUILD_NOTES){
    assert.ok(!/\d+\s*%/.test(text),`不得出现百分比：${text}`)
    assert.ok(!/第\s*\d+\s*步/.test(text),`不得出现"第 N 步"：${text}`)
    assert.ok(text.length>8,'不许是放在任何加载里都成立的空话')
  }
  assert.ok(buildNote(1e6).length>0)
  // 空表要返回空串，而不是 undefined（模板里会渲染成"undefined"）。
  assert.equal(buildNote(5,{notes:[]}),'')
})

// ---------------------------------------------------------------------------
// 十、色系：气象与班次不许同色（用户 2026-10-02 第 5 条）
// ---------------------------------------------------------------------------
test('每个 KPI 的配色必须与它自己声明的族自洽',()=>{
  const flights=[{id:'a',status:'SCHEDULED',detourMinutes:6,delayMinutes:0},
    {id:'b',status:'CLOSED',reason:'THUNDERSTORM',delayMinutes:0}]
  const weather={cells:[{id:'W1'}]}
  const plan={radarAvoidance:{included:true,mode:'measured',reason:null}}
  for(const k of stageKpis(flights,weather,plan)){
    assert.ok(k.family,`KPI 必须声明它属于哪一族：${k.key}`)
    assert.ok(toneFitsFamily(k.family,k.tone),
      `${k.key}（${k.family}）用了 ${k.tone} 的色 —— 族与色不一致，屏幕在教一个错的分类`)
  }
})

test('班次族不许用暖色 tone，气象族不许用冷色 tone',()=>{
  // 这一条是上一条的"牙齿"：不依赖任何具体 KPI，直接把两族的允许色列出来。
  assert.ok(!toneFitsFamily('flight','warn'))
  assert.ok(!toneFitsFamily('flight','alert'))
  assert.ok(!toneFitsFamily('flight','calm'))
  assert.ok(!toneFitsFamily('weather','cyan'))
  assert.ok(!toneFitsFamily('weather','normal'))
  assert.ok(toneFitsFamily('flight','cyan')&&toneFitsFamily('weather','warn'))
  assert.ok(toneFitsFamily('flight','good')&&toneFitsFamily('weather','good'),'状态色与两族都能共存')
  assert.ok(!toneFitsFamily('flight','不存在'),'未知色调不得被当作自洽')
})

test('两张滚动列表不得共用同一种行色',()=>{
  // 用户原话是"气象和班次要换颜色，不要一样的"。观测里"平平无奇的一站"在
  // observationTone 里是 normal（严重度口径，没错），但渲染到**气象**那张列表上
  // 时必须折成气象族的 calm —— 否则两张列表的大多数行跟班次那张一模一样。
  assert.equal(observationTone({visibilityM:9000,windMps:3}),'normal')
  assert.equal(tickerTone('观测','normal'),'calm')
  assert.equal(tickerTone('观测','warn'),'warn')
  assert.equal(tickerTone('观测','alert'),'alert')
  assert.equal(tickerTone('改航','cyan'),'cyan')
  const weather={observations:[{cityName:'沈阳',windMps:3,visibilityM:9000,tempC:10,weatherCode:0}],cells:[]}
  const flights=[{id:'F1',name:'班次一',detourMinutes:3,routeBasis:'RADAR_FIELD',routeBasisFromMinute:5}]
  const items=briefingTicker(weather,flights)
  const obs=items.find(i=>i.kind==='观测'),detour=items.find(i=>i.kind==='改航')
  assert.equal(obs.tone,'calm')
  assert.equal(detour.tone,'cyan')
  assert.notEqual(obs.tone,detour.tone,'气象行与班次行不许同色')
  for(const item of items){
    const family=item.kind==='改航'?'flight':'weather'
    assert.ok(toneFitsFamily(family,item.tone),`${item.title} 的 ${item.tone} 与 ${family} 族不符`)
  }
})

test('删掉「按回波改航」这个说法：判据不止回波一种',()=>{
  const flights=[{id:'a',status:'SCHEDULED',detourMinutes:5,delayMinutes:2}]
  const kpi=stageKpis(flights,{},null).find(k=>k.key==='detour')
  assert.equal(kpi.label,'受气象影响改航')
  assert.ok(!kpi.label.includes('回波'),'不得把改航归因给单一来源')
})

// ---------------------------------------------------------------------------
// 十一、舞台栅格的**子元素数 == 轨道数**（2026-10-11 首页地图全空的根因）
// ---------------------------------------------------------------------------
// 缺陷经过：`.hstage` 是固定高 1080 的 grid，`grid-template-rows` 四根轨道
// （64 / 92 / minmax(0,1fr) / 46）。有人新增了一行 `<p class="hs-drill-note">`
// 作为**直接子元素**却没加轨道 —— 它被自动排进第三根，也就是留给 `.hs-main`
// 三栏主区（地图所在地）的 `1fr`。于是一行 9.5px 的说明文字吃掉了 788px，
// 地图被挤进第四根 46px 的轨道里，canvas 再被 `overflow:hidden` 裁成一条缝。
//
// 为什么必须写成静态判据、而不是靠截图或版面探针：
//   · `vite build` 不跑布局 → 构建全绿；
//   · 337 条单测量的是 runtime.js 的语义 → 全绿；
//   · 版面探针 `_probe_workbench_layout.py` 服务的是 `frontend/dist` 旧快照，
//     且**没有任何一条判据量"主区那一格该有多高"** → 全绿。
//   「多出来的子元素静默抢轨道」属于「构建不会失败、只在屏幕上悄悄发生」那一类，
//   唯一能在合入前抓住它的地方就是源码结构本身。
//
// 这条判据红了之后的样子是明确的：告诉你 `.hstage` 有几个子元素、CSS 里有几根轨道，
// 差额就是被抢走的那一格 —— 而不是一条"主区太矮"的模糊提示。
const HOME_SRC=readFileSync(new URL('../src/components/traffic/HomeStage.vue',import.meta.url),'utf8')

// 数 `.hstage` 的直接子元素：**按标签深度数，不按缩进数**。
//
// 第一版我用了"4 空格缩进的 `<tag`"来数，结果把 `.hs-kpis`（缩进没跟着外层 wrapper
// 一起改）也数了进去，于是报出 6 个子元素 —— 判据红了，但**红的是判据自己**。
// 这正好是 §十六 那条："夹具/量具必须照抄被抓对象的真实形状"，而缩进**不是** DOM 深度：
// 本项目的模板里缩进是给人看的，不是结构的一部分。
//
// 所以改成真的走一遍嵌套：只认 `.hstage` 开标签那一层，遇到 `<tag…>` 深度 +1、
// 遇到 `</tag>` 深度 −1，深度为 0 时记录该标签。
// 顺带把 self-closing 与 void 元素排除掉（本项目模板里没有，但判据不该依赖"现在没有"）。
const VOID_TAGS=new Set(['br','hr','img','input','meta','link','source','area','base','col','embed','track','wbr'])

function directChildrenOfStage(src){
  const start=src.indexOf('<div class="hstage"')
  assert.ok(start>=0,'找不到 `.hstage` —— 判据的输入没了，必须报错而不是跳过')
  const open=src.indexOf('>',start)
  assert.ok(open>start,'`.hstage` 的开标签没有闭合')
  const rest=src.slice(open+1)
  const kids=[]
  let depth=0
  let i=0
  while(i<rest.length){
    const lt=rest.indexOf('<',i)
    if(lt<0)break
    if(rest.startsWith('<!--',lt)){
      const close=rest.indexOf('-->',lt)
      if(close<0)break
      i=close+3
      continue
    }
    const gt=rest.indexOf('>',lt)
    if(gt<0)break
    const raw=rest.slice(lt+1,gt)
    const closing=raw.startsWith('/')
    const nameMatch=/^\/?([a-zA-Z][\w-]*)/.exec(raw)
    if(!nameMatch){ i=gt+1; continue }
    const name=nameMatch[1].toLowerCase()
    const selfClosing=raw.endsWith('/')||VOID_TAGS.has(name)
    if(closing){
      // 深度为 0 时遇到的收尾标签就是 `.hstage` 自己的 —— 到此为止。
      // **不能**在"某一级回到 0"时停：一个直接子元素（如 `</header>`）
      // 正常收尾也会让深度回到 0，那是同级之间的分隔，不是舞台的结束。
      // 第一版就是在这里停早了，只读出一个 `hs-top`；自检当场报了出来。
      if(depth===0)break
      depth--
    }else{
      if(depth===0){
        const cls=/class="([^"]*)"/.exec(raw)
        kids.push({tag:name,cls:cls?cls[1]:''})
      }
      if(!selfClosing)depth++
    }
    i=gt+1
  }
  return kids
}

function stageTracks(src){
  const rowDecl=/\.hstage\{[^}]*grid-template-rows:([^;}]+)/.exec(src)
  assert.ok(rowDecl,'找不到 `.hstage` 的 grid-template-rows 声明')
  // 按空格切，但不要把 minmax(0,1fr) 这种带括号的一整个切开。
  return rowDecl[1].trim().split(/\s+(?![^()]*\))/).filter(Boolean)
}

test('.hstage 的直接子元素数必须等于 grid-template-rows 的轨道数',()=>{
  const kids=directChildrenOfStage(HOME_SRC)
  const tracks=stageTracks(HOME_SRC)
  // 自证：解析器至少要把已知的几块读出来。读不出来说明是**判据坏了**，
  // 而"判据坏了"必须与"被测对象有问题"报得不一样（M68）。
  //
  // 0.11.2：`hs-top` 按手册 §3.1.5 ① 整条删掉了（顶部让给内容），舞台现在是
  // **三根轨道**：结论条+数字（`hs-brief`）/ 主区（`hs-main`）/ 底栏（`hs-foot`）。
  // 这不是"判据放宽"：数量与轨道数的等式仍然在，只是已知清单跟着结构改。
  for(const known of ['hs-brief','hs-main','hs-foot']){
    assert.ok(kids.some(k=>k.cls.split(/\s+/).includes(known)),
      `解析器没读出已知的 .${known} —— 是判据自己坏了，不是舞台结构有问题。`
      +`读到的：${JSON.stringify(kids.map(k=>k.cls||k.tag))}`)
  }
  assert.equal(kids.length,tracks.length,
    `舞台有 ${kids.length} 个直接子元素 [${kids.map(k=>k.cls||k.tag).join(', ')}]，`
    +`但 grid-template-rows 只有 ${tracks.length} 根轨道 [${tracks.join(', ')}]。`
    +'多出来的子元素会**静默抢走**后一根轨道 —— 首屏地图全空就是这么发生的。'
    +'修法：让新块整体并入已有轨道（例如包一层 band），不要直接挂到 .hstage 下。')
})

test('主区（地图所在格）必须是舞台的弹性轨道，不得落到固定高度上',()=>{
  // 上一条只保证"数量对得上"，数量对上仍可能把顺序排错（例如把 1fr 换成 46px）。
  // 所以再钉一次**语义**：`.hs-main` 的位置对应的那根轨道必须是 minmax(0,1fr)。
  const kids=directChildrenOfStage(HOME_SRC)
  const idx=kids.findIndex(k=>k.cls.split(/\s+/).includes('hs-main'))
  assert.ok(idx>=0,'`.hs-main` 必须是 `.hstage` 的直接子元素')
  const tracks=stageTracks(HOME_SRC)
  assert.match(tracks[idx],/minmax\(0,1fr\)/,
    `主区落在第 ${idx+1} 根轨道（${tracks[idx]}）上 —— 它必须是 minmax(0,1fr)。`
    +'固定高度会让地图在窗口变高时不变、变矮时溢出，两种都表现为"版面错位"。')
})


