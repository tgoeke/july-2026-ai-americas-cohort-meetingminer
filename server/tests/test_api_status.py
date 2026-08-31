"""Contract tests for GET /status (SPEC-system-status).

Three non-negotiables from the frozen contract, each pinned here:

* the payload is an explicit allowlist that carries no key material — asserted
  against a config whose secrets are known fake strings;
* an invalid key surfaces as ``keyState: "invalid"`` with the binding named
  ``llm.roles.<role>`` (CAP-3's copy contract with the chat panel) and a
  concrete remediation (CAP-2);
* probe results are cached: a second request inside the cache window does not
  re-probe the provider, so UI polling stays free.

A fourth, added when the stopped-worker row stopped guessing at money: that row
states facts and renders no cost verdict, under every extraction binding.

Every provider probe is stubbed — no network I/O toward any provider, paid or
free, happens in this file. Store probes for Neo4j/Meilisearch are stubbed the
same way so the suite does not depend on which containers happen to be up;
Postgres is real (the per-run test database the ``client`` fixture owns).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Literal, NoReturn

import httpx
import psycopg
import pytest
from fastapi import Request
from psycopg_pool import ConnectionPool

import meetingminer.api.main as api_main
from meetingminer import db
from meetingminer.api import status as status_module
from meetingminer.api.status import ProbeResult
from meetingminer.config import AppConfig, ProviderEndpoint
from meetingminer.domain import model_selection

ORIGINAL_CHECK_NEO4J = status_module._check_neo4j
ORIGINAL_CHECK_MEILISEARCH = status_module._check_meilisearch

FAKE_SECRETS = {
    "anthropic_api_key": "sk-ant-FAKE-SECRET-anthropic-0000",
    "openai_api_key": "sk-FAKE-SECRET-openai-1111",
    "openrouter_api_key": "sk-or-FAKE-SECRET-openrouter-2222",
    "postgres_password": "FAKE-SECRET-postgres-3333",
    "neo4j_password": "FAKE-SECRET-neo4j-4444",
    "meili_master_key": "FAKE-SECRET-meili-5555",
}

RESPONSE_FIELDS = {
    "generatedAt", "overall", "observedBy", "api", "stores", "providers",
    "llmRoles", "worker",
}
COMPONENT_FIELDS = {"id", "label", "state", "detail", "remediation"}
ROLE_FIELDS = {
    "role", "model", "fallback", "provider", "keyState", "state", "detail",
    "remediation",
    # story 8.2a: the active binding beside the file default, and whose
    # reading this row is.
    "source", "defaultBinding", "fileBinding", "selected", "staleSelection",
    "staleReason", "observedBy", "servedBy", "attribution",
}
PROVIDER_FIELDS = {
    "provider", "keyState", "detail", "remediation", "state", "observedBy",
}
OBSERVED_BY_FIELDS = {
    "process", "configPath", "configLoadedAt", "catalogNote", "selectionNote",
}
WORKER_FIELDS = {"state", "jobs", "stageBacklog", "detail", "remediation"}

# The whole vocabulary of a cost claim, not one phrase of it. The row this
# guards once derived paid-vs-free from the provider prefix and failed open —
# every prefix outside `KEY_ENV_VARS` rendered as costing nothing — so what is
# pinned here is the absence of the judgement, not the wording of one version
# of it.
COST_VOCABULARY = ("spend", "paid", "free", "no money", "costs", "explicit yes")

# SPEC-system-status' read-only constraint, verbatim. Asserted in every branch
# that builds a worker remediation, not just one.
READ_ONLY_SENTENCE = (
    "This page only reports; it never starts, restarts, or resumes anything."
)


@pytest.fixture(autouse=True)
def _fresh_probe_cache():
    """Each test owns the module cache — cache behavior is itself under test."""
    status_module._PROBE_CACHE.clear()
    yield
    status_module._PROBE_CACHE.clear()


@pytest.fixture(autouse=True)
def _stores_up(monkeypatch: pytest.MonkeyPatch):
    """Neo4j/Meilisearch read as up without touching any real port."""
    monkeypatch.setattr(
        status_module, "_check_neo4j", lambda uri: (True, "stubbed up")
    )
    monkeypatch.setattr(
        status_module, "_check_meilisearch", lambda url: (True, "stubbed up")
    )


@pytest.fixture()
def fake_secret_config(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> AppConfig:
    """The committed config with every secret replaced by a known fake string,
    installed as the app's config for the duration of one test."""
    config = app_config.model_copy(
        update={"secrets": app_config.secrets.model_copy(update=FAKE_SECRETS)}
    )
    monkeypatch.setattr(api_main.app.state, "config", config)
    return config


def probe_stub(results: dict[str, ProbeResult], calls: list[tuple[str, str]]):
    def _probe(provider: str, base_url: str, api_key: str | None) -> ProbeResult:
        calls.append((provider, base_url))
        return results.get(provider, ProbeResult("ok", "stub ok"))

    return _probe


