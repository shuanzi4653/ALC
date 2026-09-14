import { applyDashboard, store } from './store.js'
import { normalizeDashboard } from './dashboardAdapter.js'

export { store }

let ws = null
let retryTimer = null
let alertTimer = null
let stopped = false
let retryCount = 0
const seenAlertIds = new Set()

export class ApiError extends Error {
  constructor(message, status = 0, code = 'NETWORK_ERROR', retryable = true) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.retryable = retryable
  }
}

export async function requestJson(path, options = {}) {
  const timeoutMs = options.timeoutMs ?? 25_000
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const { timeoutMs: _ignored, ...fetchOptions } = options
  const method = String(fetchOptions.method || 'GET').toUpperCase()
  const headers = new Headers(fetchOptions.headers || {})
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const token = document.cookie.split('; ').find(value => value.startsWith('XSRF-TOKEN='))?.split('=')[1]
    if (token) headers.set('X-XSRF-TOKEN', decodeURIComponent(token))
  }
  try {
    const response = await fetch(path, { ...fetchOptions, headers, credentials: 'same-origin', signal: controller.signal })
    const contentType = response.headers.get('content-type') || ''
    const body = contentType.includes('application/json') ? await response.json() : null
    if (!response.ok) {
      throw new ApiError(body?.message || `请求失败（HTTP ${response.status}）`, response.status,
        body?.code || 'HTTP_ERROR', Boolean(body?.retryable))
    }
    if (body === null) throw new ApiError('服务返回了无法识别的内容', response.status, 'INVALID_RESPONSE', false)
    return body
  } catch (error) {
    if (error?.name === 'AbortError') throw new ApiError('请求超时，请稍后重试', 0, 'TIMEOUT', true)
    if (error instanceof ApiError) throw error
    throw new ApiError('无法连接服务，请检查系统是否已启动', 0, 'NETWORK_ERROR', true)
  } finally {
    clearTimeout(timer)
  }
}

export async function fetchDashboard() {
  try {
    const data = normalizeDashboard(await requestJson('/api/dashboard', { timeoutMs: 8_000 }))
    applyDashboard(data)
    return data
  } catch (error) {
    store.actionError = error.message
    throw error
  }
}

export async function fetchConfigStatus() {
  try {
    store.configStatus = await requestJson('/api/config/status', { timeoutMs: 8_000 })
  } catch (_) {
    // 顶部将配置状态与连接状态分开显示，失败不覆盖已知配置。
  }
}

export async function fetchAuthStatus() {
  store.auth.loading = true
  try {
    store.auth = { ...(await requestJson('/api/auth/status', { timeoutMs: 8000 })), loading: false, statusUnavailable: false, error: '' }
  } catch (error) {
    store.auth = { enabled: true, authenticated: false, username: '', loading: false, statusUnavailable: true, error: error.message }
  }
  return store.auth
}

export async function login(username, password) {
  try {
    const result = await requestJson('/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }), timeoutMs: 8000
    })
    store.auth = { ...result, loading: false, error: '' }
    connectWs()
    await Promise.allSettled([fetchDashboard(), fetchConfigStatus()])
    return true
  } catch (error) {
    store.auth = { ...store.auth, authenticated: false, loading: false, error: error.message }
    return false
  }
}

export async function postAction(path, body, timeoutMs = 25_000) {
  const data = await requestJson(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    timeoutMs
  })
  if (data?.version === 1 && Object.prototype.hasOwnProperty.call(data, 'runSequence')) {
    applyDashboard(normalizeDashboard(data))
  }
  return data
}

function scheduleReconnect() {
  if (stopped) return
  clearTimeout(retryTimer)
  const base = Math.min(30_000, 1000 * (2 ** Math.min(retryCount, 5)))
  const delay = Math.round(base * (0.85 + Math.random() * 0.3))
  retryCount += 1
  retryTimer = setTimeout(connectWs, delay)
}

function connectWs() {
  if (stopped) return
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  store.connectionState = 'connecting'
  ws = new WebSocket(`${proto}://${location.host}/ws/dashboard`)
  ws.onopen = async () => {
    retryCount = 0
    store.wsConnected = true
    store.connectionState = 'connected'
    try { await fetchDashboard() } catch (_) { /* 状态已由 fetchDashboard 记录 */ }
  }
  ws.onclose = () => {
    store.wsConnected = false
    store.connectionState = stopped ? 'closed' : 'reconnecting'
    scheduleReconnect()
  }
  ws.onerror = () => ws?.close()
  ws.onmessage = event => {
    try {
      const message = JSON.parse(event.data)
      if (Number(message.version) !== 1 || !message.type) return
      if (message.type === 'dashboard') {
        applyDashboard(normalizeDashboard(message.payload))
      } else if (message.type === 'alert') {
        const eventId = message.payload?.eventId ?? message.payload?.id
        if (eventId != null && seenAlertIds.has(String(eventId))) return
        if (eventId != null) {
          seenAlertIds.add(String(eventId))
          if (seenAlertIds.size > 200) seenAlertIds.delete(seenAlertIds.values().next().value)
        }
        store.alertFlash = message.payload
        if (eventId != null && ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ version: 1, type: 'alert_ack', runId: message.runId,
            payload: { eventId, displayedAt: new Date().toISOString() } }))
        }
        clearTimeout(alertTimer)
        alertTimer = setTimeout(() => { store.alertFlash = null }, 12_000)
      }
    } catch (error) {
      console.warn('WebSocket 消息解析失败', error)
    }
  }
}

export function initRealtime() {
  stopped = false
  clearTimeout(retryTimer)
  fetchAuthStatus().then(auth => {
    if (stopped) return
    if (!auth.enabled || auth.authenticated) {
      connectWs()
      fetchDashboard().catch(() => {})
      fetchConfigStatus()
    } else if (auth.statusUnavailable) {
      retryTimer = setTimeout(() => { if (!stopped) initRealtime() }, 3000)
    }
  })
  return disposeRealtime
}

export function disposeRealtime() {
  stopped = true
  clearTimeout(retryTimer)
  clearTimeout(alertTimer)
  retryTimer = null
  alertTimer = null
  if (ws) {
    ws.onclose = null
    ws.close()
    ws = null
  }
  store.wsConnected = false
  store.connectionState = 'closed'
}
