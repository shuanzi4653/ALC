import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import {RADAR_SOURCE,RADAR_SOURCE_SYNTHETIC,RADAR_STATE,RADAR_PENDING_TIMEOUT_MS,radarUnavailable,criterionValueText,visibilityText,formatRadarSlot,geometryLooksGeographic,radarBandRow,radarFeatureGeometry,radarIsVirtual,radarLabels,radarLabelsFor,radarLabelsVirtual,radarSource,radarState,radarSummaryText,radarSurfaces,radarFrozenNote,fixedZoneFrozenNote,weatherBucket,weatherBucketChanged} from '../src/traffic/runtime.js'
import {feature,geographicGeometry} from '../src/traffic/geography.js'

// Frames shaped exactly as `service.radar_regions()` publishes them. The
// frontend had no consumer at all before this, so these fixtures are the only
// thing standing between the payload and a silent mismatch.
const polygon={type:'Polygon',coordinates:[[[126,45],[127,45],[127,46],[126,46],[126,45]]]}
const hazardFrame={
  available:true,error:null,
  summary:{channel:'CMA_RADAR_TILES',drivesGeometry:true,available:true,
    slot:'2026-09-18T07:18:00Z',slotAgeMinutes:3.3,
    bands:{STRATIFORM:{components:2,areaKm2:145.4},CONVECTIVE:{components:1,areaKm2:88.0},STRONG:{components:0,areaKm2:0.0}}},
  regions:[{id:'RADAR-CMA-CREF',kind:'RADAR',source:RADAR_SOURCE,slot:'2026-09-18T07:18:00Z',
    slotAgeMinutes:3.3,floorAglM:0,ceilingAglM:620,field:polygon,ban:polygon,caution:polygon}],
  watch:null,
}
const watchOnlyFrame={
  available:true,error:null,
  summary:{channel:'CMA_RADAR_TILES',drivesGeometry:true,available:true,
    slot:'2026-09-18T07:18:00Z',slotAgeMinutes:3.3,
    bands:{STRATIFORM:{components:1,areaKm2:145.4},CONVECTIVE:{components:0,areaKm2:0.0},STRONG:{components:0,areaKm2:0.0}}},
  regions:[],
  watch:{id:'RADAR-CMA-CREF-WATCH',kind:'RADAR_WATCH',source:RADAR_SOURCE,
    slot:'2026-09-18T07:18:00Z',band:'STRATIFORM',areaKm2:145.4,field:polygon},
}
const downFrame={available:false,regions:[],watch:null,summary:null,error:'最近 12 个时次均不可用：HTTP 404'}

test('radar states separate "no storm" from "no radar"',()=>{
  // The whole point of the channel: an empty map means two different things and
  // an operator must be able to tell which.
  assert.equal(radarState(hazardFrame),RADAR_STATE.READY)
  assert.equal(radarState(watchOnlyFrame),RADAR_STATE.QUIET)
  assert.equal(radarState(downFrame),RADAR_STATE.DOWN)
  // 0.11.16（K-8）：**没有载荷 ≠ 读失败**。这三条原来一律判 DOWN，于是页面刚打开
  // 那一瞬徽标就在报故障（一次失败都没发生）。现在它们是 PENDING；真正的失败
  // 由"载荷到了但 available!==true"表达（下一组断言）。
  assert.equal(radarState(null),RADAR_STATE.PENDING)
  assert.equal(radarState(undefined),RADAR_STATE.PENDING)
  // 载荷到了（对象存在）但不可用，仍是 DOWN：显式拒绝不许被说成"加载中"。
  assert.equal(radarState({}),RADAR_STATE.DOWN)
  assert.equal(radarState({available:'yes'}),RADAR_STATE.DOWN)
  // An available frame whose regions exist but carry no coordinates is quiet,
  // not ready: there is nothing to draw.
  assert.equal(radarState({available:true,regions:[{field:{type:'Polygon',coordinates:[]}}]}),RADAR_STATE.QUIET)
  assert.equal(radarState({available:true,regions:[{field:{type:'GeometryCollection',coordinates:[]}}]}),RADAR_STATE.QUIET)
})

