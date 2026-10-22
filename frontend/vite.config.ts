import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: { emptyOutDir: true },
  server: {
    allowedHosts: ["terminal.local"],
    // All data comes from the PerkFlex API (npm run api).
    proxy: { "/api": process.env.API_PROXY ?? "http://127.0.0.1:3001" },
  },
});
