import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // All /api/v1/* requests are forwarded to the backend.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // WebSocket connections to /ws/* are forwarded with ws upgrade.
      '/api/v1/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