# --- the stopped-worker row ------------------------------------------------


def expected_worker_stopped_remediation(
    pending: int, model: str, fallback: str | None
) -> str:
    """The complete authored message, with identifiers inserted unchanged.

    Exact equality is intentional: a vocabulary list alone cannot reject an
    unlisted verdict such as "billable". Pinning all authored prose makes any
    added judgement fail while still allowing arbitrary configuration values.
    """
    paused = (
        "no work is currently paused"
        if pending == 0
        else f"{pending} job(s) are currently paused"
    )
    binding = f"`llm.roles.extraction` ({model})"
    if fallback is not None:
        binding += f" with `extraction.fallback` ({fallback})"
    return (
        f"leaving it stopped is the current deliberate state; {paused}."
        " For the worker's only `llm.roles.*` call,"
        f" this API process has loaded {binding}. A newly started worker"
        " reloads `config.yaml`, so its loaded binding may differ."
        f" {READ_ONLY_SENTENCE}"
    )


def assert_states_facts_without_a_cost_claim(
    remediation: str | None,
    *,
    pending: int,
    model: str,
    fallback: str | None,
) -> None:
    """The stopped-worker invariant, asserted identically in every case.

    The endpoint may report current paused work, which binding this API loaded,
    and that a new worker reloads config; it may not predict startup or say
    what that costs. The row stays non-null whatever the binding is — the
    indicator renders it (`status.test.tsx`) — and carries the read-only
    sentence verbatim.
    """
    assert remediation is not None, "a stopped worker must carry a remediation"
    assert remediation == expected_worker_stopped_remediation(
        pending, model, fallback
    )

    # Model identifiers are quoted configuration facts, not authored prose.
    # Remove their exact, unchanged values before applying the vocabulary ban.
    authored = remediation.replace(model, "<primary-model>")
    if fallback is not None:
        authored = authored.replace(fallback, "<fallback-model>")
    lowered = authored.lower()
    for word in COST_VOCABULARY:
        assert word not in lowered, (
            f"the worker remediation makes a cost claim ({word!r}): {remediation}"
        )


def bind_extraction(
    config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    fallback: str | None,
) -> AppConfig:
    """Install ``config`` with `llm.roles.extraction` rebound, and return it.

    Deep-copied first: ``app_config`` is session-scoped, so rebinding the role
    in place would leak the test's binding into every later test in the run.
    """
    rebound = config.model_copy(deep=True)
    roles = rebound.settings.llm.roles
    roles.extraction = roles.extraction.model_copy(
        update={"model": model, "fallback": fallback}
    )
    monkeypatch.setattr(api_main.app.state, "config", rebound)
    return rebound


def add_jobs(
    pool: ConnectionPool, count: int, status: Literal["queued", "running"]
) -> None:
    """Create jobs and stages in one paused-backlog status."""
    with pool.connection() as conn:
        for index in range(count):
            job_id = conn.execute(
                "INSERT INTO job (source_id, drop_path, corpus, status)"
                " VALUES (%s, %s, 'real', %s) RETURNING id",
                (
                    f"status-{status}-src-{index}",
                    f"/tmp/status-{status}-{index}",
                    status,
                ),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO job_stage (job_id, name, status)"
                " VALUES (%s, 'extract', %s)",
                (job_id, status),
            )


def remediation_must_not_be_built(pending: int, config: AppConfig) -> NoReturn:
    """Stand-in for the stopped-worker sentence where it must never be built.

    A raise rather than a sentinel string: the two cases that install this are
    about the branch not being *entered* at all, and a returned marker would
    still let a wrong branch pass its other assertions.
    """
    raise AssertionError(
        f"the stopped-worker remediation was built (pending={pending});"
        " this branch must not be entered"
    )


def postgres_down(request: Request) -> tuple[bool, str]:
    """`_check_postgres` for the store-is-down case: no real outage needed."""
    return False, "query failed: stubbed down"


def test_payload_is_an_allowlist_with_no_key_material(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, calls))

    response = client.get("/status")
    assert response.status_code == 200, response.text

    # No fragment of any secret — not the whole value, not a prefix long
    # enough to matter — appears anywhere in the serialized response.
    for secret in FAKE_SECRETS.values():
        assert secret not in response.text
        assert secret[:12] not in response.text

    body = response.json()
    assert set(body) == RESPONSE_FIELDS
    assert set(body["api"]) == COMPONENT_FIELDS
    assert {store["id"] for store in body["stores"]} == {
        "postgres", "neo4j", "meilisearch",
    }
    for store in body["stores"]:
        assert set(store) == COMPONENT_FIELDS
    assert {row["role"] for row in body["llmRoles"]} == {
        "extraction", "chat", "judge",
    }
    for row in body["llmRoles"]:
        assert set(row) == ROLE_FIELDS
    assert set(body["worker"]) == WORKER_FIELDS
    assert set(body["observedBy"]) == OBSERVED_BY_FIELDS
    for row in body["providers"]:
        assert set(row) == PROVIDER_FIELDS
    # Every provider `config.yaml` declares gets a row, not only the ones a
    # role happens to bind today (story 8.2a: "is my key good" is asked before
    # anything is selected).
    assert {row["provider"] for row in body["providers"]} == set(
        fake_secret_config.settings.providers
    )

    # The api row is trivially up: this response is the evidence.
    assert body["api"]["state"] == "ok"


