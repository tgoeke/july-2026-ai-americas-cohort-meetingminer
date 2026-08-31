/**
 * Thread identity colour, derived from the api's immutable `colorOrdinal`.
 *
 * `DESIGN.md` · Threads: eight hues 45° apart at L 0.75 C 0.12; ordinals 9–16
 * take the same hue at lap 2 (L 0.58 C 0.08, hatched 135° 3px/7px); past 16 the
 * band is `muted-foreground` at 60% and the *name* carries identity.
 *
 * The api owns identity, the client owns only this mapping — so sorting,
 * filtering, importing older meetings and reruns never recolour a thread.
 * Nothing here may consult list position.
 *
 * The values are literals rather than CSS variables on purpose: story 10.5 owns
 * `web/src/index.css` and the Ember & Ink theme it will carry, so this screen
 * cannot depend on a token that does not exist yet. Every *other* colour on the
 * screen uses the semantic Tailwind tokens, which follow the theme when it
 * lands.
 */

/** Lap-1 hues, ordinal 1–8, in `DESIGN.md` frontmatter order. */
export const THREAD_HUES: ReadonlyArray<string> = [
  '#EC8DAB',
  '#ED946C',
  '#CBAA4B',
  '#8CBF70',
  '#3DC6B1',
  '#45BDE7',
  '#90AAFA',
  '#CB96E2',
]

/** Lap-2 hues, ordinal 9–16 — the same hue darker, drawn hatched. */
export const THREAD_HUES_LAP2: ReadonlyArray<string> = [
  '#A26678',
  '#A26B52',
  '#8D783F',
  '#668554',
  '#3C8A7C',
  '#3F849E',
  '#6878AA',
  '#8C6C9B',
]

/** `{colors.muted-foreground}` — the beyond-palette band and swatch. */
export const BEYOND_PALETTE = '#A7A09A'

/** The one lap-2 hatch, stated once so band and swatch cannot drift. */
export function hatch(color: string): string {
  return `repeating-linear-gradient(135deg, ${color} 0 3px, transparent 3px 7px)`
}

/**
 * A thread's drawn identity.
 *
 * `lap` is 1, 2, or 3+ ("beyond"). `name` is the colour the thread's *name* is
 * always set in — for lap 2 that is still the lap-1 hue, because the swatch,
 * not the text, carries the lap (`DESIGN.md` · Threads).
 */
export interface ThreadPaint {
  /** 1-based lap: 1 = solid, 2 = hatched, 3 = beyond the palette. */
  lap: 1 | 2 | 3
  /** The band's fill colour. */
  band: string
  /** The colour the thread name is set in, in the list and on the canvas. */
  name: string
  /** `true` when the band and swatch are drawn hatched rather than solid. */
  hatched: boolean
}

/**
 * Paint for a `colorOrdinal`.
 *
 * `(colorOrdinal − 1) mod 8` selects the hue and `floor((colorOrdinal − 1) / 8)`
 * selects the lap, exactly as `DESIGN.md` states. An ordinal below 1 — which the
 * api never assigns — is treated as beyond the palette rather than throwing:
 * a thread whose colour cannot be derived must still be identifiable by name.
 */
export function paintFor(colorOrdinal: number): ThreadPaint {
  if (!Number.isFinite(colorOrdinal) || colorOrdinal < 1) {
    return { lap: 3, band: BEYOND_PALETTE, name: BEYOND_PALETTE, hatched: false }
  }
  const zero = Math.floor(colorOrdinal) - 1
  const hue = zero % THREAD_HUES.length
  const lap = Math.floor(zero / THREAD_HUES.length)
  if (lap === 0) {
    return { lap: 1, band: THREAD_HUES[hue], name: THREAD_HUES[hue], hatched: false }
  }
  if (lap === 1) {
    return { lap: 2, band: THREAD_HUES_LAP2[hue], name: THREAD_HUES[hue], hatched: true }
  }
  return { lap: 3, band: BEYOND_PALETTE, name: BEYOND_PALETTE, hatched: false }
}

/** The 12×12 swatch beside a thread name: solid, hatched, or grey. */
export function swatchStyle(paint: ThreadPaint): Record<string, string> {
  if (paint.hatched) {
    return { backgroundImage: hatch(paint.band), border: `1px solid ${paint.band}` }
  }
  return { background: paint.band, border: `1px solid ${paint.band}` }
}

/**
 * The band's fill at a density step.
 *
 * Lap 1 is a flat fill at the step's alpha; lap 2 is the hatch, whose texture
 * already reads as "not lap 1", so alpha rides on top of it; beyond the palette
 * the band is grey at 60% with no hatch and no density (`DESIGN.md` · Threads —
 * "the name alone identifies it").
 */
export function bandFillStyle(paint: ThreadPaint, alpha: number): Record<string, string> {
  if (paint.lap === 3) return { background: BEYOND_PALETTE, opacity: '0.6' }
  if (paint.hatched) return { backgroundImage: hatch(paint.band), opacity: String(alpha) }
  return { background: paint.band, opacity: String(alpha) }
}

/** The sentence the list shows under a thread the palette cannot colour. */
export const BEYOND_PALETTE_NOTE = 'beyond the palette (8 hues × 2 laps) — identified by name'
