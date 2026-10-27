import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The admin calls the API on the same origin in production (behind Caddy) and
// through this proxy in development, so no CORS configuration is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": {
        target: process.env.CARDTRACKER_API_URL ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
