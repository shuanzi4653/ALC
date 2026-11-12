<template>
  <ChartFrame :name="name" :title="title" :unit="unit" :vw="680" :vh="rows.length * 26 + 12" :empty="empty" :aria="aria">
    <g v-for="(r, i) in rows" :key="r.label + i" :transform="`translate(0 ${i * 26 + 8})`">
      <!-- 轨道 -->
      <rect :x="BAR_X" y="2" :width="BAR_W" height="13" rx="3" fill="rgba(120,170,200,.13)" />
      <!-- 实测值：越过阈值的标红 -->
      <rect :x="BAR_X" y="2" :width="Math.max(2, barW(r))" height="13" rx="3" :fill="r.fail ? '#e2563f' : fillOf(r)" />
      <!-- 阈值线（虚线 + 上方小三角）。**所有行共用一把尺**，否则同一阈值在不同行落到不同位置，横向没法比 -->
      <template v-if="r.threshold != null">
        <line :x1="xOf(r.threshold)" :x2="xOf(r.threshold)" y1="0" y2="17" stroke="#ffc857" stroke-width="1" stroke-dasharray="3 2" />
        <path :d="`M${xOf(r.threshold)} 0 l-3 -4 l6 0 z`" fill="#ffc857" />
      </template>
      <text x="0" y="12" font-size="10" fill="#a9c4d6">{{ r.label }}</text>
      <text :x="VAL_X" y="12" font-size="10" text-anchor="end" :fill="r.fail ? '#ff8d78' : '#d6e8f5'">{{ r.display }}</text>
    </g>
    <g :transform="`translate(${BAR_X} ${rows.length * 26 + 6})`">
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

// 标签区宽 158：最长的一条是「端点能见度（取两端较差）」12 字 × 10px ≈ 120px，
// 原来只留 104，标签直接压在条形起点上 —— 这是"字和条重合"的真因。
// 数值区从 674 起（右对齐），与条形末端 554 之间留 80px，短的"0.23（低）"也不会贴边。
const BAR_X = 158
const BAR_W = 396
const VAL_X = 674

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
  return BAR_X + Math.min(BAR_W, (Number(v) / gmax.value) * BAR_W)
}
function barW(r) {
  return xOf(r.value) - BAR_X
}
function fillOf(r) {
  return r.fail ? '#e2563f' : '#4fae86'
}
</script>
