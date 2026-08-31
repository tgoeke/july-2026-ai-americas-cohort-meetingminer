"""The per-role model catalog `config.yaml` declares (story 8.1, FR38, AD-10).

Every case in the story's I/O matrix: the back-compat synthesis a file written
before the catalog existed still gets, the authored-catalog path, and the
refusals the loader raises by name.

Two of those refusals are the story's headline rules — a `default` outside its
own catalog, and a catalog entry whose provider `providers:` does not declare.
Provider identity is never authored beside a binding. It is derived from the
same dependency-neutral spelling rule the runtime adapter uses; known bare
OpenAI and Anthropic spellings therefore agree at load and call time, while an
ambiguous bare spelling is refused by name. Synthesized entries retain the
authored-entry provider-declaration exemption only for backward-compatible
prefixed tags whose provider is absent from ``providers:``.

Nothing here calls a model; the catalog is declaration only until story 8.2
resolves a selection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from meetingminer.adapters.llm.litellm import resolve_api_base
from meetingminer.config import ConfigError, load_config

from repo_paths import REPO_ROOT


@pytest.fixture()
def no_env(tmp_path: Path) -> Path:
    """An env-file path that does not exist, so only config.yaml is under test."""
    return tmp_path / "absent.env"


def committed_raw() -> dict[str, Any]:
    """The committed `config.yaml` as a plain mapping, for mutation per case.

    Anchoring on the real file rather than a fixture copy keeps these cases
    honest: a role block that stops matching the shipped one fails here.
    """
    raw = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def write_with_chat_role(tmp_path: Path, chat: dict[str, Any]) -> Path:
    """The committed config with `llm.roles.chat` replaced by ``chat``."""
    raw = committed_raw()
    raw["llm"]["roles"]["chat"] = chat
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def test_committed_config_declares_a_catalog_for_every_role(no_env: Path) -> None:
    settings = load_config(REPO_ROOT / "config.yaml", no_env).settings
    roles = settings.llm.roles
    for name in ("extraction", "chat", "judge"):
        binding = getattr(roles, name)
        assert binding.catalog, f"llm.roles.{name} declares no catalog entries"
        for entry in binding.catalog:
            assert entry.provider in settings.providers, (
                f"llm.roles.{name} entry {entry.binding} names undeclared provider "
                f"{entry.provider}"
            )
        catalog_bindings = [entry.binding for entry in binding.catalog]
        assert binding.default in catalog_bindings
        assert binding.model in catalog_bindings


def test_legacy_prefixed_model_becomes_a_one_entry_catalog(
    tmp_path: Path, no_env: Path
) -> None:
    path = write_with_chat_role(tmp_path, {"model": "openai/gpt-5.2"})

    chat = load_config(path, no_env).settings.llm.roles.chat

    assert len(chat.catalog) == 1
    entry = chat.catalog[0]
    assert entry.binding == "openai/gpt-5.2"
    assert entry.label == "openai/gpt-5.2"
    # The frozen I/O matrix requires derivable provider metadata even on the
    # synthesized compatibility projection. Its synthesized marker, rather
    # than a missing provider, exempts it from the new declared-provider rule.
    assert entry.provider == "openai"
    assert chat.default == "openai/gpt-5.2"
    assert chat.model == "openai/gpt-5.2"


def test_legacy_model_naming_an_undeclared_provider_still_loads(
    tmp_path: Path, no_env: Path
) -> None:
    """Back-compat beats the new refusal for a role that authored no catalog.

    A role bound to a tag whose prefix `providers:` never declared loads today
    — `resolve_api_base` returns no `api_base` and LiteLLM uses its own default
    — so this story may not start refusing it. The same rule is what keeps
    `test_failfast.py`'s embedder gate reachable with `providers.ollama`
    removed: a synthesized catalog asserts nothing about the provider map.
    """
    path = write_with_chat_role(tmp_path, {"model": "moonshot/kimi-k2"})

    chat = load_config(path, no_env).settings.llm.roles.chat

    assert [entry.binding for entry in chat.catalog] == ["moonshot/kimi-k2"]
    assert chat.catalog[0].provider == "moonshot"
    assert chat.default == "moonshot/kimi-k2"


def test_authored_provider_cannot_override_runtime_routing(
    tmp_path: Path, no_env: Path
) -> None:
    """The picker cannot claim Ollama while the call routes bare GPT to OpenAI."""
    path = write_with_chat_role(
        tmp_path,
        {
            "model": "gpt-4o",
            "catalog": [{"binding": "gpt-4o", "provider": "ollama"}],
            "default": "gpt-4o",
        },
    )

    with pytest.raises(ConfigError) as excinfo:
        load_config(path, no_env)

    message = str(excinfo.value)
    assert "provider" in message
    assert "extra" in message.lower()


def test_ambiguous_legacy_bare_tag_is_refused_by_name(
    tmp_path: Path, no_env: Path
) -> None:
    """The owner amended compatibility: an unknowable route may not load."""
    path = write_with_chat_role(tmp_path, {"model": "some-model"})

    with pytest.raises(ConfigError) as excinfo:
        load_config(path, no_env)

    message = str(excinfo.value)
    assert "some-model" in message
    assert "provider" in message


@pytest.mark.parametrize(
    ("model", "provider"),
    [("gpt-4o", "openai"), ("claude-sonnet-5", "anthropic")],
)
def test_known_bare_catalog_provider_matches_runtime_routing(
    tmp_path: Path, no_env: Path, model: str, provider: str
) -> None:
    path = write_with_chat_role(
        tmp_path,
        {"model": model, "catalog": [{"binding": model}], "default": model},
    )

    settings = load_config(path, no_env).settings
    entry = settings.llm.roles.chat.catalog[0]

    assert entry.provider == provider
    assert resolve_api_base(model, settings.providers) == settings.providers[provider].base_url


@pytest.mark.parametrize(
    ("model", "provider"),
    [("gpt-4o", "openai"), ("claude-sonnet-5", "anthropic")],
)
def test_known_bare_legacy_model_synthesizes_the_runtime_provider(
    tmp_path: Path, no_env: Path, model: str, provider: str
) -> None:
    path = write_with_chat_role(tmp_path, {"model": model})

    chat = load_config(path, no_env).settings.llm.roles.chat

    assert [entry.binding for entry in chat.catalog] == [model]
    assert chat.catalog[0].provider == provider
    assert chat.default == model


def test_authored_catalog_keeps_file_order_and_its_own_default(
    tmp_path: Path, no_env: Path
) -> None:
    path = write_with_chat_role(
        tmp_path,
        {
            "model": "openai/gpt-5.2",
            "catalog": [
                {"binding": "openai/gpt-5.2", "label": "GPT-5.2"},
                {"binding": "ollama/qwen3:30b", "label": "Qwen3 30B (local)"},
            ],
            "default": "ollama/qwen3:30b",
        },
    )

    chat = load_config(path, no_env).settings.llm.roles.chat

    assert [entry.binding for entry in chat.catalog] == [
        "openai/gpt-5.2",
        "ollama/qwen3:30b",
    ]
    assert [entry.label for entry in chat.catalog] == ["GPT-5.2", "Qwen3 30B (local)"]
    assert chat.default == "ollama/qwen3:30b"
    # The catalog is declaration only: nothing rebinds the role in 8.1.
    assert chat.model == "openai/gpt-5.2"


def test_default_outside_the_catalog_is_refused(tmp_path: Path, no_env: Path) -> None:
    path = write_with_chat_role(
        tmp_path,
        {
            "model": "openai/gpt-5.2",
            "catalog": [
                {"binding": "openai/gpt-5.2"},
                {"binding": "ollama/qwen3:30b"},
            ],
            "default": "openai/gpt-9",
        },
    )

    with pytest.raises(ConfigError) as excinfo:
        load_config(path, no_env)

    message = str(excinfo.value)
    assert "chat" in message
    assert "openai/gpt-9" in message
    assert "openai/gpt-5.2" in message
    assert "ollama/qwen3:30b" in message


def test_active_model_outside_an_authored_catalog_is_refused(
    tmp_path: Path, no_env: Path
) -> None:
    path = write_with_chat_role(
        tmp_path,
        {
            "model": "moonshot/kimi-k2",
            "catalog": [
                {"binding": "openai/gpt-5.2"},
                {"binding": "ollama/qwen3:30b"},
            ],
            "default": "openai/gpt-5.2",
        },
    )

    with pytest.raises(ConfigError) as excinfo:
        load_config(path, no_env)

    message = str(excinfo.value)
    assert "active model 'moonshot/kimi-k2'" in message
    assert "openai/gpt-5.2" in message
    assert "ollama/qwen3:30b" in message


def test_authored_empty_catalog_falls_out_of_the_default_rule(
    tmp_path: Path, no_env: Path
) -> None:
    path = write_with_chat_role(tmp_path, {"model": "openai/gpt-5.2", "catalog": []})

    with pytest.raises(ConfigError) as excinfo:
        load_config(path, no_env)

    assert "openai/gpt-5.2" in str(excinfo.value)


def test_entry_naming_an_undeclared_provider_is_refused(
    tmp_path: Path, no_env: Path
) -> None:
    path = write_with_chat_role(
        tmp_path,
        {
            "model": "openai/gpt-5.2",
            "catalog": [
                {"binding": "openai/gpt-5.2"},
                {"binding": "moonshot/kimi-k2"},
            ],
            "default": "openai/gpt-5.2",
        },
    )

    with pytest.raises(ConfigError) as excinfo:
        load_config(path, no_env)

    message = str(excinfo.value)
    assert "chat" in message
    assert "moonshot/kimi-k2" in message
    # Not just the substring inside the binding: the message must name the
    # provider as a provider, and list what the file does declare.
    assert "provider 'moonshot'" in message
    for declared in committed_raw()["providers"]:
        assert repr(declared) in message


def test_omitted_provider_is_derived_from_the_tag_prefix(
    tmp_path: Path, no_env: Path
) -> None:
    path = write_with_chat_role(
        tmp_path,
        {
            "model": "openai/gpt-5.2",
            "catalog": [
                {"binding": "openai/gpt-5.2"},
                {"binding": "ollama/qwen3:30b"},
            ],
            "default": "openai/gpt-5.2",
        },
    )

    chat = load_config(path, no_env).settings.llm.roles.chat

    assert [entry.provider for entry in chat.catalog] == ["openai", "ollama"]
    # An omitted label falls back to the binding, so a picker always has text.
    assert [entry.label for entry in chat.catalog] == [
        "openai/gpt-5.2",
        "ollama/qwen3:30b",
    ]


def test_derived_provider_is_checked_against_the_declared_set(
    tmp_path: Path, no_env: Path
) -> None:
    """Derivation states what the tag already says; it does not exempt the check."""
    path = write_with_chat_role(
        tmp_path,
        {
            "model": "openai/gpt-5.2",
            "catalog": [
                {"binding": "openai/gpt-5.2"},
                {"binding": "moonshot/kimi-k2"},
            ],
            "default": "openai/gpt-5.2",
        },
    )

    with pytest.raises(ConfigError) as excinfo:
        load_config(path, no_env)

    message = str(excinfo.value)
    assert "moonshot/kimi-k2" in message
    assert "provider 'moonshot'" in message
    for declared in committed_raw()["providers"]:
        assert repr(declared) in message


def test_authored_ambiguous_bare_entry_is_refused(
    tmp_path: Path, no_env: Path
) -> None:
    path = write_with_chat_role(
        tmp_path,
        {
            "model": "openai/gpt-5.2",
            "catalog": [
                {"binding": "openai/gpt-5.2"},
                {"binding": "some-model"},
            ],
            "default": "openai/gpt-5.2",
        },
    )

    with pytest.raises(ConfigError) as excinfo:
        load_config(path, no_env)

    message = str(excinfo.value)
    assert "chat" in message
    assert "some-model" in message
    assert "provider" in message
    assert "cannot determine" in message
