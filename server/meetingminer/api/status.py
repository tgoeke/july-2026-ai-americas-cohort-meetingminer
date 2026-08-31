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

**Whose view this is** (story 8.2a, AD-10 as amended 2026-08-31, AD-18). The
two halves of a binding resolve on different clocks. The *catalog* and the
role bindings are a process-start snapshot — ``api/main.py`` holds
``CONFIG = _load_or_die()`` at module level — so a ``config.yaml`` edit reaches
this process only on restart. The *selection* is a per-request ``app_setting``
read (``domain/model_selection.py``), so it applies live, but each process
re-checks it against its own startup catalog and calls it through its own
loaded endpoint. Consequently this payload describes the **api process**, never
"the system": the worker holds an independent snapshot the api cannot observe.
That is not hypothetical — on 2026-08-31 a ``config.yaml`` edit was followed by
a worker restart and no api restart, and this endpoint reported local
extraction from its stale snapshot while the worker was calling a paid
provider. Reporting a state the system is not in is an AD-18 violation, so
every binding and key row carries ``observedBy``, every role row carries the
process that actually issues its calls (``servedBy``) and a sentence saying
what the reading covers, and the payload carries one ``observedBy`` block
naming the file this process loaded. No wording here may imply that one answer
covers both processes.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from meetingminer.config import AppConfig
from meetingminer.api.settings import SETTINGS_ROLE_POLICY
from meetingminer.domain import model_selection
from meetingminer.domain.model_providers import provider_for_model
from meetingminer.domain.model_selection import EffectiveBinding

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

#: How the binding a role is serving was arrived at. ``selection`` and
#: ``file-default`` are :mod:`~meetingminer.domain.model_selection`'s own two
#: sources; ``unknown`` is this surface's third, and exists because the
#: selection lives in Postgres: when Postgres is down the api cannot read what
#: is stored, and saying "the file default is in force" would be a claim it
#: cannot support (AD-18).
RoleBindingSource = Literal["selection", "file-default", "unknown"]

# --- whose view this is (AD-10 as amended 2026-08-31, AD-18) ---------------

#: The process that answered the request. Every binding, endpoint and key
#: state in this payload is *this* process's reading; none of it describes the
#: worker, and none of it describes "the system".
OBSERVING_PROCESS = "api"

#: Which process issues each role's LLM calls. ``extraction`` is the worker's
#: only ``llm.roles.*`` call, ``chat`` is the api's own, and ``judge`` is bound
#: by the eval harness in the process ``make evals-run`` starts. A role whose
#: caller is not :data:`OBSERVING_PROCESS` cannot be reported as the binding in
#: use — only as this process's snapshot of a file both processes read
#: separately. A role absent from this table gets no claim about any process.
ROLE_CALLERS: dict[str, str] = {
    "extraction": "worker",
    "chat": "api",
    "judge": "eval harness",
}

CATALOG_IS_THIS_PROCESS_SNAPSHOT = (
    "Every binding, endpoint and key state below is the api process's own"
    " reading. The role bindings, the catalog and the provider endpoints are"
    " `config.yaml` as this process loaded it at startup, so an edit to that"
    " file reaches this process only when it is restarted."
)

SELECTION_IS_LIVE_BUT_PER_PROCESS = (
    "A stored model selection is read from Postgres on every request, so it"
    " applies with no restart — but each process re-checks it against its own"
    " startup catalog and calls it through its own loaded endpoint. The worker"
    " holds a separate snapshot this api cannot observe, so after a"
    " `config.yaml` edit restart the api and the worker together; until then"
    " the two can be bound differently and this page speaks only for the api."
)


def _role_attribution(role: str) -> str:
    """What this row's reading covers, and what it does not.

    One sentence per role, and it never says "the system". When the observing
    process is also the calling process the row is authoritative for the next
    call; otherwise it is explicitly this process's snapshot and names the
    process that would actually make the call.
    """
    caller = ROLE_CALLERS.get(role)
    if caller == OBSERVING_PROCESS:
        return (
            f"Read by the {OBSERVING_PROCESS} process, which is also the"
            f" process that calls `llm.roles.{role}`: this is the binding the"
            f" next {role} call from this process uses."
        )
    if caller is None:
        return (
            f"Read by the {OBSERVING_PROCESS} process. Which process calls"
            f" `llm.roles.{role}` is not recorded here, so this row states the"
            f" {OBSERVING_PROCESS}'s snapshot and claims nothing about any"
            " other process."
        )
    return (
        f"Read by the {OBSERVING_PROCESS} process, which does not call"
        f" `llm.roles.{role}` — the {caller} does, from its own `config.yaml`"
        f" snapshot and its own resolution of the stored selection. This row is"
        f" the {OBSERVING_PROCESS} process's snapshot, not the {caller}'s, and"
        " the two disagree until both are restarted after a `config.yaml` edit."
    )


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ComponentStatus(_CamelModel):
    """One dependency row: what it is, whether it works, what to do (CAP-2)."""

    id: str
    label: str
    state: State
    detail: str
    remediation: str | None = None