test('K-8 雷达徽标有 PENDING 态，且 5 秒后自己转 DOWN',()=>{
  // 三件事必须同时成立，否则"正在读取"会变成一个永久的借口：
  //   ① 有计时且未超时 → PENDING；
  //   ② 计时超过 RADAR_PENDING_TIMEOUT_MS → DOWN（真的没读到）；
  //   ③ 超时值与句子里的秒数**同源**（句子写 5 秒，判据就按 5000 ms 断）。
  assert.equal(RADAR_PENDING_TIMEOUT_MS,5000)
  assert.equal(radarState(null,{waitedMs:0}),RADAR_STATE.PENDING)
  assert.equal(radarState(null,{waitedMs:4999}),RADAR_STATE.PENDING)
  assert.equal(radarState(null,{waitedMs:5000}),RADAR_STATE.DOWN)
  assert.equal(radarState(undefined,{waitedMs:12000}),RADAR_STATE.DOWN)
  // 有载荷时计时器无权改判：读到什么就报什么。
  assert.equal(radarState(hazardFrame,{waitedMs:60000}),RADAR_STATE.READY)
  assert.equal(radarState(downFrame,{waitedMs:0}),RADAR_STATE.DOWN)
  // 负向对照（M58）：把超时抬到 60 秒，同一时刻必须还是 PENDING ——
  // 否则"5 秒转 DOWN"可能只是"任何数都转 DOWN"。
  assert.equal(radarState(null,{waitedMs:5999,timeoutMs:60000}),RADAR_STATE.PENDING)
  assert.equal(radarState(null,{waitedMs:60000,timeoutMs:60000}),RADAR_STATE.DOWN)
  // 文案：等待与故障必须是两句不同的话，且都提到超时秒数。
  const waiting=radarSummaryText(null,{waitedMs:1200})
  const failed=radarSummaryText(null,{waitedMs:9000})
  assert.match(waiting,/正在读取/)
  assert.match(waiting,/5 秒/)
  assert.match(failed,/不可用/)
  assert.notEqual(waiting,failed)
  // not-ready 的两个状态都不许产出几何（K-8 之前这里靠 ===DOWN 判，
  // 新增 PENDING 会让 null 漏进 radar.regions 里炸掉）。
  assert.deepEqual(radarSurfaces(null),[])
  assert.equal(radarUnavailable(null),true)
  assert.equal(radarUnavailable({available:false}),true)
  assert.equal(radarUnavailable(watchOnlyFrame),false)
  assert.equal(radarUnavailable(hazardFrame),false)
})

test('K-9 判据值优先用后端 display，下界不印成精确值',()=>{
  // 后端从 0.11.1 起就发 `display`（`≥ 9656 m（6+ 为下界）`），前端一直自己拼
  // `value+unit` —— 于是判据行说"恰好 9656"，结论句说"≥ 9656"。
  assert.equal(criterionValueText({value:9656,unit:'m',lowerBound:true,
    display:'≥ 9656 m（6+ 为下界）'}).text,'≥ 9656 m（6+ 为下界）')
  assert.equal(criterionValueText({value:9656,unit:'m',lowerBound:true,
    display:'≥ 9656 m（6+ 为下界）'}).lowerBound,true)
  // 没有 display 时退回 value+unit（老载荷不能因此变成空白）。
  assert.equal(criterionValueText({value:11.83,unit:'m/s'}).text,'11.83 m/s')
  assert.equal(criterionValueText({value:null,unit:'m'}).text,'未取得')
  assert.equal(criterionValueText({value:0,unit:'m'}).text,'0 m')
  // 负向对照：真正 0 值与"缺值"不同形（M99 那条，对象是数字）。
  assert.notEqual(criterionValueText({value:0,unit:'m'}).text,
    criterionValueText({value:null,unit:'m'}).text)
  // 能见度一格：下界必须带 ≥，缺值返回空串而不是 0 km。
  assert.equal(visibilityText(9656,true),'≥9.7 km')
  assert.equal(visibilityText(9656,false),'9.7 km')
  // 998 m 必须印成米：印「1 km」会被读成「满足 ≥1000 m」，而判据是「<1000 m 禁飞」。
  assert.equal(visibilityText(998,false),'998 m')
  assert.equal(visibilityText(1000,false),'1.0 km')
  assert.equal(visibilityText(997.8,true),'≥998 m')
  assert.equal(visibilityText(null,false),'')
  assert.equal(visibilityText(undefined,true),'')
})

