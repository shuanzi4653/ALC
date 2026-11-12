<template>
  <!-- 所有图表的公共外框：标题、单位、无数据说明。
       viewBox 固定逻辑宽 640，高度由 `vh` 给；SVG 宽度 100% 自适应，
       等比缩放，不会随容器宽度变形。 -->
  <figure class="ch" :data-chart="name">
    <figcaption v-if="title || unit" class="ch-head">
      <span class="ch-t">{{ title }}</span>
      <span v-if="unit" class="ch-u">{{ unit }}</span>
    </figcaption>
    <svg :viewBox="`0 0 ${vw} ${vh}`" role="img" :aria-label="aria"><slot /></svg>
    <p v-if="empty" class="ch-empty">{{ empty }}</p>
  </figure>
</template>

<script setup>
defineProps({
  name: { type: String, default: '' },
  title: { type: String, default: '' },
  unit: { type: String, default: '' },
  vw: { type: Number, default: 640 },
  vh: { type: Number, default: 120 },
  empty: { type: String, default: '' },
  aria: { type: String, default: '' },
})
</script>

<style scoped>
.ch { margin: 6px 0 9px 0; }
.ch-head { display: flex; align-items: baseline; gap: 6px; margin: 0 0 2px 0; }
.ch-t { font-size: 10.5px; color: #d6e8f5; }
.ch-u { font-size: 9px; color: #7d9cb3; }
.ch svg { width: 100%; height: auto; display: block; overflow: visible; }
.ch-empty { margin: 2px 0 0 0; font-size: 9.5px; color: #7d9cb3; }
html[data-theme="light"] .ch-t { color: #17364d; }
html[data-theme="light"] .ch-u,
html[data-theme="light"] .ch-empty { color: #5b7386; }
</style>
