import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      // In development, forward API + WebSocket traffic to the backend.
      "/ws": { target: "http://localhost:8000", ws: true },
      "/health": "http://localhost:8000",
      "/alarms": "http://localhost:8000",
      "/sites": "http://localhost:8000",
      "/sensors": "http://localhost:8000",
      "/snapshot": "http://localhost:8000",
      "/metrics": "http://localhost:8000",
    },
  },
});