test('radar surfaces carry a tier per drawable ring and never invent one',()=>{
  const surfaces=radarSurfaces(hazardFrame)
  assert.deepEqual(surfaces.map(s=>s.tier),['FIELD','BAN','CAUTION'])
  assert.ok(surfaces.every(s=>s.source===RADAR_SOURCE))
  assert.ok(surfaces.every(s=>s.slot==='2026-09-18T07:18:00Z'))

  // The watch area is a fourth tier with its own meaning: reported, never drawn
  // as a restriction.
  const watch=radarSurfaces(watchOnlyFrame)
  assert.deepEqual(watch.map(s=>s.tier),['WATCH'])
  assert.equal(watch[0].id,'RADAR-CMA-CREF-WATCH')

  // A down channel contributes nothing at all -- no placeholder geometry.
  assert.deepEqual(radarSurfaces(downFrame),[])
  assert.deepEqual(radarSurfaces(null),[])
  assert.deepEqual(radarSurfaces({}),[])

  // MultiPolygon is a first-class topology here too.
  const multi={...hazardFrame,regions:[{...hazardFrame.regions[0],
    field:{type:'MultiPolygon',coordinates:[polygon.coordinates]},ban:{type:'GeometryCollection',coordinates:[]},caution:{type:'Polygon',coordinates:[]}}]}
  assert.deepEqual(radarSurfaces(multi).map(s=>s.tier),['FIELD'])
})

test('radar summary states the band in dBZ and the observation slot in local time',()=>{
  const text=radarSummaryText(hazardFrame)
  assert.match(text,/35—45 dBZ/)
  assert.match(text,/88 km²/)
  // UTC 07:18 must be shown as 15:18 local, or an 8-hour-stale frame reads as fresh.
  assert.match(text,/09-18 15:18/)
  assert.match(text,/3 分钟前/)
  assert.equal(formatRadarSlot('2026-09-18T07:18:00Z'),'09-18 15:18')
  assert.equal(formatRadarSlot(''),'')
  assert.equal(formatRadarSlot(null),'')
  assert.equal(formatRadarSlot('not-a-time'),'not-a-time')
})

test('stratiform-only frames say so instead of looking like a failure',()=>{
  const text=radarSummaryText(watchOnlyFrame)
  assert.match(text,/层状降水/)
  assert.match(text,/不构成飞行限制/)
  assert.doesNotMatch(text,/不可用/)
})

test('a down channel explains itself rather than reporting an empty sky',()=>{
  const text=radarSummaryText(downFrame)
  assert.match(text,/实测雷达不可用/)
  assert.match(text,/HTTP 404/)
  assert.match(radarSummaryText({available:false}),/本帧未取得数据/)
})

test('band rows tolerate a half-filled summary',()=>{
  assert.deepEqual(radarBandRow(hazardFrame,'CONVECTIVE'),{components:1,areaKm2:88})
  assert.deepEqual(radarBandRow(hazardFrame,'SEVERE'),{components:0,areaKm2:0})
  assert.deepEqual(radarBandRow({},'CONVECTIVE'),{components:0,areaKm2:0})
  assert.deepEqual(radarBandRow(null,'CONVECTIVE'),{components:0,areaKm2:0})
  assert.deepEqual(radarBandRow({summary:{bands:{CONVECTIVE:null}}},'CONVECTIVE'),{components:0,areaKm2:0})
})

