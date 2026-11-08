import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const backend = process.env.ATO_BACKEND_URL || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: true,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
  build: {
    rollupOptions: {
      output: { manualChunks: { react: ["react", "react-dom", "react-router-dom"], charts: ["lightweight-charts"] } },
    },
  },
  test: { environment: "jsdom", globals: true },
});
