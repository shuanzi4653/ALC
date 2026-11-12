<template>
  <ChartFrame :name="name" :title="title" :unit="unit" :vh="66" :empty="empty" :aria="aria">
    <line x1="10" y1="26" x2="630" y2="26" stroke="rgba(120,170,200,.35)" stroke-width="1" />
    <g v-for="(pt, i) in placed" :key="pt.label + i">
      <circle :cx="pt.x" cy="26" r="4" :fill="pt.tone" />
      <line :x1="pt.x" :x2="pt.x" y1="30" :y2="pt.labelY" stroke="rgba(120,170,200,.3)" stroke-width="1" />
      <text :x="pt.x" :y="pt.labelY + 11" font-size="9" text-anchor="middle" fill="#a9c4d6">{{ pt.label }}</text>
      <text :x="pt.x" :y="pt.labelY + 22" font-size="9.5" text-anchor="middle" fill="#d6e8f5">{{ pt.text }}</text>
    </g>
  </ChartFrame>
</template>

<script setup>
import { computed } from 'vue'
import ChartFrame from './ChartFrame.vue'

/** points: [{ label, minute, text, tone? }]，minute 为当天第几分钟 */
const props = defineProps({
  name: { type: String, default: 'timeline' },
  title: { type: String, default: '' },
  unit: { type: String, default: '' },
  points: { type: Array, default: () => [] },
  empty: { type: String, default: '' },
  aria: { type: String, default: '' },
})
const TONE = { planned: '#5c86a8', actual: '#4fae86', now: '#ffc857', request: '#8aa8bd' }
const placed = computed(() => {
  const list = (props.points || []).filter((p) => typeof p.minute === 'number' && p.minute >= 0)
  if (!list.length) return []
  const lo = Math.min(...list.map((p) => p.minute))
  const hi = Math.max(...list.map((p) => p.minute))
  const span = Math.max(30, hi - lo)
  return list.map((p, i) => ({
    ...p,
    x: 14 + ((p.minute - lo) / span) * 612,
    // 相邻标签错开，避免同一时刻的"计划/实际"两行字叠在一起
    labelY: i % 2 === 0 ? 36 : 46,
    tone: TONE[p.kind] || '#5c86a8',
  }))
})
</script>
