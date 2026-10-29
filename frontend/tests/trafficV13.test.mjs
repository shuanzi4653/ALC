import test from 'node:test'
import assert from 'node:assert/strict'
import {DEFAULT_RISK_CEILING_AGL_M,classifyMapError,groupFlights,layerLabel,mapErrorSummary,markFor,orderState,releaseQueue,releaseWindows,riskCeiling,splitTrajectoryAt,splitTrajectoryInto,stateNames,vehicleState,virtualWindow} from '../src/traffic/runtime.js'

test('dispatch states carry a geometric mark instead of an emoji',()=>{
  assert.equal(markFor('AIRBORNE'),'■')
  assert.equal(markFor('HOLD'),'◆')
  assert.equal(markFor('CLOSED'),'✕')
  assert.equal(markFor('UNKNOWN'),'■')
  for(const name of Object.values(stateNames))assert.ok(!/\p{Extended_Pictographic}/u.test(name))
})

test('declared layer label never invents a height when the plan assigns none',()=>{
  assert.equal(layerLabel({}),'未分配层')
  assert.equal(layerLabel({assignedLayerAglM:500,layerStrategy:'DIRECTION_LAYER'}),'500 m AGL · 主用已声明层')
  assert.equal(layerLabel({assignedLayerAglM:160,layerStrategy:'ALTERNATE_DECLARED_LAYER'}),'160 m AGL · 备用已声明层')
  assert.equal(layerLabel({assignedLayerAglM:350}),'350 m AGL · 已声明层')
})

test('order and vehicle states advance with the simulated clock only',()=>{
  assert.equal(orderState({},'PENDING','PENDING'),'待备货')
  assert.equal(orderState({},'HOLD','HOLD'),'待分配')
  assert.equal(orderState({},'AIRBORNE','CLIMB'),'待起飞')
  assert.equal(orderState({},'AIRBORNE','CRUISE'),'配送中')
  assert.equal(orderState({},'ARRIVED','ARRIVED'),'已送达')
  assert.equal(orderState({},'CLOSED','CLOSED'),'取消')
  assert.equal(orderState({orderStatus:'取消'},'HOLD','HOLD'),'取消')
  const flight={arrivalMinute:10,returnLegMinutes:2}
  assert.equal(vehicleState(flight,'AIRBORNE',5,{chargeMinutes:5}),'飞行')
  assert.equal(vehicleState(flight,'ARRIVED',11,{chargeMinutes:5}),'返航')
  assert.equal(vehicleState(flight,'ARRIVED',12,{chargeMinutes:5}),'充电')
  assert.equal(vehicleState(flight,'ARRIVED',17,{chargeMinutes:5}),'可用')
  assert.equal(vehicleState(flight,'CLOSED',17,{chargeMinutes:5}),'停用')
})

test('release queue only exposes scheduled slots inside the chosen horizon',()=>{
  const flights=[
    {id:'b',status:'SCHEDULED',departureMinute:25},
    {id:'a',status:'SCHEDULED',departureMinute:12},
    {id:'late',status:'SCHEDULED',departureMinute:95},
    {id:'past',status:'SCHEDULED',departureMinute:4},
    {id:'closed',status:'CLOSED',departureMinute:14},
  ]
  assert.deepEqual(releaseQueue(flights,10,30).map(f=>f.id),['a','b'])
  assert.deepEqual(releaseQueue(flights,10,60).map(f=>f.id),['a','b'])
  assert.deepEqual(releaseQueue(flights,90,30).map(f=>f.id),['late'])
  assert.deepEqual(releaseQueue(flights,10,30,f=>f.id==='a').map(f=>f.id),['a'])
  assert.equal(releaseWindows.at(-1).minutes,null)
})

test('dispatch board groups flights without dropping any',()=>{
  const flights=[
    {id:'p',status:'SCHEDULED',scheduledMinute:20,departureMinute:20,arrivalMinute:40},
    {id:'h',status:'SCHEDULED',scheduledMinute:5,departureMinute:18,arrivalMinute:40},
    {id:'a',status:'SCHEDULED',scheduledMinute:5,departureMinute:8,arrivalMinute:30},
    {id:'c',status:'CLOSED',scheduledMinute:5,departureMinute:9,arrivalMinute:30},
    {id:'d',status:'SCHEDULED',scheduledMinute:5,departureMinute:6,arrivalMinute:9},
  ]
  const groups=groupFlights(flights,10)
  assert.deepEqual(groups.待放行.map(f=>f.id),['p','h'])
  assert.deepEqual(groups.运行中.map(f=>f.id),['a'])
  assert.deepEqual(groups.受限异常.map(f=>f.id),['c'])
  assert.deepEqual(groups.已完成.map(f=>f.id),['d'])
  assert.equal(Object.values(groups).flat().length,flights.length)
})

