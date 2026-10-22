/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    host: "127.0.0.1",
    proxy: { "/api": "http://127.0.0.1:8080" },
  },
  // assetsInlineLimit 0: never inline fonts or images as data: URIs, so the server CSP
  // (font-src and img-src limited to the app origin) never has to allow them.
  build: { outDir: "dist", sourcemap: false, assetsInlineLimit: 0 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    // Pages are lazy-loaded; a test that moves between pages transforms each on first use.
    testTimeout: 15000,
  },
});
