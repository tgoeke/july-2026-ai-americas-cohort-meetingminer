import { useState } from 'react'
import { API_BASE } from '@/lib/api'
import { useOpenPath } from '@/routes/navigation'
import {
  API_UNREACHABLE_REMEDIATION,
  attributionLine,
  degradedRows,
  type StatusPoll,
} from './status'
import { useSystemStatus } from './useSystemStatus'

/**
 * The persistent chrome indicator (CAP-1): always visible, one glance says
 * whether anything needs the owner's attention, a click expands the summary
 * of exactly what and how to fix it (CAP-2), and links to the full /status
 * page. Fed by the same poll the page uses, so it changes without a reload.
 */

function summarize(poll: StatusPoll): {
  tone: 'ok' | 'attention' | 'down' | 'loading'
  label: string
} {
  switch (poll.kind) {
    case 'loading':
      return { tone: 'loading', label: 'checking system status…' }
    case 'unreachable':
      return { tone: 'down', label: 'api unreachable' }
    case 'loaded':
      return poll.status.overall === 'ok'
        ? { tone: 'ok', label: 'all systems healthy' }
        : { tone: 'attention', label: 'attention needed' }
  }
}

const DOT_CLASS: Record<string, string> = {
  ok: 'bg-green-500',
  attention: 'bg-amber-500',
  down: 'bg-destructive',
  loading: 'bg-muted-foreground',
}

export function StatusIndicator() {
  const poll = useSystemStatus()
  const [open, setOpen] = useState(false)
  const openPath = useOpenPath()
  const { tone, label } = summarize(poll)

  return (
    <div className="relative">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex items-center gap-2 rounded-md border px-2 py-1 text-sm text-muted-foreground hover:bg-accent"
      >
        <span
          aria-hidden="true"
          className={`inline-block h-2.5 w-2.5 rounded-full ${DOT_CLASS[tone]}`}
        />
        {label}
      </button>
      {open && (
        <div className="absolute right-0 z-10 mt-2 w-80 rounded-md border bg-background p-3 text-sm shadow-md">
          {poll.kind === 'unreachable' && (
            <div className="flex flex-col gap-1">
              <p className="text-destructive">
                cannot reach the api at {API_BASE}: {poll.message}
              </p>
              <p className="text-muted-foreground">{API_UNREACHABLE_REMEDIATION}</p>
            </div>
          )}
          {poll.kind === 'loaded' && poll.status.overall === 'ok' && (
            <p>Every dependency is healthy.</p>
          )}
          {poll.kind === 'loaded' && poll.status.overall !== 'ok' && (
            <ul className="flex flex-col gap-2">
              {degradedRows(poll.status).map((row) => (
                <li key={row.id} className="flex flex-col gap-0.5">
                  <span>{row.detail}</span>
                  {row.remediation != null && (
                    <span className="text-muted-foreground">→ {row.remediation}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {poll.kind === 'loaded' && (
            /* The indicator summarises; it must not summarise away whose
               reading this is. A binding shown here describes the api
               process, never the system (AD-10 as amended, AD-18). */
            <p className="mt-2 text-xs text-muted-foreground">
              {attributionLine(poll.status)}
            </p>
          )}
          <button
            type="button"
            className="mt-2 text-muted-foreground underline underline-offset-2"
            onClick={() => {
              setOpen(false)
              openPath('/status')
            }}
          >
            Open system status
          </button>
        </div>
      )}
    </div>
  )
}
