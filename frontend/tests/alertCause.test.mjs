import test from 'node:test'
import assert from 'node:assert/strict'
import {groupAlerts,weatherClosureReasons,closureShortNames} from '../src/traffic/runtime.js'

// 预警中心 · 事件处置台（0.9.26 / P0-3）。
//
// 这一页要回答的是老师那句抱怨里**可核对**的一半：「一到预警中心里就有很多红的
// 『停止放行』的」。红色里有多少是气象造成的 —— 这个问题以前没有出口，而
// `README.md` §0.9.14 的实测是 `closed=123`、`closedByWeather=0`。
//
// 本文件钉住三件事，每一件都是"错了两边都看不出来"的那一类：
//
//   ① 分组键与写进运行日志的 `eventKey` 必须**逐字相同**。差一个字符，处置状态会挂到
//      一条谁也不认识的事件上 —— 页面只会永远显示「待确认」，不报错；
//   ② 「气象成因」的成员资格只由 `weatherClosureReasons` 决定。把「超出推演时段」
//      算进去，就会把晴天一样会发生的事记到气象账上，而这个数字正是本页存在的理由；
//   ③ 排序是确定的：关闭在前、气象在前、影响面在前。同一条走廊上的两班不能因为
//      渲染顺序不同而换位置 —— 读者会以为计划变了。

const flight=(over={})=>({id:'f1',routeId:'r1',reason:'CLEAR',status:'SCHEDULED',name:'一班',
  delayMinutes:0,detourMinutes:0,fromCity:'大连',toCity:'沈阳',...over})

test('the grouping key is byte-for-byte the event key the journal stores',()=>{
  // 后端 `note_disposal` 收的 `eventKey` 就是这个字符串。键不一致不会报错，
  // 只会让处置按钮永远停在「待确认」。
  const closed=groupAlerts([flight({status:'CLOSED',reason:'WEATHER_BLOCKED'})])
  assert.equal(closed.rows[0].key,'r1:WEATHER_BLOCKED:true')
  // 非关闭事件也用同一个模板（布尔要落成 'true'/'false'，不能落成 1/0 或空串）。
  const delayed=groupAlerts([flight({delayMinutes:5})])
  assert.equal(delayed.rows[0].key,'r1:CLEAR:false')
})

test('only the weather closure codes count as weather causes',()=>{
  const result=groupAlerts([
    flight({id:'a',routeId:'r1',status:'CLOSED',reason:'WEATHER_BLOCKED'}),
    flight({id:'b',routeId:'r2',status:'CLOSED',reason:'BEYOND_PLANNING_HORIZON'}),
    flight({id:'c',routeId:'r3',status:'CLOSED',reason:'SEPARATION_RESOURCE_OR_TIME_LIMIT'}),
  ])
  assert.equal(result.total,3)
  assert.equal(result.weatherEvents,1)
  assert.equal(result.nonWeatherEvents,2)
  assert.equal(result.closedFlights,3)
  assert.equal(result.weatherClosedFlights,1)
  // 成员资格是**同一个集合**，不是另写一份近似规则。
  assert.ok(weatherClosureReasons.has('WEATHER_BLOCKED'))
  assert.ok(!weatherClosureReasons.has('BEYOND_PLANNING_HORIZON'))
})

test('a flight with no delay, no detour and no closure is not an event',()=>{
  // 直飞放行的班次不该出现在预警中心。它一旦混进来，分布条的分母就没有意义了。
  const result=groupAlerts([flight({id:'x'}),flight({id:'y',delayMinutes:3})])
  assert.equal(result.total,1)
  assert.equal(result.totalFlights,1)
})

test('same corridor, cause and closure state merge into one event',()=>{
  const result=groupAlerts([
    flight({id:'a',status:'CLOSED',reason:'WEATHER_BLOCKED',fromCity:'大连',toCity:'沈阳'}),
    flight({id:'b',status:'CLOSED',reason:'WEATHER_BLOCKED',fromCity:'大连',toCity:'沈阳'}),
    flight({id:'c',status:'CLOSED',reason:'WEATHER_BLOCKED',fromCity:'大连',toCity:'丹东'}),
  ])
  assert.equal(result.total,1)
  assert.equal(result.rows[0].count,3)
  assert.equal(result.rows[0].closedCount,3)
  // 走廊最多留 4 条（入口不是台账），但两条不同走廊都要出现。
  assert.deepEqual(result.rows[0].corridors,['大连 → 沈阳','大连 → 丹东'])
})

test('closed events come first, weather before non-weather, then by impact',()=>{
  const rows=groupAlerts([
    flight({id:'a',routeId:'r1',status:'CLOSED',reason:'BEYOND_PLANNING_HORIZON'}),
    flight({id:'b',routeId:'r2',status:'CLOSED',reason:'WEATHER_BLOCKED'}),
    flight({id:'c',routeId:'r3',delayMinutes:4}),
    flight({id:'d',routeId:'r4',detourMinutes:6}),
    flight({id:'e',routeId:'r4',detourMinutes:6}),
  ]).rows
  assert.deepEqual(rows.map(row=>row.key),
    ['r2:WEATHER_BLOCKED:true','r1:BEYOND_PLANNING_HORIZON:true','r4:CLEAR:false','r3:CLEAR:false'])
})

test('every event carries a cause phrase and a disposal suggestion',()=>{
  // 成因短语用**精简名**（卡片宽度），句子用完整名；两者都不能是空串 ——
  // 空串在界面上表现为一块空白，读者会以为这一栏"没有内容"而不是"没人写"。
  const row=groupAlerts([flight({status:'CLOSED',reason:'NO_GEOMETRIC_PATH'})]).rows[0]
  assert.equal(row.short,closureShortNames.NO_GEOMETRIC_PATH)
  assert.equal(row.name,'边界内无可用路径')
  assert.ok(row.advice.length>0)
  // 这条建议必须点明"这不是气象结论"——否则它会被记到气象账上。
  assert.ok(row.advice.includes('几何'))
  assert.equal(row.weather,false)
})
