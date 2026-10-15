import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built files go into the Python package so `python -m kosh serve` serves them.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../backend/kosh/web_dist", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