test('radar vocabulary never collapses into the derived-risk wording',()=>{
  // 风险区 is this system's own threshold; a radar echo is a measurement. Two
  // orange blobs on one map must not share a name.
  for(const value of Object.values(radarLabels)){
    assert.ok(value.length>0)
    assert.doesNotMatch(value,/^风险区/)
    assert.ok(!/\p{Extended_Pictographic}/u.test(value),`不得使用 emoji：${value}`)
    assert.match(value,/雷达|回波|降水/)
  }
  assert.match(radarLabels.layer,/实测/)
  assert.equal(radarSource(hazardFrame),RADAR_SOURCE)
})

// ---------------------------------------------------------------------------
// Virtual mode. The weather controller can serve a generated frame instead of
// the measured mosaic, and the single thing that must never happen is a
// generated frame being described to an operator as an observation. These tests
// pin the vocabulary on both halves of that claim.
// ---------------------------------------------------------------------------
const virtualFrame={
  available:true,error:null,mode:'virtual',
  summary:{channel:'CMA_RADAR_TILES',drivesGeometry:true,available:true,
    slot:'2026-09-18T10:36:00Z',slotAgeMinutes:0,
    bands:{STRATIFORM:{components:3,areaKm2:208816.5},CONVECTIVE:{components:14,areaKm2:51314.5},STRONG:{components:6,areaKm2:29774.4}}},
  regions:[{id:'RADAR-CMA-CREF',kind:'RADAR',source:RADAR_SOURCE_SYNTHETIC,
    synthetic:true,sourceNote:'本区域几何由程序生成的模拟回波推导，不是观测结果的实况判读。',
    slot:'2026-09-18T10:36:00Z',slotAgeMinutes:0,floorAglM:0,ceilingAglM:620,
    field:polygon,ban:polygon,caution:polygon}],
  watch:null,
}

test('a synthetic radar payload is recognised from its flag or its source id',()=>{
  assert.equal(radarIsVirtual(virtualFrame),true)
  assert.equal(radarIsVirtual(hazardFrame),false)
  // Either signal alone is enough: an older payload may carry only one.
  assert.equal(radarIsVirtual({regions:[{source:RADAR_SOURCE_SYNTHETIC}]}),true)
  assert.equal(radarIsVirtual({regions:[{synthetic:true,source:'whatever'}]}),true)
  // An unlabelled payload is treated as measured, not as a demo: assuming
  // synthetic would hide a real hazard behind a "模拟" label, which is the more
  // dangerous of the two mistakes.
  assert.equal(radarIsVirtual({regions:[{source:RADAR_SOURCE}]}),false)
  assert.equal(radarIsVirtual({regions:[]}),false)
  assert.equal(radarIsVirtual(null),false)
  assert.equal(radarIsVirtual(undefined),false)
})

test('a synthetic frame is never described as a measurement',()=>{
  const text=radarSummaryText(virtualFrame)
  assert.match(text,/模拟/)
  assert.doesNotMatch(text,/实测/)
  // A generated frame has no observation time to be late relative to, so it
  // reports a generation slot instead of an age in minutes.
  assert.match(text,/生成时次/)
  assert.doesNotMatch(text,/分钟前/)
  assert.match(text,/45 dBZ/)
  assert.match(text,/09-18 18:36/)
  // The measured branch keeps its own wording, unchanged.
  const measured=radarSummaryText(hazardFrame)
  assert.match(measured,/观测时次/)
  assert.match(measured,/分钟前/)
})

test('a down virtual channel does not claim to be the measured one',()=>{
  const down={...downFrame,mode:'virtual',
    regions:[{source:RADAR_SOURCE_SYNTHETIC,synthetic:true}]}
  assert.match(radarSummaryText(down),/模拟雷达不可用/)
  assert.doesNotMatch(radarSummaryText(down),/实测雷达不可用/)
})

