# Builder handoff — B-36 (first half): bind the LAN diarization endpoint

Agent: `bmad-build-auto`. This is a backlog item, not an epics story — the
contract below and `docs/backlog.md` B-36 are the specification.

- Worktree: `../meetingminer-wt/b36-remote-diarizer`, branch
  `story/b36-remote-diarizer`, cut from current `main`
- Read `wave-2026-08-30-rules.md` in this directory first, then this file.

## Why this exists

MeetingMiner's `Diarizer` port has **no working engine bound**. `noop` returns
nothing; story 7.1's in-process `pyannote` engine exists but needs a gated
HuggingFace model. Meanwhile a LAN GPU host now serves diarization over HTTP
and needs no token at all. This story binds it. **Scope is the `Diarizer` port
only** — B-36's `Stt`-over-HTTP half is explicitly NOT in this story.

## The endpoint, verified 2026-08-30

```
POST http://10.77.0.120:8000/diarize    multipart: file=<audio>
  -> {"turns":[{"start":0.46,"end":4.57,"speaker":"SPEAKER_00"}],
      "model":"ClusteringDiarizer(vad_multilingual_marblenet+titanet_large)"}
GET  http://10.77.0.120:8000/health
  -> {..., "ready":true, "reason":null, "diarization":{"class":..., "ready":true}}
```

Measured: 60 min of audio in 57.5s; a real 247s meeting in 14s, 82 turns, 2
speakers, chronologically ordered. Verify against the live host if it is up,
but **your test suite must not require it** (see Testing).

Facts the endpoint already guarantees, so do not re-implement them:
- `SPEAKER_NN` is local to the recording and identifies nobody.
- Silence returns `{"turns": []}` with HTTP 200 — a legitimate result.
- Overlaps are resolved by dropping the shorter measured span; timestamps are
  never fabricated.
- `/transcribe` and `/diarize` share one inference lock, so they queue.

## Footprint

| Path | Allowed edit |
|---|---|
| `server/meetingminer/adapters/diarize/<new module>.py` | NEW. The remote engine implementing the `Diarizer` protocol. Use the project's existing HTTP client convention rather than introducing a new dependency. |
| `server/meetingminer/adapters/diarize/__init__.py` | Register the engine in `ENGINES`. `noop` stays the default. |
| `server/meetingminer/config.py` | `DiarizerConfig` only (around line 212): extend the `engine` literal and add the endpoint plus a timeout. **Do not touch anything after that class** — story 8.1 is inserting immediately below it and integrate will union the two. |
| `config.yaml` | The `diarizer:` block only (lines 20-22). |
| `server/tests/test_diarize_remote.py` | NEW. All coverage here. |
| `_bmad-output/implementation-artifacts/` | Your spec, tracking, review prompt. |

Not yours: `adapters/diarize/pyannote.py` and `noop.py`, `pipeline/**`,
anything under `web/`, and every `llm`/provider region of `config.py`.

## Contract details — the ones that matter

1. **Milliseconds.** `DiarizationTurn` carries integer `start_ms`/`end_ms`; the
   endpoint returns float seconds. Convert deliberately and say in a comment
   how you round. The pipeline assigns each transcript segment the tag with the
   longest overlap, so a systematically wrong rounding mis-attributes speech.
2. **Fail by name; never fall back.** The host is operator-scheduled — VM120 is
   `onboot=0` and shares its GPU with VM116 — so being down is normal, not
   exceptional. When it is unreachable, times out, or returns 503, raise
   `DiarizerError` naming the endpoint, the model, and the reason the host gave
   (its 503 carries a `reason`, and `/health` reports `ready:false` with one —
   surface it verbatim rather than inventing your own wording). **Never** fall
   back to `noop` or to any other engine: a meeting silently ingested with no
   speaker turns, when the operator asked for diarization, is exactly the
   silent fallback this project has rejected by owner decision.
3. **An empty `turns` list is success**, not an error — the same semantics
   `noop` already has.
4. **Timeout must be configurable and finite.** A 60-minute meeting takes ~57s
   on an idle GPU but queues behind `/transcribe`. Pick a default that
   tolerates queueing, put it in `config.yaml`, and never hang forever.
5. **Do NOT choose which engine is the default.** `noop` stays default in the
   committed `config.yaml`. Whether the LAN engine or in-process `pyannote`
   becomes the recommended default is the owner's call, pending a capacity
   measurement now running. Say so in your spec rather than deciding it.

## Testing

Offline by construction: fake the HTTP layer and cover the happy path, empty
turns, a 503 with a reason, a connection failure, a timeout, malformed JSON, a
turn with `end` before `start`, and non-monotonic turns. One live test against
`10.77.0.120` may exist but must be **env-flagged and skipped by default**,
exactly as story 6.2's network test is. The suite must pass with the host
switched off.

## Verification

`uv run --project server pytest server/tests/test_diarize_remote.py -q`, then
`make test-fast` and `make test` in the foreground. `make lint` and
`make typecheck` must pass — they are inside `test-fast` now. Run
`python3 _bmad/scripts/branch_conflicts.py --against story/b36-remote-diarizer`
before the final push; a `config.py` proximity pair with `story/8-1` is
expected and belongs to integrate.

## Completion

Spec `status: review`, `review-prompt-b36-remote-diarizer-<date>.md` written
(the review lane fixes what it finds — do not copy the retired "report
findings, do not fix" wording), everything pushed. Report SHAs and real
verification output. Do not merge, do not mark done. B-36's `Stt` half stays
open in `docs/backlog.md`; note in your report that you closed only the
diarizer half.
