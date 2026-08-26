import type { CitationModel, RouteModel } from '@/client/types.gen'
import { problemMessage } from '@/lib/problems'

/**
 * Pure helpers for the chat panel: frame type guards, the failure taxonomy,
 * and small display formatters.
 *
 * Split out of `ChatPanel.tsx` for the same reason `features/search/hits.ts`
 * is: these are the parts worth testing without rendering anything, and the
 * component stays about state and streaming.
 */

/** A `chat.token` frame: one chunk of the already-validated answer. */
export interface ChatTokenFrame {
  event: 'chat.token'
  text: string
}

/** A `chat.citations` frame: the structured citation array (AD-15). */
export interface ChatCitationsFrame {
  event: 'chat.citations'
  citations: Array<CitationModel>
}

/** A `chat.done` frame: the route summary, once the answer is fully sent. */
export interface ChatDoneFrame {
  event: 'chat.done'
  route: RouteModel
}

export type ChatFrame = ChatTokenFrame | ChatCitationsFrame | ChatDoneFrame

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export function isChatTokenFrame(value: unknown): value is ChatTokenFrame {
  return isRecord(value) && value.event === 'chat.token' && typeof value.text === 'string'
}

export function isChatCitationsFrame(value: unknown): value is ChatCitationsFrame {
  return isRecord(value) && value.event === 'chat.citations' && Array.isArray(value.citations)
}

export function isChatDoneFrame(value: unknown): value is ChatDoneFrame {
  return isRecord(value) && value.event === 'chat.done' && isRecord(value.route)
}

/**
 * Why a question could not be answered, and how the panel should render it.
 *
 * Five kinds, because they ask for five different sentences — and three of
 * them used to be one, which is the misdiagnosis SPEC-chat-fallback-timeout's
 * CAP-3 exists to fix: `transport` is a `fetch` that never established a
 * connection, and only it may render the "Cannot reach the api" wording;
 * `timeout` is the panel's own expiry firing on a request the server had
 * already accepted (the api is up, the wait ran out); `interrupted` is a
 * stream that opened and then closed before `chat.done`. Reporting either of
 * the last two as "Cannot reach" diagnosed a live server as unreachable — the
 * recorded failure in `failure-evidence.md`.
 *
 * `problem` is the api answering with a refusal that is not the citation gate
 * (a 503 naming an unreachable store or model binding, mirroring
 * `MomentView`'s transport/domain split); `rejected` is the 422
 * `no-citable-answer` gate outcome, which story 3.4 renders as its own "no
 * citable answer" state rather than a chat bubble or a failure banner.
 */
export type ChatFailure =
  | { kind: 'transport'; message: string }
  | { kind: 'timeout'; message: string }
  | { kind: 'interrupted'; message: string }
  | { kind: 'problem'; message: string }
  | { kind: 'rejected'; reason: string; message: string }

/** The longest question the api will accept (`server/meetingminer/api/chat.py:96`). */
export const CHAT_QUESTION_MAX_LENGTH = 1000

/** Whether a question would be refused at the door — checked before any request. */
export function questionProblem(question: string): string | null {
  const trimmed = question.trim()
  if (trimmed === '') return 'Type a question before asking.'
  // JavaScript's `length` counts UTF-16 code units, whereas the API's Python
  // validator counts Unicode code points. `Array.from` makes the client apply
  // the same bound to astral characters such as emoji.
  if (Array.from(trimmed).length > CHAT_QUESTION_MAX_LENGTH) {
    return `Questions are limited to ${CHAT_QUESTION_MAX_LENGTH} characters.`
  }
  return null
}

/** "answered from N moments" — the route summary named in `RouteModel`'s comment. */
export function routeSummary(route: RouteModel): string {
  return `answered from ${route.retrieved} moment${route.retrieved === 1 ? '' : 's'}`
}

/**
 * A non-2xx response from `POST /chat`, with its parsed `application/
 * problem+json` body preserved — thrown by `chatStream.ts` instead of a
 * generic error so the status and the `reason`/`route` extensions survive to
 * `classifyFailure` below (Boundaries: the generated SSE client throws the
 * body away, which is exactly what this feature must not do for a 422).
 */
export class ChatHttpError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown, message: string) {
    super(message)
    this.name = 'ChatHttpError'
    this.status = status
    this.body = body
  }
}

function describe(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  try {
    return JSON.stringify(error) ?? 'an unknown error'
  } catch {
    return 'an unknown error'
  }
}

/**
 * What a caught error from `chatStream()` means for the panel to show.
 *
 * A `ChatHttpError` with status 422 is the citation gate's refusal — its
 * `reason` extension (`no-evidence`, `no-citations`, `uncited-claim`,
 * `unresolvable-marker`, `empty-answer`) is preserved so a future caller could
 * distinguish them, though story 3.4 renders one state for all of them. Any
 * other `ChatHttpError` (503 store/model unavailable) is a `problem` — the
 * api answered and refused, so its RFC 9457 `title`/`detail` are shown rather
 * than a generic "unreachable" sentence — a `chat-model-unavailable` 503
 * naming the `llm.roles.chat` binding renders in the server's own words
 * (CAP-4). Anything else — `fetch` throwing, a network failure — is
 * `transport`. The `timeout` and `interrupted` kinds are never produced here:
 * only `ChatPanel` knows whether its own expiry fired or a stream closed
 * early, so it classifies those two before consulting this function.
 */
export function classifyFailure(error: unknown): ChatFailure {
  if (error instanceof ChatHttpError) {
    if (error.status === 422) {
      const body = error.body
      const reason =
        isRecord(body) && typeof body.reason === 'string' ? body.reason : 'no-citable-answer'
      return { kind: 'rejected', reason, message: problemMessage(body) ?? error.message }
    }
    return { kind: 'problem', message: problemMessage(error.body) ?? error.message }
  }
  return { kind: 'transport', message: describe(error) }
}