def test_invalid_key_names_binding_and_remediation(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CAP-2 + CAP-3: the row states what is broken and what to do, naming the
    binding `llm.roles.chat` exactly the way the chat panel's 503 does."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        status_module,
        "_probe_provider",
        probe_stub(
            {"openai": ProbeResult("invalid-key", "the provider refused the key (HTTP 401)")},
            calls,
        ),
    )

    body = client.get("/status").json()
    chat = next(row for row in body["llmRoles"] if row["role"] == "chat")
    assert chat["keyState"] == "invalid"
    assert chat["state"] == "degraded"
    assert "`llm.roles.chat`" in chat["detail"]
    assert "OPENAI_API_KEY" in chat["detail"]
    assert "OPENAI_API_KEY" in chat["remediation"]
    assert ".env" in chat["remediation"]
    assert "restart the api" in chat["remediation"]
    # The committed chat binding has no fallback (owner decision of record).
    assert chat["fallback"] is None
    # One degraded row degrades the whole surface — no silent green.
    assert body["overall"] == "degraded"

    # judge shares the same binding style; the stub also marked it invalid.
    judge = next(row for row in body["llmRoles"] if row["role"] == "judge")
    assert judge["keyState"] == "invalid"
    assert "`llm.roles.judge`" in judge["detail"]


def test_missing_key_is_reported_without_probing(
    client, app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = app_config.model_copy(
        update={
            "secrets": app_config.secrets.model_copy(
                update={**FAKE_SECRETS, "openai_api_key": None}
            )
        }
    )
    monkeypatch.setattr(api_main.app.state, "config", config)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, calls))

    body = client.get("/status").json()
    chat = next(row for row in body["llmRoles"] if row["role"] == "chat")
    assert chat["keyState"] == "missing"
    assert chat["state"] == "degraded"
    assert "OPENAI_API_KEY" in chat["detail"]
    assert "set OPENAI_API_KEY in .env" in chat["remediation"]
    # A missing key is a fact, not something to probe: no openai probe ran.
    assert all(provider != "openai" for provider, _ in calls)


