import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5180,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8085', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8085', ws: true }
    }
  },
  build: {
    chunkSizeWarningLimit: 1600
  }
})