class ProviderStatus(_CamelModel):
    """One configured provider's key validity (story 8.2a, FR39).

    The four fields the story names — ``provider``, ``keyState``, ``detail``,
    ``remediation`` — plus two that keep the row honest. ``state`` is carried
    rather than inferred from ``remediation is not None``: a reader that
    derives health from the presence of prose is one wording change away from
    reporting the wrong thing. ``observedBy`` names the process whose ``.env``
    and ``config.yaml`` snapshot produced the reading, because a key state is
    as process-local as a binding is (AD-10 as amended).

    Probed through the provider's free model-list endpoint only, behind the
    same cache the role rows use — never a completion, and never a second
    request for a provider a role already probed at the same endpoint.
    """

    provider: str
    key_state: KeyState
    detail: str
    remediation: str | None = None
    state: State
    observed_by: str = OBSERVING_PROCESS


class ObservedBy(_CamelModel):
    """Whose reading the whole payload is (AD-10 as amended, AD-18).

    Named once at the top so no consumer has to assemble the attribution from
    the rows, and so a surface that renders only a summary still has the one
    fact it may not omit: which process answered, and out of which file.
    """

    process: str
    #: The ``config.yaml`` this process loaded — the path, not its contents.
    config_path: str
    #: When this process took that snapshot. ``None`` only for an app that did
    #: not record it, which is never the shipped api.
    config_loaded_at: datetime | None = None
    catalog_note: str = CATALOG_IS_THIS_PROCESS_SNAPSHOT
    selection_note: str = SELECTION_IS_LIVE_BUT_PER_PROCESS


class LlmRoleStatus(_CamelModel):
    role: str
    #: The binding **in force** for this role as this process resolves it:
    #: the stored selection when one is in force, otherwise the file default.
    #: Not the file's ``model`` field, which travels separately as
    #: ``fileBinding`` — a selection may name a different provider entirely,
    #: and probing the file's model would report the health of a binding no
    #: call is going to use.
    model: str
    fallback: str | None = None
    provider: str | None = None
    key_state: KeyState
    state: State
    detail: str
    remediation: str | None = None
    # --- story 8.2a: the active binding beside the file default -----------
    source: RoleBindingSource
    #: What `config.yaml` says on its own, served beside the effective binding
    #: rather than in place of it — the same pairing `GET /settings/models`
    #: reports, so the two surfaces cannot disagree about the file half.
    default_binding: str
    file_binding: str
    #: What is stored for this role, whether or not it is still selectable.
    selected: str | None = None
    stale_selection: str | None = None
    stale_reason: str | None = None
    # --- story 8.2a: whose reading this row is ----------------------------
    observed_by: str = OBSERVING_PROCESS
    #: The process that actually issues this role's calls, when it is known.
    served_by: str | None = None
    attribution: str


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
    #: Attribution first: the rest of the payload is only meaningful once the
    #: reader knows which process produced it.
    observed_by: ObservedBy
    api: ComponentStatus
    stores: list[ComponentStatus]
    providers: list[ProviderStatus]
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


# Public within this module for the existing status tests, but deliberately an
# alias rather than a wrapper: config, call-time endpoint resolution, and this
# display surface execute the same function object and therefore the same rule.
provider_of = provider_for_model


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


# --- provider key health ---------------------------------------------------


@dataclass(frozen=True)
class _KeyHealth:
    """One provider endpoint's credential state, in provider terms only.

    Deliberately free of role framing so the provider rows and the role rows
    are the *same* decision rendered twice rather than two decisions that can
    drift. The key itself never appears — only which env var is missing or
    invalid, and what the free list endpoint answered.
    """

    key_state: KeyState
    state: State
    detail: str
    remediation: str | None


def _api_key(config: AppConfig, provider: str) -> str | None:
    """This process's loaded key for ``provider``. Never serialized anywhere."""
    secrets = config.secrets
    return {
        "anthropic": secrets.anthropic_api_key,
        "openai": secrets.openai_api_key,
        "openrouter": secrets.openrouter_api_key,
    }.get(provider)


