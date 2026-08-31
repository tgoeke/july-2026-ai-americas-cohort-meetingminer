# B-36 remote diarizer review — 2026-08-30

## Scope

Review and remediate the LAN diarization endpoint behind the `Diarizer` port. In scope: `server/meetingminer/adapters/diarize/remote_http.py`, `server/meetingminer/adapters/diarize/__init__.py`, `DiarizerConfig` in `server/meetingminer/config.py`, the `diarizer:` block of `config.yaml`, and `server/tests/test_diarize_remote.py`. The STT-over-HTTP half of B-36, the committed default engine choice, and the frozen intent contract are out of scope.

## Review range

Requested builder range: `a401d6c..6bdcca8` on `story/b36-remote-diarizer`.

Rebased review range: `origin/main..97754b4` on `story/b36-remote-diarizer-review` at the start of code inspection:

- `10457a6` — spec(b36): plan the remote-http diarizer engine behind the Diarizer port
- `46a5708` — feat(b36): bind the LAN diarization endpoint behind the Diarizer port
- `9c1cbaa` — docs(b36): spec to review with its change log, sprint tracking, review handoff
- `97754b4` — docs(b36): record the verified gate output and the real branch state

The report skeleton commit `74cbf2b` follows that reviewed builder range and is not implementation under review.

## Findings

No confirmed findings yet.
