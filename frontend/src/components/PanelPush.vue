<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { requestJson, store } from '../api.js'
import { fmtDateTime } from '../utils.js'

const logs = ref([])
let timer = null

const CHANNELS = [
  { key: 'SCREEN', name: '大屏' },
  { key: 'DINGTALK', name: '钉钉' },
  { key: 'FEISHU', name: '飞书' },
  { key: 'WECOM', name: '企微' },
  { key: 'MAIL', name: '邮件' }
]

// 由最近日志推断渠道状态
const channelState = computed(() => {
  const map = {}
  for (const c of CHANNELS) {
    const recent = logs.value.find(l => l.channel === c.key)
    map[c.key] = !recent || recent.status === 'SKIPPED' ? 'idle'
      : ['SENT', 'DISPLAYED'].includes(recent.status) ? 'ok' : 'fail'
  }
  return map
})
const STATE_LABEL = { ok: '曾送达', idle: '无有效送达记录', fail: '最近失败' }

// 明细列表：右栏空间充足，一次展示 14 条（后端 top50 内可滚动回看）
const shown = computed(() => logs.value.slice(0, 14))

async function load() {
  try {
    logs.value = await requestJson('/api/push/logs', { timeoutMs: 8000 })
  } catch (e) { /* 后端未就绪时静默 */ }
}

onMounted(() => {
  load()
  timer = setInterval(load, 15000)
})
onUnmounted(() => clearInterval(timer))

const wsOk = computed(() => store.wsConnected)
</script>

<template>
  <div class="push-wrap">
    <!-- 渠道状态卡：横排 -->
    <div class="ch-row">
      <div v-for="c in CHANNELS" :key="c.key" class="ch-card" :class="channelState[c.key]">
        <div class="ch-dot"></div>
        <div class="ch-txt">
          <div class="ch-name">{{ c.name }}</div>
          <div class="ch-state">{{ STATE_LABEL[channelState[c.key]] }}</div>
        </div>
      </div>
    </div>

    <!-- 推送明细列表 -->
    <div class="push-list" v-if="logs.length">
      <div class="push-hd">
        <span>时间</span><span>渠道</span><span>状态</span><span style="text-align:left">明细</span>
      </div>
      <div v-for="l in shown" :key="l.id" class="push-item" :title="l.detail">
        <span class="pi-time">{{ fmtDateTime(l.ts) }}</span>
        <span class="pi-ch">{{ CHANNELS.find(c => c.key === l.channel)?.name || l.channel }}</span>
        <span class="pi-status" :class="l.status.toLowerCase()">
          <i></i>{{ l.status === 'SENT' ? '已发送' : l.status === 'DISPLAYED' ? '已展示' : l.status === 'SKIPPED' ? '跳过' : '失败' }}
        </span>
        <span class="pi-detail">{{ l.detail }}</span>
      </div>
    </div>
    <div class="push-empty" v-else>暂无推送记录 · 触发预警后此处显示各渠道发送状态</div>

    <!-- 底部实时链路状态 -->
    <div class="push-ws">
      <span class="status-dot" :style="{ background: wsOk ? '#2ecc71' : '#c0392b' }"></span>
      实时链路 WebSocket {{ wsOk ? '已连接' : '重连中…' }}
      <span class="push-count" v-if="logs.length">· 累计 {{ logs.length }} 条</span>
    </div>
  </div>
</template>

<style scoped>
.push-wrap { display: flex; flex-direction: column; gap: 8px; height: 100%; min-height: 0; width: 100%; }

/* 渠道卡：横排 */
.ch-row { display: flex; gap: 7px; flex: none; }
.ch-card { flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px;
  background: linear-gradient(160deg, rgba(28,58,104,.5), rgba(14,32,62,.45));
  border: 1px solid rgba(64,140,230,.18); border-radius: 6px; padding: 8px 4px; min-width: 0; }
.ch-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.ch-card.ok { border-color: rgba(46,139,87,.45); }
.ch-card.ok .ch-dot { background: #2e8b57; box-shadow: 0 0 8px #2e8b57; }
.ch-card.idle .ch-dot { background: #51719e; }
.ch-card.fail { border-color: rgba(192,57,43,.5); }
.ch-card.fail .ch-dot { background: #c0392b; box-shadow: 0 0 8px #c0392b; }
.ch-txt { min-width: 0; }
.ch-name { font-size: 12.5px; color: #dce9f7; text-align: center; }
.ch-state { font-size: 10px; color: #6f95c4; text-align: center; margin-top: 1px; }

/* 表头 */
.push-hd { display: flex; gap: 8px; font-size: 10px; color: #51719e; padding: 2px 0 4px;
  border-bottom: 1px solid rgba(64,140,230,.25); }
.push-hd span:first-child { width: 88px; }
.push-hd span:nth-child(2) { width: 40px; }
.push-hd span:nth-child(3) { width: 44px; }

/* 明细列表：占满剩余空间 */
.push-list { flex: 1; overflow-y: auto; min-height: 0; }
.push-item { display: flex; gap: 8px; font-size: 11.5px; padding: 4px 0; align-items: baseline;
  border-bottom: 1px dashed rgba(64,140,230,.10); }
.pi-time { color: #51719e; flex: none; width: 88px; font-variant-numeric: tabular-nums; }
.pi-ch { color: #dce9f7; flex: none; width: 40px; }
.pi-status { flex: none; width: 44px; font-weight: 700; display: inline-flex; align-items: center; gap: 4px; }
.pi-status i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.pi-status.ok, .pi-status.sent, .pi-status.displayed { color: #2e8b57; }
.pi-status.skipped { color: #51719e; }
.pi-status.failed { color: #c0392b; }
.pi-detail { color: #7ba0cc; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; min-width: 0; }

.push-empty { flex: 1; display: flex; align-items: center; justify-content: center;
  font-size: 12px; color: #51719e; }

.push-ws { flex: none; font-size: 11px; color: #6f95c4; display: flex; align-items: center; gap: 6px;
  border-top: 1px dashed rgba(64,140,230,.2); padding-top: 6px; }
.push-count { color: #51719e; }
</style>
