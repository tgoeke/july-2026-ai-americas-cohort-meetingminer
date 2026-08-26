import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config.ts'

// Extends the app's own vite config rather than restating it, so the `@` alias
// and the React plugin can never drift between what the tests run and what
// `vite build` ships.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
    },
  }),
)
