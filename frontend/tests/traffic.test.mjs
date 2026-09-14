import test from 'node:test'
import assert from 'node:assert/strict'
import {atTime,flightState,profile,effectiveFlights} from '../src/traffic/runtime.js'
import {lngLat} from '../src/traffic/geography.js'

test('manual commands replay without changing the frozen trajectory',()=>{
  const f={id:'f',status:'SCHEDULED',points:[[0,0,0,0]]}
  const ops=[{flightId:'f',minute:10,action:'SUSPEND'},{flightId:'f',minute:20,action:'RESUME'}]
  assert.equal(effectiveFlights([f],ops,9)[0],f)
  assert.equal(flightState(effectiveFlights([f],ops,15)[0],15),'CLOSED')
  assert.deepEqual(effectiveFlights([f],ops,15)[0].points,[])
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
