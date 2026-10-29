import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import { bootstrapCaseMode } from './traffic/demoEntry.js'

bootstrapCaseMode()

createApp(App).mount('#app')
