"""Story 8.2: how a persisted model selection resolves, and how it fails loudly.

Three concerns, one module, because they are one rule seen from three sides:

* **The rule** — `domain/model_selection.py`: which binding a role is actually
  served by, given the file's catalog and whatever the user last chose. Pure;
  no store, no api.
* **The call-time refusal** — a provider that does not serve the selected model
  is a *configuration* failure, not an outage. It gets its own port error,
  carries the provider, the endpoint and the model, and is the one `LlmError`
  the fallback composer must not absorb (backlog B-38, and the other half of
  this story's third acceptance clause).
* **The two resolution points** — chat re-reads the selection per request and
  the worker per job, plus the eval run's configuration snapshot, which records
  the effective binding beside the file value.

`litellm` is imported at module scope on purpose. The adapter imports it lazily
*inside* `complete`, so a test that triggered the first import would pay several
seconds in its call phase and trip `fast_budget`; paying it at collection keeps
every test here in the fast set, where this behaviour belongs.
"""

from __future__ import annotations

from dataclasses import dataclass

import litellm
import litellm.exceptions
import pytest

from meetingminer.adapters.llm import FallbackLlm, LiteLlmCompleter
from meetingminer.adapters.llm.port import (
    LlmError,
    LlmModelNotServedError,
    LlmReply,
    LlmUnavailableError,
)
from meetingminer.domain.model_providers import provider_for_model


@dataclass(frozen=True)
class _Endpoint:
    """Structural stand-in for `config.ProviderEndpoint` (only `base_url` is read)."""

    base_url: str


PROVIDERS = {
    "ollama": _Endpoint(base_url="http://10.77.0.52:11434"),
    "anthropic": _Endpoint(base_url="https://api.anthropic.com"),
}


class _RecordingLlm:
    """A completer that answers, and remembers whether it was ever asked."""

    def __init__(self, model: str = "ollama/qwen3:30b") -> None:
        self.model = model
        self.calls = 0

    def complete(self, prompt: str, options: object = None) -> LlmReply:
        self.calls += 1
        return LlmReply(text="the substitute answered", model=self.model)


class _RaisingLlm:
    """A completer that only ever fails, the way the port says it may."""

    def __init__(self, error: Exception, model: str = "ollama/gpt-oss:120b") -> None:
        self.model = model
        self._error = error

    def complete(self, prompt: str, options: object = None) -> LlmReply:
        raise self._error


def _not_found(model: str, provider: str, message: str) -> Exception:
    """The SDK's 404, as LiteLLM raises it for a model a host does not serve."""
    return litellm.exceptions.NotFoundError(
        message=message, model=model, llm_provider=provider
    )


# --- B-38: a provider that does not serve the model -------------------------


def test_a_model_the_provider_does_not_serve_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """404 from the host means the binding is wrong, not that the host is down.

    Before this story it fell through the adapter's generic `except Exception`
    and became a bare `LlmError` naming neither the provider nor the endpoint —
    which the fallback composer then absorbed by answering from another model.
    """

    def boom(**kwargs: object) -> object:
        raise _not_found(
            "ollama/qwen3:30b",
            "ollama",
            'model "qwen3:30b" not found, try pulling it first',
        )

    monkeypatch.setattr(litellm, "completion", boom)
    completer = LiteLlmCompleter("ollama/qwen3:30b", PROVIDERS)

    with pytest.raises(LlmModelNotServedError) as caught:
        completer.complete("anything")

    exc = caught.value
    assert str(exc).startswith(
        "provider 'ollama' at 'http://10.77.0.52:11434'"
        " does not serve model 'ollama/qwen3:30b'"
    )
    assert exc.provider == "ollama"
    assert exc.model == "ollama/qwen3:30b"
    assert exc.api_base == "http://10.77.0.52:11434"
    assert exc.upstream_status == 404


def test_the_refusal_names_the_provider_the_shared_spelling_rule_derives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider identity comes from `provider_for_model`, never from the SDK's guess.

    A bare `claude-*` tag routes to Anthropic by the one rule config, runtime
    and status all consume; the error must name that same provider so the
    operator checks the account the call actually used.
    """

    def boom(**kwargs: object) -> object:
        # The SDK is deliberately given a *different* provider name, so a test
        # that passed by echoing `llm_provider` would fail here.
        raise _not_found("claude-sonnet-5", "openai", "model not found")

    monkeypatch.setattr(litellm, "completion", boom)
    completer = LiteLlmCompleter("claude-sonnet-5", PROVIDERS)

    with pytest.raises(LlmModelNotServedError) as caught:
        completer.complete("anything")

    assert provider_for_model("claude-sonnet-5") == "anthropic"
    assert caught.value.provider == "anthropic"
    assert "'anthropic'" in str(caught.value)
    assert "https://api.anthropic.com" in str(caught.value)


def test_the_refusal_is_still_readable_with_no_configured_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No `providers:` entry means LiteLLM's own default endpoint answered.

    The sentence must still say *where* the call went rather than printing
    `None`, because "which endpoint" is half of what makes it actionable.
    """

    def boom(**kwargs: object) -> object:
        raise _not_found("openai/gpt-5.2", "openai", "model not found")

    monkeypatch.setattr(litellm, "completion", boom)
    completer = LiteLlmCompleter("openai/gpt-5.2", PROVIDERS)

    with pytest.raises(LlmModelNotServedError) as caught:
        completer.complete("anything")

    assert caught.value.api_base is None
    assert "does not serve model 'openai/gpt-5.2'" in str(caught.value)
    assert "None" not in str(caught.value)


def test_a_model_not_served_never_substitutes_another_model() -> None:
    """The owner's standing rule, pinned at the composer.

    `FallbackLlm` absorbs every `LlmError` by design. This one error is the
    exception: answering a wrong binding from a different model is the silent
    fallback this project has rejected.
    """
    fallback = _RecordingLlm()
    composer = FallbackLlm(
        _RaisingLlm(
            LlmModelNotServedError(
                "provider 'ollama' at 'http://10.77.0.52:11434'"
                " does not serve model 'ollama/gpt-oss:120b'",
                provider="ollama",
                model="ollama/gpt-oss:120b",
                api_base="http://10.77.0.52:11434",
                upstream_status=404,
            )
        ),
        fallback,
    )

    with pytest.raises(LlmModelNotServedError):
        composer.complete("anything")

    assert fallback.calls == 0, "the fallback must never answer a wrong binding"


def test_a_genuine_outage_still_engages_the_configured_fallback() -> None:
    """The deliberate fallback is unchanged: an unreachable host is not a wrong binding."""
    fallback = _RecordingLlm()
    composer = FallbackLlm(
        _RaisingLlm(LlmUnavailableError("host is not answering")), fallback
    )

    reply = composer.complete("anything")

    assert fallback.calls == 1
    assert reply.fallback_engaged is True
    assert reply.model == "ollama/qwen3:30b"


def test_the_new_error_is_still_an_llm_error_for_existing_callers() -> None:
    """Chat's `_complete` and the extract stage both catch `LlmError` today.

    Subclassing keeps them working — the refusal reaches an operator as a named
    failure rather than escaping the port as an unmapped exception.
    """
    assert issubclass(LlmModelNotServedError, LlmError)
