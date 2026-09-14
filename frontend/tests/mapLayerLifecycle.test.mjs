import test from 'node:test'
import assert from 'node:assert/strict'
import { effectScope, nextTick } from 'vue'
import { store } from '../src/store.js'
import { useMapLayers } from '../src/composables/useMapLayers.js'

const flush = async () => {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 5))
}

test('换轮失败时撤下旧层，晚到的旧响应不能重新发布', async () => {
  let resolveA
  const request = path => {
    if (path.includes('runId=A')) return new Promise(resolve => { resolveA = resolve })
    return Promise.reject(new Error('B unavailable'))
  }
  store.dash = { ...store.dash, runId: 'A', regionId: 'zone', revision: 1 }
  const scope = effectScope()
  const state = scope.run(() => useMapLayers({ request, refreshMs: 0 }))
  await flush()
  store.dash = { ...store.dash, runId: 'B', regionId: 'zone', revision: 1 }
  await flush()
  assert.equal(state.status.value, 'ERROR')
  assert.deepEqual(state.layers.value, [])
  resolveA([{ kind: 'WIND', runId: 'A', regionId: 'zone', revision: 1, status: 'READY',
    data: { windDeg: 0, windSpeed: 5 }, expiresAt: '2099-01-01T00:00:00Z' }])
  await flush()
  assert.deepEqual(state.layers.value, [])
  scope.stop()
})