def test_probe_results_are_cached_between_polls(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second request inside PROBE_TTL_SECONDS re-probes nothing; once the
    window passes, each endpoint is probed exactly once more."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, calls))

    clock = {"now": 1000.0}
    monkeypatch.setattr(status_module, "_now", lambda: clock["now"])

    assert client.get("/status").status_code == 200
    first_round = list(calls)
    assert first_round, "expected the first request to probe at least one provider"

    # Second poll, one second later: entirely served from the cache.
    clock["now"] += 1.0
    assert client.get("/status").status_code == 200
    assert calls == first_round

    # Past the TTL: each cached endpoint is probed exactly once more.
    clock["now"] += status_module.PROBE_TTL_SECONDS
    assert client.get("/status").status_code == 200
    assert calls == first_round + first_round


def test_worker_stopped_with_an_empty_queue_reports_no_paused_work(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No worker runs during tests, so the advisory lock is free — and the
    ``client`` fixture truncates the job tables, so the backlog is genuinely
    empty. The sentence reports the observed queue, so an empty one must say
    no work is currently paused rather than predicting a future startup."""
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))
    extraction = fake_secret_config.settings.llm.roles.extraction

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert worker["jobs"] == {}
    assert "no work is currently paused" in worker["remediation"]
    assert f"`llm.roles.extraction` ({extraction.model})" in worker["remediation"]
    assert_states_facts_without_a_cost_claim(
        worker["remediation"],
        pending=0,
        model=extraction.model,
        fallback=extraction.fallback,
    )
    # A stopped pipeline is not a green surface, backlog or no backlog.
    assert body["overall"] == "degraded"


def test_worker_stopped_reports_the_work_currently_paused(
    client,
    fake_secret_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
    test_pool: ConnectionPool,
) -> None:
    """With work waiting, report the queue snapshot rather than predicting
    what a future worker start will claim or process."""
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))
    add_jobs(test_pool, 3, "queued")
    extraction = fake_secret_config.settings.llm.roles.extraction

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert worker["jobs"].get("queued") == 3
    assert worker["stageBacklog"].get("extract") == 3
    assert "3 paused job(s)" in worker["detail"]
    assert "3 job(s) are currently paused" in worker["remediation"]
    assert f"`llm.roles.extraction` ({extraction.model})" in worker["remediation"]
    assert_states_facts_without_a_cost_claim(
        worker["remediation"],
        pending=3,
        model=extraction.model,
        fallback=extraction.fallback,
    )
    assert body["overall"] == "degraded"


def test_worker_stopped_counts_orphaned_running_jobs_as_currently_paused(
    client,
    fake_secret_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
    test_pool: ConnectionPool,
) -> None:
    """Startup requeues crash-orphaned running jobs before claiming work.

    The paused-work snapshot must therefore include both queued and running
    rows. This mixed case fails if the remediation is fed only the queued count.
    """
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))
    add_jobs(test_pool, 2, "queued")
    add_jobs(test_pool, 1, "running")
    extraction = fake_secret_config.settings.llm.roles.extraction

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert worker["jobs"].get("queued") == 2
    assert worker["jobs"].get("running") == 1
    assert "3 job(s) are currently paused" in worker["remediation"]
    assert_states_facts_without_a_cost_claim(
        worker["remediation"],
        pending=3,
        model=extraction.model,
        fallback=extraction.fallback,
    )
    assert body["overall"] == "degraded"


def test_worker_stopped_on_a_key_required_binding_makes_no_cost_claim(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: an extraction role bound to a key-required provider
    once made this row emit a spend gate. The row names the binding and says
    nothing about money — the owner reading ``openai/gpt-5.2`` knows the rest."""
    bind_extraction(fake_secret_config, monkeypatch, "openai/gpt-5.2", None)
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert "`llm.roles.extraction` (openai/gpt-5.2)" in worker["remediation"]
    # No fallback configured, so none is named.
    assert "`extraction.fallback`" not in worker["remediation"]
    assert_states_facts_without_a_cost_claim(
        worker["remediation"],
        pending=0,
        model="openai/gpt-5.2",
        fallback=None,
    )
    assert body["overall"] == "degraded"


def test_worker_stopped_on_an_unrecognized_provider_makes_no_cost_claim(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect that ended the derived-cost approach: `KEY_ENV_VARS` answers
    "which env var holds this provider's key", and a prefix it does not carry
    got read as keyless — so `gemini/` rendered as costing nothing. Nothing in
    this row classifies a provider now, so an unknown prefix reads exactly like
    a known one."""
    bind_extraction(fake_secret_config, monkeypatch, "gemini/gemini-2.5-pro", None)
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert "`llm.roles.extraction` (gemini/gemini-2.5-pro)" in worker["remediation"]
    assert_states_facts_without_a_cost_claim(
        worker["remediation"],
        pending=0,
        model="gemini/gemini-2.5-pro",
        fallback=None,
    )
    assert body["overall"] == "degraded"


def test_worker_stopped_preserves_vocabulary_bearing_model_identifier(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The prose-only invariant never sanitizes configuration facts."""
    model = "openrouter/example:free"
    bind_extraction(fake_secret_config, monkeypatch, model, None)
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert f"`llm.roles.extraction` ({model})" in worker["remediation"]
    assert_states_facts_without_a_cost_claim(
        worker["remediation"], pending=0, model=model, fallback=None
    )
    assert body["overall"] == "degraded"


def test_worker_stopped_names_the_extraction_fallback_too(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`build_llm` engages `extraction.fallback` on any primary `LlmError`, so
    it is a binding a restarted worker can route to and the row names it. The
    pairing here is the second defect the derived-cost version missed: a local
    primary with a key-required fallback, which read as entirely local."""
    bind_extraction(
        fake_secret_config, monkeypatch, "ollama/gpt-oss:120b", "openai/gpt-5.2"
    )
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert (
        "`llm.roles.extraction` (ollama/gpt-oss:120b) with"
        " `extraction.fallback` (openai/gpt-5.2)" in worker["remediation"]
    )
    assert_states_facts_without_a_cost_claim(
        worker["remediation"],
        pending=0,
        model="ollama/gpt-oss:120b",
        fallback="openai/gpt-5.2",
    )
    assert body["overall"] == "degraded"


def test_worker_stopped_preserves_vocabulary_bearing_fallback_identifier(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fallback identifier stays exact even when it bears banned vocabulary.

    The explicit equality assertion is the sanitization regression guard: any
    rewrite of the fallback to remove ``free`` makes this endpoint case fail.
    """
    model = "ollama/gpt-oss:120b"
    fallback = "openrouter/example:free"
    bind_extraction(fake_secret_config, monkeypatch, model, fallback)
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "stopped"
    assert f"`extraction.fallback` ({fallback})" in worker["remediation"]
    assert_states_facts_without_a_cost_claim(
        worker["remediation"], pending=0, model=model, fallback=fallback
    )
    assert body["overall"] == "degraded"


def test_worker_running_builds_no_stopped_remediation(
    client,
    app_config: AppConfig,
    test_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the worker's own advisory lock held, the stopped branch must not be
    entered at all — the raise-only stub is what proves it, rather than an
    assertion on the message it would have produced.

    ``app_config`` rather than ``fake_secret_config``: this case opens its own
    Postgres connection to take the lock, and ``FAKE_SECRETS`` replaces
    ``postgres_password``, so a fake-secret config could not authenticate
    against the test database. The ``client`` fixture already installs
    ``app_config`` as the app's config, and this row reads no secrets.
    """
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))
    monkeypatch.setattr(
        status_module, "_worker_stopped_remediation", remediation_must_not_be_built
    )

    # The exact call `worker/main.py` `acquire_worker_lock` makes. `try` rather
    # than a blocking acquire: a lock leaked by an earlier run then fails this
    # test loudly instead of hanging the suite on it.
    with psycopg.connect(db.conninfo(app_config, database=test_database)) as conn:
        held = bool(
            conn.execute(
                "SELECT pg_try_advisory_lock(hashtext('meetingminer-worker'))"
            ).fetchone()[0]
        )
        assert held, "the worker advisory lock was already held on the test database"
        worker = client.get("/status").json()["worker"]

    assert worker["state"] == "running"
    assert worker["remediation"] is None


def test_postgres_down_reports_the_stores_remediation_not_the_stopped_one(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker state is read through Postgres, so with Postgres down there is no
    lock to read and no queue to count: the row says ``unknown`` and points at
    the stores. The stopped sentence has nothing to compose from and must not
    be built — the raise-only stub proves the branch is not entered."""
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))
    monkeypatch.setattr(status_module, "_check_postgres", postgres_down)
    monkeypatch.setattr(
        status_module, "_worker_stopped_remediation", remediation_must_not_be_built
    )

    body = client.get("/status").json()
    worker = body["worker"]
    assert worker["state"] == "unknown"
    assert worker["jobs"] == {}
    assert worker["remediation"] == status_module._STORES_REMEDIATION
    assert body["overall"] == "degraded"


# --- story 8.2a: providers[], the active binding, and whose view it is -----


# The disclaimer a role row must carry when the process that answered is not
# the process that makes the call. Pinned verbatim, like the stopped-worker
# sentence above and for the same reason: a vocabulary list cannot reject a
# rewrite that quietly starts speaking for both processes at once.
EXTRACTION_SNAPSHOT_DISCLAIMER = (
    "Read by the api process, which does not call `llm.roles.extraction` —"
    " the worker does, from its own `config.yaml` snapshot and its own"
    " resolution of the stored selection. This row is the api process's"
    " snapshot, not the worker's, and the two may disagree until both are"
    " restarted after a `config.yaml` edit."
)

# Distinctive enough that any six-character window of one is unmistakable in
# a payload: the key-material test asserts on windows, and a secret sharing a
# window with a provider name ("anthropic") could only be checked whole.
UNMISTAKABLE_SECRETS = {
    "anthropic_api_key": "sk-ant-api03-ANTQ7Z-9x8w7v6u5t4s3r2q1p",
    "openai_api_key": "sk-proj-OPNQ8Y-mnbvcxzlkjhgfdsapoiuy",
    "openrouter_api_key": "sk-or-v1-ORTR9X-1a2b3c4d5e6f7g8h9i",
    "postgres_password": "PGPW6V-qwertyuiopasdfghjk",
    "neo4j_password": "NEO5UX-zxcvbnmasdfghjklqwe",
    "meili_master_key": "MEI4TW-poiuytrewqlkjhgfd",
}

# Every path a completion could be reached by on the four configured
# providers. A probe URL containing any of these is a paid call, which the
# acceptance criterion forbids outright.
PAID_ENDPOINT_FRAGMENTS = (
    "completion", "chat/", "/messages", "/responses", "/generate",
    "/embeddings", "/embed",
)


@pytest.fixture()
def stored_selection(test_pool: ConnectionPool):
    """Write a role selection into ``app_setting``, and take it back out.

    ``app_setting`` is user-declared data, not evidence, so the ``client``
    fixture's truncation does not cover it — a selection left behind would be
    read as the binding in force by every later test in the session.
    """

    def _write(role: str, binding: str) -> None:
        with test_pool.connection() as conn:
            model_selection.write_selection(conn, role, binding)

    yield _write
    with test_pool.connection() as conn:
        conn.execute("DELETE FROM app_setting WHERE key LIKE 'llm.role.%'")


def unmistakable_secret_config(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch, **overrides: object
) -> AppConfig:
    """The committed config with window-checkable fake secrets installed."""
    config = app_config.model_copy(
        update={
            "secrets": app_config.secrets.model_copy(
                update={**UNMISTAKABLE_SECRETS, **overrides}
            )
        }
    )
    monkeypatch.setattr(api_main.app.state, "config", config)
    return config


def assert_no_key_fragment_serializes(text: str) -> None:
    """No window of any secret appears anywhere in the serialized response.

    Windows rather than whole values: the failure this guards against is a
    surface that "safely" prints a prefix or a masked tail, which is still key
    material and still enough to correlate against a leaked log.
    """
    for name, secret in UNMISTAKABLE_SECRETS.items():
        for start in range(len(secret) - 6 + 1):
            window = secret[start : start + 6]
            assert window not in text, (
                f"a {6}-character window of {name} ({window!r}) serialized"
            )


def test_probes_are_free_list_endpoints_and_never_a_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The acceptance criterion, asserted on the one function that does the I/O.

    Every other test in this file stubs ``_probe_provider``; this one exercises
    it, because "probed through free endpoints only (a model list, never a
    completion)" is a property of the URL it builds and the verb it reaches it
    with, and nothing above it can restore that property once it is lost.
    """
    seen: list[str] = []

    class _Response:
        status_code = 200
        is_success = True

    def _get(url: str, headers=None, timeout=None):
        seen.append(url)
        return _Response()

    def _refuse(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("a status probe issued a request that was not a GET")

    monkeypatch.setattr(status_module.httpx, "get", _get)
    monkeypatch.setattr(status_module.httpx, "post", _refuse)
    monkeypatch.setattr(status_module.httpx, "request", _refuse)

    status_module._probe_provider("anthropic", "https://api.anthropic.com", "k")
    status_module._probe_provider("openai", "https://api.openai.com/v1", "k")
    status_module._probe_provider("openrouter", "https://openrouter.ai/api/v1", "k")
    status_module._probe_provider("ollama", "http://localhost:11434", None)

    assert seen == [
        "https://api.anthropic.com/v1/models",
        "https://api.openai.com/v1/models",
        "https://openrouter.ai/api/v1/models",
        "http://localhost:11434/api/tags",
    ]
    for url in seen:
        for fragment in PAID_ENDPOINT_FRAGMENTS:
            assert fragment not in url, f"probe URL {url} reaches a paid endpoint"


def test_no_fragment_of_any_key_serializes_in_any_branch(
    client, app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Key material never serializes — on the healthy path or either failure.

    The three branches are the three that touch a key at all: a key that
    verifies, a key the provider refuses, and a key that is not set. Each is
    scanned whole, so a leak through a new field (`providers[]`, the
    attribution block) fails here rather than at a demo.
    """
    unmistakable_secret_config(app_config, monkeypatch)
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))
    assert_no_key_fragment_serializes(client.get("/status").text)

    status_module._PROBE_CACHE.clear()
    monkeypatch.setattr(
        status_module,
        "_probe_provider",
        probe_stub(
            {
                "openai": ProbeResult("invalid-key", "the provider refused the key (HTTP 401)"),
                "anthropic": ProbeResult("invalid-key", "the provider refused the key (HTTP 403)"),
            },
            [],
        ),
    )
    assert_no_key_fragment_serializes(client.get("/status").text)

    status_module._PROBE_CACHE.clear()
    unmistakable_secret_config(
        app_config, monkeypatch, openai_api_key=None, anthropic_api_key=None
    )
    assert_no_key_fragment_serializes(client.get("/status").text)


