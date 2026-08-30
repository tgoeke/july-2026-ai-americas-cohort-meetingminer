# Builder handoff — Story 7.1: Diarizer Engine Behind the Port

Agent: `bmad-build-auto`. Read `wave-2026-08-30-rules.md` in this directory
first; it carries the wave-wide rules and the conflict check you must pass.

- Repository: `/Users/devopsterus/current/cohort/meetingminer`
- Worktree: `/Users/devopsterus/current/cohort/meetingminer-wt/7-1`, branch `story/7-1`
- Story: `_bmad-output/planning-artifacts/epics.md` → "Story 7.1: Diarizer
  Engine Behind the Port" (FR36). Three Given/When/Then clauses. Stories
  7.2–7.4 (tags on the wire, assignment, naming UI) are NOT in scope.
- Context: `server/meetingminer/adapters/diarize/` (the port, `noop`, and the
  deliberately unbundled `pyannote` name), `pipeline/stages/transcribe.py`
  (`speaker_at`, the `SPEAKER_NN` contract), AD-8/AD-10.
- Owner prerequisite: `pyannote.audio` models need a Hugging Face token with
  the licence accepted. Read `HF_TOKEN` from `.env`. **If it is absent, build
  and test everything else with an injected fake pipeline, leave the
  measurement task open in the spec with the blocker named, and do not
  fabricate numbers.**

## Footprint — the only files and regions you may change

| Path | Allowed edit |
|---|---|
| `server/meetingminer/adapters/diarize/pyannote.py` | NEW. In-process `pyannote.audio` engine behind `Diarizer`; the pipeline object is injectable so tests never load a model. |
| `server/meetingminer/adapters/diarize/nemo.py` | NEW, only if the AC's fallback path (NeMo endpoint on the LAN GPU host) is actually built; config-swappable through `diarizer.engine`. |
| `server/meetingminer/adapters/diarize/__init__.py` | Register the engine(s) in `ENGINES`; when the optional dependency is not installed, `build_diarizer` still raises the named `DiarizerError`, now saying exactly which extra to install. `noop` stays the default. |
| `server/meetingminer/config.py` | `DiarizerConfig` only (main lines 137–138): extend the `engine` literal; add the engine's own settings (model id, token env name, endpoint for NeMo) as fields of this class. No other line. |
| `config.yaml` | The `diarizer:` block only (main lines 20–21), including an operator comment on installing the extra. |
| `server/pyproject.toml` | NEW table `[project.optional-dependencies]` with `diarize = [...]` (pyannote.audio, torch, …) placed immediately after the `dependencies = [...]` list closes (main ~line 63), before `[project.scripts]`. Nothing in `[dependency-groups]` and nothing at the end of the file (11-4 owns both). |
| `.env.example` | `HF_TOKEN=` with a one-line comment, appended to the "Model provider API keys" block (main ~line 58). Not the header. |
| `server/meetingminer/pipeline/stages/transcribe.py` | Only if the tag contract needs it; `speaker_at` semantics unchanged. |
| `server/tests/test_diarize_pyannote.py` (+ `test_transcribe_diarizer_tags.py` if needed) | NEW. All coverage here. |
| `_bmad-output/implementation-artifacts/` | Your spec, `sprint-status.yaml`, `sprint-notes.md`, `review-prompt-story-7-1-<date>.md`. |

Not yours: `test_config.py`, `server/tests/conftest.py`, `AGENTS.md`,
`infra/Makefile` (`make bootstrap` is not changed — the extra is installed by
hand: `uv sync --project server --extra diarize`, say so in the `config.yaml`
comment and your report), root and `docs/` READMEs, `docs/backlog.md`.

## Design constraints

- `noop` remains the default; an unavailable engine raises the named error
  before any work (fail closed, fail named).
- Turns carry `SPEAKER_NN` tags exactly as `speaker_at` assigns today; no tag
  resolves to a participant in this story.
- The 60-minute measurement (wall-clock, turn quality) goes in the story
  report with the machine and model named; it runs in-process in your
  worktree, never through the shared worker.

## Verification

- `uv run --project server pytest server/tests/test_diarize_pyannote.py -q`
- `make test-fast`; `make test` once before `review`.
- `python3 _bmad/scripts/branch_conflicts.py --against story/7-1` → clean.

## Completion

Spec `status: review`, `7-1-diarizer-engine-behind-the-port: review` and
`epic-7: in-progress` in `sprint-status.yaml`, review prompt written, all
pushed, SHAs reported — with the measurement either recorded or named as
blocked on the token.
