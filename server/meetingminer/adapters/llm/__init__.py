"""The `Llm` binding: the one place a completion model is named (AD-8, AD-10).

Feature code calls :func:`build_llm` with a role binding from ``config.yaml``
(``llm.roles.extraction`` and friends) plus the ``providers`` map, and gets
back something satisfying the :class:`~meetingminer.adapters.llm.port.Llm`
protocol. Which models those are comes from ``config.yaml`` and nothing else,
so swapping ``claude-sonnet-5`` for another model changes no file outside this
package.

The fallback engages **at call time, not bind time** — unlike the `Ocr`
binding, whose fallback is a host capability discoverable up front. LLM
unavailability is a network fact discovered on the first failing call. Once
engaged, the fallback serves every subsequent call this instance takes:
flip-flopping mid-meeting would mix two models' judgments in one artifact set,
and one instance serves one meeting (the stage builds it per run).
"""

from __future__ import annotations

from typing import Callable, Mapping, Protocol

from meetingminer.adapters.llm.litellm import LiteLlmCompleter, ProviderBinding
from meetingminer.adapters.llm.port import (
    Llm,
    LlmError,
    LlmOptions,
    LlmReply,
    LlmUnavailableError,
)

__all__ = [
    "FallbackLlm",
    "LiteLlmCompleter",
    "Llm",
    "LlmError",
    "LlmOptions",
    "LlmReply",
    "LlmUnavailableError",
    "build_llm",
]


class RoleBinding(Protocol):
    """Structural stand-in for :class:`meetingminer.config.LlmRoleBinding`.

    Typed structurally rather than by import: this package stays free of
    project imports other than its own port, which is what keeps the engines
    substitutable and the dependency direction one-way.
    """

    model: str
    fallback: str | None
    # The role's own call settings (`config.yaml` `llm.roles.<role>`). All
    # three are optional in the config and arrive as ``None`` when unset;
    # they are declared here because a binding that cannot answer for them is
    # not a role binding, and a silent default would hide a truncated context.
    base_url: str | None
    fallback_base_url: str | None
    timeout_seconds: float | None
    num_ctx: int | None


class FallbackLlm:
    """Primary first; on any `LlmError` from it, the fallback takes over.

    The substitution is logged exactly once, and every reply produced after it
    carries ``fallback_engaged=True`` so artifact provenance records which
    calls the substitute answered. Both models failing raises with both errors
    named — the caller (the `extract` stage) records that as a stage failure
    an operator can act on.
    """

    def __init__(
        self,
        primary: Llm,
        fallback: Llm | None,
        log: Callable[..., None] | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self._log = log
        self._engaged = False
        self._primary_error: LlmError | None = None

    def complete(self, prompt: str, options: LlmOptions | None = None) -> LlmReply:
        if not self._engaged:
            try:
                return self.primary.complete(prompt, options)
            except LlmError as exc:
                if self.fallback is None:
                    raise
                self._engaged = True
                self._primary_error = exc
                if self._log is not None:
                    self._log(
                        "llm.fallback_engaged",
                        primary=getattr(self.primary, "model", None),
                        fallback=getattr(self.fallback, "model", None),
                        error=str(exc),
                    )
        assert self.fallback is not None  # engaged only when one exists
        try:
            reply = self.fallback.complete(prompt, options)
        except LlmError as exc:
            raise LlmError(
                "primary and fallback models both failed —"
                f" primary: {self._primary_error}; fallback: {exc}"
            ) from exc
        return LlmReply(text=reply.text, model=reply.model, fallback_engaged=True)


def build_llm(
    role_binding: RoleBinding,
    providers: Mapping[str, ProviderBinding],
    log: Callable[..., None] | None = None,
) -> Llm:
    """Construct the configured role's completer, fallback composition included.

    Construction never touches a provider: an unreachable host surfaces from
    the port as :class:`LlmUnavailableError` on the first call, which is where
    the composer engages the fallback.
    """
    # The role's request settings reach the primary and the fallback alike: a
    # fallback answering with a truncated context, or giving up at a timeout
    # the role has already declared too short, would be a second undeclared
    # binding nothing in `config.yaml` describes.
    request_settings = {
        "timeout_seconds": role_binding.timeout_seconds,
        "num_ctx": role_binding.num_ctx,
    }
    # The *endpoint* is not shared, and that asymmetry is deliberate. The
    # fallback is a different model, and nothing establishes that the primary's
    # host serves it — pointing it there would make the fallback dead on the
    # first call the primary misses, leaving "both models failed" as the only
    # outcome. Absent an explicit `fallback_base_url`, the fallback resolves
    # through `providers` exactly as it did before this role had an endpoint.
    primary = LiteLlmCompleter(
        role_binding.model, providers, base_url=role_binding.base_url,
        log=log, **request_settings,
    )
    fallback = (
        LiteLlmCompleter(
            role_binding.fallback, providers,
            base_url=role_binding.fallback_base_url,
            log=log, **request_settings,
        )
        if role_binding.fallback is not None
        else None
    )
    if log is not None:
        log(
            "llm.bound",
            model=role_binding.model,
            fallback=role_binding.fallback,
            base_url=primary.api_base,
            fallback_base_url=fallback.api_base if fallback is not None else None,
            timeout_seconds=primary.timeout_seconds,
            num_ctx=primary.num_ctx,
        )
    return FallbackLlm(primary, fallback, log=log)
