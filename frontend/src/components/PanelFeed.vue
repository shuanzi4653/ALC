<script setup>
import { computed } from 'vue'
import { store } from '../api.js'
import { levelColor, levelLabel, fmtDateTime } from '../utils.js'

const alerts = computed(() => store.dash.alerts || [])

// 三行展示最近 3 条预警
const rows = computed(() => alerts.value.slice(0, 3))
</script>

<template>
  <div class="feed-rows" v-if="rows.length">
    <div v-for="(a, i) in rows" :key="a.id || i" class="feed-line"
         :style="{ borderLeftColor: levelColor(a.level) }">
      <span class="feed-lv" :style="{ color: levelColor(a.level), borderColor: levelColor(a.level) }">
        {{ levelLabel(a.level) }}
      </span>
      <span class="feed-time">{{ fmtDateTime(a.ts) }}</span>
      <span class="feed-text" :title="a.text">{{ a.text }}</span>
      <span class="feed-region">{{ a.region }}</span>
    </div>
  </div>
  <div v-else class="feed-empty">暂无预警信息，各作业区运行平稳</div>
</template>

<style scoped>
.feed-rows { display: flex; flex-direction: column; gap: 6px; height: 100%; justify-content: center; }
.feed-line { display: flex; align-items: center; gap: 10px; flex: 1; min-height: 0;
  border-left: 3px solid; background: linear-gradient(90deg, rgba(28,58,104,.45), rgba(16,36,68,.25));
  border-radius: 0 6px 6px 0; padding: 4px 12px; overflow: hidden; }
.feed-lv { font-size: 11px; font-weight: 700; border: 1px solid; border-radius: 3px; padding: 0 6px; flex: none; }
.feed-time { font-size: 11px; color: #51719e; flex: none; font-variant-numeric: tabular-nums; }
.feed-text { font-size: 12px; color: #b9d2ec; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; min-width: 0; }
.feed-region { font-size: 11px; color: #6f95c4; flex: none; }
.feed-empty { color: #51719e; font-size: 12px; padding: 10px 4px; }
</style>
