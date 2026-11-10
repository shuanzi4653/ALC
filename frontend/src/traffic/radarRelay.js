import { requestJson } from '../api.js'
import { radarRelaySlots, radarRelayReady } from './runtime.js'

export function bytesToBase64(bytes) {
  const chunk = 0x8000
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(offset, offset + chunk))
  }
  return btoa(binary)
}

async function fetchSlotTiles(relay, slot, fetchImpl) {
  const tiles = []
  for (const pair of relay.grid) {
    const [x, y] = pair
    const url = `${relay.tileBase}/${slot.path}/${relay.zoom}/${y}/${x}.bin`
    let buffer
    try {
      const response = await fetchImpl(url, { mode: 'cors', credentials: 'omit', cache: 'no-store' })
      if (!response.ok) return null
      buffer = await response.arrayBuffer()
    } catch (error) {
      // 网络层直接抛错（CORS 被拒 / DNS / 证书）说明"这一档"不是没发布，是根本读不到：
      // 后面 5 个时次、每时次几十张图都会以同样方式失败，还会各留一条 CORS 红字。
      // 记在这次取图说明上，本轮就不再往后试了。
      if (error instanceof TypeError) relay.corsBlocked = true
      return null
    }
    if (buffer.byteLength !== relay.tileBytes) return null
    tiles.push({ x, y, data: bytesToBase64(new Uint8Array(buffer)) })
  }
  return tiles
}

export async function relayRadarTiles(relay, { fetchImpl = fetch, nowMs = Date.now() } = {}) {
  if (!radarRelayReady(relay)) return { ok: false, reason: 'NO_INSTRUCTIONS' }
  if (relay && relay.corsBlocked) return { ok: false, reason: 'CORS_BLOCKED' }
  const steps = Number.isFinite(relay.maxLookbackSteps) ? relay.maxLookbackSteps : 12
  const candidates = radarRelaySlots(nowMs, relay.slotTimezoneOffsetMinutes ?? 480,
    relay.cadenceMinutes ?? 6, steps)
  for (const slot of candidates) {
    const tiles = await fetchSlotTiles(relay, slot, fetchImpl)
    if (!tiles) continue
    try {
      const stored = await requestJson(relay.postTo || '/api/traffic/radar/tiles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slot: slot.iso, zoom: relay.zoom, tiles }),
        timeoutMs: 20_000,
      })
      return { ok: true, slot: slot.label, stored }
    } catch (error) {
      return { ok: false, reason: 'POST_FAILED', message: error?.message || String(error), slot: slot.label }
    }
  }
  return { ok: false, reason: 'NO_SLOT_AVAILABLE', tried: candidates.length }
}
