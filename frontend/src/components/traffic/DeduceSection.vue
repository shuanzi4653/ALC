<template>
  <section class="ds" :class="[tone, { open: isOpen }]" :data-seg="name">
    <button type="button" class="ds-head" :aria-expanded="isOpen" @click="toggle">
      <i class="ds-no">{{ no }}</i>
      <span class="ds-title">{{ title }}</span>
      <em v-if="tag" class="ds-tag">{{ tag }}</em>
      <span v-if="!isOpen && summary" class="ds-sum" :title="summary">{{ summary }}</span>
      <span class="ds-arrow" aria-hidden="true">
        <svg viewBox="0 0 10 6" width="9" height="6"><path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.4" /></svg>
      </span>
    </button>
    <div v-show="isOpen" class="ds-body"><slot /></div>
  </section>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'

const props = defineProps({
  name: { type: String, required: true },
  no: { type: [String, Number], default: '' },
  title: { type: String, required: true },
  tag: { type: String, default: '' },
  // 折叠态的一行关键值：折叠不等于"没了"，读者要能一眼看到这一段判成什么
  summary: { type: String, default: '' },
  tone: { type: String, default: 'quiet' },
  defaultOpen: { type: Boolean, default: false },
  // 父级的批量指令：force 是递增计数（同向连点也能触发），方向看 forceDir
  force: { type: Number, default: 0 },
  forceDir: { type: Number, default: 1 },
})

const KEY = 'alc.deduce.fold.v1'
const isOpen = ref(props.defaultOpen)

function readAll() {
  try { return JSON.parse(localStorage.getItem(KEY) || '{}') } catch (_) { return {} }
}
function persist(open) {
  try {
    const all = readAll()
    all[props.name] = open
    localStorage.setItem(KEY, JSON.stringify(all))
  } catch (_) { /* 存不了就只在本次会话生效 */ }
}
function toggle() {
  isOpen.value = !isOpen.value
  persist(isOpen.value)
}

onMounted(() => {
  const all = readAll()
  if (typeof all[props.name] === 'boolean') isOpen.value = all[props.name]
})
watch(() => props.force, (v) => {
  if (!v) return
  const open = props.forceDir === 1
  isOpen.value = open
  persist(open)
})
</script>

<style scoped>
.ds { border: 1px solid rgba(70, 110, 140, 0.28); border-radius: 7px; margin: 0 0 6px 0;
  background: rgba(10, 26, 38, 0.42); overflow: hidden;
  /* 父级是 flex 列，段必须按内容高度、由父级滚动。
     默认 flex:0 1 auto 会被压到几十像素，图与表被 overflow:hidden 裁掉（实测段高 58px、表在图外）。 */
  flex: 0 0 auto; }
.ds-head { width: 100%; display: flex; align-items: center; gap: 7px; padding: 6px 9px;
  background: transparent; border: 0; cursor: pointer; text-align: left; color: inherit; font: inherit; }
.ds-head:hover { background: rgba(30, 70, 100, 0.35); }
.ds-no { width: 17px; height: 17px; flex: 0 0 17px; border-radius: 50%; font-style: normal;
  font-size: 9.5px; display: inline-flex; align-items: center; justify-content: center;
  background: rgba(120, 170, 200, 0.22); color: #cfe6f5; }
.ds-title { font-size: 12px; font-weight: 600; color: #eaf8ff; flex: 0 0 auto; }
.ds-tag { font-style: normal; font-size: 8.5px; color: #7d9cb3; border: 1px solid rgba(120, 170, 200, 0.35);
  border-radius: 3px; padding: 0 4px; flex: 0 0 auto; }
.ds-sum { flex: 1 1 auto; min-width: 0; font-size: 10.5px; color: #9dbccf;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ds-arrow { margin-left: auto; flex: 0 0 auto; color: #7d9cb3; transition: transform 140ms ease;
  display: inline-flex; }
.ds.open .ds-arrow { transform: rotate(180deg); }
.ds-body { padding: 2px 10px 8px 10px; border-top: 1px solid rgba(70, 110, 140, 0.22); }
.ds.warn .ds-no { background: rgba(224, 162, 63, 0.3); color: #ffd98a; }
.ds.bad .ds-no { background: rgba(226, 86, 63, 0.3); color: #ffb1a3; }
.ds.ok .ds-no { background: rgba(79, 174, 134, 0.3); color: #9beec4; }
@media (prefers-reduced-motion: reduce) { .ds-arrow { transition: none; } }

html[data-theme="light"] .ds { background: #fff; border-color: #dbe6f1; }
html[data-theme="light"] .ds-head:hover { background: #f2f7fc; }
html[data-theme="light"] .ds-title { color: #12395c; }
html[data-theme="light"] .ds-sum { color: #5b7386; }
html[data-theme="light"] .ds-body { border-top-color: #e6eef6; }
</style>
