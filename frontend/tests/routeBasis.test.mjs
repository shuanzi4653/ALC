import test from 'node:test'
import assert from 'node:assert/strict'
import {routeBasisNames,WEATHER_ROUTE_BASES,isWeatherDetour,weatherDetourRows,
        nonWeatherRouteRows,routeBasisNote,stageKpis,briefingTicker}
  from '../src/traffic/runtime.js'

// 用户 2026-10-03：「他的轨迹我知道是之前的受气象影响的……明明他直飞的路线没有气象
// 干扰为什么不变。」要回答这句话，屏幕必须能说出**这条航路是为谁而弯的**。
//
// 后端为此发布了 `routeBasis`（成因）与 `routeBasisFromMinute`（从第几分钟起）。
// 本文件钉住前端这一侧的三件事，逐条都是"两种说法会不会悄悄分家"：
//
//   ① 名字表与后端 `service.ROUTE_BASIS` 是同一张表（漏一个代码 = 某个成因在屏幕上
//      没有名字，而它会怎么显示取决于 `undefined` 掉进哪个模板）；
//   ② 「受气象影响改航」的成员资格**只由成因决定**，不由 `detourMinutes` 决定 ——
//      第三版之前用的是长度阈值，而长度是几何差异的代理量，于是实测通道里 42 班
//      **作业区边界**逼出来的绕行被记成了气象改航；
//   ③ 显示口径只有一处（M59：过滤用一个精度、显示用另一个精度，屏幕上就会出现
//      自相矛盾的行）。

test('the name table carries every code the backend can publish',()=>{
  // 与 `backend-python/traffic/service.py::ROUTE_BASIS` 逐字对应。这是**契约**，
  // 不是"再加一个也行"的字典：多一个代码而无名字，那一类成因就会在界面上变成空白。
  //
  // `LOW_VISIBILITY` 是 0.9.27 新增的：低能见度（雾）自成一条派生通道，与
  // `POINT_WEATHER` 同源不同层。它的名字必须在这里，否则一条因雾而弯的航迹会
  // 在屏幕上没有成因 —— 而那正是用户报「不知道原因关闭」的那类现象。
  const backendCodes=['CLEAR','STATIC_AIRSPACE','POINT_WEATHER','LOW_VISIBILITY','RADAR_CORE','RADAR_FIELD','BOUNDARY']
  assert.deepEqual(Object.keys(routeBasisNames).sort(),[...backendCodes].sort())
  for(const code of backendCodes)assert.ok(routeBasisNames[code],`${code} 必须有名字`)
  // 气象类与后端 `service.WEATHER_BASIS` 是同一组，且**不含**固定管制区与作业区边界。
  assert.deepEqual([...WEATHER_ROUTE_BASES].sort(),
                   ['POINT_WEATHER','LOW_VISIBILITY','RADAR_CORE','RADAR_FIELD'].sort())
  assert.ok(WEATHER_ROUTE_BASES.includes('LOW_VISIBILITY'),
    '低能见度必须算气象 —— 漏掉它，因雾改航的班次不计入"受气象影响改航"，只在报表上错')
  assert.ok(!WEATHER_ROUTE_BASES.includes('STATIC_AIRSPACE'))
  assert.ok(!WEATHER_ROUTE_BASES.includes('BOUNDARY'))
})

test('membership follows the cause, not the length delta',()=>{
  // 负向对照与正向各一，两条都在同一个缺陷的两侧：
  //   · 长度显著变大（5 分钟）但成因是作业区边界 → **不算**气象改航。
  //     这正是实测通道里 42 班的形状；若这里返回 true，等于把边界约束记到气象账上。
  //   · 长度增加为 0（成因回波贴着走廊，绕行后航程几乎没变）但成因是回波 → **算**。
  //     若这里返回 false，一个真的被气象推移过航路的班次会从榜上消失。
  const boundary={id:'B',routeBasis:'BOUNDARY',detourMinutes:5}
  const echo={id:'E',routeBasis:'RADAR_FIELD',detourMinutes:0,routeBasisFromMinute:10}
  assert.equal(isWeatherDetour(boundary),false)
  assert.equal(isWeatherDetour(echo),true)
  assert.deepEqual(weatherDetourRows([boundary,echo]).map(f=>f.id),['E'])
  assert.deepEqual(nonWeatherRouteRows([boundary,echo]).map(f=>f.id),['B'])
  // `CLEAR` 两边都不进：它不是"另一种成因"，它是"没有成因"。
  assert.deepEqual(nonWeatherRouteRows([{routeBasis:'CLEAR',detourMinutes:9}]),[])
  // 老计划（发布这个字段之前）没有成因，不能因此把它算成气象改航。
  assert.equal(isWeatherDetour({detourMinutes:9}),false)
  assert.equal(isWeatherDetour(null),false)
})

