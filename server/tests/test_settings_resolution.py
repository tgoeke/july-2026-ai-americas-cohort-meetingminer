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
from meetingminer.domain import model_selection
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


# --- the rule: which binding a role is actually served by --------------------


def _role(model: str, catalog: list[str], default: str | None = None, **extra: object):
    """One `llm.roles.<role>` block, built through the real loader model.

    Built rather than stubbed: the rule under test reads `catalog`, `default`
    and `model`, and story 8.1's validators are what guarantee their
    relationship. A hand-rolled stand-in could hold a combination the loader
    would have refused, and the rule would then be pinned against a state that
    cannot occur.
    """
    from meetingminer.config import LlmRoleBinding

    payload: dict[str, object] = {
        "model": model,
        "catalog": [{"binding": binding} for binding in catalog],
        **extra,
    }
    if default is not None:
        payload["default"] = default
    return LlmRoleBinding.model_validate(payload)


def test_with_no_selection_the_role_resolves_to_the_files_default() -> None:
    binding = _role(
        "ollama/gpt-oss:120b",
        ["ollama/gpt-oss:120b", "ollama/qwen3:30b"],
        default="ollama/qwen3:30b",
    )

    effective = model_selection.resolve("extraction", binding, selected=None)

    assert effective.binding == "ollama/qwen3:30b"
    assert effective.source == "file-default"
    assert effective.selected is None
    assert effective.stale_selection is None


def test_a_stored_selection_wins_over_the_files_default() -> None:
    binding = _role(
        "openai/gpt-5.2", ["openai/gpt-5.2", "anthropic/claude-sonnet-5"]
    )

    effective = model_selection.resolve(
        "chat", binding, selected="anthropic/claude-sonnet-5"
    )

    assert effective.binding == "anthropic/claude-sonnet-5"
    assert effective.source == "selection"
    assert effective.provider == "anthropic"


def test_the_provider_is_derived_by_the_one_shared_rule() -> None:
    """Never a second spelling table: whatever `provider_for_model` says, stands."""
    binding = _role("claude-sonnet-5", ["claude-sonnet-5"])

    effective = model_selection.resolve("chat", binding, selected=None)

    assert effective.provider == provider_for_model("claude-sonnet-5") == "anthropic"


def test_a_selection_outside_the_catalog_is_refused_on_write() -> None:
    binding = _role("openai/gpt-5.2", ["openai/gpt-5.2"])

    with pytest.raises(model_selection.SelectionNotInCatalogError) as caught:
        model_selection.check_selectable("chat", "openai/gpt-9", binding)

    message = str(caught.value)
    assert "chat" in message
    assert "openai/gpt-9" in message
    assert "openai/gpt-5.2" in message


def test_a_selection_the_catalog_no_longer_offers_is_discarded_on_read() -> None:
    """`config.yaml` can be edited under a stored selection.

    The stored pick is not applied and not hidden: the role falls back to the
    file's own default, and the discarded binding is reported so a surface can
    say what happened rather than showing a choice that is not in effect.
    """
    binding = _role("openai/gpt-5.2", ["openai/gpt-5.2"])

    effective = model_selection.resolve("chat", binding, selected="openai/gpt-4o")

    assert effective.binding == "openai/gpt-5.2"
    assert effective.source == "file-default"
    assert effective.stale_selection == "openai/gpt-4o"
    assert "openai/gpt-4o" in (effective.stale_reason or "")
    assert "catalog" in (effective.stale_reason or "")


def test_the_effective_binding_replaces_only_the_model_on_the_role() -> None:
    """The role's endpoint, timeout and context window still apply.

    `base_url` is declared as the endpoint for this role's *primary* model, and
    a selection replaces the primary. Dropping it would silently move the call
    to `providers.<prefix>.base_url` — a different host — which is exactly the
    kind of unannounced re-routing this story exists to remove.
    """
    binding = _role(
        "ollama/gpt-oss:120b",
        ["ollama/gpt-oss:120b", "ollama/qwen3:30b"],
        base_url="http://10.77.0.52:11434",
        timeout_seconds=900,
        num_ctx=65536,
        fallback="ollama/qwen3:30b",
    )

    applied = model_selection.bind(
        binding, model_selection.resolve("extraction", binding, "ollama/qwen3:30b")
    )

    assert applied.model == "ollama/qwen3:30b"
    assert applied.base_url == "http://10.77.0.52:11434"
    assert applied.timeout_seconds == 900
    assert applied.num_ctx == 65536
    assert applied.fallback == "ollama/qwen3:30b"
    # The configured object is never mutated: two requests in one process must
    # not see each other's selection.
    assert binding.model == "ollama/gpt-oss:120b"


# --- the worker resolves the selection per job ------------------------------


def _run_extract(
    pool: Any,
    app_config: Any,
    content_root: Any,
    drop_path: Any,
    job_id: Any,
    meeting_id: Any,
) -> None:
    """Run the `extract` stage once over an already-seeded meeting.

    The same shape `test_worker_extract.py` uses to put the stage in front of a
    prepared meeting without running the stages before it.
    """
    from meetingminer import logs
    from meetingminer.domain.drops import read_drop
    from meetingminer.pipeline.stage import StageContext
    from meetingminer.pipeline.stages import extract as extract_stage

    from conftest import DROPS_ROOT

    drop = read_drop(drop_path, config_path=app_config.config_path)
    with pool.connection() as conn:
        extract_stage.run(
            StageContext(
                conn=conn,
                config=app_config,
                job_id=job_id,
                meeting_id=meeting_id,
                drop=drop,
                content_root=content_root,
                drops_root=DROPS_ROOT,
                log=logs.bind(job_id=job_id, stage="extract"),
            )
        )
        conn.commit()


def test_the_worker_resolves_the_selection_on_every_job(
    test_pool: Any,
    app_config: Any,
    content_root: Any,
    make_drop: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A selection change takes effect on the next job, with no worker restart.

    The worker reads `app_setting` inside the job's own transaction, so a
    choice made while a job is queued is the choice that job runs on. A binding
    captured at worker start would pass the first run and fail the second.
    """
    from meetingminer.pipeline.stages import extract as extract_stage

    from conftest import FakeLlm, truncate_evidence
    from projection_seed import seed_meeting

    seen: list[str] = []

    def _build(role_binding: Any, *_a: Any, **_kw: Any) -> Any:
        seen.append(role_binding.model)
        return FakeLlm()

    monkeypatch.setattr(extract_stage, "build_llm", _build)

    truncate_evidence(test_pool)
    configured = app_config.settings.llm.roles.extraction
    alternatives = [
        entry.binding
        for entry in configured.catalog
        if entry.binding != configured.default
    ]
    if not alternatives:
        pytest.skip("`llm.roles.extraction` declares a one-entry catalog")
    chosen = alternatives[0]

    with test_pool.connection() as conn:
        conn.execute("DELETE FROM app_setting")
        first = seed_meeting(conn, source_id="settings-selection-worker-1")
        second = seed_meeting(conn, source_id="settings-selection-worker-2")
        conn.commit()

    drop = make_drop()
    _run_extract(
        test_pool, app_config, content_root, drop, first.job_id, first.meeting_id
    )

    with test_pool.connection() as conn:
        model_selection.write_selection(conn, "extraction", chosen)
        conn.commit()

    _run_extract(
        test_pool, app_config, content_root, drop, second.job_id, second.meeting_id
    )

    assert seen == [configured.default, chosen]

    with test_pool.connection() as conn:
        conn.execute("DELETE FROM app_setting")
        conn.commit()
