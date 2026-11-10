import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the BetDesk Worker running locally (`npm run dev -w worker`, port 8788).
// `npm run build` writes to web/dist, which the Worker serves as static assets.
export default defineConfig({
  plugins: [react()],
  base: "/",
  server: {
    host: true,
    proxy: {
      "/api": { target: "http://localhost:8788", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
