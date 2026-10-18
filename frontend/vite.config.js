import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, proxy API + websockets to the FastAPI backend on :8080.
const target = process.env.VITE_BACKEND_URL || "http://localhost:8080";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/api": target,
      "/healthz": target,
      "/ws": { target: target.replace("http", "ws"), ws: true },
    },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
});