test('the legend vocabulary switches with the mode',()=>{
  assert.equal(radarLabelsFor(hazardFrame),radarLabels)
  assert.equal(radarLabelsFor(virtualFrame),radarLabelsVirtual)
  // Both sets are real, distinct captions: no emoji, and the virtual set says
  // what it is rather than reusing the measured words.
  for(const value of Object.values(radarLabelsVirtual)){
    assert.ok(value.length>0)
    assert.ok(!/\p{Extended_Pictographic}/u.test(value),`不得使用 emoji：${value}`)
    assert.match(value,/模拟/)
  }
  assert.notEqual(radarLabelsVirtual.layer,radarLabels.layer)
  // Each mode's vocabulary is used for that mode on the map.
  assert.equal(radarLabelsFor({regions:[{source:RADAR_SOURCE_SYNTHETIC}]}).layer,radarLabelsVirtual.layer)
  assert.equal(radarLabelsFor({regions:[{source:RADAR_SOURCE}]}).layer,radarLabels.layer)
})

// ---------------------------------------------------------------------------
// Coordinate space. The payload carries TWO conventions: model cells arrive in
// projected metres (AEQD, origin 45N/126E) and must be converted; radar surfaces
// arrive as EPSG:4326 lon/lat and must not be. Feeding radar geometry to the
// metre converter re-projects degrees as if they were metres, which collapses a
// Heilongjiang-sized polygon into a ~2e-6 degree speck at (126.0016, 45.0005) --
// measured 2026-09-23. The layer kept drawing, just nowhere visible, which is why
// "the radar shows nothing" outlived every layer-style fix.
//
// The first vertex below is a measured coordinate from that payload; the rest of
// the ring is a fixture rectangle around it, because what is being pinned is the
// coordinate space, not the storm shape.
// ---------------------------------------------------------------------------
const measuredRing={type:'Polygon',coordinates:[[
  [124.013671875,53.173119],[124.213671875,53.173119],[124.213671875,53.373119],
  [124.013671875,53.373119],[124.013671875,53.173119]]]}
// Same shape, but in the projection the model cells use: values in the hundreds
// of thousands of metres, which is what a confused converter would expect.
const projectedRing={type:'Polygon',coordinates:[[
  [-160000,910000],[-140000,910000],[-140000,930000],[-160000,930000],[-160000,910000]]]}

function bbox(geometry){
  let minLon=Infinity,maxLon=-Infinity,minLat=Infinity,maxLat=-Infinity
  const walk=value=>{
    if(typeof value?.[0]==='number'){
      minLon=Math.min(minLon,value[0]);maxLon=Math.max(maxLon,value[0])
      minLat=Math.min(minLat,value[1]);maxLat=Math.max(maxLat,value[1])
      return
    }
    if(Array.isArray(value))value.forEach(walk)
  }
  walk(geometry.coordinates)
  return {minLon,maxLon,minLat,maxLat,spanLon:maxLon-minLon,spanLat:maxLat-minLat}
}

test('radar geometry is passed through untouched, never re-projected',()=>{
  const surface={tier:'FIELD',geometry:measuredRing}
  assert.equal(radarFeatureGeometry(surface),measuredRing)
  assert.deepEqual(radarFeatureGeometry(surface),measuredRing)
  // A MultiPolygon watch area is passed through the same way: no per-part
  // handling means no chance to convert one half of it.
  const multi={type:'MultiPolygon',coordinates:[measuredRing.coordinates]}
  assert.equal(radarFeatureGeometry({tier:'WATCH',geometry:multi}),multi)
  assert.equal(radarFeatureGeometry({}),undefined)
})

test('the geographic sanity check tells the two conventions apart',()=>{
  assert.equal(geometryLooksGeographic(measuredRing),true)
  assert.equal(geometryLooksGeographic(measuredRing,0.01),true)
  assert.equal(geometryLooksGeographic(projectedRing),false)
  assert.equal(geometryLooksGeographic(projectedRing,0.01),false)
  // Empty and malformed geometry is false, not true: an empty polygon has no
  // vertex to be in range, and "no vertices" must never read as "in range".
  assert.equal(geometryLooksGeographic({type:'Polygon',coordinates:[]}),false)
  assert.equal(geometryLooksGeographic(null),false)
  assert.equal(geometryLooksGeographic(undefined),false)
  assert.equal(geometryLooksGeographic({type:'Polygon'}),false)
})

