# B-36 remote diarizer review — 2026-08-30

## Scope

Review and remediate the LAN diarization endpoint behind the `Diarizer` port. In scope: `server/meetingminer/adapters/diarize/remote_http.py`, `server/meetingminer/adapters/diarize/__init__.py`, `DiarizerConfig` in `server/meetingminer/config.py`, the `diarizer:` block of `config.yaml`, and `server/tests/test_diarize_remote.py`. The STT-over-HTTP half of B-36, the committed default engine choice, and the frozen intent contract are out of scope.

## Review range

Requested builder range: `a401d6c..6bdcca8` on `story/b36-remote-diarizer`. Per the coordinator handoff, the review branch will be rebased onto `origin/main` before code inspection; the resulting reviewed range will be recorded here after rebase.

## Findings

No confirmed findings yet.
