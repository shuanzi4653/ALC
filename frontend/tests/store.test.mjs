import test from 'node:test'
import assert from 'node:assert/strict'
import { applyDashboard, store } from '../src/store.js'
import { normalizeDashboard } from '../src/dashboardAdapter.js'

function dashboard(sequence, revision = 1) {
  return normalizeDashboard({ version: 1, runSequence: sequence, revision, runId: `run-${sequence}` })
}

test('newer run wins over older HTTP or WebSocket response', () => {
  store.dash = dashboard(10, 1)
  assert.equal(applyDashboard(dashboard(11, 1)), true)
  assert.equal(applyDashboard(dashboard(10, 9)), false)
  assert.equal(store.dash.runId, 'run-11')
})

test('newer revision of same run is accepted', () => {
  store.dash = dashboard(20, 1)
  assert.equal(applyDashboard(dashboard(20, 2)), true)
  assert.equal(store.dash.revision, 2)
})

test('same revision and conflicting run id cannot overwrite current dashboard', () => {
  store.dash = dashboard(21, 2)
  assert.equal(applyDashboard(dashboard(21, 2)), false)
  assert.equal(applyDashboard({ ...dashboard(21, 3), runId: 'conflict' }), false)
  assert.equal(store.dash.runId, 'run-21')
})

test('unknown protocol version is rejected', () => {
  store.dash = dashboard(30, 1)
  assert.equal(applyDashboard({ version: 2, runSequence: 31, revision: 1 }), false)
  assert.equal(store.dash.runSequence, 30)
})

test('missing protocol version is rejected', () => {
  store.dash = dashboard(30, 1)
  assert.equal(applyDashboard(normalizeDashboard({ runSequence: 31, revision: 1 })), false)
  assert.equal(store.dash.runSequence, 30)
})

test('adapter supplies collection defaults without inventing data', () => {
  const value = normalizeDashboard({ version: 1, runSequence: 1, revision: 1 })
  assert.deepEqual(value.forecast, [])
  assert.deepEqual(value.alerts, [])
  assert.equal(value.effectiveSource, '-')
})
