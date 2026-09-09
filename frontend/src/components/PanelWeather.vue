<script setup>
import { computed } from 'vue'
import { store } from '../api.js'

const cur = computed(() => store.dash.current)
const snap = computed(() => cur.value?.snapshot || {})
const humidityText = computed(() => Math.round((snap.value.humidity ?? 0) * 100))

function cls(ban, warn) { return ban ? 'ban' : warn ? 'warn' : '' }
</script>

<template>
  <div v-if="cur" class="wx-grid">
    <div class="wx-item">
      <div class="lab">温度</div>
      <div class="val">{{ snap.tempC }}<small>℃</small></div>
    </div>
    <div class="wx-item">
      <div class="lab">湿度</div>
      <div class="val">{{ humidityText }}<small>%</small></div>
    </div>
    <div class="wx-item" :class="cls(snap.windSpeed >= 12, snap.windSpeed >= 8)">
      <div class="lab">平均风速</div>
      <div class="val">{{ snap.windSpeed }}<small>m/s</small></div>
    </div>
    <div class="wx-item" :class="cls(snap.windGust >= 18, snap.windGust >= 12)">
      <div class="lab">阵风</div>
      <div class="val">{{ snap.windGust }}<small>m/s</small></div>
    </div>
    <div class="wx-item" :class="cls(snap.precipMmh >= 5, snap.precipMmh >= 1)">
      <div class="lab">降水强度</div>
      <div class="val">{{ snap.precipMmh }}<small>mm/h</small></div>
    </div>
    <div class="wx-item" :class="cls(snap.visibilityM <= 1000, snap.visibilityM <= 5000)">
      <div class="lab">能见度</div>
      <div class="val">{{ (snap.visibilityM / 1000).toFixed(1) }}<small>km</small></div>
    </div>
    <div class="wx-item" :class="cls(snap.thunderProb >= 0.6, snap.thunderProb >= 0.2)">
      <div class="lab">雷暴概率</div>
      <div class="val">{{ Math.round((snap.thunderProb ?? 0) * 100) }}<small>%</small></div>
    </div>
    <div class="wx-item">
      <div class="lab">观测时间</div>
      <div class="val" style="font-size:13px;line-height:1.9">{{ (cur.ts || '').replace('T', ' ').slice(0, 19) }}</div>
    </div>
  </div>
  <div v-else style="color:#6f95c4;padding:20px 0">等待首轮监测数据…</div>
</template>
