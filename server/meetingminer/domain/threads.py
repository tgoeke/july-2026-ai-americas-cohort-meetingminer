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
2. ``identity_key`` comes from cluster content: the lexicographically first
   non-empty normalized name. Chronology selects only the machine display name
   and the membership row labelled ``seed``; an earlier backfill cannot become
   identity merely because of its timestamp.
3. A cluster first reuses the row already named by that content key, then a row
   already attached to one of its topics, before minting. Empty rows survive
   topic replacement, so an unchanged normalized name reclaims the same id.
4. Every UPSERT carries a ``WHERE`` that fires only on an actual change, so an
   unchanged rerun writes nothing at all — not even ``updated_at``.

**Human curation is an input, not a casualty** (story 10.2a). Those four
properties make a rerun reproduce the *machine's* answer, which is exactly why
a human correction cannot be stored as an edit of this module's output: the
next pass would rewrite ``thread.name`` from the seed topic and move the
membership back, and the user would watch their own correction disappear.
``domain/thread_curation.py`` holds the three API-owned tables that record
merges, splits and renames (migration 0021), and :func:`derive_threads` reads
them *before* it writes. A pinned topic is resolved to its pinned thread, and a
thread merged away to its survivor, **before** the membership UPSERT — so each
topic is still written by exactly one statement and property 4 above is
untouched. A rename is not resolved here at all: it lives in a column this
module never writes, so the two cannot collide by construction. A pin this
corpus cannot match is reported rather than dropped (AD-18), and nothing here
ever deletes a curation row.

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

import hashlib
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
from meetingminer.domain.thread_curation import (
    CURATED_LINK_RULE,
    CURATED_SPLIT_PREFIX,
    read_thread_curation,
)

# The machine `topic_thread.linked_by` legs migration 0015 declares. Migration
# 0021 adds `curated`, used when curation rather than a machine leg decided the
# derived membership.
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
        """The total order used for presentation, never durable identity."""
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
    """What one derivation pass produced, for a caller to report.

    The last three counts are the curation half, and they exist so a pass can
    be *read* rather than inferred: how many memberships a human decision
    placed, how many clusters were redirected onto a merge survivor, and — the
    one that matters most — how many recorded corrections this corpus could
    not match. A silently unapplied split and a corpus with no splits are
    otherwise the same observation (AD-18).
    """

    thread_count: int
    topic_count: int
    name_links: int
    embedding_links: int
    # Memberships a `thread_topic_pin` placed, overriding the partition.
    curated_links: int = 0
    # Clusters whose thread was merged away, so their memberships were written
    # to the survivor instead.
    merged_clusters: int = 0
    # Pins whose (meeting, normalized name) matched no topic in this pass. The
    # rows are kept; the subject may return with the next re-extraction.
    unmatched_pins: tuple[tuple[UUID, str], ...] = ()


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


