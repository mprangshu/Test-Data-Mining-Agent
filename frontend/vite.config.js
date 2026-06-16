import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server on 5173 (the backend's CORS allow-list includes this origin).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
