import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import './theme-light.css'
import { bootstrapCaseMode } from './traffic/demoEntry.js'
import { initTheme } from './theme.js'

// 先落主题再挂载：晚一步就会先闪一帧深色再变浅色
initTheme()
bootstrapCaseMode()

createApp(App).mount('#app')
