import test from 'node:test'
import assert from 'node:assert/strict'
import {ZONE_INTRUSION,zoneIntrusionLabels,zoneIntrusionAt,zoneIntrusions} from '../src/traffic/runtime.js'

// A flight whose plan crosses one approval-required area and one prohibited site,
// mirroring the record shape `zones.crossings` actually returns.
function flight(overrides={}){
  return {
    id:'TF-1',mode:'CAR',
    staticAirspace:{
      zones:2,prohibited:1,approvalRequired:1,clauses:['AIRPORT','ELECTROMAGNETIC'],
      crossings:[
        {zoneId:'Z-P',name:'某导航台有源保护区',clause:'ELECTROMAGNETIC',enforcement:'PROHIBITED',
         entryMinute:30,exitMinute:34.5,maxAglM:350,citation:'GB 6364—2013'},
        {zoneId:'Z-A',name:'沈阳桃仙国际机场净空保护区域',clause:'AIRPORT',enforcement:'APPROVAL_REQUIRED',
         entryMinute:2.78,exitMinute:27.06,maxAglM:500,citation:'MH/T 7003'},
      ],
    },
    ...overrides,
  }
}

test('a flight with no crossing payload is never reported as intruding',()=>{
  for(const value of [undefined,null,{}, {staticAirspace:{}}, {staticAirspace:{crossings:[]}}]){
    const state=zoneIntrusionAt(value,10)
    assert.equal(state.level,ZONE_INTRUSION.NONE)
    assert.equal(state.label,'')
    assert.deepEqual(state.active,[])
    assert.equal(state.lead,null)
    assert.equal(state.next,null)
    assert.equal(state.truncated,false)
    assert.equal(state.prohibitedHidden,0)
  }
})

test('the intrusion interval is closed at both ends',()=>{
  const f=flight()
  // Before the window opens nothing is flagged; a minute early must not turn a
  // vehicle red, or the whole map would flash red on the approach.
  assert.equal(zoneIntrusionAt(f,29.9).level,ZONE_INTRUSION.NONE)
  // Exactly on entry and exactly on exit count as inside, because the backend's
  // own interval is inclusive — it records the first and last sample that hit.
  assert.equal(zoneIntrusionAt(f,30).level,ZONE_INTRUSION.PROHIBITED)
  assert.equal(zoneIntrusionAt(f,32).level,ZONE_INTRUSION.PROHIBITED)
  assert.equal(zoneIntrusionAt(f,34.5).level,ZONE_INTRUSION.PROHIBITED)
  assert.equal(zoneIntrusionAt(f,34.6).level,ZONE_INTRUSION.NONE)
  // Inside the approval window only.
  assert.equal(zoneIntrusionAt(f,10).level,ZONE_INTRUSION.APPROVAL_REQUIRED)
})

test('a prohibition outranks an approval requirement whenever both are active',()=>{
  const overlapping=flight({staticAirspace:{zones:2,prohibited:1,approvalRequired:1,crossings:[
    {zoneId:'A',name:'须批准区',enforcement:'APPROVAL_REQUIRED',entryMinute:0,exitMinute:60},
    {zoneId:'B',name:'禁入区',enforcement:'PROHIBITED',entryMinute:5,exitMinute:10},
  ]}})
  const inside=zoneIntrusionAt(overlapping,7)
  assert.equal(inside.level,ZONE_INTRUSION.PROHIBITED)
  assert.equal(inside.active.length,2)
  // `lead` is the record the panel names, so it must be the strictest one rather
  // than whichever happened to be listed first.
  assert.equal(inside.lead.zoneId,'B')
  assert.equal(zoneIntrusionAt(overlapping,20).level,ZONE_INTRUSION.APPROVAL_REQUIRED)
  assert.equal(zoneIntrusionAt(overlapping,20).lead.zoneId,'A')
})

test('the next boundary is reported so the alert can arrive before the entry',()=>{
  const f=flight()
  const early=zoneIntrusionAt(f,0)
  assert.equal(early.level,ZONE_INTRUSION.NONE)
  assert.equal(early.next.record.zoneId,'Z-A')
  assert.ok(Math.abs(early.next.minutesAway-2.78)<1e-9)
  // Once past both windows there is nothing left ahead.
  assert.equal(zoneIntrusionAt(f,40).next,null)
  assert.equal(zoneIntrusionAt(f,40).level,ZONE_INTRUSION.NONE)
})