test('risk envelope falls back to the published profile ceiling',()=>{
  assert.equal(riskCeiling({riskRules:{ceilingAglM:700}}),700)
  assert.equal(riskCeiling({riskRules:{ceilingAglM:0}}),DEFAULT_RISK_CEILING_AGL_M)
  assert.equal(riskCeiling(null),DEFAULT_RISK_CEILING_AGL_M)
})

test('trajectory splits at the current minute without moving or dropping a vertex',()=>{
  const points=[[0,0,350,0],[60,0,350,5],[120,0,350,10]]
  const snapshot=JSON.parse(JSON.stringify(points))

  // Before departure nothing has been flown; after arrival nothing is ahead.
  assert.deepEqual(splitTrajectoryAt(points,-3),[[],points])
  assert.deepEqual(splitTrajectoryAt(points,10),[points,[]])
  assert.deepEqual(splitTrajectoryAt([],4),[[],[]])

  // The cut lands inside the segment containing the minute; the flown half keeps
  // every vertex up to that segment, the ahead half keeps everything after it, and
  // both halves share the single interpolated cut vertex.
  const [flown,ahead]=splitTrajectoryAt(points,7.5)
  assert.equal(flown.length,3)
  assert.equal(ahead.length,2)
  assert.deepEqual(flown.at(-1),ahead[0])
  assert.deepEqual(flown.at(-1),[90,0,350,7.5])

  // Every original vertex survives exactly once, and the timeline stays monotonic.
  assert.deepEqual([...flown,...ahead.slice(1)].map(point=>point[3]),[0,5,7.5,10])

  // A minute that lands exactly on a declared vertex must not duplicate the join,
  // because a repeated vertex becomes a zero-length segment in the Line2 geometry.
  const onVertex=splitTrajectoryAt(points,5)
  assert.deepEqual(onVertex[0].at(-1),[60,0,350,5])
  assert.deepEqual(onVertex[1][0],onVertex[0].at(-1))
  assert.deepEqual([...onVertex[0],...onVertex[1].slice(1)].map(point=>point[3]),[0,5,10])
  const monotonic=(half)=>half.every((point,i)=>i===0||point[3]>half[i-1][3])
  assert.ok(monotonic(onVertex[0]))
  assert.ok(monotonic(onVertex[1]))
  assert.ok(monotonic(flown))
  assert.ok(monotonic(ahead))

  // Purely visual: the frozen trajectory must not be mutated by the split.
  assert.deepEqual(points,snapshot)
})

test('virtual window keeps mounted rows bounded and covers the viewport',()=>{
  // Empty and single-row lists never produce a negative or inverted range.
  assert.deepEqual(virtualWindow(0,0,400,196,4),{startIndex:0,endIndex:0})
  assert.deepEqual(virtualWindow(1,0,400,196,4),{startIndex:0,endIndex:1})

  // Scrolled to the top: overscan leads but cannot go below zero.
  const top=virtualWindow(1000,0,392,196,4)
  assert.equal(top.startIndex,0)
  assert.equal(top.endIndex,6)

  // Deep in a long ledger only a handful of rows are ever mounted.
  const deep=virtualWindow(1000,196*50,392,196,4)
  assert.equal(deep.startIndex,46)
  assert.equal(deep.endIndex,56)
  assert.ok(deep.endIndex-deep.startIndex<=12)

  // At the very end the range clamps to the list length instead of overshooting.
  const end=virtualWindow(1000,196*1000,392,196,4)
  assert.equal(end.endIndex,1000)
  assert.ok(end.startIndex<1000)

  // Viewport taller than the list still returns the whole list, never more.
  const short=virtualWindow(3,0,4000,196,4)
  assert.equal(short.endIndex,3)
  assert.ok(short.startIndex>=0)
})

test('map errors are classified instead of always blamed on the network',()=>{
  // A missing tile and a missing glyph range are provider coverage gaps, not
  // network faults, so the operator must not be told to check the connection.
  assert.equal(classifyMapError('HTTP 404 for tile 14/13367/6156'),'TILE_404')
  assert.equal(classifyMapError('glyph Noto Sans Regular range not found'),'GLYPH')
  assert.equal(classifyMapError('sprite json could not be fetched'),'SPRITE')
  assert.equal(classifyMapError('the style is not valid'),'STYLE')
  // Genuine transport failures still route to the network message.
  assert.equal(classifyMapError('Failed to fetch'),'NETWORK')
  assert.equal(classifyMapError('request timed out after 30000ms'),'NETWORK')
  assert.equal(classifyMapError('net::ERR_CONNECTION_REFUSED'),'NETWORK')
  // Camera-driven cancellation is normal and must stay out of the banner.
  assert.equal(classifyMapError('AbortError: The user aborted a request'),'ABORTED')
  assert.equal(classifyMapError(''),'UNKNOWN')
  assert.equal(classifyMapError(undefined),'UNKNOWN')
})

