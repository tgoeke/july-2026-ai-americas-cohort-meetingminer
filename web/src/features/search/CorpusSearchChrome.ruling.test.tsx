import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import type { SearchResponse } from '@/client/types.gen'
import { CorpusSearch } from './CorpusSearch'

const sdk = vi.hoisted(() => ({ searchCorpus: vi.fn() }))

vi.mock('@/client/sdk.gen', () => ({
  searchCorpus: sdk.searchCorpus,
}))

it('keeps the keyword-only ranking notice visible in expanded chrome search', async () => {
  const response: SearchResponse = {
    query: 'purchase order',
    ranking: 'keyword',
    hits: [],
    estimatedTotal: 0,
    limit: 20,
    offset: 0,
    indexMissing: false,
  }
  sdk.searchCorpus.mockResolvedValue({ data: response, error: undefined })

  render(<CorpusSearch presentation="chrome" expanded />)
  await userEvent.type(screen.getByTestId('search-input'), 'purchase order')

  expect(await screen.findByTestId('ranking-degraded')).toBeVisible()
})
