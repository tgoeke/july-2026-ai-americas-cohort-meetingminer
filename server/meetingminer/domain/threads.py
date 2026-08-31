"""Deriving threads from stored topics (story 10.2, FR42).

A **thread** is one subject followed across meetings. Story 10.1's `extract`
stage wrote per-meeting `topic` rows anchored to moments; this module reads all
of them and partitions them into threads by two legs, both required by the
acceptance criteria:

* **normalized name** — two topics whose names normalize to the same string are
  the same subject ("SFTP Migration", "sftp  migration.");
* **embedding similarity** — two topic names whose vectors reach
  ``threads.embedding_similarity_threshold`` are the same subject
  ("Purchase order approvals", "PO sign-off").

**Idempotency is structural, not conventional.** The acceptance criteria
require a rerun over unchanged topics to yield the same threads, and every
downstream reference — the ``Thread`` graph node's key, story 10.2a's curation,
story 10.3's timeline — keys on ``thread.id``. Four properties together make
that hold, and each is a property of the construction rather than of a
convention the next maintainer might not notice:

1. The partition comes from **union-find over a set of pairs**, whose result
   is independent of the order the pairs are considered. There is no greedy
   "assign to the first match above threshold" pass whose output would depend
   on a sort.
2. Each cluster's **seed** is its deterministic minimum under
   ``(meeting.started_at, meeting.id, normalized name, topic.id)`` — earliest
   rather than alphabetically first, because new meetings almost always arrive
   *later*, so a chronological seed survives corpus growth where an
   alphabetical one would be re-seeded by any new topic that sorts before it.
3. ``identity_key`` is the seed's normalized name, and the derivation UPSERTs
   threads on it. Seeds cannot collide: every topic sharing a normalized name
   is already in one cluster, so no two clusters present the same seed name.
4. Every UPSERT carries a ``WHERE`` that fires only on an actual change, so an
   unchanged rerun writes nothing at all — not even ``updated_at``.

**No silent fallback.** An :class:`Embedder` is required. When the model host
is unreachable the derivation raises before it writes anything, rather than
half-running on the name leg and reporting success — a corpus threaded by name
alone is not the corpus this module claims to produce.

Deliberately store-free in the retrieval sense: nothing here imports ``neo4j``
or ``meilisearch``. ``projections`` remains the sole writer of both retrieval
stores (AD-4); this module writes only the two Postgres tables migration 0015
declares, and the graph learns about threads by reading them back through
``projections/evidence.py``.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping, Sequence
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from meetingminer.adapters.embed.port import Embedder, Vector
from meetingminer.config import AppConfig

# The three `topic_thread.linked_by` legs migration 0015's CHECK declares.
SEED = "seed"
NAME_LINK = "normalized-name"
EMBEDDING_LINK = "embedding-similarity"


class ThreadDerivationError(RuntimeError):
    """The derivation cannot produce a coherent partition — named, never partial."""


# --- value objects ---------------------------------------------------------


@dataclass(frozen=True)
class TopicForThreading:
    """One stored topic, with the two facts the partition needs about it.

    ``meeting_started_at`` rather than the topic's own timestamp: a thread is
    named for the meeting where the subject first came up, and `topic` has no
    occurrence time of its own — its mentions do, but a topic spans them.
    """

    id: UUID
    meeting_id: UUID
    name: str
    meeting_started_at: datetime

    @property
    def normalized_name(self) -> str:
        return normalized_topic_name(self.name)

    @property
    def order_key(self) -> tuple[datetime, UUID, str, UUID]:
        """The total order the cluster seed is the minimum of."""
        return (self.meeting_started_at, self.meeting_id, self.normalized_name, self.id)


@dataclass(frozen=True)
class ThreadMember:
    """One topic's membership of a thread, and the evidence for it."""

    topic_id: UUID
    linked_by: str
    similarity: float | None


@dataclass(frozen=True)
class ThreadCluster:
    """One derived thread, before it meets the database."""

    identity_key: str
    name: str
    seed_topic_id: UUID
    members: tuple[ThreadMember, ...]


@dataclass(frozen=True)
class ThreadDerivation:
    """What one derivation pass produced, for a caller to report."""

    thread_count: int
    topic_count: int
    name_links: int
    embedding_links: int


# --- the pure core ---------------------------------------------------------


