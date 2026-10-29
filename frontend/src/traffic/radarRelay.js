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
    } catch (_) {
      return null
    }
    if (buffer.byteLength !== relay.tileBytes) return null
    tiles.push({ x, y, data: bytesToBase64(new Uint8Array(buffer)) })
  }
  return tiles
}

export async function relayRadarTiles(relay, { fetchImpl = fetch, nowMs = Date.now() } = {}) {
  if (!radarRelayReady(relay)) return { ok: false, reason: 'NO_INSTRUCTIONS' }
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
