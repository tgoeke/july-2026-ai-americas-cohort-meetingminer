// Registers the jest-dom matchers (toBeDisabled, toHaveTextContent, …) on
// vitest's expect, and tears the DOM down between test files.
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
})
