import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SourceLinkAnchor } from './SourceLinkAnchor'

describe('SourceLinkAnchor', () => {
  it('renders a timed YouTube link as an outline anchor named with its offset', () => {
    render(
      <SourceLinkAnchor
        testId="the-link"
        link={{
          provider: 'youtube',
          href: 'https://www.youtube.com/watch?v=abc&t=754',
          offsetMs: 754_000,
        }}
      />,
    )

    const link = screen.getByTestId('the-link')
    // The accessible name carries the offset and excludes the hidden glyph.
    expect(link).toBe(screen.getByRole('link', { name: 'Open on YouTube at 12:34' }))
    expect(link).toHaveAttribute('href', 'https://www.youtube.com/watch?v=abc&t=754')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
    const glyph = link.querySelector('span')
    expect(glyph).toHaveTextContent('↗')
    expect(glyph).toHaveAttribute('aria-hidden', 'true')
    expect(link.className).toContain('border-border')
  })

  it('names an untimed YouTube link without an offset', () => {
    render(
      <SourceLinkAnchor
        testId="the-link"
        link={{ provider: 'youtube', href: 'https://www.youtube.com/shorts/abc', offsetMs: null }}
      />,
    )
    expect(screen.getByRole('link', { name: 'Open on YouTube' })).toHaveAttribute(
      'href',
      'https://www.youtube.com/shorts/abc',
    )
  })

  it('renders another host as the plain underlined Stream link, no glyph', () => {
    render(
      <SourceLinkAnchor
        testId="the-link"
        link={{ provider: 'other', href: 'https://example.sharepoint.com/stream.aspx?id=x' }}
      />,
    )

    const link = screen.getByTestId('the-link')
    expect(link).toBe(screen.getByRole('link', { name: 'Open in Stream' }))
    expect(link).toHaveAttribute('href', 'https://example.sharepoint.com/stream.aspx?id=x')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
    expect(link.querySelector('span')).toBeNull()
    expect(link.className).toBe('text-sm underline')
  })
})
