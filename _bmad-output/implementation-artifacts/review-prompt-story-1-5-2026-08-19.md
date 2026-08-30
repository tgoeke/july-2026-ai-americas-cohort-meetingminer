# Reviewer handoff — Story 1.5: Transcript Verification, Alignment & Participants

You have none of this run's context. Everything you need is below or at the paths named.

## Repo, branch, range

- Repo: `/Users/devopsterus/current/cohort/meetingminer`
- Branch: `main` (pushed; `git rev-list --left-right --count HEAD...@{u}` is `0 0`)
- **Review range: `a16c19872d4bf72dca393b0ce22dbf17ea160f8b..85d75ec87847cc5d9f282d20c3be015da44eac46`**

Commits in range:

| revision | subject |
|---|---|
| `85d75ec87847cc5d9f282d20c3be015da44eac46` | feat(pipeline): story 1.5 — transcript verification, alignment, participants |

One later commit, `cf7a14e5fb1403cc094732aaf9d40c5ada1b615d` ("docs(epic-1): recompile context…"), is a
regenerated planning artifact, not story code. Include it or not; nothing depends on it.

**Read this before you diff.** This working tree is shared with a concurrently running story-1.11
session (screen capture retune). Commit `85d75ec` contains **only** story 1.5, hunk-selected out of a
tree that also held 1.11's uncommitted work. So:

- `git show 85d75ec` is a clean, self-consistent story-1.5 change and is what you should review.
- The **working tree** contains story 1.11's uncommitted changes on top. `git diff` against the
  working tree will show you their work mixed with nothing of mine. Review the commit, not the tree.
- The commit's migration is `0005_`; `0004_capture_retune.sql` is 1.11's and is not in this commit.
  A migration gap is expected and harmless — `db.py` tracks applied filenames, and `0005` does not
  depend on `0004`.
- Files where hunks were split by hand: `config.yaml`, `server/meetingminer/config.py`,
  `server/pyproject.toml`, `server/uv.lock`, `server/tests/conftest.py`,
  `server/tests/test_config.py`, `server/tests/test_worker_runner.py`,
  `server/meetingminer/pipeline/runner.py`. **Worth your attention**: a split that drops a needed line
  is exactly the kind of error this process can make silently. It was verified by materialising the
  staged tree alone and running the suite (see Verification baseline), which caught four such leaks
  before commit. A fifth is possible.

## The spec

`_bmad-output/implementation-artifacts/spec-1-5-transcript-verification-alignment-participants.md`

- Everything inside `<intent-contract>` is **frozen intent** — the problem statement, the
  Always/Block-If/Never boundaries, and the I/O & Edge-Case Matrix. Do not critique these as design
  choices; if one seems wrong, say so as an intent finding.
- Everything outside it — **Code Map, Tasks & Acceptance, Design Notes, Spec Change Log, Review
  Triage Log, Auto Run Result** — is planner work and is fair game.
- The `deferred:` frontmatter list holds ten items already triaged as out of scope for this story.
  Re-raising one as a new finding is noise; challenging the *decision to defer* is not.

## Architecture authority

`_bmad-output/planning-artifacts/architecture/architecture-meetingminer-2026-08-16/ARCHITECTURE-SPINE.md`.
The decision records that actually govern this change:

- **AD-5** (`:194`) — table ownership is disjoint. The worker writes evidence tables; the API owns
  human-curated columns. Participants split by column, and a human merge writes an **alias row** the
  worker resolves before every insert. This story creates `participant_alias` and the worker-side
  read; the API-side write is Epic 2.
- **AD-8** (`:212`) — model calls go through project-owned ports bound in config. `Stt` and
  `Diarizer` are added here.
- **AD-10** (`:224`) — one config file. Every threshold introduced must be in `config.yaml`.
- **AD-11** (`:230`) — stages are idempotent; a rerun overwrites *its own* outputs for that meeting
  only, and cross-meeting entities (screens, participants) are upserted by identity key and never
  deleted by a rerun.
- **AD-13** (`:242`) — provided transcripts are immutable inputs; merge, never erase. Also fixes
  multi-form precedence: **labels from the speaker-attributed export, cue timing from the VTT when
  present, reconciled by text alignment — never by picking one file wholesale.**
