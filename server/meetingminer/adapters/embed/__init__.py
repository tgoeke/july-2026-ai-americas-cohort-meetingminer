"""The `Embedder` binding: the one place an embedding model is named (AD-8, AD-10).

Feature code calls :func:`build_embedder` with an :class:`AppConfig` and gets
back something satisfying the
:class:`~meetingminer.adapters.embed.port.Embedder` protocol. The model comes
from ``config.yaml``'s ``embedder.model``, its width from
``embedder.dimension``, and the host from ``providers.ollama.base_url`` —
nowhere else.

There is deliberately **no fallback key**, unlike the `Ocr` binding. AD-8
makes the embedder the one port whose binding is *projection state*: its model
and dimension are recorded per projected meeting, and a swap forces a full
rebuild. A silent substitute would put two vector spaces in one index, which is
exactly the failure `retrieval-prior-art.md` §3 rule 3 exists to prevent.
"""

from __future__ import annotations

from typing import Callable

from meetingminer.adapters.embed.ollama import OllamaEmbedder
from meetingminer.adapters.embed.port import (
    Embedder,
    EmbedderError,
    EmbedderUnavailableError,
    Vector,
    check_dimension,
)
from meetingminer.config import AppConfig

__all__ = [
    "Embedder",
    "EmbedderError",
    "EmbedderUnavailableError",
    "OllamaEmbedder",
    "Vector",
    "build_embedder",
    "check_dimension",
]

# The provider that serves the embedding model. A second provider would be a
# second entry here plus a way to name it in config.yaml; today every local
# embedding model in this project is served by Ollama.
_PROVIDER = "ollama"


def build_embedder(
    config: AppConfig, log: Callable[..., None] | None = None
) -> Embedder:
    """Construct the configured embedder, or raise :class:`EmbedderError`.

    Raises rather than returning ``None`` for a missing provider endpoint: an
    embedder that cannot be *constructed* is a config error, distinct from one
    whose host is merely down — that second case surfaces from the port as
    :class:`EmbedderUnavailableError` on the first call, which is the case the
    structural/embedding split is built to survive.
    """
    embedder_config = config.settings.embedder
    provider = config.settings.providers.get(_PROVIDER)
    if provider is None:
        raise EmbedderError(
            f"config.yaml declares embedder.model {embedder_config.model!r} but"
            f" has no providers.{_PROVIDER} endpoint to serve it"
        )
    if log is not None:
        log(
            "embedder.bound",
            provider=_PROVIDER,
            model=embedder_config.model,
            dimension=embedder_config.dimension,
        )
    return OllamaEmbedder(
        base_url=provider.base_url,
        model=embedder_config.model,
        dimension=embedder_config.dimension,
    )
