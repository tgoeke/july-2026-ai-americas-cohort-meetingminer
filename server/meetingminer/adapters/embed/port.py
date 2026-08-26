"""The `Embedder` port: what feature code is allowed to know about vectors (AD-8).

Nothing in this module imports a provider SDK. The projections module depends
on :class:`Embedder` and calls :meth:`embed_documents` / :meth:`embed_query`;
which model answers is decided by ``config.yaml`` in
:mod:`meetingminer.adapters.embed` and nowhere else.

Two error types, and the distinction between them is load-bearing rather than
cosmetic. :class:`EmbedderUnavailableError` means *the host was not reachable*
— the single failure the projection module is required to survive
(`retrieval-prior-art.md` §3 rule 4: structural indexing must work with the
model host off). :class:`EmbedderError` covers everything else: a model that
answered with the wrong width, a malformed response. The first leaves a
structurally-projected meeting that a later pass finishes; the second is a
misconfiguration that no retry fixes.
"""

from __future__ import annotations

from typing import Protocol, Sequence

# The vector shape every caller sees: a tuple of tuples of floats, one per
# input text, in input order. Tuples rather than lists because a vector is a
# value — nothing downstream may mutate what the port handed back.
Vector = tuple[float, ...]


class EmbedderError(RuntimeError):
    """The configured embedder answered, but not usably.

    A wrong-width vector, an unparseable response, a model the host does not
    have. Retrying does not fix any of these, so the projection module treats
    it as a failure of the embedding pass rather than as a transient outage.
    """


class EmbedderUnavailableError(EmbedderError):
    """The model host could not be reached — retryable, and expected.

    Ollama runs as a host process (AD-9) and is legitimately not running.
    `retrieval-prior-art.md` §3 rule 4 makes surviving this a requirement:
    the structural pass never calls the port at all, so a meeting still gets
    its nodes and its BM25-searchable documents, `meeting_projection.embedded_at`
    stays NULL, and `rebuild --embed-only` resumes it later.
    """


class Embedder(Protocol):
    """What every embedding engine implements and every caller may rely on.

    ``model`` and ``dimension`` are part of the contract because they are
    persisted: `meeting_projection` records which model wrote a meeting's
    vectors and at what width, so a swap is caught as a named refusal instead
    of silently producing garbage neighbours (§3 rule 3, AD-8).
    """

    model: str
    dimension: int

    def embed_documents(self, texts: Sequence[str]) -> tuple[Vector, ...]:
        """Embed a batch of passages, returning one vector per input in order.

        Raises :class:`EmbedderUnavailableError` when the host is unreachable
        and :class:`EmbedderError` for any other failure, including a vector
        whose width is not :attr:`dimension`.
        """
        ...

    def embed_query(self, text: str) -> Vector:
        """Embed one query string.

        A separate method rather than a one-element ``embed_documents`` call
        because several embedding models take different query and document
        prompts. The bake-off measured the officially-documented prompt pair
        as *worse* than naive usage on this corpus
        (`retrieval-prior-art.md` §7 finding 3), so this build sends neither —
        but the seam has to exist for that to remain a measured decision
        rather than an assumption baked into one call site.
        """
        ...


def check_dimension(vectors: Sequence[Sequence[float]], expected: int, model: str) -> None:
    """Raise :class:`EmbedderError` if any vector is not ``expected`` wide.

    Checked in the adapter, not at the call site: embedding width is baked
    into the search index, and a single wrong-width vector poisons it. The
    error names the model and both widths so the fix (config.yaml's
    ``embedder.dimension``, then a full rebuild) is obvious from the message.
    """
    for index, vector in enumerate(vectors):
        if len(vector) != expected:
            raise EmbedderError(
                f"embedder {model!r} returned a {len(vector)}-dimension vector"
                f" for input {index}, but config.yaml declares"
                f" embedder.dimension {expected} — fix the dimension to match"
                " the model and rebuild the projections (AD-8)"
            )
