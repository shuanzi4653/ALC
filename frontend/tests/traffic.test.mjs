import test from 'node:test'
import assert from 'node:assert/strict'
import {atTime,flightState,profile,effectiveFlights,executionTimes,operationalTime,relativeClock} from '../src/traffic/runtime.js'
import {lngLat,geographicGeoJson} from '../src/traffic/geography.js'

test('manual commands replay without changing the frozen trajectory',()=>{
  const f={id:'f',status:'SCHEDULED',points:[[0,0,0,0]]}
  const ops=[{flightId:'f',minute:10,action:'SUSPEND'},{flightId:'f',minute:20,action:'RESUME'}]
  assert.equal(effectiveFlights([f],ops,9)[0],f)
  assert.equal(flightState(effectiveFlights([f],ops,15)[0],15),'CLOSED')
  assert.deepEqual(effectiveFlights([f],ops,15)[0].points,[])
  assert.deepEqual(effectiveFlights([f],ops,15)[0].plannedPoints,f.points)
  assert.equal(effectiveFlights([f],ops,20)[0],f)
  assert.equal(f.points.length,1)
})
test('map origin matches backend azimuthal projection',()=>{
  const ll=lngLat([0,0,500]);assert.ok(Math.abs(ll[0]-126)<1e-9);assert.ok(Math.abs(ll[1]-45)<1e-9)
})
test('traffic interpolation connects ground endpoints and ascends continuously',()=>{
  const p=[[0,0,0,0],[0,0,120,1],[1000,0,120,2],[1000,0,0,3]]
  assert.deepEqual(atTime(p,.5),[0,0,60]);assert.deepEqual(atTime(p,1.5),[500,0,120])
  assert.deepEqual(atTime(p,4),[1000,0,0]);assert.equal(atTime([],2),null)
  assert.ok(profile(p).startsWith('10,90'));assert.ok(profile(p).endsWith('290,90'))
})
test('scheduled, held, airborne and arrived states follow dispatch times',()=>{
  const f={status:'SCHEDULED',scheduledMinute:1,departureMinute:3,arrivalMinute:8}
  assert.equal(flightState(f,0),'PENDING');assert.equal(flightState(f,2),'HOLD')
  assert.equal(flightState(f,3),'AIRBORNE');assert.equal(flightState(f,8),'ARRIVED')
  assert.equal(flightState({...f,status:'CLOSED'},4),'CLOSED')
})
test('operational time separates planned and actual simulation events',()=>{
  const f={points:[[0,0,0,3],[1,1,0,8]],departureMinute:3,arrivalMinute:8,plannedReleaseAt:'2026-09-14T10:03:00Z',plannedTakeoffAt:'2026-09-14T10:03:00Z',estimatedArrivalAt:'2026-09-14T10:08:00Z'}
  assert.equal(executionTimes(f,2).actualReleaseAt,null)
  assert.equal(executionTimes(f,3).actualReleaseAt,f.plannedReleaseAt)
  assert.equal(executionTimes(f,8).actualArrivalAt,f.estimatedArrivalAt)
  assert.equal(relativeClock(65.5),'T+01:05:30')
  assert.match(operationalTime('2026-09-14T10:03:00Z',3),/18:03:00/)
})

// ---- 2026-10-11 「未知红线」的回归守卫 -------------------------------
// 用户报「怎么有未知红线」：地图上出现两条横跨全幅的红带。根因是
// `routes[].referencePath` 是**本地米制**坐标（`backend-python/traffic/service.py`
// 用 `route(first_pad['xy'], …)` 造出来），而画布把它们当**经纬度**交给 MapLibre，
// `lon=-381319` 被钳到世界边界 → 一条横跨全图的红线。
//
// 判据选的是**转换本身**（`geographicGeoJson` 必须把米制搬到经纬度），
// 而不是「屏幕上没有红线」——后者需要跑浏览器，而这些用例要在 `node --test` 里跑。

test('geographicGeoJson converts bare meter geometry to lng/lat',()=>{
  // 米制原点（AEQD 的 lat_0/lon_0）应回到 (126,45)，与 lngLat 的契约一致。
  const out=geographicGeoJson({type:'LineString',coordinates:[[0,0],[1000,0]]})
  assert.equal(out.type,'LineString')
  assert.ok(Math.abs(out.coordinates[0][0]-126)<1e-9,`expected lon 126, got ${out.coordinates[0][0]}`)
  assert.ok(Math.abs(out.coordinates[0][1]-45)<1e-9)
})

test('geographicGeoJson recurses through FeatureCollection and Feature',()=>{
  // 这正是当初的坑：`geographicGeometry` 读 `geometry.coordinates`，
  // 而图层载荷是 FeatureCollection（有 features、没有 coordinates）→
  // 直接喂进去会得到 `coordinates: undefined` 的空壳，MapLibre 画成「什么都没有」（不报错）。
  const fc={type:'FeatureCollection',features:[
    {type:'Feature',properties:{k:'a'},geometry:{type:'LineString',coordinates:[[0,0],[1000,0]]}},
    {type:'Feature',properties:{k:'b'},geometry:{type:'Point',coordinates:[[2000,0]]}},
  ]}
  const out=geographicGeoJson(fc)
  assert.equal(out.type,'FeatureCollection')
  assert.equal(out.features.length,2)
  // 逐个要素都必须真的转过，而不是只改了最外层。
  for(const f of out.features){
    assert.equal(f.geometry.type!=='GeometryCollection',true)
    assert.ok(Math.abs(f.geometry.coordinates[0][0]-126)<1,`lon not converted: ${f.geometry.coordinates[0][0]}`)
  }
  // 属性必须原样保留（入口判据要读 properties.key）。
  assert.equal(out.features[0].properties.k,'a')
})

test('geographicGeoJson passes through non-geometry input unchanged',()=>{
  // 缺席/空值不能变成异常，也不能变成空几何。
  assert.equal(geographicGeoJson(null),null)
  assert.equal(geographicGeoJson(undefined),undefined)
  const empty={type:'FeatureCollection',features:[]}
  assert.deepEqual(geographicGeoJson(empty),empty)
})

test('geographicGeoJson keeps a raw meter path out of lng/lat range until converted',()=>{
  // 反向对照（M29）：同一串米制坐标，**不转**时确实超出经纬度定义域，
  // **转了**才落进 [−180,180]/[−90,90]。这条让「忘记转换」这件事本身变成可判定的。
  const meters=[[-381319,0],[0,0]]
  const rawOk=meters.every(([x,y])=>Math.abs(x)<=180&&Math.abs(y)<=90)
  assert.equal(rawOk,false,'米制坐标不应落在经纬度定义域内 —— 若为真，这条对照就失效了')
  const converted=geographicGeoJson({type:'LineString',coordinates:meters})
  const ok=converted.coordinates.every(([x,y])=>Math.abs(x)<=180&&Math.abs(y)<=90)
  assert.equal(ok,true,`转换后仍在定义域外：${JSON.stringify(converted.coordinates)}`)
})
