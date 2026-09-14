<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { store } from '../api.js'

const now = ref(new Date())
let timer = null
onMounted(() => { timer = setInterval(() => { now.value = new Date() }, 1000) })
onUnmounted(() => clearInterval(timer))

const clock = computed(() => {
  const d = now.value
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
})
const sourceLabel = computed(() => store.dash.effectiveSource === 'live' ? '和风实时'
  : store.dash.effectiveSource === 'sim' ? '模拟数据' : '等待数据')
const freshnessLabel = computed(() => ({ FRESH: '新鲜', STALE: '已过期', NO_DATA: '无数据', UNKNOWN: '时间未知' })[store.dash.dataStatus] || '未知')
</script>

<template>
  <div class="panel top">
    <div>
      <div class="title">天窗智巡 · 东北三省</div>
      <div class="sub">辽宁 · 吉林 · 黑龙江低空飞行气象推演与智能预警</div>
    </div>
    <div class="spacer"></div>
    <div class="status-item">
      <span class="status-dot" :style="{ background: store.wsConnected ? '#2ecc71' : '#c0392b' }"></span>
      实时同步 {{ store.wsConnected ? '已连接' : '重连中' }}
    </div>
    <div class="status-item">
      <span class="status-dot" :style="{ background: store.configStatus.qweatherReady ? '#2ecc71' : '#d98a2b' }"></span>
      和风配置 {{ store.configStatus.qweatherReady ? '完整' : '未完整' }}
    </div>
    <div class="status-item">
      <span class="status-dot" :style="{ background: store.dash.dataStatus === 'FRESH' ? '#2ecc71' : '#d98a2b' }"></span>
      数据 {{ freshnessLabel }}
    </div>
    <div class="status-item">来源：{{ sourceLabel }}</div>
    <div class="status-item">作业区：{{ store.dash.region }}</div>
    <div class="clock">{{ clock }}</div>
  </div>
</template>