def _key_health(
    provider: str | None, base_url: str | None, config: AppConfig
) -> _KeyHealth:
    """Is this provider's key usable at this endpoint, and if not, what to do.

    Both `.env` and `config.yaml` are read once per process, so every
    remediation names restarting the processes that read them rather than
    implying the fix lands live.
    """
    if provider is None or base_url is None:
        # LiteLLM's own routing would answer this; without an endpoint there
        # is nothing free to probe, so say so rather than guess.
        return _KeyHealth(
            "not-required", "ok", "no configured endpoint to probe; not checked", None
        )

    env_var = KEY_ENV_VARS.get(provider)
    if env_var is None:
        # Keyless (local) provider: reachability is the whole health question.
        result = _cached_probe(provider, base_url, None)
        if result.state == "ok":
            return _KeyHealth(
                "not-required", "ok", f"endpoint {base_url} answering", None
            )
        return _KeyHealth(
            "not-required",
            "degraded",
            result.detail,
            f"check that the {provider} host at {base_url} is up and serving"
            " this model, or edit the binding in config.yaml and restart"
            " the api and worker",
        )

    api_key = _api_key(config, provider)
    if api_key is None:
        # A missing key is a fact, not something to spend a request finding out.
        return _KeyHealth(
            "missing",
            "degraded",
            f"{env_var} is not set, so every call on this provider will fail",
            f"set {env_var} in .env and restart the api (`make api`); the"
            " worker reads .env for itself, so restart it too",
        )

    result = _cached_probe(provider, base_url, api_key)
    if result.state == "invalid-key":
        return _KeyHealth(
            "invalid",
            "degraded",
            f"{env_var} is invalid — {result.detail}",
            f"set a valid {env_var} in .env and restart the api (`make api`)"
            " and the worker; until then requests on this provider fail",
        )
    if result.state == "unreachable":
        return _KeyHealth(
            "present",
            "degraded",
            f"key present but the endpoint could not be verified — {result.detail}",
            f"check network access to {base_url}, then re-check",
        )
    return _KeyHealth("present", "ok", f"key present and {result.detail}", None)


def _provider_rows(config: AppConfig) -> list[ProviderStatus]:
    """Key validity for every provider ``config.yaml`` declares (story 8.2a).

    Every provider, in the file's own order — not only the ones a role happens
    to bind today, because the question this answers is "is my key good", asked
    before anything is selected. Each row costs at most one free list request
    per :data:`PROBE_TTL_SECONDS`, and a role probing the same endpoint shares
    the cache entry rather than making a second request.
    """
    return [
        ProviderStatus(
            provider=provider,
            key_state=health.key_state,
            detail=f"{provider} ({endpoint.base_url}): {health.detail}",
            remediation=health.remediation,
            state=health.state,
            observed_by=OBSERVING_PROCESS,
        )
        for provider, endpoint, health in (
            (name, endpoint, _key_health(name, endpoint.base_url, config))
            for name, endpoint in config.settings.providers.items()
        )
    ]


# --- llm role rows ---------------------------------------------------------

# The stores remediation, said for the one thing this surface loses when
# Postgres is down that is not a store row: the stored model selection.
_SELECTION_UNREADABLE_REMEDIATION = (
    "start the data stores with `make infra-up` (Docker), then re-check —"
    " the binding in force cannot be read while Postgres is down"
)


def _adopts_selection(role: str) -> bool:
    """Whether a stored selection actually governs this role's calls.

    Read from ``api/settings.py``'s single policy table rather than re-listed
    here. The judge role is declared file-only there because the eval harness
    still binds ``config.settings.llm.roles.judge`` directly, so reporting a
    persisted judge selection as effective would be false — the same reason
    ``GET /settings/models`` refuses to serve it.
    """
    return SETTINGS_ROLE_POLICY.get(role) is None


def _resolve_effective_bindings(
    request: Request, config: AppConfig, postgres_up: bool
) -> dict[str, EffectiveBinding | None]:
    """Each role's binding in force, or ``None`` when it cannot be read.

    ``None`` is not "no selection" — that is a resolved ``file-default``. It is
    "this process could not find out", which happens when Postgres is down, and
    it is reported as such rather than as the file default (AD-18).
    """
    roles = config.settings.llm.roles
    names = tuple(type(roles).model_fields)
    selectable = tuple(name for name in names if _adopts_selection(name))

    stored: dict[str, str] = {}
    if postgres_up and selectable:
        try:
            with request.app.state.pool.connection() as conn:
                stored = model_selection.read_selections(conn, selectable)
        except Exception:
            # The store row already reports why; this endpoint must not 500
            # because one of its readings is unavailable.
            return {name: None for name in names}

    resolved: dict[str, EffectiveBinding | None] = {}
    for name in names:
        role_binding = getattr(roles, name)
        if not _adopts_selection(name):
            # File-only role: resolved from the file alone, deliberately, so a
            # row that exists in `app_setting` is never shown as in force.
            resolved[name] = model_selection.resolve(name, role_binding, None)
        elif not postgres_up:
            resolved[name] = None
        else:
            resolved[name] = model_selection.resolve(
                name, role_binding, stored.get(name)
            )
    return resolved


