import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

// Served by nginx at /console/ next to the Flutter admin (V2_DELTA D1). In development the
// API paths are proxied to a local backend, so the app stays same-origin as in production.
const backend = process.env.OC_BACKEND ?? 'http://127.0.0.1:8000'
const apiPaths = ['/auth', '/admin', '/outbound', '/items', '/stocks', '/shopee', '/pick-items', '/meta', '/.well-known']

export default defineConfig({
  base: '/console/',
  plugins: [vue()],
  server: {
    proxy: {
      ...Object.fromEntries(apiPaths.map((p) => [p, { target: backend, changeOrigin: false }])),
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
    },
  },
  test: {
    environment: 'jsdom',
  },
})