test('the wrong path really is wrong: re-projecting lon/lat collapses the polygon',()=>{
  // Negative verification. Without this the guard above is unfalsifiable -- a
  // test that only ever passes would still pass if the converter were removed,
  // and "the fix works" would be indistinguishable from "the fix is untested".
  const collapsed=geographicGeometry(measuredRing)
  const box=bbox(collapsed)
  // A range check alone still says "true" here, and that is the whole lesson:
  // the projection origin 126E/45N sits inside the operating area, so a polygon
  // collapsed onto it is indistinguishable from a legitimate one by bounds.
  // The extent is what exposes it -- hence minSpanDeg.
  assert.equal(geometryLooksGeographic(collapsed),true,
    '纯范围检查看不见坍缩：投影原点就在作业区内')
  assert.equal(geometryLooksGeographic(collapsed,0.01),false,
    '加了跨度下限之后，二次投影的几何必须被判为不合格')
  assert.ok(box.spanLon<0.01&&box.spanLat<0.01,
    `二次投影把 ${box.spanLon.toFixed(9)} 度的经度跨度压成了一个点`)
  // ...and it lands on the projection origin, not on the storm.
  assert.ok(Math.abs(box.minLon-126)<0.01&&Math.abs(box.minLat-45)<0.01,
    `二次投影后的几何落在投影原点 (${box.minLon.toFixed(4)}, ${box.minLat.toFixed(4)})，不在回波所在处`)
})

test('drawn radar features land where the storm is',()=>{
  // Mirrors what drawRadar does, so the whole path -- surfaces -> geometry ->
  // feature -- is checked, not just the one function.
  const frame={available:true,summary:{slotAgeMinutes:3.3},
    regions:[{id:'RADAR-CMA-CREF',source:RADAR_SOURCE,field:measuredRing,
      ban:measuredRing,caution:{type:'Polygon',coordinates:[]}}],watch:null}
  const drawn=radarSurfaces(frame).map(s=>feature(radarFeatureGeometry(s),{tier:s.tier}))
  assert.equal(drawn.length,2)
  for(const f of drawn){
    assert.equal(geometryLooksGeographic(f.geometry),true,
      `图层要素 ${f.properties.tier} 的几何不在经纬度空间`)
    const box=bbox(f.geometry)
    assert.ok(box.minLon>=115&&box.maxLon<=135&&box.minLat>=38&&box.maxLat<=54,
      `图层要素 ${f.properties.tier} 落在作业区之外: ${JSON.stringify(box)}`)
    assert.ok(box.spanLon>0.1&&box.spanLat>0.1,
      `图层要素 ${f.properties.tier} 被压成了点，跨度仅 ${box.spanLon}`)
  }
})

// 2026-09-24 12:0x 实测：一次 regions=0 的层状降水帧，watch 外环（吉林，206.9 km²）。
// 之所以单独留一份真实坐标：QUIET 帧是这套系统里最常见的形态，而它恰恰是被闸门挡掉
// 的那一种 —— fixture 必须是实测形状，否则"能画出来"证明不了任何东西。
const measuredWatchRing={type:'Polygon',coordinates:[[
  [129.638671875,42.747012173],[129.638671875,42.617791433],[129.462890625,42.617791433],
  [129.462890625,42.747012173],[129.638671875,42.747012173]]]}
const quietFrame={
  available:true,error:null,
  summary:{channel:'CMA_RADAR_TILES',drivesGeometry:true,available:true,
    slot:'2026-09-24T04:00:00Z',slotAgeMinutes:4.2,
    bands:{STRATIFORM:{components:1,areaKm2:206.9},CONVECTIVE:{components:0,areaKm2:0},STRONG:{components:0,areaKm2:0}}},
  regions:[],
  watch:{id:'RADAR-CMA-CREF-WATCH',kind:'RADAR_WATCH',source:RADAR_SOURCE,
    slot:'2026-09-24T04:00:00Z',band:'STRATIFORM',areaKm2:206.9,field:measuredWatchRing},
}