def test_failed_dependency_details_never_echo_secret_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Untrusted transport/store exceptions cannot become response prose."""
    secret = UNMISTAKABLE_SECRETS["openai_api_key"]

    def fail_http(*args: object, **kwargs: object) -> NoReturn:
        raise httpx.ConnectError(f"transport included Authorization: Bearer {secret}")

    monkeypatch.setattr(status_module.httpx, "get", fail_http)
    details = [
        status_module._probe_provider(
            "openai", "https://api.openai.com/v1", secret
        ).detail,
        ORIGINAL_CHECK_MEILISEARCH("http://localhost:7700")[1],
    ]

    class _Pool:
        def connection(self) -> NoReturn:
            raise RuntimeError(
                f"connection dsn contained password={UNMISTAKABLE_SECRETS['postgres_password']}"
            )

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(pool=_Pool()))
    )
    details.append(status_module._check_postgres(request)[1])

    def fail_socket(*args: object, **kwargs: object) -> NoReturn:
        raise OSError(
            f"authentication failed with {UNMISTAKABLE_SECRETS['neo4j_password']}"
        )

    monkeypatch.setattr(status_module.socket, "create_connection", fail_socket)
    details.append(ORIGINAL_CHECK_NEO4J("bolt://localhost:7687")[1])

    assert_no_key_fragment_serializes(" ".join(details))


def test_a_provider_without_a_free_probe_is_never_reported_healthy(
    fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unsupported provider health is unknown, never fabricated from no I/O."""
    config = fake_secret_config.model_copy(deep=True)
    config.settings.providers["gemini"] = ProviderEndpoint(
        base_url="https://generativelanguage.googleapis.com"
    )

    def refuse_network(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("an unsupported provider must not be probed")

    monkeypatch.setattr(status_module.httpx, "get", refuse_network)
    health = status_module._key_health(
        "gemini", config.settings.providers["gemini"].base_url, config
    )

    assert health.key_state == "unknown"
    assert health.state == "degraded"
    assert "no free probe is defined" in health.detail


def test_provider_rows_name_the_provider_and_its_remediation(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR39's first half: key validity per configured provider, with the fix.

    The row is about the *provider*, not a role — the question it answers is
    asked before anything is selected — so it names the env var and the
    processes that would have to be restarted, and it degrades the surface.
    """
    monkeypatch.setattr(
        status_module,
        "_probe_provider",
        probe_stub(
            {"openai": ProbeResult("invalid-key", "the provider refused the key (HTTP 401)")},
            [],
        ),
    )

    body = client.get("/status").json()
    openai_row = next(row for row in body["providers"] if row["provider"] == "openai")
    assert openai_row["keyState"] == "invalid"
    assert openai_row["state"] == "degraded"
    assert "OPENAI_API_KEY" in openai_row["detail"]
    assert "OPENAI_API_KEY" in openai_row["remediation"]
    assert ".env" in openai_row["remediation"]
    assert body["overall"] == "degraded"

    healthy = next(row for row in body["providers"] if row["provider"] == "anthropic")
    assert healthy["keyState"] == "present"
    assert healthy["state"] == "ok"
    assert healthy["remediation"] is None


def test_a_missing_key_reaches_the_provider_row_without_a_probe(
    client, app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing key is a fact about this process's `.env`, not a question to
    spend a request on — and the provider row must not probe it either."""
    unmistakable_secret_config(app_config, monkeypatch, openai_api_key=None)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, calls))

    body = client.get("/status").json()
    openai_row = next(row for row in body["providers"] if row["provider"] == "openai")
    assert openai_row["keyState"] == "missing"
    assert openai_row["state"] == "degraded"
    assert "OPENAI_API_KEY is not set" in openai_row["detail"]
    assert "this api process cannot call this provider" in openai_row["detail"]
    assert "every call" not in openai_row["detail"]
    assert all(provider != "openai" for provider, _ in calls)


