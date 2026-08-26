import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// `import.meta.dirname` rather than `__dirname`: vitest.config.ts imports this
// file, and Vite's native (ESM) config loader has no CommonJS `__dirname` to
// give it — the alias would resolve to nothing under the test runner. This
// raises the floor to Node 20.11+, declared in package.json `engines`.
// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
})
