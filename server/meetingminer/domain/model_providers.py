"""The one rule that identifies which provider serves an LLM model binding.

This module is dependency-neutral so configuration, runtime adapters, and
status reporting cannot grow competing spelling tables. A ``<provider>/``
prefix identifies its provider directly; the common bare Anthropic and OpenAI
spellings retain the routing LiteLLM already used before catalogs existed.
Anything else is ambiguous and returns ``None`` for the caller to refuse or
handle explicitly.
"""

from __future__ import annotations

_ANTHROPIC = "anthropic"
_OPENAI = "openai"
_BARE_OPENAI_PREFIXES = ("gpt-4", "gpt-3.5", "chatgpt-", "o1", "o3", "o4")


def provider_for_model(model: str) -> str | None:
    """Return the provider named by a model spelling, or ``None`` if ambiguous."""
    if "/" in model:
        provider = model.split("/", 1)[0]
        return provider or None
    if model.startswith("claude-"):
        return _ANTHROPIC
    if model.startswith(_BARE_OPENAI_PREFIXES):
        return _OPENAI
    return None
