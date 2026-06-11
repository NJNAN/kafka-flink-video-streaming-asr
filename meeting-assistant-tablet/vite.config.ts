import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import basicSsl from "@vitejs/plugin-basic-ssl";

export default defineConfig(({ mode }) => ({
  base: "./",
  plugins: mode === "https" ? [react(), basicSsl()] : [react()],
  server: {
    port: 5180,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      },
      "/live": {
        target: "http://127.0.0.1:8010",
        changeOrigin: true
      }
    }
  }
}));
