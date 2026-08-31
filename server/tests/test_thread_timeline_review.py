"""Review regressions for Story 10.3's pure timeline decisions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from meetingminer.domain.thread_timeline import (
    BUCKET_LADDER_MS,
    TARGET_BUCKETS,
    plan_buckets,
)


def test_exact_target_boundary_keeps_the_finer_bucket_step() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    exact_end = start + timedelta(
        milliseconds=TARGET_BUCKETS * BUCKET_LADDER_MS[0]
    )

    assert plan_buckets(start, exact_end) == (
        BUCKET_LADDER_MS[0],
        TARGET_BUCKETS,
    )

    one_millisecond_over = exact_end + timedelta(milliseconds=1)
    over_bucket_ms, over_bucket_count = plan_buckets(start, one_millisecond_over)
    assert over_bucket_ms == BUCKET_LADDER_MS[1]
    assert over_bucket_count <= TARGET_BUCKETS
