// 共享数据 store：REST 初始加载 + WebSocket 实时增量
import { reactive } from 'vue'

export const store = reactive({
  dash: {
    serverTime: '', mode: '-', scenario: '-', region: '-', taskType: '-',
    current: null, sfiHistory: [], tracks: [], tracksHistory: [],
    forecast: [], forecastSfi: [], alerts: [], lastError: null, lastRunAt: ''
  },
  wsConnected: false,
  configStatus: { qweatherReady: false, mode: '-', note: '' },
  alertFlash: null,          // 最新预警弹窗 {levelLabel, text, ts}
  chatList: [],              // 智能体问答历史（前端会话内）
  scenario: 'clear'
})

const REST = import.meta.env.DEV ? 'http://127.0.0.1:8085' : ''

export async function fetchDashboard() {
  try {
    const r = await fetch(REST + '/api/dashboard')
    if (r.ok) store.dash = await r.json()
  } catch (e) { console.warn('dashboard 拉取失败', e) }
}

export async function fetchConfigStatus() {
  try {
    const r = await fetch(REST + '/api/config/status')
    if (r.ok) store.configStatus = await r.json()
  } catch (e) { /* 忽略 */ }
}

export async function postAction(path, body) {
  const r = await fetch(REST + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined
  })
  return r.json()
}

// ---------------- WebSocket ----------------
let ws = null
let retryTimer = null

function connectWs() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const host = import.meta.env.DEV ? '127.0.0.1:8085' : location.host
  ws = new WebSocket(`${proto}://${host}/ws/dashboard`)
  ws.onopen = () => { store.wsConnected = true }
  ws.onclose = () => {
    store.wsConnected = false
    clearTimeout(retryTimer)
    retryTimer = setTimeout(connectWs, 4000)   // 断线 4s 自动重连
  }
  ws.onerror = () => ws.close()
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data)
      if (msg.type === 'dashboard') {
        store.dash = msg
        if (msg.scenario) store.scenario = msg.scenario
      } else if (msg.type === 'alert') {
        store.alertFlash = msg.alert
        setTimeout(() => { store.alertFlash = null }, 12000)   // 弹窗 12s 自动关闭
      }
    } catch (e) { console.warn('ws 消息解析失败', e) }
  }
}

export function initRealtime() {
  connectWs()
  fetchDashboard()
  fetchConfigStatus()
}