def test_one_request_probes_each_endpoint_at_most_once(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`providers[]` and the role rows share the cache rather than doubling it.

    Both surfaces ask the same question of the same endpoints; polling must
    stay one free request per endpoint per TTL, not one per row.
    """
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, calls))

    assert client.get("/status").status_code == 200
    assert len(calls) == len(set(calls)), f"an endpoint was probed twice: {calls}"


def test_a_stored_selection_is_the_binding_reported_and_probed(
    client,
    fake_secret_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
    stored_selection,
) -> None:
    """FR39's second half: the *active* binding, resolved from story 8.2.

    The committed chat role defaults to `openai/gpt-5.2` and offers
    `ollama/gpt-oss:120b`. Selecting the second changes the provider, so a
    surface that reported the file's `model` would show the health of an
    endpoint no chat call is going to touch — the wrong-selection blindness
    this story exists to remove.
    """
    stored_selection("chat", "ollama/gpt-oss:120b")
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, calls))

    body = client.get("/status").json()
    chat = next(row for row in body["llmRoles"] if row["role"] == "chat")
    assert chat["model"] == "ollama/gpt-oss:120b"
    assert chat["provider"] == "ollama"
    assert chat["source"] == "selection"
    assert chat["selected"] == "ollama/gpt-oss:120b"
    assert chat["staleSelection"] is None
    # The file half travels beside the effective binding, never replaced by it.
    assert chat["defaultBinding"] == "openai/gpt-5.2"
    assert chat["fileBinding"] == fake_secret_config.settings.llm.roles.chat.model
    assert "`llm.roles.chat` (ollama/gpt-oss:120b)" in chat["detail"]
    # The endpoint probed is the selected binding's.
    ollama_base = fake_secret_config.settings.providers["ollama"].base_url
    assert ("ollama", ollama_base) in calls


def test_a_discarded_selection_is_named_and_degrades_the_role_row(
    client,
    fake_secret_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
    stored_selection,
) -> None:
    """A choice the catalog no longer offers is reported, never applied and
    never hidden — and the row is not green while the owner's choice is not
    the one in force (the story's own "a wrong selection is visible")."""
    stored_selection("chat", "openrouter/withdrawn-binding")
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))

    body = client.get("/status").json()
    chat = next(row for row in body["llmRoles"] if row["role"] == "chat")
    assert chat["source"] == "file-default"
    assert chat["model"] == "openai/gpt-5.2"
    assert chat["staleSelection"] == "openrouter/withdrawn-binding"
    assert "openrouter/withdrawn-binding" in chat["staleReason"]
    assert "openrouter/withdrawn-binding" in chat["detail"]
    assert chat["state"] == "degraded"
    assert "config.yaml" in chat["remediation"]
    assert body["overall"] == "degraded"


