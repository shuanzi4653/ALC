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
async function fetchSlotTiles(relay, slot, fetchImpl, deadCoords = new Set(), stats = null) {
  const tiles = []
  const missing = []
  const failed = []
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
        // 读到响应但状态不对（源站这一轮没发这个坐标）：确凿的单张缺，记下来。
        deadCoords.add(key)
        missing.push(key)
        continue
      }
      buffer = await response.arrayBuffer()
      if (stats) stats.attempted += 1
    } catch (error) {
      // 跨域请求失败在浏览器里一律是 TypeError，两种原因长得分不开：
      //   一、源站 404 —— 错误页不带 Access-Control-Allow-Origin，响应读不到，直接抛；
      //   二、真的被 CORS / DNS 拒掉。
      // 早先这里一律 return null（整档作废），结果是"一张缺图废掉 12 个时次"，
      // 而真正的 404 恰好走的就是这条分支。所以先记账，等这一档取完再判：
      // 同档有瓦片取到 → 抛错的那几张是 404，记进 deadCoords；
      // 同档一张都没取到 → 是这一档没发布（或整网不通），不能冤枉坐标。
      failed.push(key)
      missing.push(key)
      if (stats) { stats.thrown += 1; stats.attempted += 1 }
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
  // 有成功才把抛错的坐标判死：否则会把"这一档没发布"误记成"这个坐标不存在"，
  // 后面每一档都跳过它，等于自己把还能用的瓦片永久屏蔽。
  for (const k of failed) deadCoords.add(k)
  return { tiles, missing }
}

export async function relayRadarTiles(relay, { fetchImpl = fetch, nowMs = Date.now() } = {}) {
  if (!radarRelayReady(relay)) return { ok: false, reason: 'NO_INSTRUCTIONS' }
  if (relay && relay.corsBlocked) return { ok: false, reason: 'CORS_BLOCKED' }
  const steps = Number.isFinite(relay.maxLookbackSteps) ? relay.maxLookbackSteps : 12
  const candidates = radarRelaySlots(nowMs, relay.slotTimezoneOffsetMinutes ?? 480,
    relay.cadenceMinutes ?? 6, steps)
  const deadCoords = new Set()
  const stats = { thrown: 0, attempted: 0 }
  for (const slot of candidates) {
    const got = await fetchSlotTiles(relay, slot, fetchImpl, deadCoords, stats)
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
  // 每一个请求都抛错 = 连一张都读不到，那才是真的 CORS / 网络被拒；
  // 只要有一张读到过，就不是"被拒"，只是源站这一轮没发布。
  if (stats.attempted > 0 && stats.thrown === stats.attempted) relay.corsBlocked = true
  return { ok: false, reason: 'NO_SLOT_AVAILABLE', tried: candidates.length,
    missing: [...deadCoords] }
}
