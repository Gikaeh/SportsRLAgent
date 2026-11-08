import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the Python read API (`deepsports serve`).
// `npm run build` writes to web/dist, which the Python server serves at `/`.
export default defineConfig({
  plugins: [react()],
  base: "/",
  server: {
    host: true,
    proxy: {
      "/api": { target: "http://localhost:8787", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
