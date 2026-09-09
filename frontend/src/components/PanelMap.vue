<script setup>
import { computed, onMounted, onUnmounted, nextTick, ref, watch } from 'vue'
import * as echarts from 'echarts'
import chinaJson from '../assets/china.json'
import { store } from '../api.js'
import { levelColor, levelLabel } from '../utils.js'

// 注册中国地图（DataV GeoJSON，含九段线）
echarts.registerMap('china', chinaJson)

const dash = computed(() => store.dash)
const center = computed(() => [Number(dash.value.lon) || 121.61, Number(dash.value.lat) || 38.91])
const cur = computed(() => dash.value.current || {})
const snap = computed(() => cur.value.snapshot || {})
const color = computed(() => levelColor(cur.value.level))

// 示意航线：作业区 → 周边机场/城市（初代演示数据）
const DESTS = [
  { name: '烟台', coord: [121.37, 37.55] },
  { name: '威海', coord: [122.12, 37.51] },
  { name: '青岛', coord: [120.38, 36.07] },
  { name: '沈阳', coord: [123.42, 41.68] },
  { name: '天津', coord: [117.20, 39.13] }
]

/** 风向指示线终点：气象风向为"来向"（北=0°顺时针），箭头沿风吹去的方向 */
function windLine(c) {
  const deg = Number(snap.value.windDeg ?? 0)
  const speed = Number(snap.value.windSpeed ?? 0)
  const len = 0.35 + Math.min(speed, 20) * 0.035      // 风速越大线越长（0.35~1.05 度）
  const rad = ((deg + 180) % 360) * Math.PI / 180
  const dLat = len * Math.cos(rad)
  const dLon = len * Math.sin(rad) / Math.max(0.4, Math.cos(c[1] * Math.PI / 180))
  return [[c[0], c[1]], [c[0] + dLon, c[1] + dLat]]
}

const chartEl = ref(null)
let chart = null

function draw() {
  if (!chart) return
  const c = center.value
  const lines = DESTS.map(d => ({ coords: [c, d.coord] }))
  const lv = cur.value.level
  const risky = lv === 'DANGER' || lv === 'BAN'

  chart.setOption({
    tooltip: { show: false },
    geo: {
      map: 'china',
      roam: true,                                          // 滚轮缩放 + 拖动平移
      zoom: 5.2, center: [c[0] - 1.5, c[1] + 2.5],
      scaleLimit: { min: 3, max: 14 },
      itemStyle: { areaColor: '#12233f', borderColor: '#2a4a73' },
      emphasis: { disabled: true },
      select: { disabled: true },
      label: { show: false }
    },
    series: [
      // 航线动效（按当前风险等级着色）
      {
        type: 'lines', coordinateSystem: 'geo', zlevel: 2,
        lineStyle: { color: color.value, width: 1.2, opacity: 0.4, curveness: 0.18 },
        effect: { show: true, period: 5, trailLength: 0.25, symbol: 'arrow', symbolSize: 5, color: '#cfe8ff' },
        data: lines
      },
      // 周边航点
      {
        type: 'effectScatter', coordinateSystem: 'geo', zlevel: 2,
        symbolSize: 6, rippleEffect: { scale: 2.2, brushType: 'stroke' },
        itemStyle: { color: '#3fa7ff' },
        label: { show: true, position: 'right', color: '#6f95c4', fontSize: 10, formatter: p => p.name },
        data: DESTS.map(d => ({ name: d.name, value: [...d.coord, 1] }))
      },
      // 风向指示线（箭头沿风吹去方向，长度示意风速）
      {
        type: 'lines', coordinateSystem: 'geo', zlevel: 3,
        lineStyle: { color: '#8fb4de', width: 2, opacity: 0.85 },
        effect: { show: true, period: 3, trailLength: 0.4, symbol: 'arrow', symbolSize: 7, color: '#e8f4ff', loop: true },
        data: [{ coords: windLine(c) }]
      },
      // 作业区（SFI 着色）
      {
        type: 'effectScatter', coordinateSystem: 'geo', zlevel: 4,
        symbolSize: 13, rippleEffect: { scale: 3.5, brushType: 'stroke' },
        itemStyle: { color: color.value, shadowBlur: 14, shadowColor: color.value },
        label: {
          show: true, position: 'top', color: '#dce9f7', fontSize: 12, fontWeight: 700,
          formatter: () => {
            const sfi = cur.value.sfi ?? '--'
            const txt = snap.value.conditionText || ''
            return `${dash.value.region || '作业区'} · SFI ${sfi} · ${txt} · ${levelLabel(lv)}`
          }
        },
        data: [{ name: dash.value.region, value: [...c, 10] }]
      },
      // 风险/作业影响范围：半透明填充面 + 虚线边框（custom 多边形，随地图缩放平移）
      {
        type: 'custom', coordinateSystem: 'geo', zlevel: 3, silent: true,
        renderItem: (params, api) => {
          const half = risky ? 0.85 : 0.55
          const x0 = c[0] - half, y0 = c[1] - half * 0.72
          const x1 = c[0] + half, y1 = c[1] + half * 0.72
          const pts = [api.coord([x0, y0]), api.coord([x1, y0]), api.coord([x1, y1]), api.coord([x0, y1])]
          return {
            type: 'polygon',
            shape: { points: pts },
            style: {
              fill: risky ? 'rgba(192,57,43,.16)' : 'rgba(46,139,87,.10)',
              stroke: risky ? 'rgba(255,107,90,.8)' : 'rgba(46,139,87,.6)',
              lineWidth: 1.6,
              lineDash: [7, 5]
            }
          }
        },
        data: [[0]]
      },
      // 范围标签（隐形锚点 + label）
      {
        type: 'effectScatter', coordinateSystem: 'geo', zlevel: 3, silent: true,
        symbolSize: 0,
        label: {
          show: true, position: 'top', fontSize: 10,
          color: risky ? '#ff9a8a' : '#7ee2a8',
          formatter: () => risky ? '风险影响区（禁入）' : '作业影响范围'
        },
        data: [{ name: '', value: [c[0], c[1] + (risky ? 0.85 : 0.55) * 0.72] }]
      }
    ]
  })
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
watch(() => [store.dash.current, store.dash.region], draw)
</script>

<template>
  <div class="map-wrap">
    <div ref="chartEl" class="map-chart"></div>
    <div class="map-tip">滚轮缩放 · 按住拖动</div>
    <div class="map-legend">
      <span class="lg"><i style="background:#2e8b57"></i>适飞</span>
      <span class="lg"><i style="background:#d98a2b"></i>谨慎</span>
      <span class="lg"><i style="background:#d85a30"></i>危险</span>
      <span class="lg"><i style="background:#c0392b"></i>禁飞</span>
    </div>
  </div>
</template>

<style scoped>
.map-wrap { position: relative; width: 100%; height: 100%; }
.map-chart { width: 100%; height: 100%; }
.map-tip { position: absolute; left: 12px; top: 8px; font-size: 10px; color: #51719e; }
.map-legend { position: absolute; left: 12px; bottom: 10px; display: flex; gap: 12px; }
.lg { font-size: 10px; color: #6f95c4; display: inline-flex; align-items: center; gap: 4px; }
.lg i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
</style>
