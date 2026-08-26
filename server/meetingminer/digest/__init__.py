"""``digest``: read published artifacts and render an example Morning Digest email (FR31).

The capstone story that proves the Morning Digest concept without building
delivery: no SMTP, no scheduler, no per-recipient filtering. It reads whatever
``artifact`` rows already sit at ``state = 'published'`` and writes one text
file. See `meetingminer.digest.cli` for the entry point and
`meetingminer.digest.generator` for the read + render halves.
"""

from __future__ import annotations

from meetingminer.digest.generator import (
    DigestArtifact,
    DigestMeeting,
    read_published_artifacts,
    render_digest,
)

__all__ = [
    "DigestArtifact",
    "DigestMeeting",
    "read_published_artifacts",
    "render_digest",
]
