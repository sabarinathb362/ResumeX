import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// RESUMEX_API lets a second dev server point at a backend on another port (default: 8000).
const api = process.env.RESUMEX_API || 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: api,
        changeOrigin: true,
      },
      '/health': {
        target: api,
        changeOrigin: true,
      },
    },
  },
});
