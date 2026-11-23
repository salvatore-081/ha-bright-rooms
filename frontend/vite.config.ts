import { resolve } from "node:path";
import { defineConfig } from "vite";

// The sidebar panel: one self-contained file, loaded by Home Assistant.
export default defineConfig({
  build: {
    lib: {
      entry: resolve(import.meta.dirname, "src/main.ts"),
      name: "BrightRoomsPanel",
      formats: ["iife"],
      fileName: () => "bright-rooms-panel.js",
    },
    outDir: "../custom_components/bright_rooms/frontend",
    emptyOutDir: false,
    target: "es2022",
    reportCompressedSize: false,
  },
});
