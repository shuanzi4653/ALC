<template>
  <ChartFrame :name="name" :title="title" :unit="unit" :vh="58" :aria="aria">
    <!-- 三段区间：谨慎 / 预警 / 延期，边界由后端常量给出，前端不另存阈值 -->
    <rect x="0" y="10" :width="x(1)" height="16" rx="3" fill="rgba(120,170,200,.12)" />
    <rect x="0" y="10" :width="x(caution)" height="16" fill="rgba(79,174,134,.55)" />
    <rect :x="x(caution)" y="10" :width="x(warn) - x(caution)" height="16" fill="rgba(224,162,63,.5)" />
    <rect :x="x(warn)" y="10" :width="x(1) - x(warn)" height="16" rx="3" fill="rgba(226,86,63,.5)" />
    <!-- 指针 -->
    <path :d="`M${x(p)} 26 l-5 8 l10 0 z`" fill="#eaf8ff" />
    <line :x1="x(p)" :x2="x(p)" y1="6" y2="26" stroke="#eaf8ff" stroke-width="1.5" />
    <text :x="x(p)" y="4" font-size="10" text-anchor="middle" fill="#eaf8ff">{{ (p * 100).toFixed(0) }}%</text>
    <!-- 刻度 -->
    <text x="0" y="48" font-size="8.5" fill="#7d9cb3">0</text>
    <text :x="x(caution)" y="48" font-size="8.5" fill="#7d9cb3" text-anchor="middle">谨慎 {{ caution }}</text>
    <text :x="x(warn)" y="48" font-size="8.5" fill="#7d9cb3" text-anchor="middle">预警 {{ warn }}</text>
    <text :x="x(hold)" y="48" font-size="8.5" fill="#7d9cb3" text-anchor="middle">延期 {{ hold }}</text>
    <text x="632" y="48" font-size="8.5" fill="#7d9cb3" text-anchor="end">1.0</text>
  </ChartFrame>
</template>

<script setup>
import ChartFrame from './ChartFrame.vue'

const props = defineProps({
  name: { type: String, default: 'gauge' },
  title: { type: String, default: '' },
  unit: { type: String, default: '' },
  p: { type: Number, default: 0 },
  caution: { type: Number, default: 0.15 },
  warn: { type: Number, default: 0.35 },
  hold: { type: Number, default: 0.75 },
  aria: { type: String, default: '' },
})
const clamp01 = (v) => Math.max(0, Math.min(1, Number(v) || 0))
function x(v) {
  return 8 + clamp01(v) * 616
}
</script>
