"""Ollama-backed `Embedder`: the one place an embedding provider is spoken to.

Ollama runs as a macOS host process (AD-9) and exposes ``POST /api/embed``,
which takes ``{"model": ..., "input": [...]}`` and answers
``{"embeddings": [[...], ...]}`` in input order.

Deliberately the standard library rather than an SDK. The whole protocol is
one JSON POST, and adding a client dependency to reach it would put a third
HTTP stack in the server for no gain — while `urllib`'s failure taxonomy maps
exactly onto the port's two error types: :class:`URLError` (including a
refused connection and a timeout) is the *unreachable host* case the structural
pass is required to survive, and everything else is a real error.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Sequence

from meetingminer.adapters.embed.port import (
    EmbedderError,
    EmbedderUnavailableError,
    Vector,
    check_dimension,
)

# Long enough for a cold model load on a laptop, short enough that a wedged
# host fails the embedding pass rather than hanging an ingest indefinitely.
_TIMEOUT_SECONDS = 120.0


class OllamaEmbedder:
    """`Embedder` over a locally-served Ollama model."""

    name = "ollama"

    def __init__(self, base_url: str, model: str, dimension: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimension = dimension

    # -- port -------------------------------------------------------------

    def embed_documents(self, texts: Sequence[str]) -> tuple[Vector, ...]:
        if not texts:
            return ()
        vectors = self._embed(list(texts))
        check_dimension(vectors, self.dimension, self.model)
        try:
            return tuple(
                tuple(float(value) for value in vector) for vector in vectors
            )
        except (TypeError, ValueError) as exc:
            # A bare ValueError escaping here would reach the projection
            # module as an unclassified exception and fail the whole
            # projection rather than the embedding pass. Every failure this
            # adapter can produce has to be one of the port's two named
            # types, or the structural/embedding split does not hold.
            raise EmbedderError(
                f"embedder {self.model!r} on {self.base_url} returned a vector"
                f" with a non-numeric component: {exc}"
            ) from exc

    def embed_query(self, text: str) -> Vector:
        return self.embed_documents([text])[0]

    # -- transport --------------------------------------------------------

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        payload = json.dumps({"model": self.model, "input": inputs}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            # The host answered — a missing model, a bad request. Not
            # retryable, so it is not the "unavailable" case.
            detail = exc.read().decode("utf-8", errors="replace").strip()
            # 404 is overwhelmingly "that model is not pulled on this host",
            # and it is the one failure an operator can fix in one command —
            # so the message is the command, not a description of the problem.
            # An untagged model id lands here too, because Ollama resolves one
            # to `:latest`.
            remedy = (
                f" — pull it with 'ollama pull {self.model}'" if exc.code == 404 else ""
            )
            raise EmbedderError(
                f"embedder {self.model!r} on {self.base_url} refused the request"
                f" (HTTP {exc.code}): {detail or exc.reason}{remedy}"
            ) from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            raise EmbedderUnavailableError(
                f"embedding model host unreachable at {self.base_url}"
                f" ({exc}) — start Ollama ('ollama serve') and re-run"
                " 'rebuild --embed-only' to fill the vectors"
            ) from exc

        try:
            parsed = json.loads(body)
        except ValueError as exc:
            raise EmbedderError(
                f"embedder {self.model!r} on {self.base_url} returned"
                " a body that is not JSON"
            ) from exc

        embeddings = parsed.get("embeddings") if isinstance(parsed, dict) else None
        if not isinstance(embeddings, list) or len(embeddings) != len(inputs):
            raise EmbedderError(
                f"embedder {self.model!r} on {self.base_url} returned"
                f" {len(embeddings) if isinstance(embeddings, list) else 'no'}"
                f" embeddings for {len(inputs)} inputs"
            )
        for vector in embeddings:
            if not isinstance(vector, list):
                raise EmbedderError(
                    f"embedder {self.model!r} on {self.base_url} returned a"
                    " non-list embedding"
                )
        return embeddings
