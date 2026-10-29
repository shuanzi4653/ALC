import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {DEFAULT_RISK_CEILING_AGL_M,STATIC_APPROVAL_REQUIRED,STATIC_PROHIBITED,STATIC_REGISTERED,reasonNames,relativeClock,staticCrossingSummary,staticEnforcementLabel,staticZoneBand,staticZoneLabels,staticZoneSummary,staticZoneSurfaces} from '../src/traffic/runtime.js'

const catalog=JSON.parse(readFileSync(new URL('../../backend-python/data/traffic/fixed-zones.json',import.meta.url),'utf8'))

test('fixed controlled airspace is described separately from weather risk',()=>{
  // The two vocabularies must never collapse into one: a meteorologically derived
  // no-fly column is this system's own threshold, a published controlled airspace
  // is a legal fact. Sharing a label would invite reading a forecast as a ban.
  assert.match(reasonNames.STATIC_AIRSPACE_BLOCKED,/固定管制区/)
  assert.match(reasonNames.STATIC_AIRSPACE_BLOCKED,/批准/)

  assert.equal(staticEnforcementLabel(STATIC_PROHIBITED),'固定管制区（未获批准不得进入）')
  assert.equal(staticEnforcementLabel(STATIC_APPROVAL_REQUIRED),'固定管制空域（须经批准）')
  assert.equal(staticEnforcementLabel(STATIC_REGISTERED),'已登记待补范围')
  assert.equal(staticEnforcementLabel('SOMETHING_ELSE'),'固定管制区')

  const emoji=/\p{Extended_Pictographic}/u
  for(const value of [...Object.values(reasonNames),...Object.values(staticZoneLabels)]){
    assert.ok(!emoji.test(value),`不得使用 emoji：${value}`)
    assert.ok(value.length>0)
  }
  // The enforcement note must state the distinction explicitly, since it is shown
  // next to the layer toggle as the tooltip.
  assert.match(catalog.legalFramework.entryRule,/未经空中交通管理机构批准/)
})

test('fixed zone summary separates what is mapped from what is only registered',()=>{
  const empty=staticZoneSummary(undefined)
  assert.deepEqual(empty,{total:0,withGeometry:0,registeredOnly:0,prohibited:0,approvalRequired:0,
    registered:0,sectors:[],clauseCount:0,catalogVersion:'',dataRetrievedAt:'',policy:''})

  const summary=staticZoneSummary({
    zones:[
      {id:'a',geometry:{type:'Polygon',coordinates:[]},enforcement:'PROHIBITED',sector:'RESEARCH',clause:'ELECTROMAGNETIC'},
      {id:'b',geometry:{type:'Polygon',coordinates:[]},enforcement:'APPROVAL_REQUIRED',sector:'CIVIL_AVIATION',clause:'AIRPORT'},
      {id:'c',geometry:{type:'Polygon',coordinates:[]},enforcement:'APPROVAL_REQUIRED',sector:'CIVIL_AVIATION',clause:'AIRPORT'},
      {id:'d',geometry:null,enforcement:'REGISTERED_REVIEW_REQUIRED',sector:'GOVERNMENT',clause:'HERITAGE'},
    ],
    status:{catalogVersion:'v-test',dataRetrievedAt:'2026-09-16',policy:'APPROVAL_REQUIRED'},
  })
  assert.equal(summary.total,4)
  assert.equal(summary.withGeometry,3)
  assert.equal(summary.registeredOnly,1)
  assert.equal(summary.prohibited,1)
  assert.equal(summary.approvalRequired,2)
  assert.equal(summary.registered,1)
  assert.equal(summary.clauseCount,3)
  assert.equal(summary.catalogVersion,'v-test')
  assert.equal(summary.policy,'APPROVAL_REQUIRED')
  // Sectors read highest count first so the dominant domain is the first chip.
  assert.deepEqual(summary.sectors[0],['CIVIL_AVIATION',2])
})

