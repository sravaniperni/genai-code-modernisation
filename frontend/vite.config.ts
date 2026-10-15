import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// The UI only ever calls relative /api URLs; in development and preview Vite forwards them to the
// FastAPI backend. Override the target with VITE_API_PROXY_TARGET (e.g. http://127.0.0.1:8001).
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000';
const proxy = { '/api': { target: apiTarget, changeOrigin: false } };

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy },
  preview: { port: 4173, strictPort: true, proxy },
  build: { sourcemap: true },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    restoreMocks: true,
    unstubGlobals: true,
  },
});
