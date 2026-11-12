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
/** 探测一批时次：返回这批里**确实在发布**的档，并把探测到的那一张字节带回来复用。
 *
 * 为什么要有探测这一层：回看窗口是 3.6 小时（36 档），源站停更时逐档取全 4 张
 * 就是 144 次请求，浏览器串行要半分钟，用户只看到"代取中"一直转。
 *
 * `pending404` 是"这一轮暂时读不到"的坐标，**不直接进 deadCoords**：
 * 源站停更时全部坐标都 404，立刻记死会把后面能用的档一起屏蔽。只有当某一档
 * 探测成功时，才由调用方把 pending404 提升为 dead —— 那时"404 = 这一轮没发
 * 这个坐标"才成立。
 */
async function probeBatch(relay, slots, fetchImpl, pending404, stats) {
  const found = await Promise.all(slots.map(async slot => {
    for (const pair of relay.grid) {
      const [x, y] = pair
      const key = `${x},${y}`
      const url = `${relay.tileBase}/${slot.path}/${relay.zoom}/${y}/${x}.bin`
      let buffer
      try {
        const response = await fetchImpl(url, { mode: 'cors', credentials: 'omit', cache: 'no-store' })
        if (stats) stats.attempted += 1
        if (!response.ok) {
          pending404.add(key)
          continue
        }
        buffer = await response.arrayBuffer()
      } catch (error) {
        // 跨域失败与 404 在这一层分不开，也不该分：探测只回答"有没有"。
        if (stats) { stats.thrown += 1; stats.attempted += 1 }
        continue
      }
      // 长度不符不算命中：少一行像元，位置对、内容错，比没有更危险。
      if (buffer.byteLength !== relay.tileBytes) continue
      return { slot, tile: { x, y, data: bytesToBase64(new Uint8Array(buffer)) } }
    }
    return null
  }))
  return found.filter(Boolean)
}

async function fetchSlotTiles(relay, slot, fetchImpl, deadCoords = new Set(), stats = null, preloaded = null) {
  const tiles = preloaded ? [preloaded] : []
  const done = preloaded ? new Set([`${preloaded.x},${preloaded.y}`]) : new Set()
  const missing = []
  const failed = []
  for (const pair of relay.grid) {
    const [x, y] = pair
    const key = `${x},${y}`
    if (done.has(key)) continue
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
  const pending404 = new Set()
  const stats = { thrown: 0, attempted: 0 }
  // 分批探测：每批 6 档，命中即停。源站正常发布时第一批就结束；
  // 停更时才逐批往前找，最多 steps 档（服务端下发的窗口）。
  const PROBE_CHUNK = 6
  let index = 0
  while (index < candidates.length) {
    // 第一档单独问：源站正常发布时答案就在最新一档，只该发一次请求。
    // 之后才 6 档一批并发 —— 停更时才走这条慢路。
    const size = index === 0 ? 1 : PROBE_CHUNK
    const chunk = candidates.slice(index, index + size)
    index += size
    const hits = await probeBatch(relay, chunk, fetchImpl, pending404, stats)
    if (!hits.length) continue
    // 有一档真的在发布 → 之前那些 404 才能判成"这一轮没发这个坐标"。
    for (const key of pending404) deadCoords.add(key)
    pending404.clear()
    for (const hit of hits) {
      const got = await fetchSlotTiles(relay, hit.slot, fetchImpl, deadCoords, stats, hit.tile)
      if (!got) continue
      try {
        const stored = await requestJson(relay.postTo || '/api/traffic/radar/tiles', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ slot: hit.slot.iso, zoom: relay.zoom, tiles: got.tiles }),
          timeoutMs: 20_000,
        })
        // missing 是"这一档缺了哪几个坐标"，必须一路带到界面上：缺测与"无回波"
        // 在图上长得一样，只有把它说出来，读者才知道南边那块是没数据而不是晴空。
        return { ok: true, slot: hit.slot.label, stored, missing: got.missing }
      } catch (error) {
        return { ok: false, reason: 'POST_FAILED', message: error?.message || String(error), slot: hit.slot.label }
      }
    }
  }
  // 每一个请求都抛错 = 连一张都读不到，那才是真的 CORS / 网络被拒；
  // 只要有一张读到过，就不是"被拒"，只是源站这一轮没发布。
  if (stats.attempted > 0 && stats.thrown === stats.attempted) relay.corsBlocked = true
  return { ok: false, reason: 'NO_SLOT_AVAILABLE', tried: candidates.length,
    missing: [...deadCoords] }
}