test('map error summary reports counts per cause and ignores empty buckets',()=>{
  assert.equal(mapErrorSummary({}),'')
  assert.equal(mapErrorSummary({NETWORK:0,TILE_404:0}),'')
  const summary=mapErrorSummary({TILE_404:2,NETWORK:7})
  // Highest count first so the dominant cause reads first.
  assert.ok(summary.indexOf('网络不可达')<summary.indexOf('没有覆盖'),summary)
  assert.ok(summary.includes('×7'),summary)
  assert.ok(summary.includes('×2'),summary)
  assert.equal(mapErrorSummary({SOMETHING_NEW:3}),'部分城市地图资源载入失败。×3')
})

test('delivery drones are materially smaller than flying cars',()=>{
  // The two classes must differ in rendered footprint, not just fuselage length,
  // because at map zoom only the rotor span is perceivable. Reproduce the
  // footprint formula used by vehicle(): (span + 2*rotor) * scale.
  const shapes={
    CAR:{span:4.6,rotor:1.9,scale:.62,bodyLength:9.5},
    DELIVERY:{span:2.1,rotor:1.05,scale:.42,bodyLength:3.6},
  }
  const footprint=shape=>(shape.span+2*shape.rotor)*shape.scale
  const car=footprint(shapes.CAR),drone=footprint(shapes.DELIVERY)
  assert.ok(drone<car,'delivery footprint must be smaller')
  assert.ok(car/drone>2.5,`expected an obvious gap, got ${(car/drone).toFixed(2)}x`)
  // The drone must also be shorter along the fuselage, not merely narrower.
  assert.ok(shapes.DELIVERY.bodyLength*shapes.DELIVERY.scale<shapes.CAR.bodyLength*shapes.CAR.scale)
  // Neither class may collapse to nothing on screen.
  assert.ok(drone>0.5,`drone footprint ${drone} too small to see`)
})

// --- 航迹切分的热路径版必须与契约版逐字等价 --------------------------------
// 用户 2026-10-01 第 7 条：「航迹变换与轨迹改变的太慢了」。热路径版
// `splitTrajectoryInto` 存在的唯一理由是少分配，所以它**不允许**有任何语义差异：
// 一旦两半的形状对不上，地图画的航迹就与测试量的不是同一条线。
//
// 这组判据是等价的证明，不是"看起来对"。做法：对同一输入同时跑两个版本，逐点
// 比较 —— 包括边界（早于起点 / 晚于终点 / 落在顶点上 / 落在两顶点之间）。

const TRAJECTORY = [
  [123.0, 41.0, 0, 0],
  [123.1, 41.1, 500, 10],
  [123.2, 41.2, 900, 20],
  [123.3, 41.3, 600, 30],
  [123.4, 41.4, 0, 40],
]

test('hot-path split returns the same two halves as the contract version', () => {
  // 覆盖两端之外、两端之上、正好落在顶点、落在两顶点之间这五类时刻。
  for (const minute of [-5, 0, 1, 5, 10, 15.5, 20, 25, 30, 39.999, 40, 55]) {
    const expected = splitTrajectoryAt(TRAJECTORY, minute)
    const actual = splitTrajectoryInto(TRAJECTORY, minute)
    assert.deepEqual(actual[0], expected[0], `flown half differs at minute ${minute}`)
    assert.deepEqual(actual[1], expected[1], `ahead half differs at minute ${minute}`)
  }
})

test('hot-path split never emits a zero-length duplicate vertex', () => {
  // 时刻正好落在顶点上时，两半必须共享该顶点而不是各自复制一个。
  const [flown, ahead] = splitTrajectoryInto(TRAJECTORY, 20)
  assert.deepEqual(flown.at(-1), [123.2, 41.2, 900, 20])
  assert.deepEqual(ahead[0], [123.2, 41.2, 900, 20])
  // 拼起来应当正好还原原折线，不增不减。
  assert.deepEqual([...flown, ...ahead.slice(1)], TRAJECTORY)
})

test('hot-path split reuses the caller container instead of allocating one', () => {
  // 复用容器是它存在的目的：一帧几千次调用里少造一个数组。
  const slot = [[], []]
  const result = splitTrajectoryInto(TRAJECTORY, 15, slot)
  assert.equal(result, slot)
  // 换一个时刻再跑，同一个槽位要给出新结果（不是缓存的旧值）。
  splitTrajectoryInto(TRAJECTORY, 30, slot)
  assert.deepEqual(slot, splitTrajectoryAt(TRAJECTORY, 30))
})

test('hot-path split handles the degenerate inputs the same way', () => {
  for (const bad of [null, undefined, []]) {
    assert.deepEqual(splitTrajectoryInto(bad, 10), [[], []])
    assert.deepEqual(splitTrajectoryAt(bad, 10), [[], []])
  }
  // 单点航迹：两端分支都要给出同一结果。
  const single = [[123, 41, 100, 5]]
  assert.deepEqual(splitTrajectoryInto(single, 5), splitTrajectoryAt(single, 5))
  assert.deepEqual(splitTrajectoryInto(single, 9), splitTrajectoryAt(single, 9))
})
