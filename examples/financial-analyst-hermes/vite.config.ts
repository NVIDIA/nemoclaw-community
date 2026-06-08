import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  root: "ui",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/v1": "http://127.0.0.1:18080",
      "/api": "http://127.0.0.1:18080",
      "/config": "http://127.0.0.1:18080",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["../vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
