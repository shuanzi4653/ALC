<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import echarts from '../echarts.js'
import { store } from '../api.js'
import { levelColor, levelLabel, levelStyle } from '../utils.js'
import { useMapLayers } from '../composables/useMapLayers.js'
import {
  buildRouteSeries, buildWeatherSeries, buildRiskSeries, buildOperationPoint
} from '../map/layerRenderers.js'
import MapLayerControls from './MapLayerControls.vue'
import MapLayerLegend from './MapLayerLegend.vue'

const layerLabels = { wind: '密集风场', precipitation: '不规则雨场', thunder: '不规则雷暴场', risk: '运行限制区', routes: '安全航线' }
const enabled = reactive({ wind: true, precipitation: true, thunder: true, risk: true, routes: true })
const { layers, status: layersStatus, error: layersError } = useMapLayers()
const dash = computed(() => store.dash)
const cur = computed(() => dash.value.current || {})
const snap = computed(() => cur.value.snapshot || {})
const validNumber = value => typeof value === 'number' && Number.isFinite(value)
const center = computed(() => [validNumber(dash.value.lon) ? dash.value.lon : 121.61,
  validNumber(dash.value.lat) ? dash.value.lat : 38.91])
const finalTrack = computed(() => dash.value.tracks?.[0] || {})
const finalLevel = computed(() => finalTrack.value.fusedLevel || cur.value.level)
const finalSfi = computed(() => finalTrack.value.fusedSfi ?? cur.value.sfi)
const color = computed(() => levelColor(finalLevel.value))
/** 统一等级样式：填充/边框/范围文案都从此处取，避免颜色与措辞分叉 */
const style = computed(() => levelStyle(finalLevel.value))
const layerState = computed(() => ({ LOADING: '加载中', READY: dash.value.dataStatus === 'STALE' ? '已过期' : '已更新',
  ERROR: '加载失败', EXPIRED: '已过期', NO_DATA: '无数据' })[layersStatus.value] || '无数据')
const sourceText = computed(() => ({ sim: '模拟/示意', live: '实时点观测', unavailable: '数据源不可用' })[dash.value.effectiveSource] || '来源未知')
const findLayer = kind => layers.value.find(layer => layer.kind === kind)
const layerDetails = computed(() => {
  const statusLabel = { READY: '有效', NO_DATA: '无数据', EXPIRED: '已过期', ERROR: '异常' }
  return [
    ['WIND', '区域风场', l => l?.status === 'READY' ? `${l.data.samples?.length || l.data.points?.length || 1} 个区域采样 · ${Number(l.data.windSpeed).toFixed(1)} m/s` : statusLabel[l?.status] || '加载中'],
    ['PRECIPITATION', '降水范围', l => l?.status === 'READY' ? `${l.data.cells?.length || 1} 站 · 不规则区域` : statusLabel[l?.status] || '加载中'],
    ['THUNDER_PROBABILITY', '雷暴范围', l => l?.status === 'READY' ? `${l.data.cells?.length || 1} 站 · 不规则区域` : statusLabel[l?.status] || '加载中']
  ].map(([kind, label, value]) => { const layer = findLayer(kind); return { kind, label, value: value(layer), status: layer?.status || 'LOADING' } })
})

const chartEl = ref(null)
/** 用户是否已手动调整过视角（用于提示可一键回中） */
const viewMoved = ref(false)
let chart = null
let resizeObserver = null

// ---------------- 渲染组装（B02/B03） ----------------
// 初始化与数据更新分离：geo 视角只在 initMap/resetView 设置，draw 只替换 series，
// 因此用户缩放拖动后，自动刷新与轨2补全都不会把视角拉回默认位置。

function initMap() {
  chart.setOption({
    tooltip: { trigger: 'item', formatter: p => p.name || '' },
    geo: { map: 'northeast', roam: true, zoom: 1.12, center: [125.9, 45.0],
      scaleLimit: { min: 1, max: 8 }, itemStyle: { areaColor: '#122d4b', borderColor: '#4a82ad', borderWidth: 1.2 },
      emphasis: { disabled: true }, select: { disabled: true },
      label: { show: true, color: '#6e9abe', fontSize: 11, formatter: p => p.name.replace('省', '') } }
  })
  // 记录用户视角，仅用于「是否已偏离默认视角」的展示，不改动 geo
  chart.on('georoam', () => { viewMoved.value = true })
}

function draw() {
  if (!chart) return
  const c = center.value
  const riskLayer = findLayer('RISK_AREA')
  const series = [
    ...buildRouteSeries(c, color.value, enabled.routes, riskLayer),
    ...buildWeatherSeries({ center: c, findLayer, enabled }),
    ...buildRiskSeries({ center: c, layer: riskLayer, level: finalLevel.value, style: style.value, enabled: enabled.risk }),
    buildOperationPoint({
      center: c,
      region: dash.value.region,
      sfi: finalSfi.value,
      conditionText: snap.value.conditionText,
      levelLabel: levelLabel(finalLevel.value),
      color: color.value
    })
  ]
  chart.setOption({ series }, { replaceMerge: ['series'] })
}

function resetView() {
  chart?.setOption({ geo: { center: [125.9, 45.0], zoom: 1.12 } })
  viewMoved.value = false
}

onMounted(async () => {
  await nextTick()
  chart = echarts.init(chartEl.value)
  initMap()
  draw()
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(chartEl.value)
})
onUnmounted(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
})
watch(() => [dash.value.runSequence, dash.value.revision, dash.value.region, dash.value.lat, dash.value.lon], draw)
watch(layers, draw)
watch(enabled, draw, { deep: true })
</script>

<template>
  <div class="map-wrap">
    <div ref="chartEl" class="map-chart"></div>
    <MapLayerControls
      :enabled="enabled"
      :labels="layerLabels"
      :state-text="layerState"
      :source-text="sourceText"
      :error-text="layersError"
      @reset="resetView"
    />
    <div class="map-tip">气象范围与运行限制区独立 · 航线自动左右绕行，绕行超 1 小时关闭<template v-if="viewMoved"> · 已偏离默认视角</template></div>
    <MapLayerLegend :weather="layerDetails" :source-text="sourceText" :valid-time="dash.obsTime || ''" />
  </div>
</template>

<style scoped>
.map-wrap { position: relative; width: 100%; height: 100%; }
.map-chart { width: 100%; height: 100%; }
.map-tip { position: absolute; left: 12px; top: 8px; font-size: 10px; color: #51719e; }
</style>
