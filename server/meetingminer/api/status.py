"""GET /status — read-only aggregate health of every dependency (SPEC-system-status).

One endpoint reports what the product needs to work: the three stores, the
api itself, every ``llm.roles.*`` binding with its key state, and the worker
with its job backlog. The UI polls it (CAP-1), so two constraints shape the
module:

* **Health checks are free.** Key validity is probed against each provider's
  free model-list endpoint (never a completion), and probe results are cached
  for :data:`PROBE_TTL_SECONDS` so UI polling cannot hammer a provider or
  spend money. Store checks are a ``SELECT 1``, a TCP connect, and a
  ``/health`` GET — all free.
* **Secrets never serialize.** The payload is built field by explicit field
  below; no ``Settings``/``Secrets`` object is ever serialized, and no
  fragment of any key or password appears in any response.

Read-only throughout: nothing here mutates anything, and nothing on this path
touches the worker — its state is observed through the Postgres advisory lock
``worker/main.py`` holds, never through a start/restart/resume. The stated
remediation is always the file contract: edit ``.env`` / ``config.yaml`` and
restart the affected process.

Copy contract (CAP-3): a failing binding is named ``llm.roles.<role>`` —
exactly the style the chat panel's 503 problems use (``api/chat.py``: "the
configured `llm.roles.chat` binding") — so the in-flow error and this surface
tell one story.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from meetingminer.adapters.llm.litellm import _BARE_OPENAI_PREFIXES
from meetingminer.config import AppConfig

router = APIRouter()

# How long one provider probe result answers for. Sized well above the UI's
# poll interval (15s — `web/src/features/status/status.ts`) so steady polling
# re-probes each provider about once a minute, not once a tick.
PROBE_TTL_SECONDS = 60.0

# One network probe may not stall the whole status response for long: a hung
# provider must read as unreachable, not hang the surface that reports it.
PROBE_TIMEOUT_SECONDS = 3.0

# The env var each provider's key comes from (`config.py` `_load_secrets`).
# Also the allowlist of providers that need a key at all: `ollama` is local
# and keyless, and an unknown provider prefix gets no key opinion here.
KEY_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

# Hook for tests: frozen time makes the cache window assertable.
_now = time.monotonic

State = Literal["ok", "degraded"]
KeyState = Literal["present", "missing", "invalid", "not-required"]


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ComponentStatus(_CamelModel):
    """One dependency row: what it is, whether it works, what to do (CAP-2)."""

    id: str
    label: str
    state: State
    detail: str
    remediation: str | None = None


class LlmRoleStatus(_CamelModel):
    role: str
    model: str
    fallback: str | None = None
    provider: str | None = None
    key_state: KeyState
    state: State
    detail: str
    remediation: str | None = None


class WorkerStatus(_CamelModel):
    state: Literal["running", "stopped", "unknown"]
    # Jobs by status (`queued`/`running`/`done`/`failed`), from the job table.
    jobs: dict[str, int]
    # Unfinished stages of live jobs, by stage name — where the backlog sits.
    stage_backlog: dict[str, int]
    detail: str
    remediation: str | None = None


class StatusResponse(_CamelModel):
    generated_at: datetime
    overall: State
    api: ComponentStatus
    stores: list[ComponentStatus]
    llm_roles: list[LlmRoleStatus]
    worker: WorkerStatus


# --- provider key probes (free endpoints only, cached) ---------------------


@dataclass(frozen=True)
class ProbeResult:
    state: Literal["ok", "invalid-key", "unreachable"]
    detail: str


# (provider, base_url) -> (monotonic timestamp, result). Keyed by endpoint,
# never by key material.
_PROBE_CACHE: dict[tuple[str, str], tuple[float, ProbeResult]] = {}


def provider_of(model: str) -> str | None:
    """The provider a model tag resolves through — `litellm.py`'s routing rules."""
    if "/" in model:
        return model.split("/", 1)[0]
    if model.startswith("claude-"):
        return "anthropic"
    if model.startswith(_BARE_OPENAI_PREFIXES):
        return "openai"
    return None


