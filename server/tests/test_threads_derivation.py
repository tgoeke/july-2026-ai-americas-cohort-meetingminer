"""The thread partition, with no database and no model (story 10.2).

`domain/threads.py` splits deliberately into a pure core and a Postgres half so
the clauses the acceptance criteria hinge on — idempotency and its stronger
sibling, order-independence — can be pinned without a store. Everything here is
a function of its arguments: no connection, no embedder, no clock.

The Postgres half lives in `test_threads_record.py`; the graph write and the
traversal in `test_projections_threads.py`.
"""

from __future__ import annotations

import itertools
import random
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence
from uuid import UUID

import pytest

from meetingminer.domain.threads import (
    EMBEDDING_LINK,
    NAME_LINK,
    SEED,
    ThreadCluster,
    ThreadDerivationError,
    TopicForThreading,
    cluster_topics,
    cosine_similarity,
    normalized_topic_name,
)

STARTED_AT = datetime(2026, 8, 5, 12, 0, 19, tzinfo=timezone.utc)

# Fixed ids so a failure names a topic the reader can find in the test, and so
# the order the ids sort in is a property of the test rather than of a run.
IDS = tuple(
    UUID(f"00000000-0000-4000-8000-{index:012d}") for index in range(1, 9)
)


def topic(
    index: int, name: str, *, day: int = 0, meeting: int | None = None
) -> TopicForThreading:
    """One topic, in meeting `meeting` (default: one meeting per topic)."""
    meeting_index = index if meeting is None else meeting
    return TopicForThreading(
        id=IDS[index],
        meeting_id=IDS[meeting_index],
        name=name,
        meeting_started_at=STARTED_AT + timedelta(days=day),
    )


def partition(clusters: Sequence[ThreadCluster]) -> list[frozenset[UUID]]:
    """The membership sets alone — what order-independence is a claim about."""
    return sorted(
        (frozenset(member.topic_id for member in cluster.members) for cluster in clusters),
        key=lambda members: sorted(str(member) for member in members),
    )


def legs(cluster: ThreadCluster) -> dict[UUID, str]:
    return {member.topic_id: member.linked_by for member in cluster.members}


# Orthogonal unit vectors: distinct topics that the embedding leg never links,
# so a test about the *name* leg is not quietly also a test about vectors.
def orthogonal(topics: Sequence[TopicForThreading]) -> dict[UUID, tuple[float, ...]]:
    return {
        item.id: tuple(1.0 if axis == index else 0.0 for axis in range(len(topics)))
        for index, item in enumerate(topics)
    }


# --- normalization ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SFTP Migration", "sftp migration"),
        ("sftp  migration.", "sftp migration"),
        ("SFTP-migration", "sftp migration"),
        ("  Vendor Feed  ", "vendor feed"),
        ("Purchase Order (PO) approvals", "purchase order po approvals"),
        # NFKC folds the full-width forms onto their ASCII equivalents, so a
        # name pasted out of a document is the same subject as one typed.
        ("ＳＦＴＰ", "sftp"),
        ("Straße", "strasse"),
        ("—", ""),
    ],
)
def test_normalization_is_what_the_name_leg_compares(raw: str, expected: str) -> None:
    assert normalized_topic_name(raw) == expected


# --- cosine ----------------------------------------------------------------


def test_cosine_of_a_vector_with_itself_is_one() -> None:
    assert cosine_similarity((3.0, 4.0, 0.0), (3.0, 4.0, 0.0)) == 1.0


def test_cosine_of_orthogonal_vectors_is_zero() -> None:
    assert cosine_similarity((1.0, 0.0), (0.0, 1.0)) == 0.0


def test_cosine_ignores_magnitude() -> None:
    assert cosine_similarity((1.0, 0.0), (7.0, 0.0)) == 1.0


def test_cosine_is_the_expected_ratio() -> None:
    assert cosine_similarity((1.0, 0.0, 0.0), (3.0, 4.0, 0.0)) == pytest.approx(0.6)


