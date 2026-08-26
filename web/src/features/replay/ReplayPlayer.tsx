import { useEffect, useRef } from 'react'
import { recordingUrl } from '@/lib/media'

export interface ReplayPlayerProps {
  /** The meeting whose recording plays. */
  meetingId: string
  /** Where playback opens, in milliseconds from the start of the recording. */
  startMs: number
  /** What assistive tech announces instead of the raw url. */
  label?: string
  className?: string
}

/**
 * The one video element every replay affordance mounts.
 *
 * It exists as a shared component rather than a `<video>` tag in each view
 * because "open the recording at this moment" is a single behaviour with a
 * single awkward edge — the seek can only happen once the browser knows the
 * duration — and re-deriving that per view is how one of them ends up opening
 * at zero.
 *
 * Seeking works because the api answers HTTP Range on
 * `/media/recordings/{meetingId}`; without that the element could only ever
 * play from the beginning.
 */
export function ReplayPlayer({ meetingId, startMs, label, className }: ReplayPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const src = recordingUrl(meetingId)

  useEffect(() => {
    const video = videoRef.current
    if (video === null) return
    // Clamped, because assigning a NaN, Infinity or negative `currentTime`
    // throws — and this runs inside an effect, so the throw takes the whole
    // view down rather than just mis-seeking. A caller that derived `startMs`
    // from an offset that turned out to be absent hands over NaN, and opening
    // at the top of the recording is the honest answer to "no known moment".
    const seconds = Number.isFinite(startMs) ? Math.max(0, startMs / 1000) : 0
    const seek = () => {
      video.currentTime = seconds
    }
    // Assigned twice on purpose, because the effect runs in two different
    // states and there is only one event to hang off.
    //
    // When metadata is already loaded — a re-seek on a player that is already
    // mounted, or a recording the browser has cached — `loadedmetadata` has
    // been and gone, and this assignment is the seek.
    //
    // When it is not, HTML defines an assignment to `currentTime` at
    // `HAVE_NOTHING` as setting the element's *default playback start
    // position* rather than seeking, so this one arms the open position and
    // the listener re-applies it the moment the duration is known and the
    // element can genuinely seek.
    seek()
    video.addEventListener('loadedmetadata', seek)
    return () => {
      video.removeEventListener('loadedmetadata', seek)
    }
    // `startMs` only: a re-render that changes neither the recording nor the
    // moment must not yank the playhead back from wherever the viewer scrubbed.
  }, [src, startMs])

  return (
    <video
      ref={videoRef}
      data-testid="replay-player"
      src={src}
      controls
      // Enough of the file to know the duration, so the seek can happen
      // without the viewer pressing play first — and no more, because these
      // recordings are large.
      preload="metadata"
      playsInline
      aria-label={label ?? 'Meeting recording'}
      className={className}
    />
  )
}