def _assert_finite_vector(vector: Sequence[float], *, label: str) -> None:
    """Refuse a provider vector that cannot participate in real cosine math."""
    for index, value in enumerate(vector):
        try:
            finite = math.isfinite(value)
        except TypeError as exc:
            raise ThreadDerivationError(
                f"{label} has a non-finite or non-numeric component at index"
                f" {index}: {value!r}"
            ) from exc
        if not finite:
            raise ThreadDerivationError(
                f"{label} has a non-finite component at index {index}: {value!r}"
            )


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
    _assert_finite_vector(left, label="left vector")
    _assert_finite_vector(right, label="right vector")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not math.isfinite(left_norm) or not math.isfinite(right_norm):
        raise ThreadDerivationError(
            "cannot compare vectors whose norm is non-finite — the embedder"
            " returned components too large for cosine similarity"
        )
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def _normalized_vectors(
    topics: Sequence[TopicForThreading], vectors: Mapping[UUID, Vector]
) -> dict[UUID, Vector]:
    """Unit vectors for one derivation, with each norm computed exactly once.

    All-pairs comparison is required for an exact partition, but repeating two
    O(d) norms for every pair is not. A zero vector remains zero and therefore
    has dot similarity 0.0 with every other vector, matching
    :func:`cosine_similarity`.
    """
    expected_width = len(vectors[topics[0].id])
    normalized: dict[UUID, Vector] = {}
    for topic in topics:
        vector = vectors[topic.id]
        if len(vector) != expected_width:
            raise ThreadDerivationError(
                f"cannot compare a {expected_width}-dimension vector with a"
                f" {len(vector)}-dimension one — every topic name is embedded"
                " by the same model in one pass, so a width mismatch is a bug"
                " here, not a model response"
            )
        _assert_finite_vector(vector, label=f"embedding for topic {topic.id}")
        norm = math.sqrt(sum(value * value for value in vector))
        if not math.isfinite(norm):
            raise ThreadDerivationError(
                f"embedding for topic {topic.id} has a non-finite norm — its"
                " components are too large for cosine similarity"
            )
        normalized[topic.id] = (
            tuple(value / norm for value in vector)
            if norm != 0.0
            else tuple(0.0 for _ in vector)
        )
    return normalized


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

    Pair generation is O(n²) in the number of topics because an approximate
    neighbour index would make the partition depend on index recall. The
    implementation still normalizes each vector only once and retains only
    each topic's best qualifying similarity: exact all-pairs semantics do not
    require O(n²) norm work or score storage.
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

    # The embedding leg. A non-name member needs only its strongest qualifying
    # score for the membership row. Any score below threshold cannot be that
    # maximum because the topic necessarily has at least one qualifying edge
    # to have joined the final cluster by embedding.
    normalized_vectors = _normalized_vectors(topics, vectors)
    best_similarities: dict[UUID, float] = {}
    ordered = sorted(topics, key=lambda topic: topic.order_key)
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            score = max(
                -1.0,
                min(
                    1.0,
                    math.sumprod(
                        normalized_vectors[left.id], normalized_vectors[right.id]
                    ),
                ),
            )
            if score >= threshold:
                sets.union(left.id, right.id)
                best_similarities[left.id] = max(best_similarities.get(left.id, score), score)
                best_similarities[right.id] = max(
                    best_similarities.get(right.id, score), score
                )

    grouped: dict[UUID, list[TopicForThreading]] = {}
    for topic in ordered:
        grouped.setdefault(sets.find(topic.id), []).append(topic)

    clusters: list[ThreadCluster] = []
    for members in grouped.values():
        seed = min(members, key=lambda topic: topic.order_key)
        clusters.append(
            ThreadCluster(
                identity_key=_identity_key(members),
                name=seed.name,
                seed_topic_id=seed.id,
                members=tuple(
                    _member(
                        topic,
                        seed=seed,
                        members=members,
                        best_similarities=best_similarities,
                    )
                    for topic in sorted(members, key=lambda topic: topic.order_key)
                ),
            )
        )
    clusters.sort(key=lambda cluster: cluster.identity_key)
    _assert_keys_are_unique(clusters)
    return tuple(clusters)


def _identity_key(members: Sequence[TopicForThreading]) -> str:
    """The cluster's canonical content key, independent of chronology.

    The ordinary form is one of the cluster's normalized names. Equal names
    are already unioned, so two live clusters cannot claim the same key. A
    punctuation-only cluster has no non-empty normalized name; its fallback is
    a bounded digest of normalized raw name content rather than a topic UUID,
    so Story 10.1 replacing the row does not replace the thread identity.
    """
    normalized_names = sorted(
        {topic.normalized_name for topic in members if topic.normalized_name}
    )
    if normalized_names:
        return normalized_names[0]
    raw_names = sorted(
        unicodedata.normalize("NFKC", topic.name).casefold() for topic in members
    )
    digest = hashlib.sha256(raw_names[0].encode("utf-8")).hexdigest()
    return f"topic-name-sha256:{digest}"


