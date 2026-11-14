// 阈值与代价系数的前端副本（V1.1.2）
//
// 这里**不定义数值**，只缓存后端 `/api/traffic/v2/constants` 的下发结果。
// 背景：1.1.1 之前，走廊页的"需关注"、台账的模型筛选、气象表的配色各写了一份
// 0.35/0.60，其中 0.15 在后端根本没有对应常量 —— 改后端一个数，屏幕上有三处
// 不跟随，且没人知道哪一处是准的。现在只有一处来源，前端只是读者。
//
// 取不到时用与后端一致的缺省值：宁可显示一个"和后端此刻一致"的旧值，
// 也不能因为一次请求失败把整张表的分档颜色变成空白。
import { reactive } from 'vue'
import { requestJson } from '../api.js'

export const TH = reactive({
  riskWatch: 0.35,
  riskHold: 0.75,
  modelWatch: 0.35,
  modelHold: 0.6,
  windHigh: 12,
  costPerHour: 0.6,
  loaded: false,
})

let started = null

/** 只发一次；失败不重试、不抛错（阈值不是页面能不能用的前提）。 */
export function loadThresholds() {
  if (started) return started
  started = (async () => {
    try {
      const body = await requestJson('/api/traffic/v2/constants', { timeoutMs: 8000 })
      const risk = body?.risk || {}
      const model = body?.model || {}
      const cost = body?.cost || {}
      TH.riskWatch = Number(risk.watch ?? TH.riskWatch)
      TH.riskHold = Number(risk.hold ?? TH.riskHold)
      TH.modelWatch = Number(model.watch ?? TH.modelWatch)
      TH.modelHold = Number(model.hold ?? TH.modelHold)
      TH.windHigh = Number(body?.windHighMps ?? TH.windHigh)
      TH.costPerHour = Number(cost.perHour ?? TH.costPerHour)
      TH.loaded = true
    } catch (_) {
      // 静默：阈值取不到时用缺省值，界面照常可用。
    }
    return TH
  })()
  return started
}
