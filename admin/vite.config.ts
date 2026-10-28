import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The admin calls the API on the same origin in production (behind Caddy) and
// through this proxy in development, so no CORS configuration is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    headers: {
      "Content-Security-Policy":
        "default-src 'self'; connect-src 'self' ws://127.0.0.1:5173 http://127.0.0.1:8000; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
    },
    proxy: {
      "/v1": {
        target: process.env.CARDTRACKER_API_URL ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  preview: {
    headers: {
      "Content-Security-Policy":
        "default-src 'self'; connect-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
    },
  },
  build: {
    outDir: "dist",
    // Production bundles are served publicly. Do not ship source maps; if
    // crash reporting needs them, upload them privately in CI (hidden mode)
    // instead of placing `.map` files next to the bundle.
    sourcemap: false,
  },
});
