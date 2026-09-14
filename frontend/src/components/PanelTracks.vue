<script setup>
import { computed } from 'vue'
import { store } from '../api.js'
import { levelColor, levelLabel, AGREEMENT_LABELS, fmtDateTime } from '../utils.js'

const t = computed(() => (store.dash.tracks && store.dash.tracks[0]) || null)
const agreeLabel = computed(() => AGREEMENT_LABELS[t.value?.agreement] || t.value?.agreement || '-')
</script>

<template>
  <div v-if="t" class="tr-wrap">
    <div class="tr-cols">
      <!-- 轨1 -->
      <div class="tr-card">
        <div class="tr-tag">轨1 · 规则引擎</div>
        <div class="tr-lv" :style="{ color: levelColor(t.track1Level) }">
          {{ levelLabel(t.track1Level) }} <small>{{ t.track1Sfi }}分</small>
        </div>
        <div class="tr-reason" :title="t.track1Reason">{{ t.track1Reason }}</div>
      </div>
      <!-- 轨2 -->
      <div class="tr-card">
        <div class="tr-tag">轨2 · LLM 智能体 <em>{{ t.track2Source }}</em></div>
        <div class="tr-lv" :style="{ color: levelColor(t.track2Level) }">
          {{ levelLabel(t.track2Level) }}
          <small>模型自报 {{ Math.round((t.track2Confidence ?? 0) * 100) }}%（未校准）</small>
        </div>
        <div class="tr-reason" :title="t.track2Factors">{{ t.track2Factors }}</div>
      </div>
    </div>
    <!-- 融合 -->
    <div class="tr-fused">
      <span class="tr-arrow">→</span>
      <span class="tr-fused-lv" :style="{ color: levelColor(t.fusedLevel) }">
        {{ levelLabel(t.fusedLevel) }}
      </span>
      <span class="tr-fused-meta">融合 SFI {{ t.fusedSfi }} · {{ agreeLabel }}</span>
      <span class="tr-ts">{{ fmtDateTime(t.ts) }}</span>
    </div>
    <div class="tr-advice" v-if="t.track2Advice">建议：{{ t.track2Advice }}</div>
  </div>
  <div v-else style="color:#6f95c4;padding:14px 4px;font-size:12px">等待首轮双轨推演结果…</div>
</template>

<style scoped>
.tr-wrap { display: flex; flex-direction: column; gap: 8px; height: 100%; }
.tr-cols { display: flex; gap: 8px; flex: 1; min-height: 0; }
.tr-card { flex: 1; background: rgba(20,40,70,.5); border-radius: 4px; padding: 8px 10px;
  display: flex; flex-direction: column; gap: 4px; overflow: hidden; }
.tr-tag { font-size: 10px; color: #6f95c4; }
.tr-tag em { font-style: normal; color: #51719e; margin-left: 4px; }
.tr-lv { font-size: 20px; font-weight: 800; }
.tr-lv small { font-size: 11px; font-weight: 400; color: #6f95c4; margin-left: 6px; }
.tr-reason { font-size: 10px; color: #a9c4e4; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.tr-fused { display: flex; align-items: center; gap: 8px; background: rgba(63,167,255,.08);
  border: 1px solid #24406a; border-radius: 4px; padding: 6px 10px; }
.tr-arrow { color: #3fa7ff; font-weight: 700; }
.tr-fused-lv { font-size: 18px; font-weight: 800; }
.tr-fused-meta { font-size: 10px; color: #6f95c4; }
.tr-ts { margin-left: auto; font-size: 10px; color: #51719e; }
.tr-advice { font-size: 10px; color: #a9c4e4; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
</style>
