<script setup>
import { computed } from 'vue'
import { store } from '../api.js'
import { levelColor, levelLabel, fmtDateTime } from '../utils.js'

const alerts = computed(() => store.dash.alerts || [])
const triggerLabel = { LEVEL_REACH: '等级触发', SFI_DROP: '指数骤降' }
</script>

<template>
  <div v-if="alerts.length" class="al-list">
    <div v-for="a in alerts.slice(0, 5)" :key="a.id" class="al-item"
         :style="{ borderLeftColor: levelColor(a.level) }">
      <div class="al-top">
        <span class="al-lv" :style="{ color: levelColor(a.level), borderColor: levelColor(a.level) }">
          {{ levelLabel(a.level) }}预警
        </span>
        <span class="al-trigger">{{ triggerLabel[a.triggerType] || a.triggerType }}</span>
        <span class="al-ts">{{ fmtDateTime(a.ts) }}</span>
      </div>
      <div class="al-text" :title="a.text">{{ a.text }}</div>
    </div>
  </div>
  <div v-else style="color:#6f95c4;padding:14px 4px;font-size:12px">暂无预警记录，运行状态平稳</div>
</template>

<style scoped>
.al-list { display: flex; flex-direction: column; gap: 8px; height: 100%; overflow-y: auto; }
.al-item { border-left: 3px solid; background: rgba(20,40,70,.5); border-radius: 0 4px 4px 0; padding: 6px 10px; }
.al-top { display: flex; align-items: center; gap: 8px; margin-bottom: 3px; }
.al-lv { font-size: 11px; font-weight: 700; border: 1px solid; border-radius: 3px; padding: 0 6px; }
.al-trigger { font-size: 10px; color: #6f95c4; }
.al-ts { margin-left: auto; font-size: 10px; color: #51719e; }
.al-text { font-size: 11px; color: #a9c4e4; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
</style>