def normalized_topic_name(name: str) -> str:
    """The comparison form of a topic name — what the name leg links on.

    NFKC first so a full-width or composed character does not read as a
    different subject, then casefold (not ``lower()``: casefold is the form
    that folds ``ß`` and the Turkish dotted forms), then every non-alphanumeric
    character becomes a space and runs of whitespace collapse. That is what
    makes "SFTP Migration", "sftp  migration." and "SFTP-migration" one string
    and therefore one thread.
    """
    folded = unicodedata.normalize("NFKC", name).casefold()
    spaced = "".join(character if character.isalnum() else " " for character in folded)
    return " ".join(spaced.split())


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine of the angle between two vectors, clamped to [-1.0, 1.0].

    A zero-norm vector has no direction, so no angle to another vector exists
    and the similarity is 0.0 — the value that links nothing. That is the safe
    direction for a degenerate embedding: it costs a link that might have been
    real, where the alternative (treating it as maximally similar) would fuse
    unrelated subjects. Clamping absorbs the float error that can push an
    identical pair to 1.0000000000000002 and out of `similarity`'s CHECK.
    """
    if len(left) != len(right):
        raise ThreadDerivationError(
            f"cannot compare a {len(left)}-dimension vector with a"
            f" {len(right)}-dimension one — every topic name is embedded by"
            " the same model in one pass, so a width mismatch is a bug here,"
            " not a model response"
        )
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


class _DisjointSet:
    """Union-find over topic ids. Path compression, union by size.

    The reason this is union-find and not a greedy assignment pass: the
    partition it produces is a function of the *set* of pairs, not of the order
    they arrive in. That is exactly the idempotency clause, obtained from the
    algorithm rather than from a sort somebody could later change.
    """

    def __init__(self, items: Sequence[UUID]) -> None:
        self._parent: dict[UUID, UUID] = {item: item for item in items}
        self._size: dict[UUID, int] = dict.fromkeys(items, 1)

    def find(self, item: UUID) -> UUID:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, left: UUID, right: UUID) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        if self._size[left_root] < self._size[right_root]:
            left_root, right_root = right_root, left_root
        self._parent[right_root] = left_root
        self._size[left_root] += self._size[right_root]


def cluster_topics(
    topics: Sequence[TopicForThreading],
    *,
    vectors: Mapping[UUID, Vector],
    threshold: float,
) -> tuple[ThreadCluster, ...]:
    """Partition topics into threads. Pure — no database, no model, no clock.

    Pair generation is O(n²) in the number of topics. At corpus scale — a few
    hundred meetings with a handful of topics each — that is a few hundred
    thousand dot products over short vectors, which is cheaper than the round
    trip that fetched the rows. It is written plainly rather than indexed
    because an approximate-neighbour index would make the partition depend on
    the index's recall, and the acceptance criteria ask for a partition that
    depends only on the topics.
    """
    if not topics:
        return ()
    by_id = {topic.id: topic for topic in topics}
    if len(by_id) != len(topics):
        raise ThreadDerivationError(
            "the same topic id was supplied twice — a topic belongs to exactly"
            " one thread, so a duplicated input would make the partition"
            " ambiguous"
        )
    missing = sorted(str(topic.id) for topic in topics if topic.id not in vectors)
    if missing:
        raise ThreadDerivationError(
            f"no embedding was produced for {len(missing)} topic(s):"
            f" {', '.join(missing)} — every topic is embedded in one pass, so"
            " a gap here would silently drop the similarity leg for them"
        )

    sets = _DisjointSet([topic.id for topic in topics])

    # The name leg. An empty normalized name (a topic whose name is entirely
    # punctuation) is deliberately excluded: it has no name to match on, and
    # treating "" as a shared name would union every such topic into one
    # thread on the strength of having no name.
    by_normalized: dict[str, list[UUID]] = {}
    for topic in topics:
        if topic.normalized_name:
            by_normalized.setdefault(topic.normalized_name, []).append(topic.id)
    for same_name in by_normalized.values():
        for other in same_name[1:]:
            sets.union(same_name[0], other)

    # The embedding leg, plus the per-pair scores the membership rows record.
    similarities: dict[tuple[UUID, UUID], float] = {}
    ordered = sorted(topics, key=lambda topic: topic.order_key)
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            score = cosine_similarity(vectors[left.id], vectors[right.id])
            similarities[(left.id, right.id)] = score
            similarities[(right.id, left.id)] = score
            if score >= threshold:
                sets.union(left.id, right.id)

    grouped: dict[UUID, list[TopicForThreading]] = {}
    for topic in ordered:
        grouped.setdefault(sets.find(topic.id), []).append(topic)

    clusters: list[ThreadCluster] = []
    for members in grouped.values():
        seed = min(members, key=lambda topic: topic.order_key)
        clusters.append(
            ThreadCluster(
                identity_key=_identity_key(seed),
                name=seed.name,
                seed_topic_id=seed.id,
                members=tuple(
                    _member(topic, seed=seed, members=members, similarities=similarities)
                    for topic in sorted(members, key=lambda topic: topic.order_key)
                ),
            )
        )
    clusters.sort(key=lambda cluster: cluster.identity_key)
    _assert_keys_are_unique(clusters)
    return tuple(clusters)


def _identity_key(seed: TopicForThreading) -> str:
    """What a rerun lands on. Non-empty and collision-free by construction.

    Normally the seed's normalized name. A topic whose name carries no
    alphanumeric character normalizes to the empty string, which is no key at
    all, so such a cluster is keyed on its seed's own id instead. The two forms
    cannot collide: normalization strips ``:``, so no normalized name can look
    like ``topic:<uuid>``.
    """
    return seed.normalized_name or f"topic:{seed.id}"


def _member(
    topic: TopicForThreading,
    *,
    seed: TopicForThreading,
    members: Sequence[TopicForThreading],
    similarities: Mapping[tuple[UUID, UUID], float],
) -> ThreadMember:
    """Which leg is recorded as having carried this topic into the thread.

    Order-independent by construction, which matters because ``linked_by`` is
    stored: "did it share a name with any other member" is a property of the
    finished cluster, not of which pair the union-find happened to process
    first. Only when it shares its name with nobody is the embedding leg
    credited, and then with the strongest score to any other member — the
    score that is at least the threshold, since that is how it got in.
    """
    if topic.id == seed.id:
        return ThreadMember(topic_id=topic.id, linked_by=SEED, similarity=None)
    shares_name = any(
        other.id != topic.id
        and topic.normalized_name
        and other.normalized_name == topic.normalized_name
        for other in members
    )
    if shares_name:
        return ThreadMember(topic_id=topic.id, linked_by=NAME_LINK, similarity=None)
    best = max(
        similarities[(topic.id, other.id)] for other in members if other.id != topic.id
    )
    return ThreadMember(topic_id=topic.id, linked_by=EMBEDDING_LINK, similarity=best)


def _assert_keys_are_unique(clusters: Sequence[ThreadCluster]) -> None:
    """A guard on the argument that seeds cannot collide.

    ``thread.identity_key`` is UNIQUE, so a collision would surface as a
    constraint violation halfway through a write. Checked here, where the
    message can say what actually happened, rather than left to Postgres.
    """
    seen: dict[str, UUID] = {}
    for cluster in clusters:
        previous = seen.get(cluster.identity_key)
        if previous is not None:
            raise ThreadDerivationError(
                f"two clusters both claim identity key {cluster.identity_key!r}"
                f" (seed topics {previous} and {cluster.seed_topic_id}) — every"
                " topic sharing a normalized name should already be in one"
                " cluster, so this is a partitioning bug"
            )
        seen[cluster.identity_key] = cluster.seed_topic_id


# --- the Postgres half -----------------------------------------------------


def read_topics_for_threading(conn: Connection) -> tuple[TopicForThreading, ...]:
    """Every stored topic, corpus-wide, in the derivation's total order.

    Corpus-wide rather than per-meeting because a thread is by definition
    cross-meeting: a per-meeting pass could not see the earlier topic that
    should seed the thread, and its answer would depend on ingest order.
    """
    return tuple(
        TopicForThreading(id=row[0], meeting_id=row[1], name=row[2], meeting_started_at=row[3])
        for row in conn.execute(
            "SELECT t.id, t.meeting_id, t.name, m.started_at"
            " FROM topic t JOIN meeting m ON m.id = t.meeting_id"
            " ORDER BY m.started_at, m.id, t.name, t.id"
        ).fetchall()
    )


def embed_topic_names(
    embedder: Embedder, topics: Sequence[TopicForThreading]
) -> dict[UUID, Vector]:
    """One vector per topic, embedding each distinct name exactly once.

    Distinct *name* rather than distinct topic: two topics with identical names
    are already unioned by the name leg, so embedding both would spend two
    model calls to learn that a string is similar to itself.
    """
    distinct = sorted({topic.name for topic in topics})
    if not distinct:
        return {}
    vectors = embedder.embed_documents(distinct)
    if len(vectors) != len(distinct):
        raise ThreadDerivationError(
            f"the embedder returned {len(vectors)} vectors for"
            f" {len(distinct)} topic names — the port's contract is one vector"
            " per input, in input order"
        )
    by_name = dict(zip(distinct, vectors))
    return {topic.id: by_name[topic.name] for topic in topics}


def derive_threads(
    conn: Connection,
    config: AppConfig,
    *,
    embedder: Embedder,
    log: Callable[..., None] | None = None,
) -> ThreadDerivation:
    """Re-derive every thread from the stored topics. Idempotent by construction.

    Reads, embeds, partitions, then writes — in that order, so an unreachable
    model host raises before a single row is touched. The caller owns the
    transaction: nothing here commits, so a failure anywhere leaves the record
    exactly as it was.

    Threads whose members all move elsewhere are not deleted here. Migration
    0015's row trigger removes a thread when its last membership leaves, which
    keeps the no-orphan invariant true for the extraction rerun and the direct
    ``DELETE`` as well as for this pass.
    """
    emit = log or _noop
    settings = config.settings.threads
    topics = read_topics_for_threading(conn)
    if not topics:
        # No model call at all: an empty corpus has nothing to embed, and
        # asking an unreachable host to embed nothing would turn "there are no
        # topics yet" into an outage.
        emit("threads.derived", threads=0, topics=0)
        return ThreadDerivation(thread_count=0, topic_count=0, name_links=0, embedding_links=0)

    vectors = embed_topic_names(embedder, topics)
    clusters = cluster_topics(
        topics,
        vectors=vectors,
        threshold=settings.embedding_similarity_threshold,
    )
    derivation = {
        "link_rule": settings.link_rule,
        "embedding_similarity_threshold": settings.embedding_similarity_threshold,
        "embedder_model": embedder.model,
        "embedder_dimension": embedder.dimension,
    }

    name_links = 0
    embedding_links = 0
    for cluster in clusters:
        thread_id = _upsert_thread(conn, cluster, link_rule=settings.link_rule, derivation=derivation)
        for member in cluster.members:
            _upsert_membership(conn, member, thread_id=thread_id)
            if member.linked_by == NAME_LINK:
                name_links += 1
            elif member.linked_by == EMBEDDING_LINK:
                embedding_links += 1

    emit(
        "threads.derived",
        threads=len(clusters),
        topics=len(topics),
        name_links=name_links,
        embedding_links=embedding_links,
    )
    return ThreadDerivation(
        thread_count=len(clusters),
        topic_count=len(topics),
        name_links=name_links,
        embedding_links=embedding_links,
    )


def _upsert_thread(
    conn: Connection,
    cluster: ThreadCluster,
    *,
    link_rule: str,
    derivation: dict[str, object],
) -> UUID:
    """Insert or update one thread by ``identity_key``, returning its id.

    The ``WHERE`` on the conflict clause is what makes an unchanged rerun a
    true no-op: without it every pass would fire ``set_updated_at`` on every
    thread, and "the derivation changed nothing" would be unobservable. The
    cost is one extra SELECT in exactly the case where nothing was written.
    """
    row = conn.execute(
        "INSERT INTO thread (identity_key, name, link_rule, derivation)"
        " VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (identity_key) DO UPDATE"
        " SET name = EXCLUDED.name, link_rule = EXCLUDED.link_rule,"
        "     derivation = EXCLUDED.derivation"
        " WHERE thread.name IS DISTINCT FROM EXCLUDED.name"
        "    OR thread.link_rule IS DISTINCT FROM EXCLUDED.link_rule"
        "    OR thread.derivation IS DISTINCT FROM EXCLUDED.derivation"
        " RETURNING id",
        (cluster.identity_key, cluster.name, link_rule, Jsonb(derivation)),
    ).fetchone()
    if row is not None:
        return row[0]
    unchanged = conn.execute(
        "SELECT id FROM thread WHERE identity_key = %s", (cluster.identity_key,)
    ).fetchone()
    if unchanged is None:
        raise ThreadDerivationError(
            f"thread {cluster.identity_key!r} was neither written nor found"
            " after its upsert — another writer removed it mid-derivation"
        )
    return unchanged[0]


def _upsert_membership(conn: Connection, member: ThreadMember, *, thread_id: UUID) -> None:
    """Attach one topic to its thread, moving it if it was somewhere else.

    ``topic_thread.topic_id`` is the primary key, so a move is one statement
    and never a delete-then-insert — which matters because deleting the last
    membership of a thread fires the trigger that removes the thread, and a
    delete-then-insert pass would destroy and re-mint every thread it touched.
    """
    conn.execute(
        "INSERT INTO topic_thread (topic_id, thread_id, linked_by, similarity)"
        " VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (topic_id) DO UPDATE"
        " SET thread_id = EXCLUDED.thread_id, linked_by = EXCLUDED.linked_by,"
        "     similarity = EXCLUDED.similarity"
        " WHERE topic_thread.thread_id IS DISTINCT FROM EXCLUDED.thread_id"
        "    OR topic_thread.linked_by IS DISTINCT FROM EXCLUDED.linked_by"
        "    OR topic_thread.similarity IS DISTINCT FROM EXCLUDED.similarity",
        (member.topic_id, thread_id, member.linked_by, member.similarity),
    )


def _noop(*_args: object, **_kwargs: object) -> None:
    return None
