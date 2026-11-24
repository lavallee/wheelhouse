import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// One file out: ui -> ../web/index.html, served by the admin backend.
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss(), viteSingleFile()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  build: { outDir: "../web", emptyOutDir: true },
  // `npm run dev` proxies the API to a locally running backend.
  server: { proxy: { "/api": process.env.ADMIN_API || "http://127.0.0.1:8870" } },
});
