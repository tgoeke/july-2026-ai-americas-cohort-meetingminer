import { defineConfig } from '@hey-api/openapi-ts'

// Regenerates the typed TS client from the live api process (`make client`).
// The api must be running on :8000.
export default defineConfig({
  input: 'http://localhost:8000/openapi.json',
  output: 'src/client',
})
