import test from 'node:test'
import assert from 'node:assert/strict'
import {RADAR_BAN_TIER,radarBanSurfaces,insideRadarBan,radarCoreIntrusionAt,radarSurfaces,RADAR_SOURCE_SYNTHETIC} from '../src/traffic/runtime.js'

// 用户 2026-10-01 第 3 条第 4 项：「右上角本视图内存在飞机进入禁飞区未实现统计」。
// 监视条当时只读 `flight.staticAirspace.crossings`（法定管制区），对气象派生的
// 雷达内核一个字都没有 —— 地图上红着、右上角写 0，两个结论同屏矛盾。
//
// 这里钉的是判据本身：红色内核 = 雷达 BAN 层（≥45 dBZ），且**只有**那一层。
// FIELD（≥35 dBZ，须绕飞）与 WATCH（层状降水，可穿越）都不得计入 —— 把"须绕飞"
// 也算成"进入禁飞区"会让这个数字从漏报直接变成谎报。

function radar(regions){
  return {available:true,mode:'virtual',source:RADAR_SOURCE_SYNTHETIC,regions,watch:null}
}
function ring(minLon,minLat,maxLon,maxLat){
  return [[minLon,minLat],[maxLon,minLat],[maxLon,maxLat],[minLon,maxLat],[minLon,minLat]]
}
function geometry(rings){
  return {type:'Polygon',coordinates:rings}
}
const INSIDE=[126.0,45.0]

test('只有 BAN 层进入禁入内核判定',()=>{
  const frame=radar([{
    id:'R-1',source:RADAR_SOURCE_SYNTHETIC,
    field:geometry([ring(125,44,127,46)]),
    ban:geometry([ring(125.5,44.5,126.5,45.5)]),
    caution:geometry([ring(124,43,128,47)]),
  }])
  const bans=radarBanSurfaces(frame)
  assert.equal(bans.length,1)
  assert.equal(bans[0].id,'R-1')
  // 三层都在同一个 payload 里，选中的是 BAN；这正是 tier 常量存在的理由。
  assert.equal(radarSurfaces(frame).length,3)
  assert.equal(RADAR_BAN_TIER,'BAN')
  assert.equal(insideRadarBan(INSIDE,bans[0]),true)
})

test('禁入内核有一圈空洞时，空洞内不算越界',()=>{
  // 一个环状内核：外壳 125.5-126.5，内部 125.9-126.1 是"眼"。
  const frame=radar([{
    id:'R-DONUT',source:RADAR_SOURCE_SYNTHETIC,
    ban:geometry([ring(125.5,44.5,126.5,45.5),ring(125.9,44.9,126.1,45.1)]),
  }])
  const ban=radarBanSurfaces(frame)[0]
  assert.equal(insideRadarBan([126.0,45.0],ban),false,'空洞内部不应判为越界')
  assert.equal(insideRadarBan([125.7,44.7],ban),true,'壳内空洞外应判为越界')
})

test('MultiPolygon 的每个分量都要被看到，且不依赖分量顺序',()=>{
  // 最险的失效模式是"静默只取第一个分量"：只测第 0 个会把第二个风暴里的飞机漏掉，
  // 而地图仍然把它画红。所以两个分量都要落点在判定里。
  const near=[ring(125,44,126,45)]
  const far=[ring(130,48,131,49)]
  for(const polygons of [[near,far],[far,near]]){
    const ban=radarBanSurfaces(radar([{id:'R-M',source:RADAR_SOURCE_SYNTHETIC,
      ban:{type:'MultiPolygon',coordinates:polygons}}]))[0]
    assert.equal(insideRadarBan([125.5,44.5],ban),true)
    assert.equal(insideRadarBan([130.5,48.5],ban),true)
    assert.equal(insideRadarBan([128.0,46.0],ban),false)
  }
})

test('边界框先于逐边测试，框外一律不越界',()=>{
  const ban=radarBanSurfaces(radar([{id:'R-2',source:RADAR_SOURCE_SYNTHETIC,
    ban:geometry([ring(125.5,44.5,126.5,45.5)])}]))[0]
  assert.deepEqual(ban.bounds,[125.5,44.5,126.5,45.5])
  assert.equal(insideRadarBan([126.0,45.0],ban),true)
  assert.equal(insideRadarBan([100.0,30.0],ban),false)
  assert.equal(insideRadarBan([126.0,30.0],ban),false)
})

test('降级情形一律返回"没有内核"，不抛异常也不编造',()=>{
  // 雷达不可用、没有 regions、几何缺失、坐标是空数组 —— 每一个都必须给出"无内核"
  // 而不是一个空的正方形或一次崩溃：这个数字是要贴在屏幕上的。
  for(const frame of [undefined,null,{},{available:false},{regions:[]},
                      {available:true,regions:[{}]},
                      {available:true,regions:[{id:'x',ban:{type:'Polygon',coordinates:[]}}]}]){
    assert.deepEqual(radarBanSurfaces(frame),[])
    assert.equal(insideRadarBan(INSIDE,null),false)
    assert.equal(insideRadarBan(INSIDE,{}),false)
    assert.equal(insideRadarBan(null,{bounds:[0,0,1,1],geometry:geometry([ring(0,0,1,1)])}),false)
    assert.equal(radarCoreIntrusionAt(INSIDE,radarBanSurfaces(frame)),null)
  }
})

test('toLocal 决定坐标空间，且结果用同一空间的边界框',()=>{
  const frame=radar([{id:'R-3',source:RADAR_SOURCE_SYNTHETIC,
    ban:geometry([ring(125,44,126,45)])}])
  // 身份映射＝经纬度空间（测试与"几何与航迹已在同一空间"的调用方都用它）。
  const identity=value=>value
  const same=radarBanSurfaces(frame,identity)[0]
  assert.deepEqual(same.bounds,[125,44,126,45])
  // 一个粗糙的"度->米"映射：断言的是**转换被应用了**，而不是投影本身正确
  // （投影由 geography.js 负责，另有测试）。
  const scaled=radarBanSurfaces(frame,value=>({...value,
    coordinates:value.coordinates.map(ringCoords=>ringCoords.map(([lon,lat])=>[lon*1000,lat*1000]))}))[0]
  assert.deepEqual(scaled.bounds,[125000,44000,126000,45000])
  assert.equal(insideRadarBan([125500,44500],scaled),true)
  assert.equal(insideRadarBan([125.5,44.5],scaled),false,'度与米不可混用')
})

test('radarCoreIntrusionAt 返回命中的那个内核，未命中返回 null',()=>{
  const frame=radar([
    {id:'R-A',source:RADAR_SOURCE_SYNTHETIC,ban:geometry([ring(120,40,121,41)])},
    {id:'R-B',source:RADAR_SOURCE_SYNTHETIC,ban:geometry([ring(125,44,126,45)])},
  ])
  const bans=radarBanSurfaces(frame)
  assert.equal(radarCoreIntrusionAt([125.5,44.5],bans).id,'R-B')
  assert.equal(radarCoreIntrusionAt([122,42],bans),null)
  assert.equal(radarCoreIntrusionAt([125.5,44.5],[]),null)
})
