<script setup>
import { ref } from 'vue'
import { login, store, initRealtime } from '../api.js'

const username = ref('')
const password = ref('')
const busy = ref(false)
async function submit() {
  if (busy.value || !username.value || !password.value) return
  busy.value = true
  await login(username.value, password.value)
  password.value = ''
  busy.value = false
}
</script>

<template>
  <div v-if="store.auth.enabled && !store.auth.authenticated" class="login-mask">
    <form class="login-card" @submit.prevent="submit">
      <h2>天窗智巡</h2>
      <p>{{store.auth.statusUnavailable?'服务暂不可达，正在自动重连':'登录后查看气象与作业态势'}}</p>
      <input v-if="!store.auth.statusUnavailable" v-model.trim="username" autocomplete="username" placeholder="用户名" />
      <input v-if="!store.auth.statusUnavailable" v-model="password" type="password" autocomplete="current-password" placeholder="密码" />
      <div v-if="store.auth.error" class="error">{{ store.auth.error }}</div>
      <button v-if="store.auth.statusUnavailable" type="button" :disabled="store.auth.loading" @click="initRealtime">重新检查连接</button>
      <button v-else type="submit" :disabled="busy">{{ busy ? '登录中…' : '登录' }}</button>
    </form>
  </div>
</template>

<style scoped>
.login-mask { position: fixed; inset: 0; z-index: 9999; display: grid; place-items: center;
  background: radial-gradient(circle at 50% 30%, #173253, #06101f 70%); }
.login-card { width: 340px; padding: 30px; display: grid; gap: 13px; color: #dcecff;
  background: rgba(10,29,52,.96); border: 1px solid #315b83; border-radius: 8px; box-shadow: 0 18px 50px #0009; }
.login-card h2 { margin: 0; letter-spacing: 4px; }
.login-card p { margin: 0 0 8px; color: #7398bd; }
.login-card input { padding: 11px 12px; color: #e7f3ff; background: #07182b; border: 1px solid #294b6d; border-radius: 4px; }
.login-card button { padding: 10px; color: white; background: #1976bd; border: 0; border-radius: 4px; cursor: pointer; }
.login-card button:disabled { opacity: .6; }
.error { color: #ff8d82; font-size: 12px; }
</style>
