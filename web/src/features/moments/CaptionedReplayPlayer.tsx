import { useEffect, useRef, useState } from 'react'
import { ReplayPlayer, type ReplayPlayerProps } from '@/features/replay/ReplayPlayer'

const CAPTIONS_PREFERENCE_KEY = 'meetingminer.replay.captions'

interface CaptionsTrack {
  src: string
  label?: string
  language?: string
}

interface CaptionedReplayPlayerProps extends ReplayPlayerProps {
  captions?: CaptionsTrack
}

function rememberedCaptions(): boolean {
  try {
    return globalThis.localStorage?.getItem(CAPTIONS_PREFERENCE_KEY) === 'showing'
  } catch {
    return false
  }
}

/** Story 10.5's captions seam around the unchanged shared replay player.
 * Keeping attachment local avoids colliding with Story 7.4, which owns the
 * same shared player in this wave, while preserving its seek behavior. */
export function CaptionedReplayPlayer({
  captions,
  ...playerProps
}: CaptionedReplayPlayerProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const [captionOverride, setCaptionOverride] = useState<boolean | null>(null)
  const captionsVisible = captions === undefined ? false : (captionOverride ?? rememberedCaptions())

  useEffect(() => {
    if (captions === undefined) return
    const video = hostRef.current?.querySelector('video')
    if (video === null || video === undefined) return
    const track = document.createElement('track')
    track.dataset.testid = 'replay-captions-track'
    track.kind = 'captions'
    track.src = captions.src
    track.srclang = captions.language ?? 'en'
    track.label = captions.label ?? 'Meeting transcript'
    video.append(track)
    const syncMode = () => {
      if (track.track !== undefined) {
        track.track.mode = captionsVisible ? 'showing' : 'disabled'
      }
    }
    syncMode()
    video.addEventListener('loadedmetadata', syncMode)
    return () => {
      video.removeEventListener('loadedmetadata', syncMode)
      track.remove()
    }
  }, [captions, captionsVisible])

  const toggleCaptions = () => {
    const next = !captionsVisible
    setCaptionOverride(next)
    try {
      globalThis.localStorage?.setItem(
        CAPTIONS_PREFERENCE_KEY,
        next ? 'showing' : 'disabled',
      )
    } catch {
      // Storage may be denied; the choice still applies to this mounted player.
    }
  }

  return (
    <div ref={hostRef} className="contents">
      <ReplayPlayer {...playerProps} />
      {captions !== undefined && (
        <button
          type="button"
          aria-pressed={captionsVisible}
          onClick={toggleCaptions}
          className="min-h-6 self-end rounded-md border px-2 py-1 text-xs"
          style={{ borderColor: 'var(--control-border)' }}
        >
          {captionsVisible ? 'Hide captions' : 'Show captions'}
        </button>
      )}
    </div>
  )
}
