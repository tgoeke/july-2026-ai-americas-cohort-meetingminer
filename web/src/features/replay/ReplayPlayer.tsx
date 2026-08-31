import { useEffect, useRef } from 'react'
import { recordingUrl } from '@/lib/media'

export interface ReplayPlayerProps {
  /** The meeting whose recording plays. */
  meetingId: string
  /** Where playback opens, in milliseconds from the start of the recording. */
  startMs: number
  /**
   * Where playback stops, in milliseconds from the start of the recording.
   *
   * Absent for every caller that opens a moment, and that is the point: a
   * replay runs on for as long as the viewer lets it, and imposing an end on
   * those callers would truncate the thing they came to hear. Story 7.4's
   * speaker clips are the one caller that sets it, at `startMs + 8000` —
   * enough of a voice to recognize it, and short enough that the clip does
   * not run into the next speaker's turn and teach the wrong voice.
   */
  endMs?: number
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
export function ReplayPlayer({
  meetingId,
  startMs,
  endMs,
  label,
  className,
}: ReplayPlayerProps) {
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

  useEffect(() => {
    const video = videoRef.current
    if (video === null || endMs === undefined || !Number.isFinite(endMs)) return
    const stopAt = Math.max(0, endMs / 1000)
    // Armed once per clip, and disarmed by the stop it causes.
    //
    // Without the latch, the pause would be permanent rather than a stop: the
    // playhead stays past `stopAt` after the clip ends, so the viewer's next
    // press of play would be undone by the very next `timeupdate`, and the
    // control would look broken. Disarming means the clip stops once and the
    // recording is the viewer's again — this component's job is to end the
    // sample, not to fence off the rest of the meeting.
    let armed = true
    const stop = () => {
      if (!armed || video.currentTime < stopAt) return
      armed = false
      video.pause()
    }
    // Seeking back before the boundary is a new listen, so it re-arms: a
    // curator who scrubs back a few seconds to hear the voice again gets the
    // same eight-second stop they got the first time.
    const rearm = () => {
      if (video.currentTime < stopAt) armed = true
    }
    video.addEventListener('timeupdate', stop)
    video.addEventListener('seeked', rearm)
    return () => {
      video.removeEventListener('timeupdate', stop)
      video.removeEventListener('seeked', rearm)
    }
    // `startMs` is in the list so that pressing the same clip's neighbour —
    // or the same clip again after a seek — re-arms the latch even when the
    // end offset is unchanged.
  }, [src, startMs, endMs])

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