def _member(
    topic: TopicForThreading,
    *,
    seed: TopicForThreading,
    members: Sequence[TopicForThreading],
    best_similarities: Mapping[UUID, float],
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
    best = best_similarities.get(topic.id)
    if best is None:
        raise ThreadDerivationError(
            f"topic {topic.id} belongs to a multi-topic cluster but has neither"
            " a shared normalized name nor a qualifying embedding edge — the"
            " partition and its membership evidence disagree"
        )
    return ThreadMember(topic_id=topic.id, linked_by=EMBEDDING_LINK, similarity=best)


def _assert_keys_are_unique(clusters: Sequence[ThreadCluster]) -> None:
    """A guard on the argument that content keys cannot collide.

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
                f" (presentation topics {previous} and {cluster.seed_topic_id})"
                " — every topic sharing normalized content should already be"
                " in one cluster, so this is a partitioning bug"
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

    Threads whose members disappear or move elsewhere are retained as empty
    identity rows. Story 10.1 replaces a meeting's topics wholesale, so
    membership cannot be the condition for identity lifetime; the next pass
    reuses a matching content key, and a future explicit sweep may remove rows
    proven genuinely dead.

    Human curation (story 10.2a) is read here and applied as the membership is
    written, never afterwards — see the module docstring. This function still
    writes only `thread` and `topic_thread`; it never writes, deletes or
    repairs a curation row, which is what keeps AD-5's ownership split real
    rather than nominal.
    """
    emit = log or _noop
    settings = config.settings.threads
    topics = read_topics_for_threading(conn)
    curation = read_thread_curation(conn)
    if not topics:
        # No model call at all: an empty corpus has nothing to embed, and
        # asking an unreachable host to embed nothing would turn "there are no
        # topics yet" into an outage. Curation is still reported: every pin on
        # record is unmatched when there are no topics, and saying so is the
        # difference between "nothing to do" and "your corrections did not
        # apply" (AD-18).
        unmatched = curation.unmatched_pins(())
        emit("threads.derived", threads=0, topics=0, unmatched_pins=len(unmatched))
        return ThreadDerivation(
            thread_count=0,
            topic_count=0,
            name_links=0,
            embedding_links=0,
            unmatched_pins=unmatched,
        )

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
    curated_links = 0
    merged_clusters = 0
    topic_by_id = {topic.id: topic for topic in topics}
    reserved_by_key = _threads_by_identity_key(conn, clusters)
    claimed_thread_ids = set(reserved_by_key.values())
    for cluster in clusters:
        existing = reserved_by_key.get(cluster.identity_key)
        if existing is None:
            existing = _attached_thread_to_reuse(
                conn, cluster, unavailable=claimed_thread_ids
            )
        thread_id = _upsert_thread(
            conn,
            cluster,
            link_rule=settings.link_rule,
            derivation=derivation,
            existing_thread_id=existing,
        )
        claimed_thread_ids.add(thread_id)
        # The cluster's own row keeps its identity, its name and its colour
        # even when it has been merged away: a merge moves *memberships*, so
        # the absorbed row stays as the durable identity a later unmerge or a
        # later rerun can still find, and `color_ordinal` is never touched by
        # either side (migration 0017's immutability trigger would refuse it).
        if curation.follow_alias(thread_id) != thread_id:
            merged_clusters += 1
        for member in cluster.members:
            topic = topic_by_id[member.topic_id]
            target, pinned = curation.thread_for(
                meeting_id=topic.meeting_id,
                normalized_name=topic.normalized_name,
                derived_thread_id=thread_id,
            )
            _upsert_membership(conn, member, thread_id=target, curated=pinned)
            if pinned:
                curated_links += 1
            elif member.linked_by == NAME_LINK:
                name_links += 1
            elif member.linked_by == EMBEDDING_LINK:
                embedding_links += 1

    # Every subject this pass could see, in the pin's own key space, so an
    # unmatched pin is decided against the corpus rather than against whichever
    # clusters happened to form.
    present = {(topic.meeting_id, topic.normalized_name) for topic in topics}
    unmatched = curation.unmatched_pins(present)
    stale_hints = curation.stale_hints(
        {(topic.meeting_id, topic.normalized_name): topic.id for topic in topics}
    )

    emit(
        "threads.derived",
        threads=len(clusters),
        topics=len(topics),
        name_links=name_links,
        embedding_links=embedding_links,
        curated_links=curated_links,
        merged_clusters=merged_clusters,
        unmatched_pins=len(unmatched),
        stale_pin_hints=stale_hints,
    )
    if unmatched:
        # A separate event, not a field on the one above, because this is the
        # sentence an operator has to be able to find: a human correction is on
        # record and did not apply to this corpus. Each key is named — a count
        # alone would not say *which* split is waiting for its subject to come
        # back (AD-18).
        emit(
            "threads.curation_unmatched",
            pins=len(unmatched),
            keys=[f"{meeting_id}:{name}" for meeting_id, name in unmatched],
        )
    return ThreadDerivation(
        thread_count=len(clusters),
        topic_count=len(topics),
        name_links=name_links,
        embedding_links=embedding_links,
        curated_links=curated_links,
        merged_clusters=merged_clusters,
        unmatched_pins=unmatched,
    )


def _upsert_thread(
    conn: Connection,
    cluster: ThreadCluster,
    *,
    link_rule: str,
    derivation: dict[str, object],
    existing_thread_id: UUID | None,
) -> UUID:
    """Insert or update one thread by ``identity_key``, returning its id.

    The ``WHERE`` on the conflict clause is what makes an unchanged rerun a
    true no-op: without it every pass would fire ``set_updated_at`` on every
    thread, and "the derivation changed nothing" would be unobservable. The
    cost is one extra SELECT in exactly the case where nothing was written.
    """
    if existing_thread_id is not None:
        row = conn.execute(
            "UPDATE thread"
            " SET identity_key = %s, name = %s, link_rule = %s, derivation = %s"
            " WHERE id = %s"
            "   AND (identity_key IS DISTINCT FROM %s"
            "        OR name IS DISTINCT FROM %s"
            "        OR link_rule IS DISTINCT FROM %s"
            "        OR derivation IS DISTINCT FROM %s)"
            " RETURNING id",
            (
                cluster.identity_key,
                cluster.name,
                link_rule,
                Jsonb(derivation),
                existing_thread_id,
                cluster.identity_key,
                cluster.name,
                link_rule,
                Jsonb(derivation),
            ),
        ).fetchone()
        return row[0] if row is not None else existing_thread_id

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


def _threads_by_identity_key(
    conn: Connection, clusters: Sequence[ThreadCluster]
) -> dict[str, UUID]:
    """Reserve exact content-key rows before any cluster claims an old row."""
    keys = [cluster.identity_key for cluster in clusters]
    return {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT identity_key, id FROM thread WHERE identity_key = ANY(%s)",
            (keys,),
        ).fetchall()
    }


