<script setup>
import { nextTick, ref } from 'vue'
import { store, postAction } from '../api.js'

const input = ref('')
const sending = ref(false)
const listEl = ref(null)

async function send() {
  const q = (input.value || '').trim()
  if (!q || sending.value) return
  store.chatList.push({ role: 'user', text: q })
  input.value = ''
  sending.value = true
  scrollBottom()
  try {
    const r = await postAction('/api/agent/ask', { question: q })
    store.chatList.push({ role: 'agent', text: r.answer || '(空回复)', source: r.source })
  } catch (e) {
    store.chatList.push({ role: 'agent', text: '智能体服务暂时不可用，请稍后重试。', source: 'error' })
  } finally {
    sending.value = false
    scrollBottom()
  }
}

async function scrollBottom() {
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}

const SRC_LABEL = { deepseek: 'DeepSeek', rule: '规则降级', ask: '知识问答', error: '异常' }
</script>

<template>
  <div class="ag-wrap">
    <div ref="listEl" class="ag-list">
      <div v-if="!store.chatList.length" class="ag-hint">
        向智能体提问，例如：当前适合执行巡检任务吗？需要注意什么？
      </div>
      <div v-for="(m, i) in store.chatList" :key="i" class="ag-msg" :class="m.role">
        <div class="ag-bubble">{{ m.text }}</div>
        <div v-if="m.role === 'agent' && m.source" class="ag-src">{{ SRC_LABEL[m.source] || m.source }}</div>
      </div>
      <div v-if="sending" class="ag-msg agent"><div class="ag-bubble thinking">研判中…</div></div>
    </div>
    <div class="ag-input">
      <input v-model="input" type="text" placeholder="输入问题，回车发送"
             @keydown.enter="send" :disabled="sending" />
      <button class="btn" @click="send" :disabled="sending || !input.trim()">发送</button>
    </div>
  </div>
</template>

<style scoped>
.ag-wrap { display: flex; flex-direction: column; height: 100%; width: 100%; }
.ag-list { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 5px; padding: 2px 2px; }
.ag-hint { font-size: 11px; color: #51719e; line-height: 1.6; }
.ag-msg { display: flex; flex-direction: column; }
.ag-msg.user { align-items: flex-end; }
.ag-bubble { max-width: 92%; padding: 4px 9px; border-radius: 6px; font-size: 11px; line-height: 1.5; }
.ag-msg.user .ag-bubble { background: rgba(61,139,255,.3); color: #e6f1fb; border-bottom-right-radius: 2px; }
.ag-msg.agent .ag-bubble { background: rgba(20,40,70,.7); color: #a9c4e4; border-bottom-left-radius: 2px; }
.ag-bubble.thinking { color: #6f95c4; }
.ag-src { font-size: 9px; color: #51719e; margin-top: 2px; }
.ag-input { display: flex; gap: 6px; padding-top: 6px; border-top: 1px solid rgba(64,140,230,.25); flex: none; }
.ag-input input { flex: 1; background: rgba(10,25,48,.8); border: 1px solid rgba(64,140,230,.35); border-radius: 4px;
  color: #dce9f7; font-size: 11px; padding: 6px 8px; outline: none; }
.ag-input input:focus { border-color: #3fa7ff; box-shadow: 0 0 8px rgba(61,139,255,.3); }
</style>
