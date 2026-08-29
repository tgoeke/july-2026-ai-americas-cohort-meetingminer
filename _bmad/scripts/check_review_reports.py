#!/usr/bin/env python3
"""Fail when a dispatched review has no filed report.

Three reviews in this repo were completed in a session's terminal and never
written to disk. The prompt naming the required file did not prevent the third
loss, so the requirement is now checked mechanically: every
``review-prompt-story-<slug>-<date>.md`` in the implementation-artifacts
directory must have at least one committed ``review-story-<slug>-*.md``
sibling. Run via ``make check-reviews``; reviewers run it before reporting
completion, and anyone can run it after the fact to catch a loss immediately
instead of stories later.

Exit 0 when every dispatched review is filed, 1 otherwise, listing what is
missing. A report that exists but is only on disk (uncommitted) is called out
separately — an uncommitted report is one crash away from being the next loss.
A report that is gitignored (the 2026-08-26 reorg made ``_bmad-output``
local-only) cannot be committed, so for those the check degrades to
presence-on-disk and says so in one line rather than failing.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ARTIFACTS = Path(__file__).resolve().parents[2] / "_bmad-output" / "implementation-artifacts"
PROMPT_RE = re.compile(r"^review-prompt-story-(?P<slug>.+)-(?P<date>\d{4}-\d{2}-\d{2})\.md$")


def _tracked(path: Path) -> bool:
    return (
        subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path)],
            cwd=ARTIFACTS,
            capture_output=True,
        ).returncode
        == 0
    )


def _ignored(path: Path) -> bool:
    return (
        subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=ARTIFACTS.parent,
            capture_output=True,
        ).returncode
        == 0
    )


def main() -> int:
    missing: list[str] = []
    uncommitted: list[str] = []
    ignored = 0
    for prompt in sorted(ARTIFACTS.glob("review-prompt-story-*.md")):
        match = PROMPT_RE.match(prompt.name)
        if match is None:
            continue
        slug = match.group("slug")
        reports = sorted(ARTIFACTS.glob(f"review-story-{slug}-*.md"))
        if not reports:
            missing.append(f"{prompt.name} -> review-story-{slug}-<date>.md not filed")
            continue
        for report in reports:
            if _tracked(report):
                continue
            if _ignored(report):
                ignored += 1
                continue
            uncommitted.append(f"{report.name} exists but is not committed")
    for line in missing + uncommitted:
        print(f"check-reviews: {line}")
    if missing or uncommitted:
        print(
            "check-reviews: FAILED — a review that lives only in a terminal or"
            " an uncommitted file is not a deliverable"
        )
        return 1
    if ignored:
        print(
            f"check-reviews: every dispatched review has a report on disk ({ignored}"
            " gitignored, so their commit status could not be checked)"
        )
    else:
        print("check-reviews: every dispatched review has a committed report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
