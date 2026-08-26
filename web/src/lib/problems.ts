/**
 * Reading an RFC 9457 problem body, wherever the api refused something.
 *
 * Every error body the api emits is `application/problem+json`
 * (`server/meetingminer/api/problems.py`), so any feature that shows a
 * refusal reads the same two members: `type` to decide which refusal it was,
 * `title`/`detail` to say it in the api's own words. Split out of
 * `features/search/hits.ts` (story 2.2) because the moment views classify
 * problems too, and features must not deep-import a sibling feature.
 */

/** The problem's `type` URI (`urn:meetingminer:problem:<slug>`), or `null`. */
export function problemType(error: unknown): string | null {
  if (error === null || typeof error !== 'object') return null
  const type = (error as { type?: unknown }).type
  return typeof type === 'string' ? type : null
}

/** The human sentence inside an RFC 9457 body, or `null` if it is not one. */
export function problemMessage(error: unknown): string | null {
  if (error === null || typeof error !== 'object') return null
  const body = error as { title?: unknown; detail?: unknown }
  const detail = typeof body.detail === 'string' ? body.detail.trim() : ''
  const title = typeof body.title === 'string' ? body.title.trim() : ''
  if (detail && title) return `${title}: ${detail}`
  return detail || title || null
}
