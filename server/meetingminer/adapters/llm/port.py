"""The `Llm` port: what feature code is allowed to know about completions (AD-8).

Nothing in this module imports a provider SDK. The `extract` stage depends on
:class:`Llm` and calls :meth:`complete`; which model answers is decided by
``config.yaml``'s ``llm.roles.*`` in :mod:`meetingminer.adapters.llm` and
nowhere else.

Two error types, mirroring `embed/port.py`, and the distinction is a contract
rather than cosmetics. :class:`LlmUnavailableError` means *the model host was
not answering* — unreachable, timing out, refusing the credentials — the
failure the role's configured fallback exists to absorb. :class:`LlmError`
covers everything else the provider can do wrong. The fallback composer
engages on either (a primary that cannot answer is a primary that cannot
answer), but a caller that wants to say *why* it substituted can tell the two
apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LlmError(RuntimeError):
    """The configured completer could not produce a usable reply."""


class LlmUnavailableError(LlmError):
    """The model host could not be reached or would not serve the request.

    Network failures, timeouts, and authentication refusals land here: all
    three are "this completer cannot answer right now", which is exactly the
    condition the configured fallback model exists to cover.
    """


class LlmModelNotServedError(LlmError):
    """The provider answered, and does not have the model this binding names.

    A *configuration* failure, not an outage, and the distinction decides
    whether another model may answer. A host that is down cannot serve
    anything, so substituting the role's fallback is the deliberate cover for
    it. A host that is up and does not have *this* model will answer the same
    way forever, and quietly returning a different model's completion is the
    silent fallback this project has rejected by owner decision (story 8.2's
    third acceptance clause; backlog B-38).

    It therefore subclasses :class:`LlmError` -- so every caller that already
    maps the port's failures to a named error keeps working -- while
    :class:`~meetingminer.adapters.llm.FallbackLlm` re-raises it ahead of the
    ``except LlmError`` that engages the substitute.

    The four fields are what make the failure actionable without a log viewer:
    which provider was called, at which endpoint, for which model, and what
    the upstream said. ``api_base`` is ``None`` when no ``providers:`` entry
    matched and the SDK used its own default endpoint for that provider.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        model: str,
        api_base: str | None,
        upstream_status: int | None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.api_base = api_base
        self.upstream_status = upstream_status


@dataclass(frozen=True)
class LlmOptions:
    """Per-call knobs a caller may set without naming a provider or an SDK.

    The port is the only place model interaction is expressed (AD-8), so a
    setting the caller genuinely needs has to travel through it rather than be
    smuggled past it. Both fields are ``None`` by default, meaning "whatever
    the binding configured"; a set value overrides the binding for that call.

    ``num_ctx`` is the Ollama context window. It is a correctness setting: the
    default context silently truncates a long transcript, and a truncated
    transcript produces fewer artifacts while reporting success. An engine that
    has no such concept ignores it — see the adapter, which forwards it only to
    ``ollama/``-prefixed models so no other provider is handed a parameter it
    does not know.
    """

    num_ctx: int | None = None
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class LlmReply:
    """One completion, plus the provenance every artifact row records.

    ``model`` is the model that *actually* answered — under fallback that is
    the fallback's model string, not the configured primary's — and
    ``fallback_engaged`` says whether the reply came from the substitute.
    """

    text: str
    model: str
    fallback_engaged: bool = False


class Llm(Protocol):
    """What every completion engine implements and every caller may rely on."""

    def complete(self, prompt: str, options: LlmOptions | None = None) -> LlmReply:
        """Complete one prompt, optionally overriding the binding's call knobs.

        Raises :class:`LlmUnavailableError` when the host cannot be reached
        (or refuses to serve) and :class:`LlmError` for any other failure.
        """
        ...
