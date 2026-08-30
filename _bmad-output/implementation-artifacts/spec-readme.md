---
title: 'Repository README'
type: 'chore'
created: '2026-08-22'
status: 'done'
route: 'one-shot'
---

# Repository README

## Intent

**Problem:** `README.md` was a two-line stub repeating the project name, so the
repository's front door said nothing about what MeetingMiner is, how to run it,
or which of its committed model bindings cost money — every one of those facts
lived only in `SPEC.md`, `AGENTS.md`, `make help`, or `config.yaml` comments.

**Approach:** Write a full README from the sources of truth already in the tree
— the SPEC's capabilities and constraints, `infra/Makefile`'s targets,
`config.yaml`'s adapter bindings, `.env.example`'s roots, and the startup gates
in `config.py` — verifying each claim against the file that implements it rather
than against prose describing it.

## Suggested Review Order

**Cost and model bindings — the section most likely to mislead**

- The paid/local split; the first draft wrongly claimed no paid provider was reachable.
  [`README.md:299`](../../README.md#L299)

- Prerequisites now name Ollama and `OPENAI_API_KEY`, neither checked by `make check-tools`.
  [`README.md:100`](../../README.md#L100)

**Startup gates and roots — wrong here costs an unrecoverable ingest**

- All three roots, which process checks which, and what is auto-created.
  [`README.md:132`](../../README.md#L132)

- `make up` backgrounds without `--reload`; only `make api` reloads.
  [`README.md:166`](../../README.md#L166)

**System description**

- Diagram and the four properties; Postgres carries no vector column.
  [`README.md:53`](../../README.md#L53)

- Capability table, including the hybrid ranking the design argument obscured.
  [`README.md:40`](../../README.md#L40)

**Operating surface**

- Command table with required arguments; the two targets that need serializing.
  [`README.md:205`](../../README.md#L205)

- `make test` ordering, worktree store sharing, and the known-failing `make evals-run`.
  [`README.md:319`](../../README.md#L319)

- Troubleshooting: `.logs/`, store health, stuck stages, keyword-only ranking.
  [`README.md:361`](../../README.md#L361)

**Peripherals**

- Three findings routed out of this change rather than patched into it.
  [`deferred-work.md`](deferred-work.md)
