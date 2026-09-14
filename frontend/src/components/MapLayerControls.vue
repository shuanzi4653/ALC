<script setup>
/**
 * 图层控件（B02）。
 * 与「模拟剧本」严格分离：这里只控制**显示显隐**，不触发监测、不调用 LLM、不写回 scenario。
 */
const props = defineProps({
  /** 图层显隐开关对象（引用传递，直接改写属性） */
  enabled: { type: Object, required: true },
  /** 图层名称映射：key → 中文标签 */
  labels: { type: Object, required: true },
  /** 图层加载状态文案（已更新 / 加载中 / 已过期 / 无数据 / 加载失败） */
  stateText: { type: String, default: '无数据' },
  /** 数据来源标注（实时 / 模拟·示意） */
  sourceText: { type: String, default: '' },
  /** 状态提示（悬浮显示错误原因） */
  errorText: { type: String, default: '' }
})

defineEmits(['reset'])
</script>

<template>
  <div class="map-tools">
    <div class="layer-state" :title="errorText">图层：{{ stateText }}<template v-if="sourceText"> · {{ sourceText }}</template></div>
    <label v-for="(label, key) in labels" :key="key">
      <input v-model="enabled[key]" type="checkbox" />{{ label }}
    </label>
    <button class="btn reset" type="button" @click="$emit('reset')">东北全域</button>
  </div>
</template>

<style scoped>
.map-tools { position: absolute; right: 10px; top: 8px; display: flex; align-items: center; gap: 8px;
  padding: 5px 8px; background: rgba(8,21,41,.84); border: 1px solid rgba(64,140,230,.3); border-radius: 4px;
  backdrop-filter: blur(2px); }
.map-tools label { font-size: 10px; color: #9bb9da; display: inline-flex; align-items: center; gap: 3px; cursor: pointer; }
.map-tools input { accent-color: #3fa7ff; }
.layer-state { font-size: 10px; color: #6f95c4; }
.reset { padding: 2px 7px; font-size: 10px; }
</style>
