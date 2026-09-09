<script setup>
import { computed, onMounted, ref, onUnmounted } from 'vue'
import { store } from '../api.js'

const now = ref(new Date())
let timer = null
onMounted(() => { timer = setInterval(() => { now.value = new Date() }, 1000) })
onUnmounted(() => clearInterval(timer))

const clock = computed(() => {
  const d = now.value
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
})

/* ---------- 结束系统 ---------- */
const confirmOpen = ref(false)
const agreed = ref(false)
const shuttingDown = ref(false)
const shutdownDone = ref(false)
const shutdownErr = ref('')

function openConfirm() {
  agreed.value = false
  shutdownErr.value = ''
  confirmOpen.value = true
}

async function doShutdown() {
  shuttingDown.value = true
  shutdownErr.value = ''
  try {
    const r = await fetch((import.meta.env.DEV ? 'http://127.0.0.1:8085' : '') + '/api/system/shutdown', { method: 'POST' })
    if (!r.ok) throw new Error('HTTP ' + r.status)
    // 后端会先关闭 Python 服务再延迟退出自身；前端立即展示已停止覆盖层
    shutdownDone.value = true
    confirmOpen.value = false
    if (timer) { clearInterval(timer); timer = null }
  } catch (e) {
    shutdownErr.value = '结束指令发送失败（' + e.message + '），可改用工程根目录 stop.bat'
  } finally {
    shuttingDown.value = false
  }
}
</script>

<template>
  <div class="panel top">
    <div>
      <div class="title">天窗智巡</div>
      <div class="sub">低空飞行气象保障系统 · 无人机飞行窗口预测与智能预警</div>
    </div>
    <div class="spacer"></div>
    <div class="status-item">
      <span class="status-dot" :style="{ background: store.wsConnected ? '#2ecc71' : '#c0392b' }"></span>
      数据链路 {{ store.wsConnected ? '正常' : '中断' }}
    </div>
    <div class="status-item">
      <span class="status-dot" :style="{ background: store.configStatus.qweatherReady ? '#2ecc71' : '#d98a2b' }"></span>
      和风服务 {{ store.configStatus.qweatherReady ? '已接入' : '未配置' }}
    </div>
    <div class="status-item">
      <span class="status-dot" style="background:#3d8bff"></span>
      模式：{{ store.dash.mode === 'live' ? '实时' : '模拟' }}
    </div>
    <div class="status-item">作业区：{{ store.dash.region }}</div>
    <div class="clock">{{ clock }}</div>
    <button class="btn danger btn-shutdown" @click="openConfirm">结束系统</button>

    <!-- 确认弹层 -->
    <div class="mask" v-if="confirmOpen" @click.self="confirmOpen = false">
      <div class="confirm-box">
        <div class="cb-title">确认结束系统运行？</div>
        <div class="cb-body">
          将执行以下操作：<br />
          1. 停止 Python 推演服务（端口 8600）<br />
          2. 停止 Java 后端服务（端口 8085）<br />
          3. 释放全部占用的端口<br />
          <span class="cb-note">执行后大屏将无法访问，需重新运行 start.bat 启动。</span>
        </div>
        <label class="cb-agree">
          <input type="checkbox" v-model="agreed" />
          我已知晓该操作将停止全部服务并释放端口
        </label>
        <div class="cb-actions">
          <button class="btn" @click="confirmOpen = false">取消</button>
          <button class="btn danger" :disabled="!agreed || shuttingDown" @click="doShutdown">
            {{ shuttingDown ? '正在结束…' : '确认结束' }}
          </button>
        </div>
        <div class="cb-err" v-if="shutdownErr">{{ shutdownErr }}</div>
      </div>
    </div>

    <!-- 已停止覆盖层 -->
    <div class="mask stopped" v-if="shutdownDone">
      <div class="stopped-box">
        <div class="sp-icon">■</div>
        <div class="sp-title">系统已停止</div>
        <div class="sp-desc">全部服务已退出，端口 8085 / 8600 已释放</div>
        <div class="sp-tip">如需重新启动，请双击工程根目录 start.bat</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.btn-shutdown { flex: none; margin-left: 4px; }

.mask { position: absolute; inset: 0; z-index: 200;
  background: rgba(2, 8, 18, 0.78); backdrop-filter: blur(2px);
  display: flex; align-items: center; justify-content: center; }
.mask.stopped { background: rgba(2, 8, 18, 0.96); }

.confirm-box { width: 460px; background: rgba(12, 28, 54, 0.98);
  border: 1px solid rgba(192, 57, 43, 0.65); border-radius: 10px; padding: 20px 24px;
  box-shadow: 0 8px 40px rgba(0,0,0,.6); }
.cb-title { font-size: 17px; font-weight: 700; color: #ffd9d3; margin-bottom: 12px; }
.cb-body { font-size: 13px; color: #cfe3ff; line-height: 1.9; margin-bottom: 12px; }
.cb-note { color: #d98a2b; }
.cb-agree { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: #a9c8ea;
  cursor: pointer; margin-bottom: 16px; }
.cb-agree input { width: 15px; height: 15px; accent-color: #3d8bff; cursor: pointer; }
.cb-actions { display: flex; gap: 10px; justify-content: flex-end; }
.cb-actions .danger { background: rgba(192, 57, 43, 0.4); color: #fff; }
.cb-actions .danger:not(:disabled):hover { background: rgba(192, 57, 43, 0.7); }
.cb-err { margin-top: 10px; font-size: 12px; color: #ff9a8a; }

.stopped-box { text-align: center; padding: 40px 60px; }
.sp-icon { font-size: 34px; color: #c0392b; margin-bottom: 14px; }
.sp-title { font-size: 24px; font-weight: 700; color: #e8f4ff; letter-spacing: 4px; margin-bottom: 10px; }
.sp-desc { font-size: 13px; color: #8fb4de; margin-bottom: 6px; }
.sp-tip { font-size: 12px; color: #51719e; }
</style>
