# Code review — Story 1.6: Moment Identification Completes the Bundle

Reviewed range: `2d301b6d7db1f48fc5f631707c34ea52dc21db86..f0d1669c019f42e6ea320656f6e4c673e1656546` on `main`.

Review mode: full. The frozen intent contract in `spec-1-6-moment-identification-completes-the-bundle.md` was used as the specification. Four independent review layers completed; no layer failed.

## High

- **Upstream evidence reruns leave `moments` settled over replaced inputs** — [server/meetingminer/pipeline/stages/screens.py:323](/Users/devopsterus/current/cohort/meetingminer/server/meetingminer/pipeline/stages/screens.py:323), [server/meetingminer/pipeline/stages/align.py:598](/Users/devopsterus/current/cohort/meetingminer/server/meetingminer/pipeline/stages/align.py:598), [server/meetingminer/pipeline/runner.py:315](/Users/devopsterus/current/cohort/meetingminer/server/meetingminer/pipeline/runner.py:315). A normal runner-driven rerun can queue only `screens`, exactly as the existing screens-rerun test does. That stage deletes screenshots; their FK sets moment references to `NULL`, but the runner resumes the already-done `moments` stage and never attaches the replacement captures or creates new screen-derived moments. An `align` rerun likewise deletes transcript segments and cascades all moment links while `moments.segment_count` stays stale. This breaks the evidence bundle after a supported upstream rerun. Caused by this change, which introduced `moments` as both consumers' dependent output. Fix now: successful `screens` and `align` re-execution must cause `moments` to rerun through the runner, retaining citation ids; add runner-level regressions for both dependency paths.

## Medium

None.

## Low

- **The required missing-link event field is absent** — [server/meetingminer/pipeline/stages/moments.py:249](/Users/devopsterus/current/cohort/meetingminer/server/meetingminer/pipeline/stages/moments.py:249). The frozen I/O matrix requires `moments_without_link`; the implementation and its tests use only `degraded_moments_without_link`. A transcript-only drop without a usable provenance URL emits no specified contract field. Caused by this change. Fix now: emit the required field (additively retaining the renamed field if desired) and test the frozen name.

- **`retained_stale` counts superseded screen moments** — [server/meetingminer/pipeline/stages/moments.py:224](/Users/devopsterus/current/cohort/meetingminer/server/meetingminer/pipeline/stages/moments.py:224). The required count is restricted to transcript-anchored moments retained without recomputation, but the unfiltered update returns a screen moment when a transcript boundary takes over its start. The summary therefore reports a misleading stale-transcript count. Caused by this change. Fix now: compute the metric for transcript-anchored retained rows only while retaining the correct supersession behavior for screen rows.

- **Replay does not retire deep links on newly superseded moments** — [server/meetingminer/pipeline/stages/moments.py:224](/Users/devopsterus/current/cohort/meetingminer/server/meetingminer/pipeline/stages/moments.py:224). When a linked transcript-only moment is retained as superseded after replay arrives and alignment moves its boundary, the broad supersession update leaves its source deep link. This contradicts the table/stage rule that the fallback link clears once replay exists. Caused by this change. Fix now: clear the link for retained rows whenever replay evidence is present, without deleting or re-keying those rows.

- **A hostless HTTP(S) value is accepted as a deep link** — [server/meetingminer/domain/drops.py:123](/Users/devopsterus/current/cohort/meetingminer/server/meetingminer/domain/drops.py:123). `urlsplit("https:")` reports an allowed scheme, so the invalid value is written and rendered rather than treated as absent. Caused by this change. Fix now: require an authority component for an HTTP(S) URL and test hostless malformed cases.

## Dismissed after validation

13 candidates were dismissed: missing screenshot-only and heartbeat tests are coverage improvements rather than defects in the implemented stage; the hard-coded heartbeat cadence is operational, not a boundary threshold; the requested screenshot query index is a non-blocking pre-existing performance concern; generic cross-meeting, identity-key, and URL-schema constraints are not required where the sole writer already scopes and validates inputs; timestamp churn is compatible with stated idempotence; duplicate `start_ms` for documented superseded rows is explicitly deferred to Epic 2 projection filtering; and the final-capture screenshot rule is an explicit, tested design choice.