test('a quiet sky still yields a drawable watch area',()=>{
  // The 2026-09-24 root cause: the map gated drawing on READY, so a QUIET frame
  // produced no geometry at all while the badge said the area was marked. A
  // stratiform-only frame is the common case in NE China in autumn, so this is
  // "the weather does not show" for most of the year.
  assert.equal(radarState(quietFrame),RADAR_STATE.QUIET)
  const surfaces=radarSurfaces(quietFrame)
  assert.deepEqual(surfaces.map(s=>s.tier),['WATCH'])
  // ...and what it yields is real geographic geometry, not a collapsed speck.
  const geometry=radarFeatureGeometry(surfaces[0])
  assert.equal(geometryLooksGeographic(geometry,0.01),true)
  const box=bbox(geometry)
  assert.ok(Math.abs(box.minLon-129.46)<0.01&&Math.abs(box.maxLat-42.75)<0.01,
    `watch 几何不在实测位置: ${JSON.stringify(box)}`)
  assert.ok(box.spanLon>0.1,`watch 被压成了点，跨度仅 ${box.spanLon}`)
  // A DOWN frame is the one case that must yield nothing.
  assert.deepEqual(radarSurfaces(downFrame),[])
})

test('a quiet frame reads as rain, not as a failure, and has geometry to draw',()=>{
  // The map's own badge for QUIET promises 「已标出范围」(CityTrafficMap.vue); that
  // promise is checked statically in mapLayerContracts. What belongs here is that
  // the frame is not described as a failure and does carry a drawable area.
  const text=radarSummaryText(quietFrame)
  assert.match(text,/层状降水/)
  assert.doesNotMatch(text,/不可用/)
  assert.equal(radarState(quietFrame),RADAR_STATE.QUIET)
  assert.ok(radarSurfaces(quietFrame).length>0,
    '徽标声称已标出范围，图层就必须真的有可画的几何')
})

test('a virtual payload attributes its source to the synthetic channel',()=>{
  assert.equal(radarSource(virtualFrame),RADAR_SOURCE_SYNTHETIC)
  // A virtual payload with the source field missing must still not be
  // attributed to the national mosaic.
  assert.equal(radarSource({available:true,regions:[{synthetic:true,field:polygon}]}),RADAR_SOURCE_SYNTHETIC)
  // Surfaces keep the synthetic tag, so the map cannot draw a demo as measured.
  const surfaces=radarSurfaces(virtualFrame)
  assert.deepEqual(surfaces.map(s=>s.tier),['FIELD','BAN','CAUTION'])
  assert.ok(surfaces.every(s=>s.source===RADAR_SOURCE_SYNTHETIC))
  assert.equal(radarState(virtualFrame),RADAR_STATE.READY)
})

// --- 2026-10-01：用户报「推演的时候气象回波与禁飞不动了」-----------------------
// 排查结论是这一条的核心：**实测回波在推演中保持不动是正确行为**，一次真实观测
// 不允许被外推成预报。缺陷不在"它不动"，而在"从没说过它为什么不动"。
// 所以下面钉住的是**披露**，而不是让移动画 —— 让实测回波随推演移动会是一次
// 伪造观测，比沉默严重得多。

test('a measured echo is declared frozen during playback, a virtual one is not',()=>{
  // 实测 + 推演中：必须说出来。
  const measured=radarFrozenNote(hazardFrame,{playing:true,minute:120})
  assert.match(measured,/单次观测/)
  assert.match(measured,/保持不动/)
  // 报告里必须带上这一帧有多旧，否则"不动"读起来仍像是卡住。
  assert.match(measured,/分钟前的观测/)

  // 虚拟回波是按时次生成的，会漂移 —— 对它说"保持不动"就是错话。
  assert.equal(radarFrozenNote(virtualFrame,{playing:true,minute:120}),'',
    '虚拟回波随推演漂移，不得声称它不动')

  // 没在推演时，"不动"这件事不存在，不需要解释。
  assert.equal(radarFrozenNote(hazardFrame,{playing:false,minute:120}),'')

  // 雷达不可用时，已经有"不可用"的措辞，再加一句"保持不动"只会互相打架。
  const down={available:false,regions:[],summary:null,error:'read failed'}
  assert.equal(radarFrozenNote(down,{playing:true,minute:120}),'')
})

