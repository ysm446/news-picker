import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // Electron が file:// で dist を読むため、アセットは相対パスで参照する
  base: "./",
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
  },
});
