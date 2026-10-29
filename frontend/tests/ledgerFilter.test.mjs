import test from 'node:test'
import assert from 'node:assert/strict'
import {filterLedgerRows,flightState,dispositionSummary,delaySpread} from '../src/traffic/runtime.js'

// The ledger filter used to live inline in TrafficWorkbench.vue, where neither
// the node test runner nor the frame benchmark could reach it. Pulling it out is
// only safe if the row set it produces is unchanged, so these tests pin the
// behaviour the toolbar relied on.

function fleet(){
  return [
    {id:'CAR-1',name:'运输一号',mode:'CAR',fromCity:'shenyang',toCity:'dalian',status:'SCHEDULED',scheduledMinute:0,departureMinute:10,arrivalMinute:60},
    {id:'DEL-2',name:'配送二号',mode:'DELIVERY',fromCity:'shenyang',toCity:'shenyang',status:'SCHEDULED',scheduledMinute:0,departureMinute:5,arrivalMinute:20},
    {id:'DEL-3',name:'配送三号',mode:'DELIVERY',fromCity:'changchun',toCity:'dalian',status:'CLOSED',scheduledMinute:0,departureMinute:30,arrivalMinute:90},
    {id:'CAR-4',name:'Transport Four',mode:'CAR',fromCity:'changchun',toCity:'changchun',status:'SCHEDULED',scheduledMinute:60,departureMinute:100,arrivalMinute:150},
  ]
}

test('ledger filter defaults to showing every row',()=>{
  assert.equal(filterLedgerRows(fleet(),{}).length,4)
  assert.equal(filterLedgerRows(fleet()).length,4)
})

test('ledger filter hides the vehicle class whose layer is switched off',()=>{
  const ids=(rows)=>rows.map(r=>r.id)
  assert.deepEqual(ids(filterLedgerRows(fleet(),{showCar:false})),['DEL-2','DEL-3'])
  assert.deepEqual(ids(filterLedgerRows(fleet(),{showDelivery:false})),['CAR-1','CAR-4'])
  assert.deepEqual(ids(filterLedgerRows(fleet(),{showCar:false,showDelivery:false})),[])
})

test('ledger filter keeps a flight touching the chosen city at either end',()=>{
  const ids=(rows)=>rows.map(r=>r.id)
  // shenyang is the origin of CAR-1 and both ends of DEL-2.
  assert.deepEqual(ids(filterLedgerRows(fleet(),{city:'shenyang'})),['CAR-1','DEL-2'])
  // dalian is the destination of CAR-1 and DEL-3.
  assert.deepEqual(ids(filterLedgerRows(fleet(),{city:'dalian'})),['CAR-1','DEL-3'])
  assert.deepEqual(ids(filterLedgerRows(fleet(),{city:'nowhere'})),[])
})

test('ledger filter searches name and id case-insensitively',()=>{
  const ids=(rows)=>rows.map(r=>r.id)
  assert.deepEqual(ids(filterLedgerRows(fleet(),{search:'运输'})),['CAR-1'])
  // A lowercase query has to find the uppercase id.
  assert.deepEqual(ids(filterLedgerRows(fleet(),{search:'del-2'})),['DEL-2'])
  // ... and an uppercase query the mixed-case name.
  assert.deepEqual(ids(filterLedgerRows(fleet(),{search:'TRANSPORT'})),['CAR-4'])
  assert.deepEqual(ids(filterLedgerRows(fleet(),{search:'nothing-matches'})),[])
})

test('ledger filter status compares against the state at the current minute',()=>{
  const ids=(rows)=>rows.map(r=>r.id)
  // At minute 40: CAR-1 (10->60) is airborne; DEL-2 (5->20) has already arrived;
  // DEL-3 is closed; CAR-4 (departs 100, scheduled 60) is still PENDING.
  assert.deepEqual(ids(filterLedgerRows(fleet(),{status:'AIRBORNE',minute:40})),['CAR-1'])
  assert.deepEqual(ids(filterLedgerRows(fleet(),{status:'ARRIVED',minute:40})),['DEL-2'])
  assert.deepEqual(ids(filterLedgerRows(fleet(),{status:'CLOSED',minute:40})),['DEL-3'])
  assert.deepEqual(ids(filterLedgerRows(fleet(),{status:'PENDING',minute:40})),['CAR-4'])
  // Between the scheduled and the departure minute the same flight is HOLD.
  assert.deepEqual(ids(filterLedgerRows(fleet(),{status:'HOLD',minute:80})),['CAR-4'])
  assert.deepEqual(ids(filterLedgerRows(fleet(),{status:'PENDING',minute:80})),[])
  // The status branch is the only one that reads the clock, so it is checked
  // against `flightState` directly rather than against hand-written expectations.
  assert.equal(filterStateAgrees(5),true)
  assert.equal(filterStateAgrees(40),true)
  assert.equal(filterStateAgrees(80),true)
  assert.equal(filterStateAgrees(120),true)
})