test('zone band falls back to the operation ceiling instead of inventing a limit',()=>{
  assert.deepEqual(staticZoneBand({floorAglM:120,displayCeilingAglM:620,openEndedAbove:true}),
    {floor:120,ceiling:620,openEndedAbove:true})
  // An explicit legal ceiling is never replaced by the viewport ceiling.
  assert.deepEqual(staticZoneBand({floorAglM:0,displayCeilingAglM:200,openEndedAbove:false}),
    {floor:0,ceiling:200,openEndedAbove:false})
  // Missing or nonsensical values degrade to something drawable and non-empty.
  assert.deepEqual(staticZoneBand({},999),{floor:0,ceiling:999,openEndedAbove:true})
  assert.deepEqual(staticZoneBand(null,999),{floor:0,ceiling:999,openEndedAbove:true})
  assert.deepEqual(staticZoneBand({floorAglM:620,displayCeilingAglM:620},999),
    {floor:620,ceiling:999,openEndedAbove:true})
  assert.equal(staticZoneBand({floorAglM:620,displayCeilingAglM:100}).ceiling,621)
})

test('zone surfaces never turn a registration into an invented footprint',()=>{
  const {volumes,references}=staticZoneSurfaces({zones:[
    {id:'v',geometry:{type:'Polygon',coordinates:[]},floorAglM:0,displayCeilingAglM:620,citation:'X'},
    {id:'m',geometry:{type:'MultiPolygon',coordinates:[]},floorAglM:120,displayCeilingAglM:620,citation:'Y'},
    {id:'r',geometry:null,referencePoint:{coordinate:[126.6,45.6]}},
    // No geometry and no verified coordinate: it must vanish rather than be
    // buffered, which is exactly the failure mode the catalogue forbids.
    {id:'ghost',geometry:null},
    {id:'point',geometry:{type:'Point',coordinates:[126,45]}},
  ]})
  assert.deepEqual(volumes.map(v=>v.zone.id),['v','m'])
  assert.deepEqual(volumes.map(v=>v.floor),[0,120])
  assert.deepEqual(volumes.map(v=>v.citation),['X','Y'])
  assert.deepEqual(references.map(r=>r.zone.id),['r'])
  assert.deepEqual(references[0].coordinate,[126.6,45.6])

  // A geometry-less block yields nothing at all — the map must show no column.
  assert.deepEqual(staticZoneSurfaces(undefined),{volumes:[],references:[]})
  assert.deepEqual(staticZoneSurfaces({zones:[]}),{volumes:[],references:[]})
})

test('crossing summary names each zone with its time window',()=>{
  assert.equal(staticCrossingSummary(undefined),'')
  assert.equal(staticCrossingSummary({}),'')
  assert.equal(staticCrossingSummary({staticAirspace:{zones:0,crossings:[]}}),'')

  const text=staticCrossingSummary({staticAirspace:{zones:2,prohibited:1,approvalRequired:1,crossings:[
    {name:'沈阳桃仙国际机场净空保护区域',entryMinute:2.78,exitMinute:27.06,enforcement:'APPROVAL_REQUIRED'},
    {name:'某导航台有源保护区',entryMinute:30,exitMinute:30.5,enforcement:'PROHIBITED'},
  ]}})
  assert.match(text,/2 处固定管制区/)
  assert.match(text,/含 1 处禁入/)
  assert.match(text,/沈阳桃仙国际机场净空保护区域/)
  assert.match(text,/某导航台有源保护区/)
  // The window is rendered through the shared clock so a plan window and a ledger
  // row can never disagree about when the aircraft was inside the zone.
  assert.ok(text.includes(`${relativeClock(2.78)}—${relativeClock(27.06)}`),text)
  assert.ok(!text.includes('未展开'),text)

  // The id list is capped server-side, so the summary has to admit the remainder
  // instead of quietly reporting a smaller number than the plan actually found.
  const capped=staticCrossingSummary({staticAirspace:{zones:9,prohibited:0,approvalRequired:9,crossings:[
    {name:'A',entryMinute:1,exitMinute:2},{name:'B',entryMinute:3,exitMinute:4},
  ]}})
  assert.match(capped,/9 处固定管制区/)
  assert.match(capped,/另有 7 处未展开/)
  assert.ok(!capped.includes('禁入'))
})