def test_cosine_never_exceeds_one_so_the_similarity_check_cannot_be_violated() -> None:
    """`topic_thread.similarity` is CHECKed into [0, 1]; float error must not
    push an identical pair to 1.0000000000000002 and fail the insert."""
    vector = (0.1, 0.2, 0.30000000000004, 0.7)
    assert cosine_similarity(vector, vector) <= 1.0


def test_a_zero_vector_links_nothing() -> None:
    """No direction means no angle. 0.0 is the value that links nothing —
    the recoverable failure, where treating it as similar would fuse."""
    assert cosine_similarity((0.0, 0.0), (1.0, 1.0)) == 0.0


def test_comparing_different_widths_is_a_named_refusal() -> None:
    with pytest.raises(ThreadDerivationError) as excinfo:
        cosine_similarity((1.0, 0.0), (1.0, 0.0, 0.0))
    assert "2-dimension" in str(excinfo.value) and "3-dimension" in str(excinfo.value)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_vector_component_is_a_named_refusal(bad: float) -> None:
    with pytest.raises(ThreadDerivationError, match="non-finite"):
        cosine_similarity((bad, 0.0), (1.0, 0.0))


def test_the_partition_refuses_non_finite_embeddings_instead_of_linking_them() -> None:
    topics = [topic(1, "Vendor feed"), topic(2, "Budget review", day=1)]
    vectors = {IDS[1]: (float("nan"), 0.0), IDS[2]: (1.0, 0.0)}
    with pytest.raises(ThreadDerivationError, match=str(IDS[1])):
        cluster_topics(topics, vectors=vectors, threshold=0.82)


# --- the two legs ----------------------------------------------------------


def test_topics_with_the_same_normalized_name_are_one_thread() -> None:
    topics = [topic(1, "SFTP Migration"), topic(2, "sftp  migration.", day=1)]
    clusters = cluster_topics(topics, vectors=orthogonal(topics), threshold=0.82)
    assert len(clusters) == 1
    assert clusters[0].identity_key == "sftp migration"
    assert legs(clusters[0]) == {IDS[1]: SEED, IDS[2]: NAME_LINK}


def test_topics_above_the_threshold_are_one_thread() -> None:
    topics = [topic(1, "Purchase order approvals"), topic(2, "PO sign-off", day=1)]
    vectors = {IDS[1]: (1.0, 0.0, 0.0), IDS[2]: (4.0, 3.0, 0.0)}  # cosine 0.8
    clusters = cluster_topics(topics, vectors=vectors, threshold=0.6)
    assert len(clusters) == 1
    assert legs(clusters[0]) == {IDS[1]: SEED, IDS[2]: EMBEDDING_LINK}
    joined = next(m for m in clusters[0].members if m.topic_id == IDS[2])
    assert joined.similarity == pytest.approx(0.8)


def test_a_pair_exactly_at_the_threshold_links() -> None:
    """The comparison is `>=`, and a boundary that is documented as inclusive
    but implemented as exclusive is the classic off-by-one in a threshold."""
    topics = [topic(1, "Alpha"), topic(2, "Beta", day=1)]
    vectors = {IDS[1]: (1.0, 0.0, 0.0), IDS[2]: (3.0, 4.0, 0.0)}  # cosine 0.6
    assert len(cluster_topics(topics, vectors=vectors, threshold=0.6)) == 1


def test_a_pair_just_below_the_threshold_stays_apart() -> None:
    topics = [topic(1, "Alpha"), topic(2, "Beta", day=1)]
    vectors = {IDS[1]: (1.0, 0.0, 0.0), IDS[2]: (3.0, 4.0, 0.0)}  # cosine 0.6
    clusters = cluster_topics(topics, vectors=vectors, threshold=0.61)
    assert len(clusters) == 2
    assert all(legs(cluster) == {cluster.seed_topic_id: SEED} for cluster in clusters)


