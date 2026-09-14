import test from 'node:test'
import assert from 'node:assert/strict'
import {fetchAuthStatus,store} from '../src/api.js'

test('服务短时故障与登录要求分开，恢复后撤下故障状态',async()=>{
 const original=globalThis.fetch
 try{
  globalThis.fetch=async()=>new Response(JSON.stringify({message:'upstream unavailable'}),{status:502,headers:{'Content-Type':'application/json'}})
  await fetchAuthStatus()
  assert.equal(store.auth.statusUnavailable,true)
  assert.equal(store.auth.authenticated,false)
  globalThis.fetch=async()=>new Response(JSON.stringify({enabled:false,authenticated:false}),{status:200,headers:{'Content-Type':'application/json'}})
  await fetchAuthStatus()
  assert.equal(store.auth.statusUnavailable,false)
  assert.equal(store.auth.enabled,false)
  assert.equal(store.auth.error,'')
 }finally{globalThis.fetch=original}
})
