<script setup>
/**
 * 地图图例（B02）。
 * 等级颜色与文案全部来自 utils.js 的 LEVEL_STYLES，保证与图元（点/线/面/标签）一致，
 * 并额外展示「不可判定」灰色态，避免未知被误读为适飞。
 */
import { LEVEL_STYLES, UNKNOWN_STYLE } from '../utils.js'
import { fmtDateTime } from '../utils.js'

defineProps({
  weather: { type: Array, default: () => [] },
  sourceText: { type: String, default: '' },
  validTime: { type: String, default: '' }
})

const items = [
  ...Object.entries(LEVEL_STYLES).map(([key, style]) => ({ key, ...style })),
  { key: '__unknown', ...UNKNOWN_STYLE }
]
</script>

<template>
  <div class="map-legend">
    <div class="levels"><span class="lg" v-for="item in items" :key="item.key">
      <i :style="{ background: item.color }"></i>{{ item.label }}</span></div>
    <div class="weather-row" v-for="item in weather" :key="item.kind" :class="`status-${item.status.toLowerCase()}`">
      <b>{{ item.kind === 'WIND' ? '⇣' : item.kind === 'PRECIPITATION' ? '●' : '◆' }}</b>
      {{ item.label }}：{{ item.value }}
    </div>
    <div class="meta">{{ sourceText }}<template v-if="validTime"> · 时次 {{ fmtDateTime(validTime) }}</template></div>
  </div>
</template>

<style scoped>
.map-legend { position: absolute; left: 12px; bottom: 10px; min-width: 230px; padding: 7px 9px;
  background: rgba(8,21,41,.82); border: 1px solid rgba(64,140,230,.24); border-radius: 4px; }
.levels { display: flex; gap: 9px; flex-wrap: wrap; margin-bottom: 4px; }
.lg { font-size: 10px; color: #6f95c4; display: inline-flex; align-items: center; gap: 4px; }
.lg i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.weather-row { display: inline-flex; gap: 4px; margin-right: 10px; font-size: 10px; color: #9fc1e4; }
.weather-row b { color: #56adff; }
.weather-row.status-no_data, .weather-row.status-expired, .weather-row.status-error { color: #758ba5; }
.meta { margin-top: 3px; font-size: 9px; color: #55779e; }
</style>
