export function normalizeDashboard(payload) {
  if (!payload || typeof payload !== 'object') throw new Error('大屏响应为空或格式错误')
  return {
    ...payload,
    version: Number(payload.version),
    runSequence: Number(payload.runSequence ?? 0),
    revision: Number(payload.revision ?? 0),
    configuredMode: payload.configuredMode ?? payload.mode ?? '-',
    effectiveSource: payload.effectiveSource ?? payload.current?.source ?? '-',
    appliedScenario: payload.appliedScenario ?? payload.scenario ?? 'clear',
    sfiHistory: Array.isArray(payload.sfiHistory) ? payload.sfiHistory : [],
    tracks: Array.isArray(payload.tracks) ? payload.tracks : [],
    tracksHistory: Array.isArray(payload.tracksHistory) ? payload.tracksHistory : [],
    forecast: Array.isArray(payload.forecast) ? payload.forecast : [],
    forecastSfi: Array.isArray(payload.forecastSfi) ? payload.forecastSfi : [],
    alerts: Array.isArray(payload.alerts) ? payload.alerts : []
  }
}
