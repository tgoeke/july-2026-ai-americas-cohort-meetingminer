import type { DrilldownSegment } from '@/client/types.gen'

function timestamp(milliseconds: number): string {
  const whole = Math.max(0, Math.floor(milliseconds))
  const hours = Math.floor(whole / 3_600_000)
  const minutes = Math.floor((whole % 3_600_000) / 60_000)
  const seconds = Math.floor((whole % 60_000) / 1_000)
  const millis = whole % 1_000
  return [hours, minutes, seconds]
    .map((part) => String(part).padStart(2, '0'))
    .join(':') + `.${String(millis).padStart(3, '0')}`
}

function cueText(value: string): string {
  return value
    .replace(/\s+/g, ' ')
    .trim()
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
}

/** Turn the ordered transcript returned by `/drilldown` into a captions
 * resource the browser can consume without another server endpoint. */
export function webVttDataUrl(segments: Array<DrilldownSegment>): string | null {
  const cues = [...segments]
    .sort((left, right) => left.ordinal - right.ordinal)
    .flatMap((segment) => {
      if (!Number.isFinite(segment.startMs) || !Number.isFinite(segment.endMs)) return []
      const text = cueText(segment.text)
      if (text === '') return []
      const speaker = cueText(segment.speakerLabel)
      const start = Math.max(0, segment.startMs)
      const end = Math.max(start + 1, segment.endMs)
      return [
        `${timestamp(start)} --> ${timestamp(end)}\n${speaker === '' ? text : `${speaker}: ${text}`}`,
      ]
    })
  if (cues.length === 0) return null
  return `data:text/vtt;charset=utf-8,${encodeURIComponent(`WEBVTT\n\n${cues.join('\n\n')}\n`)}`
}
