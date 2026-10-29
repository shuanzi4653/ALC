import { applyDashboard, store } from './store.js'
import { normalizeDashboard } from './dashboardAdapter.js'
import { workspaceId } from './workspace.js'

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

export function operatorRole() {
  try {
    const value = localStorage.getItem('alc-operator')
    return ['observer', 'duty', 'admin'].includes(value) ? value : 'duty'
  } catch (_) {
    return 'duty'
  }
}

export function setOperatorRole(role) {
  try {
    if (['observer', 'duty', 'admin'].includes(role)) localStorage.setItem('alc-operator', role)
  } catch (_) {
  }
}

export async function requestJson(path, options = {}) {
  const timeoutMs = options.timeoutMs ?? 25_000
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const { timeoutMs: _ignored, ...fetchOptions } = options
  const method = String(fetchOptions.method || 'GET').toUpperCase()
  const headers = new Headers(fetchOptions.headers || {})
  headers.set('X-ALC-Workspace', workspaceId())
  headers.set('X-ALC-Operator', operatorRole())
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

export function dashboardSocketUrl(host = location.host, secure = location.protocol === 'https:') {
  return `${secure ? 'wss' : 'ws'}://${host}/ws/dashboard?ws=${encodeURIComponent(workspaceId())}`
}

function connectWs() {
  if (stopped) return
  store.connectionState = 'connecting'
  ws = new WebSocket(dashboardSocketUrl())
  ws.onopen = async () => {
    retryCount = 0
    store.wsConnected = true
    store.connectionState = 'connected'
    try { await fetchDashboard() } catch (_) {  }
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
  connectWs()
  fetchDashboard().catch(() => {})
  fetchConfigStatus()
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