// The status branch is the one that reads the clock, so it is checked against
// `flightState` directly rather than against a hand-written expectation. Rows are
// matched by `id`: the filter returns the objects it was handed, but `fleet()`
// builds a fresh array per call, so an identity comparison would report every row
// as absent no matter what the filter did.
function filterStateAgrees(minute){
  for(const status of ['AIRBORNE','CLOSED','PENDING','HOLD','ARRIVED']){
    const ids=new Set(filterLedgerRows(fleet(),{status,minute}).map(row=>row.id))
    for(const flight of fleet()){
      const matches=flightState(flight,minute)===status
      if(ids.has(flight.id)!==matches)return false
    }
  }
  return true
}

test('ledger filter combines class, city, search and status',()=>{
  const rows=filterLedgerRows(fleet(),{showCar:false,city:'shenyang',search:'配送',status:'AIRBORNE',minute:10})
  assert.deepEqual(rows.map(r=>r.id),['DEL-2'])
})

test('ledger filter tolerates a missing fleet instead of throwing',()=>{
  assert.deepEqual(filterLedgerRows(undefined,{}),[])
  assert.deepEqual(filterLedgerRows(null),[])
  assert.deepEqual(filterLedgerRows([],{search:'x'}),[])
})

// --- 2026-10-01 第 2 条：延迟优先的处置口径 ----------------------------------
// 用户要求「尽可能不要做禁飞处理，可以用延迟起飞来安排」。这条政策如果界面上
// 没有一处数得出来，演示时它就不可见 —— 关闭数下降会被读成运气，而不是处置顺序
// 的结果。下面钉住的就是那个"数得出来"的部分。

test('the disposition card separates delaying from detouring from closing',()=>{
  const text=dispositionSummary({accepted:7641,closed:119,detours:35,groundHolds:3514})
  assert.match(text,/时隙重排 3514/)
  assert.match(text,/改航绕飞 35/)
  assert.match(text,/停止放行 119/)
  // 放行率按 (放行)/(放行+关闭) 算，四舍五入到整数百分比。
  assert.match(text,/放行率 98%/)
  // 缺统计时不得编造数字。
  assert.equal(dispositionSummary(null),'等待计划')
  assert.equal(dispositionSummary({}),'等待计划')
})

test('the disposition card does not claim the three categories are exhaustive',()=>{
  // 一架可以既延迟又绕飞，所以三类是**互不排斥**的计数。这里断言的是文案没有
  // 写出"合计等于总数"这类只在特定天上成立的等式 —— 一个不成立的等式比没有
  // 汇总更糟，因为它会让操作员按错误的分母判断。
  const text=dispositionSummary({accepted:100,closed:0,detours:10,groundHolds:20})
  assert.doesNotMatch(text,/合计/)
  assert.doesNotMatch(text,/=/)
  assert.doesNotMatch(text,/共 \d+ 班/)
})

test('delay spread reports a median, not only the ceiling',()=>{
  // 「最多延迟 120 分钟」说的是上界，不是常态。中位数量才是判断这套处置是
  // "轻微错峰"还是"大面积推迟"的依据，所以它必须被算出来。
  const flights=[{delayMinutes:0},{delayMinutes:5},{delayMinutes:10},{delayMinutes:15},{delayMinutes:120}]
  const spread=delaySpread(flights)
  assert.equal(spread.count,4,'延迟为 0 的班次不计入延迟样本')
  // 样本 [5,10,15,120]，floor(4*0.5)=2 → 第 3 个值 15。这是"取偏上中位数"的定义，
  // 不是 10 —— 先把期望值算对再去断言，否则测的是自己的算术。
  assert.equal(spread.median,15)
  assert.equal(spread.max,120)
  // 空输入必须给出零值而不是 NaN —— NaN 会一路渲染成 "NaN 分"。
  const empty=delaySpread([])
  assert.deepEqual(empty,{count:0,median:0,p90:0,max:0})
  assert.deepEqual(delaySpread(null),{count:0,median:0,p90:0,max:0})
  // 缺字段的班次不得让统计崩掉。
  assert.equal(delaySpread([{},{delayMinutes:null}]).count,0)
})