- **AD-1** (`:170`) — participant resolution is the *source side's* job; the sidecar carries what the
  puller supplies, and when a drop omits participants the pipeline derives them from transcript
  speaker attribution. No server component calls Microsoft Graph.

Also relevant: `_bmad-output/specs/spec-meetingminer/corpus-facts.md` §3–§4 (measured properties of
the real transcripts and participant graph) and `SPEC.md`'s never-guess constraint.

## Scope

**In scope — the files in `85d75ec`:**

- `server/meetingminer/adapters/stt/{port,mlx_whisper,parakeet_mlx,__init__}.py`
- `server/meetingminer/adapters/diarize/{port,noop,__init__}.py`
- `server/meetingminer/pipeline/{transcripts,speakers,alignment}.py` — the pure cores
- `server/meetingminer/pipeline/stages/{transcribe,align}.py` — the stages
- `server/meetingminer/pipeline/stages/__init__.py`, `server/meetingminer/pipeline/runner.py`,
  `server/meetingminer/pipeline/media.py`
- `server/meetingminer/migrations/0005_transcripts_participants.sql`
- `server/meetingminer/config.py`, `config.yaml`, `server/pyproject.toml`, `server/.python-version`,
  `server/uv.lock`
- `docs/source-drop.schema.json` (description text only)
- `server/tests/` — five new modules plus `conftest.py`, `test_pipeline_media.py`,
  `test_worker_runner.py`

**Explicitly out of scope:**

- Story 1.6 (moments), 1.7 (projections), 1.9 (UI/SSE), 1.11 (screen capture retune), 1.12
  (late-recording augmentation). Epic 2–5 of any kind.
- Screens, screenshots, OCR, frames — untouched by this commit.
- `pull_transcript/` — the upstream puller. Not modified, and must not be.
- The ten `deferred:` items in the spec frontmatter.

**No commit in the range belongs to a different story.**

## Design decisions to attack

The planner is not a neutral judge of its own calls. These are the ones worth your scepticism.

