import { reactive } from 'vue'

export const store = reactive({
  dash: {
    version: 1, runId: null, runSequence: 0, revision: 0, status: 'WAITING',
    configuredMode: '-', effectiveSource: '-', appliedScenario: 'clear',
    serverTime: '', region: '-', taskType: '-', dataStatus: 'NO_DATA',
    current: null, sfiHistory: [], tracks: [], tracksHistory: [],
    forecast: [], forecastSfi: [], alerts: [], lastError: null, lastAttempt: null
  },
  wsConnected: false,
  connectionState: 'connecting',
  configStatus: { qweatherReady: false, mode: '-', note: '' },
  alertFlash: null,
  chatList: [],
  requestedScenario: null,
  pendingAction: null,
  actionError: ''
  ,auth: { enabled: false, authenticated: true, username: '', loading: true, error: '' }
})

export function isNewerDashboard(next, current = store.dash) {
  const nextSeq = Number(next?.runSequence ?? 0)
  const currentSeq = Number(current?.runSequence ?? 0)
  if (nextSeq !== currentSeq) return nextSeq > currentSeq
  if (next?.runId !== current?.runId) return false
  return Number(next?.revision ?? 0) > Number(current?.revision ?? 0)
}

export function applyDashboard(next) {
  if (!next || typeof next !== 'object' || Number(next.version) !== 1) return false
  if (!isNewerDashboard(next)) return false
  store.dash = next
  return true
}
