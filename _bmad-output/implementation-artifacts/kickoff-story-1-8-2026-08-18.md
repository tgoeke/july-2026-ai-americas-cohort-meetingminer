# Kickoff brief — Story 1.8: Teams Puller Emits Source Drops

Written 2026-08-18 for a fresh session. Everything below was verified on this
machine; nothing here is inferred.

## Invocation

```
bmad-build-auto 1.8
```

Do not start until the session is fresh. The workflow's step 01 will re-check
the tree and remote itself.

## Repo state at handoff

- Branch `main`, HEAD `6c4bd43`, tree clean, `0	0` against `origin/main`.
- `make up` works end to end: stores healthy, migrations current, api (:8000),
  worker, web (:5173) all ready.
- `make test` — 205 passed, web build clean.

## Why 1.8 and not 1.4

Story 1.3 is at `review` (spec `in-review`), awaiting a Codex pass via
`review-prompt-story-1-3-2026-08-18.md`. Stories 1.4–1.7 and 1.9 all read or
extend surfaces that review may change:

| Story | Blocked by |
| --- | --- |
| 1.4 Screen identification | consumes the `frame` rows and `offset_ms` that 1.3 introduced |
| 1.5 Transcript verification | registers `transcribe`/`align` into 1.3's stage registry |
| 1.6, 1.7 | chain off 1.4/1.5 |
| 1.9 UI progress | needs SSE in `api/jobs.py` — the exact file rewritten in `a56440e`, which is inside the review range |

Story 1.8 depends only on the drop schema and `POST /ingests`, both shipped in
story 1.2 and untouched by 1.3. Per AD-1 the puller shares no server code, so no
review finding against the pipeline can invalidate this work.

## The puller: what is actually here

`puller` is a symlink to `pull_transcript/`. The user's ruling: this is a
complete, separate fork, **freely modifiable** — their working copy lives on
another machine. The story-1.2 and story-1.3 specs listed `pull_transcript/`
under "Never"; that constraint was scoped to those stories and does not apply
here. The architecture explicitly says the puller "gains emit-drop + one-time
backfill steps".

Present on disk and gitignored (`pull_transcript/.gitignore` ignores `*`), so
nothing here enters git:

- 28 pulled occurrences, each a `<Title>/<M.D.YY>/` directory with `_source.json`
- `.transcript-profile/` — the persisted browser session
- `pulls.jsonl`, `archives.txt`, `node_modules/`, `migration-plan.txt`

Tracked source (13 files): `grab-teams-transcript.js`, `migrate-layout.js`,
`seed-pull-log.js`, `index-archives.sh`, `.probe-item.js`, `package.json`,
`package-lock.json`, `CLAUDE.md`, `README.md`, three prompt `.md` files,
`.gitignore`.

### Archive profile (all 28 occurrences, measured)

| Files present | Count |
| --- | --- |
| `docx, md, txt, vtt` | 11 |
| `txt` only | 5 |
| `docx, md, mp4, txt, vtt` | 4 |
| `mp4, txt` | 2 |
| `docx, txt, vtt` | 2 |
| `docx, mp4, txt, vtt` | 2 |
| `md, txt, vtt` | 1 |
| `md, txt` | 1 |

- **8 of 28 have a recording** (`.mp4`); **20 are transcript-only** — confirms
  the epic's "mostly transcript-only" and exercises story 1.3's skip path.
- **20 of 28 carry a `.vtt`** — which is why the story-1.2 review finding about
  VTT-only intake mattered; that fix is in `a56440e`.
- All 28 have a `.txt` (the speaker-attributed export).
- `.docx` / `.md` are the puller's generated summaries. Per AD-1 these are
  unknown files and must be **ignored at intake**, not mapped into the drop.

`_source.json` `dateSource` values: 21 `migrate-layout.js (from pulls.jsonl)`,
6 `the recording's createdDateTime`, 1 `the date in the recording's name`. The
`startedAt` / `startedAtPrecision` mapping must handle all three; the first
group is the reason `day` precision exists.

## Scope caveat — read before planning

This fork is **not the working puller**. Live pulls run on another machine
against the corp production tenant. Consequences for the story's acceptance
criteria:

- **Buildable and verifiable here:** the emit-drop mapping, the one-time backfill
  over all 28 occurrences, write-once/never-overwrite on re-emit, and the
  puller-side schema validation tests.
- **Not verifiable here:** the live "paste a recap URL → pull → emit → POST
  `/ingests`" path. It needs a live Teams session against a production tenant,
  which should not run unattended regardless. Implement it, test the emit and
  POST halves against fixtures and the local api, and hand the live leg to the
  user to run on their working copy.

State this split explicitly in the spec rather than implying the whole story was
exercised.

## Decision already made

Drops folder defaults to `/Users/devopsterus/current/meetingminer-drops` — a
sibling of `MM_CONTENT_ROOT` (`/Users/devopsterus/current/meetingminer-content`),
outside both the repo and the puller's archive. AD-1 requires it be distinct
from the puller's working archive, which re-pulls mutate in place. Make it
overridable puller-side; the puller must not read the server's `config.yaml`
(black-box seam).

## What the workflow now does on its own

Overrides added 2026-08-18 in `_bmad/custom/`:

- **Remote-sync gate** before step 01 — fetches upstream, fast-forwards when
  behind, halts on divergence. Added after story 1.3 was built on a base that
  had diverged from `origin/main`.
- **`on_complete`** — commits (staging only the story's files), pushes,
  announces and confirms five verified facts, then writes
  `review-prompt-story-1-8-<date>.md` for Codex.

So the run ends by handing over the next Codex prompt. No manual step needed.

## Parallel track

Codex is reviewing story 1.3 from
`_bmad-output/implementation-artifacts/review-prompt-story-1-3-2026-08-18.md`.
It will return `build-prompt-story-1-3-<date>.md`. When that arrives, apply or
defer the findings, mark 1.3 `done`, commit, push — that work is independent of
1.8 and touches different files.