def test_dissimilar_differently_named_topics_stay_apart() -> None:
    topics = [topic(1, "Vendor feed"), topic(2, "Budget review", day=1)]
    clusters = cluster_topics(topics, vectors=orthogonal(topics), threshold=0.82)
    assert len(clusters) == 2


def test_the_legs_compose_transitively() -> None:
    """A~B by name and B~C by embedding puts all three in one thread.

    Union-find takes the transitive closure, which is what makes "the same
    subject" an equivalence relation rather than a pairwise opinion — and it
    is why A and C share a thread despite being neither name-equal nor
    similar to each other.
    """
    topics = [
        topic(1, "Vendor feed"),
        topic(2, "vendor  feed", day=1),
        topic(3, "Supplier data pipeline", day=2),
    ]
    vectors = {
        IDS[1]: (1.0, 0.0, 0.0),
        IDS[2]: (0.0, 1.0, 0.0),
        IDS[3]: (0.0, 4.0, 3.0),  # cosine 0.8 with topic 2, 0.0 with topic 1
    }
    clusters = cluster_topics(topics, vectors=vectors, threshold=0.6)
    assert partition(clusters) == [frozenset({IDS[1], IDS[2], IDS[3]})]
    assert legs(clusters[0]) == {IDS[1]: SEED, IDS[2]: NAME_LINK, IDS[3]: EMBEDDING_LINK}


def test_the_name_leg_is_credited_when_both_legs_would_apply() -> None:
    """`linked_by` is stored, so it must be a property of the finished
    cluster and not of whichever pair the union-find happened to see first."""
    topics = [topic(1, "Vendor feed"), topic(2, "vendor feed", day=1)]
    vectors = {IDS[1]: (1.0, 0.0), IDS[2]: (1.0, 0.0)}  # also cosine 1.0
    clusters = cluster_topics(topics, vectors=vectors, threshold=0.6)
    assert legs(clusters[0]) == {IDS[1]: SEED, IDS[2]: NAME_LINK}
    assert all(member.similarity is None for member in clusters[0].members)


# --- idempotency and its stronger sibling, order-independence --------------


def scenario() -> tuple[list[TopicForThreading], dict[UUID, tuple[float, ...]]]:
    """Every shape at once: a name pair, an embedding pair, a transitive
    third, and two singletons — so a partition that is right by accident on a
    two-topic case has somewhere to go wrong."""
    topics = [
        topic(1, "Vendor feed"),
        topic(2, "vendor  feed.", day=3),
        topic(3, "Supplier data pipeline", day=5),
        topic(4, "Budget review", day=1),
        topic(5, "Release plan", day=2),
    ]
    vectors = {
        IDS[1]: (1.0, 0.0, 0.0, 0.0),
        IDS[2]: (0.0, 1.0, 0.0, 0.0),
        IDS[3]: (0.0, 4.0, 3.0, 0.0),
        IDS[4]: (0.0, 0.0, 1.0, 0.0),
        IDS[5]: (0.0, 0.0, 0.0, 1.0),
    }
    return topics, vectors


def test_the_partition_does_not_depend_on_the_order_topics_arrive_in() -> None:
    """Idempotency's stronger sibling, and the reason the core is union-find.

    A rerun sees the same rows, but a `SELECT` whose ORDER BY ties differently
    — or a future caller that batches — presents them in another order. If the
    partition depended on that, "a rerun yields the same threads" would hold
    only while nothing upstream changed its sort.
    """
    topics, vectors = scenario()
    baseline = cluster_topics(topics, vectors=vectors, threshold=0.6)
    for permutation in itertools.permutations(topics):
        clusters = cluster_topics(list(permutation), vectors=vectors, threshold=0.6)
        assert partition(clusters) == partition(baseline)
        assert [cluster.identity_key for cluster in clusters] == [
            cluster.identity_key for cluster in baseline
        ]
        assert [cluster.seed_topic_id for cluster in clusters] == [
            cluster.seed_topic_id for cluster in baseline
        ]
        assert [legs(cluster) for cluster in clusters] == [legs(cluster) for cluster in baseline]


