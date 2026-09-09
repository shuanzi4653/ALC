<script setup>
import { computed, onMounted, onUnmounted, nextTick, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { store } from '../api.js'
import { levelColor, levelLabel } from '../utils.js'

const cur = computed(() => store.dash.current)
const sfiVal = computed(() => cur.value?.sfi ?? 0)
const sfiColor = computed(() => levelColor(cur.value?.level))

const chartEl = ref(null)
let chart = null

function draw() {
  if (!chart) return
  const history = [...(store.dash.sfiHistory || [])].reverse()
  const forecast = store.dash.forecastSfi || []

  const histX = history.map(h => fmt(h.ts))
  const histY = history.map(h => h.sfi)

  // 预测线从最后一个历史点续起
  const fcX = [...histX.slice(-1), ...forecast.map(f => fmt(f.time))]
  const fcY = [...histY.slice(-1), ...forecast.map(f => f.sfi)]

  chart.setOption({
    grid: { left: 34, right: 10, top: 12, bottom: 20 },
    xAxis: {
      type: 'category', data: [...histX, ...fcX.slice(1)],
      axisLine: { lineStyle: { color: '#2a4a73' } },
      axisLabel: { color: '#6f95c4', fontSize: 9, interval: Math.max(0, Math.floor(histX.length / 6)) }
    },
    yAxis: {
      type: 'value', min: 0, max: 100,
      axisLabel: { color: '#6f95c4', fontSize: 9 },
      splitLine: { lineStyle: { color: 'rgba(42,74,115,.35)' } },
      markLine: { silent: true, symbol: 'none', label: { show: false }, data: [
        { yAxis: 80, lineStyle: { color: 'rgba(46,139,87,.5)', type: 'dashed' } },
        { yAxis: 60, lineStyle: { color: 'rgba(217,138,43,.5)', type: 'dashed' } },
        { yAxis: 40, lineStyle: { color: 'rgba(192,57,43,.5)', type: 'dashed' } }
      ] }
    },
    series: [
      {
        name: 'SFI 实测', type: 'line', data: [...histY, ...nulls(fcY.length - 1)],
        smooth: true, symbol: 'none', connectNulls: false,
        lineStyle: { color: '#3fa7ff', width: 2 },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(63,167,255,.35)' },
            { offset: 1, color: 'rgba(63,167,255,0)' }
          ])
        }
      },
      {
        name: 'SFI 预测(0-6h)', type: 'line', data: [...nulls(histY.length - 1), ...fcY],
        smooth: true, symbol: 'circle', symbolSize: 4,
        lineStyle: { color: '#e0a13c', width: 2, type: 'dashed' },
        itemStyle: { color: '#e0a13c' }
      }
    ]
  })
}

function fmt(iso) {
  return String(iso || '').replace('T', ' ').slice(11, 16) || '-'
}

/** 生成 n 个 null（n 为负或 0 时返回空数组，避免 Array(负数) RangeError） */
function nulls(n) {
  return n > 0 ? new Array(n).fill(null) : []
}

onMounted(async () => {
  await nextTick()
  if (chartEl.value) {
    chart = echarts.init(chartEl.value)
    draw()
  }
  window.addEventListener('resize', onResize)
})
function onResize() { chart && chart.resize() }
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  chart && chart.dispose()
})
watch(() => [store.dash.sfiHistory, store.dash.forecastSfi, store.dash.current], draw, { deep: false })
</script>

<template>
  <div class="sfi-wrap">
    <div class="sfi-head">
      <div class="sfi-big" :style="{ color: sfiColor }">
        {{ cur ? sfiVal : '--' }}
      </div>
      <div class="sfi-meta">
        <div class="lv-badge" :style="{ background: sfiColor + '22', borderColor: sfiColor, color: sfiColor }">
          {{ levelLabel(cur?.level) }}
        </div>
        <div class="sfi-sub" style="font-size:11px;color:#6f95c4;margin-top:6px">
          {{ cur ? (cur.source === 'live' ? '和风实时观测' : '模拟数据') : '等待首轮监测…' }}
        </div>
      </div>
      <div class="sfi-checks" v-if="cur && cur.checks && cur.checks.length">
        <div v-for="c in cur.checks.slice(0, 3)" :key="c.factor"
             class="ck" :class="{ bad: c.banned || c.warn }">
          {{ c.factor }} {{ c.value }}{{ c.unit }}
        </div>
      </div>
    </div>
    <div ref="chartEl" class="sfi-chart"></div>
  </div>
</template>

<style scoped>
.sfi-wrap { display: flex; flex-direction: column; height: 100%; }
.sfi-head { display: flex; align-items: center; gap: 14px; padding: 2px 6px; }
.sfi-big { font-size: 42px; font-weight: 800; line-height: 1; text-shadow: 0 0 18px currentColor; min-width: 78px; }
.lv-badge { display: inline-block; padding: 2px 10px; border: 1px solid; border-radius: 3px; font-size: 13px; font-weight: 700; }
.sfi-checks { display: flex; gap: 6px; margin-left: auto; flex-wrap: wrap; justify-content: flex-end; max-width: 46%; }
.ck { font-size: 10px; color: #6f95c4; border: 1px solid #24406a; border-radius: 3px; padding: 1px 5px; }
.ck.bad { color: #ff8f6b; border-color: #7a3a28; }
.sfi-chart { flex: 1; min-height: 0; }
</style>