def _source_clause(
    role: str, default: str, effective: EffectiveBinding | None
) -> str:
    """Why *this* binding, in one sentence, never blurring the two clocks."""
    if effective is None:
        return (
            " The binding in force could not be determined: the api could not"
            f" read the stored selection, so the config.yaml default ({default})"
            " is shown and may not be the binding the next call uses."
        )
    if effective.source == "selection":
        return (
            " In force by a stored selection, which applies with no restart;"
            f" the config.yaml default is {default}."
        )
    if effective.stale_selection is not None:
        return (
            f" In force by the config.yaml default ({default}) because"
            f" {effective.stale_reason}."
        )
    if not _adopts_selection(role):
        return (
            f" In force by the config.yaml default ({default}); this role does"
            " not adopt a stored selection —"
            f" {SETTINGS_ROLE_POLICY[role]}."
        )
    return (
        f" In force by the config.yaml default ({default}); no selection is"
        " stored for this role."
    )


def _role_row(
    role: str,
    role_binding: Any,
    effective: EffectiveBinding | None,
    config: AppConfig,
) -> LlmRoleStatus:
    """Health of the binding ``llm.roles.<role>`` is actually serving.

    The binding probed is the **effective** one — the stored selection when it
    is in force — because a selection may name a different provider than the
    file, and probing the file's model would report the health of a binding no
    call is going to use, which is the wrong-selection blindness story 8.2a
    exists to remove.

    The key itself never appears: only which env var is missing or invalid.
    """
    default = role_binding.default or role_binding.model
    if effective is None:
        model = default
        source: RoleBindingSource = "unknown"
        selected = stale_selection = stale_reason = None
    else:
        model = effective.binding
        source = effective.source
        selected = effective.selected
        stale_selection = effective.stale_selection
        stale_reason = effective.stale_reason

    provider = provider_of(model)
    provider_conf = config.settings.providers.get(provider) if provider else None
    # `bind()` keeps the role's own `base_url` when a selection replaces the
    # primary model, so the endpoint probed here is the endpoint the call
    # would use — role override first, provider entry second.
    base_url = role_binding.base_url or (
        provider_conf.base_url if provider_conf is not None else None
    )
    health = _key_health(provider, base_url, config)

    binding = f"`llm.roles.{role}` ({model})"
    detail = f"{binding}: {health.detail}.{_source_clause(role, default, effective)}"

    remediations = [health.remediation] if health.remediation else []
    if effective is None:
        remediations.append(_SELECTION_UNREADABLE_REMEDIATION)
    elif stale_selection is not None:
        remediations.append(
            f"choose a binding this role's catalog offers on the settings page,"
            f" or restore {stale_selection} to the `llm.roles.{role}` catalog in"
            " config.yaml and restart the api and worker"
        )

    # A row cannot read healthy while it cannot vouch for what is in force, and
    # a discarded selection is a state the owner has to see before asking
    # anything — both are `degraded` even when the key itself is fine.
    state: State = (
        "degraded"
        if health.state == "degraded" or effective is None or stale_selection
        else "ok"
    )

    return LlmRoleStatus(
        role=role,
        model=model,
        fallback=role_binding.fallback,
        provider=provider,
        key_state=health.key_state,
        state=state,
        detail=detail,
        remediation=" ".join(remediations) if remediations else None,
        source=source,
        default_binding=default,
        file_binding=role_binding.model,
        selected=selected,
        stale_selection=stale_selection,
        stale_reason=stale_reason,
        observed_by=OBSERVING_PROCESS,
        served_by=ROLE_CALLERS.get(role),
        attribution=_role_attribution(role),
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

    providers = _provider_rows(config)

    roles = config.settings.llm.roles
    effective = _resolve_effective_bindings(request, config, pg_up)
    llm_rows = [
        _role_row(name, binding, effective[name], config)
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
        or any(row.state == "degraded" for row in providers)
        or any(row.state == "degraded" for row in llm_rows)
        # The stopped worker is a deliberate state, but the surface must not
        # read green while ingestion is paused (SPEC: no silent fallback) —
        # `unknown` (Postgres down) is already covered by the store row.
        or worker.state == "stopped"
    )
    return StatusResponse(
        generated_at=datetime.now(timezone.utc),
        overall="degraded" if degraded else "ok",
        observed_by=ObservedBy(
            process=OBSERVING_PROCESS,
            config_path=str(config.config_path),
            config_loaded_at=getattr(request.app.state, "config_loaded_at", None),
        ),
        api=api_row,
        stores=stores,
        providers=providers,
        llm_roles=llm_rows,
        worker=worker,
    )
