import path from 'node:path';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    // The API is served by the Python backend; proxying keeps the client on
    // same-origin relative URLs in dev and in the built bundle alike.
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8470',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
});
