"""The LiteLLM-backed completer: the one module that imports `litellm` (AD-8).

The model string from ``config.yaml`` is passed through verbatim — LiteLLM's
own routing reads the provider prefix (``ollama/qwen3:32b``) or recognizes a
bare Anthropic id (``claude-sonnet-5``). What this module adds is the
``api_base``: resolved from ``providers.<prefix>.base_url`` when the model
string carries a known provider prefix, and from ``providers.anthropic`` for a
bare ``claude-*`` id, so the endpoint an answer comes from is always the one
``config.yaml`` declares (AD-10). Secrets stay in the environment —
``ANTHROPIC_API_KEY`` is read by LiteLLM itself, never by this code.

A role may also carry its own ``base_url``, ``timeout_seconds`` and
``num_ctx`` (``config.yaml`` ``llm.roles.<role>``), and a caller may override
the latter two per call through :class:`~meetingminer.adapters.llm.port.LlmOptions`.
``num_ctx`` is forwarded only to ``ollama/``-prefixed models: it is an Ollama
request parameter, and handing it to another provider would be an unknown key
on that provider's API.

``litellm`` is imported lazily, inside the call, because importing it costs
seconds: constructing a completer (which every worker start and every test
does) must not pay for a model call that may never happen.
"""

from __future__ import annotations

from typing import Callable, Mapping, Protocol

from meetingminer.adapters.llm.port import (
    LlmError,
    LlmOptions,
    LlmReply,
    LlmUnavailableError,
)
from meetingminer.domain.model_providers import provider_for_model

# One model call may legitimately think for a while over a long moment, but a
# hung provider must not hang the stage forever. Generous rather than tight:
# a timeout surfaces as LlmUnavailableError and engages the fallback.
DEFAULT_TIMEOUT_SECONDS = 120.0

# The one provider that takes `num_ctx`; matched on the model-string prefix.
_OLLAMA = "ollama"


class ProviderBinding(Protocol):
    """Structural stand-in for :class:`meetingminer.config.ProviderEndpoint`."""

    base_url: str


def resolve_api_base(
    model: str, providers: Mapping[str, ProviderBinding]
) -> str | None:
    """The configured endpoint for this model string, or ``None`` when unknown.

    A prefixed model (``ollama/qwen3:32b``) resolves through its prefix; the
    common bare Anthropic and OpenAI spellings resolve through their configured
    providers. Anything else gets no ``api_base`` and LiteLLM's own default for
    that provider — an unknown prefix is a routing question LiteLLM answers,
    not a config error this adapter invents.
    """
    provider_name = provider_for_model(model)
    provider = providers.get(provider_name) if provider_name is not None else None
    return provider.base_url if provider is not None else None


class LiteLlmCompleter:
    """One configured model behind the `Llm` port.

    Holds only the binding (model string, endpoint, timeout, context window);
    the SDK is touched on :meth:`complete` and nowhere earlier, so an
    unreachable host is discovered at call time — which is where the fallback
    composer in ``__init__.py`` is listening for it.

    ``base_url`` is the role's own endpoint override and wins over
    :func:`resolve_api_base`. ``providers.ollama.base_url`` is one value the
    embedder also resolves, so a role served by a different Ollama host has no
    other way to say so without moving the embedder with it.
    """

    def __init__(
        self,
        model: str,
        providers: Mapping[str, ProviderBinding],
        timeout_seconds: float | None = None,
        base_url: str | None = None,
        num_ctx: int | None = None,
        log: Callable[..., None] | None = None,
    ) -> None:
        self.model = model
        self.api_base = base_url or resolve_api_base(model, providers)
        # `None` means "the role declared none", which is the adapter default —
        # never "no timeout", which would let a hung provider hang the stage.
        self.timeout_seconds = (
            DEFAULT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        )
        self.num_ctx = num_ctx
        if num_ctx is not None and not model.startswith(f"{_OLLAMA}/") and log is not None:
            # `num_ctx` exists here to prevent a silently truncated transcript.
            # Dropping it silently because the provider would not understand it
            # is the same class of quiet loss, one layer down — so the drop is
            # named at bind time, where an operator reading the worker log sees
            # it before the first call rather than after a thin extraction run.
            log(
                "llm.num_ctx_ignored",
                model=model,
                num_ctx=num_ctx,
                reason=(
                    "num_ctx is an Ollama request parameter and this model is not"
                    " served through the ollama/ prefix; the provider's own"
                    " default context applies, which may truncate a long prompt"
                ),
            )

    def complete(self, prompt: str, options: LlmOptions | None = None) -> LlmReply:
        try:
            import litellm
        except ImportError as exc:
            # A broken install is a misconfiguration, not an outage: no
            # fallback model fixes an environment that cannot import the SDK,
            # so this is the base error, and it names the fix.
            raise LlmError(
                f"the litellm package is not importable: {exc} — reinstall the"
                " server dependencies (cd server && uv sync)"
            ) from exc

        timeout = self.timeout_seconds
        num_ctx = self.num_ctx
        if options is not None:
            if options.timeout_seconds is not None:
                timeout = options.timeout_seconds
            if options.num_ctx is not None:
                num_ctx = options.num_ctx
        extra: dict[str, object] = {}
        # `num_ctx` is an Ollama request parameter. Sending it to any other
        # provider would be an unknown key on that provider's API, so the
        # prefix — the same thing LiteLLM routes on — decides.
        if num_ctx is not None and self.model.startswith(f"{_OLLAMA}/"):
            extra["num_ctx"] = num_ctx

        try:
            response = litellm.completion(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                api_base=self.api_base,
                timeout=timeout,
                **extra,
            )
        except (
            litellm.exceptions.APIConnectionError,
            litellm.exceptions.Timeout,
            litellm.exceptions.ServiceUnavailableError,
            litellm.exceptions.InternalServerError,
            litellm.exceptions.RateLimitError,
            litellm.exceptions.AuthenticationError,
            litellm.exceptions.PermissionDeniedError,
        ) as exc:
            # The host is not answering (unreachable, timing out, refusing the
            # credentials) — the condition the configured fallback covers.
            raise LlmUnavailableError(
                f"model {self.model!r}"
                f"{f' at {self.api_base}' if self.api_base else ''}"
                f" is not answering: {type(exc).__name__}: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - every SDK failure maps to the port
            raise LlmError(
                f"model {self.model!r} failed: {type(exc).__name__}: {exc}"
            ) from exc

        # The broad except tuple is deliberate: a degenerate response (choices
        # None, dict-shaped members) raises TypeError/KeyError rather than
        # AttributeError/IndexError, and every shape failure must surface as
        # the port's error, never escape unmapped.
        try:
            text = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError, KeyError) as exc:
            raise LlmError(
                f"model {self.model!r} returned a response with no completion"
            ) from exc
        # Explicitly a non-empty *string*: some providers answer with content
        # blocks (a list), which must be refused here rather than handed to
        # the parser as if it were text.
        if not isinstance(text, str) or not text.strip():
            raise LlmError(f"model {self.model!r} answered with no usable text")
        # The model that actually answered, when the provider reports one —
        # this is what artifact provenance records.
        answered_by = getattr(response, "model", None) or self.model
        return LlmReply(text=text, model=answered_by, fallback_engaged=False)
