<template>
  <ChartFrame :name="name" :title="title" :unit="unit" :vh="rows.length * 26 + 10" :empty="empty" :aria="aria">
    <g v-for="(r, i) in rows" :key="r.label + i" :transform="`translate(0 ${i * 26 + 8})`">
      <!-- 轨道 -->
      <rect x="104" y="2" width="432" height="13" rx="3" fill="rgba(120,170,200,.13)" />
      <!-- 实测值：越过阈值的标红 -->
      <rect x="104" :y="2" :width="Math.max(2, barW(r))" height="13" rx="3" :fill="r.fail ? '#e2563f' : fillOf(r)" />
      <!-- 阈值线（虚线 + 上方小三角）。**所有行共用一把尺**，否则同一阈值在不同行落到不同位置，横向没法比 -->
      <template v-if="r.threshold != null">
        <line :x1="xOf(r.threshold)" :x2="xOf(r.threshold)" y1="0" y2="17" stroke="#ffc857" stroke-width="1" stroke-dasharray="3 2" />
        <path :d="`M${xOf(r.threshold)} 0 l-3 -4 l6 0 z`" fill="#ffc857" />
      </template>
      <text x="0" y="12" font-size="10" fill="#a9c4d6">{{ r.label }}</text>
      <text x="632" y="12" font-size="10" text-anchor="end" :fill="r.fail ? '#ff8d78' : '#d6e8f5'">{{ r.display }}</text>
    </g>
    <g :transform="`translate(104 ${rows.length * 26 + 4})`">
      <line x1="0" x2="10" y1="-4" y2="-4" stroke="#ffc857" stroke-width="1" stroke-dasharray="3 2" />
      <text x="13" y="-1" font-size="8.5" fill="#7d9cb3">虚线＝判据阈值</text>
    </g>
  </ChartFrame>
</template>

<script setup>
import { computed } from 'vue'
import ChartFrame from './ChartFrame.vue'

/** rows: [{ label, value, threshold?, display, fail? }]，value 与 threshold 必须同单位 */
const props = defineProps({
  name: { type: String, default: 'bar-threshold' },
  title: { type: String, default: '' },
  unit: { type: String, default: '' },
  rows: { type: Array, default: () => [] },
  empty: { type: String, default: '' },
  aria: { type: String, default: '' },
})

// 全局标尺：取所有行里 value 与 threshold 的最大值，留 12% 余量
const gmax = computed(() => {
  const vals = []
  for (const r of props.rows) {
    if (typeof r.value === 'number') vals.push(r.value)
    if (typeof r.threshold === 'number') vals.push(r.threshold)
  }
  const m = vals.length ? Math.max(...vals) : 1
  return m > 0 ? m * 1.12 : 1
})
function xOf(v) {
  return 104 + Math.min(432, (Number(v) / gmax.value) * 432)
}
function barW(r) {
  return xOf(r.value) - 104
}
function fillOf(r) {
  return r.fail ? '#e2563f' : '#4fae86'
}
</script>
