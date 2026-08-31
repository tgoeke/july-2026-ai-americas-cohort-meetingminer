import { describe, expect, it } from 'vitest'
import {
  BEYOND_PALETTE,
  bandFillStyle,
  paintFor,
  swatchStyle,
  THREAD_HUES,
  THREAD_HUES_LAP2,
} from './palette'

describe('thread colour from the immutable colorOrdinal', () => {
  it('gives ordinals 1–8 the eight lap-1 hues, in order', () => {
    for (let ordinal = 1; ordinal <= 8; ordinal += 1) {
      const paint = paintFor(ordinal)
      expect(paint.lap).toBe(1)
      expect(paint.band).toBe(THREAD_HUES[ordinal - 1])
      expect(paint.hatched).toBe(false)
    }
  })

  it('gives ordinals 9–16 the same hue at lap 2, hatched', () => {
    const nine = paintFor(9)
    expect(nine.lap).toBe(2)
    expect(nine.band).toBe(THREAD_HUES_LAP2[0])
    expect(nine.hatched).toBe(true)
    // The name stays in the lap-1 hue — the swatch, not the text, carries the lap.
    expect(nine.name).toBe(THREAD_HUES[0])
    expect(paintFor(16).band).toBe(THREAD_HUES_LAP2[7])
  })

  it('drops past 16 to grey, where the name alone identifies the thread', () => {
    const beyond = paintFor(17)
    expect(beyond.lap).toBe(3)
    expect(beyond.band).toBe(BEYOND_PALETTE)
    expect(beyond.name).toBe(BEYOND_PALETTE)
    expect(beyond.hatched).toBe(false)
  })

  it('depends on the ordinal alone, never on where the thread sits in a list', () => {
    // The same ordinal in any position is the same colour; two threads sorted
    // either way keep theirs. This is the whole point of the api owning it.
    expect(paintFor(3)).toEqual(paintFor(3))
    expect(paintFor(3)).not.toEqual(paintFor(4))
    // 8 apart is the same hue, a different lap — adjacency never recolours.
    expect(paintFor(3).name).toBe(paintFor(11).name)
    expect(paintFor(3).band).not.toBe(paintFor(11).band)
  })

  it('treats an ordinal the api never assigns as beyond the palette, not a crash', () => {
    for (const bad of [0, -1, Number.NaN]) {
      expect(paintFor(bad).band).toBe(BEYOND_PALETTE)
    }
  })
})

describe('how the paint is drawn', () => {
  it('hatches the lap-2 swatch and fills the lap-1 one', () => {
    expect(swatchStyle(paintFor(1)).background).toBe(THREAD_HUES[0])
    expect(swatchStyle(paintFor(9)).backgroundImage).toContain('repeating-linear-gradient(135deg')
  })

  it('rides density alpha on the band, and never on a beyond-palette one', () => {
    expect(bandFillStyle(paintFor(1), 0.6).opacity).toBe('0.6')
    expect(bandFillStyle(paintFor(9), 0.88).opacity).toBe('0.88')
    // Beyond the palette the band is grey at 60% whatever the density: the
    // name carries identity there, and a dimmable grey would say less, not more.
    expect(bandFillStyle(paintFor(17), 1).opacity).toBe('0.6')
    expect(bandFillStyle(paintFor(17), 0.08).opacity).toBe('0.6')
    expect(bandFillStyle(paintFor(17), 1).background).toBe(BEYOND_PALETTE)
  })
})
