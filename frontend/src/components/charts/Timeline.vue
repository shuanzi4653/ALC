<template>
  <ChartFrame :name="name" :title="title" :unit="unit" :vw="680" :vh="frameH" :empty="empty" :aria="aria">
    <line x1="16" y1="26" x2="632" y2="26" stroke="rgba(120,170,200,.35)" stroke-width="1" />
    <g v-for="(pt, i) in placed" :key="pt.label + i">
      <circle :cx="pt.x" cy="26" r="4" :fill="pt.tone" />
      <line :x1="pt.x" :x2="pt.labelX" y1="30" :y2="pt.labelY - 8" stroke="rgba(120,170,200,.3)" stroke-width="1" />
      <text :x="pt.labelX" :y="pt.labelY" font-size="9.5" text-anchor="middle" fill="#a9c4d6">{{ pt.caption }}</text>
    </g>
  </ChartFrame>
</template>

<script setup>
import { computed } from 'vue'
import ChartFrame from './ChartFrame.vue'

/** points: [{ label, minute, text, kind? }]，minute 为当天第几分钟 */
const props = defineProps({
  name: { type: String, default: 'timeline' },
  title: { type: String, default: '' },
  unit: { type: String, default: '' },
  points: { type: Array, default: () => [] },
  empty: { type: String, default: '' },
  aria: { type: String, default: '' },
})

const TONE = { planned: '#5c86a8', actual: '#4fae86', now: '#ffc857', request: '#8aa8bd' }

// 文字宽度估算：中文按 9.5px、数字与字母按 5.6px、空格按 3px。
// 只用它做**标签避让**，不参与任何数值计算，估宽了顶多多分一道，估窄了会重叠 ——
// 所以宁可估宽。
function widthOf(s) {
  let w = 0
  for (const ch of String(s)) {
    if (/[\u4e00-\u9fff]/.test(ch)) w += 9.5
    else if (ch === ' ') w += 3
    else w += 5.6
  }
  return w
}

// 原实现把标签固定成两行（labelY 36 / 46），可两行文字本身要 22px 高，
// 行距 10px 时第二行的"申请"正好压在第一行的"08:45"上 —— 截图里那团字就是这么来的。
//
// 现在改成：一行「申请 08:45」+ 贪心分道。点仍在真实时间位置（不改数据），
// 只有标签可以横向夹紧、纵向错开，并用引线连回自己的点。
const placed = computed(() => {
  const list = (props.points || []).filter((p) => typeof p.minute === 'number' && p.minute >= 0)
  if (!list.length) return []
  const lo = Math.min(...list.map((p) => p.minute))
  const hi = Math.max(...list.map((p) => p.minute))
  const span = Math.max(30, hi - lo)
  const rows = list.map((p) => ({ ...p, x: 16 + ((p.minute - lo) / span) * 616 }))

  const laneEnd = []
  for (const p of [...rows].sort((a, b) => a.x - b.x)) {
    const caption = `${p.label} ${p.text}`
    const half = widthOf(caption) / 2
    const labelX = Math.min(678 - half - 2, Math.max(half + 2, p.x))
    let lane = 0
    while (lane < 6 && laneEnd[lane] != null && labelX - half < laneEnd[lane] + 8) lane += 1
    laneEnd[lane] = labelX + half
    p.caption = caption
    p.labelX = labelX
    p.lane = lane
    p.labelY = 34 + lane * 15
  }
  return rows.map((p) => ({ ...p, tone: TONE[p.kind] || '#5c86a8' }))
})

const frameH = computed(() => {
  const maxLane = placed.value.reduce((m, p) => Math.max(m, p.lane || 0), 0)
  return 34 + (maxLane + 1) * 15 + 6
})
</script>
