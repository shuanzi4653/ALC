import { onScopeDispose, ref, watch } from 'vue'
import { fetchDashboard, requestJson, store } from '../api.js'

const VALID_STATUS = new Set(['READY', 'NO_DATA', 'EXPIRED', 'ERROR'])

export function normalizeLayers(payload, identity, nowMs = Date.now()) {
  if (!Array.isArray(payload)) return []
  return payload.filter(layer => layer && typeof layer === 'object')
    .filter(layer => layer.runId === identity.runId && layer.regionId === identity.regionId)
    .filter(layer => Number(layer.revision) === identity.revision)
    .map(layer => {
      const expires = Date.parse(layer.expiresAt || '')
      const expired = Number.isFinite(expires) && expires <= nowMs
      return {
        ...layer,
        status: expired ? 'EXPIRED' : VALID_STATUS.has(layer.status) ? layer.status : 'ERROR',
        errorCode: VALID_STATUS.has(layer.status) ? layer.errorCode : 'INVALID_LAYER_STATUS'
      }
    })
}

function summarize(layers) {
  if (layers.some(layer => layer.status === 'READY')) return 'READY'
  if (layers.some(layer => layer.status === 'ERROR')) return 'ERROR'
  if (layers.some(layer => layer.status === 'EXPIRED')) return 'EXPIRED'
  return 'NO_DATA'
}

/** 只发布与当前 Dashboard 身份完全匹配的图层，换轮和失败时立即撤下旧图元。 */
export function useMapLayers(options = {}) {
  const request = options.request || requestJson
  const now = options.now || Date.now
  const refreshMs = options.refreshMs ?? 15_000
  const layers = ref([])
  const status = ref('NO_DATA')
  const error = ref('')
  let generation = 0
  let expiryTimer = null

  const reevaluateExpiry = () => {
    const current = now()
    layers.value = layers.value.map(layer => {
      const expires = Date.parse(layer.expiresAt || '')
      return Number.isFinite(expires) && expires <= current && layer.status === 'READY'
        ? { ...layer, status: 'EXPIRED' }
        : layer
    })
    if (status.value !== 'LOADING') status.value = summarize(layers.value)
  }

  const stop = watch(
    () => `${store.dash.runId || ''}|${store.dash.regionId || ''}|${Number(store.dash.revision || 0)}`,
    async () => {
      const identity = { runId: store.dash.runId, regionId: store.dash.regionId || '', revision: Number(store.dash.revision || 0) }
      const current = ++generation
      layers.value = []
      error.value = ''
      if (!identity.runId) {
        status.value = 'NO_DATA'
        return
      }
      status.value = 'LOADING'
      try {
        const query = new URLSearchParams({ runId: identity.runId, regionId: identity.regionId, revision: String(identity.revision) })
        const result = await request(`/api/layers?${query}`, { timeoutMs: 8000 })
        if (current !== generation) return
        const liveIdentity = `${store.dash.runId || ''}|${store.dash.regionId || ''}|${Number(store.dash.revision || 0)}`
        const requestedIdentity = `${identity.runId}|${identity.regionId}|${identity.revision}`
        if (liveIdentity !== requestedIdentity) return
        layers.value = normalizeLayers(result, identity, now())
        status.value = summarize(layers.value)
      } catch (reason) {
        if (current !== generation) return
        layers.value = []
        status.value = 'ERROR'
        error.value = reason?.message || '图层加载失败'
        if (reason?.code === 'LAYER_REVISION_CONFLICT') {
          fetchDashboard().catch(() => {})
        }
      }
    }, { immediate: true })

  if (refreshMs > 0) expiryTimer = setInterval(reevaluateExpiry, refreshMs)
  onScopeDispose(() => {
    generation += 1
    stop()
    if (expiryTimer) clearInterval(expiryTimer)
  })
  return { layers, status, error, reevaluateExpiry }
}
