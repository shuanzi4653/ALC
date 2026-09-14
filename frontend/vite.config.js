import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const configDir = path.dirname(fileURLToPath(import.meta.url))

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
    outDir: process.env.TIANCHUANG_FRONTEND_OUT
      ? path.resolve(configDir, process.env.TIANCHUANG_FRONTEND_OUT)
      : 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1600
  }
})
