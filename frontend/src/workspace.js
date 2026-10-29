const KEY = 'alc_ws'
const COOKIE = 'alc_ws'
const PATTERN = /^[A-Za-z0-9_-]{6,64}$/
const TTL_SECONDS = 365 * 24 * 3600
const BYTES = 12

function randomId() {
  const bytes = new Uint8Array(BYTES)
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes)
  else for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256)
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
}

function readStored() {
  try { return globalThis.localStorage?.getItem(KEY) || '' } catch (_) { return '' }
}

function writeStored(value) {
  try { globalThis.localStorage?.setItem(KEY, value) } catch (_) {  }
}

function readCookie() {
  if (typeof document === 'undefined') return ''
  const hit = document.cookie.split('; ').find(v => v.startsWith(COOKIE + '='))
  return hit ? decodeURIComponent(hit.slice(COOKIE.length + 1)) : ''
}

function writeCookie(value) {
  if (typeof document === 'undefined') return
  document.cookie = `${COOKIE}=${encodeURIComponent(value)}; path=/; max-age=${TTL_SECONDS}; SameSite=Lax`
}

let cached = ''

export function workspaceId() {
  if (cached) return cached
  const existing = [readStored(), readCookie()].find(v => PATTERN.test(v))
  cached = existing || randomId()
  writeStored(cached)
  writeCookie(cached)
  return cached
}

export function workspaceLabel() {
  return workspaceId().slice(0, 8)
}

export function resetWorkspace() {
  const next = randomId()
  cached = next
  writeStored(next)
  writeCookie(next)
  return next
}

export function __resetCacheForTests() {
  cached = ''
}