def test_rerunning_the_partition_over_unchanged_topics_reproduces_it_exactly() -> None:
    topics, vectors = scenario()
    first = cluster_topics(topics, vectors=vectors, threshold=0.6)
    second = cluster_topics(topics, vectors=vectors, threshold=0.6)
    assert second == first


def test_each_vector_norm_is_computed_once_not_once_per_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact all-pairs comparison still needs only one normalization per
    topic. Recomputing two norms for every pair turns the configured
    1,024-dimensional vectors into three full scans per comparison."""
    topics, vectors = scenario()
    real_sqrt = __import__("math").sqrt
    calls = 0

    def counted_sqrt(value: float) -> float:
        nonlocal calls
        calls += 1
        return real_sqrt(value)

    monkeypatch.setattr("meetingminer.domain.threads.math.sqrt", counted_sqrt)

    cluster_topics(topics, vectors=vectors, threshold=0.6)

    assert calls == len(topics)


def test_the_seed_is_the_earliest_topic_in_the_cluster() -> None:
    """Chronological, so a thread is named for where the subject started and
    a later meeting cannot rename it."""
    topics = [topic(1, "Vendor Feed", day=9), topic(2, "vendor feed", day=1)]
    clusters = cluster_topics(topics, vectors=orthogonal(topics), threshold=0.82)
    assert clusters[0].seed_topic_id == IDS[2]
    assert clusters[0].name == "vendor feed"
    assert clusters[0].identity_key == "vendor feed"


def test_topics_in_one_meeting_break_the_seed_tie_deterministically() -> None:
    """Same meeting, same timestamp: the tie-break chain has to finish the job."""
    topics = [
        topic(1, "Zebra crossing", meeting=7),
        topic(2, "Alpha channel", meeting=7),
    ]
    clusters = cluster_topics(topics, vectors=orthogonal(topics), threshold=0.82)
    seeds = {cluster.identity_key: cluster.seed_topic_id for cluster in clusters}
    shuffled = list(topics)
    random.Random(20260830).shuffle(shuffled)
    reshuffled = cluster_topics(shuffled, vectors=orthogonal(topics), threshold=0.82)
    assert {c.identity_key: c.seed_topic_id for c in reshuffled} == seeds


# --- degenerate input ------------------------------------------------------


def test_no_topics_is_no_threads() -> None:
    assert cluster_topics([], vectors={}, threshold=0.82) == ()


def test_a_punctuation_only_name_gets_its_own_key_and_links_no_one() -> None:
    """An empty normalized name is not a shared name. Two nameless topics must
    not be fused on the strength of having nothing to compare."""
    topics = [topic(1, "—"), topic(2, "***", day=1)]
    clusters = cluster_topics(topics, vectors=orthogonal(topics), threshold=0.82)
    assert len(clusters) == 2
    assert {cluster.identity_key for cluster in clusters} == {
        f"topic:{IDS[1]}",
        f"topic:{IDS[2]}",
    }


def test_a_duplicated_topic_is_a_named_refusal() -> None:
    topics = [topic(1, "Vendor feed"), topic(1, "Vendor feed")]
    with pytest.raises(ThreadDerivationError) as excinfo:
        cluster_topics(topics, vectors=orthogonal(topics), threshold=0.82)
    assert "twice" in str(excinfo.value)


def test_a_topic_with_no_vector_is_a_named_refusal() -> None:
    """A missing vector would silently drop the similarity leg for that topic
    — a partial derivation reporting success."""
    topics = [topic(1, "Vendor feed"), topic(2, "Budget review", day=1)]
    vectors: Mapping[UUID, tuple[float, ...]] = {IDS[1]: (1.0, 0.0)}
    with pytest.raises(ThreadDerivationError) as excinfo:
        cluster_topics(topics, vectors=vectors, threshold=0.82)
    assert str(IDS[2]) in str(excinfo.value)
