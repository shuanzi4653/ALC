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

/** 取一档瓦片。返回 null 表示"这一档整个不可用"，否则 {tiles, missing}。
 *
 * `deadCoords` 在**本轮**所有时次之间共享：网格是枚举出来的，会随源站发布策略变
 * （2026-11-12 实测 zoom 3 只发 (5,2)(6,2)(5,3)，(6,3) 全天 404）。某个坐标在某一档
 * 404 之后，后面每一档都不会有它 —— 记住它，别拿 11 次白跑换同一个 404。
 */
async function fetchSlotTiles(relay, slot, fetchImpl, deadCoords = new Set()) {
  const tiles = []
  const missing = []
  for (const pair of relay.grid) {
    const [x, y] = pair
    const key = `${x},${y}`
    if (deadCoords.has(key)) {
      missing.push(key)
      continue
    }
    const url = `${relay.tileBase}/${slot.path}/${relay.zoom}/${y}/${x}.bin`
    let buffer
    try {
      const response = await fetchImpl(url, { mode: 'cors', credentials: 'omit', cache: 'no-store' })
      if (!response.ok) {
        // 单张 404 是"源站这一轮没发这个坐标"，不是网络层被拒：余下的瓦片照常取。
        // 早先这里 return null 是整档作废，后果是一张缺图让 12 个时次全部报废。
        deadCoords.add(key)
        missing.push(key)
        continue
      }
      buffer = await response.arrayBuffer()
    } catch (error) {
      // 网络层直接抛错（CORS 被拒 / DNS / 证书）说明"这一档"不是没发布，是根本读不到：
      // 后面几个时次、每时次几十张图都会以同样方式失败，还会各留一条 CORS 红字。
      // 记在这次取图说明上，本轮就不再往后试了。
      if (error instanceof TypeError) {
        relay.corsBlocked = true
        return null
      }
      missing.push(key)
      continue
    }
    // 长度不符 = 这一张不能用（少一行像元位置对、内容错，比没有更危险）；但它只是
    // "这一张缺"，不是"这一档没发布"——其余瓦片长度正确就照常回传。
    if (buffer.byteLength !== relay.tileBytes) {
      missing.push(key)
      continue
    }
    tiles.push({ x, y, data: bytesToBase64(new Uint8Array(buffer)) })
  }
  if (!tiles.length) return null
  return { tiles, missing }
}

export async function relayRadarTiles(relay, { fetchImpl = fetch, nowMs = Date.now() } = {}) {
  if (!radarRelayReady(relay)) return { ok: false, reason: 'NO_INSTRUCTIONS' }
  if (relay && relay.corsBlocked) return { ok: false, reason: 'CORS_BLOCKED' }
  const steps = Number.isFinite(relay.maxLookbackSteps) ? relay.maxLookbackSteps : 12
  const candidates = radarRelaySlots(nowMs, relay.slotTimezoneOffsetMinutes ?? 480,
    relay.cadenceMinutes ?? 6, steps)
  const deadCoords = new Set()
  for (const slot of candidates) {
    const got = await fetchSlotTiles(relay, slot, fetchImpl, deadCoords)
    if (!got) continue
    try {
      const stored = await requestJson(relay.postTo || '/api/traffic/radar/tiles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slot: slot.iso, zoom: relay.zoom, tiles: got.tiles }),
        timeoutMs: 20_000,
      })
      // missing 是"这一档缺了哪几个坐标"，必须一路带到界面上：缺测与"无回波"
      // 在图上长得一样，只有把它说出来，读者才知道南边那块是没数据而不是晴空。
      return { ok: true, slot: slot.label, stored, missing: got.missing }
    } catch (error) {
      return { ok: false, reason: 'POST_FAILED', message: error?.message || String(error), slot: slot.label }
    }
  }
  return { ok: false, reason: 'NO_SLOT_AVAILABLE', tried: candidates.length,
    missing: [...deadCoords] }
}
