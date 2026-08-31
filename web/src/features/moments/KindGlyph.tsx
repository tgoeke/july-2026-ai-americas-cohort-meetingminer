import type { ArtifactKind } from './feed'

/**
 * The kind glyphs, as one 12×12 inline SVG sprite (`DESIGN.md` · Kind chip).
 *
 * They are not decoration. The seven kinds collapse into four hue families —
 * records (decision, adr), actions (action-item), backlog (story,
 * requirement), corrections (bug-fix, change-request) — so inside a family the
 * glyph is the *only* carrier, and between families it is the second carrier
 * for a reader who cannot tell the hues apart. A chip without its glyph is a
 * defect.
 *
 * Drawn rather than set as font characters: Geist lacks the shapes, a fallback
 * face would size them unevenly, and a checkbox outline versus a bookmark
 * separates action-item from story better than ☐ versus ▣ ever does.
 */

const STROKE = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.5 } as const

function paths(kind: ArtifactKind) {
  switch (kind) {
    case 'decision':
      // Filled diamond — a call that has been made.
      return <path d="M6 1 11 6 6 11 1 6Z" fill="currentColor" />
    case 'adr':
      // Outlined diamond ruled with a line: the decision, written down.
      return (
        <>
          <path d="M6 1 11 6 6 11 1 6Z" {...STROKE} strokeLinejoin="round" />
          <path d="M3.6 6h4.8" {...STROKE} strokeLinecap="round" />
        </>
      )
    case 'action-item':
      // Checkbox outline — the thing still to do.
      return (
        <>
          <rect x="1.4" y="1.4" width="9.2" height="9.2" rx="1.6" {...STROKE} />
          <path d="M3.6 6.2 5.3 8 8.5 4.3" {...STROKE} strokeLinecap="round" strokeLinejoin="round" />
        </>
      )
    case 'story':
      // Bookmark — a slice of work, held open.
      return (
        <path
          d="M3 1.4h6v9.2L6 8.3l-3 2.3Z"
          {...STROKE}
          strokeLinejoin="round"
        />
      )
    case 'requirement':
      // Triple bar — a stated must.
      return (
        <>
          <path d="M2 3.4h8" {...STROKE} strokeLinecap="round" />
          <path d="M2 6h8" {...STROKE} strokeLinecap="round" />
          <path d="M2 8.6h8" {...STROKE} strokeLinecap="round" />
        </>
      )
    case 'bug-fix':
      // Cross — something that was wrong.
      return (
        <>
          <path d="M2.6 2.6 9.4 9.4" {...STROKE} strokeLinecap="round" />
          <path d="M9.4 2.6 2.6 9.4" {...STROKE} strokeLinecap="round" />
        </>
      )
    case 'change-request':
      // Delta — a difference asked for.
      return <path d="M6 1.6 10.8 10.4H1.2Z" {...STROKE} strokeLinejoin="round" />
  }
}

export interface KindGlyphProps {
  kind: ArtifactKind
  className?: string
}

/** The glyph alone. `aria-hidden`: the chip's text carries the kind's name,
 * and a screen reader must not hear the shape twice. */
export function KindGlyph({ kind, className }: KindGlyphProps) {
  return (
    <svg
      viewBox="0 0 12 12"
      width="12"
      height="12"
      aria-hidden="true"
      focusable="false"
      data-testid={`kind-glyph-${kind}`}
      className={className}
    >
      {paths(kind)}
    </svg>
  )
}