def _attached_thread_to_reuse(
    conn: Connection,
    cluster: ThreadCluster,
    *,
    unavailable: set[UUID],
) -> UUID | None:
    """Choose an unclaimed prior row attached to a cluster member.

    Exact content-key rows have already been reserved for their own clusters.
    The remaining ordered choice preserves identity across a backfill without
    allowing two products of a split to collapse back onto the same row.

    **A thread minted by a split is never a reuse target** (story 10.2a). This
    is the subtle way a rerun could undo a curation, and it is subtle precisely
    because attachment is the mechanism that normally *preserves* identity: a
    curated thread is attached to the very topics that were split onto it, so
    without this filter the cluster the split was correcting would claim the
    curated row here, and `_upsert_thread` would then overwrite its
    `identity_key` and its name with the machine's — quietly reversing the
    correction while reporting a successful pass. The key space makes the test
    exact rather than heuristic (`domain/thread_curation.py`): a derived key is
    a normalized name, which `normalized_topic_name` reduces to alphanumerics
    and single spaces, or the literal prefix `topic-name-sha256:`. Neither can
    begin with the curated prefix.

    A cluster whose every member is pinned away therefore mints a fresh row on
    the pass after a split and reuses it by content key on every pass after
    that. The row is left with no memberships, which is the state migration
    0015 already retains deliberately, and it is invisible to `GET /threads`
    because that route joins membership.
    """
    members = [member.topic_id for member in cluster.members]
    attached = conn.execute(
        "SELECT DISTINCT th.id, th.identity_key"
        " FROM topic_thread tt JOIN thread th ON th.id = tt.thread_id"
        " WHERE tt.topic_id = ANY(%s)"
        " AND NOT starts_with(th.identity_key, %s)"
        " ORDER BY th.identity_key, th.id",
        (members, CURATED_SPLIT_PREFIX),
    ).fetchall()
    return next((row[0] for row in attached if row[0] not in unavailable), None)


def _upsert_membership(
    conn: Connection, member: ThreadMember, *, thread_id: UUID, curated: bool = False
) -> None:
    """Attach one topic to its thread, moving it if it was somewhere else.

    ``topic_thread.topic_id`` is the primary key, so a move is one statement
    and never a delete-then-insert. Empty thread rows intentionally survive,
    because Story 10.1 may remove and recreate every topic in the meeting
    before this derivation has a chance to reattach the replacement rows.
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
        (
            member.topic_id,
            thread_id,
            CURATED_LINK_RULE if curated else member.linked_by,
            None if curated else member.similarity,
        ),
    )


def _noop(*_args: object, **_kwargs: object) -> None:
    return None
