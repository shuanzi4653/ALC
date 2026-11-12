<template>
  <ChartFrame :name="name" :title="title" :unit="unit" :vh="rows.length * 30 + 12" :empty="empty" :aria="aria">
    <g v-for="(r, i) in rows" :key="r.label + i" :transform="`translate(0 ${i * 30 + 8})`">
      <rect x="96" y="4" width="420" height="15" rx="3" fill="rgba(120,170,200,.13)" />
      <rect x="96" y="4" :width="Math.max(2, wOf(r))" height="15" rx="3"
            :fill="r.recommended ? '#4fae86' : (r.available === false ? 'rgba(120,170,200,.25)' : '#5c86a8')" />
      <text x="0" y="15" font-size="10" :fill="r.available === false ? '#5f7c90' : '#a9c4d6'">{{ r.label }}</text>
      <text x="632" y="15" font-size="10" text-anchor="end" fill="#d6e8f5">{{ r.display }}</text>
      <text x="96" y="29" font-size="8.5" fill="#7d9cb3">{{ r.parts }}</text>
      <text v-if="r.recommended" x="524" y="15" font-size="8.5" fill="#6fe0a8">推荐</text>
    </g>
  </ChartFrame>
</template>

<script setup>
import ChartFrame from './ChartFrame.vue'

/** rows: [{ label, cost, display, parts, recommended?, available? }] */
const props = defineProps({
  name: { type: String, default: 'option-bars' },
  title: { type: String, default: '' },
  unit: { type: String, default: '' },
  rows: { type: Array, default: () => [] },
  empty: { type: String, default: '' },
  aria: { type: String, default: '' },
})
function maxCost() {
  const vals = props.rows.filter((r) => r.available !== false).map((r) => Number(r.cost) || 0)
  const m = vals.length ? Math.max(...vals) : 1
  return m > 0 ? m * 1.06 : 1
}
function wOf(r) {
  return Math.min(418, ((Number(r.cost) || 0) / maxCost()) * 418)
}
</script>
