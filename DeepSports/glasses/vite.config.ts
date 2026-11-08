import { defineConfig } from 'vite'

// Served by the Python API at /glasses/ (same origin as /api, so no CORS or whitelist hop).
// In dev, /api is proxied to `deepsports serve` on :8787.
export default defineConfig({
  base: '/glasses/',
  server: {
    host: true,
    port: 5173,
    proxy: { '/api': { target: 'http://localhost:8787', changeOrigin: true } },
  },
  build: { target: 'es2022', outDir: 'dist', emptyOutDir: true },
})
