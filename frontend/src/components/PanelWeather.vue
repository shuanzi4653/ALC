<script setup>
import { computed } from 'vue'
import { store } from '../api.js'

const cur = computed(() => store.dash.current)
const snap = computed(() => cur.value?.snapshot || {})
const present = value => typeof value === 'number' && Number.isFinite(value)
const humidityText = computed(() => present(snap.value.humidity) ? Math.round(snap.value.humidity * 100) : '--')
const valueText = (value, digits = 1) => present(value) ? Number(value).toFixed(digits).replace(/\.0$/, '') : '--'
const visibilityText = computed(() => present(snap.value.visibilityM) ? (snap.value.visibilityM / 1000).toFixed(1) : '--')
const thunderText = computed(() => present(snap.value.thunderProb) ? Math.round(snap.value.thunderProb * 100) : '--')
const compass = degree => {
  if (!present(degree)) return '--'
  const names = ['北', '东北', '东', '东南', '南', '西南', '西', '西北']
  return `${names[Math.round(degree / 45) % 8]}风 ${Math.round(degree)}°`
}

function cls(ban, warn) { return ban ? 'ban' : warn ? 'warn' : '' }
</script>

<template>
  <div v-if="cur" class="wx-grid">
    <div class="wx-item">
      <div class="lab">天气现象</div>
      <div class="val text-val">{{ snap.conditionText || '--' }}</div>
    </div>
    <div class="wx-item">
      <div class="lab">风向</div>
      <div class="val text-val">{{ compass(snap.windDeg) }}</div>
    </div>
    <div class="wx-item">
      <div class="lab">温度</div>
      <div class="val">{{ valueText(snap.tempC) }}<small>℃</small></div>
    </div>
    <div class="wx-item">
      <div class="lab">湿度</div>
      <div class="val">{{ humidityText }}<small>%</small></div>
    </div>
    <div class="wx-item" :class="cls(present(snap.windSpeed) && snap.windSpeed >= 12, present(snap.windSpeed) && snap.windSpeed >= 8)">
      <div class="lab">平均风速</div>
      <div class="val">{{ valueText(snap.windSpeed) }}<small>m/s</small></div>
    </div>
    <div class="wx-item" :class="cls(present(snap.windGust) && snap.windGust >= 18, present(snap.windGust) && snap.windGust >= 12)">
      <div class="lab">阵风</div>
      <div class="val">{{ valueText(snap.windGust) }}<small>m/s</small></div>
    </div>
    <div class="wx-item" :class="cls(present(snap.precipMmh) && snap.precipMmh >= 5, present(snap.precipMmh) && snap.precipMmh >= 1)">
      <div class="lab">降水强度</div>
      <div class="val">{{ valueText(snap.precipMmh, 2) }}<small>mm/h</small></div>
    </div>
    <div class="wx-item" :class="cls(present(snap.visibilityM) && snap.visibilityM <= 1000, present(snap.visibilityM) && snap.visibilityM <= 5000)">
      <div class="lab">能见度</div>
      <div class="val">{{ visibilityText }}<small>km</small></div>
    </div>
    <div class="wx-item" :class="cls(present(snap.thunderProb) && snap.thunderProb >= 0.6, present(snap.thunderProb) && snap.thunderProb >= 0.2)">
      <div class="lab">雷暴概率</div>
      <div class="val">{{ thunderText }}<small>%</small></div>
    </div>
    <div class="wx-item">
      <div class="lab">气压</div>
      <div class="val">{{ valueText(snap.pressureHpa) }}<small>hPa</small></div>
    </div>
    <div class="wx-item">
      <div class="lab">云量</div>
      <div class="val">{{ present(snap.cloudCover) ? Math.round(snap.cloudCover * 100) : '--' }}<small>%</small></div>
    </div>
    <div class="wx-item">
      <div class="lab">观测时间</div>
      <div class="val observation-time">{{ cur.obsTime || snap.time ? new Date(cur.obsTime || snap.time).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false}) : '—' }}<small>北京时间</small></div>
    </div>
  </div>
  <div v-else style="color:#6f95c4;padding:20px 0">等待首轮监测数据…</div>
</template>

<style scoped>
.text-val { font-size: 15px !important; line-height: 1.45; }
.observation-time { font-size:12px!important;white-space:normal!important;overflow-wrap:anywhere; }
</style>
