import { buttonVariants } from '@/components/ui/button'
import { type SourceLink, sourceLinkLabel } from '@/lib/affordance'

export interface SourceLinkAnchorProps {
  /** The classified source link — already timed when it is YouTube's. */
  link: SourceLink
  /** The `data-testid` the surface addresses this anchor by. */
  testId: string
}

/**
 * The one rendering of a source deep link (story 6.6, UX-DR12).
 *
 * Four surfaces render the same anchor, so the rule lives here for the same
 * reason the decision lives in `affordanceOf`: one place to change. A
 * YouTube link takes the outline-button look — secondary to the default-
 * variant Replay button it sits beside — and a hidden `↗` glyph; any other
 * host keeps the plain underlined text it had before. Always a new tab, and
 * `rel="noreferrer"` because the source system is another origin.
 */
export function SourceLinkAnchor({ link, testId }: SourceLinkAnchorProps) {
  const youtube = link.provider === 'youtube'
  return (
    <a
      data-testid={testId}
      href={link.href}
      target="_blank"
      rel="noreferrer"
      className={
        youtube ? buttonVariants({ variant: 'outline', size: 'sm' }) : 'text-sm underline'
      }
    >
      {sourceLinkLabel(link)}
      {youtube && <span aria-hidden="true">↗</span>}
    </a>
  )
}