def _probe_provider(provider: str, base_url: str, api_key: str | None) -> ProbeResult:
    """One free HTTP probe of a provider endpoint. Never a completion.

    ``openai``/``openrouter``/``anthropic`` get their model-list endpoint with
    the key attached — a 401/403 is the provider saying the key is bad, which
    is the one fact a "key invalid" row must rest on. ``ollama`` gets its tags
    listing, keyless. Tests monkeypatch this function; nothing else in the
    module does network I/O for key validity.
    """
    if provider == "anthropic":
        url = f"{base_url.rstrip('/')}/v1/models"
        headers = {"x-api-key": api_key or "", "anthropic-version": "2023-06-01"}
    elif provider in ("openai", "openrouter"):
        url = f"{base_url.rstrip('/')}/models"
        headers = {"Authorization": f"Bearer {api_key or ''}"}
    elif provider == "ollama":
        url = f"{base_url.rstrip('/')}/api/tags"
        headers = {}
    else:
        return ProbeResult("ok", f"no probe defined for provider {provider!r}")
    try:
        response = httpx.get(url, headers=headers, timeout=PROBE_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        return ProbeResult("unreachable", f"{url} unreachable: {exc}")
    if response.status_code in (401, 403):
        return ProbeResult(
            "invalid-key", f"the provider refused the key (HTTP {response.status_code})"
        )
    if response.is_success:
        return ProbeResult("ok", "verified against the provider's free list endpoint")
    return ProbeResult(
        "unreachable", f"{url} answered HTTP {response.status_code}"
    )


def _cached_probe(provider: str, base_url: str, api_key: str | None) -> ProbeResult:
    """The probe, behind the poll-safe cache (SPEC constraint: free per tick)."""
    key = (provider, base_url)
    cached = _PROBE_CACHE.get(key)
    now = _now()
    if cached is not None and now - cached[0] < PROBE_TTL_SECONDS:
        return cached[1]
    result = _probe_provider(provider, base_url, api_key)
    _PROBE_CACHE[key] = (now, result)
    return result


# --- store liveness --------------------------------------------------------


def _check_postgres(request: Request) -> tuple[bool, str]:
    try:
        pool = request.app.state.pool
        with pool.connection() as conn:
            conn.execute("SELECT 1")
    except Exception as exc:  # any pool/connection failure means "down"
        return False, f"query failed: {exc}"
    return True, "answering queries"


def _check_neo4j(uri: str) -> tuple[bool, str]:
    """Bolt-port TCP liveness. No driver: `projections/` is the only module
    allowed to import the neo4j client (AD-4, test_projections_single_writer)."""
    parsed = urlparse(uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 7687
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT_SECONDS):
            pass
    except OSError as exc:
        return False, f"bolt port {host}:{port} unreachable: {exc}"
    return True, f"bolt port {host}:{port} accepting connections"


def _check_meilisearch(url: str) -> tuple[bool, str]:
    """`GET /health` liveness. Same single-writer reasoning: no client import."""
    health_url = f"{url.rstrip('/')}/health"
    try:
        response = httpx.get(health_url, timeout=PROBE_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        return False, f"{health_url} unreachable: {exc}"
    if not response.is_success:
        return False, f"{health_url} answered HTTP {response.status_code}"
    return True, "health endpoint answering"


_STORES_REMEDIATION = (
    "start the data stores with `make infra-up` (Docker), then re-check;"
    " the api needs no restart for a store coming back"
)


def _store_row(store_id: str, label: str, up: bool, detail: str) -> ComponentStatus:
    return ComponentStatus(
        id=store_id,
        label=label,
        state="ok" if up else "degraded",
        detail=detail,
        remediation=None if up else _STORES_REMEDIATION,
    )


# --- llm role rows ---------------------------------------------------------


def _role_row(
    role: str,
    model: str,
    fallback: str | None,
    base_url_override: str | None,
    config: AppConfig,
) -> LlmRoleStatus:
    """Health of one ``llm.roles.<role>`` binding, remediation included.

    The key itself never appears — only which env var is missing or invalid.
    """
    provider = provider_of(model)
    binding = f"`llm.roles.{role}` ({model})"
    provider_conf = config.settings.providers.get(provider) if provider else None
    base_url = base_url_override or (
        provider_conf.base_url if provider_conf is not None else None
    )

    if provider is None or base_url is None:
        # LiteLLM's own routing would answer this; without an endpoint there
        # is nothing free to probe, so say so rather than guess.
        return LlmRoleStatus(
            role=role,
            model=model,
            fallback=fallback,
            provider=provider,
            key_state="not-required",
            state="ok",
            detail=f"{binding}: no configured endpoint to probe; not checked",
        )

    env_var = KEY_ENV_VARS.get(provider)
    if env_var is None:
        # Keyless (local) provider: reachability is the whole health question.
        result = _cached_probe(provider, base_url, None)
        if result.state == "ok":
            return LlmRoleStatus(
                role=role, model=model, fallback=fallback, provider=provider,
                key_state="not-required", state="ok",
                detail=f"{binding}: endpoint {base_url} answering",
            )
        return LlmRoleStatus(
            role=role, model=model, fallback=fallback, provider=provider,
            key_state="not-required", state="degraded",
            detail=f"{binding}: {result.detail}",
            remediation=(
                f"check that the {provider} host at {base_url} is up and serving"
                f" this model, or edit the binding in config.yaml and restart"
                " the api and worker"
            ),
        )

    secrets = config.secrets
    api_key = {
        "anthropic": secrets.anthropic_api_key,
        "openai": secrets.openai_api_key,
        "openrouter": secrets.openrouter_api_key,
    }.get(provider)

    if api_key is None:
        return LlmRoleStatus(
            role=role, model=model, fallback=fallback, provider=provider,
            key_state="missing", state="degraded",
            detail=f"{binding}: {env_var} is not set, so every call on this"
            " binding will fail",
            remediation=f"set {env_var} in .env and restart the api (`make api`)",
        )

    result = _cached_probe(provider, base_url, api_key)
    if result.state == "invalid-key":
        return LlmRoleStatus(
            role=role, model=model, fallback=fallback, provider=provider,
            key_state="invalid", state="degraded",
            detail=f"{binding}: {env_var} is invalid — {result.detail}",
            remediation=(
                f"set a valid {env_var} in .env and restart the api"
                " (`make api`); until then requests on this binding fail"
            ),
        )
    if result.state == "unreachable":
        return LlmRoleStatus(
            role=role, model=model, fallback=fallback, provider=provider,
            key_state="present", state="degraded",
            detail=f"{binding}: key present but the endpoint could not be"
            f" verified — {result.detail}",
            remediation=f"check network access to {base_url}, then re-check",
        )
    return LlmRoleStatus(
        role=role, model=model, fallback=fallback, provider=provider,
        key_state="present", state="ok",
        detail=f"{binding}: key present and {result.detail}",
    )


# --- worker ----------------------------------------------------------------

# The exact advisory lock `worker/main.py` takes for its process lifetime.
# Postgres splits the bigint key into classid (high 32 bits) / objid (low 32
# bits) in pg_locks, so the comparison recomposes it the same way.
_WORKER_LOCK_HELD = """
SELECT EXISTS (
    SELECT 1
    FROM pg_locks
    WHERE locktype = 'advisory'
      AND granted
      -- pg_locks is cluster-wide; the worker holds its lock on the database
      -- the api shares with it, so only this database's locks count.
      AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
      AND classid = ((hashtext('meetingminer-worker')::bigint >> 32) & 4294967295)::oid
      AND objid = (hashtext('meetingminer-worker')::bigint & 4294967295)::oid
)
"""

_JOB_COUNTS = "SELECT status, count(*) FROM job GROUP BY status"

_STAGE_BACKLOG = (
    "SELECT s.name, count(*) FROM job_stage s"
    " JOIN job j ON j.id = s.job_id"
    " WHERE j.status IN ('queued', 'running')"
    "   AND s.status IN ('queued', 'running')"
    " GROUP BY s.name"
)

# Owner direction of record (2026-08-22): this row states facts and renders no
# cost verdict. It reports the current paused-work snapshot, the binding this
# API process loaded for the worker's one `llm.roles.*` call, and that a newly
# started worker reloads config.yaml. It predicts neither a successful startup
# nor that the API's snapshot and a future worker's snapshot match.
# The row used to derive paid-vs-free from the provider prefix and got it
# wrong in the dangerous direction: any prefix outside `KEY_ENV_VARS` rendered
# as keyless-and-therefore-costless, so `gemini/`, `azure/`, `bedrock/` and
# `groq/` all read as costing nothing. The judgement is removed rather than
# re-derived, and no provider classification happens in this function.
# The stopped worker is still deliberate, never a generic alarm, and never
# something this endpoint acts on.


def _worker_stopped_remediation(pending: int, config: AppConfig) -> str:
    """The current paused work and this API's loaded binding snapshot.

    Two snapshots, no prediction or verdict. ``pending`` is the paused work
    observed by this status request. ``llm.roles.extraction`` is the worker's
    only ``llm.roles.*`` call, but a newly started worker loads config.yaml for
    itself and may therefore see a different binding than this already-running
    API process. The fallback is named whenever one is configured:
    `adapters/llm/__init__.py` builds it as its own completer and engages it on
    any primary ``LlmError``.
    """
    extraction = config.settings.llm.roles.extraction
    paused = (
        "no work is currently paused"
        if pending == 0
        else f"{pending} job(s) are currently paused"
    )
    binding = f"`llm.roles.extraction` ({extraction.model})"
    if extraction.fallback is not None:
        binding += f" with `extraction.fallback` ({extraction.fallback})"
    return (
        f"leaving it stopped is the current deliberate state; {paused}."
        " For the worker's only `llm.roles.*` call,"
        f" this API process has loaded {binding}. A newly started worker"
        " reloads `config.yaml`, so its loaded binding may differ."
        " This page only reports; it never starts, restarts, or resumes anything."
    )


def _worker_status(
    request: Request, postgres_up: bool, config: AppConfig
) -> WorkerStatus:
    if not postgres_up:
        return WorkerStatus(
            state="unknown",
            jobs={},
            stage_backlog={},
            detail="worker state is read through Postgres, which is down",
            remediation=_STORES_REMEDIATION,
        )
    pool = request.app.state.pool
    with pool.connection() as conn:
        running = bool(conn.execute(_WORKER_LOCK_HELD).fetchone()[0])
        jobs = {row[0]: row[1] for row in conn.execute(_JOB_COUNTS).fetchall()}
        stage_backlog = {
            row[0]: row[1] for row in conn.execute(_STAGE_BACKLOG).fetchall()
        }
    pending = jobs.get("queued", 0) + jobs.get("running", 0)
    if running:
        return WorkerStatus(
            state="running",
            jobs=jobs,
            stage_backlog=stage_backlog,
            detail=f"worker is running; {pending} job(s) in flight or queued",
        )
    return WorkerStatus(
        state="stopped",
        jobs=jobs,
        stage_backlog=stage_backlog,
        detail=(
            f"worker is stopped — deliberately, with {pending} paused job(s)"
            " in the backlog"
        ),
        remediation=_worker_stopped_remediation(pending, config),
    )


# --- the endpoint ----------------------------------------------------------


@router.get("/status", operation_id="getSystemStatus", response_model=StatusResponse)
def get_status(request: Request) -> StatusResponse:
    """Aggregate current-state health. Read-only; mutates nothing anywhere."""
    config: AppConfig = request.app.state.config
    stores_conf = config.settings.stores

    pg_up, pg_detail = _check_postgres(request)
    neo4j_up, neo4j_detail = _check_neo4j(stores_conf.neo4j.uri)
    meili_up, meili_detail = _check_meilisearch(stores_conf.meilisearch.url)

    stores = [
        _store_row("postgres", "Postgres", pg_up, pg_detail),
        _store_row("neo4j", "Neo4j", neo4j_up, neo4j_detail),
        _store_row("meilisearch", "Meilisearch", meili_up, meili_detail),
    ]

    roles = config.settings.llm.roles
    llm_rows = [
        _role_row(name, binding.model, binding.fallback, binding.base_url, config)
        for name, binding in (
            ("extraction", roles.extraction),
            ("chat", roles.chat),
            ("judge", roles.judge),
        )
    ]

    worker = _worker_status(request, pg_up, config)

    api_row = ComponentStatus(
        id="api",
        label="api",
        state="ok",
        detail="this response came from the api, so it is up",
    )

    degraded = (
        any(row.state == "degraded" for row in stores)
        or any(row.state == "degraded" for row in llm_rows)
        # The stopped worker is a deliberate state, but the surface must not
        # read green while ingestion is paused (SPEC: no silent fallback) —
        # `unknown` (Postgres down) is already covered by the store row.
        or worker.state == "stopped"
    )
    return StatusResponse(
        generated_at=datetime.now(timezone.utc),
        overall="degraded" if degraded else "ok",
        api=api_row,
        stores=stores,
        llm_roles=llm_rows,
        worker=worker,
    )