test('catalog declares the four requested sectors and all eight items',()=>{
  assert.equal(catalog.clauses.length,8)
  const sectors=new Set(catalog.clauses.map(clause=>clause.sectorLabel))
  for(const label of ['机密','国防','科研','政务'])assert.ok(sectors.has(label),`缺少领域 ${label}`)
  const byKey=Object.fromEntries(catalog.clauses.map(clause=>[clause.key,clause]))
  assert.equal(byKey.CLASSIFIED_UNIT.siteCount,0)
  assert.match(byKey.CLASSIFIED_UNIT.reviewAction,/不公开/)
})

test('catalog emits geometry only where a published rule fixes the shape',()=>{
  const allowedKinds=new Set(['CIRCLE','RUNWAY_RECT'])
  const publishedRadii=new Set([500,5000,55000])
  let withGeometry=0
  for(const site of catalog.sites){
    if(!site.geometry){
      assert.match(site.geometryStatus,/NOT_PUBLICLY_PUBLISHED|REQUIRES_LOCAL_PUBLICATION/,site.id)
      assert.ok(site.referencePoint?.coordinate?.length===2,`${site.id} 缺少公开参考点`)
      continue
    }
    withGeometry++
    assert.ok(allowedKinds.has(site.geometry.kind),`${site.id} 几何种类未公开`)
    assert.ok(site.citation&&site.geometryRule,`${site.id} 缺少依据`)
    if(site.geometry.kind==='CIRCLE'){
      assert.ok(publishedRadii.has(site.geometry.radiusM),`${site.id} 半径未公开：${site.geometry.radiusM}`)
    }else{
      assert.equal(site.geometry.halfWidthM,10000,site.id)
      assert.equal(site.geometry.beyondEndM,20000,site.id)
    }
  }
  assert.equal(withGeometry,catalog.sites.filter(site=>site.geometry).length)
  assert.ok(withGeometry>=60,`有几何的站点过少：${withGeometry}`)
  // The GB 31223 radar protection radius must never be rendered as airspace.
  assert.ok(!catalog.sites.some(site=>site.geometry?.radiusM===20000))
})

test('the weather radar is registered, not given a 20 km no-fly disc',()=>{
  const radars=catalog.sites.filter(site=>site.facilityType==='WEATHER_RADAR_STATION')
  assert.equal(radars.length,1)
  const radar=radars[0]
  assert.equal(radar.geometry,null)
  assert.equal(radar.enforcement,'REGISTERED_REVIEW_REQUIRED')
  assert.match(radar.citation,/GB 31223/)
  assert.match(radar.note,/探测环境/)
  assert.ok(radar.referencePoint.coordinate.every(Number.isFinite))
  assert.ok(radar.operator)
})

test('the catalog carries its legal basis and no emoji',()=>{
  assert.match(catalog.legalFramework.instrument,/无人驾驶航空器飞行管理暂行条例/)
  assert.match(catalog.legalFramework.instrument,/761/)
  assert.equal(catalog.legalFramework.clause,'第十九条')
  assert.match(catalog.legalFramework.publicationRule,/由设区的市级以上人民政府公布/)
  assert.match(catalog.disclaimer,/不构成飞行许可/)
  assert.ok(catalog.dataRetrievedAt)
  const emoji=/\p{Extended_Pictographic}/u
  assert.ok(!emoji.test(JSON.stringify(catalog)))
  // The interval mark must survive: it is punctuation, not a pictograph.
  assert.ok(catalog.sites.some(site=>site.name.includes('·')))
})

test('the frontend ceiling fallback matches the plan ceiling',()=>{
  // staticZoneSurfaces is called with the network's own risk ceiling; if those two
  // ever diverge the drawn columns stop matching the weather volumes.
  assert.equal(DEFAULT_RISK_CEILING_AGL_M,620)
  const floor=120
  const {volumes}=staticZoneSurfaces({zones:[
    {id:'z',geometry:{type:'Polygon',coordinates:[]},floorAglM:floor,displayCeilingAglM:DEFAULT_RISK_CEILING_AGL_M,citation:'C'},
  ]})
  assert.ok(volumes[0].ceiling>volumes[0].floor)
  assert.ok(volumes[0].ceiling>500,'固定管制柱应当贯穿飞行汽车巡航层')
})