test('the two kinds of "frozen" are stated as different kinds of statement',()=>{
  const network={staticAirspace:{zones:[{id:'Z1',name:'甲',geometry:polygon},{id:'Z2',name:'乙'}]}}
  const note=fixedZoneFrozenNote(network,{playing:true})
  assert.match(note,/静态数据/)
  assert.match(note,/2 处/)
  // 必须指出"变的是穿越时段"，否则操作员会以为整块图层失效。
  assert.match(note,/穿越/)
  // 未推演时不解释；没有管制区时不编造一条说明。
  assert.equal(fixedZoneFrozenNote(network,{playing:false}),'')
  assert.equal(fixedZoneFrozenNote({staticAirspace:{zones:[]}},{playing:true}),'')
  assert.equal(fixedZoneFrozenNote(null,{playing:true}),'')
})

test('the weather bucket cannot be skipped by a fast scrubbing step',()=>{
  // 旧写法是 `Math.floor(minute/2)` 直接当 watch 的键。这里要证明的是：
  // 桶号随分钟**单调不减**，因此任何时间跳跃都必然改变桶号并被观察到。
  assert.equal(weatherBucket(0),0)
  assert.equal(weatherBucket(1.9),0)
  assert.equal(weatherBucket(2),1)
  assert.equal(weatherBucket(480),240)

  // 负向对照 —— 这一条正是修那个缺陷的理由。旧写法在**跨多个桶**的一步之后，
  // 只有起点和终点两个桶被触发，中间桶从未被请求过。用"步长 60 分钟"模拟
  // 一次 300 倍速下的大幅拖拽：新判据看到桶变了（该刷新），而"只比较终点是否
  // 恰好落在偶数分钟"这种写法会漏掉。这里断言的是**步长越大越不能漏**，
  // 而不是某种实现细节。
  assert.ok(weatherBucketChanged(0,60),'跨 30 个桶的拖拽必须被看见')
  assert.ok(weatherBucketChanged(59.9,60.1),'跨桶边界必须被看见')
  assert.ok(!weatherBucketChanged(60.0,61.9),'同桶内不刷新，避免放大请求量')
  // 反向拖拽同样要触发 —— 时间轴是可以往回拉的。
  assert.ok(weatherBucketChanged(120,0),'往回拖拽必须被看见')
})

// --- 桶号不能写死：地图侧也要用同一个函数 ------------------------------------
// 同一个缺陷在界面上有两处（工作台 `watchweatherBucket(minute)` 与地图
// `watchweatherBucket(props.minute)`）。工作台那处在 2026-10-01 先修好，地图这处
// 留着 —— 于是"推演时航迹不动"会在地图上继续发生，而日志与工作台的代码都看不出
// 问题。这条静态断言读的是**两个 .vue 源码**，因为 watch 的注册 `node --test`
// 求值不了；`weatherBucket` 本身的行为已由 radarLayer.test.mjs 覆盖。
//
// 判据是"两处都用同一个函数"，不是"某处出现了某个字符串"—— 后者会在有人再写一处
// `Math.floor(minute/2)` 时继续通过。

test('no component derives its redraw bucket from Math.floor(minute/2)', async () => {
  const dir = dirname(fileURLToPath(import.meta.url))
  const sources = await Promise.all([
    readFile(join(dir, '..', 'src', 'components', 'CityTrafficMap.vue'), 'utf8'),
    readFile(join(dir, '..', 'src', 'components', 'TrafficWorkbench.vue'), 'utf8'),
  ])
  for (const [index, source] of sources.entries()) {
    const label = ['CityTrafficMap.vue', 'TrafficWorkbench.vue'][index]
    assert.doesNotMatch(
      source,
      /Math\.floor\(\s*(props\.)?minute\s*\/\s*2\s*\)/,
      `${label} 仍在使用 Math.floor(minute/2) 作为重绘桶号`,
    )
    assert.match(source, /weatherBucket\(/, `${label} 应当使用 weatherBucket 派生桶号`)
  }
})