test('a server-side truncation is reported, never silently treated as absent',()=>{
  // The endpoint caps the record list at six entries sorted by priority. Nine
  // zones were found but only two records survived, so a reader of the payload
  // alone cannot conclude the vehicle is clear.
  const capped=flight({staticAirspace:{zones:9,prohibited:3,approvalRequired:6,crossings:[
    {zoneId:'P1',name:'禁入一',enforcement:'PROHIBITED',entryMinute:0,exitMinute:1},
    {zoneId:'P2',name:'禁入二',enforcement:'PROHIBITED',entryMinute:2,exitMinute:3},
  ]}})
  const state=zoneIntrusionAt(capped,10)
  assert.equal(state.reported,2)
  assert.equal(state.total,9)
  assert.equal(state.truncated,true)
  // Three prohibitions were counted by the server, two of which made it into the
  // records — the remaining one is surfaced as a number, not assumed to be zero.
  assert.equal(state.prohibitedHidden,1)
  assert.equal(zoneIntrusionAt(flight(),10).prohibitedHidden,0)
  assert.equal(zoneIntrusionAt(flight(),10).truncated,false)
})

test('malformed records are skipped instead of producing NaN windows',()=>{
  // `Number(null)` is 0 and `Number('')` is 0, so a naive conversion turns a
  // missing `entryMinute` into "inside since minute 0" and paints the vehicle red
  // for the entire plan. Every empty form has to be rejected before conversion.
  const broken=flight({staticAirspace:{zones:4,prohibited:0,approvalRequired:0,crossings:[
    {zoneId:'X',enforcement:'PROHIBITED'},
    {zoneId:'Y',enforcement:'PROHIBITED',entryMinute:'abc',exitMinute:null},
    {zoneId:'Z',enforcement:'PROHIBITED',entryMinute:5,exitMinute:null},
    {zoneId:'W',enforcement:'PROHIBITED',entryMinute:null,exitMinute:9},
  ]}})
  const state=zoneIntrusionAt(broken,6)
  assert.equal(state.level,ZONE_INTRUSION.NONE)
  assert.deepEqual(state.active,[])
  assert.equal(state.next,null)

  const blanks=flight({staticAirspace:{zones:2,prohibited:0,approvalRequired:0,crossings:[
    {zoneId:'E1',enforcement:'APPROVAL_REQUIRED',entryMinute:'',exitMinute:'  '},
    {zoneId:'E2',enforcement:'APPROVAL_REQUIRED',entryMinute:undefined,exitMinute:undefined},
  ]}})
  assert.equal(zoneIntrusionAt(blanks,0).level,ZONE_INTRUSION.NONE)
  // A zero-length window is still a real window and stays flagged.
  const instant=flight({staticAirspace:{zones:1,prohibited:0,approvalRequired:1,crossings:[
    {zoneId:'I',enforcement:'APPROVAL_REQUIRED',entryMinute:7,exitMinute:7}]}})
  assert.equal(zoneIntrusionAt(instant,7).level,ZONE_INTRUSION.APPROVAL_REQUIRED)
  assert.equal(zoneIntrusionAt(instant,7.01).level,ZONE_INTRUSION.NONE)
})

test('the fleet view lists intruding vehicles strictly before clear ones',()=>{
  const flights=[
    {id:'CLEAR-1',staticAirspace:{zones:0,prohibited:0,crossings:[]}},
    flight(),
    {id:'BAN-2',mode:'DELIVERY',staticAirspace:{zones:1,prohibited:1,crossings:[
      {zoneId:'P',name:'禁入',enforcement:'PROHIBITED',entryMinute:0,exitMinute:35}]}},
  ]
  const rows=zoneIntrusions(flights,32)
  // Only the two vehicles inside a zone are returned, the prohibition first.
  assert.deepEqual(rows.map(row=>row.flight.id),['BAN-2','TF-1'])
  assert.deepEqual(rows.map(row=>row.state.level),[ZONE_INTRUSION.PROHIBITED,ZONE_INTRUSION.PROHIBITED])
  // Past every window the fleet is clear: the list is derived, not sticky.
  assert.deepEqual(zoneIntrusions(flights,45),[])
  assert.deepEqual(zoneIntrusions(undefined,10),[])
})

test('intrusion wording stays inside the fixed-airspace vocabulary',()=>{
  const emoji=/\p{Extended_Pictographic}/u
  for(const value of Object.values(zoneIntrusionLabels)){
    assert.ok(!emoji.test(value),`不得使用 emoji：${value}`)
  }
  assert.match(zoneIntrusionLabels[ZONE_INTRUSION.PROHIBITED],/禁入区/)
  assert.match(zoneIntrusionLabels[ZONE_INTRUSION.APPROVAL_REQUIRED],/批准/)
  // The prohibited wording must not claim an official airspace closure — this is
  // the system reporting a planned crossing, not issuing a control order.
  for(const value of Object.values(zoneIntrusionLabels)){
    assert.ok(!/禁飞区/.test(value),`不得把管制空域写成禁飞区：${value}`)
  }
})
