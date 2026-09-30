import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    fs: {
      // The Evals page imports eval results from ../backend/evals at build
      // time; let the dev server read them too.
      allow: [".."],
    },
  },
});