1. **Identity keys on `mail`, namespaced `mail:` / `name:`.** Mid-run the original premise ("no
   directory identifier is available because Graph is a non-goal") was falsified: the participant
   graph carries a real `mail` on 222/225 person-rows, from the SharePoint user-profile service, no
   Graph call involved. Identity was switched to mail-first with normalized name as fallback.
   *Assumption:* mail is stable enough to be a permanent identity key, and a namespaced single column
   beats two columns or a synthetic id. *Also assumes* the split it creates (see deferred item 1) is
   acceptable to defer.
2. **The graph is the roster authority, not a union with transcript labels.** With a graph present, a
   speaker the graph omits is `unresolved` and never becomes a participant. AC 4's "joined to" is
   readable as a union. *Assumption:* corpus-facts' "treat the chart as the participant source of
   record" settles it. On today's data the readings are indistinguishable, because no drop carries a
   graph — so nothing tests which one is right.
3. **A shared name forces `ambiguous`, applied in `align` rather than `speakers`.** `resolve_label`
   compares against a *set* of keys and so cannot see two roster entries writing one name;
   `_disambiguate` handles it at the stage. *Assumption:* the stage is the right layer for a fact only
   the roster knows. An alternative is making `resolve_label` take entries rather than keys.
4. **The STT lane is persisted as `transcript_source.segments` jsonb rather than as derived rows.**
   Otherwise `align`'s second run destroys its own verification anchor. *Assumption:* a raw lane in
   jsonb is better than a second segment table, and re-parsing the provided transcript from the
   read-only drop every run is cheap enough.
5. **Audio is extracted to a persisted 16 kHz mono WAV under `meetings/<id>/audio/`.** *Assumption:*
   handing both engines an identical decoded waveform matters more than the disk cost, and a
   persisted artifact beats a temp file.
6. **Python pinned `>=3.12,<3.13` for the whole server.** The MLX wheels have no 3.14 build.
   *Assumption:* AD-9's single-Mac runtime makes a narrow bound free. It is a repo-wide constraint
   imposed by one story's dependency.
7. **`_PLACEHOLDER_LABEL` was widened to `speaker|spk|guest|attendee|participant` with `_`/`-`
   separators.** Fixes a real hole (`SPEAKER_00` became a resolved participant). *Assumption:* no real
   person in this corpus is labelled by one of those words. Check the false-positive risk.
8. **`transcript_segment.stt_source_id` is `ON DELETE CASCADE`.** Deleting the STT lane therefore
   destroys derived rows whose text came from the provided `.txt`. Deferred, not fixed — argue it.

## History you need to tell a regression from a pre-existing condition

- **Two tests fail at the baseline** and are not this story's:
  `test_ocr_adapter.py::test_parse_tsv_without_page_dimensions_is_a_named_error` and
  `test_worker_runner.py::test_empty_and_populated_stage_logs_carry_the_same_fields`. Both were
  reproduced at `a16c1987` in a clean detached worktree. The second asserts
  `stage.screens.captured.directory is None` on the zero-frame path while the stage does publish an
  empty directory there — a stale assertion from story 1.4's reviewed fix, left alone rather than
  edited unattended to match code. They make `make test` red independently of this change.
- **The suite is unreliable when run concurrently.** The story-1.11 session shares the fixed-name
  `meetingminer_test` database, and interleaved runs produced anywhere from 2 to 62 spurious
  failures (`psycopg.errors.AdminShutdown`, `UndefinedTable`, empty-result unpacking). **Run the
  suite in isolation before believing any red result.**
- One assertion was legitimately updated by this story:
  `test_zero_frames_completes_ocr_and_screens_with_no_outputs` asserted `transcribe == "queued"`,
  which was true only while `transcribe` was unbuilt.
- The migration was renumbered `0004_` → `0005_` mid-run because story 1.11 took `0004_`.

## Verification baseline

Reproduce before judging any failure as a finding.

```
# The commit alone, isolated from the shared test database and from story 1.11:
git worktree add /tmp/s15 85d75ec87847cc5d9f282d20c3be015da44eac46
cp .env /tmp/s15/.env
sed -i '' 's/^TEST_DATABASE = "meetingminer_test"$/TEST_DATABASE = "meetingminer_test_rev"/' \
  /tmp/s15/server/tests/conftest.py
cd /tmp/s15 && uv run --project server pytest server/tests -q
```

Current results:

- **Staged commit alone: 409 passed, 2 failed, 0 skipped** — the two pre-existing failures above.
- **Full working tree (story 1.5 + 1.11): 444 passed, 2 failed, 0 skipped.**
- `make migrate` twice: applies once, then "nothing to apply". Fresh empty database applies
  `0001`–`0005` once and reports nothing on the second pass.
- `uv run --project server python -c "import sys; print(sys.version)"` → `3.12.14`.
- Real corpus, through the actual worker, drop
  `2026-04-28-supplier-hub-design-icontract-review-059c6916`:
  - as it exists (no `participants` key): 55 segments, all `resolved`, 9 `name:`-keyed participants,
    0 externals, 0 non-resolved rows carrying a `participant_id`.
  - with the live `org chart.json` mapped into `metadata.participants`: 55 segments, all `resolved`,
    10 participants (9 `mail:`-keyed, 1 `name:` fallback), 1 external preserved, 0 misattributions.
  - The drop directory's file list, sizes, and mtimes are unchanged by either run.
- Corpus-wide: all 28 real `transcript.txt` files parse; the 28 real `org chart.json` files carry all
  16 documented fields on 225/225 person-rows, 222 with `mail`, 3 external, 0 `guest`.

A skip or a failure during your review is a finding, not noise — the suite has zero skips.

## Required output

Write your findings to
`_bmad-output/implementation-artifacts/review-story-1-5-2026-08-19.md`.

**Report findings; do not apply fixes.** Structure each as:

- **Location** — `path/to/file.py:line`
- **Severity** — high / medium / low, by consequence for a user of the system
- **Claim** — one sentence stating the defect
- **Failure scenario** — concrete inputs or state, and the wrong output or crash that results
- **Evidence** — why you believe it, ideally a command and its output

Group findings under `## Correctness`, `## Design`, `## Tests`, and `## Documentation`. If a section
is empty, say so rather than omitting it. Close with a short verdict paragraph: does this change meet
the story's acceptance criteria as written in `_bmad-output/planning-artifacts/epics.md` under
`### Story 1.5`?

Eighteen findings were already patched during this run and are listed in the spec's Review Triage
Log — read it first so you do not re-report them. Finding something it missed is the point.