test('the reason label and the basis must not be able to disagree',()=>{
  // 这是 ⑭「把包含关系写成断言」：同一件事在后端有 `reason` 与 `routeBasis` 两个
  // 说法，如果只在注释里说"它们一致"，下一次改后端时它们就会分家，而分家的表现是
  // 「台账说气象改航、地图说作业区边界」—— 两个都对，读者无从判断。
  const fleet=[
    {id:'a',reason:'CLEAR',routeBasis:'CLEAR'},
    {id:'b',reason:'CLEAR',routeBasis:'BOUNDARY'},
    {id:'c',reason:'CLEAR',routeBasis:'STATIC_AIRSPACE'},
    {id:'d',reason:'WEATHER_DETOUR',routeBasis:'POINT_WEATHER'},
    {id:'e',reason:'WEATHER_DETOUR',routeBasis:'RADAR_CORE'},
    {id:'f',reason:'WEATHER_DETOUR',routeBasis:'RADAR_FIELD'},
  ]
  for(const f of fleet){
    assert.equal(f.reason==='WEATHER_DETOUR',isWeatherDetour(f),
                 `${f.id}: reason 与 routeBasis 不一致`)
  }
})

test('a cause without a minute says so instead of pretending to be minute zero',()=>{
  // `routeBasisFromMinute` 为 null 的成因（固定管制区 / 风险区核心 / 作业区边界）是
  // 整段窗口内一直成立的事实。写成 `T+00:00:00 起` 就是 M30：两种世界共用一个读数。
  assert.equal(routeBasisNote({routeBasis:'BOUNDARY',routeBasisFromMinute:null}),
               '成因：作业区边界（全时段）')
  assert.equal(routeBasisNote({routeBasis:'STATIC_AIRSPACE'}),
               '成因：固定管制区（全时段）')
  // 有分钟时按同一套相对时刻口径显示（与地图时间轴上的读数同源）。
  assert.equal(routeBasisNote({routeBasis:'RADAR_FIELD',routeBasisFromMinute:50}),
               '成因：雷达 ≥35 dBZ 场（T+00:50:00 起）')
  // 第 0 分钟**是**一个分钟，不能因为它是 0 就被当成"没有分钟"。
  assert.equal(routeBasisNote({routeBasis:'RADAR_CORE',routeBasisFromMinute:0}),
               '成因：雷达 ≥45 dBZ 内核（T+00:00:00 起）')
  // 未知代码不编句子：宁可空，也不要一句读上去像结论的话。
  assert.equal(routeBasisNote({routeBasis:'SOMETHING_NEW'}),'')
  assert.equal(routeBasisNote({}),'')
})

test('the KPI and the panel count the same thing, and the empty panel explains itself',()=>{
  const flights=[
    {id:'car-1',mode:'CAR',status:'SCHEDULED',reason:'CLEAR',routeBasis:'BOUNDARY',detourMinutes:5},
    {id:'car-2',mode:'CAR',status:'SCHEDULED',reason:'CLEAR',routeBasis:'STATIC_AIRSPACE',detourMinutes:2},
    {id:'car-3',mode:'CAR',status:'SCHEDULED',reason:'WEATHER_DETOUR',routeBasis:'RADAR_FIELD',detourMinutes:0},
    {id:'car-4',mode:'CAR',status:'SCHEDULED',reason:'CLEAR',routeBasis:'CLEAR',detourMinutes:0},
  ]
  const kpi=stageKpis(flights,{},{}).find(row=>row.key==='detour')
  // 只有 car-3 是气象改航。car-1/car-2 长度更大但成因不是气象 —— 归因问题就在这里。
  assert.equal(kpi.value,1)
  // 榜与 KPI 读同一个集合：两处各写一遍筛选条件，就是"同一常量两份副本"。
  const panel=briefingTicker({},flights).filter(item=>item.kind==='改航')
  assert.deepEqual(panel.map(item=>item.id),['FL-car-3'])
  assert.match(panel[0].foot,/成因：雷达 ≥35 dBZ 场/)

  // 空榜不是一句话：非气象成因的绕行必须被说出来，否则用户看着一屏弯航迹会觉得
  // 系统没在工作（2026-10-03 那句「为什么不变」就是这么来的）。
  const onlyBoundary=stageKpis(flights.slice(0,2),{},{}).find(row=>row.key==='detour')
  assert.equal(onlyBoundary.value,0)
  assert.match(onlyBoundary.note,/另有 2 班/)
  assert.match(onlyBoundary.note,/非气象约束/)
  // 完全没有改航时回到原来那句，不要凭空多出一个"另有 0 班"。
  const none=stageKpis([flights[3]],{},{}).find(row=>row.key==='detour')
  assert.equal(none.value,0)
  assert.ok(!/另有/.test(none.note),none.note)
})
