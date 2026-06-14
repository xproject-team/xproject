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
  preview: {
    // Production deploy on Railway serves on vera-event.com. Vite's
    // preview server blocks unknown hosts by default, so allowlist
    // the prod domain (+ wildcard for any Railway-generated subdomain
    // that might also point at this service).
    allowedHosts: ['vera-event.com', 'www.vera-event.com', '.up.railway.app'],
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