def test_an_unreadable_selection_is_never_reported_as_the_file_default(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With Postgres down the selection cannot be read, so the binding in force
    is unknown. Showing the file default as if it were in force would be the
    surface reporting a state it cannot support (AD-18)."""
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))
    monkeypatch.setattr(status_module, "_check_postgres", postgres_down)

    body = client.get("/status").json()
    chat = next(row for row in body["llmRoles"] if row["role"] == "chat")
    assert chat["source"] == "unknown"
    assert chat["state"] == "degraded"
    assert "could not be determined" in chat["detail"]
    assert "Postgres" in chat["remediation"]
    # The file half is still reported — it is what the file says, which is
    # true regardless of the store being reachable.
    assert chat["defaultBinding"] == "openai/gpt-5.2"


def test_the_judge_role_is_never_reported_as_selection_governed(
    client,
    fake_secret_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
    stored_selection,
) -> None:
    """`api/settings.py` refuses to persist a judge choice because the eval
    harness binds the file value directly. A row written by any other means
    must therefore never be shown as the binding in force."""
    stored_selection("judge", "ollama/gpt-oss:120b")
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))

    body = client.get("/status").json()
    judge = next(row for row in body["llmRoles"] if row["role"] == "judge")
    assert judge["source"] == "file-default"
    assert judge["model"] == "openai/gpt-5.2"
    assert judge["selected"] is None
    assert "does not adopt a stored selection" in judge["detail"]


def test_every_reading_is_attributed_to_the_process_that_answered(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The third criterion, and the 2026-08-31 incident it comes from.

    A config edit was followed by a worker restart and no api restart, and this
    endpoint reported local extraction from its stale snapshot while the worker
    was calling a paid provider. The catalog is a process-start snapshot and
    the two processes hold their own, so no row here may read as a statement
    about "the system": every row names the process that produced it, the role
    rows name the process that would actually make the call, and the row for a
    role this process does not call carries the disclaimer verbatim.
    """
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))

    body = client.get("/status").json()

    observed = body["observedBy"]
    assert observed["process"] == "api"
    assert observed["configPath"].endswith("config.yaml")
    assert observed["configLoadedAt"] is not None
    assert "loaded it at startup" in observed["catalogNote"]
    assert "restart the api and the worker together" in observed["selectionNote"]

    for row in body["llmRoles"] + body["providers"]:
        assert row["observedBy"] == "api"

    extraction = next(row for row in body["llmRoles"] if row["role"] == "extraction")
    assert extraction["servedBy"] == "worker"
    assert extraction["attribution"] == EXTRACTION_SNAPSHOT_DISCLAIMER
    assert "may disagree until both are restarted" in extraction["attribution"]

    chat = next(row for row in body["llmRoles"] if row["role"] == "chat")
    assert chat["servedBy"] == "api"
    assert "which is also the process that calls" in chat["attribution"]

    judge = next(row for row in body["llmRoles"] if row["role"] == "judge")
    assert judge["servedBy"] == "eval harness"
    assert "not the eval harness's" in judge["attribution"]


