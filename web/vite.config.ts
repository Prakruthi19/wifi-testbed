import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Live mode: the browser calls /api/..., and Vite forwards it to the Python API (testbed/api.py).
// Demo mode (VITE_DEMO=1): the app reads frozen JSON from public/demo/ and needs no server.
// GitHub Pages serves the repo under /wifi-testbed/, so the demo build sets that as the base path.
export default defineConfig({
  plugins: [vue()],
  base: process.env.VITE_BASE ?? '/',
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
