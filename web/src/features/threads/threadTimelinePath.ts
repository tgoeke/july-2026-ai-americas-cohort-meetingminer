/** The optional moment anchor carried by a thread deep link. */
export type ThreadTimelineAnchor =
  | { kind: 'absent' }
  | { kind: 'valid'; source: string; epochMs: number }
  | { kind: 'invalid'; source: string; reason: string }

// RFC 3339 date-time with an explicit UTC designator or numeric offset. A bare
// date is useful elsewhere in the product, but it is not a moment instant.
const RFC3339_INSTANT =
  /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:[Zz]|([+-])(\d{2}):(\d{2}))$/

function daysInMonth(year: number, month: number): number {
  if (month === 2) {
    const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
    return leap ? 29 : 28
  }
  return [4, 6, 9, 11].includes(month) ? 30 : 31
}

function epochOf(source: string): number | null {
  const match = RFC3339_INSTANT.exec(source)
  if (match === null) return null
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, , offsetHourText, offsetMinuteText] =
    match
  const year = Number(yearText)
  const month = Number(monthText)
  const day = Number(dayText)
  const hour = Number(hourText)
  const minute = Number(minuteText)
  const second = Number(secondText)
  const offsetHour = offsetHourText === undefined ? 0 : Number(offsetHourText)
  const offsetMinute = offsetMinuteText === undefined ? 0 : Number(offsetMinuteText)
  if (
    year === 0 ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > daysInMonth(year, month) ||
    hour > 23 ||
    minute > 59 ||
    second > 59 ||
    offsetHour > 23 ||
    offsetMinute > 59
  ) {
    return null
  }
  const epochMs = Date.parse(source)
  return Number.isNaN(epochMs) ? null : epochMs
}

/**
 * The URL decision shared with a moment-card producer.
 *
 * A calling moment preserves its served RFC 3339 instant as `at`; callers that
 * only know the thread get the bare path and therefore the thread-span default.
 */
export function threadTimelinePath(threadId: string, occurredAt?: string | null): string {
  if (threadId.trim().length === 0) throw new Error('thread timeline requires a non-empty thread id')
  const path = `/threads/${encodeURIComponent(threadId)}`
  if (occurredAt === undefined || occurredAt === null) return path
  if (epochOf(occurredAt) === null) {
    throw new Error(`thread timeline \`at\` must be an RFC 3339 instant: ${occurredAt}`)
  }
  return `${path}?${new URLSearchParams({ at: occurredAt }).toString()}`
}

/** Parse the route's optional anchor without ever degrading an invalid value to bare-link behavior. */
export function threadTimelineAnchor(search: string): ThreadTimelineAnchor {
  const values = new URLSearchParams(search).getAll('at')
  if (values.length === 0) return { kind: 'absent' }
  const source = values.join(', ')
  if (values.length !== 1) {
    return { kind: 'invalid', source, reason: '`at` must appear exactly once' }
  }
  const epochMs = epochOf(values[0])
  if (epochMs === null) {
    return { kind: 'invalid', source, reason: '`at` must be an RFC 3339 instant' }
  }
  return { kind: 'valid', source: values[0], epochMs }
}
