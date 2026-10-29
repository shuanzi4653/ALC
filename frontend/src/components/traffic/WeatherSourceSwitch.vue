<script setup>
import { computed, ref } from 'vue'
import { requestJson } from '../../api.js'
import {
  WEATHER_MODE_MEASURED, WEATHER_MODE_VIRTUAL,
  normalizeWeatherMode, weatherModeIsVirtual, weatherModeButtonState, weatherModeStatusText,
} from '../../traffic/runtime.js'

const props = defineProps({
  mode: { type: String, default: WEATHER_MODE_MEASURED },
  status: { type: Object, default: null },
  compact: { type: Boolean, default: false },
})

const emit = defineEmits(['change'])

const busy = ref(false)
const error = ref('')
const notice = ref('')

const isVirtual = computed(() => weatherModeIsVirtual(props.mode))
const buttons = computed(() => [WEATHER_MODE_MEASURED, WEATHER_MODE_VIRTUAL].map(target => ({
  target,
  ...weatherModeButtonState(props.mode, target, busy.value),
})))
const statusText = computed(() => weatherModeStatusText(props.mode, props.status))
const virtualNotice = computed(() => (props.status?.virtualNotice?.statement) || '')

async function switchTo(target) {
  const wanted = normalizeWeatherMode(target)
  if (busy.value) return
  if (wanted === normalizeWeatherMode(props.mode)) {
    error.value = ''
    notice.value = `模式未变化（仍为${weatherModeButtonState(props.mode, wanted).label}）`
    return
  }
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await requestJson('/api/traffic/weather/mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: wanted, actor: '运行台', reason: '操作台手动切换气象通道' }),
      timeoutMs: 12_000,
    })
    notice.value = result?.changed
      ? `已切换到${weatherModeButtonState(result.mode, result.mode).label}`
      : `模式未变化（仍为${weatherModeButtonState(result?.mode, result?.mode).label}）`
    emit('change', result)
  } catch (e) {
    error.value = e?.message || '切换失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="weather-switch" :class="{ compact, virtual: isVirtual }">
    <div class="row">
      <span class="caption">气象通道</span>
      <button
        v-for="b in buttons"
        :key="b.target"
        type="button"
        class="mode-btn"
        :class="{ on: b.active, virtual: b.target === WEATHER_MODE_VIRTUAL }"
        :disabled="b.disabled"
        :title="b.hint"
        :aria-pressed="b.active"
        @click="switchTo(b.target)"
      >{{ b.label }}<small v-if="b.active">当前</small></button>
      <span v-if="busy" class="busy">切换中…</span>
    </div>
    <p class="status" :class="{ warn: isVirtual }">{{ statusText }}</p>
    <p v-if="isVirtual && virtualNotice" class="notice">{{ virtualNotice }}</p>
    <p v-if="notice" class="outcome" role="status">{{ notice }}</p>
    <p v-if="error" class="error" role="alert">切换失败：{{ error }}</p>
  </div>
</template>

<style scoped>
.weather-switch { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.weather-switch .row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.weather-switch.compact { flex-direction: row; align-items: center; gap: 8px; flex-wrap: wrap; }
.weather-switch.compact .row { flex-wrap: wrap; }
.caption { font-size: 10px; color: #7fa5bd; letter-spacing: .04em; white-space: nowrap; }
.mode-btn {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 6px 13px; font-size: 12px; font-weight: 500;
  background: #122334; color: #bcd3e2; border: 1px solid #2d4a5f; border-radius: 6px;
  white-space: nowrap; flex: 0 0 auto;
}
.mode-btn small { font-size: 9px; opacity: .8; font-weight: 400; }
.mode-btn:hover:not(:disabled) { border-color: #65cce5; color: #fff; }
.mode-btn:disabled { cursor: default; opacity: .5; }
.mode-btn.on { background: #1d4f66; border-color: #4aa8c4; color: #dff7ff; opacity: 1; cursor: default; }
.mode-btn.on.virtual { background: #6b3d12; border-color: #d9963f; color: #ffe4bd; }
.mode-btn.on.virtual::before,
.weather-switch.virtual .mode-btn.on::before { content: '\25B2'; font-size: 8px; }
.weather-switch.virtual { border-left: 3px solid #d9963f; padding-left: 10px; border-radius: 3px; }
.busy { font-size: 10px; color: #d9b06a; }
.status { font-size: 10px; color: #6f95c4; line-height: 1.6; margin: 0; }
.status.warn { color: #e8b96a; }
.notice { font-size: 10px; color: #f0c98a; line-height: 1.7; margin: 0;
  padding: 5px 9px; background: rgba(120, 70, 18, .28); border: 1px solid rgba(217, 150, 63, .45); border-radius: 4px; }
.error { font-size: 10px; color: #ffd9a8; margin: 0; }
.outcome { font-size: 10px; color: #8fe0a8; margin: 0; }
.compact .notice { display: none; }
.compact .status { display: none; }
.compact .outcome, .compact .error { padding: 4px 8px; border-radius: 4px; }
.compact .error { background: rgba(90, 44, 16, .5); border: 1px solid rgba(255, 217, 168, .5); }
</style>