def test_no_wording_anywhere_speaks_for_the_whole_system(
    client, fake_secret_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wording rule from the third criterion, applied to the whole payload.

    A binding or health reading describes the process that answered. Phrases
    that assert a system-wide or worker-side state are exactly the ones that
    made the 2026-08-31 report false, so they are banned outright rather than
    reviewed case by case. Model identifiers are configuration facts and are
    removed before the ban applies, the way the worker row's guard does it.
    """
    monkeypatch.setattr(status_module, "_probe_provider", probe_stub({}, []))
    body = client.get("/status").json()

    banned = (
        "the system is",
        "the system uses",
        "the system will",
        "system-wide",
        "both processes are",
        "the worker is using",
        "the worker is bound",
        "the worker is calling",
    )
    prose: list[str] = [
        body["observedBy"]["catalogNote"],
        body["observedBy"]["selectionNote"],
    ]
    for row in body["llmRoles"]:
        prose += [row["detail"], row["attribution"], row["remediation"] or ""]
    for row in body["providers"]:
        prose += [row["detail"], row["remediation"] or ""]

    for sentence in prose:
        lowered = sentence.lower()
        for phrase in banned:
            assert phrase not in lowered, (
                f"a status sentence speaks for a process it cannot observe"
                f" ({phrase!r}): {sentence}"
            )
